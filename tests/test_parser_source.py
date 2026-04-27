"""Tests for the stub parser card source.

The stub is throwaway; these tests verify only its placeholder
contract — that it claims something, returns only what it claims,
and refuses to build decks. The real parser will replace it and
its tests will be much more substantive.
"""

from __future__ import annotations

import pytest

from mtg_bot.cards.parser_source import StubParserCardSource


def test_claimed_names_is_nonempty():
    assert len(StubParserCardSource.claimed_names) > 0


def test_get_printings_returns_only_claimed_names():
    parser = StubParserCardSource()
    assert set(parser.get_printings()) == set(parser.claimed_names)


def test_build_mono_color_deck_raises():
    with pytest.raises(NotImplementedError):
        StubParserCardSource().build_mono_color_deck("G", seed=0)
