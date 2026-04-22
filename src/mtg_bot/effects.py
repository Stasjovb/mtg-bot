"""Effects and triggered abilities.

An ``Effect`` is a small object attached to a ``TriggeredAbility`` that knows
how to mutate the game state when its ability resolves. Kept as frozen
dataclasses so they can live on frozen ``CardPrinting`` objects.

Stage 3 starts with untargeted effects only — gain life, draw cards, etc.
Targeted effects (discard, destroy target, ...) land in the next branch
once the target-selection layer exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mtg_bot.game import GameState


class Effect:
    """Base class for untargeted ability effects."""

    def resolve(self, state: "GameState", controller_id: int) -> None:
        raise NotImplementedError

    def describe(self) -> str:
        raise NotImplementedError


@dataclass(frozen=True)
class GainLife(Effect):
    amount: int

    def resolve(self, state: "GameState", controller_id: int) -> None:
        p = state.player_by_id(controller_id)
        p.life += self.amount
        state.log.append(
            f"P{controller_id} gains {self.amount} life (life: {p.life})"
        )

    def describe(self) -> str:
        return f"you gain {self.amount} life"


@dataclass(frozen=True)
class DrawCards(Effect):
    amount: int

    def resolve(self, state: "GameState", controller_id: int) -> None:
        from mtg_bot.turn import draw_card

        for _ in range(self.amount):
            draw_card(state, controller_id)
        state.log.append(f"P{controller_id} draws {self.amount} card(s)")

    def describe(self) -> str:
        if self.amount == 1:
            return "you draw a card"
        return f"you draw {self.amount} cards"


@dataclass(frozen=True)
class TriggeredAbility:
    """An ability that fires on a specific event.

    Stage 3 only supports ``trigger == "etb"`` (enters the battlefield).
    """

    trigger: str
    effect: Effect

    def describe(self) -> str:
        prefix = {
            "etb": "When ~ enters the battlefield",
        }.get(self.trigger, self.trigger)
        return f"{prefix}, {self.effect.describe()}."
