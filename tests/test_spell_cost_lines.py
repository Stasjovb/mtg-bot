"""Parser: alternative-cost / additional-cost lines
(:mod:`mtg_bot.cards.parser.spell_cost_lines`) and conditional riders
(:mod:`mtg_bot.cards.parser.conditional_phrases`)."""

from __future__ import annotations

import pytest

from mtg_bot.cards.parser.conditional_phrases import (
    combine_instead_rider,
    parse_an_opponent_draws,
    parse_cost_paid_conditional,
    parse_effect_with_instead_rider,
    parse_instead_rider,
)
from mtg_bot.cards.parser.spell_cost_lines import (
    detect_spell_costs,
    is_spell_cost_line,
    parse_additional_cost_line,
    parse_alternative_cost_line,
)
from mtg_bot.cards.parser.spell_builder import _build_spell_printing
from mtg_bot.cards.spell_costs import AdditionalCostOption, AlternativeCost
from mtg_bot.effects.conditions import DeliriumActive
from mtg_bot.effects.combinators import IfConditionElse
from mtg_bot.effects.generic.cast_conditionals import (
    AlternativeCostWasPaid,
    AnOpponentDrawsCards,
    SpellWasKicked,
)
from mtg_bot.effects.generic.damage import DealDamage
from mtg_bot.effects.object_predicates import IsCreature

from tests._spells_a_helpers import cube_printings


@pytest.mark.parametrize("line, expected", [
    (
        "You may pay 1 life and exile a blue card from your hand rather "
        "than pay this spell's mana cost.",
        AlternativeCost(pay_life=1, exile_card_color="U"),
    ),
    (
        "If it's not your turn, you may exile a green card from your hand "
        "rather than pay this spell's mana cost.",
        AlternativeCost(exile_card_color="G", turn="not_yours"),
    ),
    (
        "If it's your turn, you may sacrifice a Mountain rather than pay "
        "this spell's mana cost.",
        AlternativeCost(sacrifice_subtype="Mountain", turn="yours"),
    ),
    (
        "If you control a Swamp, you may pay 4 life rather than pay this "
        "spell's mana cost.",
        AlternativeCost(pay_life=4, requires_control_subtype="Swamp"),
    ),
    (
        "You may return an Island you control to its owner's hand rather "
        "than pay this spell's mana cost.",
        AlternativeCost(return_subtype="Island"),
    ),
    (
        "You may pay {1}{B} rather than pay this spell's mana cost.",
        AlternativeCost(mana="{1}{B}"),
    ),
])
def test_alternative_cost_lines(line, expected):
    assert parse_alternative_cost_line(line) == expected
    assert is_spell_cost_line(line)


@pytest.mark.parametrize("line", [
    "You may tap an untapped creature you control rather than pay this "
    "spell's mana cost.",
    "You may pay 1 life and pay 2 life rather than pay this spell's mana cost.",
    "You may pay {1}{B}.",
])
def test_alternative_cost_rejects(line):
    assert parse_alternative_cost_line(line) is None


def test_additional_cost_lines():
    assert parse_additional_cost_line(
        "As an additional cost to cast this spell, discard a card or pay 3 life.",
    ) == (
        AdditionalCostOption(kind="discard", amount=1),
        AdditionalCostOption(kind="pay_life", amount=3),
    )
    arms = parse_additional_cost_line(
        "As an additional cost to cast this spell, sacrifice a creature or "
        "discard a card.",
    )
    assert arms[0] == AdditionalCostOption(
        kind="sacrifice", permanent_filter=IsCreature(), label="creature",
    )
    # Single-arm costs are the casting substrate's (alt_casting).
    assert parse_additional_cost_line(
        "As an additional cost to cast this spell, pay X life.",
    ) is None
    assert parse_additional_cost_line(
        "As an additional cost to cast this spell, discard two cards.",
    ) is None


