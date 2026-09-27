"""Effects for the cube W/G creature bucket.

Each class models one printed effect shape claimed by
:mod:`mtg_bot.cards.parser.creature_wg_effects`; the docstrings name the
cards that print it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mtg_bot.effects.base import Effect, Target

if TYPE_CHECKING:
    from mtg_bot.game import GameState


def _living_players(state: "GameState") -> list[Target]:
    return [("player", p.id) for p in state.players if not p.has_lost]


def _chosen_player(state: "GameState", targets):
    """The still-legal target player (``None`` when absent / lost)."""
    for kind, pid in targets:
        if kind == "player":
            p = state.player_by_id(pid)
            return None if p.has_lost else p
    return None


@dataclass(frozen=True)
class TargetPlayerPutsGraveyardOnBottomRandom(Effect):
    """"[Up to one] target player puts all the cards from their graveyard
    on the bottom of their library in a random order." (Endurance.)"""

    up_to_one: bool = True

    def requires_target(self) -> bool:
        return not self.up_to_one

    def target_count_range(self) -> tuple[int, int]:
        return (0 if self.up_to_one else 1, 1)

    def legal_targets(self, state, controller_id):
        return _living_players(state)

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.game import Zone, reset_public_knowledge

        p = _chosen_player(state, targets)
        if p is None:
            return
        cards = list(p.graveyard)
        p.graveyard.clear()
        state.rng.shuffle(cards)
        for c in cards:
            c.zone = Zone.LIBRARY
            reset_public_knowledge(c)
            p.library.append(c)
        state.log.append(
            f"P{p.id} puts {len(cards)} graveyard card(s) on the bottom of "
            f"their library"
        )

    def describe(self) -> str:
        who = "up to one target player" if self.up_to_one else "target player"
        return (
            f"{who} puts all the cards from their graveyard on the bottom of "
            f"their library in a random order"
        )
