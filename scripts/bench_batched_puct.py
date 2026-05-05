"""Micro-benchmark: PUCT MCTS at varying ``batch_size``.

Run:
    PYTHONPATH=src .venv-py313/Scripts/python.exe \
        scripts/bench_batched_puct.py

Measures wall-clock per ``mcts.choose_with_visits()`` call at a fixed
deterministic mid-game-ish root state (PRECOMBAT_MAIN of a fresh
seeded game), running PUCT with the dual-head NN evaluator, at
batch_size 1 / 8 / 32. Reports ms/call and speedup vs batch_size=1.

The expectation when this lands: batch_size=8 and 32 should be
materially faster per-call than batch_size=1 because each value+policy
forward pass replaces N single-state forward passes. The exact
speedup depends on the network size, hardware, and how much of the
search wall-clock is NN inference vs Python tree-walking. On the
25k+33k network (small trunk, small policy head), expect modest
single-digit speedups on CPU.

Not part of the test suite — run manually before/after a perf-
sensitive change.
"""

from __future__ import annotations

import argparse
import random
import time

from mtg_bot.actions import PassPriority
from mtg_bot.agents import RandomAgent
from mtg_bot.search import (
    Budget, MCTS, MtgGameStateAdapter, NNEvaluator,
)
from mtg_bot.simulate import _default_deck_for_color as _default_deck, setup_game
from mtg_bot.turn import Step


def _adapter(seed: int = 42) -> MtgGameStateAdapter:
    state = setup_game(
        [RandomAgent(), RandomAgent()], decks=[_default_deck("G", seed), _default_deck("R", seed)], seed=seed,
    )
    return MtgGameStateAdapter(state)


def _adapter_at_precombat_main(
    seed: int = 42,
) -> MtgGameStateAdapter:
    """Walk through UPKEEP/DRAW so the search has real choices."""
    adapter = _adapter(seed=seed)
    for _ in range(50):
        if adapter.is_terminal():
            break
        if adapter.engine_state.step == Step.PRECOMBAT_MAIN:
            break
        adapter.apply(PassPriority())
    return adapter


def time_search(
    adapter, *, batch_size: int, max_nodes: int,
    samples: int, seed: int,
) -> float:
    """Return mean ms/call over ``samples`` independent searches.

    Each sample re-instantiates the evaluator (with a fresh torch
    seed so weights are reproducible across batch sizes) and the
    MCTS so tree state doesn't leak between runs."""
    import torch
    times: list[float] = []
    for k in range(samples):
        torch.manual_seed(123)
        evaluator = NNEvaluator(with_policy=True)
        mcts = MCTS(
            evaluator=evaluator,
            budget_factory=lambda: Budget(max_nodes=max_nodes),
            rng=random.Random(seed),
            puct=True,
            batch_size=batch_size,
        )
        start = time.perf_counter()
        mcts.choose_with_visits(
            adapter, adapter.active_player(),
        )
        times.append(time.perf_counter() - start)
    return sum(times) / len(times) * 1000.0  # ms


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=4)
    parser.add_argument("--nodes", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--mcts-seed", type=int, default=11)
    args = parser.parse_args()

    adapter = _adapter_at_precombat_main(seed=args.seed)
    print(
        f"Root: step={adapter.engine_state.step}, "
        f"legal={len(list(adapter.legal_decisions()))}, "
        f"samples={args.samples}, nodes={args.nodes}"
    )

    baseline = None
    for batch_size in (1, 8, 32):
        ms = time_search(
            adapter,
            batch_size=batch_size,
            max_nodes=args.nodes,
            samples=args.samples,
            seed=args.mcts_seed,
        )
        if baseline is None:
            baseline = ms
            speedup = 1.0
        else:
            speedup = baseline / ms if ms > 0 else float("inf")
        print(
            f"  batch_size={batch_size:>2}: {ms:7.2f} ms/call "
            f"(speedup vs batch_size=1: {speedup:.2f}x)"
        )


if __name__ == "__main__":
    main()
