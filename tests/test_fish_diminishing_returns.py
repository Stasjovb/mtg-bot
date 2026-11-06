"""Diminishing Returns (Forgetful Fish): "Each player shuffles their hand
and graveyard into their library. You exile the top ten cards of your
library. Then each player draws up to seven cards." With one shared
library and graveyard, every hand and the graveyard go into it once."""

from __future__ import annotations

from mtg_bot.effects.generic.fish_cards import EachPlayerDrawsUpTo
from mtg_bot.formats import FORGETFUL_FISH
from mtg_bot.game import Zone

from tests._fish_helpers import cast, lands, make_state, place, printing, script


def _fish_state():
    state = make_state()
    state.game_format = FORGETFUL_FISH
    state.players[1].library = state.players[0].library
    state.players[1].graveyard = state.players[0].graveyard
    return state


def test_parses():
    eff = printing("Diminishing Returns").spell_effect
    assert eff.effects[2] == EachPlayerDrawsUpTo(amount=7)
    assert "up to 7" in eff.effects[2].describe()


def test_shared_zones_shuffle_exile_ten_and_draw_up_to_seven():
    state = _fish_state()
    lands(state, 0, "Island", 4)
    for _ in range(20):
        place(state, 0, "Island", Zone.LIBRARY)
    for _ in range(5):
        place(state, 0, "Predict", Zone.GRAVEYARD)
    for _ in range(3):
        place(state, 1, "Dandân", Zone.HAND)
    place(state, 0, "Portent", Zone.HAND)
    spell = place(state, 0, "Diminishing Returns", Zone.HAND)
    script(state, 0, "x", 7)
    script(state, 1, "x", 2)
    cast(state, 0, spell)
    # 20 + 5 + 3 + 1 = 29 cards went into the one library; 10 exiled.
    assert len(state.players[0].exile) == 10
    assert len(state.players[0].hand) == 7
    assert len(state.players[1].hand) == 2
    assert len(state.players[0].library) == 29 - 10 - 9
    assert [c.printing.name for c in state.players[0].graveyard] == ["Diminishing Returns"]


def test_a_player_may_draw_none():
    state = _fish_state()
    for _ in range(3):
        place(state, 0, "Island", Zone.LIBRARY)
    script(state, 0, "x", 0)
    script(state, 1, "x", 9)  # clamped to the 3 cards left
    EachPlayerDrawsUpTo(amount=7).resolve(state, 0)
    assert len(state.players[0].hand) == 0
    assert len(state.players[1].hand) == 3
