"""Core effect infrastructure — base Effect class, Target alias,
ability dataclasses (ActivationCost / ActivatedAbility / StaticAbility /
TriggeredAbility), and shared private helpers used across effect modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mtg_bot.cards import ManaCost
    from mtg_bot.game import GameState


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
    # "Sacrifice another creature or artifact" — the caster picks a
    # legal target via choose_sacrifice. Cannot be the source itself.
    sacrifice_another_creature_or_artifact: bool = False
    # "Sacrifice another artifact or land" — as above but with a land
    # filter. Matches Slagdrill Scrapper.
    sacrifice_another_artifact_or_land: bool = False
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
    """

    cost: ActivationCost
    effect: Effect
    sorcery_speed: bool = False
    is_mana_ability: bool = False

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
        if self.scope == StaticScope.SLIVERS_YOU_CONTROL:
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


