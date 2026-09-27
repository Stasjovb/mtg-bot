"""``OracleParserCardSource`` — top-level card source backed by the
oracle-text parser.

Walks the active card pool (see ``mtg_bot.cards.pools`` — the
``MTG_BOT_CARD_POOL`` env var picks ``all`` / ``cube`` / ``eoe``) once
at construction, asks each of the per-card-type builders to attempt a
printing, and stores every success in a name-keyed dict. The parser's "claimed_names" property
lists exactly which cards the parser handles end-to-end today; the
structural-parity gate in ``tests/test_parser_parity.py`` runs against
every name in that tuple.
"""

from __future__ import annotations

from mtg_bot.cards.base import CardPrinting
from mtg_bot.cards.pools import load_pool_cards, resolve_pool_name, active_pool_name
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


def _load_scryfall_data(pool: str | None = None) -> list[dict]:
    """Raw Scryfall records for ``pool`` (``None`` -> env-selected)."""
    return load_pool_cards(pool)


class OracleParserCardSource:
    def __init__(self, pool: str | None = None) -> None:
        self._pool_name = (
            resolve_pool_name(pool) if pool is not None else active_pool_name()
        )
        printings: dict[str, CardPrinting] = {}
        for card in _load_scryfall_data(self._pool_name):
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
    def pool_name(self) -> str:
        """Which registered pool this source was built from."""
        return self._pool_name

    @property
    def claimed_names(self) -> tuple[str, ...]:
        return tuple(self._printings)

    def get_printings(self) -> dict[str, CardPrinting]:
        return dict(self._printings)
