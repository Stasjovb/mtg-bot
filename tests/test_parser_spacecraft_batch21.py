"""Parity tests for spacecraft-batch21 bespoke dispatch entries.

Each test verifies that ``OracleParserCardSource`` returns a
``CardPrinting`` equal to the one in the static registry for a
spacecraft whose ETB effect is claimed via the ``_BESPOKE_SPACECRAFT``
name-keyed dispatch table rather than the general Station grammar.
"""

from __future__ import annotations

from mtg_bot.cards.parser_source import OracleParserCardSource

_PARSER_PRINTINGS = OracleParserCardSource().get_printings()










