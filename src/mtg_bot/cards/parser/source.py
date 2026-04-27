"""``OracleParserCardSource`` — top-level card source backed by the
oracle-text parser.

Walks ``data/edge_of_eternities.json`` once at construction, asks each
of the per-card-type builders to attempt a printing, and stores every
success in a name-keyed dict. The parser's "claimed_names" property
lists exactly which cards the parser handles end-to-end today; the
structural-parity gate in ``tests/test_parser_parity.py`` runs against
every name in that tuple.
"""

from __future__ import annotations

import json
from pathlib import Path

from mtg_bot.cards.base import CardPrinting
from mtg_bot.cards.parser.creature_builder import _build_creature_printing
from mtg_bot.cards.parser.equipment_builder import _build_equipment_printing
from mtg_bot.cards.parser.land_builder import _build_land_printing
from mtg_bot.cards.parser.spell_builder import _build_spell_printing


_DATA_PATH = (
    Path(__file__).resolve().parents[4] / "data" / "edge_of_eternities.json"
)


def _load_scryfall_data() -> list[dict]:
    with _DATA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


class OracleParserCardSource:
    def __init__(self) -> None:
        printings: dict[str, CardPrinting] = {}
        for card in _load_scryfall_data():
            built = _build_creature_printing(card)
            if built is None:
                built = _build_spell_printing(card)
            if built is None:
                built = _build_land_printing(card)
            if built is None:
                built = _build_equipment_printing(card)
            if built is not None:
                printings[card["name"]] = built
        self._printings = printings

    @property
    def claimed_names(self) -> tuple[str, ...]:
        return tuple(self._printings)

    def get_printings(self) -> dict[str, CardPrinting]:
        return dict(self._printings)

    def build_mono_color_deck(
        self, color: str, seed: int | None = None
    ) -> list[str]:
        raise NotImplementedError(
            "parser source does not yet implement deck building; "
            "implement once it claims a deckable pool"
        )
