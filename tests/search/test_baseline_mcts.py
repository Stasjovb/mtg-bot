"""End-to-end smoke tests for the full MCTS-on-MTG baseline:

  ProgressiveWidening + mtg_default_prior + MtgHeuristicEvaluator

These verify the components compose without crashing and that the
heuristic-driven baseline runs faster than the random-rollout
baseline (the whole point — heuristic eval is O(1) per leaf vs.
RandomRolloutEvaluator's full game playout).

Not a strength test — measuring "does MCTS-with-heuristic actually
beat MCTS-with-rollouts at MTG" requires a tuned budget, multiple
games, and seed sweeps. That's a follow-up exercise once we want
real win-rate numbers.
"""

from __future__ import annotations

import random
import time

from mtg_bot.actions import PassPriority
from mtg_bot.agents import RandomAgent
from mtg_bot.search import (
    Budget, MCTS, MtgGameStateAdapter, MtgHeuristicEvaluator,
    ProgressiveWidening, RandomRolloutEvaluator,
    mtg_default_prior,
)
from mtg_bot.simulate import setup_game
from tests._test_decks import simple_test_decklists  # noqa: E402


def _adapter(seed: int = 42) -> MtgGameStateAdapter:
    state = setup_game([RandomAgent(), RandomAgent()], decks=simple_test_decklists(), seed=seed,
    )
    return MtgGameStateAdapter(state, expose_combat_decisions=True)


def _baseline_mcts(seed: int = 0) -> MCTS:
    """The full PoC stack: progressive widening + MTG prior +
    heuristic evaluator."""
    return MCTS(
        evaluator=MtgHeuristicEvaluator(),
        budget_factory=lambda: Budget(max_nodes=20),
        rng=random.Random(seed),
        expansion_policy=ProgressiveWidening(prior=mtg_default_prior),
    )


def test_baseline_mcts_returns_legal_decision():
    """The composed stack returns a legal decision without crashing."""
    adapter = _adapter()
    mcts = _baseline_mcts(seed=1)
    pick = mcts.choose(adapter, adapter.active_player())
    assert pick in adapter.legal_decisions()


def test_baseline_mcts_leaves_caller_state_unchanged():
    adapter = _adapter()
    step_before = adapter.engine_state.step
    prio_before = adapter.active_player()
    mcts = _baseline_mcts(seed=2)
    mcts.choose(adapter, adapter.active_player())
    assert adapter.engine_state.step == step_before
    assert adapter.active_player() == prio_before


def _drive_to_precombat_main(adapter: MtgGameStateAdapter) -> None:
    """Drive through UPKEEP/DRAW by passing priority until we hit
    a state with real choices (PRECOMBAT_MAIN). Bails if the game
    unexpectedly ends first."""
    from mtg_bot.turn import Step

    for _ in range(50):
        if adapter.is_terminal():
            return
        if adapter.engine_state.step == Step.PRECOMBAT_MAIN:
            return
        adapter.apply(PassPriority())


def test_heuristic_evaluator_is_faster_than_random_rollout():
    """The whole point of swapping evaluators: heuristic should be
    much faster than playing a game out at random. Measured at
    precombat-main where MCTS has non-trivial decisions and will
    actually invoke the evaluator."""
    adapter_h = _adapter()
    adapter_r = _adapter()
    _drive_to_precombat_main(adapter_h)
    _drive_to_precombat_main(adapter_r)
    BUDGET = 30

    heuristic_mcts = MCTS(
        evaluator=MtgHeuristicEvaluator(),
        budget_factory=lambda: Budget(max_nodes=BUDGET),
        rng=random.Random(10),
        expansion_policy=ProgressiveWidening(prior=mtg_default_prior),
    )
    rollout_mcts = MCTS(
        evaluator=RandomRolloutEvaluator(rng=random.Random(11)),
        budget_factory=lambda: Budget(max_nodes=BUDGET),
        rng=random.Random(12),
        expansion_policy=ProgressiveWidening(prior=mtg_default_prior),
    )

    t0 = time.perf_counter()
    heuristic_mcts.choose(adapter_h, adapter_h.active_player())
    t_heuristic = time.perf_counter() - t0

    t0 = time.perf_counter()
    rollout_mcts.choose(adapter_r, adapter_r.active_player())
    t_rollout = time.perf_counter() - t0

    # The heuristic should be at least 2x faster — it's O(battlefield
    # + hand) per leaf vs. an entire game playout. In practice 10x+ is
    # typical, but we keep the assertion loose to avoid CI flakiness.
    assert t_heuristic * 2 < t_rollout, (
        f"heuristic ({t_heuristic:.3f}s) was not at least 2x faster "
        f"than rollout ({t_rollout:.3f}s)"
    )


def test_baseline_mcts_drives_a_game_to_progress():
    """Running the baseline as P0 against a random P1 makes the
    game advance through turns without crashing."""
    adapter = _adapter()
    mcts = _baseline_mcts(seed=3)

    # Track turn progression as a proof-of-life signal.
    start_turn = adapter.engine_state.turn_number
    decisions_made = 0
    MAX_DECISIONS = 100  # cap to keep the test fast
    while not adapter.is_terminal() and decisions_made < MAX_DECISIONS:
        pid = adapter.active_player()
        if pid == 0:
            decision = mcts.choose(adapter, pid)
        else:
            # P1 plays the simplest baseline: always pass when it
            # can, else first legal.
            legal = adapter.legal_decisions()
            decision = next(
                (d for d in legal if isinstance(d, PassPriority)),
                legal[0],
            )
        adapter.apply(decision)
        decisions_made += 1

    assert (
        adapter.engine_state.turn_number > start_turn
        or adapter.is_terminal()
    )
