"""Tests for batch-20 effect-grammar additions.

One new piece of grammar lands in this batch:

* ``double the power of target creature you control until end of
  turn`` → ``DoubleTargetCreaturesPowerUEOT()``. Mightform
  Harmonizer's landfall trigger body. Distinct from the existing
  ``gets +N/+0`` UEOT pump shapes — the bonus is computed at
  resolve time from the target's current effective power rather
  than being a fixed constant. The engine class adds the
  measured-at-resolve power as a temp_power_bonus that clears at
  end-of-turn cleanup.

One creature newly claims through this primitive:

* **Mightform Harmonizer** — ``Landfall — Whenever a land you
  control enters, double the power of target creature you control
  until end of turn.`` The ability-word strip and landfall trigger
  predicate already existed; the only blocker was the
  unrecognized inner-effect grammar.

The shared parametrized parity test in ``tests/test_parser_parity.py``
enforces full ``CardPrinting`` parity, so this file focuses on the
new grammar in isolation plus the claim assertion.
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    DoubleTargetCreaturesPowerUEOT,
    TriggeredAbility,
)
from mtg_bot.cards.parser.effects import _parse_effect_phrase
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.cards.parser.triggers import _parse_triggered_ability_line
from mtg_bot.effects.predicates import (
    YOU,
    Controlled,
    Event,
    IsLand,
)


def _claimed_names() -> frozenset[str]:
    return frozenset(OracleParserCardSource().claimed_names)


# ---------- effect-phrase grammar ----------

def test_parse_double_target_creature_you_control_power_ueot():
    # The new effect-phrase primitive. Maps to the engine class with
    # no parameters — the legal-target predicate (``target creature
    # you control``) and duration (``until end of turn``) are encoded
    # by the class.
    phrase = (
        "double the power of target creature you control until end of "
        "turn"
    )
    assert _parse_effect_phrase(phrase) == DoubleTargetCreaturesPowerUEOT()


# ---------- trigger-line end-to-end ----------

def test_mightform_harmonizer_landfall_trigger_line():
    # End-to-end with the landfall ability-word prefix. Mirrors the
    # static-registry layout exactly — the ability-word is stripped,
    # the condition phrase ``a land you control enters`` resolves
    # via the existing landfall predicate, and the inner effect goes
    # through the new grammar.
    line = (
        "Landfall — Whenever a land you control enters, double "
        "the power of target creature you control until end of turn."
    )
    parsed = _parse_triggered_ability_line(line)
    assert parsed == TriggeredAbility(
        event=Event.ENTERS,
        predicate=IsLand() & Controlled(YOU),
        effect=DoubleTargetCreaturesPowerUEOT(),
    )


# ---------- claim test (end-to-end via the parser source) ----------

def test_mightform_harmonizer_claimed_by_parser():
    assert "Mightform Harmonizer" in _claimed_names()
