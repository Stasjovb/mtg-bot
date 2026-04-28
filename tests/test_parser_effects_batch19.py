"""Tests for batch-19 whole-spell exact-text dispatch additions in
``parser.spell_builder``.

Batch 19 extends ``_WHOLE_SPELL_EXACT_TEXT`` with simplified-static
counterspell shapes whose printed riders aren't modeled engine-side:

* **Unravel** ``{1}{U}{U}`` Instant — ``Counter target spell. If the
  amount of mana spent to cast that spell was less than its mana
  value, you draw a card.`` The static ships the bare
  ``CounterTargetSpell()`` and drops the mana-spent-conditional draw
  rider; the engine doesn't track per-spell cast-time mana
  accounting. The whole-spell tier mirrors that simplification.

* **Divert Disaster** ``{1}{U}`` Instant — ``Counter target spell
  unless its controller pays {2}. If they do, you create a Lander
  token.`` The static ships the bare ``CounterTargetSpell()`` (no
  pay-cost branching, no Lander creation) — the engine doesn't yet
  model the pay-cost-or-counter Mana Leak shape. The trailing
  parenthesized Lander reminder text is stripped before dispatch.

Each spell is exercised by:
  - A claim test confirming the parser's ``claimed_names`` includes
    it (end-to-end via the parser source).
  - A dispatch test confirming ``_try_whole_spell_exact_text`` returns
    the same engine-class instance the static side ships, keyed on
    the post-reminder-strip oracle text.
  - The shared parametrized parity test in
    ``tests/test_parser_parity.py`` enforces that the produced
    ``CardPrinting`` matches the static one (no separate per-card
    parity assert needed here).
"""

from __future__ import annotations

from mtg_bot.cards.base import CounterTargetSpell
from mtg_bot.cards.parser.spell_builder import _try_whole_spell_exact_text
from mtg_bot.cards.parser_source import OracleParserCardSource


def _claimed_names() -> frozenset[str]:
    return frozenset(OracleParserCardSource().claimed_names)


# ---------- claim tests (end-to-end via the parser source) ----------

def test_unravel_claimed_by_parser():
    # Unravel ``{1}{U}{U}`` Instant — counter-target-spell + a
    # mana-spent-conditional draw rider. Whole-spell exact-text
    # dispatch returns the bare ``CounterTargetSpell()`` engine class
    # the static side ships; the rider is dropped (engine doesn't
    # track per-spell cast-time mana accounting).
    assert "Unravel" in _claimed_names()


def test_divert_disaster_claimed_by_parser():
    # Divert Disaster ``{1}{U}`` Instant — Mana-Leak-shaped pay-or-
    # counter + Lander-on-pay rider. Whole-spell exact-text dispatch
    # returns the bare ``CounterTargetSpell()`` engine class the
    # static side ships; the trailing parenthesized Lander reminder
    # text is stripped before lookup.
    assert "Divert Disaster" in _claimed_names()


# ---------- dispatch tests (direct lookup) ----------

def test_dispatch_unravel_returns_engine_class():
    # Unravel's two sentences sit on a single oracle-text line; the
    # dispatch key joins them with a single space (matches the printed
    # surface form post reminder-text strip).
    eff = _try_whole_spell_exact_text(
        "Counter target spell. "
        "If the amount of mana spent to cast that spell was less "
        "than its mana value, you draw a card."
    )
    assert eff == CounterTargetSpell()


def test_dispatch_divert_disaster_returns_engine_class():
    # Divert Disaster's printed text has a parenthesized Lander
    # reminder tail; the dispatch key matches the post-reminder-strip
    # form (just the two effect sentences).
    eff = _try_whole_spell_exact_text(
        "Counter target spell unless its controller pays {2}. "
        "If they do, you create a Lander token."
    )
    assert eff == CounterTargetSpell()


def test_dispatch_unrelated_text_returns_none():
    # A spell text that isn't in the dispatch table returns ``None`` —
    # belt-and-suspenders that the new entries don't accidentally
    # widen the dispatcher's match surface.
    assert _try_whole_spell_exact_text("Counter target creature spell.") is None
