"""Parity tests for the enchantment_builder whole-card dispatch.

Each test asserts that ``OracleParserCardSource`` builds the same
``CardPrinting`` as the static registry for one of the 15 EoE
enchantments claimed by ``enchantment_builder``.
"""

from __future__ import annotations

import pytest

from mtg_bot.cards.parser_source import OracleParserCardSource
from mtg_bot.cards.source import StaticCardSource

_PARSER = OracleParserCardSource()
_PARSER_PRINTINGS = _PARSER.get_printings()
_STATIC_PRINTINGS = StaticCardSource().get_printings()


# ---------------------------------------------------------------------------
# Helper to assert parity
# ---------------------------------------------------------------------------

def _assert_parity(name: str) -> None:
    assert name in _PARSER_PRINTINGS, (
        f"parser did not claim {name!r}"
    )
    assert name in _STATIC_PRINTINGS, (
        f"static registry has no entry for {name!r}"
    )
    assert _PARSER_PRINTINGS[name] == _STATIC_PRINTINGS[name], (
        f"parser printing for {name!r} does not match static registry"
    )


# ---------------------------------------------------------------------------
# Non-Aura enchantments
# ---------------------------------------------------------------------------

def test_banishing_light_parity():
    _assert_parity("Banishing Light")


def test_seam_rip_parity():
    _assert_parity("Seam Rip")


def test_loading_zone_parity():
    _assert_parity("Loading Zone")


def test_weftwalking_parity():
    _assert_parity("Weftwalking")


def test_sothera_the_supervoid_parity():
    _assert_parity("Sothera, the Supervoid")


def test_terrasymbiosis_parity():
    _assert_parity("Terrasymbiosis")


def test_weapons_manufacturing_parity():
    _assert_parity("Weapons Manufacturing")


def test_bioengineered_future_parity():
    _assert_parity("Bioengineered Future")


def test_eusocial_engineering_parity():
    _assert_parity("Eusocial Engineering")


# ---------------------------------------------------------------------------
# Aura enchantments
# ---------------------------------------------------------------------------

def test_moonlit_meditation_parity():
    _assert_parity("Moonlit Meditation")


def test_tractor_beam_parity():
    _assert_parity("Tractor Beam")


def test_chorale_of_the_void_parity():
    _assert_parity("Chorale of the Void")


def test_cryoshatter_parity():
    _assert_parity("Cryoshatter")


def test_meltstriders_resolve_parity():
    _assert_parity("Meltstrider's Resolve")


def test_hardlight_containment_parity():
    _assert_parity("Hardlight Containment")


# ---------------------------------------------------------------------------
# Gate check: type-line guard does not claim non-enchantments
# ---------------------------------------------------------------------------

def test_enchantment_builder_skips_non_enchantment():
    from mtg_bot.cards.parser.enchantment_builder import (
        _build_enchantment_printing,
    )
    card = {
        "name": "Banishing Light",
        "mana_cost": "{2}{W}",
        "type_line": "Creature — Human",
        "oracle_text": "When this enchantment enters, ...",
    }
    assert _build_enchantment_printing(card) is None


def test_enchantment_builder_skips_enchantment_creature():
    from mtg_bot.cards.parser.enchantment_builder import (
        _build_enchantment_printing,
    )
    card = {
        "name": "Banishing Light",
        "mana_cost": "{2}{W}",
        "type_line": "Enchantment Creature — Human",
        "oracle_text": "",
    }
    assert _build_enchantment_printing(card) is None


def test_enchantment_builder_skips_enchantment_artifact():
    from mtg_bot.cards.parser.enchantment_builder import (
        _build_enchantment_printing,
    )
    card = {
        "name": "Banishing Light",
        "mana_cost": "{2}{W}",
        "type_line": "Artifact Enchantment",
        "oracle_text": "",
    }
    assert _build_enchantment_printing(card) is None


def test_enchantment_builder_skips_unknown_name():
    from mtg_bot.cards.parser.enchantment_builder import (
        _build_enchantment_printing,
    )
    card = {
        "name": "Some Unknown Enchantment",
        "mana_cost": "{2}{W}",
        "type_line": "Enchantment",
        "oracle_text": "",
    }
    assert _build_enchantment_printing(card) is None


# ---------------------------------------------------------------------------
# End-to-end: parser source claims all 15 via data walk
# ---------------------------------------------------------------------------

_EXPECTED_ENCHANTMENT_NAMES = [
    "Banishing Light",
    "Seam Rip",
    "Loading Zone",
    "Weftwalking",
    "Sothera, the Supervoid",
    "Terrasymbiosis",
    "Weapons Manufacturing",
    "Bioengineered Future",
    "Eusocial Engineering",
    "Moonlit Meditation",
    "Tractor Beam",
    "Chorale of the Void",
    "Cryoshatter",
    "Meltstrider's Resolve",
    "Hardlight Containment",
]


@pytest.mark.parametrize("name", _EXPECTED_ENCHANTMENT_NAMES)
def test_source_claims_enchantment(name: str):
    assert name in _PARSER.claimed_names, (
        f"OracleParserCardSource did not claim {name!r}"
    )
