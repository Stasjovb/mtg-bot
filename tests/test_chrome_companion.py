"""Tests for Chrome Companion — becomes_tapped lifegain + activated
grave-to-bottom ability + the new PutCardFromGraveyardOnBottomOfLibrary
effect."""

from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.actions import drain_stack
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.effects import PutCardFromGraveyardOnBottomOfLibrary
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import tap_permanent
from tests._etb_helpers import _legacy_or_inferred_key, _matches_legacy_key

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state(agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=agent or _PickFirstAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


# -----------------------
# PutCardFromGraveyardOnBottomOfLibrary effect
# -----------------------


def test_effect_requires_target_and_describe():
    e = PutCardFromGraveyardOnBottomOfLibrary()
    assert e.requires_target()
    d = e.describe()
    assert "graveyard" in d and "bottom" in d


def test_effect_legal_targets_from_both_graveyards():
    state = _new_state()
    a = state.new_object(BASIC_LANDS["Forest"], 0, Zone.GRAVEYARD)
    state.players[0].graveyard.append(a)
    b = state.new_object(BASIC_LANDS["Plains"], 1, Zone.GRAVEYARD)
    state.players[1].graveyard.append(b)
    legal = PutCardFromGraveyardOnBottomOfLibrary().legal_targets(state, 0)
    ids = {tid for kind, tid in legal if kind == "card_in_graveyard"}
    assert {a.id, b.id} <= ids


def test_effect_moves_card_from_own_graveyard_to_bottom_of_library():
    state = _new_state()
    a = state.new_object(BASIC_LANDS["Forest"], 0, Zone.GRAVEYARD)
    state.players[0].graveyard.append(a)
    # Pre-existing library cards — new card should go to bottom (end).
    b = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
    state.players[0].library.append(b)
    PutCardFromGraveyardOnBottomOfLibrary().resolve(
        state, 0, (("card_in_graveyard", a.id),),
    )
    assert a not in state.players[0].graveyard
    assert state.players[0].library[-1] is a
    assert a.zone == Zone.LIBRARY


def test_effect_moves_card_from_opponents_graveyard():
    state = _new_state()
    a = state.new_object(BASIC_LANDS["Forest"], 1, Zone.GRAVEYARD)
    state.players[1].graveyard.append(a)
    PutCardFromGraveyardOnBottomOfLibrary().resolve(
        state, 0, (("card_in_graveyard", a.id),),
    )
    assert a not in state.players[1].graveyard
    assert state.players[1].library[-1] is a


def test_effect_no_target_is_noop():
    state = _new_state()
    PutCardFromGraveyardOnBottomOfLibrary().resolve(state, 0, ())


def test_effect_wrong_kind_is_noop():
    state = _new_state()
    PutCardFromGraveyardOnBottomOfLibrary().resolve(
        state, 0, (("creature", 1),),
    )


# -----------------------
# Chrome Companion integration
# -----------------------


def test_chrome_companion_gains_life_on_becoming_tapped():
    state = _new_state()
    chrome = state.new_object(
        _PRINTINGS["Chrome Companion"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(chrome)
    life_before = state.players[0].life
    tap_permanent(state, chrome)
    drain_stack(state)
    assert chrome.tapped is True
    assert state.players[0].life == life_before + 1


def test_chrome_companion_lifegain_does_not_repeat_when_already_tapped():
    state = _new_state()
    chrome = state.new_object(
        _PRINTINGS["Chrome Companion"], 0, Zone.BATTLEFIELD,
    )
    chrome.tapped = True
    state.battlefield.append(chrome)
    life_before = state.players[0].life
    # tap_permanent no-ops when already tapped — trigger shouldn't fire.
    tap_permanent(state, chrome)
    drain_stack(state)
    assert state.players[0].life == life_before


def test_chrome_printing_has_trigger_and_activated_ability():
    c = _PRINTINGS["Chrome Companion"]
    triggers = {_legacy_or_inferred_key(ab) for ab in c.triggered_abilities}
    assert "becomes_tapped" in triggers
    assert len(c.activated_abilities) == 1
    cost = c.activated_abilities[0].cost
    assert cost.tap_self and cost.mana_str == "{2}"
