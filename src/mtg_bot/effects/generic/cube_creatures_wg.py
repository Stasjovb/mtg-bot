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


# ---------------------------------------------------------------------
# Token copies of the source (Vaultborn Tyrant)
# ---------------------------------------------------------------------


def token_copy_printing(base, extra_card_types: tuple = ()):
    """A token printing copying ``base``'s copiable values, with the
    Token supertype and ``extra_card_types`` ("except it's an artifact in
    addition to its other types") added."""
    import dataclasses as _dc

    supertypes = tuple(base.supertypes) + (
        () if "Token" in base.supertypes else ("Token",)
    )
    card_types = tuple(
        t for t in extra_card_types if t not in base.card_types
    ) + tuple(base.card_types)
    left = " ".join(supertypes + card_types)
    type_line = f"{left} — {' '.join(base.subtypes)}" if base.subtypes else left
    return _dc.replace(
        base, supertypes=supertypes, card_types=card_types, type_line=type_line,
    )


@dataclass(frozen=True)
class CreateTokenCopyOfSource(Effect):
    """"Create a token that's a copy of it[, except it's an <type> in
    addition to its other types]." -- "it" being this ability's source
    (Vaultborn Tyrant's dies trigger: last known copiable values)."""

    extra_card_types: tuple = ()

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.effects.generic.tokens import CreateToken

        source = state.resolving_source
        if source is None:
            return
        CreateToken(
            token_printing=token_copy_printing(
                source.printing, self.extra_card_types,
            ),
        ).resolve(state, controller_id)

    def describe(self) -> str:
        extra = " and ".join(t.lower() for t in self.extra_card_types)
        tail = f", except it's also {extra}" if extra else ""
        return f"create a token that's a copy of it{tail}"


# ---------------------------------------------------------------------
# Untapping (White Plume Adventurer)
# ---------------------------------------------------------------------


def _matching_permanents(state, controller_id, permanent_filter) -> list:
    prior = getattr(state, "resolving_controller_id", None)
    state.resolving_controller_id = controller_id
    try:
        return [o for o in state.battlefield if permanent_filter.test(o, state)]
    finally:
        state.resolving_controller_id = prior


@dataclass(frozen=True)
class UntapChosenPermanents(Effect):
    """"Untap a <permanent>." -- untargeted: the controller picks ``n``
    matching permanents (via ``choose_permanent_to_tap``; a declined
    pick falls back to the first tapped option, since the printed "a"
    isn't optional). Untapping an untapped permanent is a no-op, so the
    tapped ones are offered."""

    n: int = 1
    permanent_filter: "object" = None

    def resolve(self, state, controller_id, targets=()):
        p = state.player_by_id(controller_id)
        for _ in range(self.n):
            options = [
                o for o in _matching_permanents(
                    state, controller_id, self.permanent_filter,
                )
                if o.tapped
            ]
            if not options:
                return
            pick = None
            if p.agent is not None:
                pick = p.agent.choose_permanent_to_tap(
                    state, controller_id, [o.id for o in options],
                )
            obj = next((o for o in options if o.id == pick), options[0])
            obj.tapped = False
            state.log.append(f"P{controller_id} untaps {obj.printing.name}")

    def describe(self) -> str:
        return f"untap {self.n} chosen permanent(s)"


@dataclass(frozen=True)
class UntapAllMatching(Effect):
    """"Untap all <permanents>." (White Plume Adventurer's dungeon
    rider: "untap all creatures you control")."""

    permanent_filter: "object" = None

    def resolve(self, state, controller_id, targets=()):
        for o in _matching_permanents(state, controller_id, self.permanent_filter):
            o.tapped = False
        state.log.append(f"P{controller_id} untaps all matching permanents")

    def describe(self) -> str:
        return "untap all matching permanents"


