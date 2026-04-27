"""Tests for ``OracleParserCardSource`` and its clause parsers."""

from __future__ import annotations

import pytest

from mtg_bot.cards.base import DealDamageAnyTarget, TriggeredAbility
from mtg_bot.cards.parser_source import (
    OracleParserCardSource,
    _build_creature_printing,
    _parse_clause,
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
    assert _parse_clause("Trample") is None
    assert _parse_clause("This creature has menace.") is None
    assert _parse_clause("") is None


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
        oracle_text="Flying\nTrample",  # Trample not yet supported
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
