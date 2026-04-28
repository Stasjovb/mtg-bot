"""Parser support for Stellar Sights "simple" manlands.

The 6 EoE Stellar Sights manlands without bespoke per-animation
extensions share a fixed three-line oracle shape that maps cleanly
onto ``BecomeLandCreatureUEOT`` with a single keyword set. This
module verifies the parser claims those cards into the same shape
the static registry produces, and rejects near-miss variants
(extra abilities, X-cost activations, attacks-trigger riders, the
"It can't be blocked this turn." Tar Pit shape).
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    ActivatedAbility,
    ActivationCost,
    BecomeLandCreatureUEOT,
    make_utility_land,
    parse_mana_cost,
)
from mtg_bot.cards.parser.land_builder import (
    _build_land_printing,
    _parse_manland_keywords,
    _try_build_manland,
)
from mtg_bot.cards.stellar_sights import STELLAR_SIGHTS_LANDS


_SIMPLE_MANLAND_NAMES = (
    "Celestial Colonnade",
    "Hissing Quagmire",
    "Lumbering Falls",
    "Needle Spires",
    "Shambling Vent",
    "Stirring Wildwood",
)


def _shambling_vent_card() -> dict:
    return {
        "name": "Shambling Vent",
        "type_line": "Land",
        "oracle_text": (
            "This land enters tapped.\n"
            "{T}: Add {W} or {B}.\n"
            "{1}{W}{B}: Until end of turn, this land becomes a 2/3 "
            "white and black Elemental creature with lifelink. It's "
            "still a land."
        ),
        "produced_mana": ["B", "W"],
        "set": "eos",
    }


def test_shambling_vent_matches_static():
    parsed = _build_land_printing(_shambling_vent_card())
    assert parsed is not None
    assert parsed == STELLAR_SIGHTS_LANDS["Shambling Vent"]


def test_celestial_colonnade_matches_static():
    card = {
        "name": "Celestial Colonnade",
        "type_line": "Land",
        "oracle_text": (
            "This land enters tapped.\n"
            "{T}: Add {W} or {U}.\n"
            "{3}{W}{U}: Until end of turn, this land becomes a 4/4 "
            "white and blue Elemental creature with flying and "
            "vigilance. It's still a land."
        ),
        "produced_mana": ["U", "W"],
        "set": "eos",
    }
    parsed = _build_land_printing(card)
    assert parsed is not None
    assert parsed == STELLAR_SIGHTS_LANDS["Celestial Colonnade"]


def test_all_six_simple_manlands_claimed_with_parity():
    """End-to-end: every named simple manland is claimed by the
    parser and matches its static counterpart."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    parser = OracleParserCardSource()
    parsed = parser.get_printings()
    for name in _SIMPLE_MANLAND_NAMES:
        assert name in parsed, f"{name} not claimed"
        assert parsed[name] == STELLAR_SIGHTS_LANDS[name]


def test_skips_creeping_tar_pit_unblockable_rider():
    """Creeping Tar Pit's third line ends with ``It's still a land. It
    can't be blocked this turn.`` instead of ``with <KEYWORDS>``. The
    parser must NOT claim it via the simple-manland path — modeling
    the unblockable rider needs the dedicated builder."""
    card = {
        "name": "Creeping Tar Pit",
        "type_line": "Land",
        "oracle_text": (
            "This land enters tapped.\n"
            "{T}: Add {U} or {B}.\n"
            "{1}{U}{B}: Until end of turn, this land becomes a 3/2 "
            "blue and black Elemental creature. It's still a land. "
            "It can't be blocked this turn."
        ),
        "produced_mana": ["B", "U"],
        "set": "eos",
    }
    assert _try_build_manland(card, card["oracle_text"], (), ()) is None


