"""Effects for the cube W/G creature bucket.

Each class models one printed effect shape claimed by
:mod:`mtg_bot.cards.parser.creature_wg_effects`; the docstrings name the
cards that print it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mtg_bot.effects.base import Effect, Target, TriggeredAbility
from mtg_bot.effects.predicates import TriggerPredicate

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


# ---------------------------------------------------------------------
# Linked "exiled with this permanent" abilities (CR 607.2a)
# ---------------------------------------------------------------------


def exile_link_key(source) -> tuple:
    """The ``GameObject.exiled_with`` value naming ``source``'s current
    battlefield incarnation."""
    return (source.id, source.etb_timestamp)


def cards_exiled_with(state: "GameState", source) -> list:
    """Cards in exile that ``source``'s linked exiling ability put there
    (this incarnation of ``source`` only)."""
    key = exile_link_key(source)
    return [c for p in state.players for c in p.exile if c.exiled_with == key]


@dataclass(frozen=True)
class LinkExiledCardsToSource(Effect):
    """Wraps the exiling half of a linked ability pair (CR 607.2a): every
    card the inner effect moves into exile is tagged as "exiled with"
    the resolving source (``GameObject.exiled_with``), so the other half
    ("the exiled card", "cards exiled with this creature") can find it.

    Targeting delegates to ``inner`` unchanged."""

    inner: Effect

    @property
    def targets(self):  # type: ignore[override]
        return self.inner.targets

    def requires_target(self) -> bool:
        return self.inner.requires_target()

    def legal_targets(self, state, controller_id):
        return self.inner.legal_targets(state, controller_id)

    def target_count_range(self):
        return self.inner.target_count_range()

    def target_slot_kinds(self):
        return self.inner.target_slot_kinds()

    def resolve(self, state, controller_id, targets=()):
        source = state.resolving_source
        before = {c.id for p in state.players for c in p.exile}
        result = self.inner.resolve(state, controller_id, targets)
        if source is not None:
            key = exile_link_key(source)
            for p in state.players:
                for c in p.exile:
                    if c.id not in before:
                        c.exiled_with = key
        return result

    def describe(self) -> str:
        return self.inner.describe()


@dataclass(frozen=True)
class ExiledCardOwnerCreatesManaValueToken(Effect):
    """"The exiled card's owner creates an X/X <color> <Subtype> creature
    token, where X is the mana value of the exiled card." (Skyclave
    Apparition's leaves-the-battlefield half.) Reads the cards linked to
    the source's last battlefield incarnation and unlinks them."""

    consumes_exile_link = True

    color: str = "U"
    subtype: str = "Illusion"

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.cards.base import make_token_creature
        from mtg_bot.effects.generic.tokens import CreateToken

        source = state.resolving_source
        if source is None:
            return
        for card in cards_exiled_with(state, source):
            card.exiled_with = ()
            x = card.printing.mana_cost.total
            printing = make_token_creature(
                name=self.subtype, power=x, toughness=x,
                subtypes=(self.subtype,), colors=(self.color,),
            )
            CreateToken(token_printing=printing).resolve(state, card.owner_id)

    def describe(self) -> str:
        return (
            f"the exiled card's owner creates an X/X {self.subtype} token, "
            f"where X is its mana value"
        )


# ---------------------------------------------------------------------
# "Exile ... until an opponent becomes the monarch" (Palace Jailer)
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class ExileUntilOpponentBecomesMonarch(Effect):
    """"Exile target <permanent> until an opponent becomes the monarch."
    The exile ends -- the card returns under its owner's control -- the
    next time a player other than this ability's controller becomes the
    monarch (``designations.become_monarch`` calls
    :func:`release_exiled_until_opponent_monarch`), whether or not the
    source is still on the battlefield."""

    targets: tuple = ()

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.effects.generic.targets_helpers import (
            _slot_target_still_legal,
        )
        from mtg_bot.turn import move_off_battlefield

        prior = getattr(state, "resolving_controller_id", None)
        state.resolving_controller_id = controller_id
        try:
            for slot, chosen in zip(self.targets, targets):
                if not _slot_target_still_legal(state, slot, chosen):
                    continue
                obj = next(o for o in state.battlefield if o.id == chosen[1])
                obj.exiled_until_opponent_monarch_of = controller_id
                state.log.append(
                    f"{obj.printing.name} is exiled until an opponent of "
                    f"P{controller_id} becomes the monarch"
                )
                move_off_battlefield(state, obj, destination="exile")
        finally:
            state.resolving_controller_id = prior

    def describe(self) -> str:
        return "exile target permanent until an opponent becomes the monarch"


