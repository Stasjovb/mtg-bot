"""Tests for batch-17 whole-spell exact-text dispatch additions.

This batch extends the ``_WHOLE_SPELL_EXACT_TEXT`` dispatcher in
``parser.spell_builder`` with one entry — Darkness, the simplest
remaining unclaimed instant in the EoE pool.

Newly claimed spells:

* **Darkness** ``{B}`` Instant — prevent all combat damage that
  would be dealt this turn. Maps to
  ``PreventAllCombatDamageThisTurn()``.

Each spell is exercised by:
  - A claim test confirming the parser's ``claimed_names`` includes
    it.
  - A dispatch test confirming
    ``_try_whole_spell_exact_text`` returns the same engine-class
    instance the static side ships.
  - The shared parametrized parity test in
    ``tests/test_parser_parity.py`` enforces that the produced
    ``CardPrinting`` matches the static one (no separate per-card
    parity assert needed here).
"""

from __future__ import annotations

from mtg_bot.cards.base import PreventAllCombatDamageThisTurn
from mtg_bot.cards.parser.spell_builder import (
    _try_whole_spell_exact_text,
)
from mtg_bot.cards.parser_source import OracleParserCardSource


def _claimed_names() -> frozenset[str]:
    return frozenset(OracleParserCardSource().claimed_names)


# ---------- claim tests (end-to-end via the parser source) ----------

def test_darkness_claimed_by_parser():
    # Darkness ``{B}`` Instant — prevent all combat damage that would
    # be dealt this turn. Single-sentence spell whose effect engine
    # class (``PreventAllCombatDamageThisTurn``) sets a state flag the
    # combat damage step honors. The whole-spell exact-text dispatch
    # claims it because no per-clause primitive for "prevent all
    # combat damage" exists elsewhere in the EoE pool.
    assert "Darkness" in _claimed_names()


# ---------- dispatch tests (direct lookup) ----------

def test_dispatch_darkness_returns_engine_class():
    eff = _try_whole_spell_exact_text(
        "Prevent all combat damage that would be dealt this turn."
    )
    assert eff == PreventAllCombatDamageThisTurn()
