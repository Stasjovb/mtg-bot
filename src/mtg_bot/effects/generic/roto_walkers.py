"""Engine effects for the Vintage Roto P4 package: planeswalkers,
copies, control changes and turn structure.

Every effect is generic (parameterized by the printed shape), not
per-card; the parser side is ``cards/parser/roto_walkers.py`` and the
turn-structure rules live in ``mtg_bot.roto_turns``. Shortcuts are
documented in the "Vintage Roto P4" section of
``docs/SEARCH_LIMITATIONS.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mtg_bot.effects.base import Effect, Target

if TYPE_CHECKING:
    from mtg_bot.game import GameState


# ---------------------------------------------------------------------------
# Delayed "put that card into your hand" (Necropotence)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PutExiledSourceIntoOwnersHand(Effect):
    """The delayed half of "Exile <a card> ... Put that card into your
    hand at the beginning of your next end step.": the scheduled object
    (``state.resolving_source``) moves from its owner's exile to their
    hand -- only if it is still that exiled card (CR 400.7: a card that
    left exile in the meantime is a new object)."""

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone

        card = state.resolving_source
        if card is None or card.zone != Zone.EXILE:
            return
        owner = state.player_by_id(card.owner_id)
        if card not in owner.exile:
            return
        owner.exile.remove(card)
        card.zone = Zone.HAND
        owner.hand.append(card)
        state.log.append(
            f"P{owner.id} puts {card.printing.name} from exile into their hand"
        )

    def describe(self) -> str:
        return "put that card into your hand"


@dataclass(frozen=True)
class ExileTopCardsToHandAtYourNextEndStep(Effect):
    """"Exile the top <N> card(s) of your library[ face down]. Put that
    card / them into your hand at the beginning of your next end step."
    (Necropotence). Each exiled card gets its own delayed trigger
    (``roto_turns.schedule_at_your_next_end_step``) that returns it even
    if the source has left the battlefield. A face-down card is known
    to no one -- not even its owner -- until it reaches the hand."""

    count: int = 1
    face_down: bool = False

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone, reveal_to_all
        from mtg_bot.roto_turns import schedule_at_your_next_end_step

        p = state.player_by_id(controller_id)
        for _ in range(self.count):
            if not p.library:
                return
            card = p.library.pop(0)
            card.zone = Zone.EXILE
            state.player_by_id(card.owner_id).exile.append(card)
            if self.face_down:
                card.publicly_known_to = frozenset()
                shown = "a card face down"
            else:
                reveal_to_all(state, card)
                shown = card.printing.name
            schedule_at_your_next_end_step(
                state, controller_id, card.id, PutExiledSourceIntoOwnersHand(),
            )
            state.log.append(
                f"P{controller_id} exiles {shown} from the top of their "
                f"library until their next end step"
            )

    def describe(self) -> str:
        n = "the top card" if self.count == 1 else f"the top {self.count} cards"
        down = " face down" if self.face_down else ""
        return (
            f"exile {n} of your library{down}; put it into your hand at the "
            "beginning of your next end step"
        )


# ---------------------------------------------------------------------------
# Turn structure: end the turn, extra turns
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EndTheTurn(Effect):
    """"End the turn." (Sundial of the Infinite, Day's Undoing; CR 723):
    ``roto_turns.end_the_turn``."""

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.roto_turns import end_the_turn

        end_the_turn(state)

    def describe(self) -> str:
        return "end the turn"


@dataclass(frozen=True)
class LoseTheGame(Effect):
    """"You lose the game." (CR 104.3d: the effect makes the player lose
    at once; the next state-based-action check ends a two-player game)."""

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        p = state.player_by_id(controller_id)
        if p.has_lost:
            return
        p.has_lost = True
        p.lost_reason = "an effect made them lose the game"
        state.log.append(f"P{controller_id} loses the game")

    def describe(self) -> str:
        return "you lose the game"


@dataclass(frozen=True)
class TakeExtraTurnWithEndStepTrigger(Effect):
    """"Take an extra turn after this one. At the beginning of that
    turn's end step, <effect>." (Final Fortune).

    The extra turn joins ``state.extra_turn_queue`` exactly like
    ``TakeExtraTurnAfterThisOne`` (Nexus of Fate); the queue is consumed
    in order, one turn per entry, so "that turn" is turn number
    ``turn_number + <queue length after the append>``. A delayed
    end-step trigger for that turn number and the controller carries
    ``inner`` -- it never fires if that turn's end step is skipped
    (Sundial of the Infinite ends the turn first)."""

    inner: Effect

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        state.extra_turn_queue.append(controller_id)
        source = state.resolving_spell or state.resolving_source
        state.log.append(
            f"P{controller_id} is scheduled to take an extra turn"
        )
        if source is None:
            return
        state.delayed_triggers.append({
            "fire_at_turn": state.turn_number + len(state.extra_turn_queue),
            "controller_id": controller_id,
            "source_id": source.id,
            "effect": self.inner,
        })

    def describe(self) -> str:
        return (
            "take an extra turn after this one; at the beginning of that "
            f"turn's end step, {self.inner.describe()}"
        )


# ---------------------------------------------------------------------------
# Wish: "a card you own from outside the game" (CR 400.11)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PutCardFromOutsideTheGameIntoHand(Effect):
    """"You may reveal a <filter> card you own from outside the game and
    put it into your hand." (Burning Wish).

    The cards a player owns outside the game are their sideboard
    (``Player.sideboard``; the user's decision, 2026-10-02 -- in a roto
    draft, the drafter's unused picks). The controller picks one of the
    matching names (or nothing -- the reveal is optional) through the
    generic ``choose_mode`` hook; the chosen copy becomes a new object
    in their hand (``roto_turns.take_from_outside_the_game``)."""

    card_filter: object = None

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.roto_turns import take_from_outside_the_game

        p = state.player_by_id(controller_id)
        by_name: dict = {}
        for printing in p.sideboard:
            if self.card_filter is None or self.card_filter.matches(printing):
                by_name.setdefault(printing.name, printing)
        if not by_name or p.agent is None:
            state.log.append(
                f"P{controller_id} reveals nothing from outside the game"
            )
            return
        names = sorted(by_name)
        options = [f"reveal {n}" for n in names] + ["reveal nothing"]
        pick = p.agent.choose_mode(state, controller_id, options)
        if not 0 <= pick < len(names):
            state.log.append(
                f"P{controller_id} reveals nothing from outside the game"
            )
            return
        take_from_outside_the_game(state, controller_id, by_name[names[pick]])

    def describe(self) -> str:
        what = (
            self.card_filter.describe() if self.card_filter is not None
            else "card"
        )
        return (
            f"you may reveal a {what} you own from outside the game and put "
            "it into your hand"
        )