def release_exiled_until_opponent_monarch(
    state: "GameState", new_monarch_id: int,
) -> None:
    """``new_monarch_id`` just became the monarch: return every card
    exiled "until an opponent becomes the monarch" by one of their
    opponents to the battlefield under its owner's control."""
    from mtg_bot.actions import put_into_battlefield
    from mtg_bot.turn import _reset_left_battlefield_object

    for p in state.players:
        for c in list(p.exile):
            exiler = c.exiled_until_opponent_monarch_of
            if exiler is None or exiler == new_monarch_id:
                continue
            c.exiled_until_opponent_monarch_of = None
            p.exile.remove(c)
            state.log.append(
                f"{c.printing.name} returns from exile (P{new_monarch_id} "
                f"became the monarch)"
            )
            _reset_left_battlefield_object(c)
            put_into_battlefield(state, c, p.id)


# ---------------------------------------------------------------------
# Flicker until the next end step (Flickerwisp, Phelia)
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class ExileTargetReturnAtNextEndStep(Effect):
    """"Exile <target>. Return that card to the battlefield under its
    owner's control at the beginning of the next end step." (Flickerwisp)
    / "... At the beginning of the next end step, return that card ...
    If it entered under your control, put a +1/+1 counter on <this>."
    (Phelia, ``counter_on_source_if_yours``).

    The return is a delayed trigger (``schedule_at_next_end_step``)
    carrying the exiled card's id; a token target ceases to exist and
    nothing returns."""

    targets: tuple = ()
    counter_on_source_if_yours: bool = False

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.effects.generic.delayed_actions import (
            schedule_at_next_end_step,
        )
        from mtg_bot.effects.generic.targets_helpers import (
            _slot_target_still_legal,
        )
        from mtg_bot.turn import move_off_battlefield

        source = state.resolving_source
        prior = getattr(state, "resolving_controller_id", None)
        state.resolving_controller_id = controller_id
        try:
            for slot, chosen in zip(self.targets, targets):
                if not _slot_target_still_legal(state, slot, chosen):
                    continue
                obj = next(o for o in state.battlefield if o.id == chosen[1])
                state.log.append(f"{obj.printing.name} is exiled")
                move_off_battlefield(state, obj, destination="exile")
                if obj.printing.is_token:
                    continue
                schedule_at_next_end_step(
                    state, controller_id, obj.id,
                    ReturnExiledCardToBattlefield(
                        card_id=obj.id,
                        counter_on_id=(
                            source.id
                            if self.counter_on_source_if_yours
                            and source is not None else None
                        ),
                    ),
                )
        finally:
            state.resolving_controller_id = prior

    def describe(self) -> str:
        return (
            "exile target permanent; return it at the beginning of the next "
            "end step"
        )


@dataclass(frozen=True)
class ReturnExiledCardToBattlefield(Effect):
    """Delayed half of :class:`ExileTargetReturnAtNextEndStep`: return
    the exiled card ``card_id`` to the battlefield under its owner's
    control (no-op if it left exile); if ``counter_on_id`` is set and
    the card entered under this ability's controller's control, put a
    +1/+1 counter on that permanent (Phelia)."""

    card_id: int = -1
    counter_on_id: "int | None" = None

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.actions import put_into_battlefield
        from mtg_bot.game import add_plus_one_counters
        from mtg_bot.turn import _reset_left_battlefield_object

        for p in state.players:
            card = next((c for c in p.exile if c.id == self.card_id), None)
            if card is None:
                continue
            p.exile.remove(card)
            state.log.append(
                f"{card.printing.name} returns to the battlefield under "
                f"P{p.id}'s control"
            )
            _reset_left_battlefield_object(card)
            put_into_battlefield(state, card, p.id)
            if self.counter_on_id is not None and p.id == controller_id:
                host = next(
                    (o for o in state.battlefield if o.id == self.counter_on_id),
                    None,
                )
                if host is not None:
                    add_plus_one_counters(state, host, 1)
            return

    def describe(self) -> str:
        return (
            "return the exiled card to the battlefield under its owner's "
            "control"
        )


# ---------------------------------------------------------------------
# Ravenous / Mobilize / tokens scaled by power
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class EnteringWithXAtLeast(TriggerPredicate):
    """Trigger gate: the entering spell's X (``state.resolving_x_value``
    while it resolves onto the battlefield) is at least ``n`` -- the
    Ravenous "If X is 5 or more, draw a card when it enters." rider. A
    permanent that enters without being cast has X = 0."""

    n: int = 5

    def matches(self, state, subjects, source):
        return getattr(state, "resolving_x_value", 0) >= self.n


