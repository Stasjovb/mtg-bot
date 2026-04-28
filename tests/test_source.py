"""Tests for the pluggable card-source seam."""

from __future__ import annotations

import pytest

from mtg_bot.cards.parser_source import OracleParserCardSource
from mtg_bot.cards.source import (
    CardSource,
    card_source_from_env,
    get_active_source,
    set_active_source,
)


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


def test_card_source_from_env_default_is_parser():
    assert isinstance(card_source_from_env(None), OracleParserCardSource)
    assert isinstance(card_source_from_env(""), OracleParserCardSource)
    assert isinstance(card_source_from_env("parser"), OracleParserCardSource)
    assert isinstance(card_source_from_env("PARSER"), OracleParserCardSource)


def test_card_source_from_env_unknown_value_raises():
    with pytest.raises(ValueError, match="unknown MTG_BOT_CARD_SOURCE"):
        card_source_from_env("nonsense")
