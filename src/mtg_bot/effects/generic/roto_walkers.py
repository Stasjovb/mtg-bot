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


# ---------------------------------------------------------------------------
# Planeswalker costs and keywords
# ---------------------------------------------------------------------------


def choose_and_pay_loyalty_x(
    state: "GameState", player_id: int, source,
) -> int:
    """A "-X" loyalty cost: the activator chooses X (0 up to the
    walker's loyalty -- they can't remove counters it doesn't have)
    through ``choose_x`` and X loyalty counters are removed. Returns X,
    which rides the stack item as ``state.resolving_x_value``."""
    upper = max(0, source.loyalty_counters)
    p = state.player_by_id(player_id)
    x = 0
    if p.agent is not None:
        x = p.agent.choose_x(state, player_id, source.printing.name, upper)
    x = min(max(0, x), upper)
    source.loyalty_counters -= x
    state.log.append(
        f"P{player_id} pays X={x} loyalty ({source.printing.name} now at "
        f"{source.loyalty_counters})"
    )
    return x


def apply_compleated(state: "GameState", obj) -> None:
    """Compleated (CR 702.150a): a permanent with compleated whose
    Phyrexian mana symbols were paid with life enters with two fewer
    loyalty counters for each such symbol. The count is the cast
    pipeline's ``GameObject.phyrexian_life_pips``; it is consumed here."""
    pips, obj.phyrexian_life_pips = obj.phyrexian_life_pips, 0
    if "compleated" not in obj.printing.keywords or pips <= 0:
        return
    obj.loyalty_counters = max(0, obj.loyalty_counters - 2 * pips)
    state.log.append(
        f"{obj.printing.name} enters with {2 * pips} fewer loyalty counters "
        "(compleated)"
    )


# ---------------------------------------------------------------------------
# Loyalty-ability effects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EachPlayerDiscards(Effect):
    """"Each player discards <N> card(s)." (Liliana of the Veil's +1).
    In APNAP order each player picks their own discard
    (``choose_discard``) through the discard-observer funnel
    (``card_flow.discard_card``)."""

    count: int = 1

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.effects.generic.card_flow import discard_card

        n = len(state.players)
        for i in range(n):
            p = state.players[(state.active_player_idx + i) % n]
            if p.has_lost:
                continue
            for _ in range(self.count):
                if not p.hand:
                    break
                ids = [c.id for c in p.hand]
                pick = ids[0]
                if p.agent is not None:
                    pick = p.agent.choose_discard(state, p.id, ids)
                card = next((c for c in p.hand if c.id == pick), p.hand[0])
                discard_card(state, p, card)

    def describe(self) -> str:
        n = "a card" if self.count == 1 else f"{self.count} cards"
        return f"each player discards {n}"


@dataclass(frozen=True)
class PutUpToNCardsFromHandOntoBattlefield(Effect):
    """"Put up to <N> <filter> cards from your hand onto the battlefield."
    (Ugin, the Spirit Dragon's -10). The controller picks the cards one
    at a time (``choose_card_from_library``; ``None`` stops), then they
    enter one after another."""

    count: int = 1
    card_filter: object = None

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.actions import put_into_battlefield

        p = state.player_by_id(controller_id)
        chosen: list = []
        while len(chosen) < self.count and p.agent is not None:
            options = [
                c for c in p.hand
                if c not in chosen and self.card_filter.matches(c.printing)
            ]
            if not options:
                break
            pick = p.agent.choose_card_from_library(
                state, controller_id, [c.id for c in options],
            )
            card = next((c for c in options if c.id == pick), None)
            if card is None:
                break
            chosen.append(card)
        for card in chosen:
            p.hand.remove(card)
            state.log.append(
                f"P{controller_id} puts {card.printing.name} onto the "
                "battlefield"
            )
            put_into_battlefield(state, card, controller_id)

    def describe(self) -> str:
        return (
            f"put up to {self.count} {self.card_filter.describe()}s from your "
            "hand onto the battlefield"
        )


