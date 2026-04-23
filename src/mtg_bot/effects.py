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
    from mtg_bot.cards import ManaCost
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

    def target_count_range(self) -> tuple[int, int]:
        """Return (min, max) number of targets. Default:
        (1, 1) if requires_target(), else (0, 0).
        Override for "up to N target" effects (min=0, max=N)."""
        return (1, 1) if self.requires_target() else (0, 0)

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
class SetLifeToHalfStartingRoundedUp(Effect):
    """Set the controller's life total to half their starting life, rounded up.

    Matches The Endstone's end-step trigger. In standard MTG,
    starting life = 20 → target becomes 10. Rounds up via
    ``(starting_life + 1) // 2``.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        p = state.player_by_id(controller_id)
        new_life = (p.starting_life + 1) // 2
        state.log.append(
            f"P{controller_id}'s life becomes {new_life} "
            f"(was {p.life}, starting {p.starting_life})"
        )
        p.life = new_life

    def describe(self) -> str:
        return (
            "your life total becomes half your starting life total, "
            "rounded up"
        )


@dataclass(frozen=True)
class TargetPlayerLosesLife(Effect):
    """Make the (pre-selected) target player lose ``amount`` life.

    Reads ``targets[0]`` as ("player", id). Used for triggers that
    identify a specific player via targeting (Entropic Battlecruiser's
    1+ tier "that player loses 3 life").
    """

    amount: int = 1

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if not targets:
            return
        kind, pid = targets[0]
        if kind != "player":
            return
        try:
            p = state.player_by_id(pid)
        except KeyError:
            return
        p.life -= self.amount
        state.log.append(
            f"P{pid} loses {self.amount} life (now {p.life})"
        )

    def describe(self) -> str:
        return f"that player loses {self.amount} life"


@dataclass(frozen=True)
class EachOpponentDiscardsOrLosesLife(Effect):
    """Each opponent discards a card. Each opponent who can't (because
    their hand is empty) loses ``life_if_cant`` life instead.

    Matches Entropic Battlecruiser's attacks trigger. Fires discard
    triggers per-discard via fire_opponent_discards_triggers.
    """

    life_if_cant: int = 3

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone
        from mtg_bot.turn import fire_opponent_discards_triggers

        for p in state.players:
            if p.id == controller_id or p.has_lost:
                continue
            if not p.hand:
                p.life -= self.life_if_cant
                state.log.append(
                    f"P{p.id} can't discard — loses {self.life_if_cant} "
                    f"life (now {p.life})"
                )
                continue
            hand_ids = [c.id for c in p.hand]
            chosen_id = p.agent.choose_discard(state, p.id, hand_ids)
            card = next(c for c in p.hand if c.id == chosen_id)
            p.hand.remove(card)
            card.zone = Zone.GRAVEYARD
            p.graveyard.append(card)
            state.log.append(f"P{p.id} discards {card.printing.name}")
            fire_opponent_discards_triggers(state, p.id)

    def describe(self) -> str:
        return (
            f"each opponent discards a card; each opponent who can't "
            f"loses {self.life_if_cant} life"
        )


@dataclass(frozen=True)
class PutPoisonCountersOnTargetPlayer(Effect):
    """Give ``amount`` poison counters to the (pre-selected) target
    player. Reads ``targets[0]`` as ("player", id); silently no-ops on
    mismatched shapes.

    Matches Virulent Silencer's trigger effect: the observer trigger
    wiring in combat._fire_combat_damage_to_player_triggers passes the
    hit player's id as the target.
    """

    amount: int = 1

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if not targets:
            return
        kind, pid = targets[0]
        if kind != "player":
            return
        try:
            p = state.player_by_id(pid)
        except KeyError:
            return
        p.poison_counters += self.amount
        state.log.append(
            f"P{pid} gets {self.amount} poison counter(s) "
            f"(now {p.poison_counters})"
        )

    def describe(self) -> str:
        return f"that player gets {self.amount} poison counter(s)"


@dataclass(frozen=True)
class LoseLife(Effect):
    """Controller loses ``amount`` life."""

    amount: int

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        p = state.player_by_id(controller_id)
        p.life -= self.amount
        state.log.append(
            f"P{controller_id} loses {self.amount} life (life: {p.life})"
        )

    def describe(self) -> str:
        return f"you lose {self.amount} life"


@dataclass(frozen=True)
class EachOpponentLosesLife(Effect):
    """Each opponent loses ``amount`` life."""

    amount: int

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        for p in state.players:
            if p.id == controller_id or p.has_lost:
                continue
            p.life -= self.amount
            state.log.append(
                f"P{p.id} loses {self.amount} life (life: {p.life})"
            )

    def describe(self) -> str:
        return f"each opponent loses {self.amount} life"


@dataclass(frozen=True)
class DiscardSelf(Effect):
    """Controller discards ``amount`` card(s) from their hand. The discarding
    player's agent picks which cards via ``choose_discard``."""

    amount: int = 1

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone
        from mtg_bot.turn import fire_opponent_discards_triggers

        p = state.player_by_id(controller_id)
        for _ in range(self.amount):
            if not p.hand:
                break
            hand_ids = [c.id for c in p.hand]
            chosen_id = p.agent.choose_discard(state, p.id, hand_ids)
            card = next(c for c in p.hand if c.id == chosen_id)
            p.hand.remove(card)
            card.zone = Zone.GRAVEYARD
            p.graveyard.append(card)
            state.log.append(f"P{p.id} discards {card.printing.name}")
            fire_opponent_discards_triggers(state, p.id)

    def describe(self) -> str:
        if self.amount == 1:
            return "you discard a card"
        return f"you discard {self.amount} cards"


@dataclass(frozen=True)
class ReturnTargetCreatureToOwnersHand(Effect):
    """Target creature on the battlefield returns to its owner's hand.

    Tokens cease to exist when bounced (they'd briefly be in hand, then
    rule 704.5d kicks in). Matches oracle text like "Return target
    creature to its owner's hand."
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "creature":
            return
        obj = next((o for o in state.battlefield if o.id == target_id), None)
        if obj is None:
            return
        state.battlefield.remove(obj)
        # Reset combat/damage state on the way off the battlefield
        obj.damage = 0
        obj.marked_lethal = False
        obj.tapped = False
        obj.attacking = False
        obj.blocking = None
        obj.blocked_by = []
        obj.cast_via_warp = False
        obj.plus_one_counters = 0
        obj.charge_counters = 0
        obj.temp_power_bonus = 0
        obj.temp_toughness_bonus = 0
        obj.temp_keywords = frozenset()
        # Track the leave-BF for Void
        if not obj.printing.is_land:
            state.permanent_left_battlefield_this_turn = True
        if obj.printing.is_token:
            state.log.append(
                f"{obj.printing.name} token ceases to exist (bounced)"
            )
            return
        obj.zone = Zone.HAND
        state.player_by_id(obj.owner_id).hand.append(obj)
        state.log.append(
            f"{obj.printing.name} returns to P{obj.owner_id}'s hand"
        )

    def describe(self) -> str:
        return "return target creature to its owner's hand"


@dataclass(frozen=True)
class ReturnTargetPermanentYouControlToOwnersHand(Effect):
    """Target permanent you control goes back to its owner's hand.

    Matches Exosuit Savior's "return up to one other target permanent you
    control to its owner's hand" (modeled as a required target; we don't
    model "up to one" optionality). Lands are legal targets too.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("permanent", o.id)
            for o in state.battlefield
            if o.controller_id == controller_id
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "permanent":
            return
        obj = next((o for o in state.battlefield if o.id == target_id), None)
        if obj is None or obj.controller_id != controller_id:
            return
        state.battlefield.remove(obj)
        obj.damage = 0
        obj.marked_lethal = False
        obj.tapped = False
        obj.attacking = False
        obj.blocking = None
        obj.blocked_by = []
        obj.cast_via_warp = False
        obj.plus_one_counters = 0
        obj.charge_counters = 0
        obj.temp_power_bonus = 0
        obj.temp_toughness_bonus = 0
        obj.temp_keywords = frozenset()
        if not obj.printing.is_land:
            state.permanent_left_battlefield_this_turn = True
        if obj.printing.is_token:
            state.log.append(
                f"{obj.printing.name} token ceases to exist (bounced)"
            )
            return
        obj.zone = Zone.HAND
        state.player_by_id(obj.owner_id).hand.append(obj)
        state.log.append(
            f"{obj.printing.name} returns to P{obj.owner_id}'s hand"
        )

    def describe(self) -> str:
        return "return target permanent you control to its owner's hand"


@dataclass(frozen=True)
class AttachToTargetCreatureYouControl(Effect):
    """Attach the source (Equipment) to target creature the controller
    controls. Matches the common ETB trigger on EoE Equipment.

    Reads state.resolving_source for the Equipment. No-op if the source
    isn't an Equipment (is_equipment check on subtypes).
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature and o.controller_id == controller_id
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        source = state.resolving_source
        if source is None:
            return
        if "Equipment" not in source.printing.subtypes:
            return
        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "creature":
            return
        target = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if target is None or not target.printing.is_creature:
            return
        if target.controller_id != controller_id:
            return
        source.attached_to = target_id
        state.log.append(
            f"{source.printing.name} is attached to {target.printing.name}"
        )

    def describe(self) -> str:
        return "attach this Equipment to target creature you control"


@dataclass(frozen=True)
class ReturnUpToNTargetCreaturesToOwnersHands(Effect):
    """Return up to ``max_n`` target creatures to their owners' hands.

    Matches Specimen Freighter's "return up to two target non-Spacecraft
    creatures to their owners' hands". We drop the "non-Spacecraft"
    filter for simplicity — any creature is targetable.
    """

    max_n: int = 2

    def requires_target(self) -> bool:
        return True

    def target_count_range(self) -> tuple[int, int]:
        return (0, self.max_n)

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone

        for kind, target_id in targets:
            if kind != "creature":
                continue
            obj = next(
                (o for o in state.battlefield if o.id == target_id), None
            )
            if obj is None:
                continue
            state.battlefield.remove(obj)
            obj.damage = 0
            obj.marked_lethal = False
            obj.tapped = False
            obj.attacking = False
            obj.blocking = None
            obj.blocked_by = []
            obj.cast_via_warp = False
            obj.plus_one_counters = 0
            obj.charge_counters = 0
            obj.temp_power_bonus = 0
            obj.temp_toughness_bonus = 0
            obj.temp_keywords = frozenset()
            obj.attached_to = None
            if not obj.printing.is_land:
                state.permanent_left_battlefield_this_turn = True
            if obj.printing.is_token:
                state.log.append(
                    f"{obj.printing.name} token ceases to exist (bounced)"
                )
                continue
            obj.zone = Zone.HAND
            state.player_by_id(obj.owner_id).hand.append(obj)
            state.log.append(
                f"{obj.printing.name} returns to P{obj.owner_id}'s hand"
            )

    def describe(self) -> str:
        return (
            f"return up to {self.max_n} target creatures to their "
            f"owners' hands"
        )


@dataclass(frozen=True)
class ReturnUpToNSmallCreaturesFromGraveyardWithCounters(Effect):
    """Return up to ``max_n`` creature cards with mana value ≤ ``max_mv``
    from your graveyard to the battlefield. Put a +1/+1 counter on each.

    Matches Scout for Survivors (simplified: the real card's "total
    mana value 3 or less" is the SUM constraint; we use per-card filter
    instead — slightly stronger).
    """

    max_n: int = 3
    max_mv: int = 3

    def requires_target(self) -> bool:
        return True

    def target_count_range(self) -> tuple[int, int]:
        return (0, self.max_n)

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        p = state.player_by_id(controller_id)
        return [
            ("graveyard_creature", c.id)
            for c in p.graveyard
            if c.printing.is_creature
            and c.printing.mana_cost.total <= self.max_mv
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.actions import put_into_battlefield

        p = state.player_by_id(controller_id)
        for kind, target_id in targets:
            if kind != "graveyard_creature":
                continue
            card = next((c for c in p.graveyard if c.id == target_id), None)
            if card is None:
                continue
            p.graveyard.remove(card)
            state.log.append(
                f"{card.printing.name} returns to the battlefield under "
                f"P{controller_id} with a +1/+1 counter"
            )
            put_into_battlefield(state, card, controller_id)
            card.plus_one_counters += 1

    def describe(self) -> str:
        return (
            f"return up to {self.max_n} target creature cards with mana "
            f"value {self.max_mv} or less from your graveyard to the "
            f"battlefield with a +1/+1 counter on each"
        )


@dataclass(frozen=True)
class CreateLanderAndScheduleSacrifice(Effect):
    """Create a Lander token for the controller, then schedule a delayed
    trigger to sacrifice that specific Lander at the controller's next
    end step.

    Matches Kav Landseeker's ETB. "Next end step on your next turn" is
    interpreted in a 2-player game as the controller's next end step
    that isn't the current turn — turn_number+2 if it's currently the
    controller's turn, else turn_number+1.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.actions import put_into_battlefield
        from mtg_bot.cards import TOKEN_PRINTINGS
        from mtg_bot.game import Zone

        lander = state.new_object(
            TOKEN_PRINTINGS["Lander"],
            owner_id=controller_id,
            zone=Zone.BATTLEFIELD,
        )
        put_into_battlefield(state, lander, controller_id)
        offset = 2 if state.active_player().id == controller_id else 1
        state.delayed_triggers.append({
            "fire_at_turn": state.turn_number + offset,
            "controller_id": controller_id,
            "action": "sacrifice",
            "target_id": lander.id,
        })
        state.log.append(
            f"P{controller_id} creates a Lander token (scheduled to be "
            f"sacrificed at end step of turn "
            f"{state.turn_number + offset})"
        )

    def describe(self) -> str:
        return (
            "create a Lander token; at the beginning of the end step on "
            "your next turn, sacrifice that token"
        )


@dataclass(frozen=True)
class CreateTokenAndAttachSelf(Effect):
    """Create a token and attach the source (Equipment) to it.

    Matches Auxiliary Boosters' ETB. Reads state.resolving_source for
    the Equipment. No-op if source isn't Equipment.
    """

    token_printing: "CardPrinting"

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.actions import put_into_battlefield
        from mtg_bot.game import Zone

        source = state.resolving_source
        if source is None:
            return
        if "Equipment" not in source.printing.subtypes:
            return
        token = state.new_object(
            self.token_printing, owner_id=controller_id,
            zone=Zone.BATTLEFIELD,
        )
        state.log.append(
            f"P{controller_id} creates a {self.token_printing.name} token"
        )
        put_into_battlefield(state, token, controller_id)
        source.attached_to = token.id
        state.log.append(
            f"{source.printing.name} is attached to {token.printing.name}"
        )

    def describe(self) -> str:
        return (
            f"create a {self.token_printing.name} token and attach this "
            f"Equipment to it"
        )