# ---------------------------------------------------------------------
# Questing Beast / Worldspine Wurm
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class DealCombatDamageAmountToTarget(Effect):
    """"<It> deals that much damage to target <X>." -- the amount is the
    triggering combat damage (``state.resolving_combat_damage_amount``);
    Questing Beast's planeswalker redirect."""

    targets: tuple = ()

    def targets_from_event(self, state, subjects):
        """The trigger's own target (a planeswalker), not the damaged
        player the combat-damage dispatch would pre-wire: returning
        ``None`` lets ``push_triggered_ability`` prompt for it."""
        return None

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.effects.base import _apply_damage
        from mtg_bot.effects.generic.targets_helpers import (
            _slot_target_still_legal,
        )

        amount = state.resolving_combat_damage_amount
        prior = getattr(state, "resolving_controller_id", None)
        state.resolving_controller_id = controller_id
        try:
            for slot, chosen in zip(self.targets, targets):
                if amount > 0 and _slot_target_still_legal(state, slot, chosen):
                    _apply_damage(state, chosen, amount)
        finally:
            state.resolving_controller_id = prior

    def describe(self) -> str:
        return "deals that much damage to the target"


@dataclass(frozen=True)
class ShuffleSourceIntoOwnersLibrary(Effect):
    """"Shuffle it into its owner's library." -- the resolving source
    card, if it's still in its owner's graveyard (Worldspine Wurm's
    put-into-a-graveyard trigger). Re-arms the card's graveyard-arrival
    trigger."""

    # The only effects a "put into a graveyard from anywhere" trigger
    # may carry: each clears ``graveyard_arrival_pending``.
    rearms_graveyard_arrival = True

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.game import Zone, shuffle_library

        card = state.resolving_source
        if card is None:
            return
        card.graveyard_arrival_pending = False
        owner = state.player_by_id(card.owner_id)
        if card not in owner.graveyard:
            return
        owner.graveyard.remove(card)
        card.zone = Zone.LIBRARY
        owner.library.append(card)
        shuffle_library(state, owner.id)
        state.log.append(
            f"{card.printing.name} is shuffled into P{owner.id}'s library"
        )

    def describe(self) -> str:
        return "shuffle it into its owner's library"


# ---------------------------------------------------------------------
# Counters (Arwen, Bristly Bill, Scythecat Cub)
# ---------------------------------------------------------------------


def _put_counters(state, obj, counters) -> None:
    from mtg_bot.game import add_counters

    for kind, n in counters:
        add_counters(state, obj, kind, n)


def _target_object(state, slot, chosen):
    from mtg_bot.effects.generic.targets_helpers import _slot_target_still_legal

    if not _slot_target_still_legal(state, slot, chosen):
        return None
    return next((o for o in state.battlefield if o.id == chosen[1]), None)


@dataclass(frozen=True)
class GrantKeywordsUEOTAndPutCounters(Effect):
    """"<Target> gains <keywords> until end of turn. Put <counters> on
    that creature and <counters> on <this>." (Arwen, Mortal Queen.)
    ``target_counters`` / ``self_counters`` are ``((kind, n), ...)``."""

    targets: tuple = ()
    keywords: frozenset = frozenset()
    target_counters: tuple = ()
    self_counters: tuple = ()

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.effects.combinators import ApplyEffect
        from mtg_bot.effects.durations import EndOfTurn
        from mtg_bot.effects.generic.grant_keywords import GrantKeywords

        source = state.resolving_source
        prior = getattr(state, "resolving_controller_id", None)
        state.resolving_controller_id = controller_id
        try:
            obj = (
                _target_object(state, self.targets[0], targets[0])
                if targets else None
            )
        finally:
            state.resolving_controller_id = prior
        if obj is not None:
            if self.keywords:
                ApplyEffect(
                    inner=GrantKeywords(keywords=self.keywords),
                    ends_at=EndOfTurn(),
                ).resolve(state, controller_id, (("creature", obj.id),))
            _put_counters(state, obj, self.target_counters)
        if source is not None and source in state.battlefield:
            _put_counters(state, source, self.self_counters)

    def describe(self) -> str:
        return (
            "target gains keywords until end of turn; put counters on it "
            "and on this creature"
        )


