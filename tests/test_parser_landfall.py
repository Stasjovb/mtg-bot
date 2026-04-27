"""Tests for the Landfall keyword-prefix triggered-ability recognizer.

Covers the surface form ``Landfall — Whenever a land you control
enters, <effect>.`` — recognized by stripping the keyword-prefix
label before parsing the body through the normal triggered-ability
grammar. The resulting ``TriggeredAbility`` uses the engine's
``landfall`` trigger key (matching the static registry).
"""

from __future__ import annotations

from mtg_bot.cards.base import GainLife, TriggeredAbility
from mtg_bot.cards.parser.triggers import (
    _parse_triggered_ability_line,
    _strip_keyword_prefix,
)


# ---------- Happy path: Landfall-prefixed gain-life trigger ----------

def test_landfall_prefix_parses_to_landfall_trigger():
    parsed = _parse_triggered_ability_line(
        "Landfall — Whenever a land you control enters, "
        "you gain 1 life."
    )
    assert parsed == TriggeredAbility(
        trigger="landfall",
        effect=GainLife(amount=1),
    )


def test_landfall_prefix_uses_engine_landfall_trigger_key():
    parsed = _parse_triggered_ability_line(
        "Landfall — Whenever a land you control enters, "
        "you gain 1 life."
    )
    assert parsed is not None
    # The engine canonical trigger key is ``landfall``, not the inner
    # ``Whenever a land enters`` source phrase. ``eoe_creatures.py``
    # uses ``trigger="landfall"`` for every Landfall ability, so the
    # parser must agree.
    assert parsed.trigger == "landfall"


def test_landfall_prefix_extracts_effect_via_unified_grammar():
    # The effect side is parsed by the existing unified effect grammar
    # — varying the gain-life amount must flow through unchanged.
    parsed = _parse_triggered_ability_line(
        "Landfall — Whenever a land you control enters, "
        "you gain 3 life."
    )
    assert parsed == TriggeredAbility(
        trigger="landfall",
        effect=GainLife(amount=3),
    )


# ---------- Negative: malformed Landfall lines return None ----------

def test_landfall_prefix_with_unsupported_inner_effect_returns_none():
    # The inner effect ``you draw two cards`` is not a recognized
    # effect phrase (the unified grammar matches ``draw a card`` /
    # ``draw N cards``, not ``you draw …``). The Landfall prefix must
    # not paper over an unrecognized body — the line still returns
    # ``None`` so the enclosing card is skipped.
    parsed = _parse_triggered_ability_line(
        "Landfall — Whenever a land you control enters, "
        "you draw two cards."
    )
    assert parsed is None


def test_landfall_prefix_without_trigger_body_returns_none():
    # A bare ``Landfall — `` prefix with no ``Whenever …`` body is
    # malformed. After stripping the prefix the remainder doesn't match
    # the triggered-ability line pattern, so the parser returns
    # ``None`` and skips the card.
    parsed = _parse_triggered_ability_line(
        "Landfall — you gain 1 life."
    )
    assert parsed is None


# ---------- Negative: other keyword prefixes are not silently accepted

def test_other_keyword_prefix_not_silently_accepted_as_landfall():
    # Saga is not a recognized keyword prefix in this slice. The
    # ``Saga — `` label must NOT be stripped, so the line fails to
    # match the triggered-ability pattern (Saga chapters use ``I —``,
    # ``II —`` etc., not ``Whenever``) and the parser returns
    # ``None``. This guards against the recognizer over-generalizing
    # to ``<AnyKeyword> — <body>``.
    parsed = _parse_triggered_ability_line(
        "Saga — Whenever a land you control enters, "
        "you gain 1 life."
    )
    # Even if the body is itself a recognized triggered-ability line,
    # it would still be a bug to accept it under the wrong keyword
    # label — the resulting TriggeredAbility, if any, should not be
    # the result of silently treating Saga as Landfall.
    # Concretely: with the prefix not stripped, the entire line
    # ``Saga — Whenever …`` does not match the trigger-line regex.
    assert parsed is None


def test_magecraft_keyword_prefix_not_silently_accepted():
    # Magecraft is another keyword-prefix triggered ability that this
    # slice does NOT support. Its prefix must not be silently stripped.
    parsed = _parse_triggered_ability_line(
        "Magecraft — Whenever a land you control enters, "
        "you gain 1 life."
    )
    assert parsed is None


# ---------- _strip_keyword_prefix unit tests ----------

def test_strip_keyword_prefix_strips_landfall_label():
    stripped = _strip_keyword_prefix(
        "Landfall — Whenever a land you control enters, "
        "you gain 1 life."
    )
    assert stripped == (
        "Whenever a land you control enters, you gain 1 life."
    )


def test_strip_keyword_prefix_passes_through_unrecognized_keyword():
    line = (
        "Saga — Whenever a land you control enters, "
        "you gain 1 life."
    )
    assert _strip_keyword_prefix(line) == line


def test_strip_keyword_prefix_passes_through_plain_line():
    # Lines without any keyword-prefix label are returned unchanged.
    line = "When this creature enters, it deals 3 damage to any target."
    assert _strip_keyword_prefix(line) == line


# ---------- Bare condition (no prefix) is also recognized ----------

def test_bare_landfall_condition_still_parses():
    # The ``a land you control enters`` condition phrase maps directly
    # to the ``landfall`` trigger key. Even without the keyword-prefix
    # label, a line like ``Whenever a land you control enters, …``
    # parses to a landfall trigger. (Engine semantics are identical;
    # the prefix is reminder text.) No real EoE card uses this surface
    # form, but the recognizer is consistent with the unified
    # condition-phrase mechanism.
    parsed = _parse_triggered_ability_line(
        "Whenever a land you control enters, you gain 1 life."
    )
    assert parsed == TriggeredAbility(
        trigger="landfall",
        effect=GainLife(amount=1),
    )


# ---------- End-to-end: Eumidian Terrabotanist is claimed ----------

def test_eumidian_terrabotanist_is_claimed_with_landfall():
    """The only oracle text on Eumidian Terrabotanist is the Landfall
    gain-1-life trigger. With the prefix recognizer in place, the
    parser must claim it end-to-end and produce a printing identical
    to the static registry's. (The full per-card structural-parity
    check lives in ``test_parser_parity.py`` — this is a focused
    smoke test that the new recognizer wires up correctly.)
    """
    from mtg_bot.cards.parser_source import OracleParserCardSource
    from mtg_bot.cards.source import StaticCardSource

    parser = OracleParserCardSource()
    static = StaticCardSource().get_printings()

    assert "Eumidian Terrabotanist" in parser.claimed_names
    parsed = parser.get_printings()["Eumidian Terrabotanist"]
    assert parsed == static["Eumidian Terrabotanist"]
    assert parsed.triggered_abilities == (
        TriggeredAbility(trigger="landfall", effect=GainLife(amount=1)),
    )