def ravenous_draw_trigger() -> TriggeredAbility:
    """Ravenous (CR 702.156): "This creature enters with X +1/+1 counters
    on it. If X is 5 or more, draw a card when it enters." The counters
    are the printing's ``enters_with_counters_from_x="x"``; this is the
    draw half."""
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.predicates import Event, IsSelf

    return TriggeredAbility(
        event=Event.ENTERS,
        predicate=IsSelf() & EnteringWithXAtLeast(5),
        effect=DrawCards(amount=1),
    )


def _new_objects(state: "GameState", before: set) -> list:
    return [o for o in state.battlefield if o.id not in before]


@dataclass(frozen=True)
class Mobilize(Effect):
    """Mobilize N (CR 702.181): "Whenever this creature attacks, create N
    tapped and attacking 1/1 red Warrior creature tokens. Sacrifice them
    at the beginning of the next end step." -- the attack trigger's
    effect. Token doublers apply; each created token gets its own
    delayed sacrifice trigger."""

    n: int = 1

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.cards.base import make_token_creature
        from mtg_bot.effects.generic.delayed_actions import (
            SacrificeSourceDelayed,
            schedule_at_next_end_step,
        )
        from mtg_bot.effects.generic.tokens import CreateToken

        before = {o.id for o in state.battlefield}
        warrior = make_token_creature(
            name="Warrior", power=1, toughness=1, subtypes=("Warrior",),
            colors=("R",),
        )
        CreateToken(
            token_printing=warrior, count=self.n, tapped=True, attacking=True,
        ).resolve(state, controller_id)
        for tok in _new_objects(state, before):
            schedule_at_next_end_step(
                state, controller_id, tok.id, SacrificeSourceDelayed(),
            )

    def describe(self) -> str:
        return (
            f"mobilize {self.n}: create {self.n} tapped and attacking 1/1 red "
            f"Warrior tokens; sacrifice them at the next end step"
        )


@dataclass(frozen=True)
class CreateTokensEqualToSourcePower(Effect):
    """"Create a number of <token> tokens equal to this creature's power."
    (Jacked Rabbit.) Reads the source's current power (last known power
    if it has left the battlefield)."""

    token_printing: "object" = None

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.effects.generic.tokens import CreateToken
        from mtg_bot.game import effective_power

        source = state.resolving_source
        if source is None:
            return
        n = max(0, effective_power(state, source))
        if n:
            CreateToken(token_printing=self.token_printing, count=n).resolve(
                state, controller_id,
            )

    def describe(self) -> str:
        return (
            f"create a number of {self.token_printing.name} tokens equal to "
            f"this creature's power"
        )


# ---------------------------------------------------------------------
# Card flow (Loran, Stoneforge Mystic)
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class YouAndTargetOpponentEachDraw(Effect):
    """"You and target opponent each draw N cards." (Loran of the Third
    Path.)"""

    amount: int = 1

    def requires_target(self) -> bool:
        return True

    def legal_targets(self, state, controller_id):
        return [
            ("player", p.id) for p in state.players
            if not p.has_lost and p.id != controller_id
        ]

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.turn import draw_n_cards

        draw_n_cards(state, controller_id, self.amount)
        opp = _chosen_player(state, targets)
        if opp is not None:
            draw_n_cards(state, opp.id, self.amount)

    def describe(self) -> str:
        return f"you and target opponent each draw {self.amount} card(s)"


@dataclass(frozen=True)
class PutCardFromHandOntoBattlefield(Effect):
    """"[You may ]put <a filter> card from your hand onto the battlefield."
    (Stoneforge Mystic's Equipment.) The card is picked with
    ``choose_card_from_library`` (the zone-agnostic pick hook the other
    put-from-hand effects use); with ``optional`` the pick may be
    declined (``None``)."""

    card_filter: "object" = None
    optional: bool = True
    tapped: bool = False

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.actions import put_into_battlefield

        p = state.player_by_id(controller_id)
        options = [c for c in p.hand if self.card_filter.matches(c.printing)]
        if not options:
            return False
        picked = None
        if p.agent is not None:
            picked = p.agent.choose_card_from_library(
                state, controller_id, [c.id for c in options],
            )
        card = next((c for c in options if c.id == picked), None)
        if card is None:
            if self.optional:
                state.log.append(
                    f"P{controller_id} puts nothing onto the battlefield"
                )
                return False
            card = options[0]
        p.hand.remove(card)
        state.log.append(
            f"P{controller_id} puts {card.printing.name} onto the battlefield"
        )
        put_into_battlefield(state, card, controller_id)
        if self.tapped:
            card.tapped = True
        return True

    def describe(self) -> str:
        may = "you may " if self.optional else ""
        return (
            f"{may}put {self.card_filter.describe()} from your hand onto the "
            f"battlefield"
        )
