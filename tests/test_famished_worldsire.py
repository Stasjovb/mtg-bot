"""Tests for Famished Worldsire's Devour + ETB land-reveal."""

from mtg_bot.actions import put_into_battlefield, resolve_top_of_stack
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import (
    BASIC_LANDS,
    EOE_SPELLS,
    SYNTHETIC_CREATURES,
)
from mtg_bot.effects import FamishedWorldsireETBEffect
from mtg_bot.game import GameState, Player, Zone


class _DevourAllAgent(Agent):
    """Always sacrifices all the provided lands (for devour tests)."""

    def choose_devour_lands(self, state, player_id, land_ids):
        return list(land_ids)

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


class _NoDevourAgent(Agent):
    def choose_devour_lands(self, state, player_id, land_ids):
        return []

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state(agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=agent or _NoDevourAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def test_random_agent_choose_devour_lands_returns_empty():
    a = RandomAgent()
    assert a.choose_devour_lands(None, 0, [1, 2, 3]) == []


def test_famished_worldsire_devour_zero_lands_sacrificed():
    """With _NoDevourAgent, the creature enters with its printed P/T."""
    state = _new_state(_NoDevourAgent())
    ws = state.new_object(
        EOE_SPELLS["Famished Worldsire"], 0, Zone.HAND,
    )
    state.players[0].hand.append(ws)
    put_into_battlefield(state, ws, controller_id=0)
    assert ws.plus_one_counters == 0


def test_famished_worldsire_devour_sacrifices_lands_adds_counters():
    state = _new_state(_DevourAllAgent())
    p = state.players[0]
    # Two forests for sacrifice.
    f1 = state.new_object(BASIC_LANDS["Forest"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(f1)
    f2 = state.new_object(BASIC_LANDS["Forest"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(f2)
    ws = state.new_object(
        EOE_SPELLS["Famished Worldsire"], 0, Zone.HAND,
    )
    p.hand.append(ws)
    put_into_battlefield(state, ws, controller_id=0)
    # Both forests sacrificed → 3 * 2 = 6 +1/+1 counters.
    assert f1 not in state.battlefield
    assert f2 not in state.battlefield
    assert ws.plus_one_counters == 6


def test_famished_worldsire_has_devour_land_multiplier_three():
    assert EOE_SPELLS["Famished Worldsire"].devour_land_multiplier == 3


def test_famished_worldsire_etb_puts_library_lands_onto_battlefield():
    state = _new_state()
    p = state.players[0]
    # Library with a mix of lands and non-lands.
    for _ in range(2):
        land = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        p.library.append(land)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.LIBRARY,
    )
    p.library.append(bear)
    # Famished Worldsire on battlefield with power 6 (printed).
    ws = state.new_object(
        EOE_SPELLS["Famished Worldsire"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(ws)
    state.resolving_source = ws
    FamishedWorldsireETBEffect().resolve(state, 0, ())
    state.resolving_source = None
    bf_plains = [
        o for o in state.battlefield
        if o.printing.name == "Plains" and o.controller_id == 0
    ]
    assert len(bf_plains) == 2


def test_famished_worldsire_etb_x_equals_power():
    """With more counters, X grows and the library window widens."""
    state = _new_state()
    p = state.players[0]
    # Library with 10 lands.
    lands = []
    for _ in range(10):
        land = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        p.library.append(land)
        lands.append(land)
    ws = state.new_object(
        EOE_SPELLS["Famished Worldsire"], 0, Zone.BATTLEFIELD,
    )
    ws.plus_one_counters = 4  # effective power 10
    state.battlefield.append(ws)
    state.resolving_source = ws
    FamishedWorldsireETBEffect().resolve(state, 0, ())
    state.resolving_source = None
    bf_plains = [
        o for o in state.battlefield
        if o.printing.name == "Plains" and o.controller_id == 0
    ]
    # All 10 top lands put onto battlefield.
    assert len(bf_plains) == 10


def test_famished_worldsire_etb_no_source_noop():
    state = _new_state()
    FamishedWorldsireETBEffect().resolve(state, 0, ())


def test_famished_worldsire_etb_zero_power_noop():
    state = _new_state()
    ws = state.new_object(
        EOE_SPELLS["Famished Worldsire"], 0, Zone.BATTLEFIELD,
    )
    # Override printed power via temp bonus to force 0.
    ws.temp_power_bonus = -6
    state.battlefield.append(ws)
    state.resolving_source = ws
    FamishedWorldsireETBEffect().resolve(state, 0, ())
    state.resolving_source = None
    # Nothing happened.


def test_famished_worldsire_etb_describe():
    assert "X" in FamishedWorldsireETBEffect().describe()
