"""Self-update pipeline for the v2 worker daemon.

``POST /v2/self_update`` on a worker daemon makes the node refresh its
code from the coordinator's **existing** ``GET /repo.bundle`` endpoint,
rebuild the Rust engine + Python deps **only when those actually
changed**, then re-exec itself in place so the new code is live.

Design constraints (all from ``docs/DISTRIBUTED_API_v2.md`` + the
2026-05-16 AWS handoff):

- **Tailscale-only, no GitHub creds.** Workers fetch the bundle the
  coordinator already serves rather than ``git pull origin``. Ephemeral
  AWS instances get code with nothing but tailnet access.
- **Conditional rebuild.** A code-only commit must NOT pay the
  multi-minute ``maturin develop --release`` cost. The Rust engine is
  rebuilt only when ``rust/`` / ``Cargo.*`` / ``pyproject.toml``
  changed between the old and target commit; deps are reinstalled only
  when ``pyproject.toml`` changed. This gives the "only rebuild the
  engine when the engine changed" property without physically splitting
  the engine into its own package.
- **Supervisor-independent restart.** ``os.execv`` re-exec works the
  same on systemd (which is ``Restart=on-failure`` — a clean exit would
  NOT restart), launchd, and Windows Task Scheduler.

Separated from :mod:`mtg_bot.worker_daemon` so the git / subprocess /
re-exec plumbing doesn't crowd the Flask handler module, and so the
whole fetch→diff→reset→rebuild→reexec pipeline is unit-testable: every
external effect (HTTP, git, subprocess, ``os.execv``) goes through a
small injectable seam a test swaps for a fake. No test ever shells out
to git or replaces the interpreter.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

#: Default git ref the worker resets to. The coordinator's bundle is
#: ``git bundle --all`` so every branch is present; ``main`` is the
#: deployed line.
DEFAULT_REF = "main"

#: Local remote-tracking namespace the bundle's refs are fetched into.
#: Kept distinct from ``origin`` so a worker that ALSO has a GitHub
#: remote configured doesn't get its ``origin`` clobbered.
BUNDLE_REMOTE = "selfupdate"

#: A changed path triggers a Rust rebuild (``maturin develop
#: --release``) if it starts with one of these prefixes or equals one
#: of :data:`REBUILD_RUST_TRIGGER_FILES`.
REBUILD_RUST_TRIGGER_PREFIXES = ("rust/",)
REBUILD_RUST_TRIGGER_FILES = ("Cargo.toml", "Cargo.lock", "pyproject.toml")

#: A changed path triggers a dependency reinstall (``pip install -e
#: .``) if it equals one of these.
REBUILD_DEPS_TRIGGER_FILES = ("pyproject.toml",)

# Network / subprocess timeouts (seconds). The bundle is a few tens of
# MB; the build can be minutes. Generous but bounded so a wedged step
# surfaces as an error rather than a hung daemon.
DEFAULT_HTTP_TIMEOUT_S = 180.0
DEFAULT_GIT_TIMEOUT_S = 120.0
DEFAULT_BUILD_TIMEOUT_S = 1800.0

# Phase labels surfaced on /v2/heartbeat's ``last_update`` block so an
# orchestrator can watch progress without a side channel.
PHASE_FETCHING = "fetching"
PHASE_RESETTING = "resetting"
PHASE_BUILDING = "building"
PHASE_REEXEC = "reexec"
PHASE_UP_TO_DATE = "up_to_date"
PHASE_ERROR = "error"


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@dataclass
class SelfUpdateConfig:
    """Inputs for one self-update attempt.

    ``repo_root`` is the worker's checkout (the daemon's
    ``WorkingDirectory`` in the service file). ``coordinator_url`` is
    the same base URL the claim loop already uses; the bundle lives at
    ``<coordinator_url>/repo.bundle``.
    """

    repo_root: Path
    coordinator_url: str
    ref: str = DEFAULT_REF
    python_exe: str = field(default_factory=lambda: sys.executable)
    http_timeout_s: float = DEFAULT_HTTP_TIMEOUT_S
    git_timeout_s: float = DEFAULT_GIT_TIMEOUT_S
    build_timeout_s: float = DEFAULT_BUILD_TIMEOUT_S

    @property
    def bundle_url(self) -> str:
        return f"{self.coordinator_url.rstrip('/')}/repo.bundle"


@dataclass
class RebuildPlan:
    """Which post-fetch build steps the changed paths imply."""

    rust: bool = False
    deps: bool = False

    @property
    def any(self) -> bool:
        return self.rust or self.deps


@dataclass
class SelfUpdateCallbacks:
    """Side-effect seam — mirrors ``ClaimLoop``'s ``StateCallbacks``
    pattern so the pipeline stays pure and the daemon owns the state
    machine.

    - ``on_phase`` is called with a JSON-serializable progress dict at
      each transition; the daemon stores it for ``/v2/heartbeat``.
    - ``reexec`` replaces the process image. Default production wiring
      passes :func:`reexec`; tests pass a recorder.
    - ``on_error`` is called once with a human-readable detail on any
      failure; the daemon flips to ``ERROR`` and surfaces it.
    - ``on_up_to_date`` is called when the target commit already equals
      the current one (no fetch delta) so the daemon returns to IDLE
      without a pointless re-exec.
    """

    on_phase: Callable[[dict], None]
    reexec: Callable[[], None]
    on_error: Callable[[str], None]
    on_up_to_date: Callable[[], None]


class SelfUpdateError(RuntimeError):
    """Raised internally when a pipeline step fails; the orchestrator
    converts it to an ``on_error`` callback + ``ERROR`` state."""


# ---------------------------------------------------------------------------
# Injectable primitives
# ---------------------------------------------------------------------------

# ``Runner`` is the subprocess.run-shaped seam every git/build step
# goes through. The production default is ``subprocess.run``; tests
# pass a fake that records argv and returns canned CompletedProcess.
Runner = Callable[..., "subprocess.CompletedProcess[str]"]
# ``Opener`` is the urllib.request.urlopen-shaped seam the bundle
# download goes through.
Opener = Callable[..., Any]


def _run_git(
    repo_root: Path,
    args: list[str],
    *,
    runner: Runner,
    timeout: float,
) -> "subprocess.CompletedProcess[str]":
    """Run ``git -C <repo_root> <args...>`` and raise
    :class:`SelfUpdateError` with the captured stderr on a non-zero
    exit (or git-not-found / timeout)."""
    cmd = ["git", "-C", str(repo_root), *args]
    try:
        proc = runner(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:  # git not on PATH
        raise SelfUpdateError(f"git not found: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise SelfUpdateError(
            f"git {' '.join(args)} timed out after {timeout}s"
        ) from exc
    if proc.returncode != 0:
        raise SelfUpdateError(
            f"git {' '.join(args)} failed (exit {proc.returncode}): "
            f"{(proc.stderr or '').strip()[-500:]}"
        )
    return proc


def current_commit(
    repo_root: Path,
    *,
    runner: Runner = subprocess.run,
    timeout: float = DEFAULT_GIT_TIMEOUT_S,
) -> str:
    """Full SHA of the checkout's current ``HEAD``."""
    return _run_git(
        repo_root, ["rev-parse", "HEAD"], runner=runner, timeout=timeout
    ).stdout.strip()


