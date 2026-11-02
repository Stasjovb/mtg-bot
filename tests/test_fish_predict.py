"""Predict (Forgetful Fish): "Choose a card name, then target player mills
a card. If a card with the chosen name was milled this way, you draw two
cards. Otherwise, you draw a card." In Fish the milled card comes off the
shared library, so the caster's own draws come after it."""

from __future__ import annotations

from mtg_bot.cards.parser.fish_cards import parse_fish_effect
from mtg_bot.effects.generic.fish_cards import NameThenMillDrawOnHit, all_card_names
from mtg_bot.formats import FORGETFUL_FISH
from mtg_bot.game import Zone

from tests._fish_helpers import cast, lands, make_state, place, printing, script


def _ready(top: str, named: str, *, shared: bool = True):
    state = make_state()
    if shared:
        state.game_format = FORGETFUL_FISH
        state.players[1].library = state.players[0].library
        state.players[1].graveyard = state.players[0].graveyard
    lands(state, 0, "Island", 2)
    place(state, 0, top, Zone.LIBRARY)
    for _ in range(4):
        place(state, 0, "Island", Zone.LIBRARY)
    spell = place(state, 0, "Predict", Zone.HAND)
    names = all_card_names(state)
    script(state, 0, "mode", names.index(named))
    script(state, 0, "target", ("player", 1))
    return state, spell


def test_parses():
    assert printing("Predict").spell_effect == NameThenMillDrawOnHit(mill=1, hit=2, miss=1)
    assert parse_fish_effect(
        "choose a card name, then target player mills a card. If a card with "
        "the chosen name was milled this way, you draw two cards. Otherwise, "
        "you draw a card"
    ) == NameThenMillDrawOnHit()


def test_naming_the_milled_card_draws_two():
    state, spell = _ready("Dandân", "Dandân")
    cast(state, 0, spell)
    assert [c.printing.name for c in state.players[0].graveyard][:1] == ["Dandân"]
    assert len(state.players[0].hand) == 2


def test_a_wrong_name_draws_one():
    state, spell = _ready("Dandân", "Island")
    cast(state, 0, spell)
    assert len(state.players[0].hand) == 1


def test_names_come_from_every_zone():
    state, _ = _ready("Dandân", "Dandân")
    assert {"Dandân", "Island", "Predict"} <= set(all_card_names(state))
