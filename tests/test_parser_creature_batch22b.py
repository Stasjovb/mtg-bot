"""Parity tests for creature-batch22b bespoke dispatch additions.

Each test asserts that the oracle parser produces a ``CardPrinting``
identical to the static registry for one of the twelve new creatures
claimed via the ``_BESPOKE_CREATURES`` name-keyed dispatch table in
``creature_builder.py``.

Covered creatures:
  1.  Lightstall Inquisitor — vigilance only (simplified)
  2.  Biomechan Engineer — ETB Lander token + activated {8}: draw2 + Robot
  3.  Blade of the Swarm — warp {1}{B}, ETB modal PutPlusOneCounterOnSelf / OwnerPutsTargetWarpedExileCardOnBottomOfLibrary
  4.  Seedship Broodtender — ETB SelfMill(3) + activated sorcery reanimate
  5.  Genemorph Imago — flying only (simplified)
  6.  Broodguard Elite — Insect Knight, warp {X}{G}, enters_with_counters_from_x, leaves trigger
  7.  Icetill Explorer — grants_additional_land_per_turn + graveyard lands + landfall mill
  8.  Possibility Technician — warp {R}, Kavu Artificer, two ETB exile triggers
  9.  Terrapact Intimidator — ETB TerrapactIntimidatorETBEffect
 10.  Famished Worldsire — Leviathan, ward {3}, devour land 3, ETB FamishedWorldsireETBEffect
 11.  Ouroboroid — beginning-of-combat pump equal to power
 12.  Quantum Riddler — flying, warp {1}{U}, replaces_draw_with_extra, ETB draw
"""

from __future__ import annotations

from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.cards.source import StaticCardSource

_PARSER = OracleParserCardSource()
_PARSER_PRINTINGS = _PARSER.get_printings()
_STATIC_PRINTINGS = StaticCardSource().get_printings()


def _parser(name: str):
    return _PARSER_PRINTINGS[name]


def _static(name: str):
    return _STATIC_PRINTINGS[name]


def test_lightstall_inquisitor_claimed_by_parser():
    assert "Lightstall Inquisitor" in _PARSER_PRINTINGS


def test_lightstall_inquisitor_parity():
    assert _parser("Lightstall Inquisitor") == _static("Lightstall Inquisitor")


def test_biomechan_engineer_claimed_by_parser():
    assert "Biomechan Engineer" in _PARSER_PRINTINGS


def test_biomechan_engineer_parity():
    assert _parser("Biomechan Engineer") == _static("Biomechan Engineer")


def test_blade_of_the_swarm_claimed_by_parser():
    assert "Blade of the Swarm" in _PARSER_PRINTINGS


def test_blade_of_the_swarm_parity():
    assert _parser("Blade of the Swarm") == _static("Blade of the Swarm")


def test_seedship_broodtender_claimed_by_parser():
    assert "Seedship Broodtender" in _PARSER_PRINTINGS


def test_seedship_broodtender_parity():
    assert _parser("Seedship Broodtender") == _static("Seedship Broodtender")


def test_genemorph_imago_claimed_by_parser():
    assert "Genemorph Imago" in _PARSER_PRINTINGS


def test_genemorph_imago_parity():
    assert _parser("Genemorph Imago") == _static("Genemorph Imago")


def test_broodguard_elite_claimed_by_parser():
    assert "Broodguard Elite" in _PARSER_PRINTINGS


def test_broodguard_elite_parity():
    assert _parser("Broodguard Elite") == _static("Broodguard Elite")


def test_icetill_explorer_claimed_by_parser():
    assert "Icetill Explorer" in _PARSER_PRINTINGS


def test_icetill_explorer_parity():
    assert _parser("Icetill Explorer") == _static("Icetill Explorer")


def test_possibility_technician_claimed_by_parser():
    assert "Possibility Technician" in _PARSER_PRINTINGS


def test_possibility_technician_parity():
    assert _parser("Possibility Technician") == _static("Possibility Technician")


def test_terrapact_intimidator_claimed_by_parser():
    assert "Terrapact Intimidator" in _PARSER_PRINTINGS


def test_terrapact_intimidator_parity():
    assert _parser("Terrapact Intimidator") == _static("Terrapact Intimidator")


def test_famished_worldsire_claimed_by_parser():
    assert "Famished Worldsire" in _PARSER_PRINTINGS


def test_famished_worldsire_parity():
    assert _parser("Famished Worldsire") == _static("Famished Worldsire")


def test_ouroboroid_claimed_by_parser():
    assert "Ouroboroid" in _PARSER_PRINTINGS


def test_ouroboroid_parity():
    assert _parser("Ouroboroid") == _static("Ouroboroid")


def test_quantum_riddler_claimed_by_parser():
    assert "Quantum Riddler" in _PARSER_PRINTINGS


def test_quantum_riddler_parity():
    assert _parser("Quantum Riddler") == _static("Quantum Riddler")
