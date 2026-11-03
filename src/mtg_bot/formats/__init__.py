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


def setup_args_for_decks(deck_p0, deck_p1) -> tuple[list[list[str]], GameFormat]:
    """``(decks, game_format)`` for ``simulate.setup_game`` from two
    ``mtg_bot.decks.Deck`` objects of a deck pool (self-play / eval). A
    deck tagged ``game_format="forgetful_fish"`` is a shared library: both
    seats play it as ONE list (the first deck's), so a Fish pool needs
    every deck tagged alike; untagged decks are the normal two-deck game."""
    fmt0 = getattr(deck_p0, "game_format", None)
    fmt1 = getattr(deck_p1, "game_format", None)
    if fmt0 != fmt1:
        raise ValueError(f"decks of different formats: {fmt0!r} vs {fmt1!r}")
    game_format = get_format(fmt0) if fmt0 else STANDARD
    if game_format.shared_library:
        return [list(deck_p0.cards)], game_format
    return [list(deck_p0.cards), list(deck_p1.cards)], game_format


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
    "setup_args_for_decks",
]
