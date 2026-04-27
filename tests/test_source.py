"""Tests for the pluggable card-source seam."""

from __future__ import annotations

import pytest

from mtg_bot.cards.registry import all_printings, build_mono_color_deck
from mtg_bot.cards.source import (
    CardSource,
    StaticCardSource,
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


def test_default_active_source_is_static():
    assert isinstance(get_active_source(), StaticCardSource)


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
