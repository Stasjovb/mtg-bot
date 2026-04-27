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
class SacrificeSelfUnlessTapPermanent(Effect):
    """ETB rider: "sacrifice this unless you tap an untapped permanent
    you control." Reads ``state.resolving_source`` for the source
    permanent (typically a land like Command Bridge).

    Resolution:
      - Build the set of legal "alternative cost" picks: untapped
        permanents the controller controls, EXCLUDING the source itself.
      - If the set is empty, the source is sacrificed (no choice).
      - Otherwise the controller's agent picks one via
        ``choose_target`` with kind ``"untapped_permanent"``. Returning
        None (or no agent) declines and the source is sacrificed; any
        valid pick taps that permanent and the source stays.

    Note: the source might already be tapped (Command Bridge enters
    tapped before its ETB resolves) — the source is excluded from the
    pickable set regardless.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.turn import sacrifice as _sacrifice, tap_permanent

        source = state.resolving_source
        if source is None:
            return
        candidates = [
            o for o in state.battlefield
            if o.controller_id == controller_id
            and not o.tapped
            and o.id != source.id
        ]
        if not candidates:
            state.log.append(
                f"{source.printing.name}: no untapped permanent to "
                f"tap — sacrificed"
            )
            _sacrifice(state, source)
            return
        legal = [("untapped_permanent", o.id) for o in candidates]
        p = state.player_by_id(controller_id)
        chosen = None
        if p.agent is not None:
            chosen = p.agent.choose_target(state, controller_id, legal)
        if chosen is None or chosen[0] != "untapped_permanent":
            state.log.append(
                f"{source.printing.name}: declined to tap a permanent "
                f"— sacrificed"
            )
            _sacrifice(state, source)
            return
        target = next(
            (o for o in candidates if o.id == chosen[1]), None
        )
        if target is None:
            state.log.append(
                f"{source.printing.name}: chosen permanent missing "
                f"— sacrificed"
            )
            _sacrifice(state, source)
            return
        state.log.append(
            f"P{controller_id} taps {target.printing.name} to keep "
            f"{source.printing.name}"
        )
        tap_permanent(state, target)

    def describe(self) -> str:
        return (
            "sacrifice this unless you tap an untapped permanent you control"
        )



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
class OptionalPutLandFromHandOntoBattlefield(Effect):
    """"You may put a land card from your hand onto the battlefield."

    Matches Burgeoning's trigger effect. The land enters untapped
    (Burgeoning doesn't say "tapped") and fires landfall triggers via
    ``fire_landfall_triggers`` — "enters the battlefield" isn't the
    same event as "plays a land" so Burgeoning-put lands don't re-fire
    opponent-plays-land chains. Declining is legal.
    """

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone
        from mtg_bot.turn import fire_landfall_triggers

        p = state.player_by_id(controller_id)
        options = [c for c in p.hand if c.printing.is_land]
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
        card.zone = Zone.BATTLEFIELD
        card.controller_id = controller_id
        card.tapped = bool(card.printing.enters_tapped)
        state.battlefield.append(card)
        state.log.append(
            f"P{controller_id} puts {card.printing.name} from hand "
            f"onto the battlefield"
        )
        # ``fire_landfall_triggers`` walks the legacy string-key
        # ``"landfall"`` abilities AND dispatches the predicate-style
        # ENTERS event, so every migrated landfall ability fires.
        fire_landfall_triggers(state, card)

    def describe(self) -> str:
        return "you may put a land card from your hand onto the battlefield"



@dataclass(frozen=True)
class OptionalSacArtifactForEffect(Effect):
    """"You may sacrifice an artifact. If you do, [inner_effect]."

    Similar to OptionalSacAnotherForEffect but doesn't require a
    ``state.resolving_source`` for self-exclusion — the "another"
    clause isn't in the oracle text (Lithobraking: "you may sacrifice
    an artifact"). The "may" is honored via ``Agent.choose_yes_no``;
    default base-Agent behavior is "True" so existing cards that relied
    on "may → always yes" are unaffected. Once the controller agrees
    to sacrifice, ``choose_sacrifice`` picks WHICH artifact.
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
        if p.agent is not None and not p.agent.choose_yes_no(
            state, controller_id,
            "Sacrifice an artifact for the rider?",
        ):
            state.log.append(
                f"P{controller_id} declines optional artifact sacrifice"
            )
            return
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
class OptionalDiscardCardThenDrawN(Effect):
    """"You may discard a card. If you do, draw ``amount`` cards."

    Matches Melded Moxite's printed ETB rider. Distinct from
    ``DiscardHandThenDrawN`` (Vaultguard Trooper) in two ways:

    1. The discard is singular ("a card"), not the entire hand.
    2. "If you do" is gated on whether a card was actually discarded,
       so an empty hand makes the rider fizzle entirely — even an
       agent that says yes can't satisfy "if you do" with no card to
       toss.

    The "may" is exposed via ``Agent.choose_yes_no``; the default base
    Agent returns True (matching the codebase's "may → always yes"
    convention). Once yes, ``DiscardSelf(amount=1)`` picks WHICH card
    via ``choose_discard``; if the hand is empty the discard is a
    no-op and the dependent draw is skipped.
    """

    amount: int = 2

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.effects.generic import DiscardSelf, DrawCards

        p = state.player_by_id(controller_id)
        if p.agent is not None and not p.agent.choose_yes_no(
            state, controller_id,
            f"Discard a card to draw {self.amount}?",
        ):
            state.log.append(
                f"P{controller_id} declines optional discard "
                f"(OptionalDiscardCardThenDrawN)"
            )
            return
        if not p.hand:
            state.log.append(
                f"P{controller_id} has empty hand; can't discard, "
                f"draw skipped"
            )
            return
        before = len(p.graveyard)
        DiscardSelf(amount=1).resolve(state, controller_id, ())
        if len(p.graveyard) == before:
            # Defensive: discard didn't fire (shouldn't happen with a
            # non-empty hand, but matches "if you do" semantics).
            return
        DrawCards(amount=self.amount).resolve(state, controller_id, ())

    def describe(self) -> str:
        return (
            f"you may discard a card; if you do, draw {self.amount} cards"
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
        from mtg_bot.game import effective_subtypes
        from mtg_bot.turn import sacrifice as _sacrifice

        options = [
            o for o in state.battlefield
            if o.controller_id == controller_id
            and (
                o.printing.is_land
                or "Lander" in effective_subtypes(state, o)
            )
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
class ConditionalIfYouControlAtLeast(Effect):
    """Run ``inner`` only if the effect's controller controls at least
    ``threshold`` permanents matching ``predicate`` at resolution.

    Predicates:
      - ``"artifact"`` — any permanent with the Artifact type.
      - ``"creature"`` — any permanent that counts as a creature now
        (printed creature + stationed Spacecraft + animated manland).
      - ``"land"`` — any permanent with the Land type.

    Matches "At the beginning of your upkeep, if you control three or
    more artifacts, ..." (Inventors' Fair) and kin.
    """

    threshold: int
    predicate: str
    inner: Effect

    def requires_target(self) -> bool:
        return self.inner.requires_target()

    def target_count_range(self) -> tuple[int, int]:
        return self.inner.target_count_range()

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return self.inner.legal_targets(state, controller_id)

    def _count(self, state: "GameState", controller_id: int) -> int:
        from mtg_bot.game import is_creature_now

        if self.predicate == "artifact":
            return sum(
                1 for o in state.battlefield
                if o.controller_id == controller_id
                and o.printing.is_artifact
            )
        if self.predicate == "creature":
            return sum(
                1 for o in state.battlefield
                if o.controller_id == controller_id and is_creature_now(o)
            )
        if self.predicate == "land":
            return sum(
                1 for o in state.battlefield
                if o.controller_id == controller_id and o.printing.is_land
            )
        return 0

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if self._count(state, controller_id) < self.threshold:
            state.log.append(
                f"conditional skipped (you control fewer than "
                f"{self.threshold} {self.predicate}s)"
            )
            return
        self.inner.resolve(state, controller_id, targets)

    def describe(self) -> str:
        return (
            f"if you control {self.threshold} or more {self.predicate}s, "
            f"{self.inner.describe()}"
        )



@dataclass(frozen=True)
class ConditionalIfYouGainedLifeAtLeast(Effect):
    """Run ``inner`` only if the effect's controller has gained at least
    ``threshold`` life this turn at resolution.

    Matches "draw a card if you've gained 3 or more life this turn"
    end-step riders (Haliya, Guided by Light).
    """

    threshold: int
    inner: Effect

    def requires_target(self) -> bool:
        return self.inner.requires_target()

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        return self.inner.legal_targets(state, controller_id)

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        gained = state.player_by_id(controller_id).life_gained_this_turn
        if gained < self.threshold:
            state.log.append(
                f"conditional skipped (gained {gained} life, need "
                f"{self.threshold})"
            )
            return
        self.inner.resolve(state, controller_id, targets)

    def describe(self) -> str:
        return (
            f"if you've gained {self.threshold} or more life this turn, "
            f"{self.inner.describe()}"
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

    With ``or_both=True``, oracle text reads "Choose one or both" — the
    controller may pick either mode alone or both modes. The agent is
    asked via ``choose_modes`` (plural) for the ordered list of modes to
    resolve; modes resolve in that order (per CR 700.2d, "the controller
    of a modal spell or ability chooses the order in which the modes are
    resolved").

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
    or_both: bool = False

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
        if self.or_both:
            # "Choose one or both": at most one target per targeted
            # mode (we don't model multi-target sub-modes). When every
            # mode is targeted, picking both modes needs one target
            # apiece — max_t equals the count of targeted modes. min_t
            # is 0 when any mode is untargeted (you can pick only that
            # mode); 1 when every mode is targeted (you must resolve
            # at least one mode and that mode needs a target).
            targeted_count = sum(
                1 for m in self.modes if m.requires_target()
            )
            return (1 if all_targeted else 0, targeted_count)
        # min_t=0 for mixed modes (you might pick the untargeted mode);
        # min_t=min-of-targeted-modes when every mode needs a target.
        # max_t=max across modes — supports multi-target modes (e.g.
        # Archenemy's Charm mode 1 returns up to 2 cards).
        # Defensive: not every mode-like object subclasses Effect (some
        # tests pass minimal stubs), so fall back to the base default
        # (1, 1) when target_count_range isn't implemented.
        def _range(m):
            tcr = getattr(m, "target_count_range", None)
            return tcr() if callable(tcr) else (1, 1)
        targeted_ranges = [
            _range(m) for m in self.modes if m.requires_target()
        ]
        max_t = max(r[1] for r in targeted_ranges)
        if not all_targeted:
            return (0, max_t)
        min_t = min(r[0] for r in targeted_ranges)
        return (min_t, max_t)

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
        # CR 601.2e: modes are picked at cast time, replayed via
        # state.resolving_modes during resolution. Fallback to a
        # resolve-time agent prompt only when this effect is being
        # used as a sub-effect outside the spell-cast pipeline (e.g.
        # nested inside a triggered-ability effect that didn't carry
        # cast-time mode picks).
        cast_modes = state.resolving_modes
        if self.or_both:
            self._resolve_or_both(
                state, controller_id, targets, p, cast_modes,
            )
            return
        if cast_modes:
            idx = cast_modes[0]
            idx = max(0, min(idx, len(self.modes) - 1))
        elif p.agent is None:
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
        # If the chosen mode requires a target, filter the passed targets
        # down to those legal for THIS mode (the cast pipeline may have
        # collected targets across the union of all modes' pools). Fizzle
        # silently if none survive.
        if chosen.requires_target():
            legal = chosen.legal_targets(state, controller_id)
            filtered = tuple(t for t in targets if t in legal)
            if not filtered:
                state.log.append(
                    "modal fizzle: chosen mode requires a legal target"
                )
                return
            chosen.resolve(state, controller_id, filtered)
            return
        chosen.resolve(state, controller_id, targets)

    def _resolve_or_both(
        self,
        state: "GameState",
        controller_id: int,
        targets: tuple[Target, ...],
        p,
        cast_modes: tuple[int, ...] = (),
    ) -> None:
        """Resolve a "Choose one or both" modal effect. Asks the agent
        for an ordered list of mode indices via ``choose_modes`` (plural)
        and resolves each in turn, dispatching legal targets per mode.

        ``cast_modes`` is the cast-time pick (CR 601.2e); when present
        we replay it instead of prompting again at resolve time.

        Target dispatch: for each chosen mode that requires a target,
        we consume the first remaining target whose value appears in
        that mode's ``legal_targets``. A mode that requires a target but
        has no legal target available silently fizzles (logged), matching
        the single-mode fizzle path.
        """
        if cast_modes:
            order = list(cast_modes)
        elif p.agent is None:
            order = [0]
        else:
            order = p.agent.choose_modes(
                state, controller_id, [m.describe() for m in self.modes]
            )
        # Sanitise: keep unique, in-range indices preserving order.
        seen: set[int] = set()
        clean: list[int] = []
        for idx in order:
            if 0 <= idx < len(self.modes) and idx not in seen:
                clean.append(idx)
                seen.add(idx)
        if not clean:
            # Empty / all-invalid pick → default to mode 0 so the spell
            # still does something (matches the agent-absent default).
            clean = [0]
        state.log.append(
            f"modal: P{controller_id} chooses mode(s) "
            f"{clean} ({', '.join(self.modes[i].describe() for i in clean)})"
        )
        remaining = list(targets)
        for idx in clean:
            mode = self.modes[idx]
            if mode.requires_target():
                legal = mode.legal_targets(state, controller_id)
                picked = None
                for t in remaining:
                    if t in legal:
                        picked = t
                        break
                if picked is None:
                    state.log.append(
                        f"modal fizzle: mode {idx} requires a legal target"
                    )
                    continue
                remaining.remove(picked)
                mode.resolve(state, controller_id, (picked,))
            else:
                mode.resolve(state, controller_id, ())

    def describe(self) -> str:
        joiner = " AND/OR " if self.or_both else " OR "
        return joiner.join(m.describe() for m in self.modes)



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



@dataclass(frozen=True)
class OptionalManaCostThenEffect(Effect):
    """"You may pay {cost}. If you do, [inner_effect]."

    Wraps an inner Effect with an optional mana-cost gate. Following the
    OptionalSac/Kavaron Harrier precedent in this codebase, the "may"
    is treated as YES whenever the controller can afford ``cost_str``;
    otherwise the trigger does nothing.

    Used for triggers like Oreplate Pangolin's "Whenever another artifact
    you control enters, you may pay {1}. If you do, put a +1/+1 counter
    on this creature."
    """

    cost_str: str
    inner_effect: Effect

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.actions import auto_tap_for_cost, can_pay_cost
        from mtg_bot.cards import parse_mana_cost

        cost = parse_mana_cost(self.cost_str)
        if not can_pay_cost(state, controller_id, cost):
            source = state.resolving_source
            name = source.printing.name if source is not None else "ability"
            state.log.append(
                f"{name}: P{controller_id} can't pay {self.cost_str}; "
                f"trigger does nothing"
            )
            return
        auto_tap_for_cost(state, controller_id, cost)
        self.inner_effect.resolve(state, controller_id, targets)

    def describe(self) -> str:
        return (
            f"you may pay {self.cost_str}; if you do, "
            f"{self.inner_effect.describe()}"
        )



