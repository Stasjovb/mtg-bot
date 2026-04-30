"""Tests for batch-19 whole-spell exact-text dispatch additions in
``parser.spell_builder``.

Batch 19 extends ``_WHOLE_SPELL_EXACT_TEXT`` with three new entries —
two counterspell shapes whose static drops a printed rider, and one
3-mode modal whose per-mode primitives are one-offs. Per the parser-
is-right rule the parser only claims a deliberately-simplified spell
when the base mechanic still matches the printed effect (a
counterspell is still a counterspell once the rider's gone; a modal
spell stays modal even if a per-mode sub-effect drops planeswalker
targeting). When the static stand-in changes the spell's *intent*
entirely (e.g. Pull Through the Weft's dual-target sequence becoming
a single-target return; Terminal Velocity's put-from-hand composite
becoming a token-creation spell), the parser stays unclaimed. The
shared ``test_source_skips_cards_with_unsupported_clauses`` test
guards that boundary on Pull Through the Weft.

Newly claimed spells:

* **Unravel** ``{1}{U}{U}`` Instant — ``Counter target spell. If the
  amount of mana spent to cast that spell was less than its mana
  value, you draw a card.`` The static drops the mana-spent-
  conditional draw rider; the engine doesn't track per-spell cast-
  time mana accounting.

* **Divert Disaster** ``{1}{U}`` Instant — ``Counter target spell
  unless its controller pays {2}. If they do, you create a Lander
  token.`` The static drops both the pay-cost branching and the
  Lander rider — the engine doesn't yet model the pay-cost-or-
  counter Mana Leak shape. The trailing parenthesized Lander
  reminder text is stripped before dispatch.

* **Archenemy's Charm** ``{B}{B}{B}`` Instant — Choose-one modal
  with three one-off-per-mode primitives:
  ``ExileTargetCreature()``,
  ``ReturnUpToNCreaturesFromYourGraveyardToHand(max_n=2, min_n=1)``,
  and
  ``PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl(
  amount=2, granted_keywords={'lifelink'})``. The per-mode parser
  can't claim it (none of the three mode lines parse as standalone
  spell-effect phrases); whole-spell exact-text dispatch returns the
  full ``ModalChooseOne``. Mode 1's ``or planeswalker`` and Mode 2's
  ``and/or planeswalker`` simplifications mirror Warping Wail's
  same-shape Mode 1 (planeswalkers aren't fully modeled in the EoE
  pool yet).

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

from mtg_bot.cards.base import (
    CounterTargetSpell,
    ExileTargetCreature,
    ModalChooseOne,
    PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl,
    ReturnUpToNCreaturesFromYourGraveyardToHand,
)
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


def test_archenemys_charm_claimed_by_parser():
    # Archenemy's Charm ``{B}{B}{B}`` Instant — 3-mode Choose-one
    # modal now claimed via the per-clause grammar: mode 1 (exile-or-
    # planeswalker), mode 2 (1-or-2 graveyard returns), and mode 3
    # (multi-counter + grant-keyword 2-sentence body).
    assert "Archenemy's Charm" in _claimed_names()


def test_dispatch_archenemys_charm_no_bespoke_entry():
    # After migration, the whole-spell dispatcher no longer has an
    # entry for Archenemy's Charm.
    assert _try_whole_spell_exact_text(
        "Choose one —\n"
        "• Exile target creature or planeswalker.\n"
        "• Return one or two target creature and/or planeswalker "
        "cards from your graveyard to your hand.\n"
        "• Put two +1/+1 counters on target creature you control. "
        "It gains lifelink until end of turn."
    ) is None


def test_archenemys_charm_parses_via_per_clause_grammar():
    # Belt-and-suspenders: the per-clause modal grammar produces the
    # same 3-mode ModalChooseOne as the static registry.
    from mtg_bot.cards.parser.spell_builder import _parse_spell_oracle_text
    eff = _parse_spell_oracle_text(
        "Choose one —\n"
        "• Exile target creature or planeswalker.\n"
        "• Return one or two target creature and/or planeswalker "
        "cards from your graveyard to your hand.\n"
        "• Put two +1/+1 counters on target creature you control. "
        "It gains lifelink until end of turn.",
        "Archenemy's Charm",
    )
    assert eff == ModalChooseOne(modes=(
        ExileTargetCreature(),
        ReturnUpToNCreaturesFromYourGraveyardToHand(max_n=2, min_n=1),
        PutPlusOneCountersAndGrantKeywordsUEOTOnTargetCreatureYouControl(
            amount=2, granted_keywords=frozenset({"lifelink"}),
        ),
    ))


def test_dispatch_unrelated_text_returns_none():
    # A spell text that isn't in the dispatch table returns ``None`` —
    # belt-and-suspenders that the new entries don't accidentally
    # widen the dispatcher's match surface.
    assert _try_whole_spell_exact_text("Counter target creature spell.") is None
