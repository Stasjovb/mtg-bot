"""Tests for Larval Scoutlander's land/Lander sac ramp ETB."""

from mtg_bot.actions import put_into_battlefield, resolve_top_of_stack
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import (
    BASIC_LANDS,
    EOE_SPELLS,
    SYNTHETIC_CREATURES,
    TOKEN_PRINTINGS,
)
from mtg_bot.effects import (
    OptionalSacLandOrLanderForBasicLandRamp,
    SearchLibraryForBasicLandTapped,
)
from mtg_bot.game import GameState, Player, Zone


class _PickFirstAgent(Agent):
    def choose_sacrifice(self, state, player_id, legal_object_ids):
        return legal_object_ids[0]


def _new_state(agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=agent or _PickFirstAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


# -----------------------
# SearchLibraryForBasicLandTapped with count
# -----------------------


def test_search_basic_land_count_two():
    state = _new_state()
    p = state.players[0]
    f1 = state.new_object(BASIC_LANDS["Forest"], 0, Zone.LIBRARY)
    p.library.append(f1)
    f2 = state.new_object(BASIC_LANDS["Forest"], 0, Zone.LIBRARY)
    p.library.append(f2)
    SearchLibraryForBasicLandTapped(count=2).resolve(state, 0, ())
    assert f1 in state.battlefield
    assert f2 in state.battlefield
    assert f1.tapped
    assert f2.tapped


def test_search_basic_land_fewer_than_count():
    state = _new_state()
    p = state.players[0]
    f = state.new_object(BASIC_LANDS["Forest"], 0, Zone.LIBRARY)
    p.library.append(f)
    SearchLibraryForBasicLandTapped(count=3).resolve(state, 0, ())
    assert f in state.battlefield


def test_search_basic_land_describe_pluralized():
    text = SearchLibraryForBasicLandTapped(count=2).describe()
    assert "up to 2" in text
    text_one = SearchLibraryForBasicLandTapped(count=1).describe()
    assert "a basic land" in text_one


# -----------------------
# OptionalSacLandOrLanderForBasicLandRamp
# -----------------------


def test_optional_sac_land_for_ramp_sacs_and_fetches():
    state = _new_state(_PickFirstAgent())
    p = state.players[0]
    land = state.new_object(BASIC_LANDS["Forest"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(land)
    # Add a second land for sac and some library lands to fetch.
    for _ in range(2):
        lib = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        p.library.append(lib)
    OptionalSacLandOrLanderForBasicLandRamp(land_count=2).resolve(
        state, 0, (),
    )
    # Forest was sacrificed.
    assert land not in state.battlefield
    assert land in p.graveyard
    # Two Plains fetched.
    bf_lands = [
        o for o in state.battlefield
        if o.printing.name == "Plains" and o.controller_id == 0
    ]
    assert len(bf_lands) == 2


def test_optional_sac_lander_counts_as_valid_sac():
    """A Lander token qualifies for the 'land or Lander' sac."""
    state = _new_state(_PickFirstAgent())
    p = state.players[0]
    lander = state.new_object(
        TOKEN_PRINTINGS["Lander"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(lander)
    for _ in range(2):
        lib = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        p.library.append(lib)
    OptionalSacLandOrLanderForBasicLandRamp(land_count=2).resolve(
        state, 0, (),
    )
    assert lander not in state.battlefield


def test_optional_sac_no_land_no_lander_noop():
    state = _new_state()
    OptionalSacLandOrLanderForBasicLandRamp(land_count=2).resolve(
        state, 0, (),
    )


def test_larval_scoutlander_etb_flow():
    state = _new_state(_PickFirstAgent())
    p = state.players[0]
    forest = state.new_object(BASIC_LANDS["Forest"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(forest)
    # Library lands to fetch.
    for _ in range(2):
        lib = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        p.library.append(lib)
    scout = state.new_object(
        EOE_SPELLS["Larval Scoutlander"], 0, Zone.HAND,
    )
    put_into_battlefield(state, scout, controller_id=0)
    while state.stack:
        resolve_top_of_stack(state)
    # Forest sacrificed, 2 Plains fetched.
    assert forest not in state.battlefield
    bf_plains = [
        o for o in state.battlefield
        if o.printing.name == "Plains" and o.controller_id == 0
    ]
    assert len(bf_plains) == 2


def test_optional_sac_land_describe():
    text = OptionalSacLandOrLanderForBasicLandRamp(land_count=2).describe()
    assert "2" in text
    assert "Lander" in text
