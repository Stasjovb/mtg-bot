"""Core effect infrastructure — base Effect class, Target alias,
ability dataclasses (ActivationCost / ActivatedAbility / StaticAbility /
TriggeredAbility), and shared private helpers used across effect modules.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mtg_bot.cards import CostReduction, ManaCost
    from mtg_bot.effects.conditions import Condition
    from mtg_bot.effects.modifiers import (
        ContinuousModifier, ReplacementEffect,
    )
    from mtg_bot.effects.targets import TargetSlot
    from mtg_bot.game import GameState


Target = tuple[str, int]



class Effect:
    """Base class for ability effects.

    Untargeted effects override ``resolve``; targeted effects come in
    two flavours during the PR #3 → PR #4 phased migration:

    1. **New-shape effects** carry a non-empty
       ``targets: tuple[TargetSlot, ...]`` field describing each
       target slot via the
       :mod:`mtg_bot.effects.targets` grammar (``TargetSpec`` /
       ``SlotRef``). The default ``requires_target()`` /
       ``legal_targets()`` / ``target_count_range()`` implementations
       below consult ``self.targets`` to answer the targeting
       pipeline's questions.
    2. **Old-shape effects** (destroy / exile / tap / pump / +1+1 /
       return-to-hand / …) leave ``targets`` at its empty default
       and override ``requires_target()`` / ``legal_targets()``
       directly. Those overrides keep working unchanged because
       ``targets`` is empty — the default impls below short-circuit
       to "no target" and the per-class overrides take precedence.
       PR #4 migrates those families to the new shape.

    ``resolve`` receives a tuple of chosen targets (empty for
    untargeted effects). New-shape effects iterate the chosen targets
    in slot order; back-reference ``SlotRef`` slots are NOT in the
    targets tuple — the resolve path looks the parent slot's resolved
    target back up in-place.
    """

    # Per-effect target list. Empty for old-shape effects whose
    # targeting machinery lives on per-class ``requires_target`` /
    # ``legal_targets`` overrides; non-empty for new-shape effects
    # whose targeting is driven structurally through this field.
    # Class-level default — subclasses opt in by setting their own
    # ``targets`` field (typically as a frozen-dataclass field).
    targets: "tuple[TargetSlot, ...]" = ()

    def requires_target(self) -> bool:
        """Whether this effect needs at least one chosen target to resolve.

        Default: True iff any ``TargetSpec`` in ``self.targets`` has a
        ``count_min >= 1``. ``SlotRef`` slots don't count toward
        target-required because they're back-references, not fresh
        prompts. Old-shape effects override this directly and the
        default never fires for them (their ``targets`` is empty).
        """
        from mtg_bot.effects.targets import TargetSpec
        for slot in self.targets:
            if isinstance(slot, TargetSpec) and slot.count_min >= 1:
                return True
        return False

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        """Enumerate legal targets for the FIRST ``TargetSpec`` slot.

        Default behaviour: walks the battlefield + players for objects
        satisfying the slot's ``filter``, returning each as the
        engine's ``("creature"|"player"|"permanent", id)`` tuple form.
        Old-shape effects override this and the default never fires;
        new-shape effects with multiple ``TargetSpec`` slots use
        ``legal_targets_for_slot`` (below).

        Empty list means no targets are needed.
        """
        if not self.targets:
            return []
        from mtg_bot.effects.targets import TargetSpec
        # Find the first TargetSpec slot — any leading ``SlotRef`` is
        # nonsense (no slot to back-reference) but defensively skip.
        for slot in self.targets:
            if isinstance(slot, TargetSpec):
                return self._enumerate_for_filter(state, controller_id, slot.filter)
        return []

    @staticmethod
    def _enumerate_for_filter(
        state: "GameState", controller_id: int, target_filter
    ) -> list[Target]:
        """Walk battlefield + players, returning legal targets for
        ``target_filter``. Pure helper — used by both
        :meth:`legal_targets` and per-slot enumeration in multi-slot
        new-shape effects.

        Pins ``state.resolving_controller_id`` to ``controller_id``
        for the duration of the walk so controller-aware atoms
        (``ControlledByOpponent`` / ``ControlledByYou``) can resolve
        "you" / "an opponent" without the predicate test signature
        having to grow. Restores the prior value on exit so nested
        enumerations don't see a stale id.
        """
        from mtg_bot.game import is_creature_now

        prior_controller = getattr(state, "resolving_controller_id", None)
        try:
            state.resolving_controller_id = controller_id
            results: list[Target] = []
            for o in state.battlefield:
                if not target_filter.test(o, state):
                    continue
                # Pick the engine "kind" tag for the object. Creatures
                # use the legal-now check (``is_creature_now``) so
                # impending-suppressed Overlords aren't valid creature
                # targets even if their printed type carries Creature.
                if is_creature_now(o):
                    results.append(("creature", o.id))
                elif "Planeswalker" in o.printing.card_types:
                    results.append(("planeswalker", o.id))
                elif "Battle" in o.printing.card_types:
                    results.append(("battle", o.id))
                else:
                    results.append(("permanent", o.id))
            # Players are not on the battlefield list — walk them
            # separately so an "any target" filter (which accepts
            # IsPlayer) picks them up. Filters that don't admit
            # players (``IsCreature`` etc.) reject every player via
            # their own ``test`` and the loop is a cheap no-op.
            for p in state.players:
                if p.has_lost:
                    continue
                if target_filter.test(p, state):
                    results.append(("player", p.id))
            return results
        finally:
            state.resolving_controller_id = prior_controller

    def target_count_range(self) -> tuple[int, int]:
        """Return (min, max) number of TARGETS (not slots).

        Default for new-shape effects: sums ``count_min`` and
        ``count_max`` across every ``TargetSpec`` in ``self.targets``;
        ``SlotRef`` slots contribute zero. Old-shape effects override
        this and the default never fires.

        For backward-compat with old-shape effects whose
        ``requires_target()`` returns True without overriding this:
        returns ``(1, 1)`` so the "old default" stays correct.
        """
        from mtg_bot.effects.targets import TargetSpec
        if not self.targets:
            return (1, 1) if self.requires_target() else (0, 0)
        total_min = 0
        total_max: float = 0
        for slot in self.targets:
            if isinstance(slot, TargetSpec):
                total_min += slot.count_min
                if slot.count_max == math.inf:
                    total_max = math.inf
                elif total_max != math.inf:
                    total_max += slot.count_max
        # Cap to int when finite (callers expect ints for the legacy
        # one-spec common case); leave math.inf intact for the "any
        # number of target X" form.
        if total_max == math.inf:
            return (total_min, total_max)  # type: ignore[return-value]
        return (total_min, int(total_max))

    def target_slot_kinds(self) -> tuple[str, ...]:
        """Per-slot required target kinds, for effects with multiple
        distinct-kind slots (e.g., Diplomatic Relations targets BOTH
        a friendly creature ``"my_creature"`` AND an opponent's
        creature ``"creature"``). Returning a non-empty tuple opts in
        to per-slot kind enforcement: the targeting pipeline filters
        the legal-targets pool to only entries of the matching kind
        when picking each slot, preventing illegal-kind picks (e.g.,
        a friendly creature being chosen for an opp-creature slot).

        Empty tuple (default) keeps the legacy flat-kind behavior:
        all entries in ``legal_targets`` are picked from a shared
        pool, regardless of kind. Used by single-target effects and
        flexible effects whose only kind is implicit.

        When non-empty, the tuple length should equal
        ``target_count_range()[1]`` (max).
        """
        return ()

    def resolve(
        self, state: "GameState", controller_id: int, targets: tuple[Target, ...] = ()
    ) -> None:
        raise NotImplementedError

    def describe(self) -> str:
        raise NotImplementedError



# Type alias for an ordered run of effects executed back-to-back. Slot
# indices in ``TargetSpec.distinct_from`` and ``SlotRef.idx`` are 0-
# based across the EffectSequence, NOT across the larger card. A modal
# wrapper resets the scope for each mode.
EffectSequence = tuple[Effect, ...]


@dataclass(frozen=True)
class ModalEffect(Effect):
    """A modal wrapper around several alternative effect sequences.

    Models "Choose one — / Choose two —" / "Choose any number —"
    cards. ``pick`` is the printed number of modes the caster
    chooses (``1`` for "Choose one"; ``2`` for "Choose two"; etc.).
    ``modes`` is a tuple of :data:`EffectSequence` — each mode is its
    own sequence, with its own slot scope.

    ``repeats_allowed=True`` models the "the same mode may be chosen
    more than once" rider on Charm-style cards; default False matches
    "different modes" semantics.

    Out of scope this PR: actual mode-selection plumbing in the
    targeting pipeline. This dataclass exists so the architectural
    grammar is complete (PR #3 design table covers modal in the
    layered types) — there are no engine consumers in this PR.
    """

    pick: int = 1
    modes: tuple[EffectSequence, ...] = ()
    repeats_allowed: bool = False

    def describe(self) -> str:
        # Coarse human-readable summary; the full mode text lives on
        # each sub-effect. ``pick`` of 1 reads as "Choose one"; 2 as
        # "Choose two"; etc.
        words = {1: "one", 2: "two", 3: "three"}
        n = words.get(self.pick, str(self.pick))
        joined = " | ".join(
            "; ".join(eff.describe() for eff in seq)
            for seq in self.modes
        )
        return f"Choose {n} — {joined}"



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



def _apply_damage(state: "GameState", target: Target, amount: int) -> None:
    """Apply ``amount`` damage to ``target``. Used by damage effects.

    Stage-3 scope: no source-tracking (so deathtouch on a pinger wouldn't
    mark its target lethal yet — that'd layer in when we thread damage
    sources through the ETB / ability pipeline).

    For damage to a creature, also fires
    ``enchanted_creature_dealt_damage`` triggers on attached auras
    (Cryoshatter, Pain for All) — mirrors the combat-damage path in
    ``combat.py``. The aura's TriggeredAbility effects resolve
    immediately, with the aura set as ``state.resolving_source`` and the
    damage amount in ``state.resolving_combat_damage_amount``.
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
            obj.damaged_this_turn = True
            state.log.append(f"{obj.printing.name} takes {amount} damage")
            # Lazy-imported to avoid an effects <-> combat import cycle.
            from mtg_bot.combat import _fire_enchanted_dealt_damage_triggers

            _fire_enchanted_dealt_damage_triggers(state, obj, amount)



