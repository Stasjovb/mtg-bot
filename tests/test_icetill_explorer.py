"""Tests for Icetill Explorer — additional-land-per-turn + landfall mill
+ play-lands-from-graveyard."""

from mtg_bot import legal_moves
from mtg_bot.actions import PlayLand, apply_action, drain_stack
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step
from tests._etb_helpers import _legacy_or_inferred_key, _matches_legacy_key

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


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
    _put(state, _PRINTINGS["Icetill Explorer"])
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
    _put(state, _PRINTINGS["Icetill Explorer"])
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
    i = _PRINTINGS["Icetill Explorer"]
    assert i.grants_additional_land_per_turn == 1
    assert i.grants_play_lands_from_graveyard is True
    triggers = {_legacy_or_inferred_key(ab) for ab in i.triggered_abilities}
    assert "landfall" in triggers


def test_icetill_explorer_lists_graveyard_lands_as_legal_plays():
    """Oracle: 'You may play lands from your graveyard.' With Icetill in
    play, the controller's graveyard land cards should appear as
    PlayLand legal actions alongside hand lands."""
    state = _new_state()
    _put(state, _PRINTINGS["Icetill Explorer"])
    # Forest in hand AND a Plains in graveyard.
    hand_land = state.new_object(BASIC_LANDS["Forest"], 0, Zone.HAND)
    state.players[0].hand.append(hand_land)
    grave_land = state.new_object(BASIC_LANDS["Plains"], 0, Zone.GRAVEYARD)
    state.players[0].graveyard.append(grave_land)
    play_actions = [a for a in legal_moves(state) if isinstance(a, PlayLand)]
    play_ids = {a.card_id for a in play_actions}
    assert hand_land.id in play_ids
    assert grave_land.id in play_ids


def test_icetill_explorer_play_land_from_graveyard_removes_from_grave():
    """Resolving a PlayLand for a graveyard card moves it to the
    battlefield, removes it from the graveyard, and counts toward the
    per-turn land cap."""
    state = _new_state()
    _put(state, _PRINTINGS["Icetill Explorer"])
    grave_land = state.new_object(BASIC_LANDS["Plains"], 0, Zone.GRAVEYARD)
    state.players[0].graveyard.append(grave_land)
    apply_action(state, 0, PlayLand(grave_land.id))
    drain_stack(state)
    assert grave_land in state.battlefield
    assert grave_land not in state.players[0].graveyard
    assert state.players[0].lands_played_this_turn == 1


def test_no_icetill_does_not_offer_graveyard_land_plays():
    """Without Icetill, graveyard lands are NOT offered as PlayLand
    actions (only hand lands are)."""
    state = _new_state()
    grave_land = state.new_object(BASIC_LANDS["Plains"], 0, Zone.GRAVEYARD)
    state.players[0].graveyard.append(grave_land)
    play_actions = [a for a in legal_moves(state) if isinstance(a, PlayLand)]
    play_ids = {a.card_id for a in play_actions}
    assert grave_land.id not in play_ids
