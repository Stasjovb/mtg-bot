"""Tests for Thrumming Hivepool — Sliver anthem + upkeep Sliver tokens.
(Real card also has Affinity for Slivers — that cost reduction is
still dropped.)"""

from mtg_bot.actions import drain_stack
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import EOE_SPELLS, TOKEN_PRINTINGS
from mtg_bot.game import GameState, Player, Zone, effective_keywords
from mtg_bot.turn import run_beginning_of_upkeep_triggers


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    state.active_player_idx = 0
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def test_sliver_token_printing():
    s = TOKEN_PRINTINGS["Sliver"]
    assert s.is_creature
    assert s.power == 1 and s.toughness == 1
    assert "Sliver" in s.subtypes


def test_hivepool_creates_two_slivers_on_upkeep():
    state = _new_state()
    _put(state, EOE_SPELLS["Thrumming Hivepool"])
    run_beginning_of_upkeep_triggers(state)
    drain_stack(state)
    slivers = [o for o in state.battlefield if o.printing.name == "Sliver"]
    assert len(slivers) == 2


def test_slivers_get_double_strike_and_haste_from_hivepool():
    state = _new_state()
    _put(state, EOE_SPELLS["Thrumming Hivepool"])
    sliver = _put(state, TOKEN_PRINTINGS["Sliver"])
    kws = effective_keywords(state, sliver)
    assert "double strike" in kws
    assert "haste" in kws


def test_non_sliver_does_not_get_anthem():
    state = _new_state()
    _put(state, EOE_SPELLS["Thrumming Hivepool"])
    from mtg_bot.cards import SYNTHETIC_CREATURES
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    kws = effective_keywords(state, bear)
    assert "double strike" not in kws
    assert "haste" not in kws


def test_hivepool_printing_metadata():
    h = EOE_SPELLS["Thrumming Hivepool"]
    assert h.is_artifact
    assert len(h.static_abilities) == 1
    triggers = {ab.trigger for ab in h.triggered_abilities}
    assert "beginning_of_upkeep" in triggers
