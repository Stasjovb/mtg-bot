"""Tests for the forced second-main land drop heuristic.

Heuristic contract:
- When ``force_landdrop_enabled=True`` (default) AND the active player
  has priority AND the stack is empty AND step is POSTCOMBAT_MAIN AND
  ``lands_played_this_turn == 0`` AND ≥1 land in hand AND <6 lands
  in play, ``PassPriority`` is filtered OUT of ``legal_decisions``.
- When ``force_landdrop_enabled=False``, the filter never fires — the
  adapter behaves as if the heuristic didn't exist.
- The filter applies AFTER full action enumeration (unlike phase-prune
  which short-circuits BEFORE legal_actions). It removes one option
  but the player can still cast spells / activate abilities.
- The heuristic is ACTIVE-only; opp's priority is unaffected.
- Conditions are deliberately conjoint: the filter does NOT fire if
  any one of land-played / has-land-in-hand / <6-lands / etc. fails.
"""

from __future__ import annotations

from mtg_bot.actions import PassPriority, PlayLand
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.game import Zone
from mtg_bot.search import HeuristicsConfig, MtgGameStateAdapter
from mtg_bot.simulate import setup_game
from mtg_bot.turn import Step


def _fresh_state(seed: int = 42):
    return setup_game(
        [RandomAgent(), RandomAgent()], ["G", "R"], seed=seed,
    )


def _give_basic_land(state, player_idx: int, name: str, *, in_hand: bool = True):
    """Inject a basic land into ``player_idx``'s hand or battlefield."""
    from mtg_bot.cards import BASIC_LANDS
    p = state.players[player_idx]
    obj = state.new_object(BASIC_LANDS[name], owner_id=p.id, zone=Zone.HAND)
    if in_hand:
        p.hand.append(obj)
    else:
        obj.controller_id = p.id
        obj.zone = Zone.BATTLEFIELD
        state.battlefield.append(obj)


def _force_postcombat_main(adapter):
    """Force the adapter into POSTCOMBAT_MAIN at active-player priority,
    with empty stack."""
    state = adapter.engine_state
    state.step = Step.POSTCOMBAT_MAIN
    state.priority_player_idx = state.active_player_idx
    adapter._step_entered = True
    adapter._pass_count = 0
    adapter._invalidate_legal_actions_cache()


def _strip_active_hand(state):
    """Empty the active player's hand so we can inject controlled
    contents."""
    active = state.players[state.active_player_idx]
    active.hand = []


def _strip_active_battlefield_lands(state):
    """Remove all of active player's lands from battlefield."""
    active_id = state.players[state.active_player_idx].id
    state.battlefield = [
        o for o in state.battlefield
        if not (
            o.controller_id == active_id and o.printing.is_land
        )
    ]


# ---------------------------------------------------------------------
# Happy path: filter fires when all conditions hold
# ---------------------------------------------------------------------


def test_filter_fires_at_postcombat_main_with_unspent_landdrop():
    """All conditions hold: filter fires — PassPriority removed,
    PlayLand stays."""
    state = _fresh_state()
    adapter = MtgGameStateAdapter(
        state, heuristics=HeuristicsConfig(force_landdrop_enabled=True),
    )
    _strip_active_hand(state)
    _strip_active_battlefield_lands(state)
    _give_basic_land(state, state.active_player_idx, "Forest", in_hand=True)
    state.players[state.active_player_idx].lands_played_this_turn = 0
    _force_postcombat_main(adapter)

    decisions = adapter.legal_decisions()

    assert not any(isinstance(d, PassPriority) for d in decisions), (
        "PassPriority should have been filtered out"
    )
    assert any(isinstance(d, PlayLand) for d in decisions), (
        "PlayLand option should remain available"
    )


# ---------------------------------------------------------------------
# Disabled-flag path
# ---------------------------------------------------------------------