def download_bundle(
    bundle_url: str,
    dest: Path,
    *,
    opener: Opener = urllib.request.urlopen,
    timeout: float = DEFAULT_HTTP_TIMEOUT_S,
) -> None:
    """Stream the coordinator's ``/repo.bundle`` to ``dest``.

    Uses stdlib ``urllib`` (same transport choice as the claim loop —
    no ``requests`` dependency). Any network failure is normalized to
    :class:`SelfUpdateError`.
    """
    try:
        with opener(bundle_url, timeout=timeout) as resp:
            data = resp.read()
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise SelfUpdateError(
            f"bundle download from {bundle_url} failed: {exc}"
        ) from exc
    if not data:
        raise SelfUpdateError(
            f"bundle download from {bundle_url} returned an empty body"
        )
    dest.write_bytes(data)


def fetch_bundle_refs(
    repo_root: Path,
    bundle_path: Path,
    *,
    runner: Runner = subprocess.run,
    timeout: float = DEFAULT_GIT_TIMEOUT_S,
) -> None:
    """``git fetch`` every branch out of the local bundle file into the
    ``selfupdate/*`` remote-tracking namespace."""
    _run_git(
        repo_root,
        [
            "fetch",
            "--force",
            str(bundle_path),
            f"refs/heads/*:refs/remotes/{BUNDLE_REMOTE}/*",
        ],
        runner=runner,
        timeout=timeout,
    )


