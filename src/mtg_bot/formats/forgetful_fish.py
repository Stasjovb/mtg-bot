"""Forgetful Fish: two players share one library and one graveyard.

House rules used here (decided by the user, 2026-11-02):

- One shared library and one shared graveyard; the decklist is the shared
  library (``setup_game(decks=[shared_list], game_format=FORGETFUL_FISH)``).
- A mulligan is free (nothing goes to the bottom) when the hand has fewer
  than 2 or more than 5 lands; repeatable while that holds. Otherwise the
  normal London mulligan.
- A card is owned by the player who drew it / cast it: a card in a hand is
  owned by that hand's player, so a spell or permanent is owned by whoever
  cast or played it from their hand.
"""

from __future__ import annotations

from pathlib import Path

from mtg_bot.formats.base import GameFormat

FORGETFUL_FISH = GameFormat(
    name="forgetful_fish",
    shared_library=True,
    shared_graveyard=True,
    holder_owns_hand_cards=True,
    free_mulligan_land_bounds=(2, 5),
)

FISH_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "forgetful_fish"
# The real shared library, once the user's list is dropped in; until then
# the placeholder (cards the engine already plays).
DECKLIST_PATH = FISH_DATA_DIR / "decklist.txt"
PLACEHOLDER_DECKLIST_PATH = FISH_DATA_DIR / "placeholder_decklist.txt"


def default_decklist_path(data_dir: Path = FISH_DATA_DIR) -> Path:
    real = data_dir / DECKLIST_PATH.name
    return real if real.exists() else data_dir / PLACEHOLDER_DECKLIST_PATH.name


def default_decklist_text(data_dir: Path = FISH_DATA_DIR) -> str:
    return default_decklist_path(data_dir).read_text(encoding="utf-8")
