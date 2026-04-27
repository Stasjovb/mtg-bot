"""Tests for batch-8 unified-effect-grammar additions: ``surveil N``,
``mill <amount> cards`` (digit or spelled-out cardinal), and three
``destroy target <type>`` shapes for artifacts, lands, and noncreature
permanents.

Each effect is exercised three ways: directly via ``_parse_effect`` on
the normalized phrase, via ``_parse_effect_phrase`` (creature-trigger
surface form), and via ``_parse_spell_effect_phrase`` (spell sentence
form, capitalized first letter and trailing period). This three-way
coverage verifies a single grammar addition lights up both contexts.
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    DestroyTargetArtifact,
    DestroyTargetLand,
    DestroyTargetNoncreaturePermanent,
    SelfMill,
    Surveil,
)
from mtg_bot.cards.parser.effects import (
    _parse_amount,
    _parse_effect,
    _parse_effect_phrase,
    _parse_spell_effect_phrase,
)


# ---------- surveil N ----------

def test_parse_effect_recognizes_surveil_1():
    assert _parse_effect("surveil 1") == Surveil(amount=1)


def test_parse_effect_recognizes_surveil_arbitrary_n():
    assert _parse_effect("surveil 2") == Surveil(amount=2)
    assert _parse_effect("surveil 5") == Surveil(amount=5)


def test_parse_effect_phrase_recognizes_surveil_n():
    # Creature-trigger surface form. No "it" subject — "surveil" has
    # an implicit "you" subject in Scryfall printing convention.
    assert _parse_effect_phrase("surveil 2") == Surveil(amount=2)


def test_parse_spell_effect_phrase_recognizes_surveil_n():
    # Spell surface form: capitalized first letter + trailing period.
    assert _parse_spell_effect_phrase(
        "Surveil 1.", "Bogus Mindspike"
    ) == Surveil(amount=1)


# ---------- mill N cards ----------

def test_parse_effect_recognizes_mill_with_digit():
    # Digit form (mostly hypothetical for EoE; supports forward-compat).
    assert _parse_effect("mill 3 cards") == SelfMill(amount=3)


def test_parse_effect_recognizes_mill_with_spelled_word():
    # Spelled-out form is what EoE actually prints (e.g. Lithic
    # Hierograph, Hullcarver).
    assert _parse_effect("mill three cards") == SelfMill(amount=3)
    assert _parse_effect("mill five cards") == SelfMill(amount=5)
    assert _parse_effect("mill ten cards") == SelfMill(amount=10)


def test_parse_effect_phrase_recognizes_mill_n_cards():
    # Creature-trigger surface form (no "it" subject — the controller
    # mills, not the creature).
    assert _parse_effect_phrase("mill three cards") == SelfMill(amount=3)


def test_parse_spell_effect_phrase_recognizes_mill_n_cards():
    assert _parse_spell_effect_phrase(
        "Mill three cards.", "Bogus Mill"
    ) == SelfMill(amount=3)


# ---------- destroy target artifact ----------

def test_parse_effect_recognizes_destroy_target_artifact():
    assert _parse_effect("destroy target artifact") == \
        DestroyTargetArtifact()


def test_parse_effect_phrase_recognizes_destroy_target_artifact():
    assert _parse_effect_phrase("destroy target artifact") == \
        DestroyTargetArtifact()


def test_parse_spell_effect_phrase_recognizes_destroy_target_artifact():
    assert _parse_spell_effect_phrase(
        "Destroy target artifact.", "Bogus Shatter"
    ) == DestroyTargetArtifact()


# ---------- destroy target land ----------

def test_parse_effect_recognizes_destroy_target_land():
    assert _parse_effect("destroy target land") == DestroyTargetLand()


def test_parse_effect_phrase_recognizes_destroy_target_land():
    assert _parse_effect_phrase("destroy target land") == \
        DestroyTargetLand()


def test_parse_spell_effect_phrase_recognizes_destroy_target_land():
    assert _parse_spell_effect_phrase(
        "Destroy target land.", "Bogus Stone Rain"
    ) == DestroyTargetLand()


# ---------- destroy target noncreature permanent ----------

def test_parse_effect_recognizes_destroy_target_noncreature_permanent():
    assert _parse_effect("destroy target noncreature permanent") == \
        DestroyTargetNoncreaturePermanent()


def test_parse_effect_phrase_recognizes_destroy_noncreature_permanent():
    assert _parse_effect_phrase("destroy target noncreature permanent") == \
        DestroyTargetNoncreaturePermanent()


def test_parse_spell_effect_phrase_recognizes_destroy_noncreature_perm():
    assert _parse_spell_effect_phrase(
        "Destroy target noncreature permanent.", "Bogus Vindicate"
    ) == DestroyTargetNoncreaturePermanent()


# ---------- amount-token helper ----------

def test_parse_amount_handles_digit_token():
    assert _parse_amount("7") == 7


def test_parse_amount_handles_spelled_word():
    assert _parse_amount("seven") == 7
    assert _parse_amount("one") == 1
    assert _parse_amount("ten") == 10


# ---------- negative cases ----------

def test_parse_effect_returns_none_for_malformed_surveil():
    # No amount.
    assert _parse_effect("surveil") is None
    # Spelled-out cardinal not supported for surveil (Scryfall always
    # prints surveil with a digit, so we keep the grammar tight).
    assert _parse_effect("surveil two") is None
    # Trailing junk.
    assert _parse_effect("surveil 1 then draw") is None


def test_parse_effect_returns_none_for_malformed_mill():
    # Missing "cards".
    assert _parse_effect("mill three") is None
    # Singular form intentionally not handled (no EoE card uses it).
    assert _parse_effect("mill one card") is None
    # Out-of-range word.
    assert _parse_effect("mill twelve cards") is None
    # Wrong subject.
    assert _parse_effect("each opponent mills three cards") is None


def test_parse_effect_returns_none_for_malformed_destroy_artifact():
    assert _parse_effect("destroy target artifacts") is None
    assert _parse_effect("destroy target artifact you control") is None
    assert _parse_effect("destroy target artifact or creature") is None


def test_parse_effect_returns_none_for_malformed_destroy_land():
    assert _parse_effect("destroy target lands") is None
    assert _parse_effect("destroy target nonbasic land") is None


def test_parse_effect_returns_none_for_malformed_destroy_noncreature():
    assert _parse_effect("destroy target noncreature") is None
    assert _parse_effect("destroy target nonland permanent") is None
    assert _parse_effect("destroy target noncreature permanent you control") \
        is None


def test_parse_spell_effect_phrase_returns_none_for_malformed_phrase():
    assert _parse_spell_effect_phrase(
        "Surveil twice.", "Bogus"
    ) is None
    assert _parse_spell_effect_phrase(
        "Mill the top three cards of your library.", "Bogus"
    ) is None
    assert _parse_spell_effect_phrase(
        "Destroy target Dragon.", "Bogus"
    ) is None