def resolve_target_commit(
    repo_root: Path,
    ref: str,
    *,
    runner: Runner = subprocess.run,
    timeout: float = DEFAULT_GIT_TIMEOUT_S,
) -> str:
    """Full SHA the requested ``ref`` points at inside the freshly
    fetched bundle namespace."""
    return _run_git(
        repo_root,
        ["rev-parse", f"refs/remotes/{BUNDLE_REMOTE}/{ref}"],
        runner=runner,
        timeout=timeout,
    ).stdout.strip()


def changed_paths(
    repo_root: Path,
    old: str,
    new: str,
    *,
    runner: Runner = subprocess.run,
    timeout: float = DEFAULT_GIT_TIMEOUT_S,
) -> list[str]:
    """Repo-relative paths that differ between ``old`` and ``new``."""
    out = _run_git(
        repo_root,
        ["diff", "--name-only", old, new],
        runner=runner,
        timeout=timeout,
    ).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def plan_rebuild(paths: list[str]) -> RebuildPlan:
    """Map a changed-path list to the build steps it requires.

    Conservative by construction: ``pyproject.toml`` triggers BOTH a
    Rust rebuild and a deps reinstall because it carries the maturin
    build config and the dependency set, and we'd rather over-build
    than ship a daemon running against a stale ``.pyd`` or a missing
    dependency. ``pyproject.toml`` changes are rare, so the occasional
    unnecessary rebuild is cheap insurance.
    """
    rust = any(
        p.startswith(REBUILD_RUST_TRIGGER_PREFIXES)
        or p in REBUILD_RUST_TRIGGER_FILES
        for p in paths
    )
    deps = any(p in REBUILD_DEPS_TRIGGER_FILES for p in paths)
    return RebuildPlan(rust=rust, deps=deps)


def hard_reset(
    repo_root: Path,
    target: str,
    *,
    runner: Runner = subprocess.run,
    timeout: float = DEFAULT_GIT_TIMEOUT_S,
) -> None:
    """``git reset --hard <target>``.

    Worker checkouts are deploy-managed and expected to be pristine
    (no local commits/edits — see ``deploy/README.md``). This discards
    any tracked-file drift but leaves gitignored artifacts
    (``.venv-py313/``, ``trained_weights/``, the deck pool) untouched —
    we deliberately do NOT ``git clean``.
    """
    _run_git(
        repo_root,
        ["reset", "--hard", target],
        runner=runner,
        timeout=timeout,
    )