@dataclass(frozen=True)
class ReturnCreatureFromYourGraveyardToBattlefield(Effect):
    """Target creature card from your graveyard enters the battlefield under
    your control. Fires ETB triggers (via put_into_battlefield).

    Target format: ``("graveyard_creature", id)`` where id is a GameObject
    in the controller's graveyard.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        p = state.player_by_id(controller_id)
        return [
            ("graveyard_creature", c.id)
            for c in p.graveyard
            if c.printing.is_creature
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.actions import put_into_battlefield

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "graveyard_creature":
            return
        p = state.player_by_id(controller_id)
        card = next((c for c in p.graveyard if c.id == target_id), None)
        if card is None:
            return
        p.graveyard.remove(card)
        state.log.append(
            f"{card.printing.name} returns from P{controller_id}'s "
            f"graveyard to the battlefield"
        )
        put_into_battlefield(state, card, controller_id)

    def describe(self) -> str:
        return (
            "return target creature card from your graveyard to the "
            "battlefield"
        )


@dataclass(frozen=True)
class ReturnTargetArtifactCardFromYourGraveyardToHand(Effect):
    """Target artifact card from your graveyard goes to your hand.

    Matches Scour for Scrap's second mode. Uses a dedicated target kind
    ``graveyard_artifact`` so the multi-zone target pool is distinct
    from battlefield targets.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        p = state.player_by_id(controller_id)
        return [
            ("graveyard_artifact", c.id)
            for c in p.graveyard
            if c.printing.is_artifact
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "graveyard_artifact":
            return
        p = state.player_by_id(controller_id)
        card = next((c for c in p.graveyard if c.id == target_id), None)
        if card is None:
            return
        p.graveyard.remove(card)
        card.zone = Zone.HAND
        p.hand.append(card)
        state.log.append(
            f"{card.printing.name} returns from P{controller_id}'s "
            f"graveyard to hand"
        )

    def describe(self) -> str:
        return "return target artifact card from your graveyard to your hand"


@dataclass(frozen=True)
class ReturnCreatureFromYourGraveyardToHand(Effect):
    """Target creature card from your graveyard goes to your hand.

    Matches Interceptor Mechan's ETB (creature-only simplification of its
    "artifact or creature" oracle text).
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        p = state.player_by_id(controller_id)
        return [
            ("graveyard_creature", c.id)
            for c in p.graveyard
            if c.printing.is_creature
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "graveyard_creature":
            return
        p = state.player_by_id(controller_id)
        card = next((c for c in p.graveyard if c.id == target_id), None)
        if card is None:
            return
        p.graveyard.remove(card)
        card.zone = Zone.HAND
        p.hand.append(card)
        state.log.append(
            f"{card.printing.name} returns from P{controller_id}'s "
            f"graveyard to hand"
        )

    def describe(self) -> str:
        return "return target creature card from your graveyard to your hand"


@dataclass(frozen=True)
class ExileEachOpponentsGraveyard(Effect):
    """Move every card in each opponent's graveyard to that player's exile."""

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone

        total = 0
        for p in state.players:
            if p.id == controller_id or p.has_lost:
                continue
            cards_to_exile = list(p.graveyard)
            for card in cards_to_exile:
                p.graveyard.remove(card)
                card.zone = Zone.EXILE
                p.exile.append(card)
                total += 1
        state.log.append(
            f"P{controller_id} exiles {total} card(s) from opponent graveyards"
        )

    def describe(self) -> str:
        return "exile each opponent's graveyard"


@dataclass(frozen=True)
class TargetOpponentLosesNYouGainN(Effect):
    """Target opponent loses ``amount`` life; the ability's controller
    gains ``amount`` life. Matches Susurian Voidborn's
    your_creature_or_artifact_dies trigger.
    """

    amount: int = 1

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("player", p.id) for p in state.players
            if p.id != controller_id and not p.has_lost
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if not targets:
            return
        kind, pid = targets[0]
        if kind != "player":
            return
        try:
            opp = state.player_by_id(pid)
        except KeyError:
            return
        if opp.id == controller_id:
            return
        opp.life -= self.amount
        you = state.player_by_id(controller_id)
        you.life += self.amount
        state.log.append(
            f"P{pid} loses {self.amount} life (now {opp.life}); "
            f"P{controller_id} gains {self.amount} life (now {you.life})"
        )

    def describe(self) -> str:
        return (
            f"target opponent loses {self.amount} life and you gain "
            f"{self.amount} life"
        )


@dataclass(frozen=True)
class PumpTargetOtherCreatureByXOverXWhereXIsSourcePower(Effect):
    """Target another creature you control gets +X/+X until end of turn,
    where X is the effect's source's effective power. Reads
    ``state.resolving_source``; target must be under the same
    controller and not be the source itself.

    Matches Hemosymbic Mite's becomes-tapped trigger.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        source = state.resolving_source
        source_id = source.id if source is not None else -1
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature
            and o.controller_id == controller_id
            and o.id != source_id
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import effective_power

        source = state.resolving_source
        if source is None:
            return
        x = effective_power(state, source)
        if x <= 0:
            return
        if not targets:
            return
        kind, tid = targets[0]
        if kind != "creature":
            return
        obj = next(
            (o for o in state.battlefield if o.id == tid), None
        )
        if obj is None:
            return
        obj.temp_power_bonus += x
        obj.temp_toughness_bonus += x
        state.log.append(
            f"{obj.printing.name} gets +{x}/+{x} UEOT (source power)"
        )

    def describe(self) -> str:
        return (
            "another target creature you control gets +X/+X until end "
            "of turn, where X is this creature's power"
        )


@dataclass(frozen=True)
class DoubleTargetCreaturesPowerUEOT(Effect):
    """Target creature you control has its effective power doubled
    until end of turn. Implemented by adding the target's current
    effective power as a temp_power_bonus.

    Matches Mightform Harmonizer's landfall trigger. Simplification:
    the bonus is a one-time snapshot at resolution — further counter
    gains or other pumps don't re-double within the same turn.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature
            and o.controller_id == controller_id
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import effective_power

        if not targets:
            return
        kind, tid = targets[0]
        if kind != "creature":
            return
        obj = next(
            (o for o in state.battlefield if o.id == tid), None
        )
        if obj is None:
            return
        snapshot = effective_power(state, obj)
        if snapshot <= 0:
            return
        obj.temp_power_bonus += snapshot
        state.log.append(
            f"{obj.printing.name}'s power is doubled UEOT "
            f"(+{snapshot} temp power)"
        )

    def describe(self) -> str:
        return "double the power of target creature you control until end of turn"


@dataclass(frozen=True)
class DiscardHandThenDrawN(Effect):
    """Discard every card in your hand, then draw ``amount`` cards.

    Matches Vaultguard Trooper's conditional end-step ability. Acts
    on the CONTROLLER's hand. No agent decision — the card is always
    accepted (consistent with our other "may do X" simplifications).
    """

    amount: int = 2

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone

        p = state.player_by_id(controller_id)
        # Discard every card.
        discarded_count = 0
        while p.hand:
            card = p.hand.pop(0)
            card.zone = Zone.GRAVEYARD
            p.graveyard.append(card)
            discarded_count += 1
        state.log.append(
            f"P{controller_id} discards hand ({discarded_count} cards)"
        )
        # Draw N cards.
        drew = 0
        for _ in range(self.amount):
            if not p.library:
                break
            card = p.library.pop(0)
            card.zone = Zone.HAND
            p.hand.append(card)
            drew += 1
        state.log.append(
            f"P{controller_id} draws {drew} card(s)"
        )

    def describe(self) -> str:
        return f"discard your hand, then draw {self.amount} cards"


@dataclass(frozen=True)
class PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower(Effect):
    """Put X +1/+1 counters on each creature you control, where X is
    this effect's source's effective power. Reads
    ``state.resolving_source`` for the power. No-op if source is None
    or X <= 0.

    Matches Ouroboroid's beginning-of-combat trigger.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import add_plus_one_counters, effective_power

        source = state.resolving_source
        if source is None:
            return
        x = effective_power(state, source)
        if x <= 0:
            return
        count = 0
        for obj in state.battlefield:
            if obj.controller_id != controller_id:
                continue
            if not obj.printing.is_creature:
                continue
            add_plus_one_counters(state, obj, x)
            count += 1
        state.log.append(
            f"P{controller_id}'s {count} creature(s) each get {x} "
            f"+1/+1 counter(s) (source power)"
        )

    def describe(self) -> str:
        return (
            "put X +1/+1 counters on each creature you control, where X "
            "is this creature's power"
        )


@dataclass(frozen=True)
class FamishedWorldsireETBEffect(Effect):
    """Famished Worldsire's ETB: "Look at the top X cards of your
    library, where X is this creature's power. Put any number of land
    cards from among them onto the battlefield tapped, then shuffle."

    Reads state.resolving_source to compute X from the source's
    effective power (post-Devour counters). Picks all land cards from
    the top-X (a strong simplification — the oracle allows choosing
    "any number", but greedy land-picking is strictly ramp-positive).
    Non-land cards go back into the library (bottom, random order).
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        import random as _random
        from mtg_bot.game import Zone, effective_power
        from mtg_bot.turn import fire_landfall_triggers

        source = state.resolving_source
        if source is None:
            return
        x = effective_power(state, source)
        if x <= 0:
            return
        p = state.player_by_id(controller_id)
        examined = p.library[:x]
        lands = [c for c in examined if c.printing.is_land]
        rest = [c for c in examined if c not in lands]
        for land in lands:
            p.library.remove(land)
            land.zone = Zone.BATTLEFIELD
            land.tapped = True
            land.controller_id = controller_id
            state.battlefield.append(land)
            state.log.append(
                f"P{controller_id} puts {land.printing.name} onto the "
                f"battlefield tapped (Famished Worldsire)"
            )
            fire_landfall_triggers(state, land)
        # Shuffle what's left (rest goes back where it was, then the
        # whole library is shuffled per oracle).
        rng = _random.Random(
            hash(("famished_shuffle", state.turn_number, controller_id,
                  len(p.library)))
        )
        rng.shuffle(p.library)

    def describe(self) -> str:
        return (
            "look at the top X cards of your library, where X is this "
            "creature's power; put any number of land cards from among "
            "them onto the battlefield tapped, then shuffle"
        )


@dataclass(frozen=True)
class PutCardFromGraveyardOnBottomOfLibrary(Effect):
    """Put target card from a graveyard on the bottom of its owner's
    library. Matches Chrome Companion's activated ability. Any
    graveyard is a legal target source (either player's).
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        from mtg_bot.game import Zone

        return [
            ("card_in_graveyard", c.id)
            for p in state.players
            for c in p.graveyard
            if c.zone == Zone.GRAVEYARD
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "card_in_graveyard":
            return
        for p in state.players:
            card = next((c for c in p.graveyard if c.id == target_id), None)
            if card is None:
                continue
            p.graveyard.remove(card)
            card.zone = Zone.LIBRARY
            p.library.append(card)  # bottom = end of list
            state.log.append(
                f"{card.printing.name} put on the bottom of "
                f"P{p.id}'s library"
            )
            return

    def describe(self) -> str:
        return (
            "put target card from a graveyard on the bottom of its "
            "owner's library"
        )


@dataclass(frozen=True)
class PutPlusOneCounterOnEachOfUpToNTargetCreatures(Effect):
    """Put a +1/+1 counter on each of up to ``max_n`` target creatures.

    Matches "put a +1/+1 counter on each of up to two target creatures"
    templating (Weftblade Enhancer). Targets are selected by the agent
    via repeated choose_target calls; effect resolves for each valid
    target that's still a creature on the battlefield.
    """

    max_n: int = 2

    def requires_target(self) -> bool:
        return True

    def target_count_range(self) -> tuple[int, int]:
        return (0, self.max_n)

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        for kind, target_id in targets:
            if kind != "creature":
                continue
            tgt = next(
                (o for o in state.battlefield if o.id == target_id), None
            )
            if tgt is None:
                continue
            tgt.plus_one_counters += 1
            state.log.append(
                f"+1/+1 counter on {tgt.printing.name} "
                f"(now {tgt.plus_one_counters})"
            )

    def describe(self) -> str:
        return (
            f"put a +1/+1 counter on each of up to {self.max_n} target "
            f"creatures"
        )


@dataclass(frozen=True)
class SelfcraftMechanETBEffect(Effect):
    """Selfcraft Mechan's ETB: "You may sacrifice an artifact. When you
    do, put a +1/+1 counter on target creature and draw a card."

    Simplification: "may" is treated as yes whenever an artifact exists
    to sacrifice (consistent with other OptionalSac effects). If the
    controller has no artifact, the whole rider fizzles. Target creature
    is selected via the agent's choose_target before resolve (via the
    standard target-selection pipeline).
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import draw_card, sacrifice as _sacrifice

        p = state.player_by_id(controller_id)
        artifacts = [
            o for o in state.battlefield
            if o.controller_id == controller_id and o.printing.is_artifact
        ]
        if not artifacts:
            state.log.append(
                f"Selfcraft Mechan: no artifact to sacrifice — fizzles"
            )
            return
        # Agent picks which artifact to sacrifice.
        if p.agent is not None:
            pick_id = p.agent.choose_sacrifice(
                state, controller_id, [o.id for o in artifacts]
            )
            chosen = next(
                (o for o in artifacts if o.id == pick_id), artifacts[0]
            )
        else:
            chosen = artifacts[0]
        state.log.append(
            f"P{controller_id} sacrifices {chosen.printing.name} "
            f"(Selfcraft Mechan)"
        )
        _sacrifice(state, chosen)
        # Apply counter to chosen target creature (if still on battlefield).
        if targets:
            kind, tid = targets[0]
            if kind == "creature":
                tgt = next(
                    (o for o in state.battlefield if o.id == tid), None
                )
                if tgt is not None:
                    tgt.plus_one_counters += 1
                    state.log.append(
                        f"+1/+1 counter on {tgt.printing.name} "
                        f"(now {tgt.plus_one_counters})"
                    )
        # Draw a card either way — the sacrifice happened, so the
        # reflexive trigger's effect resolves fully.
        draw_card(state, controller_id)

    def describe(self) -> str:
        return (
            "you may sacrifice an artifact; if you do, put a +1/+1 "
            "counter on target creature and draw a card"
        )


@dataclass(frozen=True)
class DrawCardsEqualToResolvingCombatDamage(Effect):
    """Draw a number of cards equal to
    ``state.resolving_combat_damage_amount``. Matches Starwinder's
    "you may draw that many cards" observer trigger (the "may" is
    simplified to always yes, consistent with other OptionalXyz
    simplifications in this engine).

    No-op if the resolving amount is 0 (e.g. accidentally invoked
    outside a combat-damage trigger).
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import draw_card

        amount = state.resolving_combat_damage_amount
        if amount <= 0:
            return
        for _ in range(amount):
            draw_card(state, controller_id)
        state.log.append(
            f"P{controller_id} draws {amount} cards (combat-damage trigger)"
        )

    def describe(self) -> str:
        return "you may draw that many cards"


@dataclass(frozen=True)
class TerrapactIntimidatorETBEffect(Effect):
    """Terrapact Intimidator's ETB: "Target opponent may have you create
    two Lander tokens. If they don't, put two +1/+1 counters on this
    creature."

    Targets a player (the chosen opponent). The opponent then picks:
    option 0 = controller creates two Landers; option 1 = controller
    puts two +1/+1 counters on the source. Reads state.resolving_source
    for the source permanent.
    """

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
        from mtg_bot.cards import TOKEN_PRINTINGS
        from mtg_bot.game import Zone

        source = state.resolving_source
        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "player":
            return
        opponent = state.player_by_id(target_id)
        if opponent.has_lost or opponent.agent is None:
            return
        modes = ["have controller create two Lander tokens", "decline"]
        choice = opponent.agent.choose_mode(state, opponent.id, modes)
        if choice == 0:
            lander_printing = TOKEN_PRINTINGS["Lander"]
            for _ in range(2):
                token = state.new_object(
                    lander_printing, controller_id, Zone.BATTLEFIELD,
                )
                state.battlefield.append(token)
            state.log.append(
                f"P{opponent.id} elected — P{controller_id} creates "
                f"two Lander tokens"
            )
        else:
            if source is not None:
                source.plus_one_counters += 2
                state.log.append(
                    f"P{opponent.id} declined — {source.printing.name} "
                    f"gets two +1/+1 counters (now "
                    f"{source.plus_one_counters})"
                )

    def describe(self) -> str:
        return (
            "target opponent may have you create two Lander tokens; if "
            "they don't, put two +1/+1 counters on this creature"
        )


def _multicolored_permanents_count(
    state: "GameState", controller_id: int
) -> int:
    """Count permanents the controller controls whose mana cost has
    two or more colors. Matches the "multicolored permanent" filter
    used by Infinite Guideline Station.
    """
    count = 0
    for o in state.battlefield:
        if o.controller_id != controller_id:
            continue
        colors = o.printing.mana_cost.colors
        if len(colors) >= 2:
            count += 1
    return count


@dataclass(frozen=True)
class CreateTokenPerMulticoloredPermanent(Effect):
    """Create a ``token_printing`` token (optionally tapped) for each
    multicolored permanent the controller controls.

    Matches Infinite Guideline Station's ETB.
    """

    token_printing: "CardPrinting"
    tapped: bool = True

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.actions import put_into_battlefield
        from mtg_bot.game import Zone

        n = _multicolored_permanents_count(state, controller_id)
        if n <= 0:
            state.log.append(
                f"P{controller_id} controls 0 multicolored permanents "
                f"— no tokens created"
            )
            return
        for _ in range(n):
            obj = state.new_object(
                self.token_printing, owner_id=controller_id,
                zone=Zone.BATTLEFIELD,
            )
            put_into_battlefield(state, obj, controller_id)
            if self.tapped:
                obj.tapped = True
        state.log.append(
            f"P{controller_id} creates {n} "
            f"{self.token_printing.name} tokens "
            f"(multicolored-permanent count)"
        )

    def describe(self) -> str:
        return (
            f"create a tapped {self.token_printing.name} token for each "
            f"multicolored permanent you control"
        )


@dataclass(frozen=True)
class DrawCardPerMulticoloredPermanent(Effect):
    """Draw one card for each multicolored permanent you control.
    Matches Infinite Guideline Station's attack trigger."""

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone

        n = _multicolored_permanents_count(state, controller_id)
        p = state.player_by_id(controller_id)
        drew = 0
        for _ in range(n):
            if not p.library:
                break
            card = p.library.pop(0)
            card.zone = Zone.HAND
            p.hand.append(card)
            drew += 1
        state.log.append(
            f"P{controller_id} draws {drew} cards "
            f"(multicolored-permanent count)"
        )

    def describe(self) -> str:
        return "draw a card for each multicolored permanent you control"


@dataclass(frozen=True)
class DyadrineAttackEffect(Effect):
    """Dyadrine, Synthesis Amalgam's attack trigger:
    "Whenever you attack, you may remove a +1/+1 counter from each of
    two creatures you control. If you do, draw a card and create a
    2/2 colorless Robot artifact creature token."

    Simplifications:
    - Agent always opts to pay the cost when possible (consistent
      with other OptionalSac-like effects in the codebase).
    - The two creatures are picked by iteration order — the agent's
      choose_sacrifice hook is re-used to select one creature at a
      time so at least some agency is exposed.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.actions import put_into_battlefield
        from mtg_bot.cards import TOKEN_PRINTINGS
        from mtg_bot.game import Zone

        p = state.player_by_id(controller_id)
        candidates = [
            o for o in state.battlefield
            if o.controller_id == controller_id
            and o.printing.is_creature
            and o.plus_one_counters > 0
        ]
        if len(candidates) < 2:
            state.log.append(
                "Dyadrine's attack trigger: fewer than 2 creatures "
                "with +1/+1 counters — skipped"
            )
            return
        picks: list = []
        remaining = list(candidates)
        for _ in range(2):
            chosen = remaining[0]
            if p.agent is not None:
                pick_id = p.agent.choose_sacrifice(
                    state, controller_id, [o.id for o in remaining]
                )
                chosen = next(
                    (o for o in remaining if o.id == pick_id),
                    remaining[0],
                )
            chosen.plus_one_counters -= 1
            picks.append(chosen)
            remaining.remove(chosen)
            state.log.append(
                f"Dyadrine removes +1/+1 counter from "
                f"{chosen.printing.name} (now {chosen.plus_one_counters})"
            )
        # Draw a card.
        if p.library:
            card = p.library.pop(0)
            card.zone = Zone.HAND
            p.hand.append(card)
            state.log.append(
                f"Dyadrine: P{controller_id} draws {card.printing.name}"
            )
        # Create the Robot token.
        token = state.new_object(
            TOKEN_PRINTINGS["Robot"], owner_id=controller_id,
            zone=Zone.BATTLEFIELD,
        )
        put_into_battlefield(state, token, controller_id)
        state.log.append(
            f"Dyadrine: P{controller_id} creates a Robot token"
        )

    def describe(self) -> str:
        return (
            "you may remove a +1/+1 counter from each of two creatures "
            "you control; if you do, draw a card and create a 2/2 "
            "colorless Robot artifact creature token"
        )


@dataclass(frozen=True)
class PutLoyaltyCounterOnSelf(Effect):
    """Put ``amount`` loyalty counter(s) on the ability's source.

    Used by planeswalker "whenever ..." triggers that grow their own
    loyalty (Tezzeret's "whenever an artifact you control enters, put
    a loyalty counter on Tezzeret"). Reads state.resolving_source.
    """

    amount: int = 1

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        source = state.resolving_source
        if source is None:
            return
        source.loyalty_counters += self.amount
        state.log.append(
            f"{source.printing.name} gains {self.amount} loyalty "
            f"counter(s) (now {source.loyalty_counters})"
        )

    def describe(self) -> str:
        return f"put {self.amount} loyalty counter(s) on ~"


@dataclass(frozen=True)
class OptionalPutCreatureFromHandOntoBattlefield(Effect):
    """"You may put a creature card from your hand onto the battlefield."

    Matches Sledge-Class Seedship's attack trigger (and similar
    "cheat creatures into play" effects). Agent picks via
    ``choose_card_from_library`` (reusing the generic "pick one id
    from a list" hook — the hook is zone-agnostic). Declining is
    legal — the effect silently does nothing.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.actions import put_into_battlefield

        p = state.player_by_id(controller_id)
        options = [c for c in p.hand if c.printing.is_creature]
        if not options:
            return
        chosen_id = None
        if p.agent is not None:
            chosen_id = p.agent.choose_card_from_library(
                state, controller_id, [c.id for c in options]
            )
        if chosen_id is None:
            return
        card = next((c for c in options if c.id == chosen_id), None)
        if card is None:
            return
        p.hand.remove(card)
        put_into_battlefield(state, card, controller_id)
        state.log.append(
            f"P{controller_id} puts {card.printing.name} from hand "
            f"onto the battlefield"
        )

    def describe(self) -> str:
        return "you may put a creature card from your hand onto the battlefield"


@dataclass(frozen=True)
class CloseEncounterEffect(Effect):
    """Close Encounter `{1}{G}`:
    "As an additional cost to cast this spell, choose a creature you
    control or a warped creature card you own in exile.
    Close Encounter deals damage equal to the power of the chosen
    creature or card to target creature."

    Reads state.resolving_additional_cost_choice_id to know which
    creature the caster designated, then deals damage equal to that
    creature's effective power to the chosen target creature.

    Simplification: the "warped creature card you own in exile" half
    is dropped — the additional-cost pick is restricted to creatures
    you control, which is almost always available when casting this.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import effective_power

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "creature":
            return
        chosen_id = state.resolving_additional_cost_choice_id
        if chosen_id is None:
            return
        chosen = next(
            (o for o in state.battlefield if o.id == chosen_id), None
        )
        if chosen is None:
            # The designated creature left the battlefield before this
            # resolved (e.g., destroyed in response) — oracle says the
            # spell still deals damage equal to its power from when it
            # was designated. We don't track a P/T snapshot at cost-pay
            # time, so fall back to 0.
            amount = 0
        else:
            amount = effective_power(state, chosen)
        _apply_damage(state, targets[0], amount)

    def describe(self) -> str:
        return (
            "deals damage equal to the designated creature's power to "
            "target creature"
        )


@dataclass(frozen=True)
class ConsultTheStarChartsEffect(Effect):
    """Consult the Star Charts `{1}{U}` (kicker `{1}{U}`):
    "Look at the top X cards of your library, where X is the number of
    lands you control. Put one of those cards into your hand. If this
    spell was kicked, put two of those cards into your hand instead.
    Put the rest on the bottom of your library in a random order."

    Reads state.resolving_kicked to choose between 1 and 2 cards to
    keep. Agent picks the kept cards via ``choose_card_from_library``.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        import random as _random
        from mtg_bot.game import Zone

        p = state.player_by_id(controller_id)
        x = sum(
            1 for o in state.battlefield
            if o.controller_id == controller_id and o.printing.is_land
        )
        if x == 0 or not p.library:
            state.log.append(
                f"Consult the Star Charts: X={x}, nothing to look at"
            )
            return
        examined = p.library[:x]
        keep = 2 if state.resolving_kicked else 1
        kept_cards: list = []
        remaining = list(examined)
        for _ in range(keep):
            if not remaining:
                break
            chosen_id = None
            if p.agent is not None:
                chosen_id = p.agent.choose_card_from_library(
                    state, controller_id, [c.id for c in remaining]
                )
            if chosen_id is None:
                chosen_id = remaining[0].id
            card = next(
                (c for c in remaining if c.id == chosen_id), remaining[0]
            )
            kept_cards.append(card)
            remaining.remove(card)
        for card in kept_cards:
            p.library.remove(card)
            card.zone = Zone.HAND
            p.hand.append(card)
            state.log.append(
                f"P{controller_id} puts {card.printing.name} into hand "
                f"from Consult the Star Charts"
            )
        # Bottom the rest in random order.
        for card in remaining:
            p.library.remove(card)
        rng = _random.Random(
            hash(("consult", state.turn_number, controller_id,
                  len(p.library)))
        )
        rng.shuffle(remaining)
        p.library.extend(remaining)
        state.log.append(
            f"Consult the Star Charts: put {len(remaining)} cards on "
            f"the bottom in random order"
        )

    def describe(self) -> str:
        return (
            "look at the top X cards of your library (X = lands you "
            "control); put one into your hand (two if kicked); put "
            "the rest on the bottom in a random order"
        )


@dataclass(frozen=True)
class LookAtTopNRevealOrCounter(Effect):
    """Look at the top ``n`` cards of your library. The controller may
    reveal one card matching ``filter_name`` and put it into hand.
    Put the rest on the bottom of the library in a random order. If no
    card was revealed (either because none matched or the agent
    declined), put a +1/+1 counter on the source.

    Matches Pulsar Squadron Ace's ETB with ``n=5``, ``filter_name=
    "spacecraft"``. Reads ``state.resolving_source`` for the counter
    placement.

    The "random order" shuffle is seeded deterministically on the turn
    number + controller + library length so tests remain reproducible.
    """

    n: int = 5
    filter_name: str = "spacecraft"

    def _matches(self, printing) -> bool:
        fn = self.filter_name
        if fn == "spacecraft":
            return printing.is_spacecraft
        if fn == "creature":
            return printing.is_creature
        if fn == "artifact":
            return printing.is_artifact
        return False

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        import random as _random
        from mtg_bot.game import Zone

        p = state.player_by_id(controller_id)
        examined = p.library[: self.n]
        options = [c for c in examined if self._matches(c.printing)]
        chosen_id = None
        if options and p.agent is not None:
            chosen_id = p.agent.choose_card_from_library(
                state, controller_id, [c.id for c in options]
            )
        revealed_card = None
        if chosen_id is not None:
            revealed_card = next(
                (c for c in options if c.id == chosen_id), None
            )
        if revealed_card is not None:
            p.library.remove(revealed_card)
            revealed_card.zone = Zone.HAND
            p.hand.append(revealed_card)
            state.log.append(
                f"P{controller_id} reveals {revealed_card.printing.name} "
                f"and puts it into hand"
            )
        else:
            state.log.append(
                f"P{controller_id} reveals nothing from the top "
                f"{len(examined)} cards"
            )
            source = state.resolving_source
            if source is not None and source in state.battlefield:
                source.plus_one_counters += 1
                state.log.append(
                    f"{source.printing.name} gets a +1/+1 counter "
                    f"(now {source.plus_one_counters})"
                )
        # Bottom the remainder in a random order. Take up to n cards off
        # the top (those we examined except the revealed one if any) and
        # shuffle them onto the bottom.
        remaining_examined = [
            c for c in examined if c is not revealed_card
        ]
        for c in remaining_examined:
            p.library.remove(c)
        rng = _random.Random(
            hash(("look_top_n", state.turn_number, controller_id,
                  len(p.library)))
        )
        rng.shuffle(remaining_examined)
        p.library.extend(remaining_examined)

    def describe(self) -> str:
        return (
            f"look at the top {self.n} cards of your library; you may "
            f"reveal a {self.filter_name} card from among them and put "
            f"it into your hand; put the rest on the bottom of your "
            f"library in a random order; if you didn't put a card into "
            f"your hand this way, put a +1/+1 counter on ~"
        )


@dataclass(frozen=True)
class LookAtTopTwoSplitHandGraveyard(Effect):
    """Look at the top two cards of your library; put one into your
    hand, the other into your graveyard.

    Matches Codecracker Hound's ETB. The agent's choice via
    choose_surveil decides which pile each card goes to (surveil=True
    means graveyard, False means hand — mirrors the surveil semantics).
    Asymmetric: exactly one card ends up in hand, exactly one in
    graveyard (or fewer if the library has < 2 cards).
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone

        p = state.player_by_id(controller_id)
        if not p.library:
            return
        # Take the top 2 (or 1 if only one left).
        examined = p.library[:2]
        # Asks the agent per card; first "True" (graveyard) pick goes
        # there, then the remainder to hand. Fallback heuristic: top
        # card → hand, second → graveyard.
        if len(examined) == 1:
            card = examined[0]
            p.library.remove(card)
            card.zone = Zone.HAND
            p.hand.append(card)
            state.log.append(
                f"P{controller_id} draws {card.printing.name}"
            )
            return
        # Two cards; pick the one to send to hand. The other goes to
        # graveyard. Default: top card → hand.
        if p.agent is None:
            hand_card = examined[0]
            gy_card = examined[1]
        else:
            hand_card = examined[0]
            if p.agent.choose_surveil(state, p.id, hand_card.id):
                # Agent says "mill this one" → swap: other → hand.
                hand_card = examined[1]
                gy_card = examined[0]
            else:
                gy_card = examined[1]
        p.library.remove(hand_card)
        hand_card.zone = Zone.HAND
        p.hand.append(hand_card)
        p.library.remove(gy_card)
        gy_card.zone = Zone.GRAVEYARD
        p.graveyard.append(gy_card)
        state.log.append(
            f"P{controller_id} puts {hand_card.printing.name} into "
            f"hand and {gy_card.printing.name} into graveyard"
        )

    def describe(self) -> str:
        return (
            "look at the top two cards of your library; put one into "
            "your hand and the other into your graveyard"
        )


@dataclass(frozen=True)
class Surveil(Effect):
    """Surveil N: look at the top N cards of your library; for each one, you
    may put it into your graveyard. The rest stay on top in their original
    order. Decision delegated to the controller's agent (choose_surveil).

    If ``use_artifact_count`` is True the amount is recomputed at
    resolution as the controller's current artifact count — matches
    Cerebral Download's "Surveil X, where X is the number of artifacts
    you control".
    """

    amount: int = 1
    use_artifact_count: bool = False

    def _amount(self, state: "GameState", controller_id: int) -> int:
        if not self.use_artifact_count:
            return self.amount
        return sum(
            1 for o in state.battlefield
            if o.controller_id == controller_id and o.printing.is_artifact
        )

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone

        p = state.player_by_id(controller_id)
        n = self._amount(state, controller_id)
        milled = 0
        # Examine the top N cards in order. Mill ones the agent chooses;
        # keep the rest on top in their original order.
        examined = p.library[: n]
        keep: list = []
        for card in examined:
            if p.agent is not None and p.agent.choose_surveil(state, p.id, card.id):
                p.library.remove(card)
                card.zone = Zone.GRAVEYARD
                p.graveyard.append(card)
                milled += 1
            else:
                keep.append(card)
        state.log.append(
            f"P{controller_id} surveils {n} ({milled} milled)"
        )

    def describe(self) -> str:
        if self.use_artifact_count:
            return "surveil X, where X is the number of artifacts you control"
        return f"surveil {self.amount}"


@dataclass(frozen=True)
class SelfMill(Effect):
    """Controller mills ``amount`` cards from the top of their own library.

    Matches oracle text like "mill three cards" on triggered abilities,
    where no target selection is needed.
    """

    amount: int = 1

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone

        p = state.player_by_id(controller_id)
        milled = 0
        for _ in range(self.amount):
            if not p.library:
                break
            card = p.library.pop(0)
            card.zone = Zone.GRAVEYARD
            p.graveyard.append(card)
            milled += 1
        state.log.append(f"P{controller_id} mills {milled} cards")

    def describe(self) -> str:
        return f"mill {self.amount} cards"


@dataclass(frozen=True)
class MillTargetPlayer(Effect):
    """Target player puts the top N cards of their library into their
    graveyard.

    If ``use_controller_life`` is True, N is the controller's current life
    total (minimum 0) instead of ``amount`` — matches Space-Time Anomaly.
    Running out of cards mid-mill simply stops; empty-library loss is
    handled separately by the draw step.
    """

    amount: int = 1
    use_controller_life: bool = False

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("player", p.id) for p in state.players if not p.has_lost
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
        target = state.player_by_id(target_id)
        if self.use_controller_life:
            n = max(0, state.player_by_id(controller_id).life)
        else:
            n = self.amount
        milled = 0
        for _ in range(n):
            if not target.library:
                break
            card = target.library.pop(0)
            card.zone = Zone.GRAVEYARD
            target.graveyard.append(card)
            milled += 1
        state.log.append(f"P{target_id} mills {milled} cards")

    def describe(self) -> str:
        if self.use_controller_life:
            return (
                "target player mills cards equal to your life total"
            )
        return f"target player mills {self.amount} cards"


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
class PumpTargetCreatureUntilEOT(Effect):
    """Target creature gets +power/+toughness and optionally gains keywords
    until end of turn.

    Matches oracle text like "Target creature gets +3/+0 and gains first
    strike and reach until end of turn." Bonuses stack additively and are
    cleared at cleanup. Negative bonuses model "target creature gets
    -N/-0" debuffs.
    """

    power_bonus: int = 0
    toughness_bonus: int = 0
    granted_keywords: frozenset[str] = frozenset()
    you_control_only: bool = False  # restrict to "target creature you control"
    opponents_only: bool = False  # restrict to "an opponent controls"

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature
            and (not self.you_control_only or o.controller_id == controller_id)
            and (not self.opponents_only or o.controller_id != controller_id)
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "creature":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None:
            return
        obj.temp_power_bonus += self.power_bonus
        obj.temp_toughness_bonus += self.toughness_bonus
        if self.granted_keywords:
            obj.temp_keywords = obj.temp_keywords | self.granted_keywords
        state.log.append(
            f"{obj.printing.name} gets "
            f"+{self.power_bonus}/+{self.toughness_bonus} until end of turn"
            + (f" and gains {', '.join(sorted(self.granted_keywords))}"
               if self.granted_keywords else "")
        )

    def describe(self) -> str:
        parts: list[str] = []
        if self.power_bonus or self.toughness_bonus:
            parts.append(
                f"target creature gets +{self.power_bonus}/+{self.toughness_bonus}"
            )
        if self.granted_keywords:
            parts.append(
                f"gains {', '.join(sorted(self.granted_keywords))}"
            )
        return " and ".join(parts) + " until end of turn."


@dataclass(frozen=True)
class PumpTargetOtherArtifactYouControlUEOT(Effect):
    """Synthesizer Labship's 2+ tier trigger effect (simplified):
    up to one other target artifact you control that's a creature gets
    +power/+toughness and gains ``granted_keywords`` until end of turn.

    Simplification: the real card reads "up to one other target artifact
    you control becomes an artifact creature with base P/T 2/2 and gains
    flying UEOT". We drop the "becomes a creature" aspect (which needs
    layered continuous effects) and require the target to be a creature
    already — good for stationed Spacecraft and artifact creatures. The
    target filter still excludes the effect's own source ("other").
    """

    power_bonus: int = 0
    toughness_bonus: int = 0
    granted_keywords: frozenset[str] = frozenset()

    def requires_target(self) -> bool:
        return True

    def target_count_range(self) -> tuple[int, int]:
        # "Up to one" — declining is legal.
        return (0, 1)

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        from mtg_bot.game import is_creature_now

        source = state.resolving_source
        source_id = source.id if source is not None else -1
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.controller_id == controller_id
            and o.printing.is_artifact
            and is_creature_now(o)
            and o.id != source_id
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "creature":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None:
            return
        obj.temp_power_bonus += self.power_bonus
        obj.temp_toughness_bonus += self.toughness_bonus
        if self.granted_keywords:
            obj.temp_keywords = obj.temp_keywords | self.granted_keywords
        state.log.append(
            f"{obj.printing.name} gets "
            f"+{self.power_bonus}/+{self.toughness_bonus}"
            + (f" and gains {', '.join(sorted(self.granted_keywords))}"
               if self.granted_keywords else "")
            + " until end of turn"
        )

    def describe(self) -> str:
        kw = ""
        if self.granted_keywords:
            kw = f" and gains {', '.join(sorted(self.granted_keywords))}"
        return (
            f"up to one other target artifact you control gets "
            f"+{self.power_bonus}/+{self.toughness_bonus}{kw} until end of turn"
        )


@dataclass(frozen=True)
class DealNDamageToEachCreature(Effect):
    """Deal ``amount`` damage to each creature on the battlefield.

    Snapshot semantics: the victim list is captured before any damage
    is applied, so any deaths mid-pass don't affect what gets damaged.
    Marks damage via _apply_damage (the same helper used by targeted
    burn), which routes through creature toughness for SBAs.
    """

    amount: int

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        victims = [
            o for o in state.battlefield if o.printing.is_creature
        ]
        for o in victims:
            _apply_damage(state, ("creature", o.id), self.amount)

    def describe(self) -> str:
        return f"deals {self.amount} damage to each creature"


@dataclass(frozen=True)
class OptionalSacArtifactForEffect(Effect):
    """"You may sacrifice an artifact. If you do, [inner_effect]."

    Similar to OptionalSacAnotherForEffect but doesn't require a
    ``state.resolving_source`` for self-exclusion — the "another"
    clause isn't in the oracle text (Lithobraking: "you may sacrifice
    an artifact"). Agent picks the sacrifice via ``choose_sacrifice``.
    """

    inner_effect: Effect

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        options = [
            o for o in state.battlefield
            if o.controller_id == controller_id and o.printing.is_artifact
        ]
        if not options:
            return
        p = state.player_by_id(controller_id)
        if p.agent is None:
            chosen = options[0]
        else:
            pick_id = p.agent.choose_sacrifice(
                state, controller_id, [o.id for o in options]
            )
            chosen = next(
                (o for o in options if o.id == pick_id), options[0]
            )
        from mtg_bot.turn import sacrifice as _sacrifice

        state.log.append(
            f"P{controller_id} optionally sacrifices {chosen.printing.name}"
        )
        _sacrifice(state, chosen)
        self.inner_effect.resolve(state, controller_id, ())

    def describe(self) -> str:
        return (
            f"you may sacrifice an artifact; if you do, "
            f"{self.inner_effect.describe()}"
        )


@dataclass(frozen=True)
class OptionalSacAnotherForEffect(Effect):
    """"You may sacrifice another creature or artifact. If you do,
    [inner_effect]."

    General version of OptionalSacAnotherForPumpSelfUEOT: the inner
    effect (e.g., DrawCards) runs only if the sacrifice is paid. Agent
    decides via choose_sacrifice; no legal option → silent no-op.
    """

    inner_effect: Effect

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        source = state.resolving_source
        if source is None:
            return
        options = [
            o for o in state.battlefield
            if o.controller_id == controller_id
            and o.id != source.id
            and (o.printing.is_creature or o.printing.is_artifact)
        ]
        if not options:
            return
        p = state.player_by_id(controller_id)
        if p.agent is None:
            chosen = options[0]
        else:
            pick_id = p.agent.choose_sacrifice(
                state, controller_id, [o.id for o in options]
            )
            chosen = next(
                (o for o in options if o.id == pick_id), options[0]
            )
        from mtg_bot.turn import sacrifice as _sacrifice

        state.log.append(
            f"P{controller_id} sacrifices {chosen.printing.name} "
            f"for {source.printing.name}'s trigger"
        )
        _sacrifice(state, chosen)
        # The source itself might have been sacrificed — clear resolving
        # source temporarily? No — state.resolving_source still points to
        # the source object even if it's off the battlefield now. Inner
        # effect can still read it if needed (e.g., for a self-target),
        # but for DrawCards/GainLife etc. we only need controller_id.
        self.inner_effect.resolve(state, controller_id, ())

    def describe(self) -> str:
        return (
            f"you may sacrifice another creature or artifact; if you "
            f"do, {self.inner_effect.describe()}"
        )


@dataclass(frozen=True)
class OptionalSacAnotherForPumpSelfUEOT(Effect):
    """"You may sacrifice another creature or artifact. If you do, this
    creature gets +P/+T until end of turn."

    Agent decides via choose_sacrifice-style hook — we reuse the
    sacrifice agent method and treat a "no legal option" situation as
    decline. For the RandomAgent the heuristic is "pay if an option
    exists", matching the card's near-always-beneficial pump.
    """

    power_bonus: int = 0
    toughness_bonus: int = 0
    granted_keywords: frozenset[str] = frozenset()

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        source = state.resolving_source
        if source is None:
            return
        options = [
            o for o in state.battlefield
            if o.controller_id == controller_id
            and o.id != source.id
            and (o.printing.is_creature or o.printing.is_artifact)
        ]
        if not options:
            return
        p = state.player_by_id(controller_id)
        if p.agent is None:
            # Defensive default: pay the cost when the agent is absent.
            chosen = options[0]
        else:
            pick_id = p.agent.choose_sacrifice(
                state, controller_id, [o.id for o in options]
            )
            chosen = next(
                (o for o in options if o.id == pick_id), options[0]
            )
        from mtg_bot.turn import sacrifice as _sacrifice

        state.log.append(
            f"P{controller_id} sacrifices {chosen.printing.name} "
            f"to pump {source.printing.name}"
        )
        _sacrifice(state, chosen)
        source.temp_power_bonus += self.power_bonus
        source.temp_toughness_bonus += self.toughness_bonus
        if self.granted_keywords:
            source.temp_keywords = (
                source.temp_keywords | self.granted_keywords
            )

    def describe(self) -> str:
        parts = []
        if self.power_bonus or self.toughness_bonus:
            parts.append(
                f"+{self.power_bonus}/+{self.toughness_bonus}"
            )
        if self.granted_keywords:
            parts.append(
                "gains " + ", ".join(sorted(self.granted_keywords))
            )
        body = " and ".join(parts) if parts else "pump"
        return (
            f"you may sacrifice another creature or artifact; if you "
            f"do, this creature gets {body} until end of turn"
        )


@dataclass(frozen=True)
class PumpSelfUntilEOT(Effect):
    """The ability's source gets +power/+toughness (and optional keywords)
    until end of turn. Reads state.resolving_source."""

    power_bonus: int = 0
    toughness_bonus: int = 0
    granted_keywords: frozenset[str] = frozenset()

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        source = state.resolving_source
        if source is None:
            return
        source.temp_power_bonus += self.power_bonus
        source.temp_toughness_bonus += self.toughness_bonus
        if self.granted_keywords:
            source.temp_keywords = source.temp_keywords | self.granted_keywords
        state.log.append(
            f"{source.printing.name} gets "
            f"+{self.power_bonus}/+{self.toughness_bonus} until end of turn"
        )

    def describe(self) -> str:
        return (
            f"this gets +{self.power_bonus}/+{self.toughness_bonus} "
            f"until end of turn"
        )


@dataclass(frozen=True)
class PumpCreaturesYouControlUntilEOT(Effect):
    """Each creature the controller controls gets +power/+toughness until
    end of turn (applied at resolution; creatures entering later don't get
    the bonus — Stage-3 simplification vs. a continuous effect).

    ``exclude_source=True`` models "other creatures you control" — reads
    ``state.resolving_source`` to skip the triggering permanent.
    """

    power_bonus: int = 0
    toughness_bonus: int = 0
    granted_keywords: frozenset[str] = frozenset()
    exclude_source: bool = False

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        source = state.resolving_source if self.exclude_source else None
        count = 0
        for obj in state.battlefield:
            if obj.controller_id != controller_id:
                continue
            if not obj.printing.is_creature:
                continue
            if source is not None and obj is source:
                continue
            obj.temp_power_bonus += self.power_bonus
            obj.temp_toughness_bonus += self.toughness_bonus
            if self.granted_keywords:
                obj.temp_keywords = obj.temp_keywords | self.granted_keywords
            count += 1
        scope = "other creatures" if self.exclude_source else "creatures"
        state.log.append(
            f"P{controller_id}'s {scope} ({count}) get "
            f"+{self.power_bonus}/+{self.toughness_bonus} until end of turn"
        )

    def describe(self) -> str:
        scope = "other creatures you control" if self.exclude_source else (
            "creatures you control"
        )
        return (
            f"{scope} get "
            f"+{self.power_bonus}/+{self.toughness_bonus} until end of turn"
        )


@dataclass(frozen=True)
class SearchLibraryForCard(Effect):
    """Search your library for a card matching the named filter, reveal
    it, put it into your hand, then shuffle.

    ``filter_name`` selects the filter applied to cards in the library:
      - ``"legendary_creature"`` — creature with Legendary supertype
      - ``"basic_plains"`` / ``"basic_island"`` / ... — specific basic
      - ``"creature_small"`` — creature with mana value ≤ ``max_mv``

    If ``may_fail`` is True, the controller may decline to fetch
    (shuffle happens either way). Always shuffles at the end — matches
    MTG wording.
    """

    filter_name: str
    max_mv: int = 0
    may_fail: bool = True

    def _matches(self, printing) -> bool:
        fn = self.filter_name
        if fn == "legendary_creature":
            return (
                printing.is_creature and "Legendary" in printing.supertypes
            )
        if fn.startswith("basic_"):
            wanted = fn[len("basic_"):].capitalize()
            return printing.is_basic_land and printing.name == wanted
        if fn == "creature_small":
            return (
                printing.is_creature
                and printing.mana_cost.total <= self.max_mv
            )
        if fn == "artifact":
            return printing.is_artifact
        if fn == "spacecraft":
            return printing.is_spacecraft
        return False

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        import random as _random
        from mtg_bot.game import Zone

        p = state.player_by_id(controller_id)
        options = [c for c in p.library if self._matches(c.printing)]
        if not options:
            state.log.append(
                f"P{controller_id} searches library — no "
                f"{self.filter_name} found"
            )
            return
        chosen_id = None
        if p.agent is not None:
            chosen_id = p.agent.choose_card_from_library(
                state, controller_id, [c.id for c in options]
            )
        if chosen_id is None:
            if self.may_fail:
                state.log.append(
                    f"P{controller_id} declines to fetch"
                )
                return
            chosen_id = options[0].id
        card = next((c for c in options if c.id == chosen_id), options[0])
        p.library.remove(card)
        card.zone = Zone.HAND
        p.hand.append(card)
        state.log.append(
            f"P{controller_id} fetches {card.printing.name} to hand"
        )
        # Shuffle (deterministic: seed by turn & player to remain
        # reproducible across test runs).
        rng = _random.Random(
            hash(("shuffle", state.turn_number, controller_id, card.id))
        )
        rng.shuffle(p.library)

    def describe(self) -> str:
        return (
            f"search your library for a {self.filter_name} card, reveal "
            f"it, put it into your hand, then shuffle"
        )


@dataclass(frozen=True)
class SearchLibraryForBasicLandTapped(Effect):
    """Search the controller's library for up to ``count`` basic land
    cards, put them onto the battlefield tapped, then shuffle.

    Stage 3 simplification: picks the FIRST ``count`` basic lands in
    library order (no extra shuffle). If fewer basic lands exist,
    puts what it finds.
    """

    count: int = 1

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone
        from mtg_bot.turn import fire_landfall_triggers

        p = state.player_by_id(controller_id)
        for _ in range(self.count):
            land = next(
                (c for c in p.library if c.printing.is_basic_land), None,
            )
            if land is None:
                state.log.append(
                    f"P{controller_id} searches but finds no more basic lands"
                )
                return
            p.library.remove(land)
            land.zone = Zone.BATTLEFIELD
            land.tapped = True
            land.controller_id = controller_id
            state.battlefield.append(land)
            state.log.append(
                f"P{controller_id} puts {land.printing.name} onto the "
                f"battlefield tapped"
            )
            fire_landfall_triggers(state, land)

    def describe(self) -> str:
        if self.count == 1:
            return (
                "search your library for a basic land card, put it onto "
                "the battlefield tapped, then shuffle"
            )
        return (
            f"search your library for up to {self.count} basic land "
            f"cards, put them onto the battlefield tapped, then shuffle"
        )


@dataclass(frozen=True)
class OptionalSacLandOrLanderForBasicLandRamp(Effect):
    """"You may sacrifice a land or Lander. If you do, search your
    library for up to ``land_count`` basic land cards, put them onto
    the battlefield tapped, then shuffle."

    Matches Larval Scoutlander's ETB. A "land or Lander" is: a land
    permanent, or a Lander token artifact. The agent picks via
    choose_sacrifice; if no legal option, the effect is a no-op.
    Following OptionalSac precedent, the "may" is always yes when
    possible.
    """

    land_count: int = 2

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import sacrifice as _sacrifice

        options = [
            o for o in state.battlefield
            if o.controller_id == controller_id
            and (o.printing.is_land or "Lander" in o.printing.subtypes)
        ]
        if not options:
            return
        p = state.player_by_id(controller_id)
        chosen = options[0]
        if p.agent is not None:
            pick_id = p.agent.choose_sacrifice(
                state, controller_id, [o.id for o in options]
            )
            chosen = next(
                (o for o in options if o.id == pick_id), options[0]
            )
        state.log.append(
            f"P{controller_id} sacrifices {chosen.printing.name} "
            f"(land/Lander ramp)"
        )
        _sacrifice(state, chosen)
        SearchLibraryForBasicLandTapped(count=self.land_count).resolve(
            state, controller_id,
        )

    def describe(self) -> str:
        return (
            f"you may sacrifice a land or Lander; if you do, search "
            f"your library for up to {self.land_count} basic land cards, "
            f"put them onto the battlefield tapped, then shuffle"
        )


@dataclass(frozen=True)
class ConditionalIfOpponentHasMoreLands(Effect):
    """Run ``effect`` only if an opponent controls more lands than the
    controller at resolution.

    Matches EoE's "if an opponent controls more lands than you" ETB
    riders (Sunstar Expansionist). Untargeted and untargeted-only.
    """

    effect: Effect

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        my_lands = sum(
            1 for o in state.battlefield
            if o.controller_id == controller_id and o.printing.is_land
        )
        enemy_max = 0
        for p in state.players:
            if p.id == controller_id or p.has_lost:
                continue
            count = sum(
                1 for o in state.battlefield
                if o.controller_id == p.id and o.printing.is_land
            )
            if count > enemy_max:
                enemy_max = count
        if enemy_max <= my_lands:
            state.log.append(
                "conditional skipped (no opponent has more lands)"
            )
            return
        self.effect.resolve(state, controller_id, targets)

    def describe(self) -> str:
        return (
            f"if an opponent controls more lands than you, "
            f"{self.effect.describe()}"
        )


@dataclass(frozen=True)
class ConditionalOnTappedCreatures(Effect):
    """Run ``effect`` only if the controller has at least ``min_count``
    tapped creatures on the battlefield at resolution.

    Matches the "if you control two or more tapped creatures" intervening-if
    clause on EoE cards like Flight-Deck Coordinator and Sunstar Chaplain.
    """

    effect: Effect
    min_count: int = 2

    def requires_target(self) -> bool:
        return self.effect.requires_target()

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return self.effect.legal_targets(state, controller_id)

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import is_creature_now

        tapped_count = sum(
            1 for o in state.battlefield
            if o.controller_id == controller_id
            and is_creature_now(o)
            and o.tapped
        )
        if tapped_count < self.min_count:
            state.log.append(
                f"conditional skipped (need {self.min_count} tapped creatures, "
                f"have {tapped_count})"
            )
            return
        self.effect.resolve(state, controller_id, targets)

    def describe(self) -> str:
        return (
            f"if you control {self.min_count} or more tapped creatures, "
            f"{self.effect.describe()}"
        )


@dataclass(frozen=True)
class ConditionalIfSourcePowerAtLeast(Effect):
    """Run ``effect`` only if the triggering source's effective power is
    at least ``threshold`` at resolution. Reads state.resolving_source
    for the source (typically set by the trigger dispatcher).

    Matches oracle wording like "while its power is 4 or greater" on
    Syr Vondam, Sunstar Exemplar's leaves-battlefield trigger.
    """

    effect: Effect
    threshold: int = 4

    def requires_target(self) -> bool:
        return self.effect.requires_target()

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return self.effect.legal_targets(state, controller_id)

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import effective_power

        source = state.resolving_source
        if source is None:
            state.log.append("power-threshold conditional has no source")
            return
        power = effective_power(state, source)
        if power < self.threshold:
            state.log.append(
                f"conditional skipped (need power ≥ {self.threshold}, "
                f"have {power})"
            )
            return
        self.effect.resolve(state, controller_id, targets)

    def describe(self) -> str:
        return (
            f"if this permanent's power is {self.threshold} or greater, "
            f"{self.effect.describe()}"
        )


@dataclass(frozen=True)
class DealDamageEachOpponent(Effect):
    """Deal ``amount`` damage to each living opponent. Untargeted — mass
    burn half of Ruinous Rampage's choice.
    """

    amount: int = 1

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        for p in state.players:
            if p.id == controller_id or p.has_lost:
                continue
            p.life -= self.amount
            state.log.append(
                f"P{p.id} takes {self.amount} (life: {p.life})"
            )

    def describe(self) -> str:
        return f"deals {self.amount} damage to each opponent"


@dataclass(frozen=True)
class ExileAllArtifactsWithManaValueAtMost(Effect):
    """Exile every artifact on the battlefield with mana value ≤ ``max_mv``.

    Ruinous Rampage's anti-artifact mode. Lander tokens (MV 0) are hit.
    """

    max_mv: int = 3

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import move_off_battlefield

        victims = [
            o for o in state.battlefield
            if o.printing.is_artifact and o.printing.mana_cost.total <= self.max_mv
        ]
        for obj in victims:
            state.log.append(f"{obj.printing.name} is exiled (mass-artifact)")
            move_off_battlefield(state, obj, destination="exile")

    def describe(self) -> str:
        return (
            f"exile all artifacts with mana value {self.max_mv} or less"
        )


@dataclass(frozen=True)
class ModalChooseOne(Effect):
    """A "choose one" spell or ability effect. Delegates mode pick to the
    controller's agent via ``choose_mode``, then resolves that mode.

    Currently supports modes that are EITHER untargeted OR require a
    single target; the chosen mode's ``legal_targets`` is surfaced through
    the spell-cast pipeline via ``requires_target``.

    Sequencing: we exit early at cast time if the caller only wants to
    know about targets — the chosen mode is cached on a mutable box since
    dataclasses are frozen. Simpler alternative: call choose_mode at
    resolve time and discard any pre-picked target if the mode is
    untargeted. We take the simpler path here.
    """

    modes: tuple[Effect, ...]

    def requires_target(self) -> bool:
        # Castability gate: the spell should be castable as long as ANY
        # mode is playable. If at least one mode is untargeted, the
        # player can always pick that mode — so don't gate on targets.
        # Only require a target when every mode needs one.
        return all(m.requires_target() for m in self.modes)

    def target_count_range(self) -> tuple[int, int]:
        any_targeted = any(m.requires_target() for m in self.modes)
        if not any_targeted:
            return (0, 0)
        all_targeted = all(m.requires_target() for m in self.modes)
        # min_t=0 for mixed modes (you might pick the untargeted mode);
        # min_t=1 when every mode needs a target. max_t=1 — we don't
        # model multi-target modes yet.
        return (1 if all_targeted else 0, 1)

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        # Union of all modes' legal targets. The picked mode's resolve
        # will ignore targets it doesn't use.
        out: list[Target] = []
        seen: set[Target] = set()
        for m in self.modes:
            if not m.requires_target():
                continue
            for t in m.legal_targets(state, controller_id):
                if t not in seen:
                    seen.add(t)
                    out.append(t)
        return out

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        p = state.player_by_id(controller_id)
        if p.agent is None:
            idx = 0
        else:
            idx = p.agent.choose_mode(
                state, controller_id, [m.describe() for m in self.modes]
            )
            idx = max(0, min(idx, len(self.modes) - 1))
        chosen = self.modes[idx]
        state.log.append(
            f"modal: P{controller_id} chooses mode {idx} ({chosen.describe()})"
        )
        # If the chosen mode requires a target but the passed target is
        # not in its legal set (target was picked for a different mode),
        # fizzle silently rather than crash.
        if chosen.requires_target():
            legal = chosen.legal_targets(state, controller_id)
            if not targets or targets[0] not in legal:
                state.log.append(
                    f"modal fizzle: chosen mode requires a legal target"
                )
                return
        chosen.resolve(state, controller_id, targets)

    def describe(self) -> str:
        return " OR ".join(m.describe() for m in self.modes)


@dataclass(frozen=True)
class Sequence(Effect):
    """Run multiple effects in order as a single composite effect.

    Target selection: only one of the sub-effects may require a target (this
    keeps the cast-time target-selection pipeline single-choice). That one
    sub-effect's legal_targets becomes the Sequence's. At resolution, the
    chosen target(s) are passed to the targeted sub-effect; untargeted sub-
    effects receive an empty tuple.
    """

    effects: tuple[Effect, ...]

    def __post_init__(self) -> None:
        targeted = [e for e in self.effects if e.requires_target()]
        if len(targeted) > 1:
            raise ValueError(
                "Sequence supports at most one targeting sub-effect "
                f"(got {len(targeted)})"
            )

    def requires_target(self) -> bool:
        return any(e.requires_target() for e in self.effects)

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        for e in self.effects:
            if e.requires_target():
                return e.legal_targets(state, controller_id)
        return []

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        for e in self.effects:
            if e.requires_target():
                e.resolve(state, controller_id, targets)
            else:
                e.resolve(state, controller_id, ())

    def describe(self) -> str:
        return ". ".join(e.describe() for e in self.effects) + "."


@dataclass(frozen=True)
class ConditionalIfVoid(Effect):
    """Run ``then_effect`` when Void is active on resolution; else ``else_effect``.

    Checks ``is_void_active(state)`` at resolution time (MTG-accurate for
    intervening-if clauses on spell resolution). Either branch may be None
    (the condition simply does nothing that side).

    Matches the "Void —" rider on spell effects like Decode Transmissions
    ("instead...") or Hymn of the Faller ("...draw another card").
    """

    then_effect: Effect
    else_effect: Effect | None = None

    def requires_target(self) -> bool:
        then_req = self.then_effect.requires_target()
        else_req = self.else_effect.requires_target() if self.else_effect else False
        return then_req or else_req

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        # Matches Sequence's constraint: only one branch may require a target.
        if self.then_effect.requires_target():
            return self.then_effect.legal_targets(state, controller_id)
        if self.else_effect is not None and self.else_effect.requires_target():
            return self.else_effect.legal_targets(state, controller_id)
        return []

    def __post_init__(self) -> None:
        # Both branches can require a target if they'd accept the same
        # target space — the caller picks once at cast time and resolve
        # forwards that single target tuple to whichever branch fires.
        # No eager check here; incompatible targets would be caught at
        # resolve time as a silent no-op.
        return

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import is_void_active

        branch = self.then_effect if is_void_active(state) else self.else_effect
        if branch is None:
            return
        branch.resolve(state, controller_id, targets)

    def describe(self) -> str:
        then_desc = self.then_effect.describe()
        if self.else_effect is None:
            return f"Void — {then_desc}"
        return (
            f"if Void is active, {then_desc}; otherwise, "
            f"{self.else_effect.describe()}"
        )


def _apply_damage(state: "GameState", target: Target, amount: int) -> None:
    """Apply ``amount`` damage to ``target``. Used by damage effects.

    Stage-3 scope: no source-tracking (so deathtouch on a pinger wouldn't
    mark its target lethal yet — that'd layer in when we thread damage
    sources through the ETB / ability pipeline).
    """
    kind, target_id = target
    if kind == "player":
        p = state.player_by_id(target_id)
        p.life -= amount
        state.log.append(f"P{target_id} takes {amount} damage (life: {p.life})")
    elif kind == "creature":
        obj = next((o for o in state.battlefield if o.id == target_id), None)
        if obj is not None:
            obj.damage += amount
            state.log.append(f"{obj.printing.name} takes {amount} damage")


@dataclass(frozen=True)
class CreateToken(Effect):
    """Create ``count`` creature tokens of the given printing under the
    ability's controller.

    ``token_printing`` must be a CardPrinting with the Token supertype (built
    via ``cards.make_token_creature``). Tokens enter the battlefield through
    the same helper as spells, so any ETBs they themselves have fire
    correctly.

    Set ``tapped=True`` for effects whose oracle text says "enters tapped"
    (e.g. Gravpack Monoist's "create a tapped 2/2 Robot token").
    """

    token_printing: "CardPrinting"
    count: int = 1
    tapped: bool = False
    each_player: bool = False  # if True, every living player creates the token

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.actions import put_into_battlefield
        from mtg_bot.game import Zone

        if self.each_player:
            # Every living player creates the token(s) under their own control.
            recipients = [p.id for p in state.players if not p.has_lost]
        else:
            recipients = [controller_id]

        for recipient in recipients:
            # Token-doubling replacement effects (Exalted Sunborn).
            # Each controller-side permanent with is_token_doubler
            # doubles the count before tokens enter.
            doublers = sum(
                1 for o in state.battlefield
                if o.controller_id == recipient
                and o.printing.is_token_doubler
            )
            effective_count = self.count * (2 ** doublers)
            for _ in range(effective_count):
                obj = state.new_object(
                    self.token_printing, owner_id=recipient, zone=Zone.BATTLEFIELD
                )
                state.log.append(
                    f"P{recipient} creates a {self.token_printing.name} token"
                    + (" (tapped)" if self.tapped else "")
                    + (f" (doubled x{2 ** doublers})" if doublers else "")
                )
                put_into_battlefield(state, obj, recipient)
                if self.tapped:
                    obj.tapped = True

    def describe(self) -> str:
        p = self.token_printing
        color_word = ""  # we don't track color on tokens explicitly yet
        pt = f"{p.power}/{p.toughness}" if p.is_creature else ""
        subtype = " ".join(p.subtypes)
        if self.count == 1:
            article = "a"
        else:
            article = str(self.count)
        pieces = [article, pt, color_word, subtype, "creature token"]
        return "create " + " ".join(x for x in pieces if x)


@dataclass(frozen=True)
class DestroyTargetCreature(Effect):
    """Destroy any target creature on the battlefield.

    Matches oracle text like "destroy target creature" (Vote Out). The
    creature is moved to its owner's graveyard (tokens cease to exist).
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import destroy

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "creature":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None:
            return
        state.log.append(f"{obj.printing.name} is destroyed")
        destroy(state, obj)

    def describe(self) -> str:
        return "destroy target creature"


@dataclass(frozen=True)
class DestroyTargetArtifact(Effect):
    """Destroy target artifact. Tokens cease to exist."""

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("permanent", o.id)
            for o in state.battlefield
            if o.printing.is_artifact
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import destroy

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "permanent":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None or not obj.printing.is_artifact:
            return
        state.log.append(f"{obj.printing.name} is destroyed (artifact)")
        destroy(state, obj)

    def describe(self) -> str:
        return "destroy target artifact"


@dataclass(frozen=True)
class ExileTargetCreatureUntilSourceLeaves(Effect):
    """Exile any target creature until the source leaves the battlefield.

    Matches All-Fates Stalker's ETB and Hardlight Containment's ETB.
    Uses the Oblivion-Ring-style ``exiled_by_source`` bookkeeping so
    the exiled creature returns when the source leaves play.

    ``excluded_subtypes`` filters out creatures whose printed subtypes
    overlap with any member (e.g., ``frozenset({"Assassin"})`` for
    All-Fates Stalker's "non-Assassin creature" clause). Empty = no
    subtype restriction.

    ``opponents_only`` restricts legal targets to creatures controlled
    by a player OTHER than the effect's controller (Hardlight
    Containment: "target creature an opponent controls"). Default False.
    """

    excluded_subtypes: frozenset[str] = frozenset()
    opponents_only: bool = False

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature
            and not (
                self.excluded_subtypes
                and any(s in self.excluded_subtypes for s in o.printing.subtypes)
            )
            and not (
                self.opponents_only and o.controller_id == controller_id
            )
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        source = state.resolving_source
        if source is None:
            return
        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "creature":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None:
            return
        from mtg_bot.turn import move_off_battlefield

        obj.exiled_by_source = source.id
        state.log.append(
            f"{obj.printing.name} is exiled by {source.printing.name}"
        )
        move_off_battlefield(state, obj, destination="exile")

    def describe(self) -> str:
        return (
            "exile target creature until this creature leaves the "
            "battlefield"
        )


@dataclass(frozen=True)
class ExileOpponentsNonlandPermanentUntilLeaves(Effect):
    """ETB exile target nonland permanent an opponent controls, optionally
    restricted by mana value. The exiled card returns when the source
    enchantment leaves the battlefield (Oblivion Ring / Banishing Light
    pattern). Uses state.resolving_source as the "source" for tracking.

    ``max_mv`` = 0 means no MV filter (Banishing Light); > 0 restricts
    to permanents with mana value ≤ max_mv (Seam Rip).
    """

    max_mv: int = 0

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        out: list[Target] = []
        for o in state.battlefield:
            if o.printing.is_land:
                continue
            if o.controller_id == controller_id:
                continue
            if self.max_mv and o.printing.mana_cost.total > self.max_mv:
                continue
            out.append(("permanent", o.id))
        return out

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        source = state.resolving_source
        if source is None:
            return
        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "permanent":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None or obj.printing.is_land:
            return
        if obj.controller_id == controller_id:
            return
        if self.max_mv and obj.printing.mana_cost.total > self.max_mv:
            return
        from mtg_bot.turn import move_off_battlefield

        obj.exiled_by_source = source.id
        state.log.append(
            f"{obj.printing.name} is exiled by {source.printing.name}"
        )
        move_off_battlefield(state, obj, destination="exile")

    def describe(self) -> str:
        if self.max_mv:
            return (
                f"exile target nonland permanent an opponent controls "
                f"with mana value {self.max_mv} or less until this "
                f"enchantment leaves the battlefield"
            )
        return (
            "exile target nonland permanent an opponent controls until "
            "this enchantment leaves the battlefield"
        )


@dataclass(frozen=True)
class SeedshipImpactEffect(Effect):
    """Destroy target artifact or enchantment. If its mana value was 2
    or less, create a Lander token.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("permanent", o.id)
            for o in state.battlefield
            if o.printing.is_artifact
            or "Enchantment" in o.printing.card_types
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.actions import put_into_battlefield
        from mtg_bot.cards import TOKEN_PRINTINGS
        from mtg_bot.game import Zone
        from mtg_bot.turn import destroy

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "permanent":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None:
            return
        if not (
            obj.printing.is_artifact
            or "Enchantment" in obj.printing.card_types
        ):
            return
        mv = obj.printing.mana_cost.total
        state.log.append(f"{obj.printing.name} is destroyed")
        if not destroy(state, obj):
            return  # indestructible — no Lander consolation
        if mv <= 2:
            lander = state.new_object(
                TOKEN_PRINTINGS["Lander"],
                owner_id=controller_id,
                zone=Zone.BATTLEFIELD,
            )
            state.log.append(f"P{controller_id} creates a Lander token")
            put_into_battlefield(state, lander, controller_id)

    def describe(self) -> str:
        return (
            "destroy target artifact or enchantment; if its mana value "
            "was 2 or less, create a Lander token"
        )


@dataclass(frozen=True)
class DestroyTargetNoncreaturePermanent(Effect):
    """Destroy target noncreature permanent. Includes lands, non-
    creature artifacts, enchantments, and planeswalkers — anything
    on the battlefield that isn't a creature. Indestructible
    permanents are unaffected.

    Matches Extinguisher Battleship's ETB first clause.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        from mtg_bot.game import is_creature_now

        return [
            ("permanent", o.id)
            for o in state.battlefield
            if not is_creature_now(o)
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import is_creature_now
        from mtg_bot.turn import destroy

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "permanent":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None or is_creature_now(obj):
            return
        state.log.append(f"{obj.printing.name} is destroyed")
        destroy(state, obj)

    def describe(self) -> str:
        return "destroy target noncreature permanent"


@dataclass(frozen=True)
class DestroyTargetNonlandPermanent(Effect):
    """Destroy target nonland permanent. Indestructible permanents are
    unaffected. Tokens cease to exist normally.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("permanent", o.id)
            for o in state.battlefield
            if not o.printing.is_land
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import destroy

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "permanent":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None or obj.printing.is_land:
            return
        state.log.append(f"{obj.printing.name} is destroyed")
        destroy(state, obj)

    def describe(self) -> str:
        return "destroy target nonland permanent"


@dataclass(frozen=True)
class MoveSelfCountersToTargetCreatureYouControl(Effect):
    """Move all +1/+1 counters from the source to target creature you
    control.

    Matches Dockworker Drone's dies trigger ("put its counters on target
    creature you control"). Reads state.resolving_source for the count;
    no-op if the source has zero counters or wasn't set.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature and o.controller_id == controller_id
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        source = state.resolving_source
        if source is None:
            return
        count = source.plus_one_counters
        if count <= 0:
            return
        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "creature":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None:
            return
        obj.plus_one_counters += count
        # Clear source counters — they've been transferred.
        source.plus_one_counters = 0
        state.log.append(
            f"{count} +1/+1 counter(s) moved from {source.printing.name} "
            f"to {obj.printing.name}"
        )

    def describe(self) -> str:
        return (
            "move this creature's +1/+1 counters to target creature you "
            "control"
        )


@dataclass(frozen=True)
class PutPlusOneCountersOnSelfPerOtherCreatureOrArtifact(Effect):
    """Put a +1/+1 counter on this creature for each OTHER creature and/or
    artifact you control.

    Matches Luxknight Breacher's "enters with" clause (modeled as an ETB
    trigger since we don't implement replacement effects). Counts are
    sampled at resolution; the source itself is excluded (it's on the
    battlefield by the time the ETB trigger resolves).
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        source = state.resolving_source
        if source is None:
            return
        count = 0
        for o in state.battlefield:
            if o.id == source.id:
                continue
            if o.controller_id != controller_id:
                continue
            if o.printing.is_creature or o.printing.is_artifact:
                count += 1
        if count <= 0:
            return
        source.plus_one_counters += count
        state.log.append(
            f"{source.printing.name} enters with {count} +1/+1 counters"
        )

    def describe(self) -> str:
        return (
            "put a +1/+1 counter on this creature for each other creature "
            "and/or artifact you control"
        )


@dataclass(frozen=True)
class PutChargeCountersOnTargetSpacecraftYouControl(Effect):
    """Put ``amount`` charge counters on a Spacecraft you control.

    Matches Drill Too Deep's first mode. Simplification: we don't include
    Planets (a separate land subtype we don't model).
    """

    amount: int = 5

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("permanent", o.id)
            for o in state.battlefield
            if o.printing.is_spacecraft
            and o.controller_id == controller_id
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "permanent":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None or not obj.printing.is_spacecraft:
            return
        obj.charge_counters += self.amount
        state.log.append(
            f"{obj.printing.name} gets {self.amount} charge counters "
            f"(now {obj.charge_counters})"
        )

    def describe(self) -> str:
        return (
            f"put {self.amount} charge counters on target Spacecraft you "
            f"control"
        )


@dataclass(frozen=True)
class DestroyTargetArtifactOrTappedCreature(Effect):
    """Destroy target artifact, or tapped creature.

    Matches Radiant Strike's destroy clause. Uses the "permanent" target kind
    since either artifacts or creatures can be hit; legality is filtered by
    the more specific "artifact OR tapped creature" predicate.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        out: list[Target] = []
        for o in state.battlefield:
            if o.printing.is_artifact:
                out.append(("permanent", o.id))
            elif o.printing.is_creature and o.tapped:
                out.append(("permanent", o.id))
        return out

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import move_off_battlefield

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "permanent":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None:
            return
        # Re-verify legality at resolution (target may have untapped).
        if not (
            obj.printing.is_artifact
            or (obj.printing.is_creature and obj.tapped)
        ):
            return
        from mtg_bot.turn import destroy

        state.log.append(f"{obj.printing.name} is destroyed")
        destroy(state, obj)

    def describe(self) -> str:
        return "destroy target artifact or tapped creature"


@dataclass(frozen=True)
class TapTargetOpponentPermanentAndStunIt(Effect):
    """Tap target artifact or creature an opponent controls, then put
    a stun counter on it. Matches Mechanozoa's ETB. Both effects apply
    to the same chosen target.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("permanent", o.id)
            for o in state.battlefield
            if (o.printing.is_artifact or o.printing.is_creature)
            and o.controller_id != controller_id
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import tap_permanent

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "permanent":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None:
            return
        if not obj.tapped:
            tap_permanent(state, obj)
        obj.stun_counters += 1
        state.log.append(
            f"{obj.printing.name} tapped and gains a stun counter "
            f"(now {obj.stun_counters})"
        )

    def describe(self) -> str:
        return (
            "tap target artifact or creature an opponent controls and "
            "put a stun counter on it"
        )


@dataclass(frozen=True)
class PutStunCounterOnTappedCreature(Effect):
    """Put a stun counter on up to one target tapped creature. Matches
    Cryogen Relic's activated ability. "Up to one" → required target
    in our simplified pipeline; silently fizzles if none legal."""

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature and o.tapped
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "creature":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None or not obj.tapped:
            return
        obj.stun_counters += 1
        state.log.append(
            f"{obj.printing.name} gets a stun counter "
            f"(now {obj.stun_counters})"
        )

    def describe(self) -> str:
        return "put a stun counter on up to one target tapped creature"


@dataclass(frozen=True)
class MutinousMassacreEffect(Effect):
    """Mutinous Massacre `{3}{B}{B}{R}{R}`:
    "Choose odd or even. Destroy each creature with mana value of the
    chosen quality. Then gain control of all creatures until end of
    turn. Untap them. They gain haste until end of turn. (Zero is even.)"

    The "choose odd or even" pick goes through ``choose_mode`` with
    descriptions ``["odd", "even"]``. Surviving creatures (those whose
    mana value parity differed from the chosen one) are all stolen via
    ``temp_original_controller_id``, untapped, and given haste UEOT.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import destroy

        p = state.player_by_id(controller_id)
        pick = 0  # 0 = odd, 1 = even
        if p.agent is not None:
            pick = p.agent.choose_mode(state, controller_id, ["odd", "even"])
            pick = max(0, min(pick, 1))
        chosen_label = "odd" if pick == 0 else "even"
        state.log.append(
            f"P{controller_id} chooses {chosen_label} for Mutinous Massacre"
        )
        # Destroy phase: each creature whose mana value matches the
        # chosen parity.
        victims = []
        for o in list(state.battlefield):
            if not o.printing.is_creature:
                continue
            mv = o.printing.mana_cost.total
            if pick == 0 and mv % 2 == 1:
                victims.append(o)
            elif pick == 1 and mv % 2 == 0:
                victims.append(o)
        for v in victims:
            state.log.append(
                f"{v.printing.name} (MV {v.printing.mana_cost.total}) "
                f"destroyed by Mutinous Massacre ({chosen_label})"
            )
            destroy(state, v)
        # Gain control of all surviving creatures UEOT, untap, haste.
        for o in state.battlefield:
            if not o.printing.is_creature:
                continue
            if o.controller_id != controller_id:
                if o.temp_original_controller_id is None:
                    o.temp_original_controller_id = o.controller_id
                o.controller_id = controller_id
            o.tapped = False
            o.temp_keywords = o.temp_keywords | frozenset({"haste"})
            state.log.append(
                f"P{controller_id} takes control of {o.printing.name} "
                f"UEOT; untaps + gains haste"
            )

    def describe(self) -> str:
        return (
            "choose odd or even; destroy each creature with mana value "
            "of the chosen quality; then gain control of all creatures "
            "until end of turn, untap them, they gain haste until end "
            "of turn"
        )


@dataclass(frozen=True)
class SystemsOverrideEffect(Effect):
    """Systems Override `{2}{R}` — gain control of target artifact or
    creature until end of turn, untap it, give it haste UEOT. If it's
    a Spacecraft, put ten charge counters on it; if so, remove ten
    at the beginning of the next end step.

    Control reverts on cleanup via ``temp_original_controller_id``. The
    ten-counter remove is scheduled as a delayed end-step action
    (``"remove_charge_counters"``) resolved in run_delayed_end_step_triggers.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("permanent", o.id)
            for o in state.battlefield
            if o.printing.is_artifact or o.printing.is_creature
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "permanent":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None:
            return
        # Gain control UEOT. If we already stole it this turn, keep the
        # original controller (don't overwrite with the current — rare
        # but preserves correct reversion).
        if obj.temp_original_controller_id is None:
            obj.temp_original_controller_id = obj.controller_id
        obj.controller_id = controller_id
        obj.tapped = False
        obj.temp_keywords = obj.temp_keywords | frozenset({"haste"})
        state.log.append(
            f"P{controller_id} takes control of {obj.printing.name} "
            f"UEOT; untaps + gains haste"
        )
        if obj.printing.is_spacecraft:
            obj.charge_counters += 10
            state.log.append(
                f"{obj.printing.name} gets 10 charge counters "
                f"(now {obj.charge_counters})"
            )
            state.delayed_triggers.append({
                "fire_at_turn": state.turn_number,
                "controller_id": controller_id,
                "action": "remove_charge_counters",
                "target_id": obj.id,
                "amount": 10,
            })

    def describe(self) -> str:
        return (
            "gain control of target artifact or creature until end of "
            "turn; untap it; it gains haste until end of turn; if it's "
            "a Spacecraft, put ten charge counters on it, then remove "
            "ten at the next end step"
        )


@dataclass(frozen=True)
class TapAnotherTargetCreature(Effect):
    """Tap another target creature — target must not be the source.

    Matches Starport Security's activated "Tap another target creature"
    ability. Reads ``state.resolving_source`` to exclude self.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        source = state.resolving_source
        source_id = source.id if source is not None else -1
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature and o.id != source_id
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import tap_permanent

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "creature":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None:
            return
        tap_permanent(state, obj)

    def describe(self) -> str:
        return "tap another target creature"


@dataclass(frozen=True)
class TapTargetArtifactOrCreature(Effect):
    """Tap target artifact or creature. Matches Mental Modulation's middle
    clause. No-op if the target is already tapped.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("permanent", o.id)
            for o in state.battlefield
            if o.printing.is_artifact or o.printing.is_creature
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import tap_permanent

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "permanent":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None:
            return
        tap_permanent(state, obj)

    def describe(self) -> str:
        return "tap target artifact or creature"


@dataclass(frozen=True)
class UntapTargetOtherPermanent(Effect):
    """Untap target permanent other than the source.

    Matches Nanoform Sentinel's "untap another target permanent" trigger.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        source = state.resolving_source
        source_id = source.id if source is not None else -1
        return [
            ("permanent", o.id)
            for o in state.battlefield
            if o.id != source_id and o.tapped
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "permanent":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None:
            return
        if not obj.tapped:
            return
        obj.tapped = False
        state.log.append(f"{obj.printing.name} is untapped")

    def describe(self) -> str:
        return "untap another target permanent"


@dataclass(frozen=True)
class BiosynthicBurstEffect(Effect):
    """Put a +1/+1 counter on target creature you control. It gains reach,
    trample, and indestructible UEOT. Untap it.

    One dedicated effect because all three pieces operate on the same
    target, which doesn't compose cleanly via Sequence in our single-
    target-per-Sequence model.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature and o.controller_id == controller_id
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "creature":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None or obj.controller_id != controller_id:
            return
        obj.plus_one_counters += 1
        obj.temp_keywords = obj.temp_keywords | frozenset(
            {"reach", "trample", "indestructible"}
        )
        obj.tapped = False
        state.log.append(
            f"{obj.printing.name} gets a +1/+1 counter, gains reach, "
            f"trample, indestructible UEOT, and untaps"
        )

    def describe(self) -> str:
        return (
            "put a +1/+1 counter on target creature you control; it "
            "gains reach, trample, and indestructible until end of "
            "turn; untap it"
        )


@dataclass(frozen=True)
class DepressurizeEffect(Effect):
    """Target creature gets -3/-0 UEOT; then if its power is 0 or less,
    destroy it.

    Dedicated effect because the conditional destroy reads the pumped
    creature's post-modification power — an inline check after the pump
    is clearer than stitching Sequence + ConditionalDestroyIfPowerLEQ.
    """

    power_penalty: int = 3  # applied as a negative to temp_power_bonus

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import effective_power
        from mtg_bot.turn import destroy

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "creature":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None:
            return
        obj.temp_power_bonus -= self.power_penalty
        state.log.append(
            f"{obj.printing.name} gets -{self.power_penalty}/-0 until end "
            f"of turn"
        )
        # "Then if that creature's power is 0 or less, destroy it."
        if effective_power(state, obj) <= 0:
            state.log.append(f"{obj.printing.name} is destroyed (depressurized)")
            destroy(state, obj)

    def describe(self) -> str:
        return (
            f"target creature gets -{self.power_penalty}/-0 until end of "
            f"turn; then if its power is 0 or less, destroy it"
        )


@dataclass(frozen=True)
class DestroyTargetArtifactEnchantmentOrFlyingCreature(Effect):
    """Destroy target artifact, enchantment, or creature with flying.

    Matches Shattered Wings' destroy clause. Uses the "permanent" target
    kind. Flying check uses effective_keywords so anthem-granted flying
    (if ever implemented) and temp_keywords both count.
    """

    def requires_target(self) -> bool:
        return True

    def _is_legal(self, state: "GameState", obj: "GameObject") -> bool:
        from mtg_bot.game import effective_keywords

        if obj.printing.is_artifact:
            return True
        if "Enchantment" in obj.printing.card_types:
            return True
        if obj.printing.is_creature and "flying" in effective_keywords(state, obj):
            return True
        return False

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("permanent", o.id)
            for o in state.battlefield
            if self._is_legal(state, o)
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import destroy

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "permanent":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None:
            return
        if not self._is_legal(state, obj):
            return
        state.log.append(f"{obj.printing.name} is destroyed")
        destroy(state, obj)

    def describe(self) -> str:
        return (
            "destroy target artifact, enchantment, or creature with flying"
        )


@dataclass(frozen=True)
class CounterTargetSpell(Effect):
    """Counter target spell on the stack.

    ``filter_types`` optionally restricts what card types can be
    countered (e.g., frozenset({"Artifact", "Enchantment"}) for Annul).
    Empty set means "any spell".

    Targets a stack item by its index via the new ``"stack"`` target kind.
    Triggered and activated abilities on the stack can't be countered by
    this effect (only spells — items where ``ability`` is None).
    """

    filter_types: frozenset[str] = frozenset()

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        out: list[Target] = []
        for i, item in enumerate(state.stack):
            if item.ability is not None:
                continue  # not a spell
            if item.countered:
                continue
            src = item.source.printing
            if self.filter_types:
                if not any(t in src.card_types for t in self.filter_types):
                    continue
            out.append(("stack", i))
        return out

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if not targets:
            return
        kind, idx = targets[0]
        if kind != "stack":
            return
        if not (0 <= idx < len(state.stack)):
            return
        item = state.stack[idx]
        if item.ability is not None:
            return
        item.countered = True
        state.log.append(
            f"counterspell: {item.source.printing.name} is countered"
        )

    def describe(self) -> str:
        if not self.filter_types:
            return "counter target spell"
        types = ", ".join(sorted(t.lower() for t in self.filter_types))
        return f"counter target {types} spell"


@dataclass(frozen=True)
class DestroyAllCreatures(Effect):
    """Destroy every creature on the battlefield. Wrath-style effect.

    Indestructible creatures survive (routes each kill through
    turn.destroy()). Tokens cease to exist normally.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import destroy

        victims = [o for o in state.battlefield if o.printing.is_creature]
        for obj in victims:
            state.log.append(f"{obj.printing.name} is destroyed (wrath)")
            destroy(state, obj)

    def describe(self) -> str:
        return "destroy all creatures"


@dataclass(frozen=True)
class SingularityRuptureEffect(Effect):
    """Singularity Rupture `{3}{U}{B}{B}`:
    "Destroy all creatures, then any number of target players each mill
    half their library, rounded down."

    Multi-target: min 0, max = number of living players. After the
    wrath, each chosen player mills ``floor(library_size / 2)`` cards.
    """

    def requires_target(self) -> bool:
        # "Any number of target" — technically optional, but the cast
        # pipeline only requires a target pool to exist. legal_actions
        # won't gate casting on this since there's always at least one
        # living player.
        return True

    def target_count_range(self) -> tuple[int, int]:
        # "Any number" — min 0, max bounded by a reasonable ceiling.
        # Two-player games → max 2. We pick 8 to cover any plausible
        # multiplayer pod size; the cast pipeline clamps to actual
        # legal_targets length anyway.
        return (0, 8)

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("player", p.id) for p in state.players if not p.has_lost
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone
        from mtg_bot.turn import destroy

        # Wrath phase.
        victims = [o for o in state.battlefield if o.printing.is_creature]
        for o in victims:
            state.log.append(
                f"{o.printing.name} destroyed by Singularity Rupture"
            )
            destroy(state, o)
        # Mill phase — each targeted player mills half their library,
        # rounded down.
        for kind, tid in targets:
            if kind != "player":
                continue
            try:
                p = state.player_by_id(tid)
            except KeyError:
                continue
            if p.has_lost:
                continue
            n = len(p.library) // 2
            milled = 0
            for _ in range(n):
                if not p.library:
                    break
                card = p.library.pop(0)
                card.zone = Zone.GRAVEYARD
                p.graveyard.append(card)
                milled += 1
            state.log.append(
                f"P{tid} mills {milled} card(s) from Singularity Rupture "
                f"(library now {len(p.library)})"
            )

    def describe(self) -> str:
        return (
            "destroy all creatures; then any number of target players "
            "each mill half their library, rounded down"
        )


@dataclass(frozen=True)
class ZeroPointBalladEffect(Effect):
    """Zero Point Ballad `{X}{B}`:
    "Destroy all creatures with toughness X or less. You lose X life. If
    X is 6 or more, return a creature card put into a graveyard this way
    to the battlefield under your control."

    Reads X from ``state.resolving_x_value``. For the X≥6 clause, a
    creature card is "put into a graveyard this way" only if it was
    destroyed by the first clause AND landed in the caster's graveyard
    (i.e. the caster owned it). The agent picks one of those candidates
    via ``choose_target`` (kind=``creature_card``); declining is legal —
    the reanimation is optional.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.actions import put_into_battlefield
        from mtg_bot.game import effective_toughness
        from mtg_bot.turn import destroy

        x = state.resolving_x_value
        victims = [
            o for o in state.battlefield
            if o.printing.is_creature and effective_toughness(state, o) <= x
        ]
        caster_owned_victim_ids = {
            o.id for o in victims if o.owner_id == controller_id
        }
        for obj in victims:
            state.log.append(
                f"{obj.printing.name} destroyed by Zero Point Ballad "
                f"(X={x})"
            )
            destroy(state, obj)

        p = state.player_by_id(controller_id)
        p.life -= x
        state.log.append(
            f"P{controller_id} loses {x} life to Zero Point Ballad "
            f"(life: {p.life})"
        )

        if x >= 6:
            candidates = [
                c for c in p.graveyard
                if c.id in caster_owned_victim_ids
                and c.printing.is_creature
            ]
            if candidates and p.agent is not None:
                legal = [("creature_card", c.id) for c in candidates]
                chosen = p.agent.choose_target(state, controller_id, legal)
                if chosen is not None:
                    card = next(
                        (c for c in candidates if c.id == chosen[1]), None
                    )
                    if card is not None:
                        p.graveyard.remove(card)
                        put_into_battlefield(state, card, controller_id)
                        state.log.append(
                            f"Zero Point Ballad returns "
                            f"{card.printing.name} to the battlefield"
                        )

    def describe(self) -> str:
        return (
            "destroy all creatures with toughness X or less; you lose X "
            "life; if X is 6 or more, return a creature card put into a "
            "graveyard this way to the battlefield under your control"
        )


@dataclass(frozen=True)
class CreateXTokensOfTargetPermanentWithHasteEndStepSac(Effect):
    """Devastating Onslaught `{X}{X}{R}`:
    "Create X tokens that are copies of target artifact or creature you
    control. Those tokens gain haste until end of turn. Sacrifice them
    at the beginning of the next end step."

    Reads X from ``state.resolving_x_value``. Each token copies the
    target's printing directly (shared CardPrinting) and enters with a
    ``haste`` temp keyword. A delayed "sacrifice at end of turn"
    trigger is scheduled per token so they're cleaned up automatically.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("permanent", o.id)
            for o in state.battlefield
            if o.controller_id == controller_id
            and (o.printing.is_artifact or o.printing.is_creature)
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.actions import put_into_battlefield
        from mtg_bot.game import Zone

        if not targets:
            return
        kind, tid = targets[0]
        target = next((o for o in state.battlefield if o.id == tid), None)
        if target is None:
            return
        x = state.resolving_x_value
        if x <= 0:
            return
        for _ in range(x):
            token = state.new_object(
                target.printing,
                owner_id=controller_id,
                zone=Zone.BATTLEFIELD,
            )
            # Temporarily suppress the "enters with X counters" replacement
            # when putting token copies into play — tokens copy printed
            # characteristics but X is 0 for them (they weren't cast).
            saved_x = state.resolving_x_value
            state.resolving_x_value = 0
            try:
                put_into_battlefield(state, token, controller_id)
            finally:
                state.resolving_x_value = saved_x
            token.temp_keywords = token.temp_keywords | frozenset({"haste"})
            state.delayed_triggers.append({
                "fire_at_turn": state.turn_number,
                "controller_id": controller_id,
                "action": "sacrifice",
                "target_id": token.id,
            })
        state.log.append(
            f"Devastating Onslaught creates {x} copies of "
            f"{target.printing.name} with haste (sac at end step)"
        )

    def describe(self) -> str:
        return (
            "create X tokens that are copies of target artifact or "
            "creature you control; they gain haste until end of turn; "
            "sacrifice them at the beginning of the next end step"
        )


@dataclass(frozen=True)
class ExileAllCreaturesAndSpacecraft(Effect):
    """Exile every creature on the battlefield, as well as Spacecraft (whether
    or not the Spacecraft has been stationed into creature mode).

    Matches Beyond the Quiet. Mass wrath-style effect: no targets, acts on
    the full battlefield snapshot at resolution. Tokens cease to exist per
    rule 704.5d.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import move_off_battlefield

        victims = [
            o for o in state.battlefield
            if o.printing.is_creature or o.printing.is_spacecraft
        ]
        for obj in victims:
            state.log.append(f"{obj.printing.name} is exiled (mass)")
            move_off_battlefield(state, obj, destination="exile")

    def describe(self) -> str:
        return "exile all creatures and Spacecraft"


@dataclass(frozen=True)
class ExileTargetCreature(Effect):
    """Exile any target creature on the battlefield.

    Matches oracle text like "exile target creature" (Gravkill, minus its
    "or Spacecraft" option since Spacecraft aren't implemented yet). Tokens
    exiled cease to exist per rule 704.5d.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import move_off_battlefield

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "creature":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None:
            return
        state.log.append(f"{obj.printing.name} is exiled")
        move_off_battlefield(state, obj, destination="exile")

    def describe(self) -> str:
        return "exile target creature"


@dataclass(frozen=True)
class DestroyTargetNonlandPermanentWithLanderForController(Effect):
    """Destroy target nonland permanent. Its (former) controller creates a
    Lander token.

    Matches Emergency Eject's oracle text. Uses a new "permanent" target kind
    (any non-land battlefield object) so this can hit creatures, artifacts,
    and enchantments uniformly.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("permanent", o.id)
            for o in state.battlefield
            if not o.printing.is_land
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.actions import put_into_battlefield
        from mtg_bot.cards import TOKEN_PRINTINGS
        from mtg_bot.game import Zone
        from mtg_bot.turn import destroy

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "permanent":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None:
            return
        former_controller = obj.controller_id
        state.log.append(f"{obj.printing.name} is destroyed")
        if not destroy(state, obj):
            return  # indestructible: no Lander consolation
        lander = state.new_object(
            TOKEN_PRINTINGS["Lander"],
            owner_id=former_controller,
            zone=Zone.BATTLEFIELD,
        )
        state.log.append(f"P{former_controller} creates a Lander token")
        put_into_battlefield(state, lander, former_controller)

    def describe(self) -> str:
        return (
            "destroy target nonland permanent; its controller creates a "
            "Lander token"
        )


@dataclass(frozen=True)
class PutPlusOneCounterOnTargetCreature(Effect):
    """Put ``amount`` +1/+1 counter(s) on any target creature (yours or theirs).

    Matches oracle text like "put a +1/+1 counter on target creature" (Honor).
    Unrestricted version of PutPlusOneCounterOnCreatureYouControl.
    """

    amount: int = 1

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "creature":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None:
            return
        from mtg_bot.game import add_plus_one_counters
        add_plus_one_counters(state, obj, self.amount)
        state.log.append(
            f"{obj.printing.name} gets a +1/+1 counter "
            f"(now {obj.plus_one_counters})"
        )

    def describe(self) -> str:
        if self.amount == 1:
            return "put a +1/+1 counter on target creature"
        return f"put {self.amount} +1/+1 counters on target creature"


@dataclass(frozen=True)
class PutPlusOneCounterOnEachCreatureYouControl(Effect):
    """Put ``amount`` +1/+1 counter(s) on each creature the controller
    controls at resolution. Matches Atmospheric Greenhouse's ETB."""

    amount: int = 1

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import add_plus_one_counters
        count = 0
        for obj in state.battlefield:
            if obj.controller_id != controller_id:
                continue
            if not obj.printing.is_creature:
                continue
            add_plus_one_counters(state, obj, self.amount)
            count += 1
        state.log.append(
            f"P{controller_id}'s {count} creature(s) each get "
            f"a +1/+1 counter"
        )

    def describe(self) -> str:
        if self.amount == 1:
            return "put a +1/+1 counter on each creature you control"
        return (
            f"put {self.amount} +1/+1 counters on each creature you control"
        )


@dataclass(frozen=True)
class PutPlusOneCounterOnSelf(Effect):
    """Put ``amount`` +1/+1 counter(s) on the ability's source ("this creature").

    Reads ``state.resolving_source`` to find the source — it's set by
    ``resolve_top_of_stack`` during ability resolution.
    """

    amount: int = 1

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import add_plus_one_counters
        source = state.resolving_source
        if source is None:
            return
        add_plus_one_counters(state, source, self.amount)
        state.log.append(
            f"{source.printing.name} gets a +1/+1 counter "
            f"(now {source.plus_one_counters})"
        )

    def describe(self) -> str:
        if self.amount == 1:
            return "put a +1/+1 counter on this creature"
        return f"put {self.amount} +1/+1 counters on this creature"


@dataclass(frozen=True)
class PutPlusOneCounterOnOpponentsCreature(Effect):
    """Put a +1/+1 counter on a creature an opponent controls. Matches
    Sunset Saboteur's attacks trigger — unusual flavor (buffing an
    opponent's creature in exchange for the trigger's other effects).
    """

    amount: int = 1

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature and o.controller_id != controller_id
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "creature":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None or obj.controller_id == controller_id:
            return
        # No doubling here: the counter goes onto an OPPONENT's
        # creature; Loading Zone belongs to the caster, not the
        # opponent. Doublers check the recipient's controller.
        from mtg_bot.game import add_plus_one_counters
        add_plus_one_counters(state, obj, self.amount)
        state.log.append(
            f"{obj.printing.name} gets a +1/+1 counter "
            f"(now {obj.plus_one_counters})"
        )

    def describe(self) -> str:
        return "put a +1/+1 counter on target creature an opponent controls"


@dataclass(frozen=True)
class PutPlusOneCounterOnCreatureYouControl(Effect):
    """Put N +1/+1 counter(s) on target creature you control.

    Matches oracle text like "put a +1/+1 counter on target creature you
    control" (Rayblade Trooper). Legal targets are every creature the
    ability's controller controls.
    """

    amount: int = 1

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature and o.controller_id == controller_id
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "creature":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None:
            return
        from mtg_bot.game import add_plus_one_counters
        add_plus_one_counters(state, obj, self.amount)
        state.log.append(
            f"{obj.printing.name} gets a +1/+1 counter "
            f"(now {obj.plus_one_counters})"
        )

    def describe(self) -> str:
        if self.amount == 1:
            return "put a +1/+1 counter on target creature you control"
        return (
            f"put {self.amount} +1/+1 counters on target creature you control"
        )


@dataclass(frozen=True)
class DealDamageAnyTarget(Effect):
    """Deal ``amount`` damage to any target (creature or player).

    Matches "deals N damage to any target" on cards like Nebula Dragon.
    Planeswalkers and battles are valid MTG targets too — they just don't
    exist yet in our engine.
    """

    amount: int

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        targets: list[Target] = []
        for o in state.battlefield:
            if o.printing.is_creature:
                targets.append(("creature", o.id))
        for p in state.players:
            if not p.has_lost:
                targets.append(("player", p.id))
        return targets

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if not targets:
            return
        _apply_damage(state, targets[0], self.amount)

    def describe(self) -> str:
        return f"deals {self.amount} damage to any target"


@dataclass(frozen=True)
class DealDamageToTargetCreature(Effect):
    """Deal ``amount`` damage to any target creature (controller's or otherwise).

    Matches oracle text like "~ deals N damage to target creature" (Bombard).
    Unlike DealDamageToOpponentCreature this can target your own creatures
    too.
    """

    amount: int

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if not targets:
            return
        kind, _ = targets[0]
        if kind != "creature":
            return
        _apply_damage(state, targets[0], self.amount)

    def describe(self) -> str:
        return f"deals {self.amount} damage to target creature"


@dataclass(frozen=True)
class DealDamageToTargetCreatureWithExcessLanderRider(Effect):
    """Orbital Plunge `{3}{R}`:
    "Orbital Plunge deals 6 damage to target creature. If excess damage
    was dealt this way, create a Lander token."

    Excess damage is the portion of the 6 that exceeded what was needed
    to mark lethal on the target — ``damage_amount - max(0, effective
    toughness - damage already marked)``. We check >0 after the damage
    is applied. Lifelink/deathtouch are not modeled here; in real MTG
    "excess" is resolved through rule 120.3e which handles that, but
    for our simplified model, comparing amount to remaining toughness
    is sufficient.
    """

    amount: int = 6

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.actions import put_into_battlefield
        from mtg_bot.cards import TOKEN_PRINTINGS
        from mtg_bot.game import Zone, effective_toughness

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "creature":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        excess = 0
        if obj is not None:
            remaining = max(0, effective_toughness(state, obj) - obj.damage)
            excess = max(0, self.amount - remaining)
        _apply_damage(state, targets[0], self.amount)
        if excess > 0:
            lander = state.new_object(
                TOKEN_PRINTINGS["Lander"],
                owner_id=controller_id,
                zone=Zone.BATTLEFIELD,
            )
            put_into_battlefield(state, lander, controller_id)
            state.log.append(
                f"Orbital Plunge dealt {excess} excess damage; "
                f"P{controller_id} creates a Lander token"
            )

    def describe(self) -> str:
        return (
            f"deals {self.amount} damage to target creature; if excess "
            f"damage was dealt this way, create a Lander token"
        )


@dataclass(frozen=True)
class DealDamageToOpponentCreatureByArtifactCount(Effect):
    """Deal damage equal to the number of artifacts you control to target
    creature an opponent controls.

    Matches Warmaker Gunship's ETB. Counts include lands that are also
    artifacts (there aren't any in EoE) and tokens like Lander.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature and o.controller_id != controller_id
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if not targets:
            return
        kind, _ = targets[0]
        if kind != "creature":
            return
        artifact_count = sum(
            1 for o in state.battlefield
            if o.controller_id == controller_id and o.printing.is_artifact
        )
        if artifact_count <= 0:
            return
        _apply_damage(state, targets[0], artifact_count)

    def describe(self) -> str:
        return (
            "deals damage equal to the number of artifacts you control to "
            "target creature an opponent controls"
        )


@dataclass(frozen=True)
class FocusFireEffect(Effect):
    """Deal (``base`` + your creatures and Spacecraft) damage to an attacking
    or blocking creature.

    Matches Focus Fire. Dynamic amount is recomputed at resolution.
    Legality is filtered to attackers/blockers only; that's re-checked at
    resolve time so a creature that stops attacking/blocking between cast
    and resolve fizzles the damage.
    """

    base: int = 2

    def requires_target(self) -> bool:
        return True

    @staticmethod
    def _is_in_combat(obj: "GameObject") -> bool:
        return obj.attacking or obj.blocking is not None

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature and self._is_in_combat(o)
        ]

    def _amount(self, state: "GameState", controller_id: int) -> int:
        bonus = sum(
            1 for o in state.battlefield
            if o.controller_id == controller_id
            and (o.printing.is_creature or o.printing.is_spacecraft)
        )
        return self.base + bonus

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "creature":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None or not self._is_in_combat(obj):
            return
        _apply_damage(state, targets[0], self._amount(state, controller_id))

    def describe(self) -> str:
        return (
            f"deals {self.base}+X damage to target attacking or blocking "
            f"creature, where X is creatures and Spacecraft you control"
        )


@dataclass(frozen=True)
class CutPropulsionEffect(Effect):
    """Target creature deals damage to itself equal to its power; doubled if
    that creature has flying.

    Matches Cut Propulsion. Self-damage uses _apply_damage, which applies
    deathtouch-style marked_lethal only when a deathtouch source is involved
    — self-damage carries no source keywords so SBA-based lethal checks
    behave normally.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import effective_keywords, effective_power

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "creature":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None:
            return
        power = effective_power(state, obj)
        if power <= 0:
            state.log.append(
                f"{obj.printing.name} deals 0 damage to itself "
                f"(Cut Propulsion)"
            )
            return
        if "flying" in effective_keywords(state, obj):
            amount = power * 2
        else:
            amount = power
        state.log.append(
            f"{obj.printing.name} takes {amount} (Cut Propulsion self-damage)"
        )
        _apply_damage(state, targets[0], amount)

    def describe(self) -> str:
        return (
            "target creature deals damage to itself equal to its power; "
            "doubled if it has flying"
        )


@dataclass(frozen=True)
class DealDamageToTargetCreatureSpacecraftBoosted(Effect):
    """Deal ``base`` damage to a target creature; ``boosted`` instead if you
    control a Spacecraft.

    Matches Invasive Maneuvers (3/5). Any-target creature.
    """

    base: int = 3
    boosted: int = 5

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature
        ]

    def _amount(self, state: "GameState", controller_id: int) -> int:
        has_spacecraft = any(
            o.controller_id == controller_id and o.printing.is_spacecraft
            for o in state.battlefield
        )
        return self.boosted if has_spacecraft else self.base

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if not targets:
            return
        kind, _ = targets[0]
        if kind != "creature":
            return
        _apply_damage(state, targets[0], self._amount(state, controller_id))

    def describe(self) -> str:
        return (
            f"deals {self.base} damage to target creature, {self.boosted} "
            f"instead if you control a Spacecraft"
        )


@dataclass(frozen=True)
class DealDamageToOpponentCreature(Effect):
    """Deal ``amount`` damage to target creature an opponent controls.

    Matches oracle text like "deals N damage to target creature an opponent
    controls" (Nova Hellkite). Only enemy creatures are legal targets — the
    controller can't target their own creatures with this.
    """

    amount: int

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("creature", o.id)
            for o in state.battlefield
            if o.printing.is_creature and o.controller_id != controller_id
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if not targets:
            return
        kind, _ = targets[0]
        if kind != "creature":
            return
        _apply_damage(state, targets[0], self.amount)

    def describe(self) -> str:
        return f"deals {self.amount} damage to target creature an opponent controls"


@dataclass(frozen=True)
class EachOpponentDiscards(Effect):
    """Each opponent discards ``count`` cards (untargeted; no choice of target).

    Each discarding player chooses their own discard via their agent's
    ``choose_discard`` — the ability's controller doesn't pick for them.
    """

    count: int = 1

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone
        from mtg_bot.turn import fire_opponent_discards_triggers

        for p in state.players:
            if p.id == controller_id or p.has_lost:
                continue
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
                    f"P{p.id} discards {card.printing.name}"
                )
                fire_opponent_discards_triggers(state, p.id)

    def describe(self) -> str:
        if self.count == 1:
            return "each opponent discards a card"
        return f"each opponent discards {self.count} cards"


@dataclass(frozen=True)
class EachOpponentSacrificesCreature(Effect):
    """Each opponent sacrifices a nontoken creature of their choice.

    Each sacrificing player picks via their agent's ``choose_sacrifice``.
    If an opponent has no legal nontoken creature, they skip — no target
    required to match the standard MTG "of their choice" wording.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import sacrifice as _sacrifice

        for p in state.players:
            if p.id == controller_id or p.has_lost:
                continue
            legal = [
                o for o in state.battlefield
                if o.controller_id == p.id
                and o.printing.is_creature
                and not o.printing.is_token
            ]
            if not legal or p.agent is None:
                continue
            chosen_id = p.agent.choose_sacrifice(
                state, p.id, [o.id for o in legal]
            )
            obj = next((o for o in legal if o.id == chosen_id), legal[0])
            state.log.append(f"P{p.id} sacrifices {obj.printing.name}")
            _sacrifice(state, obj)

    def describe(self) -> str:
        return "each opponent sacrifices a nontoken creature of their choice"


@dataclass(frozen=True)
class TargetOpponentDiscardsCasterChoice(Effect):
    """Target opponent reveals their hand. You choose a nonland card
    from it. That player discards the chosen card.

    Matches Temporal Intervention's main effect. Unlike
    TargetOpponentDiscards (opponent picks their own discard), here the
    CASTER picks — a directed discard.
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("player", p.id) for p in state.players
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
        target = state.player_by_id(target_id)
        if target.has_lost:
            return
        # Nonland cards the target could be forced to discard.
        options = [
            c for c in target.hand if not c.printing.is_land
        ]
        if not options:
            state.log.append(
                f"P{target_id} has no nonland cards — directed discard "
                f"fizzles"
            )
            return
        caster = state.player_by_id(controller_id)
        if caster.agent is None:
            chosen = options[0]
        else:
            chosen_id = caster.agent.choose_card_from_opponent_hand(
                state, controller_id, [c.id for c in options]
            )
            chosen = next(
                (c for c in options if c.id == chosen_id), options[0]
            )
        target.hand.remove(chosen)
        chosen.zone = Zone.GRAVEYARD
        target.graveyard.append(chosen)
        state.log.append(
            f"P{controller_id} forces P{target_id} to discard "
            f"{chosen.printing.name}"
        )

    def describe(self) -> str:
        return (
            "target opponent reveals their hand; you choose a nonland "
            "card from it and they discard it"
        )


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
class ActivationCost:
    """Cost to activate an activated ability.

    Composable pieces: mana cost, tap the source, sacrifice the source.
    "Tap another creature" style costs aren't covered here — Station
    already has its own Action for that specialised case.
    """

    mana: "ManaCost | None" = None
    mana_str: str = ""  # display form like "{2}"
    tap_self: bool = False
    sacrifice_self: bool = False
    # "Sacrifice another creature or artifact" — the caster picks a
    # legal target via choose_sacrifice. Cannot be the source itself.
    sacrifice_another_creature_or_artifact: bool = False
    # "Sacrifice another artifact or land" — as above but with a land
    # filter. Matches Slagdrill Scrapper.
    sacrifice_another_artifact_or_land: bool = False
    # "Remove a +1/+1 counter from a creature you control" — Sunstar
    # Chaplain's activated ability. Fails if no such creature exists.
    remove_plus_one_counter_from_your_creature: bool = False

    def describe(self) -> str:
        parts: list[str] = []
        if self.mana_str:
            parts.append(self.mana_str)
        if self.tap_self:
            parts.append("{T}")
        if self.sacrifice_self:
            parts.append("Sacrifice ~")
        if self.sacrifice_another_creature_or_artifact:
            parts.append("Sacrifice another creature or artifact")
        if self.sacrifice_another_artifact_or_land:
            parts.append("Sacrifice another artifact or land")
        if self.remove_plus_one_counter_from_your_creature:
            parts.append("Remove a +1/+1 counter from a creature you control")
        return ", ".join(parts) if parts else "0"


@dataclass(frozen=True)
class ActivatedAbility:
    """An ability players can activate by paying ``cost``. On activation the
    ability goes on the stack; when it resolves, ``effect`` runs.

    ``sorcery_speed=True`` limits activation to main-phase-with-empty-stack
    timing (matches "Activate only as a sorcery").
    """

    cost: ActivationCost
    effect: Effect
    sorcery_speed: bool = False

    def describe(self) -> str:
        return f"{self.cost.describe()}: {self.effect.describe()}"


class StaticScope:
    """Scope of a static ability — which permanents it affects.

    Values are strings (not an Enum) to keep StaticAbility hashable and
    frozen-friendly.
    """

    OTHER_CREATURES_YOU_CONTROL = "other_creatures_you_control"
    CREATURES_YOU_CONTROL = "creatures_you_control"
    CREATURES_YOU_CONTROL_WITH_COUNTER = "creatures_you_control_with_counter"
    SELF = "self"  # only the source itself
    # Other tapped legendary creatures you control — The Seriema's 7+.
    OTHER_TAPPED_LEGENDARY_CREATURES_YOU_CONTROL = (
        "other_tapped_legendary_creatures_you_control"
    )


@dataclass(frozen=True)
class StaticAbility:
    """A continuous ability on a permanent that grants keywords and/or P/T
    bonuses to matching permanents while the source is on the battlefield.

    Stage 3 supports anthem-style scopes. Consumers (effective_keywords,
    effective_power, effective_toughness) walk the battlefield at query
    time and fold in applicable bonuses — no layers system yet, so the
    ordering-of-continuous-effects subtleties from the comprehensive rules
    don't apply.

    ``active_turn_only=True`` gates the ability on "it's the source
    controller's turn", matching EoE riders like "During your turn,
    [anthem]".

    ``requires_artifact_you_control=True`` gates the ability on the source's
    controller having at least one non-land artifact on the battlefield —
    the common "as long as you control an artifact" rider in EoE's
    blue/black artifacts-matter subtheme.
    """

    scope: str
    granted_keywords: frozenset[str] = frozenset()
    power_bonus: int = 0
    toughness_bonus: int = 0
    active_turn_only: bool = False
    # Tiered abilities on Spacecraft: the ability is only active when the
    # source has ``tier_threshold`` or more charge counters. 0 = always on.
    tier_threshold: int = 0
    requires_artifact_you_control: bool = False
    # Minimum spells_cast_this_turn the controller must have reached for
    # the ability to apply. 0 means "always on". Matches EoE's
    # "as long as you've cast two or more spells this turn" riders.
    requires_spells_cast_this_turn: int = 0

    def applies_to(self, source, target, state: "GameState | None" = None) -> bool:
        """True if this ability, on ``source``, currently buffs ``target``."""
        from mtg_bot.game import is_creature_now

        # Creatures only, under the source's controller.
        if not is_creature_now(target):
            return False
        if target.controller_id != source.controller_id:
            return False
        # "During your turn" gate.
        if self.active_turn_only:
            if state is None:
                return False
            if state.players[state.active_player_idx].id != source.controller_id:
                return False
        # Spacecraft tier gate — source needs enough charge counters.
        if self.tier_threshold > 0 and source.charge_counters < self.tier_threshold:
            return False
        # "As long as you control an artifact" gate.
        if self.requires_artifact_you_control:
            if state is None:
                return False
            has_artifact = any(
                o.controller_id == source.controller_id
                and o.printing.is_artifact
                for o in state.battlefield
            )
            if not has_artifact:
                return False
        # "As long as you've cast N or more spells this turn" gate.
        if self.requires_spells_cast_this_turn > 0:
            if state is None:
                return False
            controller = state.player_by_id(source.controller_id)
            if (
                controller.spells_cast_this_turn
                < self.requires_spells_cast_this_turn
            ):
                return False
        if self.scope == StaticScope.SELF:
            return target.id == source.id
        if self.scope == StaticScope.OTHER_CREATURES_YOU_CONTROL:
            return target.id != source.id
        if self.scope == StaticScope.CREATURES_YOU_CONTROL:
            return True
        if self.scope == StaticScope.CREATURES_YOU_CONTROL_WITH_COUNTER:
            return target.plus_one_counters > 0
        if self.scope == StaticScope.OTHER_TAPPED_LEGENDARY_CREATURES_YOU_CONTROL:
            return (
                target.id != source.id
                and target.tapped
                and "Legendary" in target.printing.supertypes
            )
        return False

    def describe(self) -> str:
        who = {
            StaticScope.OTHER_CREATURES_YOU_CONTROL: "Other creatures you control",
            StaticScope.CREATURES_YOU_CONTROL: "Creatures you control",
        }.get(self.scope, self.scope)
        parts: list[str] = []
        if self.power_bonus or self.toughness_bonus:
            sign_p = "+" if self.power_bonus >= 0 else ""
            sign_t = "+" if self.toughness_bonus >= 0 else ""
            parts.append(
                f"get {sign_p}{self.power_bonus}/{sign_t}{self.toughness_bonus}"
            )
        if self.granted_keywords:
            kws = ", ".join(sorted(self.granted_keywords))
            parts.append(f"have {kws}")
        return f"{who} {' and '.join(parts)}." if parts else f"{who} (no effect)."


@dataclass(frozen=True)
class TriggeredAbility:
    """An ability that fires on a specific event.

    Supported triggers:
      - ``"etb"`` — when the permanent enters the battlefield
      - ``"beginning_of_end_step"`` — at the start of its controller's end step

    ``requires_void`` is True for EoE "Void —" abilities, which only fire when
    ``is_void_active(state)`` (a nonland permanent left the battlefield this
    turn or a spell was warped this turn).
    """

    trigger: str
    effect: Effect
    requires_void: bool = False
    # "This ability triggers only once each turn." When True, the firing
    # site records (source_id, ability_index) in state.once_per_turn_fired
    # and suppresses subsequent fires within the same turn. Reset at
    # cleanup.
    once_per_turn: bool = False
    # EoE Spacecraft tier gate: ability is active only when the source has
    # ``tier_threshold`` or more charge counters. 0 = always on. Mirrors
    # ``StaticAbility.tier_threshold``. Consumed by should_fire_trigger.
    tier_threshold: int = 0

    def describe(self) -> str:
        prefix = {
            "etb": "When ~ enters the battlefield",
            "beginning_of_end_step": "At the beginning of your end step",
            "beginning_of_combat": "At the beginning of combat on your turn",
            "dies": "When ~ dies",
            "landfall": "Landfall — Whenever a land you control enters",
            "becomes_tapped": "Whenever ~ becomes tapped",
            "second_spell_each_turn": (
                "Whenever you cast your second spell each turn"
            ),
            "artifact_enters_you_control": (
                "Whenever another artifact you control enters"
            ),
            "creature_or_artifact_enters_you_control": (
                "Whenever another creature or artifact you control enters"
            ),
            "attacks": "Whenever ~ attacks",
            "leaves_battlefield": "When ~ leaves the battlefield",
            "nontoken_artifact_enters_you_control": (
                "Whenever a nontoken artifact you control enters"
            ),
            "creature_you_control_with_counter_dies": (
                "Whenever a creature you control with a +1/+1 counter on "
                "it dies"
            ),
            "sacrifice_creature_or_artifact": (
                "Whenever you sacrifice another creature or artifact"
            ),
            "combat_damage_to_player": (
                "Whenever this creature deals combat damage to a player"
            ),
            "your_creature_combat_damage_to_player": (
                "Whenever a creature you control deals combat damage "
                "to a player"
            ),
            "another_creature_you_control_dies_or_exiled": (
                "Whenever another creature you control dies or is put "
                "into exile"
            ),
        }.get(self.trigger, self.trigger)
        head = f"{prefix}, {self.effect.describe()}."
        if self.requires_void:
            return "Void — " + head
        return head