def _find_moonlit_replacement_source(
    state: "GameState", controller_id: int,
):
    """Return an attached aura with replaces_first_tokens_with_copies
    controlled by ``controller_id`` whose enchanted permanent is also
    under the controller's control, or None.
    """
    for o in state.battlefield:
        if o.controller_id != controller_id:
            continue
        if not o.printing.replaces_first_tokens_with_copies:
            continue
        if o.attached_to is None:
            continue
        return o
    return None



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
    # "Exile [the source permanent]" — Plaza of Heroes's fourth ability.
    # The source is exiled as a cost, not sacrificed, so it goes to the
    # exile zone rather than the graveyard. Paid last (same ordering as
    # sacrifice_self) so target selection and other cost payments can
    # still read the source from the battlefield.
    exile_self: bool = False
    # "Tap an untapped permanent you control" — Gene Pollinator's mana
    # ability. The activating player picks any other untapped permanent
    # they control (not the source) and taps it as a cost.
    tap_permanent_you_control: bool = False
    # "Exile an artifact card from your graveyard" — Rust Harvester's
    # activated ability. The activating player exiles one artifact card
    # from their graveyard as a cost. Legal only when the graveyard
    # contains at least one artifact card.
    exile_artifact_from_graveyard: bool = False
    # "Sacrifice another creature or artifact" — the caster picks a
    # legal target via choose_sacrifice. Cannot be the source itself.
    sacrifice_another_creature_or_artifact: bool = False
    # "Sacrifice another artifact or land" — as above but with a land
    # filter. Matches Slagdrill Scrapper.
    sacrifice_another_artifact_or_land: bool = False
    # "Sacrifice another artifact" — strict artifact-only filter.
    # Matches Memorial Vault. Cannot be the source itself.
    sacrifice_another_artifact: bool = False
    # "Remove a +1/+1 counter from a creature you control" — Sunstar
    # Chaplain's activated ability. Fails if no such creature exists.
    remove_plus_one_counter_from_your_creature: bool = False
    # "Sacrifice a Food" — Ragost, Deft Gastronaut's activated. Any
    # permanent with the Food subtype (including those granted Food
    # by Ragost's own static) is a legal sacrifice. Can sac the
    # source itself if the source has Food — but Ragost the Lobster
    # isn't an artifact so he's not a Food.
    sacrifice_food: bool = False
    # "Exile [the granting equipment]" — The Dominion Bracelet. When
    # True, the cost includes exiling the equipment attached to the
    # ability's source that granted this ability.
    exile_granting_equipment: bool = False
    # "This ability costs {X} less to activate, where X is this
    # creature's power." The Dominion Bracelet. Reduces the ability's
    # mana cost generic portion by the source's effective power at
    # activation time.
    mana_reduced_by_source_power: bool = False
    # Pay N life. Mana Confluence's "{T}, Pay 1 life: Add one mana
    # of any color." Paid at activation; gated by current life total.
    pay_life: int = 0
    # "Sacrifice a land" — Dust Bowl. Any land the controller controls
    # (excluding the source) is a legal sac.
    sacrifice_a_land: bool = False
    # "Sacrifice a Desert" — Scavenger Grounds. Subtype-filtered sac;
    # the source itself is eligible if it's a Desert.
    sacrifice_a_desert: bool = False
    # "Activate only if you control a creature with power 4 or
    # greater." Bonders' Enclave. Legal-actions gate only.
    requires_own_creature_power_at_least: int = 0
    # "Activate only if you control three or more artifacts."
    # Inventors' Fair's tutor activation. Legal-actions gate only:
    # the activation is removed from legal moves when the activator
    # controls fewer than N artifacts.
    requires_own_artifact_count_at_least: int = 0
    # "Activate only if you control a <T1> or a <T2>." Duskmourn Verge
    # cycle (Blazemire Verge, Floodfarm Verge, …). The tuple holds the
    # land-subtype names (e.g. ``("Plains", "Island")``); legal-actions
    # checks at least one of those subtypes appears on a permanent the
    # activator controls. Empty tuple disables the gate. Order does not
    # matter; matching is OR'd across the tuple.
    requires_control_of_subtype: tuple[str, ...] = ()
    # "Tap X untapped artifacts you control" — Secluded Starforge's
    # second ability. X is the number of untapped artifacts the
    # activating player CHOOSES to tap as part of the cost (X may be 0,
    # in which case the +X/+0 pump is a no-op). Bounded by the count of
    # untapped artifacts the player controls. The chosen X is threaded
    # onto the StackItem's ``x_value`` (the same channel ``{X}`` mana
    # costs use) so the resolving ``power_bonus_from_x`` pump reads it
    # via ``state.resolving_x_value``. The activating player picks the
    # count via the existing ``choose_x`` agent hook; the engine taps
    # the lowest-id-first X untapped artifacts deterministically.
    tap_x_untapped_artifacts_you_control: bool = False
    # **Planeswalker loyalty cost (CR 606).** Signed loyalty cost.
    # Positive values are PAY costs (the walker LOSES N loyalty
    # counters); negative values are ADD costs (the walker GAINS |N|
    # loyalty counters). Defaults to 0 (no loyalty cost). Convention:
    # a printed "+2" ability stamps ``loyalty=-2``; a printed "-3"
    # ability stamps ``loyalty=3``; a printed "0" ability stamps
    # ``loyalty=0``. This mirrors Rust's ``ActivationCost.loyalty: i32``
    # (cards.rs) sign convention exactly.
    #
    # Emission (``legal.py``): positive ``loyalty`` gates on the
    # source's ``loyalty_counters`` — the walker needs at least
    # ``cost.loyalty`` counters to afford. Negative / zero are always
    # affordable. Plus the once-per-turn-per-walker gate (CR 606.3,
    # via ``state.loyalty_activated_this_turn``).
    #
    # Apply (``actions._activate_ability``): ``obj.loyalty_counters -=
    # cost.loyalty`` (signed subtraction handles both directions), then
    # the (controller_id, source_id) pair is recorded in
    # ``state.loyalty_activated_this_turn``. The loyalty-at-0 SBA
    # (``turn.py`` 704.5i) catches a walker that drops to 0.
    loyalty: int = 0
    # "Discard this card" — the hand-activated cost atom of Cycling
    # (CR 702.29a: "[Cost], Discard this card: Draw a card.") and
    # Channel (CR 702.140 ability word over the same shape). Only
    # meaningful on abilities listed in
    # ``CardPrinting.hand_activated_abilities``: the source is the card
    # in its owner's hand, and paying the cost moves it to the
    # graveyard (a discard — discard triggers fire) before the ability
    # goes on the stack.
    discard_self: bool = False
    # "Remove a <kind> counter from this <permanent>" for a
    # ``GameObject.named_counters`` kind (Gemstone Mine: "mining").
    # ``legal_actions`` requires at least one such counter on the
    # source; ``_activate_ability`` removes one. "" = no such cost.
    remove_named_counter_from_self: str = ""

    def describe(self) -> str:
        parts: list[str] = []
        if self.mana_str:
            parts.append(self.mana_str)
        if self.discard_self:
            parts.append("Discard this card")
        if self.remove_named_counter_from_self:
            parts.append(
                f"Remove a {self.remove_named_counter_from_self} counter "
                f"from ~"
            )
        if self.tap_self:
            parts.append("{T}")
        if self.sacrifice_self:
            parts.append("Sacrifice ~")
        if self.exile_self:
            parts.append("Exile ~")
        if self.tap_permanent_you_control:
            parts.append("Tap an untapped permanent you control")
        if self.exile_artifact_from_graveyard:
            parts.append("Exile an artifact card from your graveyard")
        if self.sacrifice_another_creature_or_artifact:
            parts.append("Sacrifice another creature or artifact")
        if self.sacrifice_another_artifact_or_land:
            parts.append("Sacrifice another artifact or land")
        if self.sacrifice_another_artifact:
            parts.append("Sacrifice another artifact")
        if self.remove_plus_one_counter_from_your_creature:
            parts.append("Remove a +1/+1 counter from a creature you control")
        if self.sacrifice_food:
            parts.append("Sacrifice a Food")
        if self.exile_granting_equipment:
            parts.append("Exile this equipment")
        if self.mana_reduced_by_source_power:
            parts.append("(costs {X} less where X is this creature's power)")
        if self.pay_life:
            parts.append(f"Pay {self.pay_life} life")
        if self.sacrifice_a_land:
            parts.append("Sacrifice a land")
        if self.sacrifice_a_desert:
            parts.append("Sacrifice a Desert")
        if self.tap_x_untapped_artifacts_you_control:
            parts.append("Tap X untapped artifacts you control")
        if self.loyalty:
            # Printed-sign convention: positive cost.loyalty is a "-N"
            # ability, negative is "+N".
            if self.loyalty > 0:
                parts.append(f"-{self.loyalty}")
            else:
                parts.append(f"+{-self.loyalty}")
        return ", ".join(parts) if parts else "0"



