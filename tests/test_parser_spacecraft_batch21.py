"""Parity tests for spacecraft-batch21 bespoke dispatch entries.

Each test verifies that ``OracleParserCardSource`` returns a
``CardPrinting`` equal to the one in the static registry for a
spacecraft whose ETB effect is claimed via the ``_BESPOKE_SPACECRAFT``
name-keyed dispatch table rather than the general Station grammar.
"""

from __future__ import annotations

from mtg_bot.cards.parser_source import OracleParserCardSource
from mtg_bot.cards.source import StaticCardSource

_PARSER_PRINTINGS = OracleParserCardSource().get_printings()
_STATIC_PRINTINGS = StaticCardSource().get_printings()


def test_atmospheric_greenhouse_parity():
    name = "Atmospheric Greenhouse"
    assert name in _PARSER_PRINTINGS, (
        f"parser did not claim {name!r}"
    )
    assert _PARSER_PRINTINGS[name] == _STATIC_PRINTINGS[name]


def test_pinnacle_kill_ship_parity():
    name = "Pinnacle Kill-Ship"
    assert name in _PARSER_PRINTINGS, (
        f"parser did not claim {name!r}"
    )
    assert _PARSER_PRINTINGS[name] == _STATIC_PRINTINGS[name]


def test_susurian_dirgecraft_parity():
    name = "Susurian Dirgecraft"
    assert name in _PARSER_PRINTINGS, (
        f"parser did not claim {name!r}"
    )
    assert _PARSER_PRINTINGS[name] == _STATIC_PRINTINGS[name]


def test_uthros_scanship_parity():
    name = "Uthros Scanship"
    assert name in _PARSER_PRINTINGS, (
        f"parser did not claim {name!r}"
    )
    assert _PARSER_PRINTINGS[name] == _STATIC_PRINTINGS[name]


def test_warmaker_gunship_parity():
    name = "Warmaker Gunship"
    assert name in _PARSER_PRINTINGS, (
        f"parser did not claim {name!r}"
    )
    assert _PARSER_PRINTINGS[name] == _STATIC_PRINTINGS[name]
