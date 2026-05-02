"""Evaluate a trained NN evaluator vs the heuristic in self-play.

The acceptance gate from the training plan: trained NN should beat
the heuristic in head-to-head play. Loose floor — at small sample
counts (default 20 games) the noise is high; this is "did training
do something useful," not "is this network optimal."

Usage::

    # Evaluate a registered version (writes the result back into
    # the registry's metadata.json under evaluation['vs_heuristic']).
    python scripts/evaluate_nn.py --version v3 --n-games 20

    # Evaluate against a specific weights file (no registry update).
    python scripts/evaluate_nn.py --weights some/path.pt --n-games 20

The trained network plays seat 0 (PIMC + NNEvaluator), the heuristic
plays seat 1 (PIMC + MtgHeuristicEvaluator), at the recommend.py
defaults (samples=4, nodes=200) so we measure at a search budget
the user actually sees in the UI.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mtg_bot.training import run_match  # noqa: E402
from mtg_bot.training.config import (  # noqa: E402
    HeuristicConfig, NNPimcConfig, PimcConfig,
)
from mtg_bot.training.self_play import run_match_parallel  # noqa: E402
from mtg_bot.training.registry import Registry  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--version", default=None,
        help=(
            "Registered version ID (e.g. v3). Result is recorded "
            "back into metadata.json under evaluation['vs_heuristic']."
        ),
    )
    src.add_argument(
        "--weights", type=Path, default=None,
        help=(
            "Path to a raw .pt weights file. No registry update; "
            "useful for ad-hoc evaluation of off-registry weights."
        ),
    )
    parser.add_argument(
        "--registry-root", type=Path,
        default=Path("trained_weights"),
        help="Registry root (default trained_weights/).",
    )
    parser.add_argument(
        "--n-games", type=int, default=20,
        help="Games to play (default 20).",
    )
    parser.add_argument(
        "--samples", type=int, default=4,
        help="PIMC samples K (default 4 — recommend defaults).",
    )
    parser.add_argument(
        "--nodes", type=int, default=200,
        help="MCTS max_nodes per sub-search (default 200).",
    )
    parser.add_argument(
        "--seed", type=int, default=0,
        help="Base seed.",
    )
    parser.add_argument(
        "--nn-batch-size", type=int, default=32,
        help=(
            "MCTS batched-leaf-evaluation size for the NN seat "
            "(default 32). 1 disables batching (legacy serial "
            "search). Higher = more leaves per NN forward pass = "
            "fewer Python↔C round-trips. Heuristic seat always "
            "uses 1 (no batched compute to amortize)."
        ),
    )
    parser.add_argument(
        "--workers", type=int, default=None,
        help=(
            "Worker count for parallel game execution. Default: "
            "cpu_count() - 2. Pass 1 to force sequential (useful "
            "for debugging — easier traces, no spawn overhead). "
            "Pass 0 to also force sequential."
        ),
    )
    args = parser.parse_args()

    registry: Registry | None = None
    if args.version is not None:
        registry = Registry(args.registry_root)
        if not registry.has(args.version):
            sys.exit(
                f"Version {args.version!r} not found in "
                f"{args.registry_root}. Available: "
                f"{registry.list_versions()}"
            )
        weights_path = registry.weights_path(args.version)
        label = args.version
    else:
        if not args.weights.is_file():
            sys.exit(f"--weights {args.weights} not found")
        weights_path = args.weights
        label = str(args.weights)

    # Configs (picklable frozen dataclasses) so we can ship the
    # factories across multiprocessing.Pool worker boundaries.
    # Closures over local variables wouldn't pickle; bound methods
    # of frozen dataclasses do. NNPimcConfig carries weights_path
    # rather than an NNEvaluator instance — workers reload weights
    # from disk inside ``build``, which always pickles cleanly.
    # Batched leaf evaluation (B1) helps the NN side substantially:
    # one (B, FEATURE_DIM) forward pass beats B single-state
    # forwards by ~5-25× in steady-state CPU benches. The heuristic
    # side has no batched compute and pays virtual-loss bookkeeping
    # for nothing — keep it at batch_size=1.
    nn_cfg = NNPimcConfig(
        weights_path=str(weights_path),
        samples=args.samples,
        inner_nodes=args.nodes,
        batch_size=args.nn_batch_size,
    )
    heuristic_cfg = PimcConfig(
        samples=args.samples,
        inner_nodes=args.nodes,
        heuristic=HeuristicConfig(),
        batch_size=1,
    )

    if args.workers is None or args.workers > 1:
        worker_label = (
            f"workers={args.workers}" if args.workers
            else "workers=auto"
        )
    else:
        worker_label = "sequential"
    print(
        f"# evaluate_nn: {args.n_games} games, NN({label}, seat 0) "
        f"vs heuristic(seat 1), samples={args.samples} nodes={args.nodes}, "
        f"NN batch_size={args.nn_batch_size}, {worker_label}"
    )
    started = time.perf_counter()
    if args.workers is not None and args.workers <= 1:
        stats = run_match(
            p0_factory=nn_cfg.build,
            p1_factory=heuristic_cfg.build,
            n_games=args.n_games,
            base_seed=args.seed,
        )
    else:
        stats = run_match_parallel(
            p0_factory=nn_cfg.build,
            p1_factory=heuristic_cfg.build,
            n_games=args.n_games,
            base_seed=args.seed,
            n_workers=args.workers,
        )
    elapsed = time.perf_counter() - started

    print(
        f"\n# Done in {elapsed:.1f}s ({elapsed / 60:.1f}m)."
    )
    print(
        f"# NN won {stats.wins[0]}, heuristic won {stats.wins[1]}, "
        f"draws {stats.draws} / {stats.games}"
    )
    print(f"# NN win rate: {stats.win_rate(0):.1%}")
    print(f"# Avg decisions per game: {stats.avg_decisions:.0f}")

    if registry is not None and args.version is not None:
        result = {
            "wins": stats.wins[0],
            "losses": stats.wins[1],
            "draws": stats.draws,
            "n_games": stats.games,
            "win_rate": stats.win_rate(0),
            "avg_decisions": stats.avg_decisions,
            "samples": args.samples,
            "nodes": args.nodes,
            "nn_batch_size": args.nn_batch_size,
            "duration_seconds": elapsed,
            "seed": args.seed,
        }
        registry.add_evaluation_result(
            args.version, "vs_heuristic", result,
        )
        print(
            f"\n# Recorded vs_heuristic result into "
            f"{args.registry_root}/{args.version}/metadata.json"
        )


if __name__ == "__main__":
    main()
