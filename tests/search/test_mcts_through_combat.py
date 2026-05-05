"""End-to-end smoke tests: MCTS driving an adapter that exposes
combat decisions.

These are NOT win-rate tests. The goal is to prove MCTS can see
``AttackerDecision`` / ``BlockerDecision`` values in
``legal_decisions``, evaluate them, and return one without crashing
or leaking state corruption. Strong combat play comes later via
priors + a real evaluator.
"""

from __future__ import annotations

import random

from mtg_bot.agents import RandomAgent
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.game import Zone
from mtg_bot.search import (
    AttackerDecision, BlockerDecision, Budget, MCTS,
    MtgGameStateAdapter, ProgressiveWidening, RandomRolloutEvaluator,
)
from mtg_bot.search.heuristic_evaluator import MtgHeuristicEvaluator
from mtg_bot.simulate import setup_game
from mtg_bot.turn import Step
from tests._test_decks import simple_test_decklists  # noqa: E402


def _adapter_with_combat_ready_state(
    seed: int = 42,
) -> MtgGameStateAdapter:
    """Build a mid-game-ish state with creatures on both sides,
    wrapped in a combat-exposing adapter."""
    state = setup_game([RandomAgent(), RandomAgent()], decks=simple_test_decklists(), seed=seed,
    )
    for _ in range(2):
        p0_bear = state.new_object(
            SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
        )
        p0_bear.summoning_sick = False
        state.battlefield.append(p0_bear)
    p1_sapling = state.new_object(
        SYNTHETIC_CREATURES["Sapling"], owner_id=1, zone=Zone.BATTLEFIELD,
    )
    p1_sapling.summoning_sick = False
    state.battlefield.append(p1_sapling)
    return MtgGameStateAdapter(state, expose_combat_decisions=True)


def _drive_through_priority_until_step(
    adapter: MtgGameStateAdapter, target: Step,
) -> None:
    from mtg_bot.actions import PassPriority

    for _ in range(200):
        if adapter.is_terminal():
            return
        if adapter.engine_state.step == target:
            return
        legal = adapter.legal_decisions()
        pick = next(
            (d for d in legal if isinstance(d, PassPriority)), None,
        )
        if pick is None:
            return
        adapter.apply(pick)


def test_mcts_returns_attacker_decision_in_attacker_phase():
    adapter = _adapter_with_combat_ready_state()
    _drive_through_priority_until_step(adapter, Step.DECLARE_ATTACKERS)
    assert adapter.combat_phase == "attackers"

    mcts = MCTS(
        evaluator=RandomRolloutEvaluator(rng=random.Random(1)),
        budget_factory=lambda: Budget(max_nodes=8),
        rng=random.Random(2),
    )
    pick = mcts.choose(adapter, adapter.active_player())
    assert isinstance(pick, AttackerDecision)
    assert pick in adapter.legal_decisions()


def test_mcts_returns_blocker_decision_in_blocker_phase():
    adapter = _adapter_with_combat_ready_state()
    _drive_through_priority_until_step(adapter, Step.DECLARE_ATTACKERS)
    # Commit to attacking with all pending attackers.
    while adapter.combat_phase == "attackers":
        attack = next(
            d for d in adapter.legal_decisions()
            if isinstance(d, AttackerDecision) and d.attack
        )
        adapter.apply(attack)

    _drive_through_priority_until_step(adapter, Step.DECLARE_BLOCKERS)
    assert adapter.combat_phase == "blockers"

    mcts = MCTS(
        evaluator=RandomRolloutEvaluator(rng=random.Random(1)),
        budget_factory=lambda: Budget(max_nodes=8),
        rng=random.Random(2),
    )
    pick = mcts.choose(adapter, adapter.active_player())
    assert isinstance(pick, BlockerDecision)
    assert pick in adapter.legal_decisions()


def test_mcts_leaves_adapter_state_unchanged_during_combat_phase():
    adapter = _adapter_with_combat_ready_state()
    _drive_through_priority_until_step(adapter, Step.DECLARE_ATTACKERS)

    pending_before = list(adapter._pending_attackers)
    chosen_before = list(adapter._chosen_attackers)
    phase_before = adapter.combat_phase

    mcts = MCTS(
        evaluator=RandomRolloutEvaluator(rng=random.Random(0)),
        budget_factory=lambda: Budget(max_nodes=6),
        rng=random.Random(0),
    )
    mcts.choose(adapter, adapter.active_player())

    assert adapter.combat_phase == phase_before
    assert adapter._pending_attackers == pending_before
    assert adapter._chosen_attackers == chosen_before


