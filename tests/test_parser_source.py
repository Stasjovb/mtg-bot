"""Tests for ``OracleParserCardSource`` and its clause parsers."""

from __future__ import annotations

import pytest

from mtg_bot.cards.base import DealDamageAnyTarget, TriggeredAbility
from mtg_bot.cards.parser_source import (
    OracleParserCardSource,
    _build_creature_printing,
    _parse_clause,
    _parse_effect_phrase,
    _parse_trigger_phrase,
    _parse_triggered_ability_line,
    _parse_type_line,
)


# ---------- _parse_clause ----------

def test_parse_clause_recognizes_flying():
    parsed = _parse_clause("Flying")
    assert parsed is not None
    assert parsed.keyword == "flying"
    assert parsed.trigger is None


def test_parse_clause_strips_surrounding_whitespace():
    assert _parse_clause("  Flying  ") == _parse_clause("Flying")


def test_parse_clause_recognizes_etb_damage_to_any_target():
    parsed = _parse_clause(
        "When this creature enters, it deals 3 damage to any target."
    )
    assert parsed is not None
    assert parsed.keyword is None
    assert parsed.trigger == TriggeredAbility(
        trigger="etb", effect=DealDamageAnyTarget(amount=3)
    )


def test_parse_clause_etb_damage_extracts_amount():
    parsed = _parse_clause(
        "When this creature enters, it deals 7 damage to any target."
    )
    assert parsed is not None
    assert parsed.trigger is not None
    assert parsed.trigger.effect == DealDamageAnyTarget(amount=7)


def test_parse_clause_returns_none_for_unknown_line():
    assert _parse_clause("Regenerate") is None
    assert _parse_clause("This creature has menace.") is None
    assert _parse_clause("") is None


# ---------- evergreen keyword lines ----------


@pytest.mark.parametrize(
    "line,engine_keyword",
    [
        ("Flying", "flying"),
        ("Trample", "trample"),
        ("Vigilance", "vigilance"),
        ("Haste", "haste"),
        ("Reach", "reach"),
        ("Deathtouch", "deathtouch"),
        ("Lifelink", "lifelink"),
        ("Defender", "defender"),
        ("Flash", "flash"),
        ("Menace", "menace"),
        ("Double strike", "double strike"),
        ("First strike", "first strike"),
        ("Prowess", "prowess"),
    ],
)
def test_parse_clause_recognizes_each_evergreen_keyword(line, engine_keyword):
    parsed = _parse_clause(line)
    assert parsed is not None
    assert parsed.keyword == engine_keyword
    assert parsed.trigger is None


def test_build_creature_printing_handles_each_evergreen_standalone():
    """Smoke-test: every evergreen keyword on its own oracle-text
    line produces the expected engine keyword on the printing."""
    base = {
        "name": "Test Creature",
        "mana_cost": "{1}",
        "type_line": "Creature — Human",
        "power": "1",
        "toughness": "1",
    }
    cases = [
        ("Flying", "flying"),
        ("Trample", "trample"),
        ("Vigilance", "vigilance"),
        ("Haste", "haste"),
        ("Reach", "reach"),
        ("Deathtouch", "deathtouch"),
        ("Lifelink", "lifelink"),
        ("Defender", "defender"),
        ("Flash", "flash"),
        ("Menace", "menace"),
        ("Double strike", "double strike"),
        ("First strike", "first strike"),
        ("Prowess", "prowess"),
    ]
    for line, engine_keyword in cases:
        printing = _build_creature_printing(dict(base, oracle_text=line))
        assert printing is not None, line
        assert printing.keywords == frozenset({engine_keyword}), line


# ---------- compositional triggered-ability parsing ----------

def test_parse_trigger_phrase_recognizes_etb():
    assert _parse_trigger_phrase("this creature enters") == "etb"


def test_parse_trigger_phrase_strips_whitespace():
    assert _parse_trigger_phrase("  this creature enters  ") == "etb"


def test_parse_trigger_phrase_returns_none_for_unknown():
    assert _parse_trigger_phrase("you draw a card") is None
    assert _parse_trigger_phrase("") is None


def test_parse_effect_phrase_recognizes_deal_damage_any_target():
    assert _parse_effect_phrase(
        "it deals 2 damage to any target"
    ) == DealDamageAnyTarget(amount=2)


def test_parse_effect_phrase_returns_none_for_unknown():
    assert _parse_effect_phrase("you gain 2 life") is None
    assert _parse_effect_phrase("") is None


def test_parse_triggered_ability_line_full_etb_damage():
    result = _parse_triggered_ability_line(
        "When this creature enters, it deals 5 damage to any target."
    )
    assert result == TriggeredAbility(
        trigger="etb", effect=DealDamageAnyTarget(amount=5)
    )


