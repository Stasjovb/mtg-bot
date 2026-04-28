"""Tests for Tractor Beam's simplified ETB tap."""

from mtg_bot.agents import RandomAgent
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.effects import TractorBeamETBEffect
from mtg_bot.game import GameState, Player, Zone, effective_power, effective_toughness
from tests._etb_helpers import _legacy_or_inferred_key, _matches_legacy_key

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def _put(state, printing, owner_id=0, attached_to=None):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    if attached_to is not None:
        obj.attached_to = attached_to
    state.battlefield.append(obj)
    return obj


def test_etb_taps_enchanted_creature():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    aura = _put(
        state, _PRINTINGS["Tractor Beam"], owner_id=0,
        attached_to=bear.id,
    )
    state.resolving_source = aura
    try:
        TractorBeamETBEffect().resolve(state, 0, ())
    finally:
        state.resolving_source = None
    assert bear.tapped


def test_etb_describe():
    d = TractorBeamETBEffect().describe()
    assert "tap" in d and "enchanted" in d


def test_etb_noop_when_not_attached():
    state = _new_state()
    aura = _put(state, _PRINTINGS["Tractor Beam"])
    state.resolving_source = aura
    try:
        TractorBeamETBEffect().resolve(state, 0, ())
    finally:
        state.resolving_source = None


def test_tractor_printing_has_etb():
    t = _PRINTINGS["Tractor Beam"]
    triggers = {_legacy_or_inferred_key(ab) for ab in t.triggered_abilities}
    assert "etb" in triggers


def test_tractor_beam_grants_no_pump():
    """Printed oracle has no P/T bonus — pin the un-pumped reality."""
    t = _PRINTINGS["Tractor Beam"]
    assert t.equipment_bonuses == (0, 0, frozenset())


def test_attached_bear_keeps_printed_pt():
    """A 2/2 bear enchanted by Tractor Beam stays 2/2 — no pump bonus
    from the aura."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])  # 2/2
    _put(state, _PRINTINGS["Tractor Beam"], attached_to=bear.id)
    assert effective_power(state, bear) == 2
    assert effective_toughness(state, bear) == 2
