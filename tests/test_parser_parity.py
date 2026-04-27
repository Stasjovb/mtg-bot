"""Structural per-card parity between the parser source and the
static registry.

Every name the parser claims must produce a ``CardPrinting``
identical to the one the static registry produces. Failure means
the parser has drifted from the canonical implementation and would
break the engine in subtle ways once swapped in.

Parametrized over the parser's ``claimed_names`` (computed at
import time), so each newly-claimed card gets its own test case
automatically as the parser grows.
"""

from __future__ import annotations

import pytest

from mtg_bot.cards.parser_source import OracleParserCardSource
from mtg_bot.cards.source import StaticCardSource

_PARSER = OracleParserCardSource()
_PARSER_PRINTINGS = _PARSER.get_printings()
_STATIC_PRINTINGS = StaticCardSource().get_printings()


@pytest.mark.parametrize("name", _PARSER.claimed_names)
def test_parser_card_matches_static(name):
    assert name in _PARSER_PRINTINGS, (
        f"parser claims {name!r} but did not return it in get_printings()"
    )
    assert name in _STATIC_PRINTINGS, (
        f"static registry has no entry for {name!r} "
        "— claimed_names is stale"
    )
    assert _PARSER_PRINTINGS[name] == _STATIC_PRINTINGS[name]
