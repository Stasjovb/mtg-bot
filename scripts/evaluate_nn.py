"""Evaluate a trained NN evaluator vs the heuristic in self-play.

The acceptance gate from the training plan: trained NN must beat
the heuristic in head-to-head play. Loose floor — at small sample
counts (default 20 games) the noise is high; this is "did training
do something useful," not "is this network optimal."

Usage::

    python scripts/evaluate_nn.py \\
        --weights trained_weights/v1.pt \\
        --n-games 20

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

from mtg_bot.search import (  # noqa: E402
    Budget, MCTS, NNEvaluator, PIMC,
)
from mtg_bot.search.heuristic_evaluator import MtgHeuristicEvaluator  # noqa: E402
from mtg_bot.training import run_match  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--weights", type=Path, required=True,
        help="Path to trained .pt weights file.",
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
    args = parser.parse_args()

    if not args.weights.is_file():
        sys.exit(f"--weights {args.weights} not found")

    nn_evaluator = NNEvaluator(weights_path=args.weights)
    heuristic_evaluator = MtgHeuristicEvaluator()

    def make_pimc(evaluator):
        def factory(seed: int) -> PIMC:
            def inner_factory() -> MCTS:
                return MCTS(
                    evaluator=evaluator,
                    budget_factory=lambda: Budget(max_nodes=args.nodes),
                    rng=random.Random(seed + 100),
                )
            return PIMC(
                inner_factory=inner_factory,
                samples=args.samples,
                rng=random.Random(seed + 200),
            )
        return factory

    print(
        f"# evaluate_nn: {args.n_games} games, NN(seat 0) vs "
        f"heuristic(seat 1), samples={args.samples} nodes={args.nodes}"
    )
    started = time.perf_counter()
    stats = run_match(
        p0_factory=make_pimc(nn_evaluator),
        p1_factory=make_pimc(heuristic_evaluator),
        n_games=args.n_games,
        base_seed=args.seed,
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


if __name__ == "__main__":
    main()