def run_rebuild(
    plan: RebuildPlan,
    repo_root: Path,
    python_exe: str,
    *,
    runner: Runner = subprocess.run,
    timeout: float = DEFAULT_BUILD_TIMEOUT_S,
) -> None:
    """Run the build steps ``plan`` selected, in dependency order:
    deps reinstall first (so a new build dep is present), then the
    Rust extension. No-op when ``plan`` is empty."""

    def _run(cmd: list[str], label: str) -> None:
        try:
            proc = runner(
                cmd,
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise SelfUpdateError(f"{label}: executable not found: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise SelfUpdateError(
                f"{label} timed out after {timeout}s"
            ) from exc
        if proc.returncode != 0:
            raise SelfUpdateError(
                f"{label} failed (exit {proc.returncode}): "
                f"{(proc.stderr or proc.stdout or '').strip()[-800:]}"
            )

    if plan.deps:
        _run(
            [python_exe, "-m", "pip", "install", "-e", "."],
            "pip install -e .",
        )
    if plan.rust:
        _run(
            [python_exe, "-m", "maturin", "develop", "--release"],
            "maturin develop --release",
        )


# ---------------------------------------------------------------------------
# Re-exec
# ---------------------------------------------------------------------------


def build_relaunch_argv() -> list[str]:
    """Argv that re-launches this daemon with the SAME flags.

    Reconstructs the canonical ``python -m mtg_bot.worker_daemon
    <flags>`` form regardless of how ``sys.argv[0]`` looks, so the
    re-exec is invariant to launch style (``-m`` vs console script).
    """
    return [sys.executable, "-m", "mtg_bot.worker_daemon", *sys.argv[1:]]


def reexec(
    *,
    execv: Callable[[str, list[str]], None] = os.execv,
    argv_builder: Callable[[], list[str]] = build_relaunch_argv,
) -> None:  # pragma: no cover - never returns; exercised via fake in tests
    """Flush stdio and replace the process image with a fresh daemon.

    On POSIX ``os.execv`` keeps the PID, so systemd/launchd never see
    the unit "exit" — supervisor-independent. On Windows the CRT
    spawns a replacement and exits the current process; the listening
    socket is close-on-exec (Python default) and werkzeug sets
    ``SO_REUSEADDR``, so the <1s bind gap is invisible to the
    coordinator's STALE-tolerant heartbeat poller.
    """
    sys.stdout.flush()
    sys.stderr.flush()
    argv = argv_builder()
    log.info("self_update: re-exec %s", " ".join(argv))
    execv(sys.executable, argv)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def perform_self_update(
    cfg: SelfUpdateConfig,
    cbs: SelfUpdateCallbacks,
    *,
    runner: Runner = subprocess.run,
    opener: Opener = urllib.request.urlopen,
    tmp_dir: Optional[Path] = None,
) -> None:
    """Run the full fetch→diff→reset→rebuild→reexec pipeline.

    Never raises: every failure path is funneled into
    ``cbs.on_error`` so the daemon can flip to ``ERROR`` and surface
    the detail on ``/v2/heartbeat``. On success this does not return —
    ``cbs.reexec()`` replaces the process. On a no-delta fetch it
    calls ``cbs.on_up_to_date`` and returns.

    Ordering rationale: the bundle is fetched into a side namespace and
    the rebuild decision is computed BEFORE ``git reset --hard`` moves
    the working tree, so a download/fetch failure leaves the checkout
    exactly as it was (the daemon keeps running the old code happily).
    If a rebuild fails AFTER the reset, the working tree is new but the
    in-memory process still runs the old modules + old ``.pyd``; the
    daemon goes ``ERROR`` (not re-exec'd) so an operator fixes it
    rather than the node looping on a broken build. Safe because
    self-update only runs from ``IDLE`` — no game is in flight.
    """
    try:
        old = current_commit(
            cfg.repo_root, runner=runner, timeout=cfg.git_timeout_s
        )
        cbs.on_phase({"phase": PHASE_FETCHING, "old_commit": old})

        tmp_dir = tmp_dir or cfg.repo_root
        bundle_path = tmp_dir / ".mtg_bot_selfupdate.bundle"
        download_bundle(
            cfg.bundle_url,
            bundle_path,
            opener=opener,
            timeout=cfg.http_timeout_s,
        )
        fetch_bundle_refs(
            cfg.repo_root,
            bundle_path,
            runner=runner,
            timeout=cfg.git_timeout_s,
        )
        target = resolve_target_commit(
            cfg.repo_root, cfg.ref, runner=runner, timeout=cfg.git_timeout_s
        )

        if target == old:
            try:
                bundle_path.unlink()
            except OSError:
                pass
            cbs.on_phase(
                {
                    "phase": PHASE_UP_TO_DATE,
                    "old_commit": old,
                    "target_commit": target,
                }
            )
            cbs.on_up_to_date()
            return

        paths = changed_paths(
            cfg.repo_root, old, target, runner=runner, timeout=cfg.git_timeout_s
        )
        plan = plan_rebuild(paths)
        cbs.on_phase(
            {
                "phase": PHASE_RESETTING,
                "old_commit": old,
                "target_commit": target,
                "rebuild_rust": plan.rust,
                "rebuild_deps": plan.deps,
                "n_changed_paths": len(paths),
            }
        )
        hard_reset(
            cfg.repo_root, target, runner=runner, timeout=cfg.git_timeout_s
        )
        try:
            bundle_path.unlink()
        except OSError:
            pass

        if plan.any:
            cbs.on_phase(
                {
                    "phase": PHASE_BUILDING,
                    "old_commit": old,
                    "target_commit": target,
                    "rebuild_rust": plan.rust,
                    "rebuild_deps": plan.deps,
                }
            )
            run_rebuild(
                plan,
                cfg.repo_root,
                cfg.python_exe,
                runner=runner,
                timeout=cfg.build_timeout_s,
            )

        cbs.on_phase(
            {
                "phase": PHASE_REEXEC,
                "old_commit": old,
                "target_commit": target,
            }
        )
        cbs.reexec()
    except SelfUpdateError as exc:
        log.error("self_update failed: %s", exc)
        cbs.on_error(str(exc))
    except Exception as exc:  # defensive — never let the thread die silently
        log.exception("self_update unexpected failure")
        cbs.on_error(f"unexpected: {exc!r}")