def test_disabled_flag_keeps_pass_priority():
    """``force_landdrop_enabled=False`` disables the filter; the
    natural PassPriority remains in the decisions list even at
    fully-matching conditions."""
    state = _fresh_state()
    adapter = MtgGameStateAdapter(
        state, heuristics=HeuristicsConfig(force_landdrop_enabled=False),
    )
    _strip_active_hand(state)
    _strip_active_battlefield_lands(state)
    _give_basic_land(state, state.active_player_idx, "Forest", in_hand=True)
    state.players[state.active_player_idx].lands_played_this_turn = 0
    _force_postcombat_main(adapter)

    decisions = adapter.legal_decisions()
    assert any(isinstance(d, PassPriority) for d in decisions)


# ---------------------------------------------------------------------
# Negative cases: each condition guard
# ---------------------------------------------------------------------


def test_does_not_fire_at_precombat_main():
    """User explicitly scoped this to second main only —
    PRECOMBAT_MAIN should NOT fire even with all other conditions
    matching."""
    state = _fresh_state()
    adapter = MtgGameStateAdapter(
        state, heuristics=HeuristicsConfig(force_landdrop_enabled=True),
    )
    _strip_active_hand(state)
    _strip_active_battlefield_lands(state)
    _give_basic_land(state, state.active_player_idx, "Forest", in_hand=True)
    state.players[state.active_player_idx].lands_played_this_turn = 0
    state.step = Step.PRECOMBAT_MAIN
    state.priority_player_idx = state.active_player_idx
    adapter._step_entered = True
    adapter._pass_count = 0
    adapter._invalidate_legal_actions_cache()

    assert adapter._should_force_landdrop() is False


def test_does_not_fire_when_land_already_played():
    """``lands_played_this_turn > 0`` → filter does not fire."""
    state = _fresh_state()
    adapter = MtgGameStateAdapter(
        state, heuristics=HeuristicsConfig(force_landdrop_enabled=True),
    )
    _strip_active_hand(state)
    _strip_active_battlefield_lands(state)
    _give_basic_land(state, state.active_player_idx, "Forest", in_hand=True)
    state.players[state.active_player_idx].lands_played_this_turn = 1
    _force_postcombat_main(adapter)

    assert adapter._should_force_landdrop() is False


def test_does_not_fire_with_no_land_in_hand():
    """No land in active's hand → filter does not fire (otherwise
    we'd strip PassPriority and possibly leave an empty list)."""
    state = _fresh_state()
    adapter = MtgGameStateAdapter(
        state, heuristics=HeuristicsConfig(force_landdrop_enabled=True),
    )
    _strip_active_hand(state)
    _strip_active_battlefield_lands(state)
    # Hand has only a creature, no land.
    active = state.players[state.active_player_idx]
    creature = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=active.id,
        zone=Zone.HAND,
    )
    active.hand.append(creature)
    active.lands_played_this_turn = 0
    _force_postcombat_main(adapter)

    assert adapter._should_force_landdrop() is False


def test_does_not_fire_with_six_lands_in_play():
    """Land flood guard: 6+ lands in play → filter does not fire."""
    state = _fresh_state()
    adapter = MtgGameStateAdapter(
        state, heuristics=HeuristicsConfig(force_landdrop_enabled=True),
    )
    _strip_active_hand(state)
    _strip_active_battlefield_lands(state)
    active_idx = state.active_player_idx
    _give_basic_land(state, active_idx, "Forest", in_hand=True)
    for _ in range(6):
        _give_basic_land(state, active_idx, "Forest", in_hand=False)
    state.players[active_idx].lands_played_this_turn = 0
    _force_postcombat_main(adapter)

    assert adapter._should_force_landdrop() is False


def test_does_not_fire_with_non_empty_stack():
    """Non-empty stack → filter does not fire (the player may want
    to respond first)."""
    state = _fresh_state()
    adapter = MtgGameStateAdapter(
        state, heuristics=HeuristicsConfig(force_landdrop_enabled=True),
    )
    _strip_active_hand(state)
    _strip_active_battlefield_lands(state)
    _give_basic_land(state, state.active_player_idx, "Forest", in_hand=True)
    state.players[state.active_player_idx].lands_played_this_turn = 0
    _force_postcombat_main(adapter)
    state.stack.append(object())  # synthetic stack item

    assert adapter._should_force_landdrop() is False


