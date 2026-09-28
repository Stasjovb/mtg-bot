"""Cube glue bucket: recognizer edge cases for
``cards/parser/cube_glue_grammar.py`` -- every recognizer declines
(returns ``None``) rather than half-parsing, and the whole grammar is off
for EoE-only printings."""

from __future__ import annotations

import pytest

from mtg_bot.cards.parser import cube_glue_grammar as gg
from mtg_bot.cards.parser.creature_rmc_grammar import rmc_grammar_disabled

_NAME = "Comet, Stellar Pup"


@pytest.mark.parametrize("phrase", [
    "counter target creature spell or ability. At the beginning of your "
    "next main phase, add an amount of {C} equal to that spell's mana value",
    "counter up to one target spell. At the beginning of your next main "
    "phase, add an amount of {C} equal to that spell's mana value",
    "put frob +1/+1 counters on up to one target noncreature land you "
    "control. Untap it. It becomes a 0/0 Elemental creature that's still a land",
    "put three +1/+1 counters on up to one target widget. Untap it. It "
    "becomes a 0/0 Elemental creature that's still a land",
    "put three +1/+1 counters on up to one target noncreature land you "
    "control. Untap it. It becomes a 0/0 Elemental creature with "
    "frobnication that's still a land",
    "search your library for any number of glorp cards, put them onto the "
    "battlefield tapped, then shuffle",
    "tap target widget. Put two stun counters on it",
    "tap target creature. Put many stun counters on it",
    "target widget loses all abilities and becomes a green Elk creature "
    "with base power and toughness 3/3",
    "exchange control of target widget and target creature an opponent "
    "controls",
    "search your library for any number of glorp cards, exile them, then "
    "shuffle. Until end of turn, you may cast those cards without paying "
    "their mana costs",
    "you may play the exiled card without paying its mana cost if a "
    "library has many or fewer cards in it",
    "choose a card name, then reveal the top X cards of your library. Put "
    "all cards with the chosen name from among them into your hand and the "
    "rest into your graveyard",
    "return target glorp card from your graveyard to your hand",
    "choose target opponent and up to one target creature they control. "
    "They reveal their hand. You may exile a glorp card from their hand or "
    "the chosen creature until this creature leaves the battlefield",
    "exile the top card of your library. You may cast that card. If you "
    "don't, frobnicate",
    "exile the top card of your library. You may cast that card. If you "
    "don't, destroy target creature",
    'you get an emblem with "Frob." Frobnicate',
    "frobnicate. Then draw a card for each opponent who lost life this turn",
    "frobnicate. After this phase, there is an additional combat phase",
    "remove all charge counters from this artifact. Add one mana of any "
    "color for each loyalty counter removed this way",
])
def test_glue_effect_recognizers_decline_unparseable_parts(phrase):
    assert gg.parse_glue_effect(phrase) is None


def test_sequence_rejects_two_targeted_steps():
    from mtg_bot.effects.generic import DealDamageAnyTarget

    a = DealDamageAnyTarget(amount=1)
    assert gg._sequence(a, a) is None
    assert gg._sequence(a, None) is None


@pytest.mark.parametrize("line", [
    "During your turn, as long as Kaito has one or more loyalty counters on "
    "him, he's a 3/4 Ninja creature and has frobnication.",
    "During your turn, as long as Someone Else has one or more loyalty "
    "counters on him, he's a 3/4 Ninja creature.",
    "Frob.",
])
def test_walker_line_declines(line):
    assert gg.parse_glue_walker_line(line, "Kaito, Bane of Nightmares") is None


@pytest.mark.parametrize("body", [
    "Whenever you cast a spell, this emblem frobnicates.",
    "Glorp cards in your graveyard have retrace.",
    "Lands you control have frobnication.",
    "Frob.",
])
def test_emblem_declines(body):
    assert gg.parse_glue_emblem(body) is None


@pytest.mark.parametrize("line", [
    "1 or 2 — Frobnicate.",
    "1 or 2 — [+2], then frobnicate.",
    "3 — frobnicate, then [−2].",
    "4 — Comet deals 2 damage to any target.",
    "5 — [+1], and you may activate Comet's loyalty ability many more times "
    "this turn.",
    "6 — [+1], then create two 1/1 green Squirrel creature tokens. They gain "
    "frobnication until end of turn.",
    "Not a row.",
])
def test_die_rows_decline(line):
    assert gg.parse_glue_die_row(line, _NAME) is None


def test_die_row_shapes():
    lo, hi, eff = gg.parse_glue_die_row("1-3 — Draw a card.", _NAME)
    assert (lo, hi) == (1, 3) and type(eff).__name__ == "DrawCards"
    lo, hi, eff = gg.parse_glue_die_row("4 — [+1].", _NAME)
    assert (lo, hi) == (4, 4) and eff.delta == 1
    assert gg.parse_glue_die_roll_body("Roll a d6.") == 6
    assert gg.assemble_die_table(4, [(1, 3, None)]) is None


def test_number_words():
    assert gg._number("20") == 20
    assert gg._number("twenty") == 20
    assert gg._number("umpteen") is None


def test_grammar_is_off_for_eoe_only_printings():
    with rmc_grammar_disabled():
        assert gg.parse_glue_effect(
            "return the exiled card to its owner's hand"
        ) is None
        assert gg.parse_glue_walker_line(
            gg._OPPONENTS_CANT_MAKE_YOU_DISCARD_OR_SACRIFICE, "Tamiyo",
        ) is None
        assert gg.parse_glue_emblem("Ninjas you control get +1/+1.") is None
        assert gg.parse_glue_keyword_trigger("Hideaway 4") is None
        assert gg.parse_glue_die_roll_body("Roll a six-sided die.") is None
        assert gg.parse_glue_die_row("4 — [+1].", _NAME) is None
