"""Accumulated Knowledge (Forgetful Fish): "Draw a card, then draw cards
equal to the number of cards named Accumulated Knowledge in all
graveyards." The resolving copy is on the stack, so it doesn't count
itself; a shared graveyard counts once."""

from __future__ import annotations

from mtg_bot.cards.parser.fish_cards import parse_fish_effect
from mtg_bot.effects.combinators import Sequence
from mtg_bot.effects.generic.draw_mill import DrawCards
from mtg_bot.effects.generic.roto_mana import CardsNamedInAllGraveyards
from mtg_bot.effects.generic.roto_walkers import DrawCardsEqualTo
from mtg_bot.formats import FORGETFUL_FISH
from mtg_bot.game import Zone

from tests._fish_helpers import cast, lands, make_state, place, printing

AK = "Accumulated Knowledge"


def _ready(in_graveyard: int, shared: bool = False):
    state = make_state()
    if shared:
        state.game_format = FORGETFUL_FISH
        state.players[1].graveyard = state.players[0].graveyard
        state.players[1].library = state.players[0].library
    lands(state, 0, "Island", 2)
    for _ in range(10):
        place(state, 0, "Island", Zone.LIBRARY)
    for i in range(in_graveyard):
        place(state, i % 2, AK, Zone.GRAVEYARD)
    spell = place(state, 0, AK, Zone.HAND)
    return state, spell


def test_parses_to_draw_then_draw_per_named_card():
    assert printing(AK).spell_effect == Sequence(effects=(
        DrawCards(amount=1),
        DrawCardsEqualTo(count=CardsNamedInAllGraveyards(AK)),
    ))
    assert parse_fish_effect("draw cards equal to the number of gizmos") is None


def test_first_copy_draws_one():
    state, spell = _ready(0)
    cast(state, 0, spell)
    assert len(state.players[0].hand) == 1


def test_counts_copies_in_every_graveyard():
    state, spell = _ready(2)  # one in each player's graveyard
    cast(state, 0, spell)
    assert len(state.players[0].hand) == 3
    # It went to the graveyard after resolving: the next one sees three.
    assert sum(c.printing.name == AK for c in state.players[0].graveyard) == 2


def test_shared_graveyard_counts_once():
    state, spell = _ready(3, shared=True)
    cast(state, 0, spell)
    assert len(state.players[0].hand) == 4