def test_parse_triggered_ability_line_accepts_whenever():
    """The line-level pattern matches both ``When`` and ``Whenever``;
    individual condition and effect parsers decide whether the
    surface pieces are recognized."""
    # No "Whenever this creature enters" trigger phrase, but the
    # line-level structural match should still be tried — failure
    # comes from the condition parser, not the line regex.
    assert _parse_triggered_ability_line(
        "Whenever you draw a card, it deals 1 damage to any target."
    ) is None  # condition phrase unknown


def test_parse_triggered_ability_line_rejects_non_trigger_lines():
    assert _parse_triggered_ability_line("Flying") is None
    assert _parse_triggered_ability_line(
        "This creature has menace."
    ) is None


def test_parse_triggered_ability_line_rejects_unknown_effect():
    """Trigger condition parses, effect doesn't → line as a whole
    fails (no fallback)."""
    assert _parse_triggered_ability_line(
        "When this creature enters, you gain 2 life."
    ) is None


# ---------- _parse_type_line ----------

def test_parse_type_line_simple_creature():
    assert _parse_type_line("Creature — Dragon") == (
        (), ("Creature",), ("Dragon",)
    )


def test_parse_type_line_legendary_multi_subtype():
    assert _parse_type_line("Legendary Creature — Human Soldier") == (
        ("Legendary",), ("Creature",), ("Human", "Soldier")
    )


def test_parse_type_line_no_subtypes():
    assert _parse_type_line("Sorcery") == ((), ("Sorcery",), ())


def test_parse_type_line_multi_card_type():
    assert _parse_type_line("Artifact Creature — Robot") == (
        (), ("Artifact", "Creature"), ("Robot",)
    )


def test_parse_type_line_empty():
    assert _parse_type_line("") == ((), (), ())


# ---------- _build_creature_printing ----------

_NEBULA_DRAGON_CARD = {
    "name": "Nebula Dragon",
    "mana_cost": "{6}{R}",
    "type_line": "Creature — Dragon",
    "power": "4",
    "toughness": "4",
    "oracle_text": (
        "Flying\n"
        "When this creature enters, it deals 3 damage to any target."
    ),
}


def test_build_creature_printing_handles_nebula_dragon():
    printing = _build_creature_printing(_NEBULA_DRAGON_CARD)
    assert printing is not None
    assert printing.name == "Nebula Dragon"
    assert printing.power == 4
    assert printing.toughness == 4
    assert printing.subtypes == ("Dragon",)
    assert printing.keywords == frozenset({"flying"})
    assert printing.triggered_abilities == (
        TriggeredAbility(
            trigger="etb", effect=DealDamageAnyTarget(amount=3)
        ),
    )


def test_build_creature_printing_skips_non_creatures():
    sorcery = {
        "name": "Plasma Bolt",
        "mana_cost": "{R}",
        "type_line": "Sorcery",
        "oracle_text": "...",
    }
    assert _build_creature_printing(sorcery) is None


def test_build_creature_printing_skips_unparsed_clause():
    card = dict(
        _NEBULA_DRAGON_CARD,
        # ``Regenerate`` is not in the keyword grammar, so this
        # whole card must be skipped.
        oracle_text="Flying\nRegenerate",
    )
    assert _build_creature_printing(card) is None


def test_build_creature_printing_skips_non_integer_power():
    card = dict(_NEBULA_DRAGON_CARD, power="*")
    assert _build_creature_printing(card) is None


def test_build_creature_printing_handles_empty_oracle_text():
    card = dict(_NEBULA_DRAGON_CARD, oracle_text="")
    printing = _build_creature_printing(card)
    assert printing is not None
    assert printing.keywords == frozenset()
    assert printing.triggered_abilities == ()


# ---------- OracleParserCardSource ----------

def test_source_claims_nebula_dragon():
    source = OracleParserCardSource()
    assert "Nebula Dragon" in source.claimed_names
    assert "Nebula Dragon" in source.get_printings()


def test_source_skips_cards_with_unsupported_clauses():
    """A card whose oracle text uses any clause beyond Flying or
    ETB-deals-N-damage-to-any-target must not be claimed."""
    source = OracleParserCardSource()
    # Plasma Bolt is an instant, not a creature — definitely not claimed.
    assert "Plasma Bolt" not in source.claimed_names


def test_source_get_printings_returns_only_claimed():
    source = OracleParserCardSource()
    assert set(source.get_printings()) == set(source.claimed_names)


def test_source_build_mono_color_deck_raises():
    with pytest.raises(NotImplementedError):
        OracleParserCardSource().build_mono_color_deck("R", seed=0)
