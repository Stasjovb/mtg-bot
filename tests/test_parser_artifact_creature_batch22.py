"""Parity tests for artifact-creature-batch22 bespoke dispatch additions.

Each test asserts that the oracle parser produces a ``CardPrinting``
identical to the static registry for one of the 13 non-legendary
Artifact Creatures claimed via ``_BESPOKE_ARTIFACT_CREATURES`` in
``creature_builder.py``.

Covered cards:
  1. Emissary Escort — dynamic P/T formula (emissary_escort)
  2. Gene Pollinator — vanilla Artifact Creature 1/2 (simplified)
  3. Interceptor Mechan — flying + ETB return + void end-step counter
  4. Kavaron Harrier — attack trigger (KavaronHarrierAttackEffect)
  5. Mechan Shieldmate — defender + attack_bypass_if_artifact_entered_this_turn
  6. Monoist Circuit-Feeder — flying + ETB (MonoistCircuitFeederETBEffect)
  7. Pinnacle Emissary — artifact-cast trigger + Warp {U}{R}
  8. Roving Actuator — void ETB (RovingActuatorETBEffect) + Warp {1}{R}
  9. Rust Harvester — menace only (simplified vanilla)
 10. Selfcraft Mechan — ETB (SelfcraftMechanETBEffect)
 11. Survey Mechan — flying only (simplified vanilla)
 12. Tapestry Warden — vigilance only (simplified vanilla)
 13. Virulent Silencer — observer trigger + PutPoisonCountersOnTargetPlayer
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


def test_emissary_escort_claimed_by_parser():
    assert "Emissary Escort" in _PARSER_PRINTINGS


def test_emissary_escort_parity():
    assert _parser("Emissary Escort") == _static("Emissary Escort")


def test_gene_pollinator_claimed_by_parser():
    assert "Gene Pollinator" in _PARSER_PRINTINGS


def test_gene_pollinator_parity():
    assert _parser("Gene Pollinator") == _static("Gene Pollinator")


def test_interceptor_mechan_claimed_by_parser():
    assert "Interceptor Mechan" in _PARSER_PRINTINGS


def test_interceptor_mechan_parity():
    assert _parser("Interceptor Mechan") == _static("Interceptor Mechan")


def test_kavaron_harrier_claimed_by_parser():
    assert "Kavaron Harrier" in _PARSER_PRINTINGS


def test_kavaron_harrier_parity():
    assert _parser("Kavaron Harrier") == _static("Kavaron Harrier")


def test_mechan_shieldmate_claimed_by_parser():
    assert "Mechan Shieldmate" in _PARSER_PRINTINGS


def test_mechan_shieldmate_parity():
    assert _parser("Mechan Shieldmate") == _static("Mechan Shieldmate")


def test_monoist_circuit_feeder_claimed_by_parser():
    assert "Monoist Circuit-Feeder" in _PARSER_PRINTINGS


def test_monoist_circuit_feeder_parity():
    assert _parser("Monoist Circuit-Feeder") == _static("Monoist Circuit-Feeder")


def test_pinnacle_emissary_claimed_by_parser():
    assert "Pinnacle Emissary" in _PARSER_PRINTINGS


def test_pinnacle_emissary_parity():
    assert _parser("Pinnacle Emissary") == _static("Pinnacle Emissary")


def test_roving_actuator_claimed_by_parser():
    assert "Roving Actuator" in _PARSER_PRINTINGS


def test_roving_actuator_parity():
    assert _parser("Roving Actuator") == _static("Roving Actuator")


def test_rust_harvester_claimed_by_parser():
    assert "Rust Harvester" in _PARSER_PRINTINGS


def test_rust_harvester_parity():
    assert _parser("Rust Harvester") == _static("Rust Harvester")


def test_selfcraft_mechan_claimed_by_parser():
    assert "Selfcraft Mechan" in _PARSER_PRINTINGS


def test_selfcraft_mechan_parity():
    assert _parser("Selfcraft Mechan") == _static("Selfcraft Mechan")


def test_survey_mechan_claimed_by_parser():
    assert "Survey Mechan" in _PARSER_PRINTINGS


def test_survey_mechan_parity():
    assert _parser("Survey Mechan") == _static("Survey Mechan")


def test_tapestry_warden_claimed_by_parser():
    assert "Tapestry Warden" in _PARSER_PRINTINGS


def test_tapestry_warden_parity():
    assert _parser("Tapestry Warden") == _static("Tapestry Warden")


def test_virulent_silencer_claimed_by_parser():
    assert "Virulent Silencer" in _PARSER_PRINTINGS


def test_virulent_silencer_parity():
    assert _parser("Virulent Silencer") == _static("Virulent Silencer")