@dataclass(frozen=True)
class DoublePlusOneCountersOnEach(Effect):
    """"Double the number of +1/+1 counters on each <permanent>."
    (Bristly Bill.) Doubling puts that many more counters (CR 122.7)."""

    permanent_filter: "object" = None

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.game import add_plus_one_counters

        for o in _matching_permanents(state, controller_id, self.permanent_filter):
            if o.plus_one_counters > 0:
                add_plus_one_counters(state, o, o.plus_one_counters)

    def describe(self) -> str:
        return "double the number of +1/+1 counters on each matching permanent"


def _bump_resolution_count(state, source) -> int:
    """Count this resolution of ``source``'s ability for the current
    turn (``GameObject.resolutions_this_turn``); returns the new count."""
    turn, n = source.resolutions_this_turn or (state.turn_number, 0)
    n = n + 1 if turn == state.turn_number else 1
    source.resolutions_this_turn = (state.turn_number, n)
    return n


@dataclass(frozen=True)
class PutCounterDoublingOnSecondResolution(Effect):
    """"Put a +1/+1 counter on <target>. If this is the second time this
    ability has resolved this turn, double the number of +1/+1 counters
    on that creature instead." (Scythecat Cub.) The source counts its
    ability's resolutions per turn."""

    targets: tuple = ()

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.game import add_plus_one_counters

        source = state.resolving_source
        n = _bump_resolution_count(state, source) if source is not None else 1
        if not targets:
            return
        prior = getattr(state, "resolving_controller_id", None)
        state.resolving_controller_id = controller_id
        try:
            obj = _target_object(state, self.targets[0], targets[0])
        finally:
            state.resolving_controller_id = prior
        if obj is None:
            return
        if n == 2:
            if obj.plus_one_counters > 0:
                add_plus_one_counters(state, obj, obj.plus_one_counters)
        else:
            add_plus_one_counters(state, obj, 1)

    def describe(self) -> str:
        return (
            "put a +1/+1 counter on target creature; on this ability's "
            "second resolution this turn, double its counters instead"
        )


# ---------------------------------------------------------------------
# Reflexive "you may <cost>. When you do, <effect>" (Leatherhead, Guide
# of Souls)
# ---------------------------------------------------------------------


def _counter_kinds_on(obj) -> list:
    from mtg_bot.game import _DEDICATED_COUNTER_FIELDS

    kinds = [
        kind for kind, attr in _DEDICATED_COUNTER_FIELDS.items()
        if getattr(obj, attr, 0) > 0
    ]
    kinds += [k for k, n in obj.named_counters if n > 0]
    return kinds


@dataclass(frozen=True)
class RemoveACounterFromSelf(Effect):
    """"Remove a counter from <this>." -- any kind (the controller picks
    the kind with ``choose_mode``). Returns whether one was removed."""

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.game import remove_counters

        source = state.resolving_source
        if source is None or source not in state.battlefield:
            return False
        kinds = _counter_kinds_on(source)
        if not kinds:
            return False
        idx = 0
        p = state.player_by_id(controller_id)
        if len(kinds) > 1 and p.agent is not None:
            pick = p.agent.choose_mode(state, controller_id, kinds)
            if isinstance(pick, int) and 0 <= pick < len(kinds):
                idx = pick
        remove_counters(source, kinds[idx], 1)
        state.log.append(
            f"P{controller_id} removes a {kinds[idx]} counter from "
            f"{source.printing.name}"
        )
        return True

    def describe(self) -> str:
        return "remove a counter from this creature"


@dataclass(frozen=True)
class PayEnergy(Effect):
    """"Pay {E}{E}{E}." -- returns whether the energy was paid (the
    controller must have enough)."""

    amount: int = 1

    def resolve(self, state, controller_id, targets=()):
        p = state.player_by_id(controller_id)
        if p.energy < self.amount:
            return False
        p.energy -= self.amount
        state.log.append(f"P{controller_id} pays {self.amount} energy")
        return True

    def describe(self) -> str:
        return f"pay {self.amount} energy"


