"""Tests for Station Monitor's second-spell-each-turn Drone-token trigger."""

from mtg_bot.actions import _cast_spell, drain_stack, resolve_top_of_stack
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS, TOKEN_PRINTINGS
from mtg_bot.game import GameState, Player, Zone
from tests._etb_helpers import _legacy_or_inferred_key, _matches_legacy_key

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def _stock_red_mana(state, count: int) -> None:
    for _ in range(count):
        m = state.new_object(BASIC_LANDS["Mountain"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(m)


def test_station_monitor_creates_drone_on_second_spell():
    state = _new_state()
    sm = state.new_object(
        _PRINTINGS["Station Monitor"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(sm)
    _stock_red_mana(state, 2)
    bolt1 = state.new_object(_PRINTINGS["Plasma Bolt"], 0, Zone.HAND)
    bolt2 = state.new_object(_PRINTINGS["Plasma Bolt"], 0, Zone.HAND)
    state.players[0].hand.extend([bolt1, bolt2])
    # First spell — no trigger, no Drone yet.
    _cast_spell(state, 0, bolt1.id)
    assert not any(o.printing.name == "Drone" for o in state.battlefield)
    resolve_top_of_stack(state)
    # Second spell — trigger fires on cast and goes on top of the stack.
    _cast_spell(state, 0, bolt2.id)
    drain_stack(state)
    drones = [
        o for o in state.battlefield
        if o.printing.name == "Drone" and o.controller_id == 0
    ]
    assert len(drones) == 1


def test_station_monitor_drone_is_flying_artifact_creature():
    d = TOKEN_PRINTINGS["Drone"]
    assert d.is_creature and d.is_artifact and d.is_token
    assert "flying" in d.keywords
    assert d.power == 1 and d.toughness == 1


def test_station_monitor_only_fires_once_per_turn():
    """Even with 3+ spells, the second-spell trigger fires once per turn."""
    state = _new_state()
    sm = state.new_object(
        _PRINTINGS["Station Monitor"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(sm)
    _stock_red_mana(state, 3)
    for _ in range(3):
        bolt = state.new_object(_PRINTINGS["Plasma Bolt"], 0, Zone.HAND)
        state.players[0].hand.append(bolt)
    for _ in range(3):
        bolt = state.players[0].hand[0]
        _cast_spell(state, 0, bolt.id)
        while state.stack:
            resolve_top_of_stack(state)
    drones = [o for o in state.battlefield if o.printing.name == "Drone"]
    assert len(drones) == 1


def test_station_monitor_printing_has_second_spell_trigger():
    sm = _PRINTINGS["Station Monitor"]
    triggers = {_legacy_or_inferred_key(ab) for ab in sm.triggered_abilities}
    assert "second_spell_each_turn" in triggers
