"""Effect combinators: Sequence, ModalChooseOne, conditional wrappers,
optional-sacrifice wrappers. Compose other Effects into bigger ones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from mtg_bot.effects.base import Effect, Target
from mtg_bot.effects.generic import SearchLibraryForBasicLandTapped

if TYPE_CHECKING:
    from mtg_bot.cards import ManaCost
    from mtg_bot.game import GameState


@dataclass(frozen=True)
class SacrificeSelfUnlessVoidActive(Effect):
    """End-step effect: "Sacrifice this unless Void is active." Reads
    state.resolving_source to find the sacrificing permanent. Matches
    Chorale of the Void's upkeep sustain.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import is_void_active
        from mtg_bot.turn import sacrifice as _sacrifice

        source = state.resolving_source
        if source is None:
            return
        if is_void_active(state):
            state.log.append(
                f"{source.printing.name}: Void active, no sacrifice"
            )
            return
        state.log.append(
            f"{source.printing.name} sacrificed (Void not active)"
        )
        _sacrifice(state, source)

    def describe(self) -> str:
        return "sacrifice this unless Void is active"



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



