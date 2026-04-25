"""End-to-end integration tests: ``MtgGameStateAdapter`` with
``expose_resolution_decisions=True`` drives a priority action that
hits a resolution callback, exposes the decision to search, accepts
an answer, and completes.

Uses real EoE spells with target-choice requirements. Currently
target-picking happens at cast-time in our engine (``actions._cast_spell``
calls ``agent.choose_target`` before the spell goes on the stack),
but the adapter's save-and-replay machinery is agnostic to whether
the callback fires at cast-time or during resolution — both are
inside the same ``apply_action`` frame.
"""

from __future__ import annotations

import pytest

from mtg_bot.actions import CastSpell, PassPriority
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import EOE_SPELLS, SYNTHETIC_CREATURES
from mtg_bot.game import Zone
from mtg_bot.search import (
    MtgGameStateAdapter, ResolutionTargetDecision,
)
from mtg_bot.simulate import setup_game


def _adapter_with_targetable_setup() -> MtgGameStateAdapter:
    """Build a state where P0 can cast a 2-damage spell on one of
    several creatures P1 controls. Force the state into a
    precombat-main moment where the spell is actually legal."""
    state = setup_game(
        [RandomAgent(), RandomAgent()], ["G", "R"], seed=42,
    )
    # Give P0 five Mountains so they can pay {2}{R} for Bombard.
    from mtg_bot.cards import BASIC_LANDS
    for _ in range(5):
        m = state.new_object(
            BASIC_LANDS["Mountain"], owner_id=0, zone=Zone.BATTLEFIELD,
        )
        state.battlefield.append(m)
    # Put Bombard in P0's hand. (Oracle: "Bombard deals 4 damage
    # to target creature." — needs a target.)
    bombard_card = state.new_object(
        EOE_SPELLS["Bombard"], owner_id=0, zone=Zone.HAND,
    )
    state.players[0].hand.append(bombard_card)
    # Give P1 two creatures for targets.
    for name in ["Wild Bear", "Sapling"]:
        c = state.new_object(
            SYNTHETIC_CREATURES[name], owner_id=1,
            zone=Zone.BATTLEFIELD,
        )
        c.summoning_sick = False
        state.battlefield.append(c)

    return MtgGameStateAdapter(
        state, expose_resolution_decisions=True,
    )


def _drive_to_precombat_main(adapter: MtgGameStateAdapter) -> None:
    from mtg_bot.turn import Step
    for _ in range(20):
        if adapter.engine_state.step == Step.PRECOMBAT_MAIN:
            return
        adapter.apply(PassPriority())


def test_casting_targeted_spell_exposes_target_pause():
    """Casting Bombard exposes a resolution-pause with three target
    options (two creatures + player) — the exact options depend on
    the spell; what matters here is that the pause fires."""
    adapter = _adapter_with_targetable_setup()
    _drive_to_precombat_main(adapter)

    # Find the CastSpell action for Bombard.
    cast_action = next(
        a for a in adapter.legal_decisions()
        if isinstance(a, CastSpell)
    )
    # Pre-cast invariant: no pause, no snapshot.
    assert adapter._resolution_paused is False
    assert adapter._pre_action_clone is None

    adapter.apply(cast_action)

    # Post-cast invariant: paused, snapshot retained, waiting for
    # a target choice.
    assert adapter._resolution_paused is True
    assert adapter._pre_action_clone is not None
    assert adapter._resolution_kind == "target"
    # Legal decisions at this pause are Resolution*Decision values.
    legal = adapter.legal_decisions()
    assert all(
        isinstance(d, ResolutionTargetDecision) for d in legal
    )
    assert len(legal) >= 2  # at least two creatures


def test_providing_target_completes_the_cast():
    """Once search provides a target decision, resolution finishes
    and the adapter returns to a non-paused state with the spell
    on the stack (or resolved, depending on the engine flow)."""
    adapter = _adapter_with_targetable_setup()
    _drive_to_precombat_main(adapter)

    cast_action = next(
        a for a in adapter.legal_decisions()
        if isinstance(a, CastSpell)
    )
    adapter.apply(cast_action)
    assert adapter._resolution_paused

    # Pick the first available target.
    target_decision = adapter.legal_decisions()[0]
    adapter.apply(target_decision)

    # Resolution complete: adapter is back at a priority moment.
    assert adapter._resolution_paused is False
    assert adapter._pre_action_clone is None
    # State advanced — Bombard should now be on the stack.
    assert len(adapter.engine_state.stack) == 1


