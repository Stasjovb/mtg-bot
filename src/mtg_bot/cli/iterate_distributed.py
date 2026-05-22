"""``mtg_bot iterate-distributed`` — unified distributed-iter launcher.

A single entrypoint for kicking off an iter_NNN cycle that does the
right thing every time:

1. Parse one TOML config + ``--<section>.<key>`` CLI overrides.
2. Register the cycle row in runs.db ``running`` BEFORE any other
   side effect, so the UI sees the cycle immediately.
3. Render a per-cycle ephemeral ``shards_config.json`` under
   ``training_progress/launches/<cycle_id>/`` so two concurrent
   launches can't trample each other.
4. Spawn ``mtg_bot iterate`` as a child subprocess (subprocess +
   wait, NOT execv -- the lifecycle ctx mgr MUST span the iterate
   run so signal / atexit finalisation always writes a terminal
   status to the DB).
5. On any exit path (normal, signal, exception, atexit), funnel
   through one ``_finalize_cycle(status)`` so the UI never lies.

Phase A scope: ``--cluster.local-only`` is the only supported
cluster mode. AWS fleet management lives in Phase B; setting
``cluster.local_only = false`` in the TOML fails loudly with a
"Phase B not yet implemented" message rather than silently
proceeding without workers.

Usage::

    mtg_bot iterate-distributed --config launches/iter_021.toml
    mtg_bot iterate-distributed --config launches/iter_021.toml \\
        --iter.nodes 800 --cluster.local-only

A minimal TOML looks like::

    [iter]
    target_iter = 21
    bootstrap_version = "v5"
    nodes = 200
    samples = 8
    games_per_iteration = 8000
    epochs = 4

    [cluster]
    local_only = true
    master_url = "http://desktop-j05412i:5198"
    mac_url = "http://greggs-macbook-pro:5198"

See :mod:`mtg_bot.launcher.config` for the full section schema.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional, Sequence
from urllib.parse import urljoin

from mtg_bot.cli.runs import lifecycle as _runs_lifecycle
from mtg_bot.launcher import ui_autostart as _ui_autostart
from mtg_bot.launcher.aws_fleet import FleetManager
from mtg_bot.launcher.config import (
    LaunchConfig,
    LaunchConfigError,
    load_config,
    parse_cli_overrides,
)
from mtg_bot.launcher.lifecycle import (
    cycle_lifecycle,
    spawn_iterate_subprocess,
)
from mtg_bot.launcher.state import (
    LaunchPaths,
    render_shards_config,
    write_aws_instances_json,
)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Worker heartbeat verification
# ---------------------------------------------------------------------------


class WorkerNotIdleError(RuntimeError):
    """A configured worker URL responded but its state is not IDLE.

    Carries the worker URL + observed state so the operator can act
    (kill the stale claim, restart the daemon, ...).
    """


def _http_get_json(
    url: str, *, timeout: float = 5.0,
) -> tuple[int, dict[str, Any]]:
    """GET ``url`` and return ``(status, parsed_json)``. Network
    errors propagate so the caller can route them to a clear
    actionable message."""
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8") or "{}"
        return resp.status, json.loads(raw)


def verify_worker_idle(worker_url: str) -> None:
    """GET ``<worker_url>/v2/heartbeat`` and assert state == IDLE.

    Raises :class:`WorkerNotIdleError` with an actionable message if
    the worker isn't reachable or isn't IDLE. The launcher refuses
    to dispatch a fresh cycle to a busy worker -- a half-drained
    eval from the previous cycle would race the new self-play.
    """
    hb_url = worker_url.rstrip("/") + "/v2/heartbeat"
    try:
        status, body = _http_get_json(hb_url)
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        raise WorkerNotIdleError(
            f"worker {worker_url}: heartbeat GET failed ({exc}); is "
            f"the daemon running? Check `mtg_bot worker_daemon` on "
            f"that machine.",
        ) from exc
    if status != 200:
        raise WorkerNotIdleError(
            f"worker {worker_url}: heartbeat returned HTTP {status}",
        )
    state = body.get("state")
    if state != "IDLE":
        raise WorkerNotIdleError(
            f"worker {worker_url}: state={state!r} (expected IDLE). "
            f"A previous cycle may still be draining; check the "
            f"worker's UI before launching.",
        )


def collect_worker_urls(
    cfg: LaunchConfig, *, require_nonempty: bool = True,
) -> list[str]:
    """Build the cluster-side worker URL list from the [cluster] section.

    Skips ``None`` entries (the TOML may omit a machine if only a
    subset of the cluster is participating).

    ``require_nonempty=True`` (the historical default) raises when no
    URLs are configured -- used by the local-only path where the
    cluster section IS the worker list. The AWS path passes
    ``require_nonempty=False`` because the FleetManager provides the
    URLs and cluster-side workers (master / mac / win10) are optional
    co-runners.
    """
    urls: list[str] = []
    for attr in ("master_url", "mac_url", "win10_url"):
        u = getattr(cfg.cluster, attr)
        if u:
            urls.append(u)
    if not urls and require_nonempty:
        raise LaunchConfigError(
            "[cluster]: no worker URLs configured. Set at least one "
            "of master_url / mac_url / win10_url in the TOML.",
        )
    return urls


# ---------------------------------------------------------------------------
# Iterate argv builder
# ---------------------------------------------------------------------------


def _build_iterate_argv(
    cfg: LaunchConfig,
    *,
    shards_config_path: Path,
    queue_url: str,
    deck_pool: Optional[Path],
    extra_iterate_args: list[str],
) -> list[str]:
    """Construct the ``mtg_bot iterate`` argv from the LaunchConfig.

    Hand-merges the [iter] section into the corresponding iterate
    flags. ``extra_iterate_args`` is appended at the end so the
    operator has a last-resort pass-through for flags the launcher
    doesn't model explicitly (e.g. ``--acceptance-threshold 0.0`` on
    a bootstrap run).
    """
    python = sys.executable
    argv: list[str] = [
        python, "-m", "mtg_bot.cli", "iterate",
        "--n-iterations", "1",
        "--nodes", str(cfg.iter.nodes),
        "--samples", str(cfg.iter.samples),
        "--games-per-iteration", str(cfg.iter.games_per_iteration),
        "--epochs", str(cfg.iter.epochs),
        "--architecture", cfg.iter.architecture,
        "--shards-config", str(shards_config_path),
        "--queue-url", queue_url,
    ]
    if cfg.iter.bootstrap_version:
        argv += ["--bootstrap-version", cfg.iter.bootstrap_version]
    if deck_pool is not None:
        argv += ["--deck-pool", str(deck_pool)]
    argv += list(extra_iterate_args)
    return argv


def _cycle_url(cfg: LaunchConfig) -> str:
    """Build the clickable URL for the cycle's UI card.

    Uses ``[ui].base_url`` -- defaults to the user's tailnet host
    (``http://desktop-j05412i:5103``) per the project's
    Tailscale-only link policy. Built via :func:`urllib.parse.urljoin`
    so a base_url with or without trailing slash works identically.
    """
    base = cfg.ui.base_url.rstrip("/") + "/"
    return urljoin(base, f"run/{cfg.cycle_id}")


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Construct the argparse parser. Exposed for tests."""
    parser = argparse.ArgumentParser(
        prog="mtg_bot iterate-distributed",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config", type=Path, default=None,
        help=(
            "Path to the launch TOML. Optional only if every section "
            "field has a default + every required field is supplied "
            "via --<section>.<key> CLI overrides."
        ),
    )
    parser.add_argument(
        "--progress-dir", type=Path, default=Path("training_progress"),
        help=(
            "Root for runs.db + per-cycle ephemeral dirs (default "
            "``training_progress/``). Per-cycle files land under "
            "<progress-dir>/launches/<cycle_id>/."
        ),
    )
    parser.add_argument(
        "--deck-pool", type=Path, default=None,
        help=(
            "Deck-pool path forwarded to ``mtg_bot iterate "
            "--deck-pool``. Required by iterate itself; the launcher "
            "doesn't validate it (iterate's own argparse does)."
        ),
    )
    parser.add_argument(
        "--queue-url", default=None,
        help=(
            "Coordinator URL forwarded to ``iterate --queue-url``. "
            "Defaults to ``http://<first_worker_host>:5099`` (the "
            "master typically hosts the coordinator)."
        ),
    )
    parser.add_argument(
        "--force-resume-from-failed-cycle", action="store_true",
        help=(
            "Suppress the 'cycle row already exists' guard when the "
            "existing row is in a non-restartable state. Reserved "
            "for future strict-mode behaviour; today the runs.client "
            "swallows conflicts as warnings."
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help=(
            "Resolve the config + render shards_config but do NOT "
            "spawn iterate. Prints the resolved argv to stdout. "
            "Useful for validating a TOML before a live launch."
        ),
    )
    parser.add_argument(
        "--skip-worker-verify", action="store_true",
        help=(
            "Skip the heartbeat IDLE check before launch. Use only "
            "when testing the launcher itself (no live workers) -- "
            "production launches should always verify."
        ),
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry. Returns iterate's exit code (or 1 on launcher
    error). ``argv`` defaults to ``sys.argv[1:]``.
    """
    if argv is None:
        argv = sys.argv[1:]
    argv = list(argv)

    # Split argv into argparse-known + override-style flags. Anything
    # of the shape ``--<section>.<key>[=value]`` is an override; the
    # rest goes to argparse.
    parser = build_parser()
    known, unknown = parser.parse_known_args(argv)

    # Split unknown into overrides (have a dot in the keypath) and
    # iterate-passthrough (anything else). Argparse-unrecognised
    # flags without a dot get forwarded to iterate verbatim.
    override_argv: list[str] = []
    iterate_passthrough: list[str] = []
    i = 0
    while i < len(unknown):
        token = unknown[i]
        if token.startswith("--") and "." in token.split("=", 1)[0][2:]:
            # Override token. Pull the value with it if separate.
            if "=" in token:
                override_argv.append(token)
                i += 1
            elif i + 1 < len(unknown) and not unknown[i + 1].startswith(
                "--",
            ):
                override_argv.append(token)
                override_argv.append(unknown[i + 1])
                i += 2
            else:
                override_argv.append(token)
                i += 1
        else:
            iterate_passthrough.append(token)
            i += 1

    try:
        overrides = parse_cli_overrides(override_argv)
        cfg = load_config(known.config, overrides=overrides)
    except LaunchConfigError as exc:
        print(f"[iterate-distributed] config error: {exc}", file=sys.stderr)
        return 2

    return _launch(
        cfg,
        progress_dir=known.progress_dir,
        deck_pool=known.deck_pool,
        queue_url=known.queue_url,
        force_resume_from_failed=known.force_resume_from_failed_cycle,
        dry_run=known.dry_run,
        skip_worker_verify=known.skip_worker_verify,
        iterate_passthrough=iterate_passthrough,
    )


def _launch(
    cfg: LaunchConfig,
    *,
    progress_dir: Path,
    deck_pool: Optional[Path],
    queue_url: Optional[str],
    force_resume_from_failed: bool,
    dry_run: bool,
    skip_worker_verify: bool,
    iterate_passthrough: list[str],
    spawn: Optional[Any] = None,
    fleet_factory: Optional[Any] = None,
) -> int:
    """Orchestrate the launch given a resolved LaunchConfig.

    Split out from :func:`main` so tests can drive the orchestrator
    directly without parsing argv.

    ``spawn`` is an injection point for the iterate subprocess
    factory; tests pass a stub that records argv + env without
    actually spawning. Default ``None`` resolves at call time to the
    module's ``spawn_iterate_subprocess`` so a
    ``monkeypatch.setattr(id_mod, 'spawn_iterate_subprocess', stub)``
    lands at runtime (function-default capture at import would
    freeze the original).

    ``fleet_factory`` is the injection point for the AWS spot-fleet
    manager. Defaults to :class:`FleetManager` (constructor) at
    call-time so tests can substitute a fake. Only consulted when
    ``cluster.local_only`` is False.
    """
    if spawn is None:
        # Late binding so monkeypatch on the module attribute wins.
        spawn = spawn_iterate_subprocess
    if fleet_factory is None:
        fleet_factory = FleetManager

    # ---- Per-cycle ephemeral dir up-front (FleetManager needs it
    #      to write aws_instances.json before launch_fleet returns).
    paths = LaunchPaths.for_cycle(progress_dir, cfg.cycle_id).ensure()

    # ---- Two paths: local_only (cluster URLs only) vs AWS
    #      (FleetManager + optional cluster URLs).
    cluster_urls = collect_worker_urls(
        cfg, require_nonempty=cfg.cluster.local_only,
    )
    fleet: Optional[Any] = None
    aws_urls: list[str] = []
    if not cfg.cluster.local_only:
        # AWS path: spin the fleet, register teardown hook (the
        # actual hook registration happens inside cycle_lifecycle
        # below so the hook fires on any exit path).
        fleet = fleet_factory(cfg.aws, paths)
        if not dry_run:
            instances = fleet.launch_fleet()
            aws_urls = fleet.wait_for_healthy(instances)
        # In dry-run we DON'T spin real instances -- print what
        # would happen and return without touching AWS at all.

    worker_urls = list(cluster_urls) + list(aws_urls)
    if not worker_urls and not dry_run:
        # Defensive: shouldn't trigger -- collect_worker_urls + the
        # AWS path between them should always produce at least one
        # URL -- but a misconfig (local_only=false + aws.count=0
        # bypassed somehow) would otherwise leave us with an empty
        # shards_config that iterate silently falls back from.
        raise LaunchConfigError(
            "no worker URLs available; cluster section is empty AND "
            "no AWS fleet was launched.",
        )

    # Resolve queue_url: caller's --queue-url wins; otherwise derive
    # from the first cluster URL (the master typically hosts the
    # coordinator). AWS-only mode requires --queue-url explicitly
    # because there's no canonical coordinator host in the fleet.
    if queue_url is None:
        if cluster_urls:
            from urllib.parse import urlparse
            parsed = urlparse(cluster_urls[0])
            if not parsed.hostname:
                raise LaunchConfigError(
                    f"could not derive coordinator URL from worker "
                    f"{cluster_urls[0]!r}; pass --queue-url explicitly.",
                )
            queue_url = f"http://{parsed.hostname}:5099"
        else:
            raise LaunchConfigError(
                "no cluster URL to derive --queue-url from (AWS-only "
                "fleet). Pass --queue-url explicitly.",
            )

    # Verify each cluster-side worker is reachable + IDLE before any
    # DB write. AWS instances have already been wait_for_healthy'd
    # above so they don't need a second round of IDLE checks.
    if not skip_worker_verify and not dry_run:
        for url in cluster_urls:
            verify_worker_idle(url)

    # Render shards_config (cluster URLs + AWS URLs in order). In
    # AWS dry-run mode the cluster URLs alone go in -- it's a
    # documentation of what iterate WOULD launch with.
    shards_input = worker_urls if worker_urls else cluster_urls
    if shards_input:
        shards_path = render_shards_config(
            shards_input, paths.shards_config_path,
        )
    else:
        # Dry-run + AWS-only + no cluster URLs: write a placeholder
        # so the dry-run print can reference SOMETHING.
        shards_path = paths.shards_config_path
    # Phase A wrote a stub aws_instances.json; the FleetManager
    # path overwrites with the real instance list. local_only path
    # still writes the stub for forensic completeness.
    if cfg.cluster.local_only:
        write_aws_instances_json(paths.aws_instances_path)

    # Build iterate argv.
    iterate_argv = _build_iterate_argv(
        cfg,
        shards_config_path=shards_path,
        queue_url=queue_url,
        deck_pool=deck_pool,
        extra_iterate_args=iterate_passthrough,
    )

    if dry_run:
        print(f"[iterate-distributed] cycle_id={cfg.cycle_id}")
        print(f"[iterate-distributed] shards_config={shards_path}")
        print(f"[iterate-distributed] queue_url={queue_url}")
        print(f"[iterate-distributed] mode="
              f"{'local_only' if cfg.cluster.local_only else 'aws'}")
        if not cfg.cluster.local_only:
            print(
                f"[iterate-distributed] aws_count={cfg.aws.count} "
                f"instance_type={cfg.aws.instance_type} "
                f"az_fallback={cfg.aws.az_fallback}",
            )
        print(f"[iterate-distributed] argv: {' '.join(iterate_argv)}")
        return 0

    # Env vars iterate needs (runs.db transport + progress dir).
    #
    # If neither MTG_BOT_RUN_DB_URL nor MTG_BOT_RUN_DB_PATH is set
    # in the caller's env, default URL transport pointing at the
    # coord (queue_url == http://<master>:5099). The coord owns the
    # canonical runs.db; without this default a worktree-launched
    # run silently writes to a worktree-local runs.db that the UI
    # never reads, leaving the cycle row stuck at its prior value
    # (observed live during iter_020 demo). Mutate os.environ here
    # so BOTH the launcher's own runs.client calls (cycle_lifecycle
    # below) AND the subprocess env (env.copy below) pick it up.
    if (
        "MTG_BOT_RUN_DB_URL" not in os.environ
        and "MTG_BOT_RUN_DB_PATH" not in os.environ
    ):
        os.environ["MTG_BOT_RUN_DB_URL"] = queue_url
    env = os.environ.copy()
    runs_db_path = (progress_dir / "runs.db").resolve()
    env.setdefault("MTG_BOT_RUN_DB_PATH", str(runs_db_path))

    # Phase C: best-effort training-UI auto-start.
    # Runs BEFORE the cycle is registered so when the lifecycle ctx
    # mgr enters and the UI gets its first row to render, the UI
    # is up and ready. The helper is best-effort: any failure logs
    # a warning and continues -- the launcher must NOT be coupled
    # to UI liveness. See `mtg_bot.launcher.ui_autostart`.
    if cfg.ui.auto_start_training_ui:
        try:
            _ui_autostart.ensure_training_ui(cfg.ui.base_url)
        except Exception:  # noqa: BLE001 - defence-in-depth
            # ensure_training_ui already catches its own errors, but
            # if a future change widens the throw surface, the
            # launcher still must not crash here.
            logger.exception(
                "[iterate-distributed] ui auto-start raised; "
                "continuing without UI.",
            )

    # Drive the lifecycle ctx mgr so the cycle row always lands
    # terminal in the DB, no matter how the iterate subprocess exits.
    config_dict = {
        "iter": {
            "target_iter": cfg.iter.target_iter,
            "nodes": cfg.iter.nodes,
            "samples": cfg.iter.samples,
            "games_per_iteration": cfg.iter.games_per_iteration,
            "epochs": cfg.iter.epochs,
            "architecture": cfg.iter.architecture,
            "bootstrap_version": cfg.iter.bootstrap_version,
        },
        "cluster": {
            "local_only": cfg.cluster.local_only,
            "master_url": cfg.cluster.master_url,
            "mac_url": cfg.cluster.mac_url,
            "win10_url": cfg.cluster.win10_url,
        },
        "aws": {
            "count": cfg.aws.count,
            "instance_type": cfg.aws.instance_type,
            "az_fallback": cfg.aws.az_fallback,
            "storage_uri": cfg.aws.storage_uri,
        },
        "ui": {
            "auto_start_training_ui": cfg.ui.auto_start_training_ui,
            "base_url": cfg.ui.base_url,
        },
    }

    with cycle_lifecycle(
        cfg.cycle_id,
        config=config_dict,
        git_commit=_runs_lifecycle.git_commit_short(),
        label=cfg.iter_label,
        force_resume_from_failed=force_resume_from_failed,
    ) as handle:
        # Register the AWS-fleet teardown hook on every exit path
        # BEFORE we run iterate. The hook fires inside _finalize
        # (lifecycle.py) prior to finish_run, so a launcher
        # KeyboardInterrupt / iterate crash / launcher process death
        # all still tear the fleet down. Idempotent: terminate_fleet
        # tolerates re-call (the hook may fire twice on signal-+-
        # atexit overlap; the FleetManager guards against double-
        # tagging via _terminated).
        if fleet is not None:
            handle.register_finalize_hook(
                lambda: fleet.terminate_fleet("launcher_finalize"),
            )
        # Phase C: clickable Tailscale-hosted link. Printed to stderr
        # so it survives stdout redirection (the iterate child
        # writes a lot of stdout once it starts; stderr stays clean).
        # Per CLAUDE.md's Tailscale-only link policy, base_url
        # defaults to the tailnet hostname not localhost.
        print(
            f"[launcher] cycle {cfg.cycle_id} started. "
            f"Track in UI: {_cycle_url(cfg)}",
            file=sys.stderr,
            flush=True,
        )
        rc = spawn(iterate_argv, env=env)
        # Differentiate clean-stop from a real failure. iterate
        # exits non-zero on a user stop today; treat any non-zero
        # we can't characterise as "failed" by letting the ctx mgr
        # raise from a generic body exception... no -- iterate
        # subprocess exit codes are not reliable signal for
        # killed-vs-failed today. Mark explicit "completed" on rc=0;
        # for non-zero, let the ctx mgr default (which is
        # "completed" via normal exit) ride and lean on the
        # iterate-side finish_run that already wrote the truer
        # terminal status. The launcher's role is the SAFETY net,
        # not the source of truth -- iterate itself owns the
        # nuanced status.
        if rc == 0:
            handle.set_completed_status("completed")
        else:
            # Best-effort: mark failed so the safety net reflects
            # something even if iterate didn't write its own
            # terminal status. iterate's own finish_run wins on
            # the DB row (the launcher's _finalize sets the same
            # field but a later iterate write -- impossible since
            # iterate's already exited -- would overwrite). In
            # practice iterate's finish_run lands first.
            handle.set_completed_status("failed")
        return rc


__all__ = [
    "WorkerNotIdleError",
    "build_parser",
    "collect_worker_urls",
    "main",
    "verify_worker_idle",
]
