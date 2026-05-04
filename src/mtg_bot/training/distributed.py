"""Distribute self-play across local + remote machines.

Today ``iterate_alphazero``'s self-play step runs ``mp.Pool(workers=24)``
on the master box. Each iter spends ~50 minutes here. With other
machines on the same Tailnet (a Windows box, an Apple Silicon Mac),
we can shard the work and roughly halve that wall-time.

Architecture: each shard produces ONE ``iter_NNN_<bootstrap>_shard_
<label>_<utc>.npz`` file in the master's iterate-data dir. The
orchestrator then concatenates them in the existing
``train_nn.py --data-dir`` glob path — no schema change there.

Code distribution: each remote has its own ``git clone`` of the repo;
the orchestrator runs ``git pull`` over SSH before each shard so
master commits to ``main`` propagate automatically. Weight
distribution: ``scp`` the latest version's weights at the start of
each self-play phase. Result collection: ``scp`` the shard npz back
to the master after the remote finishes.

This module is the importable / testable core. The thin CLI wrapper
lives in ``scripts/distributed_self_play.py``; ``iterate_alphazero``
calls into here directly via ``run_distributed_self_play``.
"""

from __future__ import annotations

import concurrent.futures
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class ShardConfig:
    """One shard of a distributed self-play run.

    A shard is a contiguous range of games run on one machine. Each
    shard gets its own seed-offset so seed collisions across shards
    are impossible (different shards play DIFFERENT games, not the
    same games on different hosts).

    ``host="local"`` runs in the master process via the existing
    ``generate_training_data_parallel``. Any other ``host`` value
    triggers the SSH remote-shard path.
    """

    # Where the shard runs. ``"local"`` means in-process on the
    # master; anything else is a Tailscale-reachable hostname or IP.
    host: str
    # How many games this shard plays.
    n_games: int
    # Free-form short label for naming output artifacts (e.g. the
    # shard's npz file). Defaults to ``host`` when omitted.
    label: str = ""
    # Per-shard seed offset. Final per-game seed is
    # ``base_seed + seed_offset + game_idx``. Caller should ensure
    # offsets across shards don't overlap. Idiomatic pattern: the
    # orchestrator allocates 1_000_000 per shard so 500-game shards
    # never collide.
    seed_offset: int = 0
    # Worker count for the shard's local mp.Pool. Defaults to None
    # (the script's own default, currently cpu_count() - 2).
    n_workers: Optional[int] = None

    # ---- remote-only fields (ignored when host == "local") ----
    # SSH user. Required for remote shards.
    user: Optional[str] = None
    # Absolute path to the repo's working tree on the remote.
    repo_path: Optional[str] = None
    # Path (relative to ``repo_path``) of the venv's python
    # executable. Windows: ``.venv-py313\\Scripts\\python.exe``.
    # macOS / Linux: ``.venv-py313/bin/python``. Different across
    # OSes by Python convention.
    venv_python: Optional[str] = None
    # SSH port; default 22.
    ssh_port: int = 22

    @property
    def is_local(self) -> bool:
        return self.host == "local"

    @property
    def display_label(self) -> str:
        return self.label or self.host

    def __post_init__(self) -> None:
        # Validate up-front — easier to catch a malformed config at
        # load time than after several minutes of self-play.
        if not self.host:
            raise ValueError("host is required")
        if self.n_games <= 0:
            raise ValueError(
                f"n_games must be positive, got {self.n_games}"
            )
        if self.seed_offset < 0:
            raise ValueError(
                f"seed_offset must be non-negative, got {self.seed_offset}"
            )
        if not self.is_local:
            missing = [
                name for name in ("user", "repo_path", "venv_python")
                if getattr(self, name) is None
            ]
            if missing:
                raise ValueError(
                    f"remote shard host={self.host!r} missing fields: "
                    f"{missing}"
                )