@dataclass(frozen=True)
class ActivatedAbility:
    """An ability players can activate by paying ``cost``. On activation the
    ability goes on the stack; when it resolves, ``effect`` runs.

    ``sorcery_speed=True`` limits activation to main-phase-with-empty-stack
    timing (matches "Activate only as a sorcery").

    ``is_mana_ability=True`` short-circuits the stack: the effect
    resolves immediately on activation (real MTG rule 605 — mana
    abilities don't use the stack). Pair with an AddManaToPool effect.

    ``cost_reductions`` applies conditional generic-mana reductions to
    THIS ability's mana cost (analogous to ``CardPrinting.cost_reductions``
    for spell casts). Used by Thaumaton Torpedo's "this ability costs
    {3} less to activate if you attacked with a Spacecraft this turn".
    Walked by ``_effective_ability_mana_cost``; stored as a tuple of
    ``CostReduction`` (typed via ``Any`` here to dodge the cards-module
    import cycle).
    """

    cost: ActivationCost
    effect: Effect
    sorcery_speed: bool = False
    is_mana_ability: bool = False
    # Conditional generic-mana reductions to this ability's cost.
    # Mirrors CardPrinting.cost_reductions but applied at activation
    # time by actions._effective_ability_mana_cost. Matches Starport
    # Security's "this ability costs {2} less to activate if you
    # control a creature with a +1/+1 counter on it." and Thaumaton
    # Torpedo's "this ability costs {3} less to activate if you
    # attacked with a Spacecraft this turn."
    cost_reductions: tuple["CostReduction", ...] = ()
    # DSK Rooms: when this ability lives on a Room half, this is the
    # half-name (matches a key in ``CardPrinting.room_halves``).
    # ``effective_activated_abilities`` filters out abilities whose
    # ``room_half`` is not in the source's ``unlocked_halves``; the
    # half is locked, so its abilities are inert. ``None`` for
    # non-Room abilities — they're always active.
    room_half: "str | None" = None
    # EoE Spacecraft tier gate: this activated ability is only usable
    # when the source has ``tier_threshold`` or more charge counters.
    # 0 = always usable (default). Mirrors ``StaticAbility.tier_threshold``.
    # ``effective_activated_abilities`` filters out gated abilities when
    # the source doesn't meet the threshold. Used by The Eternity
    # Elevator's ``20+ | {T}: Add X mana of any one color`` ability.
    tier_threshold: int = 0
    # ``Activate only once.`` rider — DSK Haunted Screen's third
    # activation. When True, the ability is legal only while the
    # source's ``has_activated_once_only_ability`` flag is False; the
    # flag is latched at activation time (in ``_activate_ability``)
    # so a second activation (instant- or sorcery-speed) is rejected
    # by ``legal_actions`` even before the first activation has
    # resolved off the stack. The flag is per-``GameObject``, so a
    # blink-and-recast (a fresh ``GameObject`` instance) gets a fresh
    # one-shot per CR 706.2.
    activate_only_once: bool = False
    # "Activate only if <condition>." rider (CR 602.5b) — Library of
    # Alexandria's "Activate only if you have exactly seven cards in
    # hand." A ``Condition`` evaluated from the activator's viewpoint
    # (``condition.matches(state, activator_id)``); ``legal_actions``
    # omits the activation while it's False and ``_activate_ability``
    # refuses it defensively. ``None`` = no restriction.
    activate_only_if: "Condition | None" = None

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
    # Other tapped legendary creatures you control — The Seriema's
    # printed always-on static.
    OTHER_TAPPED_LEGENDARY_CREATURES_YOU_CONTROL = (
        "other_tapped_legendary_creatures_you_control"
    )
    # Slivers you control — Thrumming Hivepool.
    SLIVERS_YOU_CONTROL = "slivers_you_control"



