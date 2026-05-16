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
class GainLife(Effect):
    amount: int

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import gain_life

        gain_life(state, controller_id, self.amount)
        p = state.player_by_id(controller_id)
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
class EachOpponentLosesLifeEqualToArtifactCount(Effect):
    """Each opponent loses life equal to the number of artifacts you
    control.

    BLOCKED-RUST-EFFECT slice (round 44) -- sister of the round-26
    static ``EachOpponentLosesLife`` (same recipient set + apply step:
    each opponent of the source-controller, direct life subtraction
    CR 118.4 not damage), with a NEW dynamic-X denominator (count of
    permanents the controller controls whose ``printing.is_artifact`` is
    True, in place of the static ``amount`` field). FIFTH apply
    substrate to pick up the X-from-count plumbing established by
    round-32's ``DealDamageToOpponentCreatureByArtifactCount`` (damage),
    round-33's ``PutPlusOneCountersOnSelfPerOtherCreatureOrArtifact``
    (counters), round-34's ``SurveilXEqualToArtifactCount`` (surveil),
    and round-42's ``MillTargetPlayerEqualToYourLifeTotal`` (mill --
    different denominator). Walks the apply-substrate axis to a fifth
    entry, confirming the round-35 bidirectionally-extensible
    X-from-count plumbing generalizes across both axes.

    Lands that are also artifacts count, tokens like Lander count.
    Dual-typed artifact-creatures count toward BOTH the artifact-count
    and any creatures-controlled denominators independently (mirrors
    Scryfall typeline conventions; the ``is_artifact`` printing
    property is an independent disjunction over ``card_types``).

    The source itself counts toward the denominator if it is an
    Artifact still on the source-controller's bf at resolve time
    (vanilla walk over ``state.battlefield`` -- no source-exclusion
    clause, mirrors round-32 / round-34 sister convention).

    Zero-artifact = silent no-op (no per-opponent loop entered);
    matches Python's ``if artifact_count <= 0: return`` short-circuit
    convention used by the round-32/35/36/37 sister damage classes.

    No EoE consumers today -- ships per round-27/31/37 round-trip-
    surface-coverage rule. The Python class lands in this slice as the
    bridge translator's other side; the dynamic-X is the whole point of
    the class so there are no constructor args (mirrors the round-32
    artifact-count damage class' unit-shape convention).
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        artifact_count = sum(
            1 for o in state.battlefield
            if o.controller_id == controller_id and o.printing.is_artifact
        )
        if artifact_count <= 0:
            return
        for p in state.players:
            if p.id == controller_id or p.has_lost:
                continue
            p.life -= artifact_count
            state.log.append(
                f"P{p.id} loses {artifact_count} life "
                f"(life: {p.life}; X = artifacts you control)"
            )

    def describe(self) -> str:
        return (
            "each opponent loses life equal to the number of artifacts "
            "you control"
        )



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
        from mtg_bot.game import gain_life
        gain_life(state, controller_id, self.amount)
        you = state.player_by_id(controller_id)
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
class TargetOpponentLosesLife(Effect):
    """Target opponent loses ``amount`` life.

    Matches oracle text like "Target opponent loses 3 life" — the second
    activated ability on Dubious Delicacy ({2}, {T}, Sacrifice this
    artifact: Target opponent loses 3 life). The legality pool is
    explicitly opponents-only, so the controller can never target
    themselves.
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
        state.log.append(
            f"P{pid} loses {self.amount} life (now {opp.life})"
        )

    def describe(self) -> str:
        return f"target opponent loses {self.amount} life"



@dataclass(frozen=True)
class DefendingPlayerLosesHalfLifeRoundedUp(Effect):
    """Defending player loses half their life, rounded up. Matches
    Alpharael, Stonechosen's Void attack trigger. Simplified to "each
    opponent" — correct in 2-player, approximation in multiplayer.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        for p in state.players:
            if p.id == controller_id or p.has_lost:
                continue
            loss = (p.life + 1) // 2  # ceil(life / 2)
            p.life -= loss
            state.log.append(
                f"P{p.id} loses {loss} life (half, rounded up) — "
                f"life: {p.life}"
            )

    def describe(self) -> str:
        return "defending player loses half their life, rounded up"



@dataclass(frozen=True)
class GrantLifeToEachOpponent(Effect):
    """Grove of the Burnwillows' "Each opponent gains 1 life" clause
    (runs alongside the mana add via Sequence).
    """

    amount: int = 1

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import gain_life

        for p in state.players:
            if p.id == controller_id or p.has_lost:
                continue
            gain_life(state, p.id, self.amount)
            state.log.append(
                f"P{p.id} gains {self.amount} life (Grove) — life: {p.life}"
            )

    def describe(self) -> str:
        return f"each opponent gains {self.amount} life"
