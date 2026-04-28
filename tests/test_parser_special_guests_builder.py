"""Tests for the Special Guests bonus-sheet whole-card dispatch.

The ``special_guests_builder`` module claims a small set of EoE
Special Guests reprints whose entire oracle text maps to a single
printing-level boolean flag. This test file pins the per-card
dispatch shape and the defensive surface-form / set-code gates.
"""

from __future__ import annotations

from mtg_bot.cards.parser.special_guests_builder import (
    _build_special_guest_printing,
)
from mtg_bot.cards.special_guests import SPECIAL_GUESTS_EOE


def test_magus_of_the_moon_matches_static():
    card = {
        "name": "Magus of the Moon",
        "type_line": "Creature — Human Wizard",
        "oracle_text": "Nonbasic lands are Mountains.",
        "set": "spg",
    }
    parsed = _build_special_guest_printing(card)
    assert parsed is not None
    assert parsed == SPECIAL_GUESTS_EOE["Magus of the Moon"]


def test_deafening_silence_matches_static():
    card = {
        "name": "Deafening Silence",
        "type_line": "Enchantment",
        "oracle_text": (
            "Each player can't cast more than one noncreature "
            "spell each turn."
        ),
        "set": "spg",
    }
    parsed = _build_special_guest_printing(card)
    assert parsed is not None
    assert parsed == SPECIAL_GUESTS_EOE["Deafening Silence"]


def test_skips_non_spg_set():
    """Defensive: a same-named card from a non-spg set must not
    claim — the Special Guest dispatch is gated on set code."""
    card = {
        "name": "Magus of the Moon",
        "type_line": "Creature — Human Wizard",
        "oracle_text": "Nonbasic lands are Mountains.",
        "set": "eoe",
    }
    assert _build_special_guest_printing(card) is None


def test_skips_unknown_name():
    """A spg-set card whose name isn't on the whitelist falls
    through to the silent-skip path — defending against Scryfall
    adding new bonus-sheet cards."""
    card = {
        "name": "Hypothetical New Special Guest",
        "type_line": "Creature — Human Wizard",
        "oracle_text": "Nonbasic lands are Mountains.",
        "set": "spg",
    }
    assert _build_special_guest_printing(card) is None


def test_skips_when_oracle_text_drifts():
    """Defensive: if Scryfall changes a printed wording, the
    surface-form sanity belt rejects the card rather than claiming
    a stale-modeled flag."""
    card = {
        "name": "Magus of the Moon",
        "type_line": "Creature — Human Wizard",
        # Hypothetical reword — the modeled flag still says
        # nonbasic-lands-are-mountains, so claiming would lock parity
        # to an out-of-date interpretation.
        "oracle_text": "All nonbasic lands are Mountains.",
        "set": "spg",
    }
    assert _build_special_guest_printing(card) is None


def test_source_claims_both_via_data_walk():
    """End-to-end: the parser source's data walk picks up both
    Special Guests via the new dispatch."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    parser = OracleParserCardSource()
    parsed = parser.get_printings()
    assert "Magus of the Moon" in parsed
    assert "Deafening Silence" in parsed
    assert parsed["Magus of the Moon"] == SPECIAL_GUESTS_EOE["Magus of the Moon"]
    assert parsed["Deafening Silence"] == SPECIAL_GUESTS_EOE["Deafening Silence"]
