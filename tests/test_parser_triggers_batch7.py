"""Tests for batch-7 trigger-condition phrase additions.

Three new condition phrases land in this batch:

* ``you cast your second spell each turn`` → engine key
  ``second_spell_each_turn`` (Illvoi Operative, Sunstar Lightsmith,
  Station Monitor, etc.).
* ``you sacrifice another creature or artifact`` → engine key
  ``sacrifice_creature_or_artifact`` (Lightless Evangel).
* ``a creature you control with a +1/+1 counter on it dies`` →
  engine key ``creature_you_control_with_counter_dies``
  (Meltstrider Eulogist).

Each gets a ``_parse_trigger_phrase`` lookup test, an end-to-end
``_parse_triggered_ability_line`` test that pairs the new condition
with an existing-grammar effect, and a shared negative test for an
unknown phrase.
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    DrawCards,
    PutPlusOneCounterOnSelf,
    TriggeredAbility,
)
from mtg_bot.cards.parser.triggers import (
    _parse_predicate_trigger_phrase,
    _parse_trigger_phrase,
    _parse_triggered_ability_line,
)
from mtg_bot.effects.predicates import (
    YOU,
    Controlled,
    Event,
    HasCounter,
    IsCreature,
)


_COUNTER_DIES_PRED = IsCreature() & Controlled(YOU) & HasCounter("+1/+1")


# ---------- you cast your second spell each turn ----------

def test_parse_trigger_phrase_recognizes_second_spell_each_turn():
    # The verbatim oracle clause ``you cast your second spell each
    # turn`` is the literal lookup key that maps to the engine's
    # canonical ``second_spell_each_turn`` trigger. Other parameters
    # (e.g. "your *third* spell") aren't in scope for the simple
    # phrase-lookup mechanism — only this exact phrase resolves.
    assert _parse_trigger_phrase(
        "you cast your second spell each turn"
    ) == "second_spell_each_turn"


def test_second_spell_each_turn_end_to_end():
    # End-to-end Illvoi Operative oracle text — entirely one line of
    # the form ``Whenever <condition>, <effect>.``. The condition
    # resolves to ``second_spell_each_turn``; the effect resolves
    # via the existing unified effect grammar's
    # ``put a +1/+1 counter on this creature`` rule.
    parsed = _parse_triggered_ability_line(
        "Whenever you cast your second spell each turn, "
        "put a +1/+1 counter on this creature."
    )
    assert parsed == TriggeredAbility(
        trigger="second_spell_each_turn",
        effect=PutPlusOneCounterOnSelf(amount=1),
    )


# ---------- you sacrifice another creature or artifact ----------

def test_parse_trigger_phrase_recognizes_sacrifice_creature_or_artifact():
    # Lightless Evangel's oracle uses the verbatim phrase
    # ``you sacrifice another creature or artifact``. The engine key
    # is ``sacrifice_creature_or_artifact`` (the ``another`` vs ``a``
    # distinction collapses engine-side because the source must
    # still be on the battlefield to trigger).
    assert _parse_trigger_phrase(
        "you sacrifice another creature or artifact"
    ) == "sacrifice_creature_or_artifact"


def test_sacrifice_creature_or_artifact_end_to_end():
    # Lightless Evangel's full oracle text — one line.
    parsed = _parse_triggered_ability_line(
        "Whenever you sacrifice another creature or artifact, "
        "put a +1/+1 counter on this creature."
    )
    assert parsed == TriggeredAbility(
        trigger="sacrifice_creature_or_artifact",
        effect=PutPlusOneCounterOnSelf(amount=1),
    )


# ---------- a creature you control with a +1/+1 counter on it dies ----------

def test_parse_trigger_phrase_recognizes_counter_creature_dies():
    # Meltstrider Eulogist's oracle uses ``a creature you control with
    # a +1/+1 counter on it dies``. Phase 4 migrated this phrase to the
    # predicate-style path: ``(Event.DIES, IsCreature() & Controlled(
    # YOU) & HasCounter("+1/+1"))``. The legacy lookup must therefore
    # return ``None``.
    assert _parse_trigger_phrase(
        "a creature you control with a +1/+1 counter on it dies"
    ) is None
    assert _parse_predicate_trigger_phrase(
        "a creature you control with a +1/+1 counter on it dies"
    ) == (Event.DIES, _COUNTER_DIES_PRED)


def test_counter_creature_dies_end_to_end():
    # Meltstrider Eulogist's full oracle text — one line that composes
    # the new predicate-style condition with the existing
    # ``draw a card`` effect.
    parsed = _parse_triggered_ability_line(
        "Whenever a creature you control with a +1/+1 counter on it dies, "
        "draw a card."
    )
    assert parsed == TriggeredAbility(
        event=Event.DIES, predicate=_COUNTER_DIES_PRED,
        effect=DrawCards(amount=1),
    )


# ---------- Negative: unknown phrase returns None ----------

def test_unknown_trigger_phrase_returns_none():
    # A condition phrase the dictionary doesn't recognize must yield
    # ``None`` so the enclosing card is skipped end-to-end rather
    # than silently misclaimed with a bogus trigger key.
    assert _parse_trigger_phrase("you blink an enchantment") is None


def test_unknown_trigger_phrase_in_line_returns_none():
    # End-to-end version: a malformed/unsupported condition inside an
    # otherwise well-shaped triggered-ability line still propagates as
    # ``None`` from ``_parse_triggered_ability_line``.
    assert _parse_triggered_ability_line(
        "Whenever you blink an enchantment, draw a card."
    ) is None


# ---------- End-to-end claim parity for newly-supported cards ----------

def test_illvoi_operative_is_claimed_with_second_spell_trigger():
    """Illvoi Operative's oracle text is exactly one triggered ability
    using the new ``second_spell_each_turn`` condition phrase. With
    the phrase mapped, the parser must claim the card end-to-end and
    produce a printing identical to the static registry's.
    """
    from mtg_bot.cards.parser_source import OracleParserCardSource
    from mtg_bot.cards.source import StaticCardSource

    parser = OracleParserCardSource()
    static = StaticCardSource().get_printings()

    assert "Illvoi Operative" in parser.claimed_names
    parsed = parser.get_printings()["Illvoi Operative"]
    assert parsed == static["Illvoi Operative"]
    assert parsed.triggered_abilities == (
        TriggeredAbility(
            trigger="second_spell_each_turn",
            effect=PutPlusOneCounterOnSelf(amount=1),
        ),
    )


def test_lightless_evangel_is_claimed_with_sacrifice_trigger():
    """Lightless Evangel's oracle text is one triggered ability using
    the new ``sacrifice_creature_or_artifact`` condition phrase.
    """
    from mtg_bot.cards.parser_source import OracleParserCardSource
    from mtg_bot.cards.source import StaticCardSource

    parser = OracleParserCardSource()
    static = StaticCardSource().get_printings()

    assert "Lightless Evangel" in parser.claimed_names
    parsed = parser.get_printings()["Lightless Evangel"]
    assert parsed == static["Lightless Evangel"]
    assert parsed.triggered_abilities == (
        TriggeredAbility(
            trigger="sacrifice_creature_or_artifact",
            effect=PutPlusOneCounterOnSelf(amount=1),
        ),
    )


def test_meltstrider_eulogist_is_claimed_with_counter_dies_trigger():
    """Meltstrider Eulogist's oracle text is one triggered ability
    using the new ``creature_you_control_with_counter_dies``
    condition phrase.
    """
    from mtg_bot.cards.parser_source import OracleParserCardSource
    from mtg_bot.cards.source import StaticCardSource

    parser = OracleParserCardSource()
    static = StaticCardSource().get_printings()

    assert "Meltstrider Eulogist" in parser.claimed_names
    parsed = parser.get_printings()["Meltstrider Eulogist"]
    assert parsed == static["Meltstrider Eulogist"]
    assert parsed.triggered_abilities == (
        TriggeredAbility(
            event=Event.DIES, predicate=_COUNTER_DIES_PRED,
            effect=DrawCards(amount=1),
        ),
    )
