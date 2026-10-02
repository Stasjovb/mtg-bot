"""Roto package P6 effects: keyword mechanics, face-changing & pregame.

Engine pieces for the Vintage Roto cards P6 claims
(``docs/ROTO_COVERAGE_PLAN.md`` section 6); the grammar is
``mtg_bot.cards.parser.roto_keywords``.

* :class:`ManaValueCardFilter` -- a library-search filter for "a card
  with the same mana value as the discarded card" (Transmute, CR
  702.53).
* :class:`LookAtTopMayRevealIfMatches` -- Delver of Secrets' upkeep
  look / may-reveal / if-revealed effect.
* :class:`RegenerateSource` -- "Regenerate this creature." (Blight Mamba).
* :class:`PutPlusOneCountersOnEachCreatureTargetPlayerControls` --
  Requisition Raid's third Spree mode.
* :class:`PayLifeCost` -- a "Pay N life" ``extra_costs`` atom ("Cycling—
  Pay 2 life.", Street Wraith).
* :func:`blocked_by_landwalk` -- landwalk block legality (CR 702.14),
  consulted by ``combat.can_block``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mtg_bot.effects.base import Effect, Target
from mtg_bot.effects.predicates import TriggerPredicate
from mtg_bot.effects.generic.card_flow import CardFilter

if TYPE_CHECKING:
    from mtg_bot.cards.base import CardPrinting
    from mtg_bot.game import GameState


@dataclass(frozen=True)
class ManaValueCardFilter(CardFilter):
    """A card whose mana value is exactly ``mana_value`` (on top of any
    inherited ``CardFilter`` restriction). In a library ``{X}`` is 0
    (CR 202.3e), which ``ManaCost.total`` already reflects."""

    mana_value: int = 0

    @property
    def has_quality(self) -> bool:
        return True

    def matches(self, printing: "CardPrinting") -> bool:
        return (
            printing.mana_cost.total == self.mana_value
            and super().matches(printing)
        )

    def describe(self) -> str:
        return f"{super().describe()} with mana value {self.mana_value}"


@dataclass(frozen=True)
class LookAtTopMayRevealIfMatches(Effect):
    """"Look at the top card of your library. You may reveal that card.
    If a <filter> card is revealed this way, <then>." (Delver of Secrets.)

    The controller looks at the top card; the reveal is offered only
    when the card matches ``card_filter`` -- revealing any other card
    changes nothing but what the opponent knows, a dominated choice the
    engine doesn't offer (``docs/SEARCH_LIMITATIONS.md``). ``then`` runs
    only when the matching card is revealed."""

    card_filter: CardFilter = CardFilter()
    then: "Effect | None" = None

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import reveal_to, reveal_to_all

        player = state.player_by_id(controller_id)
        if not player.library:
            return
        top = player.library[0]
        reveal_to(top, controller_id)
        if not self.card_filter.matches(top.printing):
            state.log.append(f"P{controller_id} looks at the top card of their library")
            return
        if player.agent is not None and not player.agent.choose_yes_no(
            state, controller_id, f"reveal {top.printing.name}",
        ):
            state.log.append(
                f"P{controller_id} looks at the top card of their library "
                f"and doesn't reveal it"
            )
            return
        reveal_to_all(state, top)
        state.log.append(
            f"P{controller_id} reveals {top.printing.name} from the top of "
            f"their library"
        )
        self.then.resolve(state, controller_id, targets)

    def describe(self) -> str:
        return (
            "look at the top card of your library; you may reveal it; if "
            f"it's a {self.card_filter.describe()}, {self.then.describe()}"
        )


@dataclass(frozen=True)
class RegenerateSource(Effect):
    """"Regenerate this creature." (CR 701.15) -- the resolving ability's
    source gets the engine's regeneration shield
    (``GameObject.regeneration_shield``, consumed by the destruction
    state-based action, cleared at cleanup). The shield is a flag, so a
    second activation in the same turn adds nothing
    (``docs/SEARCH_LIMITATIONS.md``)."""

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import is_creature_now

        source = state.resolving_source
        if source is None or source not in state.battlefield:
            return
        if not is_creature_now(source):
            return
        source.regeneration_shield = True
        state.log.append(f"{source.printing.name} gains a regeneration shield")

    def describe(self) -> str:
        return "regenerate this creature"


@dataclass(frozen=True)
class PutPlusOneCountersOnEachCreatureTargetPlayerControls(Effect):
    """"Put N +1/+1 counter(s) on each creature target player controls."
    (Requisition Raid's third Spree mode.)"""

    amount: int = 1
    targets: tuple = ()

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.effects.generic.targets_helpers import _slot_target_still_legal
        from mtg_bot.game import add_plus_one_counters, is_creature_now

        if not targets:
            return
        prior = state.resolving_controller_id
        try:
            state.resolving_controller_id = controller_id
            if not _slot_target_still_legal(state, self.targets[0], targets[0]):
                return
        finally:
            state.resolving_controller_id = prior
        player_id = targets[0][1]
        for obj in list(state.battlefield):
            if obj.controller_id == player_id and is_creature_now(obj):
                add_plus_one_counters(state, obj, self.amount)
        state.log.append(
            f"each creature P{player_id} controls gets {self.amount} +1/+1 "
            f"counter(s)"
        )

    def describe(self) -> str:
        return (
            f"put {self.amount} +1/+1 counter(s) on each creature target "
            f"player controls"
        )


@dataclass(frozen=True)
class PayLifeCost:
    """"Pay N life" as an ``ActivationCost.extra_costs`` atom -- the cost
    protocol the hand / graveyard activation paths already pay (Street
    Wraith's "Cycling—Pay 2 life."). CR 119.4: payable only when the
    player's life total is at least N (paying down to 0 is legal)."""

    amount: int

    def payable(self, state, player_id: int, source) -> bool:
        return state.player_by_id(player_id).life >= self.amount

    def pay(self, state, player_id: int, source) -> list:
        player = state.player_by_id(player_id)
        player.life -= self.amount
        state.log.append(
            f"P{player_id} pays {self.amount} life (life: {player.life})"
        )
        return []

    def describe(self) -> str:
        return f"Pay {self.amount} life"


# Landwalk (CR 702.14): engine keyword -> the land subtype it walks.
LANDWALK_KEYWORDS = {
    "plainswalk": "Plains", "islandwalk": "Island", "swampwalk": "Swamp",
    "mountainwalk": "Mountain", "forestwalk": "Forest",
}


def blocked_by_landwalk(state: "GameState", attacker, blocker) -> bool:
    """CR 702.14c: a creature with <type>walk can't be blocked as long as
    the defending player (the blocker's controller) controls a land with
    that subtype (layered subtypes, so Urborg-style grants count)."""
    from mtg_bot.game import effective_keywords, effective_subtypes

    kws = effective_keywords(state, attacker)
    walks = [sub for kw, sub in LANDWALK_KEYWORDS.items() if kw in kws]
    if not walks:
        return False
    return any(
        o.controller_id == blocker.controller_id
        and o.printing.is_land
        and any(sub in effective_subtypes(state, o) for sub in walks)
        for o in state.battlefield
    )


@dataclass(frozen=True)
class FewerMinusOneCountersOnYourCreatures:
    """Printed static (``CardPrinting.replacement_statics``): "If one or
    more -1/-1 counters would be put on a creature you control, that
    many -1/-1 counters minus <reduction> are put on it instead."
    (Vizier of Remedies.)"""

    reduction: int = 1

    def describe(self) -> str:
        return (
            "if one or more -1/-1 counters would be put on a creature you "
            f"control, that many minus {self.reduction} are put on it instead"
        )


def adjust_minus_one_counters(state: "GameState", obj, amount: int) -> int:
    """The number of -1/-1 counters actually put on ``obj`` when
    ``amount`` would be: each ``FewerMinusOneCountersOnYourCreatures``
    permanent controlled by the creature's controller takes its
    reduction off (never below 0). Called by
    ``game.add_minus_one_counters``, the engine's single -1/-1 counter
    writer."""
    from mtg_bot.game import is_creature_now

    if amount <= 0 or not is_creature_now(obj):
        return amount
    for source in state.battlefield:
        if source.controller_id != obj.controller_id:
            continue
        for rule in source.printing.replacement_statics:
            if isinstance(rule, FewerMinusOneCountersOnYourCreatures):
                amount = max(0, amount - rule.reduction)
                state.log.append(
                    f"{source.printing.name}: {amount} -1/-1 counter(s) are "
                    f"put on {obj.printing.name} instead"
                )
    return amount


# ---------------------------------------------------- becomes the target


@dataclass(frozen=True)
class TargetingIs(TriggerPredicate):
    """``BECOMES_TARGET``: the targeting stack object (the ``targeting``
    subject ``cube_creatures_rmc.fire_becomes_target`` passes) is a
    spell (``kind="spell"``, copies included) or an ability
    (``kind="ability"``)."""

    kind: str = "spell"

    def matches(self, state, subjects, source):
        item = subjects.get("targeting")
        if item is None:
            return False
        is_spell = item.ability is None
        return is_spell if self.kind == "spell" else not is_spell


@dataclass(frozen=True)
class TargetIsPlayerOrPermanent(TriggerPredicate):
    """``BECOMES_TARGET`` of a player or a permanent (not a spell on the
    stack, which arrives as ``target_spell``)."""

    def matches(self, state, subjects, source):
        return subjects.get("target") is not None


@dataclass(frozen=True)
class TargetOpponentGetsPoisonCounters(Effect):
    """"Target opponent gets N poison counter(s)." (Venerated
    Rotpriest.)"""

    amount: int = 1
    targets: tuple = ()

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.effects.generic.targets_helpers import _slot_target_still_legal

        if not targets:
            return
        prior = state.resolving_controller_id
        try:
            state.resolving_controller_id = controller_id
            if not _slot_target_still_legal(state, self.targets[0], targets[0]):
                return
        finally:
            state.resolving_controller_id = prior
        player = state.player_by_id(targets[0][1])
        player.poison_counters += self.amount
        state.log.append(
            f"P{player.id} gets {self.amount} poison counter(s) "
            f"(now {player.poison_counters})"
        )

    def describe(self) -> str:
        return f"target opponent gets {self.amount} poison counter(s)"


@dataclass(frozen=True)
class DealDamageToPlayerEqualToTheirHandSize(Effect):
    """"<this creature> deals damage to that player equal to the number of
    cards in their hand." -- the player arrives as ``targets[0]``, bound
    from the triggering event by ``BindEventPlayer`` (Emberwilde
    Captain)."""

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.effects.base import _apply_damage

        if not targets or targets[0][0] != "player":
            return
        player = state.player_by_id(targets[0][1])
        amount = len(player.hand)
        if amount > 0:
            _apply_damage(state, ("player", player.id), amount)

    def describe(self) -> str:
        return (
            "this creature deals damage to that player equal to the number "
            "of cards in their hand"
        )


# ----------------------------------------------------------- split second

SPLIT_SECOND = "split second"


def split_second_on_stack(state: "GameState") -> bool:
    """A spell with split second (copies included) is on the stack."""
    return any(
        item.ability is None and SPLIT_SECOND in item.source.printing.keywords
        for item in state.stack
    )


def _is_mana_ability_action(state: "GameState", action) -> bool:
    from mtg_bot.game import Zone, effective_activated_abilities

    obj = next((o for o in state.battlefield if o.id == action.source_id), None)
    if obj is not None:
        abilities = effective_activated_abilities(state, obj)
    else:
        obj = next(
            (
                c for p in state.players for c in (*p.hand, *p.graveyard)
                if c.id == action.source_id
            ),
            None,
        )
        if obj is None:
            return False
        abilities = (
            obj.printing.hand_activated_abilities if obj.zone == Zone.HAND
            else obj.printing.graveyard_activated_abilities
        )
    if not 0 <= action.ability_index < len(abilities):
        return False
    return abilities[action.ability_index].is_mana_ability


def filter_split_second(state: "GameState", actions: list) -> list:
    """CR 702.61b: while a spell with split second is on the stack,
    players can't cast spells or activate abilities that aren't mana
    abilities. Special actions stay legal (plotting a card, turning a
    face-down permanent face up, unlocking a door), and triggered
    abilities still trigger."""
    if not state.stack or not split_second_on_stack(state):
        return actions
    from mtg_bot.actions import ActivateAbility, ActivateStation, CastSpell

    kept = []
    for action in actions:
        if isinstance(action, CastSpell) and not action.use_plot:
            continue
        if isinstance(action, ActivateStation):
            continue
        if isinstance(action, ActivateAbility) and not _is_mana_ability_action(
            state, action,
        ):
            continue
        kept.append(action)
    return kept


@dataclass(frozen=True)
class SourceDealsDamageEqualToItsPowerToTarget(Effect):
    """"<this creature> deals damage equal to its power to [up to one]
    target <np>." -- the resolving ability's source is the damage
    source; its power is read on resolution (last known power if it
    has left the battlefield)."""

    targets: tuple = ()

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.effects.base import _apply_damage
        from mtg_bot.effects.generic.targets_helpers import _slot_target_still_legal
        from mtg_bot.game import effective_power

        source = state.resolving_source
        if not targets or source is None:
            return
        prior = state.resolving_controller_id
        try:
            state.resolving_controller_id = controller_id
            if not _slot_target_still_legal(state, self.targets[0], targets[0]):
                return
        finally:
            state.resolving_controller_id = prior
        amount = effective_power(state, source)
        if amount > 0:
            _apply_damage(state, targets[0], amount)

    def describe(self) -> str:
        from mtg_bot.effects.generic.targets_helpers import _describe_targets

        return (
            "this creature deals damage equal to its power to "
            f"{_describe_targets(self.targets)}"
        )


@dataclass(frozen=True)
class UntapTargetThenGrantUntilEndOfTurn(Effect):
    """"Untap target <np>. Until end of turn, it gains <keywords>[, and
    "<triggered ability>"]." (Legolas's Quick Reflexes.)"""

    targets: tuple = ()
    keywords: frozenset = frozenset()
    granted_trigger: object = None

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.effects.combinators import ApplyEffect
        from mtg_bot.effects.durations import EndOfTurn
        from mtg_bot.effects.generic.grant_keywords import (
            GrantKeywords,
            GrantTriggeredAbility,
        )
        from mtg_bot.effects.generic.targets_helpers import _slot_target_still_legal

        if not targets:
            return
        prior = state.resolving_controller_id
        try:
            state.resolving_controller_id = controller_id
            if not _slot_target_still_legal(state, self.targets[0], targets[0]):
                return
        finally:
            state.resolving_controller_id = prior
        obj = next((o for o in state.battlefield if o.id == targets[0][1]), None)
        if obj is None:
            return
        if obj.tapped:
            obj.tapped = False
            state.log.append(f"{obj.printing.name} is untapped")
        it = (("creature", obj.id),)
        if self.keywords:
            ApplyEffect(
                inner=GrantKeywords(keywords=self.keywords), ends_at=EndOfTurn(),
            ).resolve(state, controller_id, it)
        if self.granted_trigger is not None:
            ApplyEffect(
                inner=GrantTriggeredAbility(ability=self.granted_trigger),
                ends_at=EndOfTurn(),
            ).resolve(state, controller_id, it)

    def describe(self) -> str:
        from mtg_bot.effects.generic.targets_helpers import _describe_targets

        text = (
            f"untap {_describe_targets(self.targets)}; until end of turn it "
            f"gains {', '.join(sorted(self.keywords))}"
        )
        if self.granted_trigger is not None:
            text += f' and "{self.granted_trigger.describe()}"'
        return text


def fire_granted_becomes_tapped_triggers(state: "GameState", obj) -> None:
    """Push "Whenever this creature becomes tapped" abilities ``obj``
    has been granted (layer-6 registry grants, which the printed-ability
    ``dispatch_event`` sweep doesn't see) -- the ``combat`` granted
    attack-trigger pattern, called from ``turn.tap_permanent``."""
    if not state.continuous_effects:
        return
    from mtg_bot.actions import push_triggered_ability
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import effective_triggered_abilities

    granted = [
        ab for ab in effective_triggered_abilities(state, obj)
        if ab not in obj.printing.triggered_abilities
    ]
    for i, ability in enumerate(granted):
        if ability.matches_event(Event.BECOMES_TAPPED, {"obj": obj}, obj, state):
            push_triggered_ability(
                state, source=obj, ability=ability, ability_index=4000 + i,
                controller_id=obj.controller_id, label="becomes-tapped (granted)",
            )


# ------------------------------------------------------------------ toxic

TOXIC_PREFIX = "toxic "


def toxic_amount(state: "GameState", obj) -> int:
    """Total toxic of ``obj`` (CR 702.164c: instances are cumulative);
    the keyword is spelled ``"toxic N"``."""
    from mtg_bot.game import effective_keywords

    return sum(
        int(kw[len(TOXIC_PREFIX):])
        for kw in effective_keywords(state, obj)
        if kw.startswith(TOXIC_PREFIX) and kw[len(TOXIC_PREFIX):].isdigit()
    )


def apply_toxic(state: "GameState", sources_hit_player) -> None:
    """Toxic N (CR 702.164): a player dealt combat damage by a creature
    with toxic also gets N poison counters. ``sources_hit_player`` is the
    combat step's ``(source_id, player_id, amount)`` list of damage
    actually dealt (``combat._resolve_damage_step``)."""
    for source_id, player_id, amount in sources_hit_player:
        if amount <= 0:
            continue
        source = next((o for o in state.battlefield if o.id == source_id), None)
        if source is None:
            continue
        n = toxic_amount(state, source)
        if n:
            player = state.player_by_id(player_id)
            player.poison_counters += n
            state.log.append(
                f"P{player_id} gets {n} poison counter(s) from toxic "
                f"(now {player.poison_counters})"
            )


__all__ = [
    "SPLIT_SECOND",
    "SourceDealsDamageEqualToItsPowerToTarget",
    "UntapTargetThenGrantUntilEndOfTurn",
    "filter_split_second",
    "fire_granted_becomes_tapped_triggers",
    "split_second_on_stack",
    "DealDamageToPlayerEqualToTheirHandSize",
    "TOXIC_PREFIX",
    "TargetIsPlayerOrPermanent",
    "TargetOpponentGetsPoisonCounters",
    "TargetingIs",
    "apply_toxic",
    "toxic_amount",
    "FewerMinusOneCountersOnYourCreatures",
    "adjust_minus_one_counters",
    "LANDWALK_KEYWORDS",
    "PayLifeCost",
    "blocked_by_landwalk",
    "LookAtTopMayRevealIfMatches",
    "ManaValueCardFilter",
    "PutPlusOneCountersOnEachCreatureTargetPlayerControls",
    "RegenerateSource",
]
