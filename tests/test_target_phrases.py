"""Compositional permanent noun-phrase grammar
(:mod:`mtg_bot.cards.parser.target_phrases`)."""

from __future__ import annotations

import pytest

from mtg_bot.cards.parser.target_phrases import (
    parse_permanent_phrase,
    parse_target_count,
)
from mtg_bot.effects.object_predicates import (
    ControlledByOpponent,
    ControlledByYou,
    HasPowerAtMost,
    HasToughnessAtMost,
    IsArtifact,
    IsBasic,
    IsCreature,
    IsEnchantment,
    IsLand,
    IsNontoken,
    IsPlaneswalker,
    IsTapped,
)
from mtg_bot.effects.value_predicates import (
    HasColor,
    HasManaValueAtMost,
    HasTotalPowerAndToughnessAtMost,
    IsPermanent,
)


@pytest.mark.parametrize("np, expected", [
    ("permanent", IsPermanent()),
    ("creature", IsCreature()),
    ("nonland permanent", IsPermanent() & ~IsLand()),
    ("creature or planeswalker", IsCreature() | IsPlaneswalker()),
    (
        "creature, enchantment, or planeswalker",
        (IsCreature() | IsEnchantment()) | IsPlaneswalker(),
    ),
    ("nonblack creature", IsCreature() & ~HasColor("B")),
    ("red creature", IsCreature() & HasColor("R")),
    ("nonbasic land", IsLand() & ~IsBasic()),
    ("basic land", IsLand() & IsBasic()),
    ("tapped creature", IsCreature() & IsTapped()),
    ("nontoken creature", IsCreature() & IsNontoken()),
    ("creature token", IsCreature() & ~IsNontoken()),
    ("creature you don't control", IsCreature() & ~ControlledByYou()),
    ("creature you control", IsCreature() & ControlledByYou()),
    ("creature an opponent controls", IsCreature() & ControlledByOpponent()),
    (
        "nonland permanent with mana value 3 or less",
        (IsPermanent() & ~IsLand()) & HasManaValueAtMost(3),
    ),
    (
        "creature with total power and toughness 5 or less",
        IsCreature() & HasTotalPowerAndToughnessAtMost(5),
    ),
    (
        "creature with power or toughness 2 or less",
        IsCreature() & (HasPowerAtMost(2) | HasToughnessAtMost(2)),
    ),
    (
        "noncreature artifact or noncreature enchantment",
        (IsArtifact() & ~IsCreature()) | (IsEnchantment() & ~IsCreature()),
    ),
])
def test_singular_noun_phrases(np, expected):
    assert parse_permanent_phrase(np) == expected


def test_plural_and_or_list():
    assert parse_permanent_phrase(
        "artifacts and/or enchantments", plural=True,
    ) == IsArtifact() | IsEnchantment()


def test_plural_requires_plural_heads():
    assert parse_permanent_phrase("artifact", plural=True) is None
    assert parse_permanent_phrase("creatures") is None


def test_controller_and_value_qualifiers_compose():
    f = parse_permanent_phrase(
        "creature an opponent controls with mana value 2 or less",
    )
    assert f == (IsCreature() & ControlledByOpponent()) & HasManaValueAtMost(2)


@pytest.mark.parametrize("np", [
    "",
    "wizard",
    "blah creature",
    "nonwizard creature",
    "creature or",
    "creature, , or planeswalker",
    "token",
])
def test_unknown_words_reject(np):
    assert parse_permanent_phrase(np) is None


@pytest.mark.parametrize("phrase, expected", [
    ("target creature", (1, 1, "creature")),
    ("up to one target creature", (0, 1, "creature")),
    ("up to two target artifacts", (0, 2, "artifacts")),
    ("up to X target artifacts", (0, "X", "artifacts")),
    ("one or two target creatures", (1, 2, "creatures")),
    ("two target creatures", (2, 2, "creatures")),
])
def test_parse_target_count(phrase, expected):
    assert parse_target_count(phrase) == expected


def test_parse_target_count_rejects_non_target_phrase():
    assert parse_target_count("each creature") is None