@dataclass(frozen=True)
class ReflexiveWhenYouDo(Effect):
    """"You may <cost>. When you do, <effect>." -- a reflexive triggered
    ability (CR 603.12): if the optional ``cost`` is paid, ``effect``'s
    targets are chosen then and it resolves. Engine shortcut: the
    reflexive trigger resolves immediately instead of using the stack
    (``docs/SEARCH_LIMITATIONS.md``).

    ``event_player_controls``: the effect's target must be controlled by
    the player the triggering event fixed as this ability's target
    ("... that player controls" after "deals combat damage to a
    player")."""

    cost: Effect = None  # type: ignore[assignment]
    effect: Effect = None  # type: ignore[assignment]
    event_player_controls: bool = False

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.effects.combinators import MayDo

        paid = MayDo(inner=self.cost).resolve(state, controller_id, ())
        if paid is False or paid is None:
            return False
        chosen: tuple = ()
        if self.effect.target_count_range()[1] > 0:
            legal = self.effect.legal_targets(state, controller_id)
            if self.event_player_controls:
                pid = next((t[1] for t in targets if t[0] == "player"), None)
                legal = [
                    t for t in legal
                    if t[0] != "player" and any(
                        o.id == t[1] and o.controller_id == pid
                        for o in state.battlefield
                    )
                ]
            from mtg_bot.keyword_rules import filter_targetable

            legal = filter_targetable(
                state, legal, state.resolving_source, controller_id,
            )
            if not legal:
                state.log.append("reflexive trigger has no legal targets")
                return True
            p = state.player_by_id(controller_id)
            pick = legal[0]
            if p.agent is not None:
                choice = p.agent.choose_target(state, controller_id, legal)
                if choice in legal:
                    pick = choice
            chosen = (pick,)
        self.effect.resolve(state, controller_id, chosen)
        return True

    def describe(self) -> str:
        return (
            f"you may {self.cost.describe()}; when you do, "
            f"{self.effect.describe()}"
        )


@dataclass(frozen=True)
class PutCountersOnTargetAndAddSubtype(Effect):
    """"Put <counters> on target <creature>. It becomes a <Subtype> in
    addition to its other types." (Guide of Souls.) The subtype is a
    permanent layer-4 addition."""

    targets: tuple = ()
    counters: tuple = ()
    subtype: str = ""

    def resolve(self, state, controller_id, targets=()):
        if not targets:
            return
        prior = getattr(state, "resolving_controller_id", None)
        state.resolving_controller_id = controller_id
        try:
            obj = _target_object(state, self.targets[0], targets[0])
        finally:
            state.resolving_controller_id = prior
        if obj is None:
            return
        _put_counters(state, obj, self.counters)
        if self.subtype:
            # Sourced by the creature itself so the type change outlasts
            # the ability's source (it ends only when the creature
            # leaves the battlefield).
            state.add_continuous_effect(
                source_id=obj.id,
                layer=4, kind="add_subtype", target_id=obj.id,
                params=(self.subtype,), expires_at=None,
                description=f"{obj.printing.name} becomes a {self.subtype}",
            )

    def describe(self) -> str:
        return f"put counters on target creature; it becomes a {self.subtype}"


@dataclass(frozen=True)
class GrantKeywordsUEOTThenExplores(Effect):
    """"Target <creature> gains <keywords> until end of turn. It
    explores." (Seasoned Dungeoneer.)"""

    targets: tuple = ()
    keywords: frozenset = frozenset()

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.effects.combinators import ApplyEffect
        from mtg_bot.effects.durations import EndOfTurn
        from mtg_bot.effects.generic.grant_keywords import GrantKeywords
        from mtg_bot.effects.generic.keyword_actions import explore

        if not targets:
            return
        prior = getattr(state, "resolving_controller_id", None)
        state.resolving_controller_id = controller_id
        try:
            obj = _target_object(state, self.targets[0], targets[0])
        finally:
            state.resolving_controller_id = prior
        if obj is None:
            return
        ApplyEffect(
            inner=GrantKeywords(keywords=self.keywords), ends_at=EndOfTurn(),
        ).resolve(state, controller_id, (("creature", obj.id),))
        explore(state, controller_id, obj)

    def describe(self) -> str:
        return "target creature gains keywords until end of turn; it explores"
