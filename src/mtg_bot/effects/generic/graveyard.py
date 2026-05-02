"""Generic effects cluster module. Behavior and API unchanged from
the pre-split mtg_bot.effects.generic monolith; this is a pure file move."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from mtg_bot.effects.base import (
    Effect, Target, TriggeredAbility,
    _apply_damage, _multicolored_permanents_count,
    _find_moonlit_replacement_source,
)
from mtg_bot.effects.generic.targets_helpers import (
    _eff_subtypes,
    _slot_target_still_legal,
    _fizzle_message,
    _describe_targets,
    _describe_filter,
    _bounce_to_hand,
)

if TYPE_CHECKING:
    from mtg_bot.cards import ManaCost
    from mtg_bot.effects.formulas import Formula
    from mtg_bot.game import GameState


@dataclass(frozen=True)
class ReturnCreatureFromYourGraveyardToBattlefield(Effect):
    """Target creature card from your graveyard enters the battlefield under
    your control. Fires ETB triggers (via put_into_battlefield).

    Target format: ``("graveyard_creature", id)`` where id is a GameObject
    in the controller's graveyard.

    ``max_mv``: when set, restricts the legal target pool to creature
    cards with mana value ≤ ``max_mv``. Models Surgical Suite's "with
    mana value 3 or less" rider. None = no mana-value restriction.

    ``or_enchantment`` widens the legal-target pool to also include
    enchantment cards in the graveyard. Matches oracle text "return
    target creature or enchantment card from your graveyard to the
    battlefield" — Rescue Skiff's ETB body. Mirrors the ``or_spacecraft``
    flag on ``ReturnCreatureFromYourGraveyardToHand`` (Fell Gravship).
    """

    max_mv: "int | None" = None
    # When True, enchantment cards in the graveyard are also legal
    # targets. Matches "return target creature or enchantment card from
    # your graveyard to the battlefield" — Rescue Skiff.
    or_enchantment: bool = False
    # When True, Spacecraft cards in the graveyard are also legal
    # targets. Matches "return target creature or Spacecraft card from
    # your graveyard to the battlefield" — Seedship Broodtender.
    or_spacecraft: bool = False

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        p = state.player_by_id(controller_id)
        return [
            ("graveyard_creature", c.id)
            for c in p.graveyard
            if (
                c.printing.is_creature
                or (self.or_enchantment and c.printing.is_enchantment)
                or (self.or_spacecraft and c.printing.is_spacecraft)
            )
            and (
                self.max_mv is None
                or c.printing.mana_cost.total <= self.max_mv
            )
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
        type_phrase = (
            "creature or enchantment" if self.or_enchantment else "creature"
        )
        return (
            f"return target {type_phrase} card from your graveyard to the "
            f"battlefield"
        )



@dataclass(frozen=True)
class ReturnAllCreaturesFromYourGraveyardToBattlefield(Effect):
    """Return every creature card from your graveyard to the battlefield
    under your control. Untargeted mass-reanimation — Awakening Hall's
    "Return all creature cards from your graveyard to the battlefield"
    when its door is unlocked.

    Each creature is moved out of the graveyard and routed through
    ``put_into_battlefield`` so its ETB triggers fire normally. Order
    of resolution follows the graveyard's stored order (oldest first);
    we don't model APNAP for the iteration since the controller is the
    same player throughout.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.actions import put_into_battlefield

        p = state.player_by_id(controller_id)
        # Snapshot the graveyard before mutation — entering creatures
        # could (in theory) trigger other effects that touch the
        # graveyard mid-resolution. We iterate the snapshot.
        creatures = [c for c in list(p.graveyard) if c.printing.is_creature]
        for card in creatures:
            if card not in p.graveyard:
                # Defensive: an ETB earlier in this loop already moved
                # the card (very rare; included for safety).
                continue
            p.graveyard.remove(card)
            state.log.append(
                f"{card.printing.name} returns from P{controller_id}'s "
                f"graveyard to the battlefield"
            )
            put_into_battlefield(state, card, controller_id)

    def describe(self) -> str:
        return (
            "return all creature cards from your graveyard to the "
            "battlefield"
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
class ReanimateTargetCreatureCardFromDefendersGraveyard(Effect):
    """Put target creature card from a defending player's graveyard
    onto the battlefield under the resolving controller's control,
    tapped and attacking.

    Used by Chorale of the Void's attacks trigger: the source aura's
    enchanted creature attacks, and the trigger reanimates a creature
    card from the defending player's graveyard, on the active player's
    side, already attacking.

    Target kind: ``("graveyard_creature", id)``. The legal-target pool
    is the union of every opponent's graveyard creature cards. In
    2-player mode this matches the printed "defending player" exactly
    because the resolving controller has only one opponent; in
    multiplayer / planeswalker-defender cases this is an approximation
    until the engine threads per-attacker defender identity into a
    state slot the effect can read.

    Resolve semantics:

    1. Locate the chosen card in any opponent's graveyard; remove it.
    2. ``put_into_battlefield`` brings it on under the resolving
       controller's id (CR 405.5: "under your control" — the ETB is
       the new permanent's first ETB under that controller).
    3. ``obj.tapped = True``, ``obj.attacking = True``,
       ``obj.summoning_sick = False`` so the new permanent is a
       legal attacker for the in-progress combat phase. The engine's
       combat damage path reads ``obj.attacking`` and the defending
       player id from the calling combat phase (single-defender
       semantics; the new attacker rides the same defender as the
       triggering attacker).
    """

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return [
            ("graveyard_creature", c.id)
            for p in state.players
            if p.id != controller_id
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
        for p in state.players:
            card = next(
                (c for c in p.graveyard if c.id == target_id), None,
            )
            if card is None:
                continue
            p.graveyard.remove(card)
            state.log.append(
                f"{card.printing.name} returns from P{p.id}'s graveyard "
                f"under P{controller_id} tapped and attacking"
            )
            put_into_battlefield(state, card, controller_id)
            card.tapped = True
            card.attacking = True
            card.summoning_sick = False
            return

    def describe(self) -> str:
        return (
            "put target creature card from defending player's "
            "graveyard onto the battlefield under your control tapped "
            "and attacking"
        )