def test_mcts_with_progressive_widening_through_combat():
    """Progressive widening keeps the branching factor in check
    during combat. End-to-end: MCTS with ProgressiveWidening can
    run through a state with multiple attackers without crashing."""
    adapter = _adapter_with_combat_ready_state()
    _drive_through_priority_until_step(adapter, Step.DECLARE_ATTACKERS)
    assert adapter.combat_phase == "attackers"

    mcts = MCTS(
        evaluator=RandomRolloutEvaluator(rng=random.Random(5)),
        budget_factory=lambda: Budget(max_nodes=20),
        rng=random.Random(6),
        expansion_policy=ProgressiveWidening(c=2.0, alpha=0.5),
    )
    pick = mcts.choose(adapter, adapter.active_player())
    assert pick in adapter.legal_decisions()


def test_mcts_blocks_lethal_attacker_with_idle_blocker():
    """Regression: with combat decisions exposed in production, MCTS
    must actually choose to block when blocking is the obviously
    correct move. Setup: P0 attacks with a 2/2 Wild Bear; P1 has an
    idle 2/2 Wild Bear and is at 1 life so taking the hit loses the
    game outright. MCTS (with the production heuristic evaluator)
    should pick the BlockerDecision that names the attacker, not the
    "don't block" option that lets the bear through for lethal.

    Prior to exposing combat decisions in the production adapters,
    the bot literally never blocked because MCTS never saw a
    BlockerDecision in ``legal_decisions`` — this test pins that
    fix."""
    state = setup_game([RandomAgent(), RandomAgent()], decks=simple_test_decklists(), seed=42,
    )
    p0_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    p0_bear.summoning_sick = False
    state.battlefield.append(p0_bear)
    p1_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.BATTLEFIELD,
    )
    p1_bear.summoning_sick = False
    state.battlefield.append(p1_bear)
    # P1 at 1 life — unblocked 2/2 = lethal, blocking = trade and survive.
    state.players[1].life = 1
    adapter = MtgGameStateAdapter(state, expose_combat_decisions=True)

    _drive_through_priority_until_step(adapter, Step.DECLARE_ATTACKERS)
    # P0 commits to the attack.
    while adapter.combat_phase == "attackers":
        attack = next(
            d for d in adapter.legal_decisions()
            if isinstance(d, AttackerDecision) and d.attack
        )
        adapter.apply(attack)

    _drive_through_priority_until_step(adapter, Step.DECLARE_BLOCKERS)
    assert adapter.combat_phase == "blockers"
    assert adapter.active_player() == 1  # P1 is the defender

    # Sanity-check: BlockerDecision options exist and include both
    # "block" and "don't block" — i.e. MCTS is genuinely making a
    # choice between blocking and not blocking, not picking from a
    # degenerate single-option list.
    legal = adapter.legal_decisions()
    assert any(
        isinstance(d, BlockerDecision) and d.attacker_id is not None
        for d in legal
    )
    assert any(
        isinstance(d, BlockerDecision) and d.attacker_id is None
        for d in legal
    )

    mcts = MCTS(
        evaluator=MtgHeuristicEvaluator(),
        budget_factory=lambda: Budget(max_nodes=32),
        rng=random.Random(0),
    )
    pick = mcts.choose(adapter, adapter.active_player())
    assert isinstance(pick, BlockerDecision)
    assert pick.attacker_id is not None, (
        "MCTS at low budget should block a lethal 2/2 attacker with "
        "an idle 2/2 blocker, but chose 'no block' instead"
    )


def test_mcts_drives_adapter_past_combat_phase():
    """Driving decisions through MCTS should eventually exit combat
    and land back at a priority moment with combat_phase=None."""
    adapter = _adapter_with_combat_ready_state()
    _drive_through_priority_until_step(adapter, Step.DECLARE_ATTACKERS)
    assert adapter.combat_phase == "attackers"

    mcts = MCTS(
        evaluator=RandomRolloutEvaluator(rng=random.Random(1)),
        budget_factory=lambda: Budget(max_nodes=5),
        rng=random.Random(2),
    )
    # Apply a bounded sequence of MCTS decisions; the phase should
    # resolve within a handful of steps.
    for _ in range(20):
        if adapter.combat_phase is None:
            break
        decision = mcts.choose(adapter, adapter.active_player())
        adapter.apply(decision)
    assert adapter.combat_phase is None
