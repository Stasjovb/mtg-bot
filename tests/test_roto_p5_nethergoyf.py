"""Vintage Roto P5: Nethergoyf -- power from card types among cards in
your graveyard, and Escape whose exile part is "any number of other
cards from your graveyard with four or more card types among them"."""

from __future__ import annotations

from mtg_bot.actions import CastSpell
from mtg_bot.alt_casting import escape_payable, escape_terms, pay_escape_exile
from mtg_bot.cards.parser.roto_board import (
    parse_roto_board_line,
    parse_roto_dynamic_pt_line,
)
from mtg_bot.cards.parser.creature_rmc_grammar import rmc_grammar_disabled
from mtg_bot.effects.generic.roto_board import CardTypesInYourGraveyardPT
from mtg_bot.game import Zone, effective_power, effective_toughness
from mtg_bot.legal import legal_actions

from tests._roto_p5_helpers import (
    cast,
    lands,
    make_state,
    place,
    printing,
    vanilla,
)


def test_grammar():
    assert parse_roto_dynamic_pt_line(
        "Nethergoyf's power is equal to the number of card types among cards "
        "in your graveyard and its toughness is equal to that number plus 1."
    ) == CardTypesInYourGraveyardPT(plus=1)
    assert parse_roto_dynamic_pt_line("Nothing to see here.") is None
    with rmc_grammar_disabled():
        assert parse_roto_dynamic_pt_line(
            "X's power is equal to the number of card types among cards in "
            "your graveyard and its toughness is equal to that number plus 1."
        ) is None
    assert parse_roto_board_line(
        "Escape—{2}{B}, Exile any number of other cards from your graveyard "
        "with many or more card types among them.", {"name": "X"},
    ) is None


def test_nethergoyf_counts_only_its_controllers_graveyard():
    state = make_state()
    goyf = place(state, 0, "Nethergoyf")
    assert (effective_power(state, goyf), effective_toughness(state, goyf)) == (0, 1)
    place(state, 0, "Forest", Zone.GRAVEYARD)
    place(state, 0, "Lightning Bolt", Zone.GRAVEYARD)
    place(state, 0, "Lightning Bolt", Zone.GRAVEYARD)   # same type again
    place(state, 1, "Mox Pearl", Zone.GRAVEYARD)        # opponent's
    assert (effective_power(state, goyf), effective_toughness(state, goyf)) == (2, 3)


def _graveyard(state, names):
    return [place(state, 0, n, Zone.GRAVEYARD) for n in names]


def test_nethergoyf_escape_needs_four_card_types_among_other_cards():
    state = make_state()
    goyf = place(state, 0, "Nethergoyf", Zone.GRAVEYARD)
    _graveyard(state, ["Forest", "Lightning Bolt", "Mox Pearl"])
    lands(state, 0, "Swamp", 3)
    assert escape_terms(state, 0, goyf)[1] == -4
    assert not escape_payable(state, 0, goyf)
    assert CastSpell(goyf.id, use_escape=True) not in legal_actions(state, 0)
    _graveyard(state, ["Llanowar Elves"])
    assert escape_payable(state, 0, goyf)


def test_nethergoyf_escape_exiles_the_fewest_cards_covering_four_types():
    state = make_state()
    goyf = place(state, 0, "Nethergoyf", Zone.GRAVEYARD)
    forest, bolt, bolt2, mox, elves = _graveyard(
        state, ["Forest", "Lightning Bolt", "Lightning Bolt", "Mox Pearl",
                "Llanowar Elves"],
    )
    lands(state, 0, "Swamp", 3)
    cast(state, 0, goyf, use_escape=True)
    assert goyf in state.battlefield
    exiled = state.players[0].exile
    assert len(exiled) == 4 and bolt2 in state.players[0].graveyard
    assert {o.id for o in (forest, mox, elves)} <= {o.id for o in exiled}
    # Its own graveyard now holds one card type (instant).
    assert effective_power(state, goyf) == 1


def test_pay_escape_exile_stops_when_types_run_out():
    state = make_state()
    goyf = place(state, 0, "Nethergoyf", Zone.GRAVEYARD)
    _graveyard(state, ["Forest", "Lightning Bolt"])
    pay_escape_exile(state, 0, goyf, -4)
    assert len(state.players[0].exile) == 2


def test_plain_escape_cards_unaffected():
    printing_ = printing("Nethergoyf")
    assert printing_.escape_exile_count == 0
    assert printing_.escape_exile_card_types == 4
    state = make_state()
    bear = place(state, 0, vanilla(2, 2), Zone.GRAVEYARD)
    assert escape_terms(state, 0, bear) is None