@dataclass(frozen=True)
class SeparatePermanentsIntoPilesSacrificeChosen(Effect):
    """"Separate all permanents target player controls into two piles.
    That player sacrifices all permanents in the pile of their choice."
    (Liliana of the Veil's -6). The controller sorts the permanents
    (one ``choose_yes_no`` per permanent: yes = pile 1); the target
    player then picks the pile to sacrifice through ``choose_mode``."""

    def requires_target(self) -> bool:
        return True

    def legal_targets(self, state, controller_id):
        return [("player", p.id) for p in state.players if not p.has_lost]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import sacrifice

        pid = next((t[1] for t in targets if t[0] == "player"), None)
        if pid is None:
            return
        victim = state.player_by_id(pid)
        if victim.has_lost:
            return
        me = state.player_by_id(controller_id)
        perms = sorted(
            (o for o in state.battlefield if o.controller_id == pid),
            key=lambda o: o.id,
        )
        piles: tuple[list, list] = ([], [])
        for o in perms:
            first = True
            if me.agent is not None:
                first = me.agent.choose_yes_no(
                    state, controller_id,
                    f"Put {o.printing.name} into pile 1 (else pile 2)?",
                )
            piles[0 if first else 1].append(o)
        options = [
            f"sacrifice pile {i + 1}: "
            + (", ".join(o.printing.name for o in pile) or "nothing")
            for i, pile in enumerate(piles)
        ]
        pick = 0
        if victim.agent is not None:
            pick = victim.agent.choose_mode(state, pid, options)
        chosen = 1 if pick == 1 else 0
        doomed = piles[chosen]
        state.log.append(
            f"P{pid} sacrifices pile {chosen + 1} ({len(doomed)} permanent(s))"
        )
        for o in doomed:
            if o in state.battlefield:
                sacrifice(state, o)

    def describe(self) -> str:
        return (
            "separate all permanents target player controls into two piles; "
            "that player sacrifices the pile of their choice"
        )


@dataclass(frozen=True)
class MillTargetPlayerTimesX(Effect):
    """"Target player mills <K> times X cards." (Jace, the Perfected
    Mind's -X): ``MillTargetPlayer`` with ``K * X`` cards, X being the
    resolving ability's X."""

    per_x: int = 1

    def requires_target(self) -> bool:
        return True

    def legal_targets(self, state, controller_id):
        return [("player", p.id) for p in state.players if not p.has_lost]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.effects.generic.draw_mill import MillTargetPlayer

        n = self.per_x * max(0, state.resolving_x_value)
        MillTargetPlayer(amount=n).resolve(state, controller_id, targets)

    def describe(self) -> str:
        k = "" if self.per_x == 1 else f"{self.per_x} times "
        return f"target player mills {k}X cards"


@dataclass(frozen=True)
class AnyGraveyardHasAtLeast:
    """"if a graveyard has <N> or more cards in it" -- any player's
    graveyard (Jace, the Perfected Mind's -2)."""

    n: int = 1

    def matches(self, state, viewer_id, chosen_targets=None) -> bool:
        return any(len(p.graveyard) >= self.n for p in state.players)


# ---------------------------------------------------------------------------
# Control changes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExchangeControlOfSourceAndTarget(Effect):
    """"Exchange control of this <permanent> and [up to one ]target <np>.
    If you don't or can't make an exchange, sacrifice this <permanent>.
    [This ability still resolves if its target becomes illegal.]"
    (Gilded Drake).

    The exchange happens only if the source is still on the battlefield
    and the target is still legal with a different controller (CR
    701.10); it sets ``controller_id`` directly and leaves both
    permanents summoning-sick for their new controllers (the Oko
    precedent, ``cube_glue.ExchangeControlOfTargets``). Otherwise the
    source is sacrificed. ``still_resolves_if_targets_illegal`` lifts the
    CR 608.2b fizzle (``actions._resolve_top_of_stack_item``) so an
    illegal target still leads to the sacrifice."""

    targets: tuple = ()
    still_resolves_if_targets_illegal: bool = False

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.effects.generic.targets_helpers import (
            _slot_target_still_legal,
        )
        from mtg_bot.turn import sacrifice

        source = state.resolving_source
        if source is None or source not in state.battlefield:
            return
        other = None
        if targets and self.targets:
            prior = state.resolving_controller_id
            try:
                state.resolving_controller_id = controller_id
                legal = _slot_target_still_legal(
                    state, self.targets[0], targets[0],
                )
            finally:
                state.resolving_controller_id = prior
            if legal:
                from mtg_bot.keyword_rules import can_be_targeted_by

                other = next(
                    (o for o in state.battlefield if o.id == targets[0][1]),
                    None,
                )
                # Hexproof / shroud / protection gained in response make
                # the target illegal too (CR 608.2b).
                if other is not None and not can_be_targeted_by(
                    state, other, source, controller_id,
                ):
                    other = None
        if other is not None and other.controller_id != source.controller_id:
            source.controller_id, other.controller_id = (
                other.controller_id, source.controller_id,
            )
            source.summoning_sick = True
            other.summoning_sick = True
            state.log.append(
                f"{source.printing.name} and {other.printing.name} exchange "
                "controllers"
            )
            return
        state.log.append(
            f"no exchange: P{controller_id} sacrifices {source.printing.name}"
        )
        sacrifice(state, source)

    def describe(self) -> str:
        return (
            "exchange control of this permanent and up to one target; if you "
            "don't, sacrifice this permanent"
        )


