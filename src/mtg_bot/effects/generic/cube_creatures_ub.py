"""Engine effects for the PowerLSV cube's blue / black creatures.

Each class models one printed effect shape (not one card); the parser
side lives in :mod:`mtg_bot.cards.parser.cube_creatures_ub`.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mtg_bot.effects.base import Effect, Target

if TYPE_CHECKING:
    from mtg_bot.game import GameState


# ---------------------------------------------------------------------------
# Event-bound anaphora ("they", "that player")
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BindEventPlayer(Effect):
    """Resolve ``inner`` against the player named by the triggering
    event's ``slot`` subject -- the "they" of "Whenever an opponent
    draws a card, they lose 2 life." The player is fixed when the
    trigger fires (``dispatch_event``'s ``targets_from_event`` hook), not
    targeted, so the ability never prompts and can't fizzle for lack of
    a target.
    """

    inner: Effect
    slot: str = "player"

    def targets_from_event(self, state: "GameState", subjects) -> tuple:
        player = subjects.get(self.slot)
        if player is None:
            return ()
        return (("player", player.id),)

    def requires_target(self) -> bool:
        return False

    def legal_targets(self, state, controller_id):
        return []

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        self.inner.resolve(state, controller_id, targets)

    def describe(self) -> str:
        return self.inner.describe()


# ---------------------------------------------------------------------------
# Amass (CR 701.44)
# ---------------------------------------------------------------------------


def _army_token_printing(subtype: str):
    from mtg_bot.cards.base import make_token_creature

    return make_token_creature(
        f"{subtype} Army", 0, 0, subtypes=(subtype, "Army"), colors={"B"},
    )


@dataclass(frozen=True)
class Amass(Effect):
    """``amass <Subtype> N`` (CR 701.44a): if you don't control an Army
    creature, create a 0/0 black <Subtype> Army creature token; choose
    an Army creature you control, put N +1/+1 counters on it, and if it
    isn't a <Subtype> it becomes one in addition to its other types."""

    subtype: str
    amount: int = 1

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import add_plus_one_counters, is_creature_now

        def armies():
            return [
                o for o in state.battlefield
                if o.controller_id == controller_id
                and is_creature_now(o)
                and "Army" in o.printing.subtypes
            ]

        if not armies():
            from mtg_bot.effects.generic.tokens import CreateToken

            CreateToken(
                token_printing=_army_token_printing(self.subtype),
            ).resolve(state, controller_id, ())
        pool = armies()
        if not pool:
            return
        army = pool[0]
        p = state.player_by_id(controller_id)
        if len(pool) > 1 and p.agent is not None:
            pick = p.agent.choose_target(
                state, controller_id, [("creature", o.id) for o in pool],
            )
            if pick is not None:
                army = next((o for o in pool if o.id == pick[1]), army)
        add_plus_one_counters(state, army, self.amount)
        if self.subtype not in army.printing.subtypes:
            army.printing = dataclasses.replace(
                army.printing,
                subtypes=army.printing.subtypes + (self.subtype,),
            )
        state.log.append(
            f"P{controller_id} amasses {self.subtype} {self.amount} "
            f"({army.printing.name})"
        )

    def describe(self) -> str:
        return f"amass {self.subtype}s {self.amount}"


# ---------------------------------------------------------------------------
# Self-referential riders
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TapSelf(Effect):
    """"Tap it." where "it" is the ability's own source (Iron-Shield
    Elf's "This creature gains indestructible until end of turn. Tap
    it."). No-op when the source has left the battlefield."""

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import tap_permanent

        src = state.resolving_source
        if src is None or src not in state.battlefield:
            return
        tap_permanent(state, src)

    def describe(self) -> str:
        return "tap this creature"


# ---------------------------------------------------------------------------
# Library-top reveals
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RevealTopCardToHandLoseLifeEqualMV(Effect):
    """"Reveal the top card of your library and put that card into your
    hand. You lose life equal to its mana value." (Dark Confidant). An
    empty library reveals nothing and costs no life."""

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone

        p = state.player_by_id(controller_id)
        if not p.library:
            return
        card = p.library.pop(0)
        card.zone = Zone.HAND
        p.hand.append(card)
        card.publicly_known_to = frozenset(pl.id for pl in state.players)
        mv = card.printing.mana_cost.total
        p.life -= mv
        state.log.append(
            f"P{controller_id} reveals {card.printing.name} and puts it "
            f"into their hand, losing {mv} life (now {p.life})"
        )

    def describe(self) -> str:
        return (
            "reveal the top card of your library and put it into your "
            "hand; you lose life equal to its mana value"
        )


__all__ = [
    "RevealTopCardToHandLoseLifeEqualMV",
    "TapSelf",
    "Amass",
    "BindEventPlayer",
]
