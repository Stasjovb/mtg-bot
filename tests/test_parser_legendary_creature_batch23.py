"""Parity tests for legendary-creature-batch23 bespoke dispatch additions.

Each test asserts that the oracle parser produces a ``CardPrinting``
identical to the static registry for one of the eleven legendary creatures
claimed via the ``_BESPOKE_LEGENDARY_CREATURES`` name-keyed dispatch table
in ``creature_builder.py``.

Covered cards:
  1.  Dyadrine, Synthesis Amalgam — Legendary Artifact Creature — Construct
  2.  Sami, Wildcat Captain — Legendary Creature — Human Artificer Rogue
  3.  Alpharael, Dreaming Acolyte — Legendary Creature — Human Cleric
  4.  Alpharael, Stonechosen — Legendary Creature — Human Cleric
  5.  Syr Vondam, Sunstar Exemplar — Legendary Creature — Human Knight
  6.  Haliya, Ascendant Cadet — Legendary Creature — Human Soldier
  7.  Haliya, Guided by Light — Legendary Creature — Human Soldier
  8.  Mm'menon, the Right Hand — Legendary Creature — Jellyfish Advisor
  9.  Tannuk, Memorial Ensign — Legendary Creature — Kavu Pilot
  10. Tannuk, Steadfast Second — Legendary Creature — Kavu Pilot
  11. Ragost, Deft Gastronaut — Legendary Creature — Lobster Citizen
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


# ── Dyadrine, Synthesis Amalgam ───────────────────────────────────────────────

def test_dyadrine_synthesis_amalgam_claimed_by_parser():
    assert "Dyadrine, Synthesis Amalgam" in _PARSER_PRINTINGS


def test_dyadrine_synthesis_amalgam_parity():
    assert _parser("Dyadrine, Synthesis Amalgam") == _static("Dyadrine, Synthesis Amalgam")


# ── Sami, Wildcat Captain ─────────────────────────────────────────────────────

def test_sami_wildcat_captain_claimed_by_parser():
    assert "Sami, Wildcat Captain" in _PARSER_PRINTINGS


def test_sami_wildcat_captain_parity():
    assert _parser("Sami, Wildcat Captain") == _static("Sami, Wildcat Captain")


# ── Alpharael, Dreaming Acolyte ───────────────────────────────────────────────

def test_alpharael_dreaming_acolyte_claimed_by_parser():
    assert "Alpharael, Dreaming Acolyte" in _PARSER_PRINTINGS


def test_alpharael_dreaming_acolyte_parity():
    assert _parser("Alpharael, Dreaming Acolyte") == _static("Alpharael, Dreaming Acolyte")


# ── Alpharael, Stonechosen ────────────────────────────────────────────────────

def test_alpharael_stonechosen_claimed_by_parser():
    assert "Alpharael, Stonechosen" in _PARSER_PRINTINGS


def test_alpharael_stonechosen_parity():
    assert _parser("Alpharael, Stonechosen") == _static("Alpharael, Stonechosen")


# ── Syr Vondam, Sunstar Exemplar ──────────────────────────────────────────────

def test_syr_vondam_sunstar_exemplar_claimed_by_parser():
    assert "Syr Vondam, Sunstar Exemplar" in _PARSER_PRINTINGS


def test_syr_vondam_sunstar_exemplar_parity():
    assert _parser("Syr Vondam, Sunstar Exemplar") == _static("Syr Vondam, Sunstar Exemplar")


# ── Haliya, Ascendant Cadet ───────────────────────────────────────────────────

def test_haliya_ascendant_cadet_claimed_by_parser():
    assert "Haliya, Ascendant Cadet" in _PARSER_PRINTINGS


def test_haliya_ascendant_cadet_parity():
    assert _parser("Haliya, Ascendant Cadet") == _static("Haliya, Ascendant Cadet")


# ── Haliya, Guided by Light ───────────────────────────────────────────────────

def test_haliya_guided_by_light_claimed_by_parser():
    assert "Haliya, Guided by Light" in _PARSER_PRINTINGS


def test_haliya_guided_by_light_parity():
    assert _parser("Haliya, Guided by Light") == _static("Haliya, Guided by Light")


# ── Mm'menon, the Right Hand ──────────────────────────────────────────────────

def test_mmenon_the_right_hand_claimed_by_parser():
    assert "Mm'menon, the Right Hand" in _PARSER_PRINTINGS


def test_mmenon_the_right_hand_parity():
    assert _parser("Mm'menon, the Right Hand") == _static("Mm'menon, the Right Hand")


# ── Tannuk, Memorial Ensign ───────────────────────────────────────────────────

def test_tannuk_memorial_ensign_claimed_by_parser():
    assert "Tannuk, Memorial Ensign" in _PARSER_PRINTINGS


def test_tannuk_memorial_ensign_parity():
    assert _parser("Tannuk, Memorial Ensign") == _static("Tannuk, Memorial Ensign")


# ── Tannuk, Steadfast Second ──────────────────────────────────────────────────

def test_tannuk_steadfast_second_claimed_by_parser():
    assert "Tannuk, Steadfast Second" in _PARSER_PRINTINGS


def test_tannuk_steadfast_second_parity():
    assert _parser("Tannuk, Steadfast Second") == _static("Tannuk, Steadfast Second")


# ── Ragost, Deft Gastronaut ───────────────────────────────────────────────────

def test_ragost_deft_gastronaut_claimed_by_parser():
    assert "Ragost, Deft Gastronaut" in _PARSER_PRINTINGS


def test_ragost_deft_gastronaut_parity():
    assert _parser("Ragost, Deft Gastronaut") == _static("Ragost, Deft Gastronaut")
