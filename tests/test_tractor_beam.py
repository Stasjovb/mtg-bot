"""Tests for Tractor Beam's simplified ETB tap."""

from mtg_bot.agents import RandomAgent
from mtg_bot.cards import EOE_SPELLS, SYNTHETIC_CREATURES
from mtg_bot.effects import TractorBeamETBEffect
from mtg_bot.game import GameState, Player, Zone


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
        state, EOE_SPELLS["Tractor Beam"], owner_id=0,
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
    aura = _put(state, EOE_SPELLS["Tractor Beam"])
    state.resolving_source = aura
    try:
        TractorBeamETBEffect().resolve(state, 0, ())
    finally:
        state.resolving_source = None


def test_tractor_printing_has_etb():
    t = EOE_SPELLS["Tractor Beam"]
    triggers = {ab.trigger for ab in t.triggered_abilities}
    assert "etb" in triggers
