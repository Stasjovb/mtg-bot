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


# A Target is a (kind, id) pair. ``kind`` is one of:
#   "player"   — id is a Player.id
#   "creature" — id is a GameObject.id of a creature on the battlefield
Target = tuple[str, int]


class Effect:
    """Base class for ability effects.

    Untargeted effects override ``resolve``; targeted effects also override
    ``requires_target`` + ``legal_targets``. ``resolve`` receives a tuple of
    chosen targets (empty for untargeted effects).
    """

    def requires_target(self) -> bool:
        """Whether this effect needs at least one chosen target to resolve."""
        return False

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        """Enumerate legal targets. Empty list means no targets are needed."""
        return []

    def resolve(
        self, state: "GameState", controller_id: int, targets: tuple[Target, ...] = ()
    ) -> None:
        raise NotImplementedError

    def describe(self) -> str:
        raise NotImplementedError


@dataclass(frozen=True)
class GainLife(Effect):
    amount: int

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
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

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import draw_card

        for _ in range(self.amount):
            draw_card(state, controller_id)
        state.log.append(f"P{controller_id} draws {self.amount} card(s)")

    def describe(self) -> str:
        if self.amount == 1:
            return "you draw a card"
        return f"you draw {self.amount} cards"


@dataclass(frozen=True)
class EachPlayerDraws(Effect):
    amount: int

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import draw_card

        for i in range(len(state.players)):
            idx = (state.active_player_idx + i) % len(state.players)
            p = state.players[idx]
            if p.has_lost:
                continue
            for _ in range(self.amount):
                draw_card(state, p.id)
        state.log.append(
            f"each player draws {self.amount} card(s) "
            f"(from {state.players[controller_id].id}'s trigger)"
        )

    def describe(self) -> str:
        if self.amount == 1:
            return "each player draws a card"
        return f"each player draws {self.amount} cards"


@dataclass(frozen=True)
class TargetOpponentDiscards(Effect):
    """Target opponent discards ``count`` cards.

    The discarding player (the target) chooses which cards to discard — the
    target player's agent makes the pick via ``choose_discard``.
    """

    count: int = 1

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("player", p.id)
            for p in state.players
            if p.id != controller_id and not p.has_lost
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "player":
            return
        p = state.player_by_id(target_id)
        if p.has_lost:
            return
        for _ in range(self.count):
            if not p.hand:
                break
            hand_ids = [c.id for c in p.hand]
            chosen_id = p.agent.choose_discard(state, p.id, hand_ids)
            card = next(c for c in p.hand if c.id == chosen_id)
            p.hand.remove(card)
            card.zone = Zone.GRAVEYARD
            p.graveyard.append(card)
            state.log.append(
                f"P{target_id} discards {card.printing.name}"
            )

    def describe(self) -> str:
        if self.count == 1:
            return "target opponent discards a card"
        return f"target opponent discards {self.count} cards"


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