def test_does_not_fire_at_opp_priority():
    """Opp's priority during second main → filter does not fire (it's
    active-only; opp doesn't have a land drop)."""
    state = _fresh_state()
    adapter = MtgGameStateAdapter(
        state, heuristics=HeuristicsConfig(force_landdrop_enabled=True),
    )
    _strip_active_hand(state)
    _strip_active_battlefield_lands(state)
    _give_basic_land(state, state.active_player_idx, "Forest", in_hand=True)
    state.players[state.active_player_idx].lands_played_this_turn = 0
    state.step = Step.POSTCOMBAT_MAIN
    state.priority_player_idx = 1 - state.active_player_idx
    adapter._step_entered = True
    adapter._pass_count = 0
    adapter._invalidate_legal_actions_cache()

    assert adapter._should_force_landdrop() is False


# ---------------------------------------------------------------------
# Five-land threshold: filter still fires at 5 lands in play
# ---------------------------------------------------------------------


def test_fires_with_five_lands_in_play():
    """5 lands in play is the upper inclusive bound for the filter
    (the guard is ``>= 6``)."""
    state = _fresh_state()
    adapter = MtgGameStateAdapter(
        state, heuristics=HeuristicsConfig(force_landdrop_enabled=True),
    )
    _strip_active_hand(state)
    _strip_active_battlefield_lands(state)
    active_idx = state.active_player_idx
    _give_basic_land(state, active_idx, "Forest", in_hand=True)
    for _ in range(5):
        _give_basic_land(state, active_idx, "Forest", in_hand=False)
    state.players[active_idx].lands_played_this_turn = 0
    _force_postcombat_main(adapter)

    assert adapter._should_force_landdrop() is True


# ---------------------------------------------------------------------
# Default flag value pin
# ---------------------------------------------------------------------


def test_flag_propagates_through_clone():
    """``force_landdrop_enabled`` survives ``clone()``. ISMCTS clones
    the root adapter many times per descent — both states must use
    the same heuristic setting."""
    state = _fresh_state()
    adapter_on = MtgGameStateAdapter(
        state, heuristics=HeuristicsConfig(force_landdrop_enabled=True),
    )
    clone_on = adapter_on.clone()
    assert clone_on._heuristics.force_landdrop_enabled is True

    state2 = _fresh_state()
    adapter_off = MtgGameStateAdapter(
        state2, heuristics=HeuristicsConfig(force_landdrop_enabled=False),
    )
    clone_off = adapter_off.clone()
    assert clone_off._heuristics.force_landdrop_enabled is False


# ---------------------------------------------------------------------
# Composition: spell-cast remains an option alongside PlayLand
# ---------------------------------------------------------------------


def test_filter_keeps_castable_spell_in_decisions():
    """User clarification: the filter strips PassPriority but keeps
    CastSpell — the player can sequence "cast spell, then play land"."""
    state = _fresh_state()
    adapter = MtgGameStateAdapter(
        state, heuristics=HeuristicsConfig(force_landdrop_enabled=True),
    )
    _strip_active_hand(state)
    _strip_active_battlefield_lands(state)
    active_idx = state.active_player_idx
    active = state.players[active_idx]
    # Give them a Mountain in hand AND a Mountain in play AND a
    # synthetic creature in hand to cast.
    _give_basic_land(state, active_idx, "Mountain", in_hand=True)
    _give_basic_land(state, active_idx, "Mountain", in_hand=False)
    creature = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=active.id,
        zone=Zone.HAND,
    )
    active.hand.append(creature)
    active.lands_played_this_turn = 0
    _force_postcombat_main(adapter)

    decisions = adapter.legal_decisions()
    # PassPriority filtered out.
    assert not any(isinstance(d, PassPriority) for d in decisions)
    # PlayLand still present.
    assert any(isinstance(d, PlayLand) for d in decisions)
