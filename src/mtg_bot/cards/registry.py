"""Card-pool aggregation and deck-building helpers.

Pulls every registry module together into ``all_printings`` and
``NONLAND_POOL``, and exposes the mono-color deck builder used by
``simulate.setup_game``.
"""

from __future__ import annotations

import random

from mtg_bot.cards.base import CardPrinting
from mtg_bot.cards.eoe_creatures import EOE_CREATURES
from mtg_bot.cards.eoe_spells import EOE_SPELLS
from mtg_bot.cards.lands import (
    BASIC_LANDS, PLANET_LANDS, SHOCK_LANDS, UTILITY_LANDS,
)
from mtg_bot.cards.stellar_sights import STELLAR_SIGHTS_LANDS
from mtg_bot.cards.synthetic import SYNTHETIC_CREATURES


_COLOR_TO_BASIC: dict[str, str] = {
    "W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest",
}


# Everything non-land that's playable — creatures + instants + sorceries.
# Drawn into decks, castable from hand.
NONLAND_POOL: dict[str, CardPrinting] = {
    **SYNTHETIC_CREATURES, **EOE_CREATURES, **EOE_SPELLS,
}
# Back-compat alias — some tests and the deck builder still reference the
# creature-only name. Kept so that the existing test signatures don't need
# to change; new code should read NONLAND_POOL.
CREATURE_POOL: dict[str, CardPrinting] = NONLAND_POOL


def all_printings() -> dict[str, CardPrinting]:
    return {
        **BASIC_LANDS,
        **SHOCK_LANDS,
        **UTILITY_LANDS,
        **PLANET_LANDS,
        **STELLAR_SIGHTS_LANDS,
        **NONLAND_POOL,
    }


def build_mono_color_deck(color: str, seed: int | None = None) -> list[str]:
    """60 cards: 24 basics of the chosen color + 36 non-land cards in that color.

    "In that color" includes colorless cards (empty ``mana_cost.colors``) since
    colorless generic costs can be paid from any basic land.
    """
    if color not in _COLOR_TO_BASIC:
        raise ValueError(f"unknown color: {color}")
    rng = random.Random(seed)
    land_name = _COLOR_TO_BASIC[color]
    creatures = [
        name
        for name, p in NONLAND_POOL.items()
        if color in p.mana_cost.colors or not p.mana_cost.colors
    ]
    if not creatures:
        raise ValueError(f"no creatures in color {color}")
    deck: list[str] = [creatures[i % len(creatures)] for i in range(36)]
    deck.extend([land_name] * 24)
    rng.shuffle(deck)
    return deck