@dataclass(frozen=True)
class ShardsConfig:
    """Top-level config: a list of shards plus a small block of
    defaults common to all of them.

    Loaded from JSON. Hand-editing JSON is fine for the 2-3-machine
    setup we have today; if it grows we can migrate to YAML.
    """

    shards: tuple[ShardConfig, ...]

    @property
    def total_games(self) -> int:
        return sum(s.n_games for s in self.shards)

    def __post_init__(self) -> None:
        if not self.shards:
            raise ValueError("shards list is empty")
        # Reject duplicate labels — they'd collide in the npz
        # filenames the orchestrator produces.
        labels = [s.display_label for s in self.shards]
        dupes = {x for x in labels if labels.count(x) > 1}
        if dupes:
            raise ValueError(
                f"duplicate shard labels: {sorted(dupes)}. "
                f"Set explicit ``label`` on each shard with the same "
                f"host (or use distinct hosts)."
            )


def load_shards_config(path: Path) -> ShardsConfig:
    """Read a shards-config JSON file from disk.

    Schema (one example)::

        {
          "shards": [
            {"host": "local", "n_games": 200},
            {
              "host": "win-1080ti",
              "n_games": 150,
              "user": "gregg",
              "repo_path": "C:\\Users\\gregg\\Projects\\mtg-bot",
              "venv_python": ".venv-py313\\Scripts\\python.exe"
            },
            {
              "host": "macbook",
              "n_games": 150,
              "user": "gregg",
              "repo_path": "/Users/gregg/projects/mtg-bot",
              "venv_python": ".venv-py313/bin/python"
            }
          ]
        }

    seed_offset defaults to position * 1_000_000 (idiomatic pattern,
    no collisions for shards under 1M games each) but can be set
    explicitly per shard.
    """
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict) or "shards" not in raw:
        raise ValueError(
            f"shards-config {path} missing top-level 'shards' key"
        )
    raw_shards = raw["shards"]
    if not isinstance(raw_shards, list):
        raise ValueError(
            f"shards-config {path}: 'shards' must be a list"
        )
    shards: list[ShardConfig] = []
    for i, item in enumerate(raw_shards):
        if not isinstance(item, dict):
            raise ValueError(
                f"shards-config {path}: shard #{i} must be an object"
            )
        # Auto-assign seed_offset if absent — first shard 0, second
        # shard 1_000_000, etc. Explicit offsets win over the default.
        if "seed_offset" not in item:
            item = {**item, "seed_offset": i * 1_000_000}
        shards.append(ShardConfig(**item))
    return ShardsConfig(shards=tuple(shards))


# -----------------------------------------------------------------
# Runtime orchestration: dispatch each shard's self-play, collect
# the resulting npz paths back to the master.
# -----------------------------------------------------------------


def _now_stamp() -> str:
    """ISO timestamp with no colons (filename-safe)."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _shard_npz_path(
    output_dir: Path, run_id_prefix: str, shard: ShardConfig,
    stamp: str,
) -> Path:
    """Per-shard output filename. Includes the shard's display label
    so two shards from the same iter (or two iter runs ending in the
    same second) don't collide. Lives in ``output_dir`` (typically
    the master's ``iterate_data/``)."""
    return output_dir / (
        f"{run_id_prefix}_shard_{shard.display_label}_{stamp}.npz"
    )


def _shard_progress_path(
    progress_dir: Path, run_id_prefix: str, shard: ShardConfig,
) -> Path:
    """Per-shard progress JSON path; the training UI surfaces each
    shard as a separate card. Stable across the run (no timestamp)
    so the UI can re-find the card across polls."""
    return progress_dir / (
        f"{run_id_prefix}_shard_{shard.display_label}.json"
    )


