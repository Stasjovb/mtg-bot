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

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


def test_magus_of_the_moon_falls_through_to_creature_builder():
    """Magus is no longer claimed by the special-guests dispatch — the
    ``Nonbasic lands are Mountains.`` static is recognized in the
    creature builder via ``_parse_nonbasic_lands_are_mountains_line``,
    which sets the printing-level flag. The special-guests builder
    returns ``None`` so the chain falls through to the creature
    builder."""
    card = {
        "name": "Magus of the Moon",
        "type_line": "Creature — Human Wizard",
        "oracle_text": "Nonbasic lands are Mountains.",
        "set": "spg",
    }
    assert _build_special_guest_printing(card) is None
    # End-to-end: the active source still claims it (via creature builder).
    assert _PRINTINGS["Magus of the Moon"].nonbasic_lands_are_mountains is True


def test_deafening_silence_falls_through_to_enchantment_builder():
    """Deafening Silence is no longer claimed by the special-guests
    dispatch — the noncreature-spell static is recognized by the
    enchantment builder's printing-flag-only fallback path, which sets
    the ``restricts_noncreature_spells_to_one_per_turn`` flag. The
    special-guests builder returns ``None`` so the chain falls
    through."""
    card = {
        "name": "Deafening Silence",
        "type_line": "Enchantment",
        "oracle_text": (
            "Each player can't cast more than one noncreature "
            "spell each turn."
        ),
        "set": "spg",
    }
    assert _build_special_guest_printing(card) is None
    # End-to-end: the active source still claims it (via enchantment).
    ds = _PRINTINGS["Deafening Silence"]
    assert ds.restricts_noncreature_spells_to_one_per_turn is True


def test_burgeoning_falls_through_to_enchantment_builder():
    """Burgeoning is no longer claimed by the special-guests dispatch —
    the opponent-plays-land trigger is recognized by the enchantment
    builder's unified oracle-text fallback, which produces the same
    ``OptionalPutLandFromHandOntoBattlefield`` effect via the
    generalized ``you may put a (creature|land) card from your hand
    onto the battlefield`` regex (shared with Sledge-Class Seedship's
    creature variant)."""
    from mtg_bot.effects.predicates import Event
    card = {
        "name": "Burgeoning",
        "type_line": "Enchantment",
        "oracle_text": (
            "Whenever an opponent plays a land, you may put a land "
            "card from your hand onto the battlefield."
        ),
        "set": "spg",
    }
    assert _build_special_guest_printing(card) is None
    # End-to-end: the active source still claims it (via enchantment).
    burgeoning = _PRINTINGS["Burgeoning"]
    assert len(burgeoning.triggered_abilities) == 1
    assert burgeoning.triggered_abilities[0].event == Event.PLAYS_LAND


def test_sliver_overlord_matches_static():
    card = {
        "name": "Sliver Overlord",
        "type_line": "Legendary Creature — Sliver Mutant",
        "oracle_text": (
            "{3}: Search your library for a Sliver card, reveal "
            "that card, put it into your hand, then shuffle.\n"
            "{3}: Gain control of target Sliver. (This effect "
            "lasts indefinitely.)"
        ),
        "set": "spg",
    }
    parsed = _build_special_guest_printing(card)
    assert parsed is not None
    assert parsed == _PRINTINGS["Sliver Overlord"]


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
    assert parsed["Magus of the Moon"] == _PRINTINGS["Magus of the Moon"]
    assert parsed["Deafening Silence"] == _PRINTINGS["Deafening Silence"]
