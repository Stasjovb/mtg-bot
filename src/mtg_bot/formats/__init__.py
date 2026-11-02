"""Game formats (``GameState.game_format``).

- ``STANDARD``: the engine's normal two-player game (the default).
- ``FORGETFUL_FISH``: shared library + shared graveyard
  (``mtg_bot.formats.forgetful_fish``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mtg_bot.formats.base import STANDARD, GameFormat
from mtg_bot.formats.forgetful_fish import FORGETFUL_FISH

if TYPE_CHECKING:
    from mtg_bot.game import GameState

FORMATS: dict[str, GameFormat] = {
    f.name: f for f in (STANDARD, FORGETFUL_FISH)
}


def get_format(name: str) -> GameFormat:
    try:
        return FORMATS[name]
    except KeyError:
        raise ValueError(
            f"unknown game format {name!r}; known: {sorted(FORMATS)}"
        ) from None


def apply_hand_ownership(state: "GameState") -> None:
    """Under ``holder_owns_hand_cards``, make every card in a hand owned by
    that hand's player. A no-op for every other format."""
    if not state.game_format.holder_owns_hand_cards:
        return
    for p in state.players:
        for card in p.hand:
            if card.owner_id != p.id:
                card.owner_id = p.id
                card.controller_id = p.id


__all__ = [
    "FORGETFUL_FISH",
    "FORMATS",
    "STANDARD",
    "GameFormat",
    "apply_hand_ownership",
    "get_format",
]
