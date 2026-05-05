"""Tests for the skip-dead-main1 priority short-circuit.

Heuristic contract:
- When ``skip_dead_main1_enabled=True`` (default) AND the active
  player has priority at PRECOMBAT_MAIN AND the stack is empty AND
  the active player controls 0 creatures AND no card in hand has
  the ``haste`` keyword AND no noncreature permanent has an
  activated ``BecomeLandCreatureUEOT`` effect, ``legal_decisions``
  returns ``[PassPriority()]`` without invoking
  ``legal.legal_actions``.
- Disabled by ANY of: a creature in play, a haste creature in
  hand, an animator permanent (manland), the disabled flag, opp
  priority, non-empty stack, non-PRECOMBAT_MAIN step.
"""

from __future__ import annotations

import dataclasses

from mtg_bot.actions import PassPriority
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.effects.base import ActivatedAbility
from mtg_bot.effects.generic.become_type import BecomeLandCreatureUEOT
from mtg_bot.game import Zone
from mtg_bot.search import HeuristicsConfig, MtgGameStateAdapter
from mtg_bot.simulate import setup_game
from mtg_bot.turn import Step
from tests._test_decks import simple_test_decklists  # noqa: E402


def _make_manland_printing(name: str = "Test Manland"):
    """Build a synthetic CardPrinting for a manland by extending the
    basic Forest with an animation activated ability."""
    base = BASIC_LANDS["Forest"]
    new_abilities = base.activated_abilities + (
        ActivatedAbility(
            cost=(),
            effect=BecomeLandCreatureUEOT(power=2, toughness=2),
        ),
    )
    return dataclasses.replace(
        base, name=name, activated_abilities=new_abilities,
    )


def _fresh_state(seed: int = 42):
    return setup_game([RandomAgent(), RandomAgent()], decks=simple_test_decklists(), seed=seed,
    )


def _force_main1(adapter, *, priority_idx: int | None = None):
    state = adapter.engine_state
    state.step = Step.PRECOMBAT_MAIN
    state.priority_player_idx = (
        priority_idx if priority_idx is not None
        else state.active_player_idx
    )
    adapter._step_entered = True
    adapter._pass_count = 0
    adapter._invalidate_legal_actions_cache()


def _strip_active_creatures_and_hand(state):
    """Remove all of active player's creatures from battlefield and
    empty the active player's hand, so we can build the test state
    explicitly."""
    active_id = state.players[state.active_player_idx].id
    state.battlefield = [
        o for o in state.battlefield
        if not (
            o.controller_id == active_id and o.permanent_is_creature
        )
    ]
    state.players[state.active_player_idx].hand = []


# ---------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------


def test_fires_with_no_creatures_no_haste_no_animator():
    state = _fresh_state()
    adapter = MtgGameStateAdapter(
        state, heuristics=HeuristicsConfig(skip_dead_main1_enabled=True),
    )
    _strip_active_creatures_and_hand(state)
    _force_main1(adapter)

    assert adapter._should_skip_dead_main1() is True
    assert adapter.legal_decisions() == [PassPriority()]


# ---------------------------------------------------------------------
# Negative cases — each guard
# ---------------------------------------------------------------------


def test_does_not_fire_with_creature_in_play():
    state = _fresh_state()
    adapter = MtgGameStateAdapter(state)
    _strip_active_creatures_and_hand(state)
    active_id = state.players[state.active_player_idx].id
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=active_id,
        zone=Zone.BATTLEFIELD,
    )
    bear.controller_id = active_id
    state.battlefield.append(bear)
    _force_main1(adapter)

    assert adapter._should_skip_dead_main1() is False


def test_does_not_fire_with_haste_creature_in_hand():
    state = _fresh_state()
    adapter = MtgGameStateAdapter(state)
    _strip_active_creatures_and_hand(state)
    active_id = state.players[state.active_player_idx].id
    haste_creature = state.new_object(
        SYNTHETIC_CREATURES["Goblin Runner"], owner_id=active_id,
        zone=Zone.HAND,
    )
    state.players[state.active_player_idx].hand.append(haste_creature)
    _force_main1(adapter)

    assert adapter._should_skip_dead_main1() is False


