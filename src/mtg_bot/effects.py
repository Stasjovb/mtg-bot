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
class Surveil(Effect):
    """Surveil N: look at the top N cards of your library; for each one, you
    may put it into your graveyard. The rest stay on top in their original
    order. Decision delegated to the controller's agent (choose_surveil).
    """

    amount: int = 1

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone

        p = state.player_by_id(controller_id)
        milled = 0
        # Examine the top N cards in order. Mill ones the agent chooses;
        # keep the rest on top in their original order.
        examined = p.library[: self.amount]
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
            f"P{controller_id} surveils {self.amount} ({milled} milled)"
        )

    def describe(self) -> str:
        return f"surveil {self.amount}"


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
    cleared at cleanup.
    """

    power_bonus: int = 0
    toughness_bonus: int = 0
    granted_keywords: frozenset[str] = frozenset()
    you_control_only: bool = False  # restrict to "target creature you control"

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
    """

    power_bonus: int = 0
    toughness_bonus: int = 0
    granted_keywords: frozenset[str] = frozenset()

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        count = 0
        for obj in state.battlefield:
            if obj.controller_id != controller_id:
                continue
            if not obj.printing.is_creature:
                continue
            obj.temp_power_bonus += self.power_bonus
            obj.temp_toughness_bonus += self.toughness_bonus
            if self.granted_keywords:
                obj.temp_keywords = obj.temp_keywords | self.granted_keywords
            count += 1
        state.log.append(
            f"P{controller_id}'s creatures ({count}) get "
            f"+{self.power_bonus}/+{self.toughness_bonus} until end of turn"
        )

    def describe(self) -> str:
        return (
            f"creatures you control get "
            f"+{self.power_bonus}/+{self.toughness_bonus} until end of turn"
        )


@dataclass(frozen=True)
class SearchLibraryForBasicLandTapped(Effect):
    """Search the controller's library for a basic land card, put it onto
    the battlefield tapped, then shuffle.

    Stage 3 simplification: picks the FIRST basic land in library order
    (the library was shuffled at game start; no extra shuffle here). If no
    basic land is present, the effect does nothing.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone
        from mtg_bot.turn import fire_landfall_triggers

        p = state.player_by_id(controller_id)
        land = next((c for c in p.library if c.printing.is_basic_land), None)
        if land is None:
            state.log.append(
                f"P{controller_id} searches but finds no basic land"
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
        return (
            "search your library for a basic land card, put it onto the "
            "battlefield tapped, then shuffle"
        )


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
            for _ in range(self.count):
                obj = state.new_object(
                    self.token_printing, owner_id=recipient, zone=Zone.BATTLEFIELD
                )
                state.log.append(
                    f"P{recipient} creates a {self.token_printing.name} token"
                    + (" (tapped)" if self.tapped else "")
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
        state.log.append(f"{obj.printing.name} is destroyed")
        move_off_battlefield(state, obj, destination="graveyard")

    def describe(self) -> str:
        return "destroy target creature"


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
        state.log.append(f"{obj.printing.name} is destroyed")
        move_off_battlefield(state, obj, destination="graveyard")

    def describe(self) -> str:
        return "destroy target artifact or tapped creature"


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
        obj.temp_power_bonus -= self.power_penalty
        state.log.append(
            f"{obj.printing.name} gets -{self.power_penalty}/-0 until end "
            f"of turn"
        )
        # "Then if that creature's power is 0 or less, destroy it."
        if effective_power(state, obj) <= 0:
            state.log.append(f"{obj.printing.name} is destroyed (depressurized)")
            move_off_battlefield(state, obj, destination="graveyard")

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
        if not self._is_legal(state, obj):
            return
        state.log.append(f"{obj.printing.name} is destroyed")
        move_off_battlefield(state, obj, destination="graveyard")

    def describe(self) -> str:
        return (
            "destroy target artifact, enchantment, or creature with flying"
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
        former_controller = obj.controller_id
        state.log.append(f"{obj.printing.name} is destroyed")
        move_off_battlefield(state, obj, destination="graveyard")
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
        obj.plus_one_counters += self.amount
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
        count = 0
        for obj in state.battlefield:
            if obj.controller_id != controller_id:
                continue
            if not obj.printing.is_creature:
                continue
            obj.plus_one_counters += self.amount
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
        source = state.resolving_source
        if source is None:
            return
        source.plus_one_counters += self.amount
        state.log.append(
            f"{source.printing.name} gets a +1/+1 counter "
            f"(now {source.plus_one_counters})"
        )

    def describe(self) -> str:
        if self.amount == 1:
            return "put a +1/+1 counter on this creature"
        return f"put {self.amount} +1/+1 counters on this creature"


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
        obj.plus_one_counters += self.amount
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

    def describe(self) -> str:
        if self.count == 1:
            return "each opponent discards a card"
        return f"each opponent discards {self.count} cards"


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

    def describe(self) -> str:
        parts: list[str] = []
        if self.mana_str:
            parts.append(self.mana_str)
        if self.tap_self:
            parts.append("{T}")
        if self.sacrifice_self:
            parts.append("Sacrifice ~")
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
    """

    scope: str
    granted_keywords: frozenset[str] = frozenset()
    power_bonus: int = 0
    toughness_bonus: int = 0
    active_turn_only: bool = False
    # Tiered abilities on Spacecraft: the ability is only active when the
    # source has ``tier_threshold`` or more charge counters. 0 = always on.
    tier_threshold: int = 0

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
        if self.scope == StaticScope.OTHER_CREATURES_YOU_CONTROL:
            return target.id != source.id
        if self.scope == StaticScope.CREATURES_YOU_CONTROL:
            return True
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

    def describe(self) -> str:
        prefix = {
            "etb": "When ~ enters the battlefield",
            "beginning_of_end_step": "At the beginning of your end step",
            "beginning_of_combat": "At the beginning of combat on your turn",
            "dies": "When ~ dies",
            "landfall": "Landfall — Whenever a land you control enters",
            "becomes_tapped": "Whenever ~ becomes tapped",
        }.get(self.trigger, self.trigger)
        head = f"{prefix}, {self.effect.describe()}."
        if self.requires_void:
            return "Void — " + head
        return head
