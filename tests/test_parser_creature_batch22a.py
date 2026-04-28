"""Parity tests for creature-batch22a bespoke dispatch additions.

Each test asserts that the oracle parser produces a ``CardPrinting``
identical to the static registry for one of the twelve new creatures
claimed via the ``_BESPOKE_CREATURES`` name-keyed dispatch table in
``creature_builder.py``.

Covered creatures:
  1. Starfield Shepherd — flying, warp {1}{W}, ETB modal tutor
  2. Astelli Reclaimer — flying, warp {2}{W}, ETB AstelliReclaimerETBEffect
  3. Exalted Sunborn — flying, lifelink, warp {1}{W}, is_token_doubler
  4. Territorial Bruntar — reach, landfall TerritorialBruntarLandfallEffect
  5. All-Fates Stalker — warp {1}{W}, ETB ExileTargetCreatureUntilSourceLeaves
  6. Anticausal Vestige — warp {4}, leaves-battlefield AnticausalVestigeLeavesEffect
  7. Fungal Colossus — CostReduction per_differently_named_land
  8. Perigee Beckoner — warp {1}{B}, ETB PumpTargetCreatureUntilEOT + granted trigger
  9. Honored Knight-Captain — ETB Human Soldier token + activated Equipment tutor
 10. Starfield Vocalist — warp {1}{U}, extra_etb_trigger=1
 11. Elegy Acolyte — lifelink, void end-step Robot token
 12. Pulsar Squadron Ace — ETB LookAtTopNRevealOrCounter(5, spacecraft)
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


def test_starfield_shepherd_claimed_by_parser():
    assert "Starfield Shepherd" in _PARSER_PRINTINGS


def test_starfield_shepherd_parity():
    assert _parser("Starfield Shepherd") == _static("Starfield Shepherd")


def test_astelli_reclaimer_claimed_by_parser():
    assert "Astelli Reclaimer" in _PARSER_PRINTINGS


def test_astelli_reclaimer_parity():
    assert _parser("Astelli Reclaimer") == _static("Astelli Reclaimer")


def test_exalted_sunborn_claimed_by_parser():
    assert "Exalted Sunborn" in _PARSER_PRINTINGS


def test_exalted_sunborn_parity():
    assert _parser("Exalted Sunborn") == _static("Exalted Sunborn")


def test_territorial_bruntar_claimed_by_parser():
    assert "Territorial Bruntar" in _PARSER_PRINTINGS


def test_territorial_bruntar_parity():
    assert _parser("Territorial Bruntar") == _static("Territorial Bruntar")


def test_all_fates_stalker_claimed_by_parser():
    assert "All-Fates Stalker" in _PARSER_PRINTINGS


def test_all_fates_stalker_parity():
    assert _parser("All-Fates Stalker") == _static("All-Fates Stalker")


def test_anticausal_vestige_claimed_by_parser():
    assert "Anticausal Vestige" in _PARSER_PRINTINGS


def test_anticausal_vestige_parity():
    assert _parser("Anticausal Vestige") == _static("Anticausal Vestige")


def test_fungal_colossus_claimed_by_parser():
    assert "Fungal Colossus" in _PARSER_PRINTINGS


def test_fungal_colossus_parity():
    assert _parser("Fungal Colossus") == _static("Fungal Colossus")


def test_perigee_beckoner_claimed_by_parser():
    assert "Perigee Beckoner" in _PARSER_PRINTINGS


def test_perigee_beckoner_parity():
    assert _parser("Perigee Beckoner") == _static("Perigee Beckoner")


def test_honored_knight_captain_claimed_by_parser():
    assert "Honored Knight-Captain" in _PARSER_PRINTINGS


def test_honored_knight_captain_parity():
    assert _parser("Honored Knight-Captain") == _static("Honored Knight-Captain")


def test_starfield_vocalist_claimed_by_parser():
    assert "Starfield Vocalist" in _PARSER_PRINTINGS


def test_starfield_vocalist_parity():
    assert _parser("Starfield Vocalist") == _static("Starfield Vocalist")


def test_elegy_acolyte_claimed_by_parser():
    assert "Elegy Acolyte" in _PARSER_PRINTINGS


def test_elegy_acolyte_parity():
    assert _parser("Elegy Acolyte") == _static("Elegy Acolyte")


def test_pulsar_squadron_ace_claimed_by_parser():
    assert "Pulsar Squadron Ace" in _PARSER_PRINTINGS


def test_pulsar_squadron_ace_parity():
    assert _parser("Pulsar Squadron Ace") == _static("Pulsar Squadron Ace")
