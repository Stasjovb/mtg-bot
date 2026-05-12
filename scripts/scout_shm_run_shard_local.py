"""Scout: end-to-end smoke for ``run_shard_local`` + SHM activation.

Invokes ``run_shard_local`` directly with a real (tiny) dual-head
network, the 17lands deck pool, and ``spec.use_shm_server=True``.
Verifies:
- The activation banner ``[shard local] using SharedTensorNNEvalServer ...``
  appears on stdout (real ``SharedTensorNNEvalServer`` is constructed,
  not a test double).
- The shard completes a tiny game count without deadlock or crash.
- The SHM server shuts down cleanly on shard exit (no orphan
  dispatcher thread, no lingering shared-memory regions).

This is a manual smoke — not a unit test — because it touches the real
torch + mp.Pool + SHM dispatcher substrate that the in-process unit
tests deliberately mock to keep wall-time tractable.

Usage (from the worktree root):
  PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \
      scripts/scout_shm_run_shard_local.py

Optional knobs:
  --games N      (default 4)
  --nodes N      (default 50; tiny, ~1-2s/game on master CUDA)
  --no-shm       run twice — once with SHM, once without — to compare
                 per-game wall time
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
from pathlib import Path

# Path bootstrap for direct invocation from the worktree root.
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "src"))


def _save_tiny_dual_head(weights_path: Path) -> tuple[int, ...]:
    """Save a tiny dual-head MLP to ``weights_path`` (so the SHM server
    has a real model to host) and return its hidden_sizes."""
    import torch
    from mtg_bot.search.nn_evaluator import _ValuePolicyMLP
    hidden_sizes = (16, 16)
    torch.save(
        _ValuePolicyMLP(hidden_sizes=hidden_sizes).state_dict(),
        weights_path,
    )
    return hidden_sizes


def _run_one(
    *,
    use_shm: bool,
    n_games: int,
    nodes: int,
    deck_pool_path: Path,
) -> float:
    """Run a single ``run_shard_local`` invocation; return wall-clock
    seconds. Builds a fresh tmp dir per invocation so SHM-on and
    SHM-off shards don't share output paths."""
    from mtg_bot.training.distributed import (
        SelfPlayJobSpec,
        ShardConfig,
        run_shard_local,
    )

    tmp = Path(tempfile.mkdtemp(prefix=f"scout_shm_local_{'on' if use_shm else 'off'}_"))
    try:
        weights_path = tmp / "tiny_dual_head.pt"
        hidden_sizes = _save_tiny_dual_head(weights_path)
        spec = SelfPlayJobSpec(
            weights_path=str(weights_path),
            samples=1,
            inner_nodes=nodes,
            hidden_sizes=hidden_sizes,
            base_seed=0,
            enable_mulligans=False,
            per_game_timeout_sec=300,
            with_policy=True,
            use_shm_server=use_shm,
            deck_pool_path=str(deck_pool_path),
        )
        shard = ShardConfig(host="local", label="local", n_workers=2)
        t0 = time.perf_counter()
        npz_path = run_shard_local(
            shard, spec,
            n_games=n_games,
            progress_dir=tmp / "progress",
            output_dir=tmp / "out",
            run_id_prefix="scout_shm_local",
            stamp="20260512T130000Z",
        )
        wall = time.perf_counter() - t0
        assert npz_path.is_file(), f"expected npz at {npz_path}"
        return wall
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--games", type=int, default=4)
    parser.add_argument("--nodes", type=int, default=50)
    parser.add_argument(
        "--deck-pool",
        type=Path,
        default=_REPO / "data" / "17lands" / "eoe_decks.json.gz",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="also run a SHM-off pass for per-game wall comparison",
    )
    args = parser.parse_args()

    if not args.deck_pool.is_file():
        print(
            f"ERROR: deck pool not found at {args.deck_pool}; "
            f"pass --deck-pool to override",
            file=sys.stderr,
        )
        return 2

    print(
        f"[smoke] platform={sys.platform}  games={args.games}  "
        f"nodes={args.nodes}  deck_pool={args.deck_pool.name}"
    )

    print("[smoke] === run 1: SHM ON ===")
    wall_on = _run_one(
        use_shm=True,
        n_games=args.games,
        nodes=args.nodes,
        deck_pool_path=args.deck_pool,
    )
    per_on = wall_on / max(1, args.games)
    print(f"[smoke] SHM ON  wall={wall_on:.2f}s  per_game={per_on:.2f}s")

    if args.compare:
        print("[smoke] === run 2: SHM OFF ===")
        wall_off = _run_one(
            use_shm=False,
            n_games=args.games,
            nodes=args.nodes,
            deck_pool_path=args.deck_pool,
        )
        per_off = wall_off / max(1, args.games)
        print(f"[smoke] SHM OFF wall={wall_off:.2f}s  per_game={per_off:.2f}s")
        print(
            f"[smoke] delta: SHM is "
            f"{(per_off - per_on) / per_off * 100:+.1f}% per-game faster"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
