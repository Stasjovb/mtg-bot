"""Tests for Icetill Explorer — additional-land-per-turn + landfall mill.
(Play-lands-from-graveyard dropped as a known simplification.)"""

from mtg_bot import legal_moves
from mtg_bot.actions import PlayLand, apply_action, drain_stack
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS, EOE_CREATURES
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def test_additional_land_per_turn_allows_second_land_play():
    state = _new_state()
    _put(state, EOE_CREATURES["Icetill Explorer"])
    land1 = state.new_object(BASIC_LANDS["Forest"], 0, Zone.HAND)
    land2 = state.new_object(BASIC_LANDS["Plains"], 0, Zone.HAND)
    state.players[0].hand.extend([land1, land2])
    apply_action(state, 0, PlayLand(land1.id))
    drain_stack(state)
    # Even after one play, another PlayLand action should still be legal
    # (up to 2 total per turn).
    land_plays = [a for a in legal_moves(state) if isinstance(a, PlayLand)]
    assert len(land_plays) >= 1
    apply_action(state, 0, PlayLand(land2.id))
    drain_stack(state)
    # 2 total lands played — further plays should not be legal.
    land_plays_after = [a for a in legal_moves(state) if isinstance(a, PlayLand)]
    assert land_plays_after == []


def test_no_icetill_limits_to_one_land_per_turn():
    """Sanity: without Icetill, the original 1-land cap still applies."""
    state = _new_state()
    land1 = state.new_object(BASIC_LANDS["Forest"], 0, Zone.HAND)
    land2 = state.new_object(BASIC_LANDS["Plains"], 0, Zone.HAND)
    state.players[0].hand.extend([land1, land2])
    apply_action(state, 0, PlayLand(land1.id))
    land_plays_after = [a for a in legal_moves(state) if isinstance(a, PlayLand)]
    assert land_plays_after == []


def test_landfall_mills_a_card_when_land_enters():
    state = _new_state()
    _put(state, EOE_CREATURES["Icetill Explorer"])
    # Seed library
    for _ in range(3):
        c = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        state.players[0].library.append(c)
    # Put a Forest into hand, play it — landfall should mill 1.
    forest = state.new_object(BASIC_LANDS["Forest"], 0, Zone.HAND)
    state.players[0].hand.append(forest)
    lib_before = len(state.players[0].library)
    gy_before = len(state.players[0].graveyard)
    apply_action(state, 0, PlayLand(forest.id))
    drain_stack(state)
    assert len(state.players[0].library) == lib_before - 1
    assert len(state.players[0].graveyard) == gy_before + 1


def test_icetill_printing_metadata():
    i = EOE_CREATURES["Icetill Explorer"]
    assert i.grants_additional_land_per_turn == 1
    triggers = {ab.trigger for ab in i.triggered_abilities}
    assert "landfall" in triggers
