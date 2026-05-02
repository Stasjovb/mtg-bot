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
import random
from pathlib import Path

from mtg_bot.cards.base import CardPrinting
from mtg_bot.cards.parser.artifact_builder import _build_artifact_printing
from mtg_bot.cards.parser.creature_builder import _build_creature_printing
from mtg_bot.cards.parser.equipment_builder import _build_equipment_printing
from mtg_bot.cards.parser.land_builder import _build_land_printing
from mtg_bot.cards.parser.spacecraft_builder import _build_spacecraft_printing
from mtg_bot.cards.parser.enchantment_builder import (
    _build_enchantment_printing,
)
from mtg_bot.cards.parser.room_builder import _build_room_printing
from mtg_bot.cards.parser.planeswalker_builder import (
    _build_planeswalker_printing,
)
from mtg_bot.cards.parser.spell_builder import _build_spell_printing


_DATA_DIR = Path(__file__).resolve().parents[4] / "data"
_DATA_PATHS: tuple[Path, ...] = (
    _DATA_DIR / "edge_of_eternities.json",
    _DATA_DIR / "stellar_sights.json",
    _DATA_DIR / "special_guests_eoe.json",
    _DATA_DIR / "duskmourn.json",
)


def _load_scryfall_data() -> list[dict]:
    cards: list[dict] = []
    for path in _DATA_PATHS:
        with path.open("r", encoding="utf-8") as f:
            cards.extend(json.load(f))
    return cards


class OracleParserCardSource:
    def __init__(self) -> None:
        printings: dict[str, CardPrinting] = {}
        for card in _load_scryfall_data():
            built = _build_room_printing(card)
            if built is None:
                built = _build_enchantment_printing(card)
            if built is None:
                built = _build_planeswalker_printing(card)
            if built is None:
                built = _build_creature_printing(card)
            if built is None:
                built = _build_spell_printing(card)
            if built is None:
                built = _build_land_printing(card)
            if built is None:
                built = _build_equipment_printing(card)
            if built is None:
                built = _build_spacecraft_printing(card)
            if built is None:
                built = _build_artifact_printing(card)
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
        """60 cards: 24 basics of the chosen color + 36 non-land cards in that
        color (or colorless, since colorless generic costs can be paid from any
        basic land). Drawn from the parser's claimed pool."""
        if color not in _COLOR_TO_BASIC:
            raise ValueError(f"unknown color: {color}")
        rng = random.Random(seed)
        land_name = _COLOR_TO_BASIC[color]
        candidates = [
            name
            for name, p in self._printings.items()
            if "Land" not in p.card_types
            and (color in p.mana_cost.colors or not p.mana_cost.colors)
        ]
        if not candidates:
            raise ValueError(f"no creatures in color {color}")
        deck: list[str] = [
            candidates[i % len(candidates)] for i in range(36)
        ]
        deck.extend([land_name] * 24)
        rng.shuffle(deck)
        return deck


_COLOR_TO_BASIC: dict[str, str] = {
    "W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest",
}
