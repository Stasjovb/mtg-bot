"""Profile one PIMC vs RandomChoice game and dump the hotspots.

Used to inform optimization decisions: should we speed up cloning,
the evaluator, the priority loop, the legal-action enumeration?
``cProfile`` answers that without us guessing.

Usage::

    PYTHONPATH=src .venv/Scripts/python.exe scripts/profile_pimc_game.py
    PYTHONPATH=src .venv/Scripts/python.exe scripts/profile_pimc_game.py --samples 4 --nodes 100
    PYTHONPATH=src .venv/Scripts/python.exe scripts/profile_pimc_game.py --evaluator rollout --top 30

Defaults match ``recommend.py``'s production budget (samples=4,
nodes=200) and use the heuristic evaluator. Switch to ``--evaluator
rollout`` to profile the (slower but more informative) random-rollout
path used by the slow integration smoke test.

Output is printed to stdout — sorted by cumulative time, top N
functions. Save with shell redirection::

    ... profile_pimc_game.py > /tmp/pimc_profile.txt
"""

from __future__ import annotations

import argparse
import cProfile
import pstats
import random
import sys
from io import StringIO
from pathlib import Path

# Make the local source tree importable when run from the repo root
# without `pip install -e .`. Mirrors what `PYTHONPATH=src` does
# at the shell level.
_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mtg_bot.agents import RandomAgent  # noqa: E402
from mtg_bot.search import (  # noqa: E402
    Budget, MCTS, MtgGameStateAdapter, PIMC, RandomChoice,
    RandomRolloutEvaluator,
)
from mtg_bot.search.heuristic_evaluator import MtgHeuristicEvaluator  # noqa: E402
from mtg_bot.search.protocol import CHANCE_PLAYER  # noqa: E402
from mtg_bot.simulate import setup_game  # noqa: E402


def _build_adapter(seed: int) -> MtgGameStateAdapter:
    state = setup_game(
        [RandomAgent(rng=random.Random(seed + 1)),
         RandomAgent(rng=random.Random(seed + 2))],
        ["G", "R"], seed=seed,
    )
    return MtgGameStateAdapter(state)


def _build_pimc(
    seed: int, samples: int, nodes: int, evaluator_kind: str,
) -> PIMC:
    if evaluator_kind == "heuristic":
        eval_factory = lambda: MtgHeuristicEvaluator()
    elif evaluator_kind == "rollout":
        eval_factory = lambda: RandomRolloutEvaluator(
            rng=random.Random(seed + 50)
        )
    else:
        raise ValueError(f"unknown evaluator kind: {evaluator_kind!r}")

    def inner_factory() -> MCTS:
        return MCTS(
            evaluator=eval_factory(),
            budget_factory=lambda: Budget(max_nodes=nodes),
            rng=random.Random(seed + 100),
        )
    return PIMC(
        inner_factory=inner_factory,
        samples=samples,
        rng=random.Random(seed + 200),
    )


def _play_one_game(adapter, pimc, rc, rng, decision_cap: int = 4000) -> tuple:
    """Play one PIMC-vs-RandomChoice game. Returns (winner_id, decisions)."""
    decisions = 0
    while not adapter.is_terminal() and decisions < decision_cap:
        active = adapter.active_player()
        if active == CHANCE_PLAYER:
            outcomes = adapter.chance_outcomes()
            choices = [d for d, _ in outcomes]
            weights = [w for _, w in outcomes]
            d = rng.choices(choices, weights=weights, k=1)[0]
        elif active == 0:
            d = pimc.choose(adapter, active)
        else:
            d = rc.choose(adapter, active)
        adapter.apply(d)
        decisions += 1
    return adapter.winner(), decisions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Game seed (deck shuffle, draws, etc.). Default 42.",
    )
    parser.add_argument(
        "--samples", type=int, default=4,
        help="PIMC samples K. Default 4 (matches recommend.py).",
    )
    parser.add_argument(
        "--nodes", type=int, default=200,
        help="MCTS max_nodes per sub-search. Default 200.",
    )
    parser.add_argument(
        "--evaluator", choices=("heuristic", "rollout"),
        default="heuristic",
        help="MCTS leaf evaluator. Default heuristic (fast, weak); "
             "rollout (slower, stronger) for slow-path profiling.",
    )
    parser.add_argument(
        "--top", type=int, default=25,
        help="Number of hotspot rows to print. Default 25.",
    )
    parser.add_argument(
        "--sort", default="cumulative",
        choices=("cumulative", "tottime", "calls", "ncalls"),
        help="pstats sort key. Default cumulative.",
    )
    args = parser.parse_args()

    print(
        f"# PIMC profile — seed={args.seed} samples={args.samples} "
        f"nodes={args.nodes} evaluator={args.evaluator}"
    )

    adapter = _build_adapter(args.seed)
    pimc = _build_pimc(
        args.seed, args.samples, args.nodes, args.evaluator,
    )
    rc = RandomChoice(rng=random.Random(args.seed + 300))
    rng = random.Random(args.seed + 400)

    profiler = cProfile.Profile()
    profiler.enable()
    winner, decisions = _play_one_game(adapter, pimc, rc, rng)
    profiler.disable()

    stats_io = StringIO()
    pstats.Stats(profiler, stream=stats_io).sort_stats(
        args.sort
    ).print_stats(args.top)
    print(stats_io.getvalue())

    print(
        f"# game finished: winner={winner} decisions={decisions} "
        f"turn={adapter.engine_state.turn_number}"
    )


if __name__ == "__main__":
    main()
