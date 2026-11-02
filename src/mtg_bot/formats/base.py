"""``GameFormat``: the format-level rules a game is set up and played under.

A format is frozen data hung off ``GameState.game_format``. The engine
consults it only where a format changes the rules; ``STANDARD`` (the
default) reproduces the engine's normal two-player game exactly, so every
pre-format game is byte-identical.

Zone sharing (Forgetful Fish): when ``shared_library`` /
``shared_graveyard`` is set, every ``Player`` in the state holds the SAME
list object for that zone (player 0's). Everything that reads or writes
``player.library`` / ``player.graveyard`` -- draws, mills, "owner's
library", "your graveyard" -- then acts on the one shared zone with no
per-site change. ``GameState.clone`` keeps the aliasing. Code that walks
EVERY player's zone must visit a shared zone once:
``GameState.distinct_libraries`` / ``distinct_graveyards``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Optional

if TYPE_CHECKING:
    from mtg_bot.game import GameObject


@dataclass(frozen=True)
class GameFormat:
    name: str
    # Every player draws from / mills / tucks into one library.
    shared_library: bool = False
    # Every card that would go to a graveyard goes to one graveyard.
    shared_graveyard: bool = False
    starting_life: int = 20
    # A card in a player's hand is owned by that player (Forgetful Fish:
    # "a card is owned by the player who drew it / cast it"). Applied by
    # ``formats.apply_hand_ownership`` from the state-based-action loop
    # and on every draw.
    holder_owns_hand_cards: bool = False
    # ``(low, high)``: a mulligan is free (no card goes to the bottom)
    # when the hand has fewer than ``low`` or more than ``high`` lands.
    # ``None`` = the plain London mulligan.
    free_mulligan_land_bounds: Optional[tuple[int, int]] = None

    @property
    def shares_zones(self) -> bool:
        return self.shared_library or self.shared_graveyard

    def is_free_mulligan(self, hand: Iterable["GameObject"]) -> bool:
        """Whether mulliganing ``hand`` is free under this format."""
        if self.free_mulligan_land_bounds is None:
            return False
        low, high = self.free_mulligan_land_bounds
        lands = sum(1 for c in hand if c.printing.is_land)
        return lands < low or lands > high


STANDARD = GameFormat(name="standard")
