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


__all__ = [
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
