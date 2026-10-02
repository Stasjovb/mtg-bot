"""Engine effects for the Vintage Roto P5 package (board-state prison &
layers): mass effects keyed on mana value / counters, per-player
damage, tap-all effects and the cost atoms the package's activated
abilities print.

Grammar lives in :mod:`mtg_bot.cards.parser.roto_board`; static
abilities that change the board's rules (combat restrictions, untap
limits, layer contributions) live in :mod:`mtg_bot.roto_board_statics`.
Shortcuts are documented in ``docs/SEARCH_LIMITATIONS.md`` (Roto P5
section).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mtg_bot.effects.base import Effect, Target
from mtg_bot.effects.object_predicates import ObjectPredicate

if TYPE_CHECKING:
    from mtg_bot.game import GameObject, GameState


# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HasManaValueEqualToSourceCounters(ObjectPredicate):
    """"with mana value equal to the number of <kind> counters on
    <this permanent>" (Engineered Explosives' charge counters, The
    Filigree Sylex's oil counters). The source is the resolving
    ability's source; when the ability was activated by sacrificing it,
    the departed object still carries its counters (last-known
    information: ``turn.move_off_battlefield`` keeps counters on an
    object put into a graveyard or exile)."""

    kind: str

    def test(self, obj, state):
        if not hasattr(obj, "printing"):
            return False
        from mtg_bot.effects.value_predicates import mana_value_of
        from mtg_bot.game import counter_count

        source = getattr(state, "resolving_source", None)
        if source is None:
            return False
        return mana_value_of(obj) == counter_count(source, self.kind)


@dataclass(frozen=True)
class IsLegendaryPermanent(ObjectPredicate):
    """"legendary" as a permanent modifier (Minamo's "target legendary
    permanent")."""

    def test(self, obj, state):
        if not hasattr(obj, "printing"):
            return False
        return "Legendary" in obj.printing.supertypes


@dataclass(frozen=True)
class LacksSubtype(ObjectPredicate):
    """"non-<Subtype>" (Emerald Charm's "non-Aura enchantment"), read
    through the effective subtypes."""

    subtype: str

    def test(self, obj, state):
        if not hasattr(obj, "printing"):
            return False
        from mtg_bot.game import effective_subtypes

        return self.subtype not in effective_subtypes(state, obj)


# ---------------------------------------------------------------------------
# Damage
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DamageEachPlayerPerControlled(Effect):
    """"<This> deals damage to each player equal to [twice] the number
    of <permanents> that player controls." (Price of Progress). Each
    player's amount is counted from their own permanents when the spell
    resolves; all of it is dealt as one simultaneous event (life totals
    are only checked by the state-based actions afterwards)."""

    per_filter: ObjectPredicate
    multiplier: int = 1
    label: str = "permanents"

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.effects.base import _apply_damage

        amounts: list[tuple[int, int]] = []
        for p in state.players:
            if p.has_lost:
                continue
            n = sum(
                1 for o in state.battlefield
                if o.controller_id == p.id and self.per_filter.test(o, state)
            )
            amounts.append((p.id, n * self.multiplier))
        for pid, amount in amounts:
            if amount > 0:
                _apply_damage(state, ("player", pid), amount)

    def describe(self) -> str:
        times = "twice " if self.multiplier == 2 else (
            "" if self.multiplier == 1 else f"{self.multiplier} times "
        )
        return (
            f"deals damage to each player equal to {times}the number of "
            f"{self.label} that player controls"
        )


@dataclass(frozen=True)
class DealDamageToEachTarget(Effect):
    """"<This> deals N damage to each of one or two targets." (Prismari
    Charm): one target slot with a count range; every chosen target that
    is still legal takes the damage."""

    amount: int = 1
    targets: tuple = ()

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.effects.base import _apply_damage
        from mtg_bot.effects.generic.targets_helpers import (
            _fizzle_message,
            _slot_target_still_legal,
        )

        if not targets or not self.targets:
            return
        slot = self.targets[0]
        prior = state.resolving_controller_id
        try:
            state.resolving_controller_id = controller_id
            legal = []
            for chosen in targets:
                if _slot_target_still_legal(state, slot, chosen):
                    legal.append(chosen)
                else:
                    state.log.append(_fizzle_message(state, chosen))
        finally:
            state.resolving_controller_id = prior
        for chosen in legal:
            _apply_damage(state, chosen, self.amount)

    def describe(self) -> str:
        slot = self.targets[0] if self.targets else None
        n = (
            "one or two" if slot is not None and slot.count_min == 1
            and slot.count_max == 2 else "the"
        )
        return f"deals {self.amount} damage to each of {n} targets"


# ---------------------------------------------------------------------------
# Keywords until end of turn
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LoseKeywordUEOT(Effect):
    """"Target creature loses <keyword> until end of turn." (Emerald
    Charm): a layer-6 ``lose_keyword`` entry, walked in timestamp order
    with keyword grants by ``game.effective_keywords``."""

    keyword: str
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
        slot = self.targets[0]
        prior = state.resolving_controller_id
        try:
            state.resolving_controller_id = controller_id
            ok = _slot_target_still_legal(state, slot, targets[0])
        finally:
            state.resolving_controller_id = prior
        if not ok:
            state.log.append(_fizzle_message(state, targets[0], action="effect"))
            return
        obj = next((o for o in state.battlefield if o.id == targets[0][1]), None)
        if obj is None:
            return
        src = state.resolving_source or state.resolving_spell
        state.add_continuous_effect(
            source_id=src.id if src is not None else -1,
            layer=6, kind="lose_keyword", target_id=obj.id,
            params=(self.keyword,), expires_at="cleanup",
            description=f"{obj.printing.name} loses {self.keyword} UEOT",
        )
        state.log.append(f"{obj.printing.name} loses {self.keyword}")

    def describe(self) -> str:
        return f"target creature loses {self.keyword} until end of turn"


@dataclass(frozen=True)
class GrantKeywordsToEachUEOT(Effect):
    """"<Permanents> you control gain <keywords> until end of turn."
    (Boros Charm: permanents gain indestructible): every matching
    permanent at resolution (the set is locked in, CR 611.2c) gets a
    layer-6 grant that expires at cleanup."""

    permanent_filter: ObjectPredicate
    keywords: frozenset = frozenset()
    label: str = "permanents you control"

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        prior = state.resolving_controller_id
        try:
            state.resolving_controller_id = controller_id
            matching = [
                o for o in state.battlefield
                if self.permanent_filter.test(o, state)
            ]
        finally:
            state.resolving_controller_id = prior
        src = state.resolving_source or state.resolving_spell
        for obj in matching:
            for kw in sorted(self.keywords):
                state.add_continuous_effect(
                    source_id=src.id if src is not None else -1,
                    layer=6, kind="grant_keyword", target_id=obj.id,
                    params=(kw,), expires_at="cleanup",
                    description=f"{obj.printing.name} gains {kw} UEOT",
                )
        state.log.append(
            f"{len(matching)} {self.label} gain "
            f"{', '.join(sorted(self.keywords))} until end of turn"
        )

    def describe(self) -> str:
        return (
            f"{self.label} gain {', '.join(sorted(self.keywords))} until "
            f"end of turn"
        )


# ---------------------------------------------------------------------------
# Tap / untap all
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TapAllMatching(Effect):
    """"Tap all <permanents>." (Cryptic Command's "Tap all creatures
    your opponents control."). Controller-relative filters are read
    against the resolving ability's controller."""

    permanent_filter: ObjectPredicate
    label: str = "permanents"

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import tap_permanent

        prior = state.resolving_controller_id
        try:
            state.resolving_controller_id = controller_id
            victims = [
                o for o in state.battlefield
                if not o.tapped and self.permanent_filter.test(o, state)
            ]
        finally:
            state.resolving_controller_id = prior
        for obj in victims:
            if obj in state.battlefield:
                tap_permanent(state, obj)
        state.log.append(f"tap all {self.label}: {len(victims)} tapped")

    def describe(self) -> str:
        return f"tap all {self.label}"


# ---------------------------------------------------------------------------
# Upkeep prison: "that player" acts once per counter on the source
# ---------------------------------------------------------------------------


def _event_player_id(state, targets) -> int | None:
    for kind, pid in targets:
        if kind == "player":
            return pid
    return None


@dataclass(frozen=True)
class EventPlayerActsPerSourceCounter(Effect):
    """"that player sacrifices a <permanent> of their choice for each
    <kind> counter on this <permanent>" (Smokestack) / "that player taps
    an untapped <permanent> they control for each <kind> counter on this
    <permanent>" (Tangle Wire).

    "That player" is the player of the triggering event (each player's
    upkeep): it is bound as the trigger goes on the stack
    (``targets_from_event``), so it is not a target. The count is the
    source's counters as the ability resolves (last-known information
    once the source is gone). The player picks every permanent first
    (``choose_sacrifice`` / ``choose_permanent_to_tap``, one per
    counter), then they are sacrificed / tapped together; with fewer
    candidates than counters, every candidate is used."""

    action: str  # "sacrifice" | "tap"
    kind: str
    permanent_filter: ObjectPredicate
    label: str = "permanent"

    def __post_init__(self) -> None:
        if self.action not in ("sacrifice", "tap"):
            raise ValueError(f"unknown action: {self.action!r}")

    def targets_from_event(self, state, subjects):
        player = subjects.get("player")
        if player is None:
            return None
        return (("player", player.id),)

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import counter_count

        pid = _event_player_id(state, targets)
        source = state.resolving_source
        if pid is None or source is None:
            return
        n = counter_count(source, self.kind)
        if n <= 0:
            return
        player = state.player_by_id(pid)
        prior = state.resolving_controller_id
        try:
            state.resolving_controller_id = pid
            options = [
                o for o in state.battlefield
                if o.controller_id == pid
                and not (self.action == "tap" and o.tapped)
                and self.permanent_filter.test(o, state)
            ]
        finally:
            state.resolving_controller_id = prior
        chosen = []
        while options and len(chosen) < n:
            pick = options[0]
            if player.agent is not None and len(options) > 1:
                ids = [o.id for o in options]
                if self.action == "tap":
                    pick_id = player.agent.choose_permanent_to_tap(state, pid, ids)
                else:
                    pick_id = player.agent.choose_sacrifice(state, pid, ids)
                pick = next((o for o in options if o.id == pick_id), options[0])
            options.remove(pick)
            chosen.append(pick)
        if self.action == "tap":
            from mtg_bot.turn import tap_permanent

            for obj in chosen:
                if obj in state.battlefield:
                    state.log.append(f"P{pid} taps {obj.printing.name}")
                    tap_permanent(state, obj)
        else:
            from mtg_bot.turn import sacrifice

            for obj in chosen:
                if obj in state.battlefield:
                    state.log.append(f"P{pid} sacrifices {obj.printing.name}")
                    sacrifice(state, obj)

    def describe(self) -> str:
        if self.action == "tap":
            return (
                f"that player taps an untapped {self.label} they control for "
                f"each {self.kind} counter on this permanent"
            )
        return (
            f"that player sacrifices a {self.label} of their choice for each "
            f"{self.kind} counter on this permanent"
        )


@dataclass(frozen=True)
class DestroySourceUnlessPay(Effect):
    """"destroy this creature unless you pay <cost>" (the ability The
    Tabernacle at Pendrell Vale grants every creature). "You" is the
    ability's controller -- the creature's controller; the payment is
    offered mid-resolution (``choose_yes_no`` when affordable). The
    creature may regenerate."""

    cost: str

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.cards.base import parse_mana_cost
        from mtg_bot.effects.generic.cheat_into_play import (
            pay_mana_during_resolution,
        )
        from mtg_bot.effects.generic.targeted_removal import destroy_permanent

        source = state.resolving_source
        if source is None or source not in state.battlefield:
            return
        if pay_mana_during_resolution(
            state, controller_id, parse_mana_cost(self.cost),
            f"Pay {self.cost} to keep {source.printing.name}?",
        ):
            state.log.append(
                f"P{controller_id} pays {self.cost} for {source.printing.name}"
            )
            return
        destroy_permanent(state, source)

    def describe(self) -> str:
        return f"destroy this creature unless you pay {self.cost}"


# ---------------------------------------------------------------------------
# Equipment
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PumpEquippedCreatureUEOT(Effect):
    """"Equipped creature gets +P/+T until end of turn." (Umezawa's
    Jitte's first mode): the creature the source Equipment is attached
    to as the ability resolves; nothing if it's unattached."""

    power_bonus: int = 0
    toughness_bonus: int = 0

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        source = state.resolving_source
        if source is None or source.attached_to is None:
            state.log.append("no equipped creature -- pump does nothing")
            return
        host = next(
            (o for o in state.battlefield if o.id == source.attached_to), None,
        )
        if host is None:
            return
        state.grant_pt_pump_ueot(
            source_id=source.id, target_id=host.id,
            power=self.power_bonus, toughness=self.toughness_bonus,
            description=(
                f"{source.printing.name}: equipped creature gets "
                f"{self.power_bonus:+d}/{self.toughness_bonus:+d} UEOT"
            ),
        )
        state.log.append(
            f"{host.printing.name} gets {self.power_bonus:+d}/"
            f"{self.toughness_bonus:+d} until end of turn"
        )

    def describe(self) -> str:
        return (
            f"equipped creature gets {self.power_bonus:+d}/"
            f"{self.toughness_bonus:+d} until end of turn"
        )


@dataclass(frozen=True)
class EventSubjectDealsDamageToEachOpponent(Effect):
    """"it deals N damage to each opponent" where "it" is the creature
    the triggering event is about (Hawkeye's Bow: "Whenever equipped
    creature becomes tapped, it deals 1 damage to each opponent." -- the
    equipped creature deals the damage, not the Equipment). The creature
    is bound as the trigger goes on the stack (``event_subject_id``)
    and found wherever it is at resolution (last-known information);
    "each opponent" is relative to the ability's controller."""

    amount: int = 1
    subject_slot: str = "obj"

    def event_subject_id(self, subjects) -> int:
        obj = subjects.get(self.subject_slot)
        return getattr(obj, "id", -1) if obj is not None else -1

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.effects.base import _apply_damage
        from mtg_bot.turn import _find_object_by_id

        creature = _find_object_by_id(state, state.resolving_event_subject_id)
        if creature is None:
            return
        prior = state.resolving_source
        state.resolving_source = creature
        try:
            for p in state.players:
                if p.id == controller_id or p.has_lost:
                    continue
                _apply_damage(state, ("player", p.id), self.amount)
        finally:
            state.resolving_source = prior

    def describe(self) -> str:
        return f"it deals {self.amount} damage to each opponent"


# ---------------------------------------------------------------------------
# Cost atoms (``ActivationCost.extra_costs``)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RemoveCountersFromAmongPermanentsCost:
    """"Remove N <kind> counters from among permanents you control"
    (The Filigree Sylex: ten oil counters). Payable while the
    activator's permanents carry at least N such counters in total;
    the activator picks a permanent for each counter removed (the
    ``choose_target`` hook over ``("permanent", id)`` options)."""

    kind: str
    count: int

    def _holders(self, state, player_id: int) -> list:
        from mtg_bot.game import counter_count

        return [
            o for o in state.battlefield
            if o.controller_id == player_id and counter_count(o, self.kind) > 0
        ]

    def payable(self, state, player_id: int, source) -> bool:
        from mtg_bot.game import counter_count

        return sum(
            counter_count(o, self.kind) for o in self._holders(state, player_id)
        ) >= self.count

    def pay(self, state, player_id: int, source) -> list:
        from mtg_bot.game import remove_counters

        agent = state.player_by_id(player_id).agent
        for _ in range(self.count):
            holders = self._holders(state, player_id)
            if not holders:
                break
            pick = holders[0]
            if agent is not None and len(holders) > 1:
                options = [("permanent", o.id) for o in holders]
                chosen = agent.choose_target(state, player_id, options)
                pick = next(
                    (o for o in holders if chosen == ("permanent", o.id)),
                    holders[0],
                )
            remove_counters(pick, self.kind, 1)
        state.log.append(
            f"P{player_id} removes {self.count} {self.kind} counter(s) from "
            f"among their permanents (cost)"
        )
        return []

    def describe(self) -> str:
        return (
            f"Remove {self.count} {self.kind} counters from among permanents "
            f"you control"
        )


__all__ = [
    "DamageEachPlayerPerControlled",
    "DealDamageToEachTarget",
    "GrantKeywordsToEachUEOT",
    "LoseKeywordUEOT",
    "DestroySourceUnlessPay",
    "EventPlayerActsPerSourceCounter",
    "EventSubjectDealsDamageToEachOpponent",
    "RemoveCountersFromAmongPermanentsCost",
    "HasManaValueEqualToSourceCounters",
    "IsLegendaryPermanent",
    "LacksSubtype",
    "PumpEquippedCreatureUEOT",
    "TapAllMatching",
]