@dataclass(frozen=True)
class StaticAbility:
    """A continuous ability on a permanent that grants keywords and/or P/T
    bonuses to matching permanents while the source is on the battlefield.

    Stage 3 supports anthem-style scopes. Consumers (effective_keywords,
    effective_power, effective_toughness) walk the battlefield at query
    time and fold in applicable bonuses — no layers system yet, so the
    ordering-of-continuous-effects subtleties from the comprehensive rules
    don't apply.
    """

    scope: str
    granted_keywords: frozenset[str] = frozenset()
    power_bonus: int = 0
    toughness_bonus: int = 0
    # Tiered abilities on Spacecraft: the ability is only active when the
    # source has ``tier_threshold`` or more charge counters. 0 = always on.
    tier_threshold: int = 0
    # DSK Rooms: when this static lives on a Room half, this is the
    # half-name (matches a key in ``CardPrinting.room_halves``). While
    # the half is locked (not in ``unlocked_halves``), the ability is
    # inert. ``None`` for non-Room statics — always active.
    room_half: "str | None" = None
    # Player-scope static: source's controller has no maximum hand
    # size (CR 402.2 default 7-card cleanup discard suspended).
    # Steaming Sauna (DSK Room half) prints ``You have no maximum
    # hand size.`` Gated by ``room_half`` while the half is locked.
    # ``run_cleanup_step`` scans the battlefield for active statics
    # carrying this flag whose source's controller is the active
    # player and skips the cleanup-discard loop when found, mirroring
    # CR 402.2's "no maximum hand size" replacement of the discard-
    # to-7 rule. The flag is independent of the creature-target
    # ``applies_to`` walk — this static doesn't grant keywords or
    # P/T bonuses to creatures, so the existing scope/applies_to
    # plumbing isn't exercised.
    grants_no_max_hand_size: bool = False
    # "Creature spells you control can't be countered." When True on a
    # permanent's static ability, ``CounterTargetSpell.legal_targets``
    # skips creature spells whose controller matches this permanent's
    # controller, and ``CounterTargetSpell.resolve`` is a no-op for such
    # targets. The effect is continuous (CR 101.2): while the source is
    # on the battlefield, every creature spell the controller puts on the
    # stack is shielded. Scope is implicitly the casting player's side;
    # ``applies_to`` is not used (this static applies to spells on the
    # stack, not permanents on the battlefield). Matches Frenzied Baloth's
    # third oracle line.
    grants_creature_spells_uncounterable: bool = False
    # ─── Modifier-grammar slots (additive; PR D consumers and later) ───
    # Optional structural condition gating ``applies_to``. When
    # present, evaluated against ``(state, source.controller_id,
    # chosen_targets=None)``. The source of truth for every
    # "as long as" rider on the static surface — printed conditions
    # like "as long as you control an artifact" or "during your turn"
    # ride here as ``ControlPermanent(IsArtifact())`` /
    # ``DuringYourTurn()`` rather than per-field boolean flags. ``None``
    # (default) is "no condition" and the gate short-circuits to
    # always-on.
    condition: "Condition | None" = None
    # Optional CR 614 replacement effect carried by this static.
    # Collected by :func:`mtg_bot.effects.modifiers
    # ._collect_replacement_effects` when ``StaticAbility`` is
    # exposed via the printing's static-abilities surface (PR-D
    # migrations move from per-printing boolean flags to native
    # ``ReplacementEffect`` declarations carried here). Unused
    # today — empty for every existing card.
    replacement_effect: "ReplacementEffect | None" = None
    # Optional CR 613 continuous-effect declaration carried by this
    # static. Renamed from the original ``ContinuousEffect`` to
    # ``ContinuousModifier`` to avoid colliding with the pre-existing
    # ``mtg_bot.game.ContinuousEffect`` (the runtime registry-entry
    # shape — every active layered effect lives in
    # ``GameState.continuous_effects`` as one of those). The PR-D
    # continuous-effect dispatcher walks every active
    # ``StaticAbility`` with this slot populated and folds the
    # ``ContinuousModifier.payload`` into the matching object's
    # effective state at the declared layer. Unused today — empty
    # for every existing card.
    continuous_effect: "ContinuousModifier | None" = None

    def applies_to(self, source, target, state: "GameState | None" = None) -> bool:
        """True if this ability, on ``source``, currently buffs ``target``."""
        from mtg_bot.game import is_creature_now

        # Creatures only, under the source's controller.
        if not is_creature_now(target):
            return False
        if target.controller_id != source.controller_id:
            return False
        # Spacecraft tier gate — source needs enough charge counters.
        if self.tier_threshold > 0 and source.charge_counters < self.tier_threshold:
            return False
        # Optional structural condition gate. Evaluated against
        # ``(state, source.controller_id)``; the source of truth for
        # every "as long as" rider on the static surface today. ``None``
        # (default) is "no condition" and short-circuits to the existing
        # always-on behaviour.
        if self.condition is not None:
            if state is None:
                return False
            if not self.condition.matches(
                state, source.controller_id, chosen_targets=None,
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
        if self.scope == StaticScope.SLIVERS_YOU_CONTROL:
            # Read effective_subtypes so a creature granted "Sliver"
            # by a layer-4 add_subtype effect (Conspiracy-style) is
            # picked up by Sliver lord anthems. ``state`` is optional
            # in this signature; without it we fall back to printing
            # to keep the static probe usable in card-list contexts.
            if state is not None:
                from mtg_bot.game import effective_subtypes
                return "Sliver" in effective_subtypes(state, target)
            return "Sliver" in target.printing.subtypes
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

    Two ways to specify what fires this ability:

    - **String-key style** (legacy): ``trigger`` is a string like
      ``"etb"`` / ``"landfall"`` / ``"dies"`` and the engine's
      per-event ``_fire_*`` functions hardcode-match it. Every static
      card today uses this path.
    - **Predicate style** (new): ``event`` is an ``Event`` enum value
      and ``predicate`` filters which firings of that event the
      ability cares about (subject type, controller, counters, etc.).
      The centralized dispatcher walks every triggered ability and
      fires the ones whose ``event`` matches and whose predicate
      evaluates true.

    Both styles coexist during migration. A given ability sets EXACTLY
    ONE of the two (the unused fields stay at their defaults). Phase 1
    only wires the ENTERS event family on the predicate path; the rest
    of the trigger taxonomy stays on the string-key path until later
    phases migrate them.

    ``requires_void`` is True for EoE "Void —" abilities, which only fire when
    ``is_void_active(state)`` (a nonland permanent left the battlefield this
    turn or a spell was warped this turn).
    """

    trigger: str = ""
    effect: "Effect | None" = None
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
    # Predicate-style trigger fields. ``event`` is an ``Event`` enum
    # value (None means string-key style); ``predicate`` is the filter
    # over event subjects, game state, and the source object. When
    # ``event`` is set, the engine's centralized dispatcher fires this
    # ability whenever the named event happens AND ``predicate``
    # evaluates true (or the predicate is None, which is treated as
    # ``Always``). String-key fields (``trigger``) are ignored on the
    # predicate path.
    event: "Event | None" = None
    predicate: "Predicate | None" = None
    # DSK Rooms: when this triggered ability lives on a Room half,
    # this is the half-name (matches a key in
    # ``CardPrinting.room_halves``). While the half is locked (not in
    # ``unlocked_halves``), the ability is inert and won't fire.
    # ``None`` for non-Room triggers — always active.
    room_half: "str | None" = None

    def __post_init__(self) -> None:
        if self.event is not None and self.trigger:
            raise ValueError(
                "TriggeredAbility cannot specify both `trigger` (string-key "
                "style) and `event` (predicate style); pick one."
            )

    def matches_event(
        self,
        event: "Event",
        subjects: "Mapping[str, object]",
        source: "object",
        state: "object",
    ) -> bool:
        """Predicate-style match check.

        Returns True iff this ability is on the predicate path
        (``self.event is not None``), the event matches, and the
        predicate evaluates true (or is unset, meaning ``Always``).
        Returns False for string-key abilities — those fire via the
        legacy per-event ``_fire_*`` paths.
        """
        if self.event is None:
            return False
        if self.event != event:
            return False
        if self.predicate is None:
            return True
        return self.predicate.matches(state, subjects, source)

    def describe(self) -> str:
        # Predicate-style abilities (``event`` is set, ``trigger`` is
        # empty) get a coarse human prefix derived from the event +
        # whatever predicate clauses we can recognize; the
        # printing-level oracle text is still the source of truth, this
        # is just for log/UI display. Fine-grained shapes
        # (Burgeoning's "an opponent plays a land" vs The Endstone's
        # "you play a land") aren't structurally distinguishable from
        # describe() alone since we'd need source context — the
        # PLAYS_LAND prefix uses the broad "an opponent plays a land"
        # form to keep parity with the legacy key it migrated from
        # (the only PLAYS_LAND-rider that exposes describe() in tests
        # today is Burgeoning, which is the opponent-form).
        if self.event is not None and not self.trigger:
            from mtg_bot.effects.object_predicates import IsArtifact
            from mtg_bot.effects.state_predicates import SpellsCastThisTurn
            from mtg_bot.effects.predicates import (
                Controlled, OPPONENT, StateBound, Subject, YOU,
            )
            event_prefix_map = {
                "enters": "When ~ enters the battlefield",
                "dies": "When ~ dies",
                "leaves_battlefield": "When ~ leaves the battlefield",
                "becomes_tapped": "Whenever ~ becomes tapped",
                "attacks": "Whenever ~ attacks",
                "dealt_damage": "Whenever ~ is dealt damage",
                "is_cast": "Whenever you cast a spell",
                "is_sacrificed": "Whenever you sacrifice another permanent",
                "plays_land": "Whenever an opponent plays a land",
                "discards_card": "Whenever an opponent discards a card",
                "counters_added": (
                    "Whenever you put one or more +1/+1 counters on a "
                    "creature you control"
                ),
                "beginning_of_upkeep": "At the beginning of your upkeep",
                "beginning_of_combat": (
                    "At the beginning of combat on your turn"
                ),
                "beginning_of_end_step": (
                    "At the beginning of your end step"
                ),
                "beginning_of_postcombat_main": (
                    "At the beginning of your second main phase"
                ),
                # Phase 9 added these. The DEALS_COMBAT_DAMAGE prefix
                # uses the broad self-form ("Whenever ~ deals combat
                # damage to a player") to match Illvoi Infiltrator's
                # printed text — the broader observer variants
                # (Starwinder's "a creature you control deals…",
                # Contested War Zone's "a creature deals combat damage
                # to you") are structurally distinct on the predicate
                # but indistinguishable here without source context, so
                # the self-form is the default and per-card describe
                # rides on the printed oracle text rather than this
                # prefix. Same trade-off as the PLAYS_LAND prefix above.
                "deals_combat_damage": (
                    "Whenever ~ deals combat damage to a player"
                ),
                "blocks": (
                    "Whenever ~ blocks a creature with flying"
                ),
            }
            # IS_CAST + IsArtifact("spell") → "Whenever you cast an
            # artifact spell" (Pinnacle Emissary). IS_CAST +
            # SpellsCastThisTurn(n=2) → "Whenever you cast your second
            # spell each turn".
            if self.event.value == "is_cast" and self.predicate is not None:
                from mtg_bot.effects.predicates import And

                def _leaves(p):
                    if isinstance(p, And):
                        return _leaves(p.left) + _leaves(p.right)
                    return [p]

                leaves = _leaves(self.predicate)
                if any(
                    isinstance(lf, StateBound)
                    and isinstance(lf.inner, SpellsCastThisTurn)
                    and lf.inner.n == 2
                    for lf in leaves
                ):
                    prefix = (
                        "Whenever you cast your second spell each turn"
                    )
                elif any(
                    isinstance(lf, Subject)
                    and lf.slot == "spell"
                    and isinstance(lf.inner, IsArtifact)
                    for lf in leaves
                ):
                    prefix = "Whenever you cast an artifact spell"
                else:
                    prefix = event_prefix_map.get(
                        self.event.value, self.event.value,
                    )
            else:
                prefix = event_prefix_map.get(
                    self.event.value, self.event.value,
                )
            head = f"{prefix}, {self.effect.describe()}."
            if self.requires_void:
                return "Void — " + head
            return head
        prefix = {
            "etb": "When ~ enters the battlefield",
            "beginning_of_end_step": "At the beginning of your end step",
            "beginning_of_combat": "At the beginning of combat on your turn",
            "beginning_of_upkeep": "At the beginning of your upkeep",
            "dies": "When ~ dies",
            "landfall": "Landfall — Whenever a land you control enters",
            "becomes_tapped": "Whenever ~ becomes tapped",
            "enchanted_permanent_becomes_tapped": (
                "Whenever enchanted permanent becomes tapped"
            ),
            "second_spell_each_turn": (
                "Whenever you cast your second spell each turn"
            ),
            "artifact_enters_you_control": (
                "Whenever another artifact you control enters"
            ),
            "creature_or_artifact_enters_you_control": (
                "Whenever another creature or artifact you control enters"
            ),
            "kavu_you_control_enters": (
                "Whenever this creature or another Kavu you control enters"
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
            "nontoken_creature_you_control_with_counter_dies": (
                "Whenever a nontoken creature you control with a +1/+1 "
                "counter on it dies"
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
            "your_counter_creature_combat_damage_to_player_aggregated": (
                "Whenever one or more creatures you control with +1/+1 "
                "counters on them deal combat damage to a player"
            ),
            "creature_deals_combat_damage_to_you": (
                "Whenever a creature deals combat damage to you"
            ),
            "another_creature_you_control_dies_or_exiled": (
                "Whenever another creature you control dies or is put "
                "into exile"
            ),
            "counters_added_to_your_creature": (
                "Whenever you put one or more +1/+1 counters on a "
                "creature you control"
            ),
            "opponent_plays_land": "Whenever an opponent plays a land",
        }.get(self.trigger, self.trigger)
        head = f"{prefix}, {self.effect.describe()}."
        if self.requires_void:
            return "Void — " + head
        return head