def test_providing_wrong_decision_type_raises():
    adapter = _adapter_with_targetable_setup()
    _drive_to_precombat_main(adapter)
    cast_action = next(
        a for a in adapter.legal_decisions()
        if isinstance(a, CastSpell)
    )
    adapter.apply(cast_action)
    assert adapter._resolution_paused

    # Feed a PlayerID instead of a ResolutionTargetDecision.
    with pytest.raises(TypeError):
        adapter.apply(PassPriority())


def test_clone_preserves_resolution_pause_state():
    """A clone of a paused adapter should be independently resumable
    — each clone can pick a different target."""
    adapter = _adapter_with_targetable_setup()
    _drive_to_precombat_main(adapter)
    cast_action = next(
        a for a in adapter.legal_decisions()
        if isinstance(a, CastSpell)
    )
    adapter.apply(cast_action)
    assert adapter._resolution_paused

    clone = adapter.clone()
    assert clone._resolution_paused is True
    assert clone._resolution_kind == adapter._resolution_kind
    assert clone._resolution_options == adapter._resolution_options

    # Different decisions on each; states diverge.
    target_a = adapter.legal_decisions()[0]
    target_b = clone.legal_decisions()[-1]
    adapter.apply(target_a)
    clone.apply(target_b)

    # Both completed resolution; neither still paused.
    assert not adapter._resolution_paused
    assert not clone._resolution_paused
    # Stack items target different creatures — verify via the
    # stack's first item's targets.
    a_targets = adapter.engine_state.stack[0].targets
    b_targets = clone.engine_state.stack[0].targets
    assert a_targets != b_targets


def test_shock_life_now_exposed_as_resolution_decision():
    """Shock-land ``choose_pay_shock_life`` is one of the 10
    resolution callbacks. With exposure on, playing a shock land
    pauses for a search decision on whether to pay the life."""
    from mtg_bot.actions import PlayLand
    from mtg_bot.cards import SHOCK_LANDS
    from mtg_bot.search import ResolutionShockLifeDecision
    if not SHOCK_LANDS:
        pytest.skip("no shock lands in the pool")

    state = setup_game(
        [RandomAgent(), RandomAgent()], ["G", "R"], seed=42,
    )
    shock_name = next(iter(SHOCK_LANDS))
    shock = state.new_object(
        SHOCK_LANDS[shock_name], owner_id=0, zone=Zone.HAND,
    )
    state.players[0].hand.append(shock)

    adapter = MtgGameStateAdapter(
        state, expose_resolution_decisions=True,
    )
    _drive_to_precombat_main(adapter)

    play_action = next(
        (a for a in adapter.legal_decisions()
         if isinstance(a, PlayLand) and a.card_id == shock.id),
        None,
    )
    if play_action is None:
        pytest.skip("shock land not legal to play this seed")

    adapter.apply(play_action)
    # Paused on the shock-life question.
    assert adapter._resolution_paused is True
    assert adapter._resolution_kind == "shock_life"
    legal = adapter.legal_decisions()
    assert all(
        isinstance(d, ResolutionShockLifeDecision) for d in legal
    )
    assert {d.pay for d in legal} == {True, False}
    # Answer and confirm completion.
    adapter.apply(ResolutionShockLifeDecision(pay=False))
    assert adapter._resolution_paused is False


def test_search_decision_is_hashable():
    """Sanity: Resolution*Decision values must be hashable so they
    can live in MCTS transposition tables etc."""
    d1 = ResolutionTargetDecision(target=("creature", 5))
    d2 = ResolutionTargetDecision(target=("creature", 5))
    assert hash(d1) == hash(d2)
    assert d1 == d2
    # Usable as dict key.
    {d1: "value"}
