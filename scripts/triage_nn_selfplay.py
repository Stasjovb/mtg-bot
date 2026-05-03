"""Run a small NN-self-play pool to capture hang dumps for triage.

Mirrors what ``iterate_alphazero._self_play`` does — NNPimcConfig
with PUCT, batched leaf eval, real EoE deck pool — but at a much
smaller game count and a tighter per-game timeout so hangs land in
minutes instead of an hour.

Diagnostic-only. Not committed to the parallel data path.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mtg_bot.decks import decks_from_json  # noqa: E402
from mtg_bot.training import (  # noqa: E402
    NNPimcConfig,
    Registry,
    generate_training_data_parallel,
)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--version", default="v6",
                   help="Registered NN version (default v6).")
    p.add_argument("--registry-root", type=Path, default=Path("trained_weights"))
    p.add_argument("--n-games", type=int, default=200)
    p.add_argument("--samples", type=int, default=4)
    p.add_argument("--nodes", type=int, default=200)
    p.add_argument("--seed", type=int, default=1_000_000,
                   help="iter_001's cycle_seed default.")
    p.add_argument("--n-workers", type=int, default=6)
    p.add_argument("--per-game-timeout-sec", type=float, default=60.0)
    p.add_argument("--deck-pool", type=Path, required=True)
    p.add_argument("--hang-dump-dir", type=Path, required=True)
    args = p.parse_args()

    registry = Registry(args.registry_root)
    if not registry.has(args.version):
        sys.exit(f"version {args.version!r} not in {args.registry_root}")
    weights_path = registry.weights_path(args.version)
    meta = registry.load_metadata(args.version)
    raw_hidden = getattr(meta, "hidden_sizes", None)
    hidden_sizes = tuple(raw_hidden) if raw_hidden else None

    cfg = NNPimcConfig(
        weights_path=str(weights_path),
        samples=args.samples,
        inner_nodes=args.nodes,
        batch_size=32,
        with_policy=True,
        puct=True,
        hidden_sizes=hidden_sizes,
    )

    if not args.deck_pool.is_file():
        sys.exit(f"deck pool not found: {args.deck_pool}")
    deck_pool = decks_from_json(args.deck_pool)

    args.hang_dump_dir.mkdir(parents=True, exist_ok=True)
    print(f"# triage_nn_selfplay: version={args.version} "
          f"hidden_sizes={hidden_sizes} n_games={args.n_games} "
          f"workers={args.n_workers} timeout={args.per_game_timeout_sec}s")
    print(f"# hang dumps -> {args.hang_dump_dir}")
    started = time.perf_counter()
    f, o, _, _ = generate_training_data_parallel(
        p0_factory=cfg.build, p1_factory=cfg.build,
        n_games=args.n_games, base_seed=args.seed,
        n_workers=args.n_workers,
        deck_pool=deck_pool,
        with_policy=True,
        per_game_timeout_sec=args.per_game_timeout_sec,
        hang_dump_dir=str(args.hang_dump_dir),
    )
    elapsed = time.perf_counter() - started
    print(f"# done in {elapsed:.1f}s ({elapsed/60:.1f}m). "
          f"{f.shape[0]} samples.")


if __name__ == "__main__":
    main()
