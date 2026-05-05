"""Standalone perf comparison for ISMCTS tree reuse across calls.

Runs five sequential ``choose_with_visits()`` calls against an
adapter that gets advanced (via ``apply`` + ``observe_action``)
between calls. Compares two configurations:

- baseline: tree is forcibly reset before every search call,
  matching the pre-tree-reuse behavior.
- tree-reuse: the strategy retains its persistent tree across
  calls, with ``observe_action`` advancing/pruning the root.

Both configurations use identical seeds, evaluators, and budgets.
The headline metric is *not* wall-clock time at fixed budget —
the budget caps iterations, and each iteration runs whether or not
the root inherits visits, so total time is roughly identical
between the two paths. The real benefit is **effective search
work**: under tree reuse, the new search starts from a root that
already has accumulated visits + cached priors + cached policy
logits from prior iterations, so the first batch of selections in
the new search are guided by deeper info than a cold-start search
of the same budget would have access to.

This script reports:

- per-call wall-clock time (should be ~equal between the two paths)
- inherited root visits per call under tree reuse (the "free"
  search budget the next search starts with)
- inherited tree size per call (proxy for prior search depth)

Run from a worktree:

  PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \
      scripts/bench_ismcts_tree_reuse.py
"""

from __future__ import annotations

import random
import statistics
import time
from dataclasses import dataclass, field
from typing import Callable

from mtg_bot.agents import RandomAgent
from mtg_bot.search import (
    Budget, ISMCTS, MtgGameStateAdapter, RandomRolloutEvaluator,
)
from mtg_bot.simulate import _default_deck_for_color as _default_deck, setup_game


# Small budget so the per-call time is dominated by the actual
# search loop and the tree-reuse benefit shows up clearly. Larger
# budgets dwarf the inherited visits since the budget alone fills
# the tree fast.
BUDGET = 200
NUM_CALLS = 5


def _fresh_adapter(seed: int) -> MtgGameStateAdapter:
    state = setup_game(
        [RandomAgent(), RandomAgent()], decks=[_default_deck("G", seed), _default_deck("R", seed)], seed=seed,
    )
    adapter = MtgGameStateAdapter(state)
    # Walk past forced moves so the first search has something to do.
    while (
        len(adapter.legal_decisions()) == 1
        and not adapter.is_terminal()
    ):
        adapter.apply(adapter.legal_decisions()[0])
    return adapter


def _make_strategy(seed: int) -> ISMCTS:
    return ISMCTS(
        evaluator=RandomRolloutEvaluator(rng=random.Random(seed)),
        budget_factory=lambda: Budget(max_nodes=BUDGET),
        rng=random.Random(seed + 100),
        puct=False,
    )


@dataclass
class _RunResult:
    per_call_seconds: list[float] = field(default_factory=list)
    # Visits the new root inherited at the start of each call (0
    # always for the baseline path; nonzero when tree reuse fires).
    inherited_root_visits: list[int] = field(default_factory=list)
    # Tree size at the start of each call (after reuse path's root
    # advance + prune; matches reachable-from-root subtree size).
    inherited_tree_nodes: list[int] = field(default_factory=list)

    @property
    def total(self) -> float:
        return sum(self.per_call_seconds)

    @property
    def mean(self) -> float:
        return statistics.mean(self.per_call_seconds)


def _run(seed: int, *, reuse: bool) -> _RunResult:
    """Drive ``NUM_CALLS`` sequential choose calls. When ``reuse``
    is False, the strategy's tree is reset before every call to
    simulate the old behavior (no tree carryover).
    """
    from mtg_bot.search.info_set import info_set_key
    adapter = _fresh_adapter(seed)
    strategy = _make_strategy(seed)
    result = _RunResult()
    for call_idx in range(NUM_CALLS):
        if adapter.is_terminal():
            break
        if not reuse:
            strategy.reset_tree()
        actor = adapter.active_player()
        # Probe inherited state BEFORE the search runs.
        prospective_root_key = info_set_key(adapter, actor)
        prior_root = strategy._tree.get(prospective_root_key)
        result.inherited_root_visits.append(
            prior_root.visits if prior_root is not None else 0
        )
        result.inherited_tree_nodes.append(len(strategy._tree))
        t0 = time.perf_counter()
        visits = strategy.choose_with_visits(adapter, actor)
        elapsed = time.perf_counter() - t0
        result.per_call_seconds.append(elapsed)
        if not visits:
            break
        decision = max(visits.items(), key=lambda kv: kv[1])[0]
        # Advance the adapter and the strategy's tree.
        strategy.observe_action(adapter, decision, actor)
        adapter.apply(decision)
        # Skip past forced moves so the next search lands on a real
        # decision point — observe_action steps the tree per forced
        # apply too, which is the realistic in-game pattern.
        while (
            len(adapter.legal_decisions()) == 1
            and not adapter.is_terminal()
        ):
            forced_actor = adapter.active_player()
            forced = adapter.legal_decisions()[0]
            strategy.observe_action(adapter, forced, forced_actor)
            adapter.apply(forced)
    return result


def _format(result: _RunResult) -> str:
    if not result.per_call_seconds:
        return "(no calls completed)"
    per = ", ".join(f"{t * 1000:.1f}" for t in result.per_call_seconds)
    inherited = ", ".join(str(v) for v in result.inherited_root_visits)
    nodes = ", ".join(str(n) for n in result.inherited_tree_nodes)
    return (
        f"total={result.total * 1000:.1f}ms "
        f"mean/call={result.mean * 1000:.1f}ms\n"
        f"    per-call ms     = [{per}]\n"
        f"    inherited visits= [{inherited}]\n"
        f"    inherited nodes = [{nodes}]"
    )


def main() -> None:
    print(
        f"ISMCTS tree-reuse perf: {NUM_CALLS} sequential "
        f"choose_with_visits() calls, budget={BUDGET} per call."
    )
    print()
    seeds = [11, 13, 17]
    for seed in seeds:
        baseline = _run(seed, reuse=False)
        reuse = _run(seed, reuse=True)
        if not baseline.per_call_seconds or not reuse.per_call_seconds:
            print(f"seed={seed}: insufficient calls; skipping")
            continue
        delta = baseline.total - reuse.total
        speedup = (
            baseline.total / reuse.total
            if reuse.total > 0 else float("inf")
        )
        print(f"seed={seed}")
        print(f"  baseline (no reuse): {_format(baseline)}")
        print(f"  tree-reuse:          {_format(reuse)}")
        print(
            f"  wall-clock delta:    "
            f"{delta * 1000:+.1f}ms  speedup={speedup:.2f}x"
        )
        # Effective-budget summary: cumulative inherited visits is
        # the "free" search work tree reuse contributed across the
        # five calls. Divided by per-call budget gives the speedup
        # in *effective* iterations (not wall-clock).
        total_inherited = sum(reuse.inherited_root_visits)
        total_iters = BUDGET * len(reuse.per_call_seconds)
        eff_ratio = (
            (total_inherited + total_iters) / total_iters
            if total_iters > 0 else 1.0
        )
        print(
            f"  effective-budget:    "
            f"inherited_visits_total={total_inherited}, "
            f"effective/spent={eff_ratio:.2f}x"
        )
        print()


if __name__ == "__main__":
    main()
