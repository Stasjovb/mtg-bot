"""Tests for batch-7 unified-effect-grammar additions: ``counter target
spell``, ``exile target creature``, and ``each opponent loses N life``.

Each effect is exercised three ways: directly via ``_parse_effect`` on
the normalized phrase, via ``_parse_effect_phrase`` (creature-trigger
surface form), and via ``_parse_spell_effect_phrase`` (spell sentence
form, capitalized first letter and trailing period). This three-way
coverage verifies a single grammar addition lights up both contexts.
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    CounterTargetSpell,
    EachOpponentLosesLife,
    ExileTargetCreature,
)
from mtg_bot.cards.parser.effects import (
    _parse_effect,
    _parse_effect_phrase,
    _parse_spell_effect_phrase,
)


# ---------- counter target spell ----------

def test_parse_effect_recognizes_counter_target_spell():
    assert _parse_effect("counter target spell") == CounterTargetSpell()


def test_parse_effect_phrase_recognizes_counter_target_spell():
    # Creature-trigger surface form, no "it" subject (the controller
    # does the countering, not the creature).
    assert _parse_effect_phrase("counter target spell") == \
        CounterTargetSpell()


def test_parse_spell_effect_phrase_recognizes_counter_target_spell():
    # Spell surface form: capitalized + trailing period.
    assert _parse_spell_effect_phrase(
        "Counter target spell.", "Bogus Counterspell"
    ) == CounterTargetSpell()


def test_parse_spell_effect_phrase_counter_strips_card_name_subject():
    # Card-name subject prefix stripped.
    assert _parse_spell_effect_phrase(
        "Bogus Counterspell counter target spell.", "Bogus Counterspell"
    ) == CounterTargetSpell()


# ---------- exile target creature ----------

def test_parse_effect_recognizes_exile_target_creature():
    assert _parse_effect("exile target creature") == ExileTargetCreature()


def test_parse_effect_phrase_recognizes_exile_target_creature():
    assert _parse_effect_phrase("exile target creature") == \
        ExileTargetCreature()


def test_parse_spell_effect_phrase_recognizes_exile_target_creature():
    assert _parse_spell_effect_phrase(
        "Exile target creature.", "Bogus Exile"
    ) == ExileTargetCreature()


# ---------- each opponent loses N life ----------

def test_parse_effect_recognizes_each_opponent_loses_2_life():
    assert _parse_effect("each opponent loses 2 life") == \
        EachOpponentLosesLife(amount=2)


def test_parse_effect_recognizes_each_opponent_loses_arbitrary_n():
    # The N is captured generically — verify a few values land.
    assert _parse_effect("each opponent loses 1 life") == \
        EachOpponentLosesLife(amount=1)
    assert _parse_effect("each opponent loses 7 life") == \
        EachOpponentLosesLife(amount=7)


def test_parse_effect_phrase_recognizes_each_opponent_loses_n_life():
    # Creature-trigger surface form (no "it" subject — opponents lose
    # the life, not the creature).
    assert _parse_effect_phrase("each opponent loses 3 life") == \
        EachOpponentLosesLife(amount=3)


def test_parse_spell_effect_phrase_recognizes_each_opponent_loses_n_life():
    # Spell surface form: capitalized + trailing period.
    assert _parse_spell_effect_phrase(
        "Each opponent loses 2 life.", "Bogus Drain"
    ) == EachOpponentLosesLife(amount=2)


# ---------- negative cases ----------

def test_parse_effect_returns_none_for_malformed_counter_phrase():
    assert _parse_effect("counter target") is None
    assert _parse_effect("counter target creature spell") is None
    assert _parse_effect("counter spell") is None


def test_parse_effect_returns_none_for_malformed_exile_phrase():
    assert _parse_effect("exile target") is None
    assert _parse_effect("exile target artifact") is None
    assert _parse_effect("exile target creature you control") is None


def test_parse_effect_returns_none_for_malformed_each_opponent_loses():
    # Missing amount, non-numeric amount, missing "life".
    assert _parse_effect("each opponent loses life") is None
    assert _parse_effect("each opponent loses two life") is None
    assert _parse_effect("each opponent loses 2") is None
    assert _parse_effect("target opponent loses 2 life") is None


def test_parse_spell_effect_phrase_returns_none_for_malformed_phrase():
    assert _parse_spell_effect_phrase(
        "Counter every spell ever.", "Bogus"
    ) is None
    assert _parse_spell_effect_phrase(
        "Exile something nonsense.", "Bogus"
    ) is None
    assert _parse_spell_effect_phrase(
        "Each opponent gains 2 life.", "Bogus"
    ) is None