def test_skips_when_color_pair_mismatches_animate_line():
    """Defensive: the colors in the dual mana ability must match the
    color words on the animate line."""
    card = {
        "name": "Mismatched Manland",
        "type_line": "Land",
        "oracle_text": (
            "This land enters tapped.\n"
            "{T}: Add {W} or {U}.\n"
            "{3}{W}{U}: Until end of turn, this land becomes a 4/4 "
            "red and green Elemental creature with flying. It's "
            "still a land."
        ),
        "produced_mana": ["U", "W"],
        "set": "eos",
    }
    assert _try_build_manland(card, card["oracle_text"], (), ()) is None


def test_skips_when_supertype_present():
    """A Legendary manland (e.g. a hypothetical Legendary version)
    must skip the simple-manland path — supertypes belong on the
    dedicated bespoke handler."""
    card = {
        "name": "Hypothetical Legendary Manland",
        "type_line": "Legendary Land",
        "oracle_text": (
            "This land enters tapped.\n"
            "{T}: Add {W} or {U}.\n"
            "{3}{W}{U}: Until end of turn, this land becomes a 4/4 "
            "white and blue Elemental creature with flying. It's "
            "still a land."
        ),
        "produced_mana": ["U", "W"],
        "set": "eos",
    }
    assert _try_build_manland(
        card, card["oracle_text"], ("Legendary",), (),
    ) is None


def test_skips_when_subtype_present():
    """A subtyped manland (e.g. a hypothetical Cave or Desert manland)
    skips the simple-manland path."""
    card = {
        "name": "Hypothetical Cave Manland",
        "type_line": "Land — Cave",
        "oracle_text": (
            "This land enters tapped.\n"
            "{T}: Add {W} or {U}.\n"
            "{3}{W}{U}: Until end of turn, this land becomes a 4/4 "
            "white and blue Elemental creature with flying. It's "
            "still a land."
        ),
        "produced_mana": ["U", "W"],
        "set": "eos",
    }
    assert _try_build_manland(
        card, card["oracle_text"], (), ("Cave",),
    ) is None


def test_skips_when_first_line_is_not_enters_tapped():
    """All EoE simple manlands enter tapped; an untapped variant
    falls outside this shape."""
    card = {
        "name": "Untapped Manland",
        "type_line": "Land",
        "oracle_text": (
            "{T}: Add {W} or {U}.\n"
            "{3}{W}{U}: Until end of turn, this land becomes a 4/4 "
            "white and blue Elemental creature with flying. It's "
            "still a land."
        ),
        "produced_mana": ["U", "W"],
        "set": "eos",
    }
    assert _try_build_manland(card, card["oracle_text"], (), ()) is None


def test_parse_manland_keywords_handles_single_keyword():
    assert _parse_manland_keywords("flying") == frozenset({"flying"})


def test_parse_manland_keywords_handles_two_keywords_with_and():
    assert _parse_manland_keywords("flying and vigilance") == frozenset(
        {"flying", "vigilance"}
    )


def test_parse_manland_keywords_handles_compound_keyword_phrase():
    """``double strike`` is a single keyword, not two."""
    assert _parse_manland_keywords("double strike") == frozenset(
        {"double strike"}
    )


def test_parse_manland_keywords_rejects_unknown_keyword():
    """If any token isn't a known surface keyword, return None so
    the parser falls through rather than claiming a card whose grant
    semantics aren't yet supported."""
    assert _parse_manland_keywords("flying and unicorn-mode") is None


def test_parse_manland_keywords_rejects_empty():
    assert _parse_manland_keywords("") is None
    assert _parse_manland_keywords("   ") is None


def test_simple_manland_builder_returns_make_utility_land_shape():
    """White-box: the builder produces a CardPrinting equal to the
    one ``make_utility_land`` would produce with the same parameters.
    Asserts no extra fields creep in over time."""
    card = _shambling_vent_card()
    parsed = _build_land_printing(card)
    expected = make_utility_land(
        "Shambling Vent",
        produces=frozenset({"W", "B"}),
        enters_tapped=True,
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{1}{W}{B}"),
                    mana_str="{1}{W}{B}",
                ),
                effect=BecomeLandCreatureUEOT(
                    power=2,
                    toughness=3,
                    granted_keywords=frozenset({"lifelink"}),
                ),
            ),
        ),
    )
    assert parsed == expected
