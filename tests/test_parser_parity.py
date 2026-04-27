"""Structural per-card parity between the parser source and the
static registry.

Every name the parser claims must produce a ``CardPrinting``
identical to the one the static registry produces. Failure means
the parser has drifted from the canonical implementation and would
break the engine in subtle ways once swapped in.

Parametrized over ``StubParserCardSource.claimed_names`` so each
new card the parser claims gets its own test case automatically.
"""

from __future__ import annotations

import pytest

from mtg_bot.cards.parser_source import StubParserCardSource
from mtg_bot.cards.source import StaticCardSource


@pytest.mark.parametrize("name", StubParserCardSource.claimed_names)
def test_parser_card_matches_static(name):
    parser_printings = StubParserCardSource().get_printings()
    static_printings = StaticCardSource().get_printings()
    assert name in parser_printings, (
        f"parser claims {name!r} but did not return it in get_printings()"
    )
    assert name in static_printings, (
        f"static registry has no entry for {name!r} — claimed_names is stale"
    )
    assert parser_printings[name] == static_printings[name]
