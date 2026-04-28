"""Parity tests for spacecraft-batch22 bespoke dispatch entries.

Each test verifies that ``OracleParserCardSource`` returns a
``CardPrinting`` equal to the one in the static registry for a
spacecraft claimed via the ``_BESPOKE_SPACECRAFT`` name-keyed dispatch
table (batch 22 additions).
"""

from __future__ import annotations

from mtg_bot.cards.parser_source import OracleParserCardSource
from mtg_bot.cards.source import StaticCardSource

_PARSER_PRINTINGS = OracleParserCardSource().get_printings()
_STATIC_PRINTINGS = StaticCardSource().get_printings()


def test_debris_field_crusher_parity():
    name = "Debris Field Crusher"
    assert name in _PARSER_PRINTINGS, (
        f"parser did not claim {name!r}"
    )
    assert _PARSER_PRINTINGS[name] == _STATIC_PRINTINGS[name]


def test_fell_gravship_parity():
    name = "Fell Gravship"
    assert name in _PARSER_PRINTINGS, (
        f"parser did not claim {name!r}"
    )
    assert _PARSER_PRINTINGS[name] == _STATIC_PRINTINGS[name]


def test_larval_scoutlander_parity():
    name = "Larval Scoutlander"
    assert name in _PARSER_PRINTINGS, (
        f"parser did not claim {name!r}"
    )
    assert _PARSER_PRINTINGS[name] == _STATIC_PRINTINGS[name]


def test_rescue_skiff_parity():
    name = "Rescue Skiff"
    assert name in _PARSER_PRINTINGS, (
        f"parser did not claim {name!r}"
    )
    assert _PARSER_PRINTINGS[name] == _STATIC_PRINTINGS[name]


def test_sledge_class_seedship_parity():
    name = "Sledge-Class Seedship"
    assert name in _PARSER_PRINTINGS, (
        f"parser did not claim {name!r}"
    )
    assert _PARSER_PRINTINGS[name] == _STATIC_PRINTINGS[name]


def test_specimen_freighter_parity():
    name = "Specimen Freighter"
    assert name in _PARSER_PRINTINGS, (
        f"parser did not claim {name!r}"
    )
    assert _PARSER_PRINTINGS[name] == _STATIC_PRINTINGS[name]


def test_extinguisher_battleship_parity():
    name = "Extinguisher Battleship"
    assert name in _PARSER_PRINTINGS, (
        f"parser did not claim {name!r}"
    )
    assert _PARSER_PRINTINGS[name] == _STATIC_PRINTINGS[name]


def test_entropic_battlecruiser_parity():
    name = "Entropic Battlecruiser"
    assert name in _PARSER_PRINTINGS, (
        f"parser did not claim {name!r}"
    )
    assert _PARSER_PRINTINGS[name] == _STATIC_PRINTINGS[name]


def test_synthesizer_labship_parity():
    name = "Synthesizer Labship"
    assert name in _PARSER_PRINTINGS, (
        f"parser did not claim {name!r}"
    )
    assert _PARSER_PRINTINGS[name] == _STATIC_PRINTINGS[name]


def test_lumen_class_frigate_parity():
    name = "Lumen-Class Frigate"
    assert name in _PARSER_PRINTINGS, (
        f"parser did not claim {name!r}"
    )
    assert _PARSER_PRINTINGS[name] == _STATIC_PRINTINGS[name]


def test_infinite_guideline_station_parity():
    name = "Infinite Guideline Station"
    assert name in _PARSER_PRINTINGS, (
        f"parser did not claim {name!r}"
    )
    assert _PARSER_PRINTINGS[name] == _STATIC_PRINTINGS[name]


def test_dawnsire_sunstar_dreadnought_parity():
    name = "Dawnsire, Sunstar Dreadnought"
    assert name in _PARSER_PRINTINGS, (
        f"parser did not claim {name!r}"
    )
    assert _PARSER_PRINTINGS[name] == _STATIC_PRINTINGS[name]


def test_the_seriema_parity():
    name = "The Seriema"
    assert name in _PARSER_PRINTINGS, (
        f"parser did not claim {name!r}"
    )
    assert _PARSER_PRINTINGS[name] == _STATIC_PRINTINGS[name]


def test_the_eternity_elevator_parity():
    name = "The Eternity Elevator"
    assert name in _PARSER_PRINTINGS, (
        f"parser did not claim {name!r}"
    )
    assert _PARSER_PRINTINGS[name] == _STATIC_PRINTINGS[name]
