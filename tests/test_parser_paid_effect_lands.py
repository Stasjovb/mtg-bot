"""Parser support for generic-paid single-effect utility lands.

Plain ``Land`` cards (no supertypes, no subtypes) whose oracle text is
the strict two-line shape:

    {T}: Add {C}.
    <MANA-COST>, {T}: <BODY>.

where ``<MANA-COST>`` is a generic-mana cost (``{1}``, ``{2}``, …)
and ``<BODY>`` is on ``_PAID_EFFECT_BODIES``. Each body maps to a
single bespoke ``Effect`` instance; the static side wraps that effect
in one ``ActivatedAbility`` whose cost carries the parsed mana plus
``tap_self=True``.

Currently claims Deserted Temple, Mystifying Maze, Terrain Generator.
"""

from __future__ import annotations

from mtg_bot.cards.parser.land_builder import (
    _build_land_printing,
    _try_build_paid_effect_utility_land,
)
from mtg_bot.cards.stellar_sights import STELLAR_SIGHTS_LANDS


def test_deserted_temple_matches_static():
    card = {
        "name": "Deserted Temple",
        "type_line": "Land",
        "oracle_text": (
            "{T}: Add {C}.\n"
            "{1}, {T}: Untap target land."
        ),
        "produced_mana": ["C"],
        "set": "eos",
    }
    parsed = _build_land_printing(card)
    assert parsed is not None
    assert parsed == STELLAR_SIGHTS_LANDS["Deserted Temple"]


def test_mystifying_maze_matches_static():
    card = {
        "name": "Mystifying Maze",
        "type_line": "Land",
        "oracle_text": (
            "{T}: Add {C}.\n"
            "{4}, {T}: Exile target attacking creature an opponent "
            "controls. At the beginning of the next end step, return "
            "it to the battlefield tapped under its owner's control."
        ),
        "produced_mana": ["C"],
        "set": "eos",
    }
    parsed = _build_land_printing(card)
    assert parsed is not None
    assert parsed == STELLAR_SIGHTS_LANDS["Mystifying Maze"]


def test_terrain_generator_matches_static():
    card = {
        "name": "Terrain Generator",
        "type_line": "Land",
        "oracle_text": (
            "{T}: Add {C}.\n"
            "{2}, {T}: You may put a basic land card from your hand "
            "onto the battlefield tapped."
        ),
        "produced_mana": ["C"],
        "set": "eos",
    }
    parsed = _build_land_printing(card)
    assert parsed is not None
    assert parsed == STELLAR_SIGHTS_LANDS["Terrain Generator"]


def test_skips_unknown_body():
    """A body outside the whitelist must NOT be claimed — parity would
    fail because the parser would have no effect to bind."""
    card = {
        "name": "Hypothetical Variant",
        "type_line": "Land",
        "oracle_text": (
            "{T}: Add {C}.\n"
            "{2}, {T}: Untap each artifact you control."
        ),
        "produced_mana": ["C"],
        "set": "eos",
    }
    assert _try_build_paid_effect_utility_land(
        card, card["oracle_text"], (), (),
    ) is None


def test_skips_when_first_line_is_not_tap_for_c():
    """Two-line shapes whose first line isn't ``{T}: Add {C}.`` fall
    through — those need a different recognizer."""
    card = {
        "name": "Hypothetical Variant",
        "type_line": "Land",
        "oracle_text": (
            "{T}: Add one mana of any color.\n"
            "{1}, {T}: Untap target land."
        ),
        "produced_mana": ["W", "U", "B", "R", "G"],
        "set": "eos",
    }
    assert _try_build_paid_effect_utility_land(
        card, card["oracle_text"], (), (),
    ) is None


def test_skips_supertyped_land():
    """Legendary or other-supertyped utility lands fall outside this
    shape — they need the bespoke per-card path."""
    card = {
        "name": "Hypothetical Legendary",
        "type_line": "Legendary Land",
        "oracle_text": (
            "{T}: Add {C}.\n"
            "{1}, {T}: Untap target land."
        ),
        "produced_mana": ["C"],
        "set": "eos",
    }
    assert _try_build_paid_effect_utility_land(
        card, card["oracle_text"], ("Legendary",), (),
    ) is None


def test_skips_subtyped_land():
    """A subtyped land (e.g. Cave, Desert) with this shape needs the
    bespoke per-subtype recognizer; the generic builder rejects it."""
    card = {
        "name": "Hypothetical Cave",
        "type_line": "Land — Cave",
        "oracle_text": (
            "{T}: Add {C}.\n"
            "{1}, {T}: Untap target land."
        ),
        "produced_mana": ["C"],
        "set": "eos",
    }
    assert _try_build_paid_effect_utility_land(
        card, card["oracle_text"], (), ("Cave",),
    ) is None


def test_skips_three_line_shape():
    """The recognizer is for the strict two-line shape. A third oracle
    line falls through — anything richer needs the bespoke path."""
    card = {
        "name": "Hypothetical Extra Line",
        "type_line": "Land",
        "oracle_text": (
            "{T}: Add {C}.\n"
            "{1}, {T}: Untap target land.\n"
            "Indestructible"
        ),
        "produced_mana": ["C"],
        "set": "eos",
    }
    assert _try_build_paid_effect_utility_land(
        card, card["oracle_text"], (), (),
    ) is None


def test_skips_colored_cost():
    """Activation costs that include colored or hybrid pips fall
    outside the all-generic cost capture and skip — extending support
    to colored costs is a regex change plus a per-cost-shape factory."""
    card = {
        "name": "Hypothetical Colored",
        "type_line": "Land",
        "oracle_text": (
            "{T}: Add {C}.\n"
            "{U}, {T}: Untap target land."
        ),
        "produced_mana": ["C"],
        "set": "eos",
    }
    assert _try_build_paid_effect_utility_land(
        card, card["oracle_text"], (), (),
    ) is None


def test_skips_when_tap_only_no_mana():
    """A bare ``{T}: <BODY>.`` activation (no mana cost) doesn't match
    this shape — the recognizer requires at least one generic-mana
    pip ahead of the tap glyph."""
    card = {
        "name": "Hypothetical No-Cost",
        "type_line": "Land",
        "oracle_text": (
            "{T}: Add {C}.\n"
            "{T}: Untap target land."
        ),
        "produced_mana": ["C"],
        "set": "eos",
    }
    assert _try_build_paid_effect_utility_land(
        card, card["oracle_text"], (), (),
    ) is None