@dataclass(frozen=True)
class SelfPlayJobSpec:
    """All the parameters a shard needs to play games. Same shape on
    every shard — only the per-shard count + seed-offset differs.
    Frozen so it crosses the multiprocessing pickle boundary cleanly
    when iterate hands it to local-shard workers via ``generate_
    training_data_parallel``."""

    weights_path: str
    samples: int
    inner_nodes: int
    hidden_sizes: Optional[tuple[int, ...]]
    base_seed: int
    enable_mulligans: bool
    per_game_timeout_sec: Optional[float]
    deck_pool_path: Optional[str] = None
    with_policy: bool = True
    decision_cap: int = 4000
    sample_every: int = 1
    capture_every: int = 0  # 0 = no replay capture
    nn_version_label: Optional[str] = None
    replays_root: Optional[str] = None
    hang_dump_root: Optional[str] = None


def run_shard_local(
    shard: ShardConfig,
    spec: SelfPlayJobSpec,
    *,
    progress_dir: Path,
    output_dir: Path,
    run_id_prefix: str,
    stamp: str,
) -> Path:
    """Run a single shard in-process. Builds the same NNPimcConfig +
    DataGenProgress + (optional) ReplayCaptureConfig that
    iterate_alphazero's ``_self_play`` builds, then calls
    ``generate_training_data_parallel`` for the shard's slice of
    the workload.

    Returns the path of the produced ``.npz``.

    Lives in this module (not in a script) so the orchestrator can
    invoke it from the same process iterate runs in.
    """
    # Imports are local to keep the module's import-cost low for
    # the common "load shards-config to validate" path that doesn't
    # need any of the training internals.
    from mtg_bot.decks import decks_from_json
    from mtg_bot.training import (
        DataGenProgress,
        NNPimcConfig,
        generate_training_data_parallel,
        save_dataset,
    )
    from mtg_bot.training.data_gen import ReplayCaptureConfig

    cfg = NNPimcConfig(
        weights_path=spec.weights_path,
        samples=spec.samples,
        inner_nodes=spec.inner_nodes,
        batch_size=32,
        with_policy=spec.with_policy,
        puct=True,
        hidden_sizes=spec.hidden_sizes,
    )

    deck_pool = None
    if spec.deck_pool_path is not None:
        deck_pool = decks_from_json(Path(spec.deck_pool_path))

    output_dir.mkdir(parents=True, exist_ok=True)
    progress_dir.mkdir(parents=True, exist_ok=True)
    output_path = _shard_npz_path(
        output_dir, run_id_prefix, shard, stamp,
    )
    progress_path = _shard_progress_path(
        progress_dir, run_id_prefix, shard,
    )

    # Replay capture — opt-in via spec.capture_every. Each shard
    # writes to its own subdir under the master's replays-root so
    # the training UI's per-card 'View N games' link finds them.
    replay_config: Optional[ReplayCaptureConfig] = None
    replays_subdir: Optional[str] = None
    if spec.capture_every > 0 and spec.replays_root is not None:
        run_id = (
            f"{run_id_prefix}_shard_{shard.display_label}"
        )
        replays_subdir = str(
            Path(spec.replays_root) / run_id
        )
        Path(replays_subdir).mkdir(parents=True, exist_ok=True)
        replay_config = ReplayCaptureConfig(
            save_dir=replays_subdir,
            capture_every=spec.capture_every,
            nn_weights_path=spec.weights_path,
            nn_version_label=spec.nn_version_label,
            nn_hidden_sizes=spec.hidden_sizes,
            nn_with_policy=spec.with_policy,
        )

    hang_dump_dir: Optional[str] = None
    if spec.hang_dump_root is not None:
        hang_dump_dir = str(
            Path(spec.hang_dump_root)
            / f"{run_id_prefix}_shard_{shard.display_label}"
        )

    progress = DataGenProgress(
        progress_path=progress_path,
        run_id=f"{run_id_prefix}_shard_{shard.display_label}",
        n_games_total=shard.n_games,
        n_workers=(
            shard.n_workers if shard.n_workers is not None
            else max(1, 0)  # generate_training_data_parallel will
                            # default-fill from cpu_count
        ),
        command="distributed_self_play (local shard)",
        notes=(
            f"distributed shard {shard.display_label} "
            f"({shard.n_games} games)"
        ),
        replays_dir=replays_subdir,
    )

    try:
        features, outcomes, policy_targets, action_masks = (
            generate_training_data_parallel(
                p0_factory=cfg.build,
                p1_factory=cfg.build,
                n_games=shard.n_games,
                base_seed=spec.base_seed + shard.seed_offset,
                n_workers=shard.n_workers,
                with_policy=True,
                decision_cap=spec.decision_cap,
                sample_every=spec.sample_every,
                enable_mulligans=spec.enable_mulligans,
                per_game_timeout_sec=spec.per_game_timeout_sec,
                progress=progress,
                deck_pool=deck_pool,
                replay_config=replay_config,
                hang_dump_dir=hang_dump_dir,
            )
        )
    except BaseException:
        progress.finalize(status="failed")
        raise
    progress.finalize(status="completed")

    save_dataset(
        features, outcomes, output_path,
        policy_targets=policy_targets, action_masks=action_masks,
    )
    return output_path


