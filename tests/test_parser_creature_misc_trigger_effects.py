"""Tests for batch-19 trigger-time and effect-grammar additions.

Two new pieces of grammar land in this batch:

* ``At the beginning of combat on your turn`` —
  ``_AT_BEGINNING_OF_PHRASES`` gains the
  ``"combat on your turn"`` entry mapping to
  ``(Event.BEGINNING_OF_COMBAT, Controlled(YOU))``. Mirrors the
  existing ``"your end step"`` precedent: ``your X`` reads as
  ``Controlled(YOU)`` (the trigger fires on the controller's own
  combat). ``each combat`` would map to ``Always()`` if a future
  printing ships it; no EoE printing today carries the variant.

* ``you may discard your hand. If you do, draw N cards`` →
  ``DiscardHandThenDrawN(amount=N)``. Vaultguard Trooper's tapped-
  creatures-gated end-step trigger inner effect. Distinct from the
  existing single-card ``you may discard a card. If you do, draw N
  cards`` shape (Mechan Navigator-adjacent grammar): discards the
  WHOLE hand, not a single chosen card.

Two creatures newly claim through these primitives:

* **Molecular Modifier** — ``At the beginning of combat on your
  turn, target creature you control gets +1/+0 and gains first
  strike until end of turn.`` The inner pump-and-grant effect
  already parsed via the existing ``_PUMP_AND_GAIN_KEYWORDS_UEOT``
  regex; the only blocker was the unrecognized
  ``combat on your turn`` time phrase.
* **Vaultguard Trooper** — ``At the beginning of your end step, if
  you control two or more tapped creatures, you may discard your
  hand. If you do, draw two cards.`` The
  ``ConditionalOnTappedCreatures`` wrapper already sat at the
  trigger-line level via the tapped-creatures-gate prefix path; the
  blocker was the unrecognized inner-effect grammar.

The shared parametrized parity test in ``tests/test_parser_parity.py``
enforces full ``CardPrinting`` parity, so this file focuses on the
new grammar in isolation plus claim assertions.
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    ConditionalOnTappedCreatures,
    DiscardHandThenDrawN,
    PumpTargetCreatureUntilEOT,
    TriggeredAbility,
)
from mtg_bot.cards.parser.effects import _parse_effect_phrase
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.cards.parser.triggers import (
    _parse_at_beginning_of_phrase,
    _parse_triggered_ability_line,
)
from mtg_bot.effects.predicates import (
    YOU,
    Controlled,
    Event,
)


def _claimed_names() -> frozenset[str]:
    return frozenset(OracleParserCardSource().claimed_names)


# ---------- ``At the beginning of combat on your turn`` ----------

def test_parse_at_beginning_of_combat_on_your_turn():
    # The new time-phrase entry. ``your X`` reads as
    # ``Controlled(YOU)`` per the existing precedent — the trigger
    # fires only on the controller's own combat phase.
    assert _parse_at_beginning_of_phrase("combat on your turn") == (
        Event.BEGINNING_OF_COMBAT, Controlled(YOU),
    )


def test_molecular_modifier_trigger_line():
    # End-to-end: the new time-phrase composes with the existing
    # ``_PUMP_AND_GAIN_KEYWORDS_UEOT`` inner-effect grammar to produce
    # a single ``TriggeredAbility`` whose shape mirrors the static
    # registry's Molecular Modifier entry.
    line = (
        "At the beginning of combat on your turn, target creature you "
        "control gets +1/+0 and gains first strike until end of turn."
    )
    parsed = _parse_triggered_ability_line(line)
    assert parsed == TriggeredAbility(
        event=Event.BEGINNING_OF_COMBAT,
        predicate=Controlled(YOU),
        effect=PumpTargetCreatureUntilEOT(
            power_bonus=1, toughness_bonus=0,
            granted_keywords=frozenset({"first strike"}),
            you_control_only=True,
        ),
    )


# ---------- ``you may discard your hand. If you do, draw N cards`` ----------

def test_parse_discard_hand_then_draw():
    # Vaultguard Trooper's inner-effect surface form. Distinct from
    # the single-card ``discard a card`` grammar: discards the WHOLE
    # hand, not a single chosen card. Maps to
    # ``DiscardHandThenDrawN(amount=N)``.
    phrase = "you may discard your hand. If you do, draw two cards"
    assert _parse_effect_phrase(phrase) == DiscardHandThenDrawN(amount=2)


def test_parse_discard_hand_then_draw_amount_one():
    # Bare ``draw a card`` tail collapses to amount=1 — included for
    # symmetry with the single-card discard grammar (no EoE printing
    # today uses ``draw a card`` after a hand discard, but the regex
    # accepts the surface form).
    phrase = "you may discard your hand. If you do, draw a card"
    assert _parse_effect_phrase(phrase) == DiscardHandThenDrawN(amount=1)


def test_vaultguard_trooper_trigger_line():
    # End-to-end: the existing tapped-creatures-gate prefix path wraps
    # the new ``DiscardHandThenDrawN`` inner effect in
    # ``ConditionalOnTappedCreatures``. Mirrors the static registry's
    # Vaultguard Trooper entry exactly.
    line = (
        "At the beginning of your end step, if you control two or "
        "more tapped creatures, you may discard your hand. If you do, "
        "draw two cards."
    )
    parsed = _parse_triggered_ability_line(line)
    assert parsed == TriggeredAbility(
        event=Event.BEGINNING_OF_END_STEP,
        predicate=Controlled(YOU),
        effect=ConditionalOnTappedCreatures(
            effect=DiscardHandThenDrawN(amount=2),
            min_count=2,
        ),
    )


# ---------- claim tests (end-to-end via the parser source) ----------

def test_molecular_modifier_claimed_by_parser():
    assert "Molecular Modifier" in _claimed_names()


def test_vaultguard_trooper_claimed_by_parser():
    assert "Vaultguard Trooper" in _claimed_names()
