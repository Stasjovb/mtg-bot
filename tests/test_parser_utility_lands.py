"""Parser support for colorless utility lands.

The first utility-land kind the parser claims is the "tap-for-{C}
plus dropped activated abilities" shape — Secluded Starforge today.
The branch matches plain ``Land`` cards (no supertypes, no subtypes)
whose first oracle line is exactly ``"{T}: Add {C}."`` and reuses the
static-side ``make_colorless_land`` factory, dropping the trailing
activated-ability lines the parser doesn't model.

Other utility lands (Command Bridge — ETB sac-self trigger + any-color
mana ability) are out of scope this batch and remain skipped.
"""

from __future__ import annotations

from mtg_bot.cards.base import make_colorless_land
from mtg_bot.cards.parser.land_builder import _build_land_printing
from mtg_bot.cards.parser_source import OracleParserCardSource


_STARFORGE_CARD = {
    "name": "Secluded Starforge",
    "mana_cost": "",
    "type_line": "Land",
    "oracle_text": (
        "{T}: Add {C}.\n"
        "{2}, {T}, Tap X untapped artifacts you control: Target "
        "creature gets +X/+0 until end of turn. Activate only as a "
        "sorcery.\n"
        "{5}, {T}: Create a 2/2 colorless Robot artifact creature "
        "token."
    ),
    "produced_mana": ["C"],
}


def test_build_land_printing_claims_secluded_starforge():
    """The Scryfall-shaped Starforge record builds a colorless utility
    land — name, type line, no abilities, no produces (generic-only)."""
    printing = _build_land_printing(_STARFORGE_CARD)
    assert printing is not None
    assert printing.name == "Secluded Starforge"
    assert printing.is_land
    assert printing.is_basic_land is False
    assert printing.supertypes == ()
    assert printing.card_types == ("Land",)
    assert printing.subtypes == ()
    # Colorless utility: no produced colors (taps for generic via the
    # auto-tap-for-cost fallback), no triggered or activated abilities.
    assert printing.produces == frozenset()
    assert printing.triggered_abilities == ()
    assert printing.activated_abilities == ()
    assert printing.enters_tapped is False


def test_build_land_printing_matches_static_make_colorless_land():
    """The parser-built printing must equal what the static registry
    produces via ``make_colorless_land`` — required by the parity
    gate, asserted directly here for fast feedback."""
    parsed = _build_land_printing(_STARFORGE_CARD)
    expected = make_colorless_land("Secluded Starforge")
    assert parsed == expected


def test_build_land_printing_skips_basic_with_extra_lines():
    """A non-basic ``Land`` whose first line is ``{T}: Add {C}.`` but
    has no further detail is also fine — same colorless-utility shape,
    just without the dropped abilities."""
    card = {
        "name": "Hypothetical Lone Tap",
        "mana_cost": "",
        "type_line": "Land",
        "oracle_text": "{T}: Add {C}.",
        "produced_mana": ["C"],
    }
    printing = _build_land_printing(card)
    assert printing is not None
    assert printing.name == "Hypothetical Lone Tap"
    assert printing.produces == frozenset()


def test_build_land_printing_skips_utility_land_with_subtypes():
    """A non-basic ``Land — <subtype>`` that taps for {C} is NOT this
    shape (subtypes mean it's something more specific, e.g. a Locus
    or named land type with its own grammar). Parser must skip rather
    than wrongly drop the subtype to coerce a colorless utility land.
    """
    card = {
        "name": "Hand-Crafted Locus",
        "mana_cost": "",
        "type_line": "Land — Locus",
        "oracle_text": "{T}: Add {C}.",
        "produced_mana": ["C"],
    }
    assert _build_land_printing(card) is None


def test_build_land_printing_skips_when_first_line_is_not_colorless_tap():
    """Command Bridge's first line is ``"This land enters tapped."``,
    not ``{T}: Add {C}.`` — must not match the colorless-utility
    branch even though it's a plain ``Land``.
    """
    card = {
        "name": "Command Bridge",
        "mana_cost": "",
        "type_line": "Land",
        "oracle_text": (
            "This land enters tapped.\n"
            "When this land enters, sacrifice it unless you tap an "
            "untapped permanent you control.\n"
            "{T}: Add one mana of any color."
        ),
    }
    assert _build_land_printing(card) is None


def test_build_land_printing_skips_legendary_supertype_with_colorless_tap():
    """A non-basic ``Land`` with another supertype (e.g. Legendary or
    Snow) is out of scope for the colorless-utility branch. The
    static-side ``make_colorless_land`` does support ``legendary=True``
    but we don't claim those yet — silent skip rather than miss the
    Legendary supertype on the type line.
    """
    card = {
        "name": "Hand-Crafted Legendary Tap",
        "mana_cost": "",
        "type_line": "Legendary Land",
        "oracle_text": "{T}: Add {C}.",
        "produced_mana": ["C"],
    }
    assert _build_land_printing(card) is None


def test_build_land_printing_skips_basic_supertype_with_colorless_tap():
    """A ``Basic Land`` (with the Basic supertype) is handled by the
    basic branch only — the colorless-utility branch must not steal a
    Basic whose oracle text happens to read ``{T}: Add {C}.`` (without
    parentheses, so the basic branch also rejects it).
    """
    card = {
        "name": "Hand-Crafted Wastes",
        "mana_cost": "",
        "type_line": "Basic Land — Wastes",
        "oracle_text": "{T}: Add {C}.",
        "produced_mana": ["C"],
    }
    # Basic supertype routes to the basic branch, which requires
    # parentheses around the reminder. No fallthrough to the
    # colorless-utility branch — the card is silently skipped.
    assert _build_land_printing(card) is None


def test_build_land_printing_skips_colorless_tap_with_colored_produced_mana():
    """Defensive: a plain ``Land`` whose first line is
    ``{T}: Add {C}.`` but whose ``produced_mana`` lists a color must
    not match — the card actually produces colored mana via some
    other ability, so dropping that ability would silently neuter it.
    """
    card = {
        "name": "Hand-Crafted Mixed",
        "mana_cost": "",
        "type_line": "Land",
        "oracle_text": (
            "{T}: Add {C}.\n"
            "{1}, {T}: Add {U}."
        ),
        "produced_mana": ["C", "U"],
    }
    assert _build_land_printing(card) is None


def test_build_land_printing_skips_empty_oracle_on_plain_land():
    """A plain ``Land`` with no oracle text at all has nothing to key
    off — must skip rather than build a stub colorless utility land."""
    card = {
        "name": "Hand-Crafted Empty",
        "mana_cost": "",
        "type_line": "Land",
        "oracle_text": "",
    }
    assert _build_land_printing(card) is None


def test_source_claims_secluded_starforge():
    """End-to-end: ``OracleParserCardSource`` walks the cached EoE
    Scryfall data and ends up claiming Secluded Starforge."""
    source = OracleParserCardSource()
    assert "Secluded Starforge" in source.claimed_names
    assert "Secluded Starforge" in source.get_printings()