@pytest.mark.parametrize("line", [
    "As an additional cost to cast this spell, tap a creature.",
    "As an additional cost to cast this spell, sacrifice a wizard.",
    "As an additional cost to cast this spell, discard a card or tap a land.",
    "Draw a card.",
])
def test_additional_cost_rejects(line):
    assert parse_additional_cost_line(line) is None


def test_detect_spell_costs_skips_legacy_lines():
    text = (
        "As an additional cost to cast this spell, discard a card or pay 3 "
        "life.\nDraw a card."
    )
    assert detect_spell_costs(text, legacy_line=lambda l: "discard" in l) == (
        (), (),
    )
    alts, arms = detect_spell_costs(text)
    assert alts == () and len(arms) == 2
    # "sacrifice an artifact or creature" is ONE arm (the substrate's
    # additional_cost_sacrifice_filter), not a one-of choice.
    assert detect_spell_costs(
        "As an additional cost to cast this spell, sacrifice an artifact "
        "or creature.",
    ) == ((), ())


def test_build_spell_printing_threads_costs():
    printing = cube_printings()["Force of Will"]
    assert printing.alternative_costs == (
        AlternativeCost(pay_life=1, exile_card_color="U"),
    )
    assert cube_printings()["Bitter Triumph"].additional_cost_options


# ---------- conditional riders ----------


def test_cost_paid_conditional():
    eff = parse_cost_paid_conditional(
        "if the {1}{B} cost was paid, an opponent draws a card",
    )
    assert eff == IfConditionElse(
        condition=AlternativeCostWasPaid(),
        then_effect=AnOpponentDrawsCards(amount=1),
    )
    assert parse_cost_paid_conditional("if the {1} cost was paid, blorp") is None
    assert parse_cost_paid_conditional(
        "if the {1} cost was paid, destroy target creature",
    ) is None
    assert parse_cost_paid_conditional("draw a card") is None


def test_an_opponent_draws():
    assert parse_an_opponent_draws("an opponent draws two cards") == (
        AnOpponentDrawsCards(amount=2)
    )
    assert parse_an_opponent_draws("each opponent draws a card") is None


def test_instead_rider_forms():
    base = DealDamage(amount=2)
    assert parse_instead_rider(
        "if this spell was kicked, it deals 4 damage instead", base,
    ) == IfConditionElse(
        condition=SpellWasKicked(),
        then_effect=DealDamage(amount=4),
        else_effect=base,
    )
    assert parse_instead_rider(
        "Delirium — Foo deals 6 damage instead if there are four or "
        "more card types among cards in your graveyard.",
        base, "Foo",
    ).condition == DeliriumActive()
    # Unknown condition / variant / base shape all reject.
    assert parse_instead_rider("it deals 4 damage instead if it rains", base) is None
    assert parse_instead_rider(
        "if this spell was kicked, draw a card instead", base,
    ) is None
    assert parse_instead_rider("draw a card", base) is None
    assert parse_instead_rider(
        "if this spell was kicked, it deals 4 damage instead",
        AnOpponentDrawsCards(),
    ) is None


def test_effect_with_instead_rider_single_line():
    eff = parse_effect_with_instead_rider(
        "deals 2 damage to any target. If this spell was kicked, it deals "
        "4 damage instead",
    )
    assert isinstance(eff, IfConditionElse)
    assert parse_effect_with_instead_rider("deals 2 damage to any target") is None
    assert parse_effect_with_instead_rider(
        "blorp. If this spell was kicked, it deals 4 damage instead",
    ) is None


def test_combine_instead_rider_requires_two_parseable_clauses():
    assert combine_instead_rider(["Draw a card."], "X") is None
    assert combine_instead_rider(["Blorp.", "Blorp."], "X") is None


@pytest.mark.parametrize("name", [
    "Force of Will", "Force of Negation", "Force of Vigor", "Daze",
    "Snuff Out", "Mine Collapse", "Baleful Mastery", "Bitter Triumph",
    "Bone Shards", "Vicious Rivalry", "Burst Lightning", "Unholy Heat",
    "Fatal Push",
])
def test_cost_and_conditional_cards_claimed(name):
    assert name in cube_printings()
