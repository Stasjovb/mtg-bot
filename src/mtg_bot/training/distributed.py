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

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


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
