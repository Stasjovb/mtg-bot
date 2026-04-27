"""Tests for the pluggable card-source seam."""

from __future__ import annotations

import pytest

from mtg_bot.cards.parser_source import StubParserCardSource
from mtg_bot.cards.registry import all_printings, build_mono_color_deck
from mtg_bot.cards.source import (
    CardSource,
    FallbackCardSource,
    StaticCardSource,
    card_source_from_env,
    get_active_source,
    set_active_source,
)


def test_static_source_get_printings_matches_registry():
    source = StaticCardSource()
    assert source.get_printings() == all_printings()


def test_static_source_build_mono_color_deck_matches_registry():
    source = StaticCardSource()
    for color in ("W", "U", "B", "R", "G"):
        assert source.build_mono_color_deck(color, seed=42) == \
            build_mono_color_deck(color, seed=42)


def test_static_source_build_mono_color_deck_rejects_unknown_color():
    source = StaticCardSource()
    with pytest.raises(ValueError):
        source.build_mono_color_deck("Z")


def test_set_active_source_swaps_and_reverts():
    """The swap function replaces the active source, and the original
    can be restored. This is the mechanism parity tests will use to
    point the engine at an alternative source."""

    class FakeSource:
        def get_printings(self):
            return {}

        def build_mono_color_deck(self, color, seed=None):
            return []

    original = get_active_source()
    fake = FakeSource()
    try:
        set_active_source(fake)
        assert get_active_source() is fake
    finally:
        set_active_source(original)
    assert get_active_source() is original


def test_card_source_protocol_is_runtime_compatible():
    """A class with the right shape satisfies the protocol structurally;
    no explicit ``CardSource`` subclassing required."""

    class Minimal:
        def get_printings(self):
            return {}

        def build_mono_color_deck(self, color, seed=None):
            return []

    source: CardSource = Minimal()
    assert source.get_printings() == {}
    assert source.build_mono_color_deck("G") == []


def test_fallback_returns_primary_for_claimed_names():
    primary = StubParserCardSource()
    composite = FallbackCardSource(primary, StaticCardSource())
    primary_printings = primary.get_printings()
    composite_printings = composite.get_printings()
    for name in primary.claimed_names:
        assert composite_printings[name] is primary_printings[name]


def test_fallback_returns_static_for_unclaimed_names():
    primary = StubParserCardSource()
    static = StaticCardSource()
    composite = FallbackCardSource(primary, static)
    composite_printings = composite.get_printings()
    static_printings = static.get_printings()
    unclaimed = next(
        n for n in static_printings if n not in primary.claimed_names
    )
    assert composite_printings[unclaimed] == static_printings[unclaimed]


def test_fallback_includes_every_static_name():
    composite = FallbackCardSource(
        StubParserCardSource(), StaticCardSource()
    )
    static_printings = StaticCardSource().get_printings()
    composite_printings = composite.get_printings()
    assert set(static_printings).issubset(composite_printings)


def test_fallback_delegates_deck_building_to_fallback():
    composite = FallbackCardSource(
        StubParserCardSource(), StaticCardSource()
    )
    static = StaticCardSource()
    assert composite.build_mono_color_deck("G", seed=7) == \
        static.build_mono_color_deck("G", seed=7)


def test_card_source_from_env_default_is_static():
    assert isinstance(card_source_from_env(None), StaticCardSource)
    assert isinstance(card_source_from_env(""), StaticCardSource)
    assert isinstance(card_source_from_env("static"), StaticCardSource)
    assert isinstance(card_source_from_env("STATIC"), StaticCardSource)


def test_card_source_from_env_parser_returns_stub():
    assert isinstance(card_source_from_env("parser"), StubParserCardSource)


def test_card_source_from_env_parser_with_fallback_returns_composite():
    source = card_source_from_env("parser_with_fallback")
    assert isinstance(source, FallbackCardSource)
    assert isinstance(source.primary, StubParserCardSource)
    assert isinstance(source.fallback, StaticCardSource)


def test_card_source_from_env_unknown_value_raises():
    with pytest.raises(ValueError, match="unknown MTG_BOT_CARD_SOURCE"):
        card_source_from_env("nonsense")