def run_distributed_self_play(
    shards_config: ShardsConfig,
    spec: SelfPlayJobSpec,
    *,
    progress_dir: Path,
    output_dir: Path,
    run_id_prefix: str,
) -> list[Path]:
    """Orchestrate every shard's self-play in parallel, return the
    list of per-shard ``.npz`` paths.

    Local shards run in-process (one at a time today — both shards'
    inner ``mp.Pool``s would otherwise compete for the same CPU
    cores; rely on the user putting at most one ``host="local"``
    shard in the config). Remote shards are dispatched concurrently
    via ``concurrent.futures.ThreadPoolExecutor`` since SSH I/O is
    blocking but not CPU-bound.

    Future commit on this branch wires up the remote-shard runner;
    today remote shards raise ``NotImplementedError``.
    """
    stamp = _now_stamp()
    output_paths: dict[str, Path] = {}

    # Run all remote shards concurrently in threads (SSH I/O is the
    # bottleneck, not the master's CPU).  Local shards run inline
    # after — they hold the master's mp.Pool so concurrent local
    # shards would just contend with each other.
    remote_shards = [s for s in shards_config.shards if not s.is_local]
    local_shards = [s for s in shards_config.shards if s.is_local]

    futures: dict[concurrent.futures.Future, ShardConfig] = {}
    if remote_shards:
        executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=len(remote_shards),
            thread_name_prefix="dist-self-play",
        )
        try:
            for shard in remote_shards:
                fut = executor.submit(
                    run_shard_remote, shard, spec,
                    progress_dir=progress_dir,
                    output_dir=output_dir,
                    run_id_prefix=run_id_prefix,
                    stamp=stamp,
                )
                futures[fut] = shard
        finally:
            executor.shutdown(wait=False)

    # Local shards run inline — they want all the master's CPU.
    for shard in local_shards:
        path = run_shard_local(
            shard, spec,
            progress_dir=progress_dir,
            output_dir=output_dir,
            run_id_prefix=run_id_prefix,
            stamp=stamp,
        )
        output_paths[shard.display_label] = path

    # Drain the remote futures.
    for fut, shard in futures.items():
        output_paths[shard.display_label] = fut.result()

    # Return in shards-config order so callers get deterministic
    # ordering for any downstream concat that's order-sensitive.
    return [output_paths[s.display_label] for s in shards_config.shards]


def run_shard_remote(
    shard: ShardConfig,
    spec: SelfPlayJobSpec,
    *,
    progress_dir: Path,
    output_dir: Path,
    run_id_prefix: str,
    stamp: str,
) -> Path:
    """Run a single shard on a remote machine via SSH, scp the
    resulting ``.npz`` back to the master's ``output_dir``, return
    the local path.

    Stub today — implementation lands in the next commit on this
    branch.
    """
    raise NotImplementedError(
        f"remote shard runner not yet implemented (shard host="
        f"{shard.host!r}). Use ``host=\"local\"`` shards for now."
    )