def test_fires_with_non_haste_creature_in_hand():
    """Conjugate: a creature in hand WITHOUT haste does not block the
    heuristic. Casting it at main 1 vs main 2 is functionally
    equivalent (no attack this turn either way, summoning sick)."""
    state = _fresh_state()
    adapter = MtgGameStateAdapter(
        state, heuristics=HeuristicsConfig(skip_dead_main1_enabled=True),
    )
    _strip_active_creatures_and_hand(state)
    active_id = state.players[state.active_player_idx].id
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=active_id,
        zone=Zone.HAND,
    )
    state.players[state.active_player_idx].hand.append(bear)
    _force_main1(adapter)

    assert adapter._should_skip_dead_main1() is True


def test_does_not_fire_with_animator_permanent_in_play():
    """Manland exception: a noncreature permanent with an activated
    ``BecomeLandCreatureUEOT`` ability blocks the heuristic — the
    player can animate and attack."""
    state = _fresh_state()
    adapter = MtgGameStateAdapter(state)
    _strip_active_creatures_and_hand(state)
    active_id = state.players[state.active_player_idx].id
    manland_printing = _make_manland_printing()
    manland = state.new_object(
        manland_printing, owner_id=active_id, zone=Zone.BATTLEFIELD,
    )
    manland.controller_id = active_id
    state.battlefield.append(manland)
    _force_main1(adapter)

    assert adapter._should_skip_dead_main1() is False


def test_animator_only_blocks_when_active_controls_it():
    """If the OPP controls the manland but active doesn't, the
    heuristic still fires — the active player can't attack with opp's
    permanent."""
    state = _fresh_state()
    adapter = MtgGameStateAdapter(
        state, heuristics=HeuristicsConfig(skip_dead_main1_enabled=True),
    )
    _strip_active_creatures_and_hand(state)
    opp_id = state.players[1 - state.active_player_idx].id
    manland_printing = _make_manland_printing()
    manland = state.new_object(
        manland_printing, owner_id=opp_id, zone=Zone.BATTLEFIELD,
    )
    manland.controller_id = opp_id
    state.battlefield.append(manland)
    _force_main1(adapter)

    assert adapter._should_skip_dead_main1() is True


def test_does_not_fire_at_opp_priority():
    state = _fresh_state()
    adapter = MtgGameStateAdapter(state)
    _strip_active_creatures_and_hand(state)
    _force_main1(
        adapter, priority_idx=1 - state.active_player_idx,
    )

    assert adapter._should_skip_dead_main1() is False


def test_does_not_fire_outside_precombat_main():
    state = _fresh_state()
    adapter = MtgGameStateAdapter(state)
    _strip_active_creatures_and_hand(state)
    for step in (
        Step.UPKEEP, Step.DRAW, Step.POSTCOMBAT_MAIN,
        Step.DECLARE_ATTACKERS, Step.END,
    ):
        adapter.engine_state.step = step
        adapter.engine_state.priority_player_idx = (
            adapter.engine_state.active_player_idx
        )
        adapter._step_entered = True
        adapter._pass_count = 0
        adapter._invalidate_legal_actions_cache()
        assert adapter._should_skip_dead_main1() is False, (
            f"step {step}: should not fire (not PRECOMBAT_MAIN)"
        )


def test_does_not_fire_with_non_empty_stack():
    state = _fresh_state()
    adapter = MtgGameStateAdapter(state)
    _strip_active_creatures_and_hand(state)
    _force_main1(adapter)
    state.stack.append(object())

    assert adapter._should_skip_dead_main1() is False


# ---------------------------------------------------------------------
# Disabled flag
# ---------------------------------------------------------------------


def test_disabled_flag():
    state = _fresh_state()
    adapter = MtgGameStateAdapter(
        state, heuristics=HeuristicsConfig(skip_dead_main1_enabled=False),
    )
    _strip_active_creatures_and_hand(state)
    _force_main1(adapter)

    assert adapter._should_skip_dead_main1() is False


# ---------------------------------------------------------------------
# Default + clone propagation
# ---------------------------------------------------------------------


def test_flag_propagates_through_clone():
    state = _fresh_state()
    adapter_on = MtgGameStateAdapter(
        state, heuristics=HeuristicsConfig(skip_dead_main1_enabled=True),
    )
    clone_on = adapter_on.clone()
    assert clone_on._heuristics.skip_dead_main1_enabled is True

    state2 = _fresh_state()
    adapter_off = MtgGameStateAdapter(
        state2,
        heuristics=HeuristicsConfig(skip_dead_main1_enabled=False),
    )
    clone_off = adapter_off.clone()
    assert clone_off._heuristics.skip_dead_main1_enabled is False
