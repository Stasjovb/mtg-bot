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
import shlex
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "n_games": self.n_games,
            "label": self.label,
            "seed_offset": self.seed_offset,
            "n_workers": self.n_workers,
            "user": self.user,
            "repo_path": self.repo_path,
            "venv_python": self.venv_python,
            "ssh_port": self.ssh_port,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ShardConfig":
        return cls(
            host=d["host"],
            n_games=int(d["n_games"]),
            label=d.get("label", ""),
            seed_offset=int(d.get("seed_offset", 0)),
            n_workers=d.get("n_workers"),
            user=d.get("user"),
            repo_path=d.get("repo_path"),
            venv_python=d.get("venv_python"),
            ssh_port=int(d.get("ssh_port", 22)),
        )

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
    training_data_parallel``.

    All path fields (``weights_path``, ``deck_pool_path``,
    ``replays_root``, ``hang_dump_root``) are RELATIVE to the repo
    root by convention, so the same spec works for both local and
    remote shards (which have different absolute paths but the same
    relative layout). Local shards run with cwd at the master's
    repo root; remote shards' wrapper script ``cd``s into the
    remote's repo root before resolving paths.
    """

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
    use_ismcts: bool = False
    use_belief_weighted: bool = False
    # Phase-based active-priority prune (training heuristic). Defaults
    # ON for self-play; see ``docs/SEARCH_LIMITATIONS.md`` entry #6.
    phase_prune_enabled: bool = True
    # Forced second-main land drop (training heuristic). Defaults ON
    # for self-play; see ``docs/SEARCH_LIMITATIONS.md`` entry #7.
    force_landdrop_enabled: bool = True
    # Skip-empty-combat short-circuit (training heuristic). Defaults
    # ON for self-play; see ``docs/SEARCH_LIMITATIONS.md`` entry #9.
    skip_empty_combat_enabled: bool = True
    # Skip our priority on opp's POSTCOMBAT_MAIN (training heuristic).
    # Defaults ON for self-play; see ``docs/SEARCH_LIMITATIONS.md``
    # entry #10.
    skip_opp_postcombat_main_enabled: bool = True
    # Skip-dead-main1 (training heuristic). Defaults ON for self-play;
    # see ``docs/SEARCH_LIMITATIONS.md`` entry #11.
    skip_dead_main1_enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable dict. Used by ``run_self_play_shard.py``
        to round-trip the spec across the SSH boundary — the remote
        receives the spec via ``--spec-json '<base64-encoded JSON>'``
        and reconstructs.

        Path fields are normalized to forward slashes here so the
        wire format is platform-neutral. iterate runs on Windows and
        produces ``tmp/foo\\bar.pt`` from ``str(Path(...))``; the Mac
        remote then opens a literal filename with embedded ``\\``
        characters and crashes. Forward slashes work on both Windows
        (cmd.exe + Python both accept them) and POSIX, so we settle
        on them universally for the wire format.
        """
        def _posix(p):
            return p.replace("\\", "/") if isinstance(p, str) else p
        return {
            "weights_path": _posix(self.weights_path),
            "samples": self.samples,
            "inner_nodes": self.inner_nodes,
            "hidden_sizes": (
                list(self.hidden_sizes) if self.hidden_sizes is not None
                else None
            ),
            "base_seed": self.base_seed,
            "enable_mulligans": self.enable_mulligans,
            "per_game_timeout_sec": self.per_game_timeout_sec,
            "deck_pool_path": _posix(self.deck_pool_path),
            "with_policy": self.with_policy,
            "decision_cap": self.decision_cap,
            "sample_every": self.sample_every,
            "capture_every": self.capture_every,
            "nn_version_label": self.nn_version_label,
            "replays_root": _posix(self.replays_root),
            "hang_dump_root": _posix(self.hang_dump_root),
            "use_ismcts": self.use_ismcts,
            "use_belief_weighted": self.use_belief_weighted,
            "phase_prune_enabled": self.phase_prune_enabled,
            "force_landdrop_enabled": self.force_landdrop_enabled,
            "skip_empty_combat_enabled": self.skip_empty_combat_enabled,
            "skip_opp_postcombat_main_enabled": (
                self.skip_opp_postcombat_main_enabled
            ),
            "skip_dead_main1_enabled": self.skip_dead_main1_enabled,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SelfPlayJobSpec":
        hs = d.get("hidden_sizes")
        return cls(
            weights_path=d["weights_path"],
            samples=int(d["samples"]),
            inner_nodes=int(d["inner_nodes"]),
            hidden_sizes=tuple(hs) if hs is not None else None,
            base_seed=int(d["base_seed"]),
            enable_mulligans=bool(d["enable_mulligans"]),
            per_game_timeout_sec=d.get("per_game_timeout_sec"),
            deck_pool_path=d.get("deck_pool_path"),
            with_policy=bool(d.get("with_policy", True)),
            decision_cap=int(d.get("decision_cap", 4000)),
            sample_every=int(d.get("sample_every", 1)),
            capture_every=int(d.get("capture_every", 0)),
            nn_version_label=d.get("nn_version_label"),
            replays_root=d.get("replays_root"),
            hang_dump_root=d.get("hang_dump_root"),
            use_ismcts=bool(d.get("use_ismcts", False)),
            use_belief_weighted=bool(d.get("use_belief_weighted", False)),
            phase_prune_enabled=bool(
                d.get("phase_prune_enabled", True),
            ),
            force_landdrop_enabled=bool(
                d.get("force_landdrop_enabled", True),
            ),
            skip_empty_combat_enabled=bool(
                d.get("skip_empty_combat_enabled", True),
            ),
            skip_opp_postcombat_main_enabled=bool(
                d.get("skip_opp_postcombat_main_enabled", True),
            ),
            skip_dead_main1_enabled=bool(
                d.get("skip_dead_main1_enabled", True),
            ),
        )


@dataclass(frozen=True)
class EvalJobSpec:
    """Eval-mode counterpart to ``SelfPlayJobSpec``: parameters for an
    acceptance-gate match between two NN versions across the cluster.

    Two weights paths because every eval game pits ``new`` (seat 0)
    against ``old`` (seat 1). ``old_weights_path=None`` falls back to a
    heuristic opponent — useful for sanity-check evals against the
    baseline. Path fields normalize to forward slashes in
    ``to_dict()`` for the same cross-platform reasons documented on
    ``SelfPlayJobSpec``.
    """

    new_weights_path: str
    old_weights_path: Optional[str]
    samples: int
    inner_nodes: int
    hidden_sizes: Optional[tuple[int, ...]]
    base_seed: int
    enable_mulligans: bool
    per_game_timeout_sec: Optional[float]
    deck_pool_path: Optional[str] = None
    capture_every: int = 0
    nn_new_version_label: Optional[str] = None
    nn_old_version_label: Optional[str] = None
    replays_root: Optional[str] = None
    hang_dump_root: Optional[str] = None
    opponent_label: str = "previous"
    use_ismcts: bool = False
    use_belief_weighted: bool = False
    # Phase-based active-priority prune. For eval/tournament play
    # this defaults OFF — the strength-vs-throughput tradeoff that
    # justifies the prune in training does not apply when match
    # outcomes determine acceptance.
    phase_prune_enabled: bool = False
    # Forced second-main land drop. Defaults OFF for eval (same
    # rationale: match outcomes are load-bearing, the heuristic
    # forces a play that may differ from optimal).
    force_landdrop_enabled: bool = False
    # Skip-empty-combat short-circuit. Defaults OFF for eval — the
    # 0-attacking-creatures gate is correctness-tight (no creature
    # to pump or remove), so this is safer than the others to leave
    # ON, but eval still defaults conservative.
    skip_empty_combat_enabled: bool = False
    # Skip our priority on opp's POSTCOMBAT_MAIN. Defaults OFF for
    # eval — the heuristic forgoes potential reactive plays that
    # match outcomes might depend on.
    skip_opp_postcombat_main_enabled: bool = False
    # Skip-dead-main1. Defaults OFF for eval — the rare niche plays
    # the heuristic skips (cast a sorcery early enough to be relevant
    # to a turn-1 effect; activate a non-mana ability) might matter
    # in the tight margin of an eval match.
    skip_dead_main1_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        def _posix(p):
            return p.replace("\\", "/") if isinstance(p, str) else p
        return {
            "new_weights_path": _posix(self.new_weights_path),
            "old_weights_path": _posix(self.old_weights_path),
            "samples": self.samples,
            "inner_nodes": self.inner_nodes,
            "hidden_sizes": (
                list(self.hidden_sizes) if self.hidden_sizes is not None
                else None
            ),
            "base_seed": self.base_seed,
            "enable_mulligans": self.enable_mulligans,
            "per_game_timeout_sec": self.per_game_timeout_sec,
            "deck_pool_path": _posix(self.deck_pool_path),
            "capture_every": self.capture_every,
            "nn_new_version_label": self.nn_new_version_label,
            "nn_old_version_label": self.nn_old_version_label,
            "replays_root": _posix(self.replays_root),
            "hang_dump_root": _posix(self.hang_dump_root),
            "opponent_label": self.opponent_label,
            "use_ismcts": self.use_ismcts,
            "use_belief_weighted": self.use_belief_weighted,
            "phase_prune_enabled": self.phase_prune_enabled,
            "force_landdrop_enabled": self.force_landdrop_enabled,
            "skip_empty_combat_enabled": self.skip_empty_combat_enabled,
            "skip_opp_postcombat_main_enabled": (
                self.skip_opp_postcombat_main_enabled
            ),
            "skip_dead_main1_enabled": self.skip_dead_main1_enabled,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EvalJobSpec":
        hs = d.get("hidden_sizes")
        return cls(
            new_weights_path=d["new_weights_path"],
            old_weights_path=d.get("old_weights_path"),
            samples=int(d["samples"]),
            inner_nodes=int(d["inner_nodes"]),
            hidden_sizes=tuple(hs) if hs is not None else None,
            base_seed=int(d["base_seed"]),
            enable_mulligans=bool(d["enable_mulligans"]),
            per_game_timeout_sec=d.get("per_game_timeout_sec"),
            deck_pool_path=d.get("deck_pool_path"),
            capture_every=int(d.get("capture_every", 0)),
            nn_new_version_label=d.get("nn_new_version_label"),
            nn_old_version_label=d.get("nn_old_version_label"),
            replays_root=d.get("replays_root"),
            hang_dump_root=d.get("hang_dump_root"),
            opponent_label=d.get("opponent_label", "previous"),
            use_ismcts=bool(d.get("use_ismcts", False)),
            use_belief_weighted=bool(d.get("use_belief_weighted", False)),
            phase_prune_enabled=bool(
                d.get("phase_prune_enabled", False),
            ),
            force_landdrop_enabled=bool(
                d.get("force_landdrop_enabled", False),
            ),
            skip_empty_combat_enabled=bool(
                d.get("skip_empty_combat_enabled", False),
            ),
            skip_opp_postcombat_main_enabled=bool(
                d.get("skip_opp_postcombat_main_enabled", False),
            ),
            skip_dead_main1_enabled=bool(
                d.get("skip_dead_main1_enabled", False),
            ),
        )


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
        use_ismcts=spec.use_ismcts,
        use_belief_weighted=spec.use_belief_weighted,
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
                phase_prune_enabled=spec.phase_prune_enabled,
                force_landdrop_enabled=spec.force_landdrop_enabled,
                skip_empty_combat_enabled=spec.skip_empty_combat_enabled,
                skip_opp_postcombat_main_enabled=(
                    spec.skip_opp_postcombat_main_enabled
                ),
                skip_dead_main1_enabled=spec.skip_dead_main1_enabled,
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


class _AggregateProgressPoller:
    """Periodically reads all per-shard progress JSONs in
    ``progress_dir`` matching ``<run_id>_shard_*.json`` and writes a
    rolled-up ``<run_id>.json`` summing the counters across shards.

    The training UI (``training_progress/`` viewer) globs that
    directory for run cards; without this aggregate it would render
    one card per shard, each showing ``X / iter_total`` where X is
    that shard's share. The aggregate gives the user one coherent
    "iter card" with the cluster-wide totals; individual per-shard
    files still exist for diagnostic drill-down (the UI filters them
    out of the top-level listing by the ``_shard_`` substring).

    ``kind`` is ``"data_gen"`` for self-play or ``"eval"`` — controls
    which set of summed fields ends up in the JSON. Both share the
    progress / total / status / elapsed shape so the UI renderer
    doesn't need to special-case distributed runs.
    """

    _SUM_FIELDS = (
        "n_games_done", "n_samples", "n_workers", "crashed",
        "p0_wins", "p1_wins", "draws",
        "wins_new", "wins_old",
    )

    def __init__(
        self,
        progress_dir: Path,
        run_id: str,
        n_games_total: int,
        kind: str,
        *,
        opponent_label: Optional[str] = None,
        interval_s: float = 2.0,
    ) -> None:
        self._progress_dir = Path(progress_dir)
        self._run_id = run_id
        self._n_games_total = n_games_total
        self._kind = kind
        self._opponent_label = opponent_label
        self._interval_s = interval_s
        self._aggregate_path = self._progress_dir / f"{run_id}.json"
        self._started_perf = time.monotonic()
        self._started_iso = datetime.now(timezone.utc).isoformat(
            timespec="seconds",
        )
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._write("running")
        self._thread = threading.Thread(
            target=self._loop,
            name=f"agg-progress-{self._run_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self, status: str) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._write(status)

    def _loop(self) -> None:
        while not self._stop_event.wait(self._interval_s):
            self._write("running")

    def _write(self, status: str) -> None:
        from mtg_bot.training.progress import atomic_write_json
        sums = {f: 0 for f in self._SUM_FIELDS}
        machines: list[dict[str, Any]] = []
        ended_ats: list[str] = []
        decisions_weighted_total = 0.0
        pattern = f"{self._run_id}_shard_*.json"
        for path in sorted(self._progress_dir.glob(pattern)):
            # Eval shards write a sibling ``..._shard_<label>_result.json``
            # carrying the same wins/draws/crashed counts. Including it
            # in the sum would double-count every remote shard's games.
            if path.stem.endswith("_result"):
                continue
            try:
                shard = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for f in self._SUM_FIELDS:
                v = shard.get(f, 0)
                if isinstance(v, (int, float)):
                    sums[f] += v
            shard_done = shard.get("n_games_done", 0)
            shard_avg_dec = shard.get("avg_decisions", 0)
            if (
                isinstance(shard_done, (int, float))
                and isinstance(shard_avg_dec, (int, float))
            ):
                decisions_weighted_total += shard_avg_dec * shard_done
            label = path.stem.split("_shard_", 1)[-1]
            machines.append({
                "label": label,
                "status": shard.get("status", "unknown"),
                "n_games_done": shard.get("n_games_done", 0),
                "n_workers": shard.get("n_workers", 0),
                "crashed": shard.get("crashed", 0),
            })
            if shard.get("ended_at"):
                ended_ats.append(shard["ended_at"])
        elapsed = max(time.monotonic() - self._started_perf, 0.0)
        done = sums["n_games_done"]
        total = self._n_games_total
        avg = (elapsed / done) if done > 0 else 0.0
        eta = avg * max(total - done, 0)
        games_per_hour = (done / elapsed * 3600.0) if elapsed > 0 else 0.0
        ended_at = (
            max(ended_ats) if ended_ats and status != "running" else None
        )
        payload: dict[str, Any] = {
            "run_id": self._run_id,
            "kind": self._kind,
            "status": status,
            "started_at": self._started_iso,
            "ended_at": ended_at,
            "n_games_total": int(total),
            "n_games_done": int(done),
            "n_workers": int(sums["n_workers"]),
            "crashed": int(sums["crashed"]),
            "elapsed_seconds": float(elapsed),
            "estimated_remaining_seconds": float(eta),
            "per_game_seconds_avg": float(avg),
            "games_per_hour": float(games_per_hour),
            "machines": machines,
        }
        if self._kind == "data_gen":
            samples_per_hour = (
                sums["n_samples"] / elapsed * 3600.0 if elapsed > 0 else 0.0
            )
            payload["n_samples"] = int(sums["n_samples"])
            payload["p0_wins"] = int(sums["p0_wins"])
            payload["p1_wins"] = int(sums["p1_wins"])
            payload["draws"] = int(sums["draws"])
            payload["samples_per_hour"] = float(samples_per_hour)
        else:
            decided = sums["wins_new"] + sums["wins_old"]
            avg_decisions = (
                decisions_weighted_total / done if done > 0 else 0.0
            )
            payload["wins_new"] = int(sums["wins_new"])
            payload["wins_old"] = int(sums["wins_old"])
            payload["draws"] = int(sums["draws"])
            payload["win_rate"] = (
                sums["wins_new"] / decided if decided > 0 else 0.0
            )
            payload["avg_decisions"] = float(avg_decisions)
            if self._opponent_label is not None:
                payload["opponent_label"] = self._opponent_label
        atomic_write_json(self._aggregate_path, payload)


def _loopback_queue_url(queue_url: str) -> str:
    """Rewrite the queue URL's host to ``127.0.0.1`` so the master's
    own local shard skips Tailscale name resolution. On Windows that
    resolution attempts IPv6 first against the tailnet hostname and
    burns ~4s per take before falling back; ``localhost`` also has a
    ~2s penalty. Loopback IP literal hits ~12ms. Remote shards keep
    the original URL — they reach master via the tailnet."""
    from urllib.parse import urlsplit, urlunsplit
    parts = urlsplit(queue_url)
    netloc = f"127.0.0.1:{parts.port}" if parts.port else "127.0.0.1"
    return urlunsplit((
        parts.scheme, netloc, parts.path,
        parts.query, parts.fragment,
    ))


def run_distributed_self_play(
    shards_config: ShardsConfig,
    spec: SelfPlayJobSpec,
    *,
    progress_dir: Path,
    output_dir: Path,
    run_id_prefix: str,
    total_games: int,
    queue_url: str,
    bundle_url: Optional[str] = None,
) -> list[Path]:
    """Pull-model orchestrator. Initializes a queue of ``total_games``
    on master, dispatches every shard concurrently to pull from it,
    returns the list of every ``.npz`` produced. Master's training
    step globs ``output_dir`` so the union becomes the iter's training
    mix automatically.

    Each shard runs ``run_shard_pull``, which opens a pool of
    ``n_workers`` worker processes and continuously feeds them games
    one at a time from ``/queue/take``. As any worker finishes its
    game, the shard pulls the next available game and dispatches it
    to that worker. Slow machines pull fewer total games; fast ones
    pull more — wall ≈ ``total_games / sum(per_machine_throughput)``
    instead of being capped by the slowest shard.
    """
    import threading as _threading
    import urllib.request
    import json as _json

    stamp = _now_stamp()
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_dir.mkdir(parents=True, exist_ok=True)

    # Initialize the queue. The run_id_prefix doubles as the queue
    # key — same value workers send back to /queue/take.
    init_url = f"{queue_url.rstrip('/')}/queue/init"
    init_body = _json.dumps({
        "run_id": run_id_prefix,
        "total_games": total_games,
    }).encode("utf-8")
    req = urllib.request.Request(
        init_url, data=init_body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status != 200:
            raise RuntimeError(
                f"queue init failed at {init_url}: HTTP {resp.status}"
            )

    output_paths: list[Path] = []
    output_paths_lock = _threading.Lock()

    def _local_runner(shard: ShardConfig) -> list[Path]:
        n_workers = shard.n_workers
        if n_workers is None:
            import os
            n_workers = max(1, (os.cpu_count() or 1) - 2)
        return run_shard_pull(
            spec,
            queue_url=_loopback_queue_url(queue_url),
            run_id=run_id_prefix,
            n_workers=n_workers,
            output_dir=output_dir,
            label=shard.display_label,
            stamp=stamp,
            iter_total_games=total_games,
            progress_dir=progress_dir,
        )

    def _remote_runner(shard: ShardConfig) -> list[Path]:
        return run_shard_remote(
            shard, spec,
            queue_url=queue_url,
            run_id=run_id_prefix,
            iter_total_games=total_games,
            progress_dir=progress_dir,
            output_dir=output_dir,
            run_id_prefix=run_id_prefix,
            stamp=stamp,
            bundle_url=bundle_url,
        )

    aggregator = _AggregateProgressPoller(
        progress_dir=progress_dir,
        run_id=run_id_prefix,
        n_games_total=total_games,
        kind="data_gen",
    )
    aggregator.start()

    # All shards run concurrently — they pull from the same queue,
    # so there's no static partitioning to worry about. Local
    # shards' mp.Pool runs in this process; remote shards block on
    # SSH (lots of idle wall time waiting on the network call to
    # finish before a thread can do useful work, but the master
    # CPU isn't held).
    futures: dict[concurrent.futures.Future, ShardConfig] = {}
    n_threads = max(1, len(shards_config.shards))
    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=n_threads, thread_name_prefix="dist-self-play",
    )
    try:
        for shard in shards_config.shards:
            runner = _local_runner if shard.is_local else _remote_runner
            futures[executor.submit(runner, shard)] = shard
    finally:
        executor.shutdown(wait=False)

    failed = False
    try:
        for fut in concurrent.futures.as_completed(futures):
            try:
                shard_paths = fut.result()
            except BaseException:
                failed = True
                raise
            with output_paths_lock:
                output_paths.extend(shard_paths)
    finally:
        aggregator.stop("failed" if failed else "completed")
    return output_paths


def run_distributed_eval(
    shards_config: ShardsConfig,
    spec: EvalJobSpec,
    *,
    progress_dir: Path,
    run_id_prefix: str,
    total_games: int,
    queue_url: str,
    bundle_url: Optional[str] = None,
) -> dict[str, int]:
    """Eval counterpart to ``run_distributed_self_play``. Initializes
    a queue of ``total_games``, dispatches every shard concurrently
    to play eval games (new vs old), and returns the cluster-aggregate
    counts as a dict::

        {"n_games": int, "wins_new": int, "wins_old": int,
         "draws": int, "crashed": int}

    The orchestrator's caller (typically iterate's eval-gate) maps
    this onto its existing ``MatchStats`` shape.
    """
    import threading as _threading
    import urllib.request
    import json as _json

    stamp = _now_stamp()
    progress_dir.mkdir(parents=True, exist_ok=True)

    init_url = f"{queue_url.rstrip('/')}/queue/init"
    init_body = _json.dumps({
        "run_id": run_id_prefix,
        "total_games": total_games,
    }).encode("utf-8")
    req = urllib.request.Request(
        init_url, data=init_body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status != 200:
            raise RuntimeError(
                f"queue init failed at {init_url}: HTTP {resp.status}"
            )

    totals = {
        "n_games": 0, "wins_new": 0, "wins_old": 0,
        "draws": 0, "crashed": 0,
    }
    totals_lock = _threading.Lock()

    def _local_runner(shard: ShardConfig) -> dict[str, int]:
        n_workers = shard.n_workers
        if n_workers is None:
            import os
            n_workers = max(1, (os.cpu_count() or 1) - 2)
        return run_shard_eval_pull(
            spec,
            queue_url=_loopback_queue_url(queue_url),
            run_id=run_id_prefix,
            n_workers=n_workers,
            label=shard.display_label,
            iter_total_games=total_games,
            progress_dir=progress_dir,
        )

    def _remote_runner(shard: ShardConfig) -> dict[str, int]:
        return run_shard_eval_remote(
            shard, spec,
            queue_url=queue_url,
            run_id=run_id_prefix,
            iter_total_games=total_games,
            progress_dir=progress_dir,
            stamp=stamp,
            bundle_url=bundle_url,
        )

    aggregator = _AggregateProgressPoller(
        progress_dir=progress_dir,
        run_id=run_id_prefix,
        n_games_total=total_games,
        kind="eval",
        opponent_label=spec.opponent_label,
    )
    aggregator.start()

    futures: dict[concurrent.futures.Future, ShardConfig] = {}
    n_threads = max(1, len(shards_config.shards))
    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=n_threads, thread_name_prefix="dist-eval",
    )
    try:
        for shard in shards_config.shards:
            runner = _local_runner if shard.is_local else _remote_runner
            futures[executor.submit(runner, shard)] = shard
    finally:
        executor.shutdown(wait=False)

    failed = False
    try:
        for fut in concurrent.futures.as_completed(futures):
            try:
                shard_counts = fut.result()
            except BaseException:
                failed = True
                raise
            with totals_lock:
                for k in totals:
                    totals[k] += int(shard_counts.get(k, 0))
    finally:
        aggregator.stop("failed" if failed else "completed")
    return totals


class EventLog:
    """JSONL event log per shard. One JSON object per line:
    ``{"ts": <iso8601>, "event": <type>, ...kwargs}``. Plain stdlib
    so it ships with the worker over SSH (no extra deps on remotes).
    Thread-safe for the in-process master shard's case where the
    orchestrator and the pool driver may both write.

    Sits next to the per-shard progress JSON in ``progress_dir`` so
    everything observability-related is in one place. ``run_shard_
    remote`` scps it back to the master at end-of-shard so analysis
    on the host has every machine's events in one file tree.

    Truncates the file on construction: re-running the same iter
    (retries after a crash, repeated test runs) replaces the prior
    events file rather than appending to it.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def record(self, event: str, **kwargs: Any) -> None:
        """Append one line. ``default=str`` swallows non-JSON-native
        values (Path, datetime, etc.) into their string repr — the
        log is for human + ad-hoc analysis, not strict round-trip."""
        line = json.dumps(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "event": event,
                **kwargs,
            },
            default=str,
        )
        with self._lock, self._path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def _machine_metadata() -> dict[str, Any]:
    """Best-effort machine info captured once per shard at startup.
    Useful when one shard's results look weird and you want to know
    "did this run on the M2 Mac or the 1080Ti box; same torch
    version?". Cheap enough that we always emit it."""
    import os
    import platform
    info: dict[str, Any] = {
        "host": platform.node(),
        "platform": platform.platform(),
        "python_version": sys.version.split()[0],
        "cpu_count": os.cpu_count(),
    }
    try:  # noqa: SIM105
        import torch  # type: ignore
        info["torch_version"] = torch.__version__
        info["cuda_available"] = bool(torch.cuda.is_available())
    except Exception:  # noqa: BLE001
        pass
    return info


def _weights_digest(weights_path: str) -> Optional[str]:
    """SHA-256 hex prefix of the weights file. Lets cross-machine
    analysis confirm "same weights ran on every shard" — a stale
    weights file on one remote would silently bias the iter's
    training mix toward that worker's policy."""
    try:
        import hashlib
        h = hashlib.sha256()
        with open(weights_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()[:16]
    except OSError:
        return None


def _play_one_parallel_game_timed(args: tuple) -> tuple:
    """Wrap ``_play_one_parallel_game`` with a ``perf_counter`` pair
    so the pull-mode worker gets per-game wall time without engine
    instrumentation. Top-level so multiprocessing can pickle it
    across the spawn boundary.

    Returns ``(game_idx, chunk, wall_seconds)``. ``chunk`` is the
    same 5-tuple the original wrapper returns.
    """
    import time as _time

    from mtg_bot.training.data_gen import _play_one_parallel_game
    t0 = _time.perf_counter()
    game_idx, chunk = _play_one_parallel_game(args)
    return game_idx, chunk, _time.perf_counter() - t0


def _play_one_match_game_timed(args: tuple) -> tuple:
    """Eval shard worker. Wraps the seat-alternating match player
    with ``perf_counter`` so we get per-game wall time. The
    alternating variant swaps factories on odd ``game_idx`` and
    remaps the returned winner — neutralizes the engine's seat-0
    advantage so wins[0] across a match means "the original
    ``p0_factory`` won" without a structural bias.

    Returns ``(game_idx, (winner, decisions), wall_seconds)``.
    """
    import time as _time

    from mtg_bot.training.self_play import (  # type: ignore
        _play_one_match_game_alternating_indexed,
    )
    t0 = _time.perf_counter()
    game_idx, result = _play_one_match_game_alternating_indexed(args)
    return game_idx, result, _time.perf_counter() - t0


def run_shard_pull(
    spec: SelfPlayJobSpec,
    *,
    queue_url: str,
    run_id: str,
    n_workers: int,
    output_dir: Path,
    label: str,
    stamp: str,
    iter_total_games: int,
    progress_dir: Optional[Path] = None,
) -> list[Path]:
    """Continuously feed ``n_workers`` worker processes from the
    master's pull-queue. Each worker plays one game, returns its
    chunk, then is given the next available game. Loop until the
    queue is drained AND all in-flight games have finished.

    Maximum concurrency = ``n_workers``; each ``/queue/take`` pulls
    one game (the worker that just freed up gets the next idx). Per-
    game completions are accumulated; an npz is flushed every
    ``n_workers`` games for crash resilience and reasonable file
    granularity, plus one final flush at shard end.

    Per-shard progress JSON gets ``n_games_total = iter_total_games``
    so the training UI shows "this shard did X of Y" honestly — pull
    mode doesn't know in advance how many games each shard will run.
    """
    import concurrent.futures as _cf
    import json as _json
    import time as _time
    import urllib.request

    from mtg_bot.decks import decks_from_json
    from mtg_bot.training import (
        NNPimcConfig, save_dataset,
    )
    from mtg_bot.training.data_gen import (
        ReplayCaptureConfig, _concat_chunks,
        _winner_to_p0_outcome,
    )
    from mtg_bot.training.progress import DataGenProgress

    cfg = NNPimcConfig(
        weights_path=spec.weights_path,
        samples=spec.samples,
        inner_nodes=spec.inner_nodes,
        batch_size=32,
        with_policy=spec.with_policy,
        puct=True,
        hidden_sizes=spec.hidden_sizes,
        use_ismcts=spec.use_ismcts,
        use_belief_weighted=spec.use_belief_weighted,
    )
    factory = cfg.build

    deck_pool = None
    if spec.deck_pool_path is not None:
        deck_pool = decks_from_json(Path(spec.deck_pool_path))

    replay_config: Optional[ReplayCaptureConfig] = None
    replays_subdir: Optional[str] = None
    if spec.capture_every > 0 and spec.replays_root is not None:
        replays_subdir = str(
            Path(spec.replays_root) / f"{run_id}_shard_{label}"
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
            Path(spec.hang_dump_root) / f"{run_id}_shard_{label}"
        )

    progress: Optional[DataGenProgress] = None
    events: Optional[EventLog] = None
    if progress_dir is not None:
        progress_dir.mkdir(parents=True, exist_ok=True)
        progress = DataGenProgress(
            progress_path=progress_dir / f"{run_id}_shard_{label}.json",
            run_id=f"{run_id}_shard_{label}",
            n_games_total=iter_total_games,
            n_workers=n_workers,
            command="distributed_self_play (pull-mode shard)",
            notes=(
                f"pull-mode shard {label} (one of N workers in iter "
                f"{run_id})"
            ),
            replays_dir=replays_subdir,
        )
        progress.begin()
        events = EventLog(
            progress_dir / f"{run_id}_shard_{label}_events.jsonl"
        )
        events.record(
            "shard_start",
            run_id=run_id,
            label=label,
            iter_total_games=iter_total_games,
            n_workers=n_workers,
            base_seed=spec.base_seed,
            samples=spec.samples,
            inner_nodes=spec.inner_nodes,
            weights_path=spec.weights_path,
            weights_digest=_weights_digest(spec.weights_path),
            machine=_machine_metadata(),
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    take_url = f"{queue_url.rstrip('/')}/queue/take"
    npz_paths: list[Path] = []
    chunk_idx = 0
    n_games_completed = 0
    n_games_crashed = 0
    pending_chunks: list = []
    flush_every = max(1, n_workers)

    def _take_one() -> tuple[Optional[int], int, float]:
        req_body = _json.dumps({
            "run_id": run_id, "batch_size": 1,
        }).encode("utf-8")
        req = urllib.request.Request(
            take_url, data=req_body,
            headers={"Content-Type": "application/json"},
        )
        take_t0 = _time.perf_counter()
        with urllib.request.urlopen(req, timeout=30) as resp:
            response = _json.loads(resp.read().decode("utf-8"))
        take_wall = _time.perf_counter() - take_t0
        games = response.get("games", [])
        return (
            games[0] if games else None,
            response.get("remaining", 0),
            take_wall,
        )

    def _build_args(game_idx: int) -> tuple:
        return (
            game_idx, factory, factory, spec.base_seed,
            spec.decision_cap, spec.sample_every,
            replay_config, deck_pool,
            spec.enable_mulligans, spec.per_game_timeout_sec,
            hang_dump_dir, spec.phase_prune_enabled,
            spec.force_landdrop_enabled,
            spec.skip_empty_combat_enabled,
            spec.skip_opp_postcombat_main_enabled,
            spec.skip_dead_main1_enabled,
        )

    def _flush() -> None:
        nonlocal chunk_idx
        if not pending_chunks:
            return
        f, o, p, m = _concat_chunks(
            [c[:4] for _, c, _ in pending_chunks]
        )
        output_path = output_dir / (
            f"{run_id}_shard_{label}_chunk_"
            f"{chunk_idx:04d}_{stamp}.npz"
        )
        save_dataset(
            f, o, output_path,
            policy_targets=p, action_masks=m,
        )
        npz_paths.append(output_path)
        if events is not None:
            events.record(
                "batch_saved",
                chunk_idx=chunk_idx,
                npz_path=str(output_path),
                n_samples=int(f.shape[0]) if f.size else 0,
                n_games=len(pending_chunks),
            )
        chunk_idx += 1
        pending_chunks.clear()

    shard_t0 = _time.perf_counter()
    try:
        with _cf.ProcessPoolExecutor(max_workers=n_workers) as exe:
            in_flight: dict[_cf.Future, int] = {}
            queue_drained = False
            while True:
                while len(in_flight) < n_workers and not queue_drained:
                    game_idx, remaining, take_wall = _take_one()
                    if events is not None:
                        events.record(
                            "game_take",
                            game_idx=game_idx,
                            remaining_after=remaining,
                            take_wall_s=take_wall,
                            in_flight=len(in_flight),
                        )
                    if game_idx is None:
                        queue_drained = True
                        break
                    fut = exe.submit(
                        _play_one_parallel_game_timed,
                        _build_args(game_idx),
                    )
                    in_flight[fut] = game_idx
                if not in_flight:
                    break
                done, _pending = _cf.wait(
                    list(in_flight.keys()),
                    return_when=_cf.FIRST_COMPLETED,
                )
                for fut in done:
                    in_flight.pop(fut)
                    game_idx, chunk, wall_s = fut.result()
                    n_samples = int(chunk[0].shape[0])
                    crashed = n_samples == 0 and chunk[4] is None
                    if crashed:
                        n_games_crashed += 1
                    n_games_completed += 1
                    if progress is not None:
                        if crashed:
                            progress.record_game(crashed=True)
                        else:
                            progress.record_game(
                                n_samples=n_samples,
                                outcome_p0=_winner_to_p0_outcome(
                                    chunk[4],
                                ),
                            )
                    if events is not None:
                        events.record(
                            "game_end",
                            game_idx=int(game_idx),
                            wall_s=wall_s,
                            n_samples=n_samples,
                            winner=chunk[4],
                            crashed=crashed,
                        )
                    pending_chunks.append((game_idx, chunk, wall_s))
                    if len(pending_chunks) >= flush_every:
                        _flush()
            _flush()
    except BaseException as exc:
        try:
            _flush()
        except Exception:  # noqa: BLE001
            pass
        if progress is not None:
            progress.finalize(status="failed")
        if events is not None:
            events.record(
                "shard_end",
                status="failed",
                error=repr(exc),
                n_games_completed=n_games_completed,
                n_games_crashed=n_games_crashed,
                n_batches=chunk_idx,
                wall_s=_time.perf_counter() - shard_t0,
            )
        raise
    if progress is not None:
        progress.finalize(status="completed")
    if events is not None:
        events.record(
            "shard_end",
            status="completed",
            n_games_completed=n_games_completed,
            n_games_crashed=n_games_crashed,
            n_batches=chunk_idx,
            wall_s=_time.perf_counter() - shard_t0,
        )
    return npz_paths


def run_shard_eval_pull(
    spec: EvalJobSpec,
    *,
    queue_url: str,
    run_id: str,
    n_workers: int,
    label: str,
    iter_total_games: int,
    progress_dir: Optional[Path] = None,
) -> dict[str, int]:
    """Eval counterpart to ``run_shard_pull``: continuously feeds
    n_workers worker processes from the master's pull-queue, where
    each game is one match (new-NN seat 0 vs old-NN-or-heuristic
    seat 1). Returns the shard's aggregated counts as a dict so the
    orchestrator can sum across shards into a single ``MatchStats``.
    """
    import concurrent.futures as _cf
    import json as _json
    import time as _time
    import urllib.request

    from mtg_bot.decks import decks_from_json
    from mtg_bot.training import NNPimcConfig
    from mtg_bot.training.config import HeuristicConfig, PimcConfig
    from mtg_bot.training.data_gen import ReplayCaptureConfig
    from mtg_bot.training.progress import EvalProgress

    new_cfg = NNPimcConfig(
        weights_path=spec.new_weights_path,
        samples=spec.samples, inner_nodes=spec.inner_nodes,
        batch_size=32, with_policy=True, puct=True,
        hidden_sizes=spec.hidden_sizes,
        use_ismcts=spec.use_ismcts,
        use_belief_weighted=spec.use_belief_weighted,
    )
    if spec.old_weights_path is not None:
        old_cfg = NNPimcConfig(
            weights_path=spec.old_weights_path,
            samples=spec.samples, inner_nodes=spec.inner_nodes,
            batch_size=32, with_policy=True, puct=True,
            hidden_sizes=spec.hidden_sizes,
            use_ismcts=spec.use_ismcts,
            use_belief_weighted=spec.use_belief_weighted,
        )
        p1_factory = old_cfg.build
    else:
        p1_factory = PimcConfig(
            samples=spec.samples, inner_nodes=spec.inner_nodes,
            heuristic=HeuristicConfig(), batch_size=1,
        ).build
    p0_factory = new_cfg.build

    deck_pool = None
    if spec.deck_pool_path is not None:
        deck_pool = decks_from_json(Path(spec.deck_pool_path))

    replay_config: Optional[ReplayCaptureConfig] = None
    replays_subdir: Optional[str] = None
    if spec.capture_every > 0 and spec.replays_root is not None:
        replays_subdir = str(
            Path(spec.replays_root) / f"{run_id}_shard_{label}"
        )
        Path(replays_subdir).mkdir(parents=True, exist_ok=True)
        replay_config = ReplayCaptureConfig(
            save_dir=replays_subdir,
            capture_every=spec.capture_every,
            nn_weights_path=spec.new_weights_path,
            nn_version_label=spec.nn_new_version_label,
            nn_hidden_sizes=spec.hidden_sizes,
            nn_with_policy=True,
        )

    hang_dump_dir: Optional[str] = None
    if spec.hang_dump_root is not None:
        hang_dump_dir = str(
            Path(spec.hang_dump_root) / f"{run_id}_shard_{label}"
        )

    progress: Optional[EvalProgress] = None
    events: Optional[EventLog] = None
    if progress_dir is not None:
        progress_dir.mkdir(parents=True, exist_ok=True)
        progress = EvalProgress(
            progress_path=progress_dir / f"{run_id}_shard_{label}.json",
            run_id=f"{run_id}_shard_{label}",
            n_games_total=iter_total_games,
            n_workers=n_workers,
            opponent_label=spec.opponent_label,
            command="distributed_eval (pull-mode shard)",
            notes=(
                f"pull-mode eval shard {label} (one of N workers in "
                f"iter {run_id})"
            ),
            replays_dir=replays_subdir,
        )
        progress.begin()
        events = EventLog(
            progress_dir / f"{run_id}_shard_{label}_events.jsonl"
        )
        events.record(
            "shard_start",
            run_id=run_id, label=label, mode="eval",
            iter_total_games=iter_total_games,
            n_workers=n_workers,
            base_seed=spec.base_seed,
            samples=spec.samples, inner_nodes=spec.inner_nodes,
            new_weights_path=spec.new_weights_path,
            old_weights_path=spec.old_weights_path,
            new_weights_digest=_weights_digest(spec.new_weights_path),
            old_weights_digest=(
                _weights_digest(spec.old_weights_path)
                if spec.old_weights_path else None
            ),
            machine=_machine_metadata(),
        )

    take_url = f"{queue_url.rstrip('/')}/queue/take"
    wins_new = 0
    wins_old = 0
    draws = 0
    crashed = 0
    n_games = 0

    def _take_one() -> tuple[Optional[int], int, float]:
        req_body = _json.dumps({
            "run_id": run_id, "batch_size": 1,
        }).encode("utf-8")
        req = urllib.request.Request(
            take_url, data=req_body,
            headers={"Content-Type": "application/json"},
        )
        take_t0 = _time.perf_counter()
        with urllib.request.urlopen(req, timeout=30) as resp:
            response = _json.loads(resp.read().decode("utf-8"))
        take_wall = _time.perf_counter() - take_t0
        games = response.get("games", [])
        return (
            games[0] if games else None,
            response.get("remaining", 0),
            take_wall,
        )

    def _build_args(game_idx: int) -> tuple:
        return (
            game_idx, p0_factory, p1_factory, spec.base_seed,
            4000,  # decision_cap, mirrors run_match's default
            spec.enable_mulligans, spec.per_game_timeout_sec,
            deck_pool, replay_config, hang_dump_dir,
            spec.phase_prune_enabled,
            spec.force_landdrop_enabled,
            spec.skip_empty_combat_enabled,
            spec.skip_opp_postcombat_main_enabled,
            spec.skip_dead_main1_enabled,
        )

    shard_t0 = _time.perf_counter()
    try:
        with _cf.ProcessPoolExecutor(max_workers=n_workers) as exe:
            in_flight: dict[_cf.Future, int] = {}
            queue_drained = False
            while True:
                while len(in_flight) < n_workers and not queue_drained:
                    game_idx, remaining, take_wall = _take_one()
                    if events is not None:
                        events.record(
                            "game_take",
                            game_idx=game_idx,
                            remaining_after=remaining,
                            take_wall_s=take_wall,
                            in_flight=len(in_flight),
                        )
                    if game_idx is None:
                        queue_drained = True
                        break
                    fut = exe.submit(
                        _play_one_match_game_timed,
                        _build_args(game_idx),
                    )
                    in_flight[fut] = game_idx
                if not in_flight:
                    break
                done, _pending = _cf.wait(
                    list(in_flight.keys()),
                    return_when=_cf.FIRST_COMPLETED,
                )
                for fut in done:
                    in_flight.pop(fut)
                    game_idx, (winner, decisions), wall_s = fut.result()
                    is_crash = winner is None and decisions == 0
                    n_games += 1
                    if is_crash:
                        crashed += 1
                    elif winner == 0:
                        wins_new += 1
                    elif winner == 1:
                        wins_old += 1
                    else:
                        draws += 1
                    if progress is not None:
                        progress.record_game(
                            winner=winner, decisions=decisions,
                            crashed=is_crash,
                        )
                    if events is not None:
                        events.record(
                            "game_end",
                            game_idx=int(game_idx),
                            wall_s=wall_s,
                            winner=winner,
                            decisions=decisions,
                            crashed=is_crash,
                        )
    except BaseException as exc:
        if progress is not None:
            progress.finalize(status="failed")
        if events is not None:
            events.record(
                "shard_end",
                status="failed",
                error=repr(exc),
                n_games=n_games, wins_new=wins_new,
                wins_old=wins_old, draws=draws, crashed=crashed,
                wall_s=_time.perf_counter() - shard_t0,
            )
        raise
    if progress is not None:
        progress.finalize(status="completed")
    if events is not None:
        events.record(
            "shard_end",
            status="completed",
            n_games=n_games, wins_new=wins_new,
            wins_old=wins_old, draws=draws, crashed=crashed,
            wall_s=_time.perf_counter() - shard_t0,
        )
    return {
        "n_games": n_games,
        "wins_new": wins_new,
        "wins_old": wins_old,
        "draws": draws,
        "crashed": crashed,
    }


def _is_windows_remote(shard: ShardConfig) -> bool:
    """Cheap heuristic to pick remote path semantics: ``.exe`` ending
    on the venv python path is unambiguously Windows. POSIX shells
    don't use that suffix."""
    return (shard.venv_python or "").endswith(".exe")


def _remote_join(shard: ShardConfig, *parts: str) -> str:
    """Join path parts using the remote's OS conventions. We don't
    actually run on the remote — this just produces the string the
    remote shell will interpret.

    POSIX: ``/`` separator via ``PurePosixPath``.

    Windows: all forward slashes, even inside ``C:\\Users\\...`` —
    cmd.exe handles ``C:/Users/...`` fine, AND scp's quoting layer
    rejects mixed-separator paths like ``C:\\Users\\.../sub/file``
    (it double-escapes the backslashes and the SSH server can't
    find the path). So we rewrite every backslash in each input to
    ``/`` and join with ``/``.
    """
    if _is_windows_remote(shard):
        return "/".join(p.replace("\\", "/") for p in parts)
    return str(PurePosixPath(*parts))


def _ssh_target(shard: ShardConfig) -> str:
    return f"{shard.user}@{shard.host}"


def _ssh_cmd(shard: ShardConfig, remote_command: str) -> list[str]:
    """SSH invocation for a shell command on the remote. Sends one
    argument string the remote shell will interpret. The remote
    shell is bash on POSIX and cmd.exe on Windows OpenSSH-Server
    default — both handle ``&&`` and simple variable assignment, so
    a single command string portable to both is achievable.
    """
    return [
        "ssh",
        "-o", "BatchMode=yes",      # never prompt for password
        "-o", "StrictHostKeyChecking=accept-new",
        "-p", str(shard.ssh_port),
        _ssh_target(shard),
        remote_command,
    ]


def _scp_cmd(
    shard: ShardConfig, src: str, dst: str, *, from_remote: bool,
) -> list[str]:
    """``scp`` invocation. ``from_remote=True`` pulls from remote to
    local; ``False`` pushes."""
    target = _ssh_target(shard)
    if from_remote:
        return [
            "scp", "-P", str(shard.ssh_port),
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new",
            f"{target}:{src}", str(dst),
        ]
    return [
        "scp", "-P", str(shard.ssh_port),
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        str(src), f"{target}:{dst}",
    ]


def _run_subprocess(
    cmd: list[str], *, timeout: Optional[float] = None,
) -> subprocess.CompletedProcess:
    """Wrapper that captures both streams + raises on non-zero exit.
    Also gives us ONE place to instrument later (logging, retry)."""
    return subprocess.run(
        cmd, capture_output=True, text=True,
        timeout=timeout, check=True,
    )


def _build_remote_pull_command(
    shard: ShardConfig,
    spec: SelfPlayJobSpec,
    *,
    queue_url: str,
    run_id: str,
    iter_total_games: int,
    stamp: str,
) -> str:
    """Produce the one-line shell command the remote runs to start
    its pull-mode worker. Same wrapper script as the master's local
    shard uses, just invoked over SSH.

    Spec + shard configs ride as base64-encoded JSON to avoid
    quoting hazards across cmd.exe vs bash. ``queue_url`` is plain
    ASCII (no quoting needed); the rest of the args are integers
    or short strings.
    """
    import base64
    spec_b64 = base64.b64encode(
        json.dumps(spec.to_dict()).encode("utf-8"),
    ).decode("ascii")
    shard_b64 = base64.b64encode(
        json.dumps(shard.to_dict()).encode("utf-8"),
    ).decode("ascii")

    args = (
        f"scripts/run_self_play_shard.py "
        f"--mode=pull "
        f"--spec-b64={spec_b64} "
        f"--shard-b64={shard_b64} "
        f"--queue-url={queue_url} "
        f"--run-id={run_id} "
        f"--iter-total-games={iter_total_games} "
        f"--stamp={stamp}"
    )
    repo_path = shard.repo_path or ""
    venv_python = shard.venv_python or ""
    if _is_windows_remote(shard):
        return (
            f'cd /d "{repo_path}" && '
            f'set PYTHONPATH=src && '
            f'"{venv_python}" {args}'
        )
    return (
        f'cd {shlex.quote(repo_path)} && '
        f'PYTHONPATH=src {shlex.quote(venv_python)} {args}'
    )


def _build_remote_eval_command(
    shard: ShardConfig,
    spec: EvalJobSpec,
    *,
    queue_url: str,
    run_id: str,
    iter_total_games: int,
    stamp: str,
) -> str:
    """Eval counterpart to ``_build_remote_pull_command``. Same shape;
    ``--mode=eval`` and an ``EvalJobSpec`` instead of ``SelfPlayJobSpec``.
    """
    import base64
    spec_b64 = base64.b64encode(
        json.dumps(spec.to_dict()).encode("utf-8"),
    ).decode("ascii")
    shard_b64 = base64.b64encode(
        json.dumps(shard.to_dict()).encode("utf-8"),
    ).decode("ascii")

    args = (
        f"scripts/run_self_play_shard.py "
        f"--mode=eval "
        f"--spec-b64={spec_b64} "
        f"--shard-b64={shard_b64} "
        f"--queue-url={queue_url} "
        f"--run-id={run_id} "
        f"--iter-total-games={iter_total_games} "
        f"--stamp={stamp}"
    )
    repo_path = shard.repo_path or ""
    venv_python = shard.venv_python or ""
    if _is_windows_remote(shard):
        return (
            f'cd /d "{repo_path}" && '
            f'set PYTHONPATH=src && '
            f'"{venv_python}" {args}'
        )
    return (
        f'cd {shlex.quote(repo_path)} && '
        f'PYTHONPATH=src {shlex.quote(venv_python)} {args}'
    )


class _ProgressPoller:
    """Periodically scp the remote's per-shard progress JSON back to
    the master so the training UI shows live updates. Stops when
    ``stop()`` is called. Errors are swallowed — a failed scp on
    one tick must not break the run; the next tick retries.
    """

    def __init__(
        self,
        shard: ShardConfig,
        remote_progress_path: str,
        local_progress_path: Path,
        interval_s: float = 5.0,
    ) -> None:
        self._shard = shard
        self._remote_path = remote_progress_path
        self._local_path = local_progress_path
        self._interval_s = interval_s
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._loop,
            name=f"progress-poll-{self._shard.display_label}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=10.0)

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                cmd = _scp_cmd(
                    self._shard,
                    self._remote_path, str(self._local_path),
                    from_remote=True,
                )
                # Don't raise on non-zero: the file may not yet
                # exist on the remote (worker startup).
                subprocess.run(
                    cmd, capture_output=True, text=True,
                    timeout=self._interval_s + 5,
                )
            except Exception:  # noqa: BLE001
                pass
            self._stop_event.wait(self._interval_s)


def _build_remote_mkdir_command(
    shard: ShardConfig, remote_dir: str,
) -> str:
    """Idempotent ``mkdir -p`` equivalent for the remote shell. cmd.exe
    ``mkdir`` is finicky over OpenSSH-Server (silently fails on
    existing dirs), so on Windows we route through PowerShell's
    ``New-Item -Force`` which is genuinely idempotent."""
    if _is_windows_remote(shard):
        return (
            f"powershell -Command \"New-Item -ItemType Directory "
            f"-Force -Path '{remote_dir}'\""
        )
    return f"mkdir -p {shlex.quote(remote_dir)}"


def _build_remote_bundle_sync_command(
    shard: ShardConfig, bundle_url: str,
) -> str:
    """Sync the remote's working tree to the latest master commits
    via a Tailscale-served git bundle. Avoids needing GitHub auth on
    the remote (curl gets the bundle over Tailscale; git fetches
    from the local bundle file; git reset --hard advances HEAD).

    Refspec ``main`` is hard-coded — that's what iterate runs from.
    Other branches stay on whatever they were.
    """
    repo_path = shard.repo_path or ""
    if _is_windows_remote(shard):
        return (
            f'cd /d "{repo_path}" && '
            f'curl.exe -sSL {bundle_url} -o "%TEMP%\\repo.bundle" && '
            f'git fetch "%TEMP%\\repo.bundle" main && '
            f'git reset --hard FETCH_HEAD'
        )
    return (
        f'cd {shlex.quote(repo_path)} && '
        f'curl -sSL {bundle_url} -o /tmp/repo.bundle && '
        f'git fetch /tmp/repo.bundle main && '
        f'git reset --hard FETCH_HEAD'
    )


def _push_weights_to_remote(
    shard: ShardConfig, remote_repo: str, weights_path: str,
) -> None:
    """scp ``<master_cwd>/<weights_path>`` to ``<repo_path>/<weights_path>``
    on the remote. Idempotent ``mkdir`` first so the parent dir exists.
    Failures propagate — a missing weights file on the remote silently
    breaks the shard."""
    print(
        f"[shard {shard.display_label}] pushing weights "
        f"{weights_path} to {shard.host}...",
        file=sys.stderr,
    )
    local_weights = (Path.cwd() / weights_path).resolve()
    weights_posix = weights_path.replace("\\", "/")
    remote_weights = _remote_join(shard, remote_repo, weights_posix)
    remote_weights_parent = _remote_join(
        shard, remote_repo, str(PurePosixPath(weights_posix).parent),
    )
    _run_subprocess(
        _ssh_cmd(shard, _build_remote_mkdir_command(
            shard, remote_weights_parent,
        )),
        timeout=30,
    )
    _run_subprocess(
        _scp_cmd(
            shard, str(local_weights), remote_weights,
            from_remote=False,
        ),
        timeout=300,
    )


def _pull_remote_replays(
    shard: ShardConfig,
    remote_repo: str,
    replays_root: Optional[str],
    capture_every: int,
    run_id_full: str,
) -> None:
    """scp every per-game ``.json.gz`` replay from the remote shard's
    replay subdir back to the master's matching subdir, mirroring what
    ``run_shard_local`` writes directly. No-op when capture is off
    (``capture_every <= 0`` or ``replays_root is None``).

    Mirrors the ls+scp loop used for npz collection. The remote shell
    listing returns no-match exit code (``ls`` / ``dir /b``) when the
    shard captured zero games; we treat that as zero files and return
    silently rather than raising.
    """
    if capture_every <= 0 or replays_root is None:
        return

    replays_posix = replays_root.replace("\\", "/")
    local_replays_dir = (
        Path.cwd() / replays_posix / run_id_full
    )
    print(
        f"[shard {shard.display_label}] collecting replays from "
        f"{shard.host}...",
        file=sys.stderr,
    )
    if _is_windows_remote(shard):
        replays_backslash = replays_posix.replace("/", "\\")
        list_cmd = (
            f'cd /d "{remote_repo}" && '
            f'dir /b {replays_backslash}\\{run_id_full}\\*.json.gz '
            f'2>nul'
        )
    else:
        list_cmd = (
            f'cd {shlex.quote(remote_repo)} && '
            f'ls {replays_posix}/{run_id_full}/*.json.gz '
            f'2>/dev/null | xargs -n1 basename'
        )
    list_proc = subprocess.run(
        _ssh_cmd(shard, list_cmd),
        capture_output=True, text=True, timeout=30,
    )
    basenames = [
        line.strip() for line in list_proc.stdout.splitlines()
        if line.strip()
    ]
    if not basenames:
        return
    local_replays_dir.mkdir(parents=True, exist_ok=True)
    for basename in basenames:
        remote_replay = _remote_join(
            shard, remote_repo, replays_posix, run_id_full, basename,
        )
        local_replay = local_replays_dir / basename
        _run_subprocess(
            _scp_cmd(
                shard, remote_replay, str(local_replay),
                from_remote=True,
            ),
            timeout=120,
        )


def run_shard_remote(
    shard: ShardConfig,
    spec: SelfPlayJobSpec,
    *,
    queue_url: str,
    run_id: str,
    iter_total_games: int,
    progress_dir: Path,
    output_dir: Path,
    run_id_prefix: str,
    stamp: str,
    bundle_url: Optional[str] = None,
) -> list[Path]:
    """Run one shard on a remote machine in pull mode.

    Sequence:
    1. Code sync from master's git bundle (if ``bundle_url`` is set).
    2. Push the master's current weights file to the remote at the
       same relative path. Failures here propagate — a stale weights
       file on the remote silently produces zero-sample games.
    3. Start a poller that periodically scps the remote progress
       JSON back for the master UI.
    4. Block on ``ssh ... run_self_play_shard.py --mode=pull`` —
       the wrapper loops fetching from /queue/take until empty.
    5. Stop poller; final progress scp.
    6. scp every per-batch npz back to ``output_dir``. Filenames
       follow ``{run_id}_shard_{label}_chunk_{NNNN}_{stamp}.npz``,
       which is what ``run_shard_pull`` writes server-side.

    Returns the list of local-side npz paths (one per batch the
    remote produced). The orchestrator concatenates lists across
    all shards.

    Raises ``subprocess.CalledProcessError`` on SSH/SCP non-zero
    exits — the caller re-surfaces it.
    """
    run_id_full = f"{run_id}_shard_{shard.display_label}"

    output_dir.mkdir(parents=True, exist_ok=True)
    progress_dir.mkdir(parents=True, exist_ok=True)
    local_progress_path = progress_dir / f"{run_id_full}.json"
    local_events_path = progress_dir / f"{run_id_full}_events.jsonl"

    remote_repo = shard.repo_path or ""
    remote_progress = _remote_join(
        shard, remote_repo, "training_progress", f"{run_id_full}.json",
    )
    remote_events = _remote_join(
        shard, remote_repo, "training_progress",
        f"{run_id_full}_events.jsonl",
    )
    # Per-shard npz output dir on the remote.
    remote_iterate_data = _remote_join(
        shard, remote_repo, "iterate_data",
    )

    # 1. Code sync.
    if bundle_url:
        print(
            f"[shard {shard.display_label}] sync from bundle on "
            f"{shard.host}...", file=sys.stderr,
        )
        sync_cmd = _build_remote_bundle_sync_command(shard, bundle_url)
        _run_subprocess(_ssh_cmd(shard, sync_cmd), timeout=300)

    # 2. Weight push. Without this, iter #2+ silently produces
    # samples=0 games on remotes because their weights file is stale
    # or missing.
    _push_weights_to_remote(shard, remote_repo, spec.weights_path)

    # 3. Progress poller.
    poller = _ProgressPoller(
        shard,
        remote_progress_path=remote_progress,
        local_progress_path=local_progress_path,
    )
    poller.start()

    # 4. The actual pull-mode invocation. Blocks until queue drains.
    print(
        f"[shard {shard.display_label}] pull-mode self-play on "
        f"{shard.host}...",
        file=sys.stderr,
    )
    try:
        run_cmd = _build_remote_pull_command(
            shard, spec,
            queue_url=queue_url,
            run_id=run_id,
            iter_total_games=iter_total_games,
            stamp=stamp,
        )
        # No timeout — the run loops indefinitely waiting on master.
        _run_subprocess(_ssh_cmd(shard, run_cmd))
    finally:
        poller.stop()
        # Final progress JSON snapshot.
        try:
            _run_subprocess(
                _scp_cmd(
                    shard, remote_progress, str(local_progress_path),
                    from_remote=True,
                ),
                timeout=30,
            )
        except Exception:  # noqa: BLE001
            pass
        # Pull the JSONL event log too — this is where machine
        # metadata, per-game wall times, and per-batch throughput
        # live for cross-machine analysis. Failure isn't fatal: if
        # the shard crashed before opening the file there's nothing
        # to fetch, but we still want the npzs back.
        try:
            _run_subprocess(
                _scp_cmd(
                    shard, remote_events, str(local_events_path),
                    from_remote=True,
                ),
                timeout=30,
            )
        except Exception:  # noqa: BLE001
            pass

    # 5. Pull all per-batch npzs back. The remote wrote them under
    # iterate_data/ with a known prefix; we glob via SSH ``ls`` + scp
    # each. (Bulk scp of a glob has shell-quoting issues across cmd
    # vs bash, so we list + transfer one at a time.)
    print(
        f"[shard {shard.display_label}] collecting per-batch npzs"
        f" from {shard.host}...",
        file=sys.stderr,
    )
    prefix = f"{run_id}_shard_{shard.display_label}_chunk_"
    if _is_windows_remote(shard):
        # cmd.exe: ``dir /b`` lists basenames only.
        list_cmd = (
            f'cd /d "{remote_repo}" && '
            f'dir /b iterate_data\\{prefix}*.npz 2>nul'
        )
    else:
        list_cmd = (
            f'cd {shlex.quote(remote_repo)} && '
            f'ls iterate_data/{prefix}*.npz 2>/dev/null '
            f'| xargs -n1 basename'
        )
    # Don't ``check=True`` here: a shard that lost every batch race
    # (or whose self-play crashed before producing any output) is
    # not a bug at the listing layer. Both ``dir /b`` and ``ls`` exit
    # non-zero on no-match; we treat that as zero files and move on.
    list_proc = subprocess.run(
        _ssh_cmd(shard, list_cmd),
        capture_output=True, text=True, timeout=30,
    )
    basenames = [
        line.strip() for line in list_proc.stdout.splitlines()
        if line.strip()
    ]
    local_paths: list[Path] = []
    for basename in basenames:
        remote_npz = _remote_join(
            shard, remote_repo, "iterate_data", basename,
        )
        local_npz = output_dir / basename
        _run_subprocess(
            _scp_cmd(
                shard, remote_npz, str(local_npz),
                from_remote=True,
            ),
            timeout=120,
        )
        local_paths.append(local_npz)

    # 6. Pull any per-batch replay .json.gz files back. Same shape as
    # the local-shard path so the training UI's replay viewer
    # (which only knows about the master's replays_root) finds them.
    _pull_remote_replays(
        shard, remote_repo,
        replays_root=spec.replays_root,
        capture_every=spec.capture_every,
        run_id_full=run_id_full,
    )
    return local_paths


def run_shard_eval_remote(
    shard: ShardConfig,
    spec: EvalJobSpec,
    *,
    queue_url: str,
    run_id: str,
    iter_total_games: int,
    progress_dir: Path,
    stamp: str,
    bundle_url: Optional[str] = None,
) -> dict[str, int]:
    """Run an eval shard on a remote machine. Mirrors
    ``run_shard_remote`` but pushes BOTH NN weights files (new + old),
    invokes the wrapper in eval mode, and returns aggregated counts
    parsed from a JSON result file scp'd back from the remote.
    """
    run_id_full = f"{run_id}_shard_{shard.display_label}"
    progress_dir.mkdir(parents=True, exist_ok=True)
    local_progress_path = progress_dir / f"{run_id_full}.json"
    local_events_path = progress_dir / f"{run_id_full}_events.jsonl"
    local_result_path = progress_dir / f"{run_id_full}_result.json"

    remote_repo = shard.repo_path or ""
    remote_progress = _remote_join(
        shard, remote_repo, "training_progress", f"{run_id_full}.json",
    )
    remote_events = _remote_join(
        shard, remote_repo, "training_progress",
        f"{run_id_full}_events.jsonl",
    )
    remote_result = _remote_join(
        shard, remote_repo, "training_progress",
        f"{run_id_full}_result.json",
    )

    if bundle_url:
        print(
            f"[shard {shard.display_label}] sync from bundle on "
            f"{shard.host}...", file=sys.stderr,
        )
        _run_subprocess(
            _ssh_cmd(shard, _build_remote_bundle_sync_command(
                shard, bundle_url,
            )),
            timeout=300,
        )

    _push_weights_to_remote(shard, remote_repo, spec.new_weights_path)
    if spec.old_weights_path is not None:
        _push_weights_to_remote(
            shard, remote_repo, spec.old_weights_path,
        )

    poller = _ProgressPoller(
        shard,
        remote_progress_path=remote_progress,
        local_progress_path=local_progress_path,
    )
    poller.start()

    print(
        f"[shard {shard.display_label}] pull-mode eval on "
        f"{shard.host}...",
        file=sys.stderr,
    )
    try:
        run_cmd = _build_remote_eval_command(
            shard, spec,
            queue_url=queue_url,
            run_id=run_id,
            iter_total_games=iter_total_games,
            stamp=stamp,
        )
        _run_subprocess(_ssh_cmd(shard, run_cmd))
    finally:
        poller.stop()
        for remote_path, local_path in (
            (remote_progress, local_progress_path),
            (remote_events, local_events_path),
            (remote_result, local_result_path),
        ):
            try:
                _run_subprocess(
                    _scp_cmd(
                        shard, remote_path, str(local_path),
                        from_remote=True,
                    ),
                    timeout=30,
                )
            except Exception:  # noqa: BLE001
                pass

    if not local_result_path.is_file():
        raise RuntimeError(
            f"eval shard {shard.display_label} produced no result "
            f"file at {local_result_path}; check stderr."
        )

    _pull_remote_replays(
        shard, remote_repo,
        replays_root=spec.replays_root,
        capture_every=spec.capture_every,
        run_id_full=run_id_full,
    )
    return json.loads(local_result_path.read_text(encoding="utf-8"))
