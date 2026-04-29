"""Tests for batch-20 effect-grammar and whole-spell additions.

One effect-grammar primitive lands in this batch:

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

One whole-spell exact-text dispatch entry also lands in this batch
(see ``_WHOLE_SPELL_EXACT_TEXT`` in ``parser.spell_builder``):

* **Scrounge for Eternity** ``{2}{B}`` Sorcery — additional-cost
  sacrifice + ``Return target creature or Spacecraft card with mana
  value 5 or less from your graveyard to the battlefield. Then
  create a Lander token.`` The static drops the target-type
  widening, the mana-value cap, and the Lander rider; ships
  ``ReturnCreatureFromYourGraveyardToBattlefield()`` plus the
  ``additional_cost_sacrifice_creature_or_artifact=True`` printing
  flag (the latter wired separately via
  ``_detect_additional_cost_flags``). Per the parser-is-right rule
  (codified in batch 19), the parser claims a deliberately-
  simplified spell only when the printed effect's intent survives
  the simplification — Scrounge's base mechanic ("a graveyard
  return") survives, so the whole-spell tier matches; Pull Through
  the Weft and Terminal Velocity stay unclaimed because the
  static replaces their composites with effects of a different
  intent.

The shared parametrized parity test in ``tests/test_parser_parity.py``
enforces full ``CardPrinting`` parity, so this file focuses on the
new grammar / dispatch entries in isolation plus the claim
assertions.
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    DoubleTargetCreaturesPowerUEOT,
    ReturnCreatureFromYourGraveyardToBattlefield,
    TriggeredAbility,
)
from mtg_bot.cards.parser.effects import _parse_effect_phrase
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.cards.parser.spell_builder import _try_whole_spell_exact_text
from mtg_bot.cards.parser.triggers import _parse_triggered_ability_line
from mtg_bot.effects.object_predicates import (
    IsLand,
)
from mtg_bot.effects.predicates import (
    Controlled,
    Event,
    Subject,
    YOU,
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
        predicate=Subject(None, IsLand()) & Controlled(YOU),
        effect=DoubleTargetCreaturesPowerUEOT(),
    )


# ---------- claim test (end-to-end via the parser source) ----------

def test_mightform_harmonizer_claimed_by_parser():
    assert "Mightform Harmonizer" in _claimed_names()


# ---------- whole-spell exact-text dispatch (Scrounge for Eternity) ----------

def test_scrounge_for_eternity_claimed_by_parser():
    # Scrounge for Eternity ``{2}{B}`` Sorcery — additional-cost
    # sacrifice preamble + ``Return target creature or Spacecraft card
    # with mana value 5 or less from your graveyard to the battlefield.
    # Then create a Lander token.``. Whole-spell exact-text dispatch
    # returns the bare ``ReturnCreatureFromYourGraveyardToBattlefield()``
    # engine class the static side ships (the target widening, mana-
    # value cap, and Lander rider are dropped — the base mechanic, a
    # graveyard return, survives the simplification per the
    # parser-is-right rule).
    assert "Scrounge for Eternity" in _claimed_names()


def test_dispatch_scrounge_for_eternity_returns_engine_class():
    # The dispatch key carries the additional-cost preamble line plus
    # the post-reminder-strip second line (the parenthesized Lander
    # reminder tail has been stripped before lookup). The dispatcher
    # hits BEFORE the per-clause additional-cost preamble-stripping
    # pass, so the key includes the verbatim preamble line.
    eff = _try_whole_spell_exact_text(
        "As an additional cost to cast this spell, sacrifice an "
        "artifact or creature.\n"
        "Return target creature or Spacecraft card with mana value 5 "
        "or less from your graveyard to the battlefield. "
        "Then create a Lander token."
    )
    assert eff == ReturnCreatureFromYourGraveyardToBattlefield()


def test_scrounge_for_eternity_carries_additional_cost_flag():
    # The additional-cost flag is wired separately via
    # ``_detect_additional_cost_flags`` — the whole-spell dispatcher
    # only returns the spell-effect engine class. End-to-end the
    # produced ``CardPrinting`` carries
    # ``additional_cost_sacrifice_creature_or_artifact=True`` so the
    # engine prompts the caster for the cost at cast time. Belt-
    # and-suspenders that the dispatcher entry doesn't accidentally
    # bypass the flag-detection pass.
    parser = OracleParserCardSource()
    p = parser.get_printings()["Scrounge for Eternity"]
    assert p.additional_cost_sacrifice_creature_or_artifact is True


def test_dispatch_scrounge_unrelated_text_returns_none():
    # A spell text that strips the additional-cost preamble or differs
    # in any meaningful way should NOT match the dispatcher entry —
    # the table is exact-match by design. Belt-and-suspenders that the
    # new entry doesn't accidentally widen the dispatcher's match
    # surface (e.g. a future printing with a different graveyard-return
    # body shouldn't accidentally pick up the simplification).
    assert _try_whole_spell_exact_text(
        # Same body, but missing the preamble — should miss.
        "Return target creature or Spacecraft card with mana value 5 "
        "or less from your graveyard to the battlefield. "
        "Then create a Lander token."
    ) is None
