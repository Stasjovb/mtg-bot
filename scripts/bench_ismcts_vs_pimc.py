"""Quick perf comparison between ISMCTS and PIMC at comparable budget."""

from __future__ import annotations

import random
import statistics
import sys
import time

from mtg_bot.agents import RandomAgent
from mtg_bot.search import (
    Budget, ISMCTS, MCTS, MtgGameStateAdapter, PIMC,
    RandomRolloutEvaluator,
)
from mtg_bot.simulate import setup_game


def _make_state(seed: int) -> MtgGameStateAdapter:
    state = setup_game(
        [RandomAgent(), RandomAgent()], ["G", "R"], seed=seed,
    )
    adapter = MtgGameStateAdapter(state)
    while (
        len(adapter.legal_decisions()) == 1
        and not adapter.is_terminal()
    ):
        adapter.apply(adapter.legal_decisions()[0])
    return adapter


def _bench_pimc(adapter: MtgGameStateAdapter, total_budget: int) -> float:
    """Comparable budget: K=4 sub-trees of (total_budget/4) nodes each."""
    per_world = total_budget // 4

    def make_inner():
        return MCTS(
            evaluator=RandomRolloutEvaluator(rng=random.Random(7)),
            budget_factory=lambda: Budget(max_nodes=per_world),
            rng=random.Random(8),
        )
    pimc = PIMC(
        inner_factory=make_inner,
        samples=4,
        rng=random.Random(0),
    )
    t0 = time.perf_counter()
    pimc.choose_with_visits(adapter, adapter.active_player())
    return time.perf_counter() - t0


def _bench_ismcts(adapter: MtgGameStateAdapter, total_budget: int) -> float:
    """Same total iterations as PIMC's K * per_world."""
    ismcts = ISMCTS(
        evaluator=RandomRolloutEvaluator(rng=random.Random(7)),
        budget_factory=lambda: Budget(max_nodes=total_budget),
        rng=random.Random(8),
        puct=False,
    )
    t0 = time.perf_counter()
    ismcts.choose_with_visits(adapter, adapter.active_player())
    return time.perf_counter() - t0


def main() -> None:
    seeds = [11, 42, 77, 99, 2026]
    total_budget = 80  # 80 iters total (PIMC: 4 worlds × 20 nodes each)
    pimc_times = []
    ismcts_times = []
    for seed in seeds:
        print(f"seed {seed}: setting up state...", flush=True)
        adapter = _make_state(seed)
        if adapter.is_terminal():
            print(f"seed {seed}: terminal, skipping", flush=True)
            continue
        print(
            f"seed {seed}: legal_decisions="
            f"{len(adapter.legal_decisions())}",
            flush=True,
        )
        # Warmup pass (excluded from timings).
        _bench_pimc(adapter, total_budget)
        _bench_ismcts(adapter, total_budget)
        pimc_t = _bench_pimc(adapter, total_budget)
        ismcts_t = _bench_ismcts(adapter, total_budget)
        pimc_times.append(pimc_t)
        ismcts_times.append(ismcts_t)
        print(
            f"seed={seed}: PIMC={pimc_t * 1000:.1f}ms  "
            f"ISMCTS={ismcts_t * 1000:.1f}ms",
            flush=True,
        )
    print(flush=True)
    if pimc_times:
        print(
            f"PIMC median: {statistics.median(pimc_times) * 1000:.1f}ms",
            flush=True,
        )
    if ismcts_times:
        print(
            f"ISMCTS median: "
            f"{statistics.median(ismcts_times) * 1000:.1f}ms",
            flush=True,
        )


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    main()
