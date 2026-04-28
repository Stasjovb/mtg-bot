"""Tests for batch-17 whole-spell exact-text dispatch additions plus
the self-shuffle printing-flag detector.

Batch 17 extends the ``_WHOLE_SPELL_EXACT_TEXT`` dispatcher in
``parser.spell_builder`` with three entries (Darkness, Nexus of Fate,
Green Sun's Zenith) and adds a name-aware self-shuffle rider detector
(``_detect_shuffle_self_flags``) that threads the
``shuffles_into_library_instead_of_graveyard`` printing flag onto
spells whose oracle text carries either of the two recognized
shuffle-self riders.

Newly claimed spells:

* **Darkness** ``{B}`` Instant — prevent all combat damage that
  would be dealt this turn. Maps to
  ``PreventAllCombatDamageThisTurn()``.
* **Nexus of Fate** ``{5}{U}{U}`` Instant — take an extra turn after
  this one, plus a shuffle-instead-of-graveyard rider. Effect maps
  to ``TakeExtraTurnAfterThisOne()``; the rider sets the
  ``shuffles_into_library_instead_of_graveyard`` printing flag.
* **Green Sun's Zenith** ``{X}{G}`` Sorcery — variable-X tutor for a
  green creature, plus a self-shuffle rider on the same line. Effect
  maps to ``SearchLibraryForGreenCreatureWithMVAtMostX()``; the
  rider sets the printing flag.

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

from mtg_bot.cards.base import (
    PreventAllCombatDamageThisTurn,
    SearchLibraryForGreenCreatureWithMVAtMostX,
    TakeExtraTurnAfterThisOne,
)
from mtg_bot.cards.parser.spell_builder import (
    _detect_shuffle_self_flags,
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


def test_nexus_of_fate_claimed_by_parser():
    # Nexus of Fate ``{5}{U}{U}`` Instant — take-extra-turn plus a
    # shuffle-instead-of-graveyard rider. Whole-spell exact-text
    # dispatch returns the take-extra-turn engine class; the rider
    # threads the printing flag via ``_detect_shuffle_self_flags``.
    assert "Nexus of Fate" in _claimed_names()


def test_green_suns_zenith_claimed_by_parser():
    # Green Sun's Zenith ``{X}{G}`` Sorcery — variable-X tutor for a
    # green creature plus a self-shuffle rider. Whole-spell exact-text
    # dispatch returns the search-engine instance; the rider threads
    # the printing flag via ``_detect_shuffle_self_flags``.
    assert "Green Sun's Zenith" in _claimed_names()


# ---------- dispatch tests (direct lookup) ----------

def test_dispatch_darkness_returns_engine_class():
    eff = _try_whole_spell_exact_text(
        "Prevent all combat damage that would be dealt this turn."
    )
    assert eff == PreventAllCombatDamageThisTurn()


def test_dispatch_nexus_of_fate_returns_engine_class():
    # The dispatch key carries the literal newline between the take-
    # extra-turn line and the shuffle-instead-of-graveyard rider.
    eff = _try_whole_spell_exact_text(
        "Take an extra turn after this one.\n"
        "If Nexus of Fate would be put into a graveyard from anywhere, "
        "reveal Nexus of Fate and shuffle it into its owner's library "
        "instead."
    )
    assert eff == TakeExtraTurnAfterThisOne()


def test_dispatch_green_suns_zenith_returns_engine_class():
    # GSZ's two sentences sit on a single line in the printed text;
    # the dispatch key joins them with a single space.
    eff = _try_whole_spell_exact_text(
        "Search your library for a green creature card with mana "
        "value X or less, put it onto the battlefield, then shuffle. "
        "Shuffle Green Sun's Zenith into its owner's library."
    )
    assert eff == SearchLibraryForGreenCreatureWithMVAtMostX()


# ---------- self-shuffle rider detector ----------

def test_detect_shuffle_self_flags_nexus_shape():
    # Nexus-of-Fate-style rider: ``If <Name> would be put into a
    # graveyard from anywhere, reveal <Name> and shuffle it into its
    # owner's library instead.``
    text = (
        "Take an extra turn after this one.\n"
        "If Nexus of Fate would be put into a graveyard from anywhere, "
        "reveal Nexus of Fate and shuffle it into its owner's library "
        "instead."
    )
    flags = _detect_shuffle_self_flags(text, "Nexus of Fate")
    assert flags == {"shuffles_into_library_instead_of_graveyard": True}


def test_detect_shuffle_self_flags_gsz_shape():
    # GSZ-style rider: ``Shuffle <Name> into its owner's library.`` —
    # appears as the trailing sentence of the spell's single oracle
    # line.
    text = (
        "Search your library for a green creature card with mana "
        "value X or less, put it onto the battlefield, then shuffle. "
        "Shuffle Green Sun's Zenith into its owner's library."
    )
    flags = _detect_shuffle_self_flags(text, "Green Sun's Zenith")
    assert flags == {"shuffles_into_library_instead_of_graveyard": True}


def test_detect_shuffle_self_flags_no_rider():
    # Spell text without a self-shuffle rider returns an empty dict so
    # the caller's ``**`` spread is a no-op.
    text = "Prevent all combat damage that would be dealt this turn."
    assert _detect_shuffle_self_flags(text, "Darkness") == {}


def test_detect_shuffle_self_flags_name_with_apostrophe():
    # ``Green Sun's Zenith`` carries an apostrophe; the helper
    # ``re.escape``-s the name so the rider matches verbatim. Sanity-
    # check that this works (regression for a future card with
    # similar punctuation).
    text = (
        "Do something. "
        "Shuffle Green Sun's Zenith into its owner's library."
    )
    flags = _detect_shuffle_self_flags(text, "Green Sun's Zenith")
    assert flags == {"shuffles_into_library_instead_of_graveyard": True}


def test_detect_shuffle_self_flags_wrong_name():
    # The detector keys on the card's name, so a spell that mentions
    # a DIFFERENT card's shuffle rider doesn't trip the flag. (No real
    # card in the EoE pool does this — defensive regression.)
    text = (
        "Take an extra turn after this one.\n"
        "If Nexus of Fate would be put into a graveyard from anywhere, "
        "reveal Nexus of Fate and shuffle it into its owner's library "
        "instead."
    )
    assert _detect_shuffle_self_flags(text, "Some Other Card") == {}
