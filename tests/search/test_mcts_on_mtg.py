"""End-to-end smoke tests: MCTS driving the real MTG engine via
``MtgGameStateAdapter``.

These aren't win-rate tests — MCTS with a useful evaluator against a
real MTG opponent is its own wave. The goal here is just to prove the
wiring works: MCTS can clone an adapter-wrapped state many times,
apply decisions down exploration paths, and return a legal choice
without corrupting the underlying engine state.

Budgets are tiny (single-digit to low-tens of nodes) because:
- Real-MTG cloning is ~100× more expensive than the toy games
- The Python 3.13 specializing-interpreter bug we hit on the search
  scaffold is avoided by keeping hot-loop iteration counts modest
"""

from __future__ import annotations

import random

from mtg_bot.actions import Action, PassPriority
from mtg_bot.agents import RandomAgent
from mtg_bot.search import (
    MCTS, Budget, MtgGameStateAdapter, RandomRolloutEvaluator,
)
from mtg_bot.simulate import setup_game
from tests._test_decks import simple_test_decklists  # noqa: E402


def _fresh_adapter(seed: int = 42) -> MtgGameStateAdapter:
    state = setup_game([RandomAgent(), RandomAgent()], decks=simple_test_decklists(), seed=seed,
    )
    return MtgGameStateAdapter(state)


def test_mcts_returns_a_legal_decision_on_real_mtg():
    """MCTS wrapped around the adapter returns one of the adapter's
    legal decisions, without crashing or raising."""
    adapter = _fresh_adapter()
    mcts = MCTS(
        evaluator=RandomRolloutEvaluator(rng=random.Random(1)),
        budget_factory=lambda: Budget(max_nodes=8),
        rng=random.Random(2),
    )
    legal = adapter.legal_decisions()
    decision = mcts.choose(adapter, adapter.active_player())
    assert decision in legal


def test_mcts_leaves_caller_state_unchanged():
    """MCTS clones internally — the caller's adapter must be the
    same after the call as before."""
    adapter = _fresh_adapter()
    step_before = adapter.engine_state.step
    prio_before = adapter.active_player()
    turn_before = adapter.engine_state.turn_number
    hand_before = [
        [c.id for c in p.hand] for p in adapter.engine_state.players
    ]

    mcts = MCTS(
        evaluator=RandomRolloutEvaluator(rng=random.Random(0)),
        budget_factory=lambda: Budget(max_nodes=5),
        rng=random.Random(0),
    )
    mcts.choose(adapter, adapter.active_player())

    assert adapter.engine_state.step == step_before
    assert adapter.active_player() == prio_before
    assert adapter.engine_state.turn_number == turn_before
    hand_after = [
        [c.id for c in p.hand] for p in adapter.engine_state.players
    ]
    assert hand_after == hand_before


def test_mcts_forced_pass_shortcut_on_upkeep():
    """When only PassPriority is legal (typical at UPKEEP with no
    triggers), MCTS returns it immediately — tested implicitly via
    the forced-move shortcut in MCTS.choose."""
    adapter = _fresh_adapter()
    # Fresh state at UPKEEP; only PassPriority is legal.
    assert all(
        isinstance(a, PassPriority) for a in adapter.legal_decisions()
    )
    mcts = MCTS(
        evaluator=RandomRolloutEvaluator(rng=random.Random(0)),
        budget_factory=lambda: Budget(max_nodes=1_000),
        rng=random.Random(0),
    )
    pick = mcts.choose(adapter, adapter.active_player())
    assert isinstance(pick, PassPriority)


def test_mcts_drives_adapter_through_full_decision_chain():
    """Drive a short game: at each decision moment, ask MCTS for a
    choice and apply it to the caller's adapter. Make sure the
    engine makes progress (turn counter eventually goes up) without
    exceptions."""
    adapter = _fresh_adapter()
    mcts = MCTS(
        evaluator=RandomRolloutEvaluator(rng=random.Random(5)),
        budget_factory=lambda: Budget(max_nodes=5),
        rng=random.Random(6),
    )
    start_turn = adapter.engine_state.turn_number
    decisions_made = 0
    MAX_DECISIONS = 200
    while not adapter.is_terminal() and decisions_made < MAX_DECISIONS:
        decision = mcts.choose(adapter, adapter.active_player())
        adapter.apply(decision)
        decisions_made += 1
    # Engine made at least SOME progress.
    assert (
        adapter.engine_state.turn_number > start_turn
        or adapter.is_terminal()
    )
