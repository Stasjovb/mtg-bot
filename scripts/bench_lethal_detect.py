"""Benchmark for the lethal-detect heuristic firing rate.

Runs self-play games with two ISMCTS agents (one with the heuristic
on, one with it off) and reports:

- How often the heuristic fires per game (mean, min, max)
- Per-game wall delta (heuristic on vs off)
- Number of search-loop bypasses contributed by the heuristic

Both agents share the same evaluator (RandomRolloutEvaluator) and
budget; only the ``enable_lethal_detect`` flag differs.

Usage:
    PYTHONPATH=src python scripts/bench_lethal_detect.py --n-games 10
"""

from __future__ import annotations

import argparse
import statistics
import time
from typing import Optional

from mtg_bot.agents import RandomAgent
from mtg_bot.search import (
    ISMCTS, MtgGameStateAdapter, RandomRolloutEvaluator,
)
from mtg_bot.search.budget import Budget
from mtg_bot.simulate import _default_deck_for_color as _default_deck, setup_game


def _play_one_game(
    seed: int,
    enable_lethal_detect: bool,
    *,
    decision_cap: int = 200,
    node_limit: int = 50,
) -> tuple[float, int, int, Optional[int]]:
    """Play one self-play game with ISMCTS agents on both sides.
    Returns ``(wall_seconds, total_decisions, lethal_fires, winner_id)``.
    """
    state = setup_game(
        [RandomAgent(), RandomAgent()], decks=[_default_deck("G", seed), _default_deck("R", seed)], seed=seed,
    )

    def _make_search() -> ISMCTS:
        return ISMCTS(
            evaluator=RandomRolloutEvaluator(),
            budget_factory=lambda: Budget(max_nodes=node_limit),
            puct=False,
            enable_lethal_detect=enable_lethal_detect,
        )

    search = _make_search()
    adapter = MtgGameStateAdapter(state, expose_combat_decisions=True)

    start = time.perf_counter()
    decisions = 0
    while not adapter.is_terminal() and decisions < decision_cap:
        viewer = adapter.active_player()
        legal = list(adapter.legal_decisions())
        if not legal:
            break
        if len(legal) == 1:
            adapter.apply(legal[0])
        else:
            decision = search.choose(adapter, viewer)
            adapter.apply(decision)
        decisions += 1
    wall = time.perf_counter() - start

    winner = adapter.winner() if adapter.is_terminal() else None
    return wall, decisions, search._lethal_detect_fires, winner


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-games", type=int, default=5)
    parser.add_argument("--seed-base", type=int, default=100)
    parser.add_argument("--decision-cap", type=int, default=200)
    parser.add_argument("--node-limit", type=int, default=50)
    args = parser.parse_args()

    print(
        f"Running {args.n_games} games with budget "
        f"node_limit={args.node_limit}, decision_cap="
        f"{args.decision_cap}.\n"
    )

    on_walls: list[float] = []
    on_fires: list[int] = []
    on_decisions: list[int] = []
    on_winners: list[Optional[int]] = []
    off_walls: list[float] = []
    off_decisions: list[int] = []
    off_winners: list[Optional[int]] = []

    for i in range(args.n_games):
        seed = args.seed_base + i
        # Heuristic ON
        wall, decs, fires, winner = _play_one_game(
            seed, enable_lethal_detect=True,
            decision_cap=args.decision_cap,
            node_limit=args.node_limit,
        )
        on_walls.append(wall)
        on_fires.append(fires)
        on_decisions.append(decs)
        on_winners.append(winner)

        # Heuristic OFF (same seed for paired comparison)
        wall_off, decs_off, _, winner_off = _play_one_game(
            seed, enable_lethal_detect=False,
            decision_cap=args.decision_cap,
            node_limit=args.node_limit,
        )
        off_walls.append(wall_off)
        off_decisions.append(decs_off)
        off_winners.append(winner_off)

        print(
            f"Game {i+1:2d} seed={seed}: "
            f"ON wall={wall:6.2f}s fires={fires:3d} decisions={decs:3d} "
            f"winner={winner}  |  "
            f"OFF wall={wall_off:6.2f}s decisions={decs_off:3d} "
            f"winner={winner_off}"
        )

    print("\n=== Summary ===\n")
    n = args.n_games

    print("Heuristic firings per game:")
    print(
        f"  mean={statistics.mean(on_fires):.2f}  "
        f"min={min(on_fires)}  max={max(on_fires)}  "
        f"games_with_fire={sum(1 for f in on_fires if f > 0)}/{n}"
    )

    print("\nWall (sec):")
    print(
        f"  ON  mean={statistics.mean(on_walls):.3f}  "
        f"median={statistics.median(on_walls):.3f}"
    )
    print(
        f"  OFF mean={statistics.mean(off_walls):.3f}  "
        f"median={statistics.median(off_walls):.3f}"
    )
    delta_pct = (
        100.0 * (statistics.mean(on_walls) - statistics.mean(off_walls))
        / statistics.mean(off_walls)
    )
    print(f"  ON-vs-OFF wall delta: {delta_pct:+.1f}%")

    print("\nTotal decisions per game:")
    print(f"  ON  mean={statistics.mean(on_decisions):.1f}")
    print(f"  OFF mean={statistics.mean(off_decisions):.1f}")

    # Same-winner agreement
    matching = sum(
        1 for w_on, w_off in zip(on_winners, off_winners)
        if w_on == w_off
    )
    print(
        f"\nSame-winner across ON/OFF (paired by seed): "
        f"{matching}/{n} games"
    )


if __name__ == "__main__":
    main()
