"""Grid-search the heuristic evaluator weights, ranked by win rate
vs RandomChoice.

Phase A demo: validates the self-play harness end-to-end and
produces real (if noisy) data on whether moving the heuristic
weights from 0.4/0.4/0.2 helps. The ranking is what matters here,
not the absolute win rates — the per-config game count is small
(default 10) and PIMC budgets are tiny (samples=2 nodes=50).

Usage::

    python scripts/tune_heuristic.py --n-games 10
    python scripts/tune_heuristic.py --n-games 30 --step 0.05
    python scripts/tune_heuristic.py --output results.json

Single-threaded; full default sweep (~21 configs × 10 games) takes
~5-10 minutes on a recent CPU. Phase D adds multiprocessing for
real AlphaZero-style data generation; for tuning 3 weights the
sequential loop is fine.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Make src/ importable when run from the repo root without
# pip install -e .
_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mtg_bot.training import (  # noqa: E402
    grid_search,
    heuristic_weight_grid,
    random_choice_factory,
)


def _print_progress(idx: int, total: int, config, stats) -> None:
    h = config.heuristic
    print(
        f"  [{idx + 1}/{total}] life={h.life_weight} "
        f"board={h.board_weight} card={h.card_weight}: "
        f"P0 win={stats.win_rate(0):.0%} "
        f"({stats.wins[0]}-{stats.wins[1]}-{stats.draws}) "
        f"avg_decisions={stats.avg_decisions:.0f}",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--n-games", type=int, default=10,
        help="Games per config (default 10). More = less noise, "
             "more time.",
    )
    parser.add_argument(
        "--step", type=float, default=0.1,
        help="Grid step over weights (default 0.1 → ~21 configs).",
    )
    parser.add_argument(
        "--samples", type=int, default=2,
        help="PIMC samples K per decision (default 2 — small for "
             "tuning speed).",
    )
    parser.add_argument(
        "--nodes", type=int, default=50,
        help="MCTS max_nodes per sub-search (default 50 — small for "
             "tuning speed).",
    )
    parser.add_argument(
        "--seed", type=int, default=0,
        help="Base seed for deterministic reproduction.",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Optional JSON file to write the ranked results to.",
    )
    args = parser.parse_args()

    grid = heuristic_weight_grid(
        step=args.step,
        samples=args.samples,
        inner_nodes=args.nodes,
    )
    n_games = args.n_games

    print(
        f"# tune_heuristic: {len(grid)} configs × {n_games} games "
        f"(samples={args.samples}, nodes={args.nodes}, "
        f"seed={args.seed}); opponent = RandomChoice"
    )
    started = time.perf_counter()
    results = grid_search(
        grid=grid,
        opponent_factory=random_choice_factory,
        n_games=n_games,
        base_seed=args.seed,
        progress_callback=_print_progress,
    )
    elapsed = time.perf_counter() - started

    print(f"\n# Done in {elapsed:.1f}s ({elapsed / 60:.1f}m)")
    print(
        f"\n{'rank':<5}{'win%':<7}{'record':<10}{'avg_dec':<10}"
        f"{'life':<7}{'board':<7}{'card':<7}"
    )
    for rank, (config, stats) in enumerate(results, start=1):
        h = config.heuristic
        record = f"{stats.wins[0]}-{stats.wins[1]}-{stats.draws}"
        print(
            f"{rank:<5}{stats.win_rate(0) * 100:<7.0f}"
            f"{record:<10}{stats.avg_decisions:<10.0f}"
            f"{h.life_weight:<7.2f}{h.board_weight:<7.2f}"
            f"{h.card_weight:<7.2f}"
        )

    if args.output is not None:
        payload = [
            {"config": c.to_dict(), "stats": {
                "wins": stats.wins,
                "draws": stats.draws,
                "games": stats.games,
                "avg_decisions": stats.avg_decisions,
                "win_rate_p0": stats.win_rate(0),
            }}
            for c, stats in results
        ]
        args.output.write_text(json.dumps(payload, indent=2))
        print(f"\n# wrote {args.output}")


if __name__ == "__main__":
    main()
