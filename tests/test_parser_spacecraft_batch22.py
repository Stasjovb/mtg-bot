"""Parity tests for spacecraft-batch22 bespoke dispatch entries.

Each test verifies that ``OracleParserCardSource`` returns a
``CardPrinting`` equal to the one in the static registry for a
spacecraft claimed via the ``_BESPOKE_SPACECRAFT`` name-keyed dispatch
table (batch 22 additions).
"""

from __future__ import annotations

from mtg_bot.cards.parser_source import OracleParserCardSource

_PARSER_PRINTINGS = OracleParserCardSource().get_printings()




