@dataclass(frozen=True)
class GainControlUntapHasteUEOT(Effect):
    """"Gain control of target <np> until end of turn. Untap that
    <permanent>. It gains haste until end of turn." -- the Threaten shape
    over any permanent noun (Zealous Conscripts: "target permanent").
    Control rides the layer-2 cleanup-expiring registry
    (``state.grant_control_change_ueot``, the ``ThreatenTargetCreatureUEOT``
    path); haste is a cleanup-expiring layer-6 grant."""

    targets: tuple = ()

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.effects.generic.targets_helpers import (
            _fizzle_message,
            _slot_target_still_legal,
        )

        if not targets or not self.targets:
            return
        prior = state.resolving_controller_id
        try:
            state.resolving_controller_id = controller_id
            legal = _slot_target_still_legal(state, self.targets[0], targets[0])
        finally:
            state.resolving_controller_id = prior
        if not legal:
            state.log.append(_fizzle_message(state, targets[0]))
            return
        obj = next((o for o in state.battlefield if o.id == targets[0][1]), None)
        if obj is None:  # pragma: no cover - legality checked above
            return
        src = state.resolving_source
        state.grant_control_change_ueot(
            source_id=src.id if src is not None else obj.id,
            target_id=obj.id,
            new_controller_id=controller_id,
            description=(
                f"P{controller_id} controls {obj.printing.name} until end of "
                "turn"
            ),
        )
        obj.tapped = False
        state.add_continuous_effect(
            source_id=src.id if src is not None else obj.id,
            layer=6, kind="grant_keyword", target_id=obj.id,
            params=("haste",), expires_at="cleanup",
            description=f"{obj.printing.name} gains haste until end of turn",
        )
        state.log.append(
            f"P{controller_id} gains control of {obj.printing.name} until end "
            "of turn; it untaps and gains haste"
        )

    def describe(self) -> str:
        return (
            "gain control of target permanent until end of turn; untap it; "
            "it gains haste until end of turn"
        )


# ---------------------------------------------------------------------------
# Flicker
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExileTargetThenReturnUnderOwnersControl(Effect):
    """"[You may ]exile [another ]target <np>, then return it / that card
    to the battlefield under its owner's control." (Ephemerate, Felidar
    Guardian). The returned card is a new object (CR 400.7: fresh ETB,
    counters and attachments gone); a token exiled this way ceases to
    exist. ``optional`` ("you may") asks ``choose_yes_no`` first."""

    targets: tuple = ()
    optional: bool = False

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.actions import put_into_battlefield
        from mtg_bot.effects.generic.targets_helpers import (
            _fizzle_message,
            _slot_target_still_legal,
        )
        from mtg_bot.turn import move_off_battlefield

        if not targets or not self.targets:
            return
        prior = state.resolving_controller_id
        try:
            state.resolving_controller_id = controller_id
            legal = _slot_target_still_legal(state, self.targets[0], targets[0])
        finally:
            state.resolving_controller_id = prior
        if not legal:
            state.log.append(_fizzle_message(state, targets[0]))
            return
        obj = next((o for o in state.battlefield if o.id == targets[0][1]), None)
        if obj is None:  # pragma: no cover - legality checked above
            return
        agent = state.player_by_id(controller_id).agent
        if self.optional and agent is not None and not agent.choose_yes_no(
            state, controller_id, f"Exile and return {obj.printing.name}?",
        ):
            return
        move_off_battlefield(state, obj, destination="exile")
        if obj.printing.is_token:
            return
        owner = state.player_by_id(obj.owner_id)
        if obj not in owner.exile:
            return  # a replacement sent it elsewhere
        owner.exile.remove(obj)
        # CR 400.7: it returns as a new object -- no counters.
        from mtg_bot.turn import _reset_left_battlefield_object

        _reset_left_battlefield_object(obj)
        state.log.append(f"{obj.printing.name} returns to the battlefield")
        put_into_battlefield(state, obj, obj.owner_id)

    def describe(self) -> str:
        may = "you may " if self.optional else ""
        return (
            f"{may}exile target permanent, then return it to the battlefield "
            "under its owner's control"
        )


