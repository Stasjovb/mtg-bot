"""Tests for Weftwalking's ETB shuffle-hand-and-grave + draw-7 and
Possibility Technician's ETB impulse-exile (simplified)."""

from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS, EOE_CREATURES, EOE_SPELLS, SYNTHETIC_CREATURES
from mtg_bot.effects import PossibilityTechnicianETBEffect, WeftwalkingETBEffect
from mtg_bot.game import GameState, Player, Zone


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def _stock_library(state, player_id, n, printing=None):
    printing = printing or BASIC_LANDS["Plains"]
    p = state.players[player_id]
    for _ in range(n):
        c = state.new_object(printing, player_id, Zone.LIBRARY)
        p.library.append(c)


# -----------------------
# Weftwalking ETB
# -----------------------


def test_weftwalking_shuffles_hand_and_graveyard_into_library_and_draws_7():
    state = _new_state()
    p = state.players[0]
    # Hand has 2, graveyard has 3, library has 5.
    for _ in range(2):
        c = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.HAND)
        p.hand.append(c)
    for _ in range(3):
        c = state.new_object(BASIC_LANDS["Plains"], 0, Zone.GRAVEYARD)
        p.graveyard.append(c)
    _stock_library(state, 0, 5)
    WeftwalkingETBEffect().resolve(state, 0, ())
    # Hand contains exactly 7 cards (the draw). Graveyard is empty.
    # Library started with 5 + 2 (hand) + 3 (gy) = 10; drew 7 → 3 left.
    assert len(p.hand) == 7
    assert len(p.graveyard) == 0
    assert len(p.library) == 3


def test_weftwalking_describe():
    d = WeftwalkingETBEffect().describe()
    assert "shuffle" in d and "seven" in d


def test_weftwalking_printing_has_etb():
    w = EOE_SPELLS["Weftwalking"]
    triggers = {ab.trigger for ab in w.triggered_abilities}
    assert "etb" in triggers


# -----------------------
# Possibility Technician ETB
# -----------------------


def test_possibility_exiles_top_card_and_marks_playable_this_turn():
    state = _new_state()
    _stock_library(state, 0, 3)
    PossibilityTechnicianETBEffect().resolve(state, 0, ())
    p = state.players[0]
    assert len(p.exile) == 1
    assert p.exile[0].playable_from_exile_this_turn is True


def test_possibility_empty_library_noop():
    state = _new_state()
    PossibilityTechnicianETBEffect().resolve(state, 0, ())
    assert state.players[0].exile == []


def test_possibility_describe():
    d = PossibilityTechnicianETBEffect().describe()
    assert "exile" in d and "this turn" in d


def test_possibility_printing_has_etb_and_warp():
    pt = EOE_CREATURES["Possibility Technician"]
    assert pt.warp_cost_str == "{R}"
    triggers = {ab.trigger for ab in pt.triggered_abilities}
    assert "etb" in triggers