# ---------------------------------------------------------------------------
# Rebound (CR 702.88)
# ---------------------------------------------------------------------------


def exile_with_rebound(state: "GameState", card, controller_id: int) -> None:
    """Rebound (CR 702.88a): the spell, cast from its owner's hand, is
    exiled as it resolves, with a delayed "at the beginning of your next
    upkeep, you may cast this card from exile without paying its mana
    cost" trigger (``turn.run_delayed_upkeep_triggers``, ``own_upkeep``)."""
    from mtg_bot.game import Zone

    card.cast_via_hand = False
    card.zone = Zone.EXILE
    state.player_by_id(card.owner_id).exile.append(card)
    state.delayed_triggers.append({
        "step": "upkeep",
        "own_upkeep": True,
        "fire_at_turn": state.turn_number + 1,
        "controller_id": controller_id,
        "source_id": card.id,
        "effect": MayCastExiledSourceFree(),
    })
    state.log.append(f"{card.printing.name} is exiled (rebound)")


@dataclass(frozen=True)
class MayCastExiledSourceFree(Effect):
    """Rebound's delayed trigger: "you may cast this card from exile
    without paying its mana cost" -- if it is still that exiled card,
    castable now (targets available), and the controller agrees, it is
    cast through ``creature_casting_ub.cast_now`` (above the trigger)."""

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.creature_casting_ub import can_cast_now, cast_now
        from mtg_bot.game import Zone

        card = state.resolving_source
        if card is None or card.zone != Zone.EXILE:
            return
        if card not in state.player_by_id(card.owner_id).exile:
            return
        if not can_cast_now(state, controller_id, card, free=True):
            state.log.append(f"{card.printing.name} can't be cast (rebound)")
            return
        agent = state.player_by_id(controller_id).agent
        if agent is not None and not agent.choose_yes_no(
            state, controller_id, f"Cast {card.printing.name} (rebound)?",
        ):
            return
        cast_now(state, controller_id, card, free=True)

    def describe(self) -> str:
        return "you may cast this card from exile without paying its mana cost"


# ---------------------------------------------------------------------------
# Nicol Bolas, God-Pharaoh
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TargetOpponentExilesUntilNonlandCastFree(Effect):
    """"Target opponent exiles cards from the top of their library until
    they exile a nonland card. Until end of turn, you may cast that card
    without paying its mana cost." (Nicol Bolas, God-Pharaoh's +2). The
    cards are exiled face up; the nonland card carries a this-turn,
    free, cast-only ``ExilePlayPermission`` for the controller."""

    def requires_target(self) -> bool:
        return True

    def legal_targets(self, state, controller_id):
        return [
            ("player", p.id) for p in state.players
            if p.id != controller_id and not p.has_lost
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.effects.generic.cube_creatures_rmc import (
            exile_card,
            grant_exile_play,
        )

        pid = next((t[1] for t in targets if t[0] == "player"), None)
        if pid is None:
            return
        opp = state.player_by_id(pid)
        while opp.library:
            card = opp.library.pop(0)
            exile_card(state, card)
            state.log.append(f"P{pid} exiles {card.printing.name}")
            if not card.printing.is_land:
                grant_exile_play(
                    state, card, controller_id, free=True, cast_only=True,
                )
                return

    def describe(self) -> str:
        return (
            "target opponent exiles cards from the top of their library until "
            "a nonland card; you may cast it free this turn"
        )


@dataclass(frozen=True)
class EachOpponentExilesCardsFromHand(Effect):
    """"Each opponent exiles <N> cards from their hand." (Nicol Bolas,
    God-Pharaoh's +1). Each opponent picks their own cards (the
    ``choose_discard`` hand-card picker); the cards are exiled face up."""

    count: int = 1

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.effects.generic.cube_creatures_rmc import exile_card

        for p in state.players:
            if p.id == controller_id or p.has_lost:
                continue
            for _ in range(self.count):
                if not p.hand:
                    break
                ids = [c.id for c in p.hand]
                pick = ids[0]
                if p.agent is not None:
                    pick = p.agent.choose_discard(state, p.id, ids)
                card = next((c for c in p.hand if c.id == pick), p.hand[0])
                p.hand.remove(card)
                exile_card(state, card)
                state.log.append(
                    f"P{p.id} exiles {card.printing.name} from their hand"
                )

    def describe(self) -> str:
        n = "a card" if self.count == 1 else f"{self.count} cards"
        return f"each opponent exiles {n} from their hand"
