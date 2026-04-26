"""Game state: zones, game objects, players, stack, and GameState."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Optional

from mtg_bot.cards import CardPrinting

if TYPE_CHECKING:
    from mtg_bot.agents import Agent
    from mtg_bot.effects import TriggeredAbility
    from mtg_bot.turn import Step


class Zone(Enum):
    LIBRARY = "library"
    HAND = "hand"
    BATTLEFIELD = "battlefield"
    GRAVEYARD = "graveyard"
    EXILE = "exile"
    STACK = "stack"


@dataclass
class GameObject:
    """An instance of a card in the game. Uniquely identified by ``id``."""

    id: int
    printing: CardPrinting
    owner_id: int
    controller_id: int
    zone: Zone
    tapped: bool = False
    damage: int = 0
    summoning_sick: bool = True
    attacking: bool = False
    blocking: Optional[int] = None
    blocked_by: list[int] = field(default_factory=list)
    # Marked lethal by a deathtouch source this turn — destroyed by SBAs
    # regardless of damage vs toughness. Cleared when damage is cleared.
    marked_lethal: bool = False
    # "Was this creature dealt damage this turn?" — set True at every site
    # that applies damage (combat damage, _apply_damage, bespoke pingers).
    # Cleared at cleanup. Used by effects with riders gated on
    # "if that creature wasn't dealt damage this turn" (Faller's Faithful).
    damaged_this_turn: bool = False
    # +1/+1 counters raise effective power and toughness by equal amounts.
    # Persist across turns (never wear off on their own).
    plus_one_counters: int = 0
    # "Can't be blocked this turn" marker (cleared at cleanup).
    temp_unblockable: bool = False
    # "Until end of turn, this land becomes a creature." Manlands
    # (Celestial Colonnade, Blinkmoth Nexus, etc.). When True, the
    # object counts as a creature for combat/targeting purposes.
    # Cleared at cleanup. Pair with temp_base_pt_override + temp_keywords.
    temp_is_creature: bool = False
    # Subtype granted UEOT — typically by an animation effect like
    # Blinkmoth Nexus's "becomes a 1/1 Blinkmoth artifact creature".
    # Cleared at cleanup. Consumed by target-subtype filters that
    # need to recognize creatures whose subtype is granted at runtime
    # (e.g. PumpTargetCreatureUntilEOT.target_subtype="Blinkmoth").
    temp_subtype: str | None = None
    # "You may play this card this turn" — set on cards exiled by
    # impulse-style effects (Territorial Bruntar landfall, Memorial
    # Vault activated). Cleared at cleanup. legal_actions honors it
    # for cast-from-exile at normal cost.
    playable_from_exile_this_turn: bool = False
    # Persistent cast-from-exile permission gated on the controller
    # controlling a Kavu. Set on cards exiled by Possibility
    # Technician's ETB / Kavu observer trigger ("for as long as that
    # card remains exiled, you may play it if you control a Kavu").
    # NOT cleared at cleanup — persists until the card leaves exile.
    # legal_actions honors it for cast-from-exile at normal cost when
    # the controller currently controls at least one Kavu.
    play_from_exile_requires_kavu: bool = False
    # Base P/T override ("has base power and toughness 1/1 until end of
    # turn") — Atomic Microsizer. None = use printed P/T. Cleared at
    # cleanup.
    temp_base_pt_override: "tuple[int, int] | None" = None
    # Warp-cast state. ``cast_via_warp`` is set True when this card was cast
    # from hand for its warp cost — it triggers an exile at the next end step.
    # ``warped`` is set True when this card sits in exile having been exiled
    # via that trigger — it can be cast from exile at its normal cost.
    cast_via_warp: bool = False
    warped: bool = False
    # EoE Spacecraft charge counters. A Spacecraft at ``station_threshold`` or
    # more is a creature (see ``is_creature_now``).
    charge_counters: int = 0
    # Stun counters: a permanent with stun counters doesn't untap during
    # its controller's untap step — instead one stun counter is removed.
    stun_counters: int = 0
    # Until-end-of-turn bonuses applied by pump effects (e.g. "+3/+0 until
    # end of turn"). Cleared on the cleanup step. Stacked additively when
    # multiple pumps hit the same object.
    temp_power_bonus: int = 0
    temp_toughness_bonus: int = 0
    temp_keywords: frozenset[str] = field(default_factory=frozenset)
    # Extended-temporal-scope bonuses: "until your next turn" — expire
    # at the START (untap step) of player ``extended_temp_expires_at_player_id``,
    # NOT at this turn's cleanup. Stacked additively, contribute to
    # effective_power / effective_toughness / effective_keywords just
    # like the regular temp_* fields. Matches Mouth of the Storm's
    # "creatures your opponents control get -3/-0 until your next turn."
    # Set ``extended_temp_expires_at_player_id`` to the casting/source
    # controller's id; their next untap clears these.
    extended_temp_power_bonus: int = 0
    extended_temp_toughness_bonus: int = 0
    extended_temp_keywords: frozenset[str] = field(default_factory=frozenset)
    extended_temp_expires_at_player_id: Optional[int] = None
    # UEOT triggered abilities granted by other effects (e.g. Requiem
    # Monolith's "Whenever this creature is dealt damage, you draw that
    # many cards and lose that much life"). Stored as a tuple so the
    # field is frozen-friendly and additive grants stack. Fire helpers
    # iterate this alongside ``printing.triggered_abilities``; the
    # ``should_fire_trigger`` once-per-turn ledger uses synthetic
    # ``("temp", i)`` indices to avoid colliding with printed-ability
    # indices. Cleared at cleanup.
    temp_triggered_abilities: "tuple[TriggeredAbility, ...]" = ()
    # Equipment attachment: if this object is Equipment, ``attached_to``
    # is the id of the creature it's attached to (or None if unattached).
    # Plays no role if the object isn't Equipment.
    attached_to: Optional[int] = None
    # Oblivion-Ring-style "until X leaves the battlefield" tracking: when
    # a card is exiled by a specific source, its ``exiled_by_source`` is
    # set to that source's id. When the source leaves the battlefield,
    # move_off_battlefield returns all cards tagged with its id from
    # exile back to their owner's battlefield.
    exiled_by_source: Optional[int] = None
    # "Gain control of ~ until end of turn" tracking: when this object
    # is controlled UEOT, ``temp_original_controller_id`` stores the
    # controller it came from. run_cleanup_step swaps ``controller_id``
    # back and clears this field. None = no temporary-control effect.
    temp_original_controller_id: Optional[int] = None
    # Planeswalker loyalty counters. Initialized to printing.loyalty
    # when a planeswalker enters the battlefield. State-based actions
    # send planeswalkers with 0 loyalty to the graveyard.
    loyalty_counters: int = 0
    # Snapshot of this object's original CardPrinting, taken the first
    # time a "becomes a copy of target X" effect mutates ``printing``.
    # Restored on cleanup? No — "becomes a copy" is a continuous effect
    # with no end condition, so the mutation persists. The snapshot is
    # kept so a second copy activation can re-derive "retained own
    # abilities" (Thespian's Stage: "except it has this ability").
    original_printing: Optional["CardPrinting"] = None
    # Regenerate shield: "The next time this creature would be
    # destroyed this turn, instead remove all damage from it, tap it,
    # and remove it from combat." Set by RegenerateTargetCreature;
    # consumed by state_based_actions when destruction is averted;
    # cleared at cleanup if unconsumed (regeneration is UEOT).
    regeneration_shield: bool = False
    # Phasing — "treat it and anything attached to it as though they
    # don't exist until its controller's next turn." While True, this
    # object is skipped in combat damage assignment. Set by
    # PhaseOutEquippedCreature (Robe of Stars) and cleared at the
    # start of its controller's untap step. Simplification: only
    # combat-damage resolution filters phased objects — triggers,
    # anthems, and legal_actions targeting don't (yet) hide them.
    phased_out: bool = False
    # Reveal-tracking for hidden-information determinization. Each
    # player id in this set has been shown this card's identity in a
    # way that gives them perfect knowledge of where it currently is —
    # e.g. it's their own card, it's in a public zone, or they were
    # shown it as part of resolution (tutor reveal, look-at-hand,
    # cast-from-exile-revealed). When the card moves into a face-down
    # zone whose ordering becomes uncertain (library shuffle, hand
    # mixed back into library), this is reset to ``frozenset()`` to
    # avoid the engine making misinformed claims about what other
    # players still know. See ``docs/HIDDEN_INFO_MODEL.md`` for the
    # design rationale and the under-informed edge cases this
    # representation cannot capture (multi-zone positional uncertainty,
    # cardinality constraints).
    publicly_known_to: frozenset[int] = field(default_factory=frozenset)


def is_void_active(state: GameState) -> bool:
    """EoE Void condition: a nonland permanent left the battlefield this turn
    OR a spell was warped this turn."""
    return (
        state.permanent_left_battlefield_this_turn
        or state.spell_warped_this_turn
    )


def reveal_to(obj: GameObject, *player_ids: int) -> None:
    """Mark ``obj`` as publicly known to each of ``player_ids``.

    Idempotent. Use this whenever a card's identity is shown to a
    specific set of players in a way that gives them perfect knowledge
    of where the card currently is — e.g. an opponent looks at your
    hand (reveal_to(card, looker_id)) or you tutor with a reveal step
    and put the card into your hand publicly (reveal_to_all(state, card)).

    See ``docs/HIDDEN_INFO_MODEL.md`` for the design and its caveats.
    """
    if not player_ids:
        return
    obj.publicly_known_to = obj.publicly_known_to | frozenset(player_ids)


def reveal_to_all(state: GameState, obj: GameObject) -> None:
    """Mark ``obj`` as publicly known to every player in ``state``.

    Use at every site where a card is revealed publicly — bounce
    (battlefield → hand), tutor-with-reveal landing in hand, casting
    a spell from a private zone (it briefly transits the public
    stack), etc.
    """
    obj.publicly_known_to = frozenset(p.id for p in state.players)


def reset_public_knowledge(obj: GameObject) -> None:
    """Drop everyone from ``obj.publicly_known_to``.

    Call at "disturbance" sites — library shuffles, hand mixed back
    into library, scry-then-shuffle. Conservatively forgets all
    revealed-knowledge state; the bot becomes under-informed rather
    than misinformed about what other players still know.
    """
    obj.publicly_known_to = frozenset()


def reset_library_public_knowledge(state: GameState, player_id: int) -> None:
    """After shuffling ``player_id``'s library, forget who knew what
    about each card in it. Convenience wrapper around
    ``reset_public_knowledge`` for the common "shuffle the whole
    library" case.
    """
    p = state.player_by_id(player_id)
    for card in p.library:
        reset_public_knowledge(card)


def shuffle_library(state: GameState, player_id: int) -> None:
    """Shuffle ``player_id``'s library and reset reveal-tracking on
    every card in it.

    Always use this helper instead of calling ``state.rng.shuffle``
    directly on a library — it keeps shuffle and knowledge-reset paired
    so the engine can never produce a state where the determinizer
    "remembers" a card whose position was actually scrambled.
    """
    p = state.player_by_id(player_id)
    state.rng.shuffle(p.library)
    for card in p.library:
        reset_public_knowledge(card)


def is_stationed(obj: GameObject) -> bool:
    """True when this Spacecraft has enough charge counters to be a creature."""
    threshold = obj.printing.station_threshold
    return threshold is not None and obj.charge_counters >= threshold


def is_creature_now(obj: GameObject) -> bool:
    """Whether ``obj`` currently counts as a creature on the battlefield.

    True for printed creatures, for Spacecraft whose charge-counter
    threshold has been crossed (they're artifact creatures while
    stationed), and for lands animated by a manland activation
    (``temp_is_creature`` set until cleanup).
    """
    return (
        obj.printing.is_creature
        or is_stationed(obj)
        or obj.temp_is_creature
    )


def _static_bonuses(
    state: GameState, obj: GameObject
) -> tuple[int, int, frozenset[str]]:
    """Walk the battlefield for static abilities that buff ``obj``.

    Returns (power_bonus, toughness_bonus, granted_keywords). Used by the
    effective_* helpers below.
    Also folds in bonuses from any Equipment attached to ``obj``.
    """
    power_bonus = 0
    toughness_bonus = 0
    granted: set[str] = set()
    for source in state.battlefield:
        for ability in source.printing.static_abilities:
            if ability.applies_to(source, obj, state):
                power_bonus += ability.power_bonus
                toughness_bonus += ability.toughness_bonus
                granted |= ability.granted_keywords
    # Equipment attached to obj contributes its equipment_bonuses.
    for source in state.battlefield:
        if source.attached_to != obj.id:
            continue
        eb = source.printing.equipment_bonuses
        if eb is None:
            continue
        ep, et, ek = eb
        power_bonus += ep
        toughness_bonus += et
        granted |= ek
    return power_bonus, toughness_bonus, frozenset(granted)


def effective_keywords(state: GameState, obj: GameObject) -> frozenset[str]:
    """Keywords in effect right now — printing + stationed_keywords +
    keywords granted by static abilities on other permanents + UEOT
    keyword grants from pump effects."""
    kws = obj.printing.keywords
    if is_stationed(obj):
        kws = kws | obj.printing.stationed_keywords
    _, _, granted = _static_bonuses(state, obj)
    return (
        kws | granted | obj.temp_keywords | obj.extended_temp_keywords
    )


def _dynamic_base_pt(
    state: GameState, obj: GameObject
) -> tuple[int, int] | None:
    """Return (base_power, base_toughness) for dynamic-P/T creatures,
    or None if this creature has no dynamic formula and should use
    its printed P/T.
    """
    formula = obj.printing.dynamic_pt_formula
    if formula is None:
        return None
    if formula == "cosmogoyf":
        # Cards owned in exile (by the creature's controller).
        controller = state.player_by_id(obj.controller_id)
        n = len(controller.exile)
        return n, n + 1
    if formula == "harmonious_grovestrider":
        # P = T = number of lands the controller controls.
        n = sum(
            1 for o in state.battlefield
            if o.controller_id == obj.controller_id and o.printing.is_land
        )
        return n, n
    if formula == "emissary_escort":
        # "Gets +X/+0 where X is the greatest mana value among other
        # artifacts you control." We encode that as a dynamic base
        # derived from printed P/T plus X on power only.
        mvs = [
            o2.printing.mana_cost.total
            for o2 in state.battlefield
            if o2.controller_id == obj.controller_id
            and o2.printing.is_artifact
            and o2.id != obj.id
        ]
        x = max(mvs) if mvs else 0
        printed_p = obj.printing.power or 0
        printed_t = obj.printing.toughness or 0
        return printed_p + x, printed_t
    return None  # pragma: no cover - defensive fallback


def gain_life(state: "GameState", player_id: int, amount: int) -> int:
    """Add ``amount`` life to ``player_id`` and track it in
    life_gained_this_turn. Returns the amount actually gained (same as
    ``amount`` for non-negative values; zero for non-positive).

    Use this helper instead of mutating ``p.life`` directly whenever
    an effect "gains life" — keys like Ragost's "if you gained life
    this turn" rely on the tracker being kept up-to-date.
    """
    if amount <= 0:
        return 0
    p = state.player_by_id(player_id)
    p.life += amount
    p.life_gained_this_turn += amount
    return amount


def effective_subtypes(
    state: "GameState", obj: "GameObject"
) -> tuple[str, ...]:
    """Return ``obj``'s subtypes including any granted by permanents
    on the battlefield. Currently only handles "artifacts you control
    are Foods" (Ragost, Deft Gastronaut's static)."""
    subtypes = list(obj.printing.subtypes)
    if obj.printing.is_artifact:
        for o in state.battlefield:
            if o.id == obj.id:
                continue
            if o.controller_id != obj.controller_id:
                continue
            if o.printing.grants_food_to_your_artifacts:
                if "Food" not in subtypes:
                    subtypes.append("Food")
                break
    return tuple(subtypes)


def magus_of_the_moon_active(state: "GameState") -> bool:
    """True when any permanent on the battlefield has the
    ``nonbasic_lands_are_mountains`` flag. Used by
    effective_land_produces and effective_activated_abilities to
    collapse nonbasic lands to vanilla Mountains.
    """
    return any(
        o.printing.nonbasic_lands_are_mountains for o in state.battlefield
    )


def effective_land_produces(
    state: "GameState", land_obj: "GameObject"
) -> frozenset[str]:
    """Return the effective colors a land taps for, applying the
    Magus-of-the-Moon rewrite.

    Nonbasic lands under Magus produce {R} only; basic lands and any
    lands when Magus isn't active use their printed ``produces`` set
    unchanged.
    """
    if (
        not land_obj.printing.is_basic_land
        and magus_of_the_moon_active(state)
    ):
        return frozenset({"R"})
    return land_obj.printing.produces


def effective_activated_abilities(
    state: "GameState", obj: "GameObject"
) -> tuple:
    """Return ``obj``'s activated abilities plus any granted.

    Current grants:
    - Ragost: artifacts you control gain {2}, {T}, Sac: gain 3 life.
    - The Dominion Bracelet: the equipped creature gains the
      control-opponent-next-turn activated ability.

    Magus of the Moon: nonbasic lands lose their activated abilities
    entirely (their {T}: Add {R} tap is handled via
    ``effective_land_produces``, not as an activated ability).
    """
    from mtg_bot.cards import (
        DOMINION_BRACELET_GRANTED_ABILITY, RAGOST_FOOD_GRANTED_ABILITY,
    )

    # Magus: nonbasic land abilities suppressed while in play.
    if (
        obj.printing.is_land and not obj.printing.is_basic_land
        and magus_of_the_moon_active(state)
    ):
        return ()

    base = list(obj.printing.activated_abilities)
    if obj.printing.is_artifact:
        for o in state.battlefield:
            if o.id == obj.id:
                continue
            if o.controller_id != obj.controller_id:
                continue
            if o.printing.grants_food_ability_to_your_artifacts:
                base.append(RAGOST_FOOD_GRANTED_ABILITY)
                break
    # Equipment-granted abilities: walk attached equipment.
    for o in state.battlefield:
        if o.attached_to != obj.id:
            continue
        if o.printing.grants_control_opponent_ability_when_equipped:
            base.append(DOMINION_BRACELET_GRANTED_ABILITY)
    return tuple(base)


def effective_draw_count(
    state: "GameState", player_id: int, base_count: int
) -> int:
    """Effective number of cards a "draw N" event should draw for
    ``player_id``, accounting for active replacement effects.

    Currently models Quantum Riddler: "As long as you have one or
    fewer cards in hand, if you would draw one or more cards, you
    draw that many cards plus one instead." Returns ``base_count + 1``
    when the controller has a Quantum-Riddler-flavored permanent on
    the battlefield AND hand size ≤ 1 AND base_count ≥ 1; otherwise
    returns ``base_count`` unchanged. Multiple Riddlers don't stack —
    the replacement adds one card per draw event regardless.
    """
    if base_count < 1:
        return base_count
    p = state.player_by_id(player_id)
    if len(p.hand) > 1:
        return base_count
    has_riddler = any(
        o.controller_id == player_id
        and o.printing.replaces_draw_with_extra_when_hand_at_most_one
        for o in state.battlefield
    )
    return base_count + 1 if has_riddler else base_count


def etb_trigger_multiplier(state: "GameState", controller_id: int) -> int:
    """Return how many times an ETB-caused triggered ability on a
    permanent controlled by ``controller_id`` should fire.

    1 by default, +1 per permanent the controller controls with
    ``extra_etb_trigger > 0`` (Starfield Vocalist). Matches the
    oracle wording: "If a permanent entering the battlefield causes
    a triggered ability of a permanent you control to trigger, that
    ability triggers an additional time."
    """
    extra = sum(
        o.printing.extra_etb_trigger for o in state.battlefield
        if o.controller_id == controller_id
    )
    return 1 + extra


def _counter_doubling_factor(state: GameState, obj: GameObject) -> int:
    """Return 2^N where N is the number of Loading-Zone-style counter
    doublers active for ``obj``. Loading Zone's scope: counters being
    put on a creature, Spacecraft, or Planet you control. The "Planet"
    type isn't modeled yet, so we apply on creatures and Spacecraft.
    Returns 1 when ``obj`` is outside that scope or no doublers are in
    play.
    """
    if not (obj.printing.is_creature or obj.printing.is_spacecraft):
        return 1
    doublers = sum(
        1 for o in state.battlefield
        if o.controller_id == obj.controller_id
        and o.printing.is_counter_doubler
    )
    return 2 ** doublers


def add_plus_one_counters(
    state: GameState, obj: GameObject, amount: int
) -> int:
    """Add ``amount`` +1/+1 counters to ``obj``, applying Loading Zone-
    style doubling replacement effects for each active doubler
    controlled by the recipient. Only applies to creatures and
    Spacecraft (the Planet type isn't modeled yet) — matches the real
    Loading Zone scope.

    Fires "whenever you put one or more +1/+1 counters on a creature
    you control" observer triggers (Terrasymbiosis) for counters added
    to creatures.

    Returns the effective count actually added (after doubling). Safe
    when amount <= 0 (no-op).
    """
    if amount <= 0:
        return 0
    effective = amount * _counter_doubling_factor(state, obj)
    obj.plus_one_counters += effective
    if obj.printing.is_creature and effective > 0:
        from mtg_bot.turn import fire_counters_added_to_your_creature_triggers
        fire_counters_added_to_your_creature_triggers(
            state, obj.controller_id, effective,
        )
    return effective


def add_charge_counters(
    state: GameState, obj: GameObject, amount: int
) -> int:
    """Add ``amount`` charge counters to ``obj``. Charge counters are
    Spacecraft-only in the EoE engine, so doubling via Loading Zone
    applies (Spacecraft is in scope). Returns the effective count
    actually added.
    """
    if amount <= 0:
        return 0
    effective = amount * _counter_doubling_factor(state, obj)
    obj.charge_counters += effective
    return effective


def add_stun_counters(
    state: GameState, obj: GameObject, amount: int
) -> int:
    """Add ``amount`` stun counters to ``obj``, applying Loading Zone
    doubling when ``obj`` is in scope (creature/Spacecraft). Returns
    the effective count actually added.
    """
    if amount <= 0:
        return 0
    effective = amount * _counter_doubling_factor(state, obj)
    obj.stun_counters += effective
    return effective


def effective_power(state: GameState, obj: GameObject) -> int:
    """Power including +1/+1 counters, static bonuses, and UEOT pumps.
    Dynamic P/T creatures compute their base via ``dynamic_pt_formula``
    instead of reading ``printing.power``.
    """
    dynamic = _dynamic_base_pt(state, obj)
    if obj.temp_base_pt_override is not None:
        base = obj.temp_base_pt_override[0]
    else:
        base = dynamic[0] if dynamic is not None else (obj.printing.power or 0)
    power_bonus, _, _ = _static_bonuses(state, obj)
    return (
        base
        + obj.plus_one_counters
        + power_bonus
        + obj.temp_power_bonus
        + obj.extended_temp_power_bonus
    )


def effective_toughness(state: GameState, obj: GameObject) -> int:
    """Toughness including +1/+1 counters, static bonuses, and UEOT pumps.
    Dynamic P/T creatures compute their base via ``dynamic_pt_formula``
    instead of reading ``printing.toughness``.
    """
    dynamic = _dynamic_base_pt(state, obj)
    if obj.temp_base_pt_override is not None:
        base = obj.temp_base_pt_override[1]
    else:
        base = dynamic[1] if dynamic is not None else (obj.printing.toughness or 0)
    _, toughness_bonus, _ = _static_bonuses(state, obj)
    return (
        base
        + obj.plus_one_counters
        + toughness_bonus
        + obj.temp_toughness_bonus
        + obj.extended_temp_toughness_bonus
    )


@dataclass
class StackItem:
    """A spell or triggered ability on the stack.

    When ``ability`` is None the stack item represents a spell being cast;
    resolving it moves ``source`` to the battlefield. When ``ability`` is set,
    the item represents a triggered ability; resolving it runs the effect.

    ``targets`` holds (kind, id) pairs chosen when the ability went on the
    stack — empty for spells and for untargeted abilities.
    """

    source: GameObject
    controller_id: int
    # Either a TriggeredAbility or an ActivatedAbility — both have an
    # ``.effect`` attribute and resolve the same way.
    ability: "object | None" = None
    targets: tuple[tuple[str, int], ...] = ()
    # True when the spell was countered at cast time (currently by unpaid
    # Ward). A countered spell resolves as a no-op, with the card going
    # to its owner's graveyard (for instants/sorceries) or vanishing
    # (for permanents) without firing any effects/ETBs.
    countered: bool = False
    # The value chosen for {X} in this spell's cost (0 for non-X spells).
    # Set by _cast_spell via agent.choose_x; exposed to the resolving
    # effect via state.resolving_x_value.
    x_value: int = 0
    # True when the spell was cast with its kicker cost paid. Exposed
    # to the resolving effect via state.resolving_kicked.
    kicked: bool = False
    # Id of the creature the caster designated as a
    # choose-your-creature additional cost. None for spells that
    # don't have such a cost. Mirrored to
    # state.resolving_additional_cost_choice_id during resolution.
    additional_cost_choice_id: Optional[int] = None
    # Combat damage amount carried by a combat-damage-triggered ability
    # while it sits on the stack. Mirrored to
    # state.resolving_combat_damage_amount during resolution so effects
    # like DrawCardsEqualToResolvingCombatDamage can read "that many"
    # even though the ability resolves after the damage step ends.
    # 0 for non-combat-damage triggers and for spells.
    combat_damage_amount: int = 0
    # Counter amount carried by a counters-added-to-creature observer
    # trigger. Mirrored to state.resolving_counter_amount during
    # resolution so effects like Terrasymbiosis ("draw that many cards")
    # can read the count even though the ability resolves later.
    counter_amount: int = 0


@dataclass
class Player:
    id: int
    life: int = 20
    # Starting life total — used by effects that reference it directly
    # (e.g. "your life total becomes half your starting life total").
    # Defaults to 20 (MTG standard); adjust for alternate formats.
    starting_life: int = 20
    # Poison counters (MTG rule 704.5c). A player with 10+ poison
    # counters loses the game — enforced via state-based actions.
    poison_counters: int = 0
    library: list[GameObject] = field(default_factory=list)
    hand: list[GameObject] = field(default_factory=list)
    graveyard: list[GameObject] = field(default_factory=list)
    exile: list[GameObject] = field(default_factory=list)
    lands_played_this_turn: int = 0
    # Number of lands that have entered the battlefield under this player's
    # control during the current turn. Distinct from lands_played_this_turn
    # (which counts the per-turn land-drop action only): incremented for
    # *every* land ETB, including basics fetched by Lander tokens or other
    # search-and-put-onto-battlefield effects. Reset at cleanup. Used by
    # cards that read "for each land that entered the battlefield under your
    # control this turn" (Bioengineered Future).
    lands_entered_this_turn: int = 0
    # Number of spells this player has cast in the current turn. Reset at
    # cleanup. Used by "whenever you cast your Nth spell each turn" triggers.
    spells_cast_this_turn: int = 0
    # Number of noncreature spells this player has cast this turn. Reset
    # at cleanup. Used by the Deafening Silence restriction ("each player
    # can't cast more than one noncreature spell each turn") — legal_actions
    # gates additional noncreature casts when any permanent on the
    # battlefield has ``restricts_noncreature_spells_to_one_per_turn``.
    noncreature_spells_cast_this_turn: int = 0
    # True if this player has declared at least one Spacecraft as an
    # attacker this turn. Reset at cleanup. Drives the
    # "attacked_with_spacecraft_this_turn" cost-reduction condition.
    attacked_with_spacecraft_this_turn: bool = False
    # Number of artifacts that entered the battlefield under this
    # player's control this turn. Reset at cleanup. Incremented by
    # ``actions.put_into_battlefield`` whenever an artifact (including
    # artifact creatures and artifact tokens) enters under their
    # control. Used by Mechan Shieldmate's "as long as an artifact
    # entered the battlefield under your control this turn, this
    # creature can attack as though it didn't have defender" — see
    # ``CardPrinting.attack_bypass_if_artifact_entered_this_turn`` and
    # ``combat.eligible_attackers``.
    artifacts_entered_under_your_control_this_turn: int = 0
    has_lost: bool = False
    lost_reason: str = ""
    agent: Optional["Agent"] = None
    # Mana pool: list of ManaCoin entries (color + optional spend
    # restriction). Populated by mana-ability activations; consumed
    # before lands when paying costs; emptied at cleanup step.
    mana_pool: list["ManaCoin"] = field(default_factory=list)
    # Total life gained this turn. Reset at cleanup. Consumed by
    # effects that key on "if you gained life this turn" (Ragost,
    # Deft Gastronaut's end-step untap). Incremented by gain_life().
    life_gained_this_turn: int = 0
    # Pending agent swap scheduled by The Dominion Bracelet's
    # "You control target opponent during their next turn". When set,
    # run_untap_step installs the override at the start of this
    # player's next turn (saving the original agent in
    # ``agent_override_saved`` so cleanup can revert).
    scheduled_agent_override: Optional["Agent"] = None
    scheduled_agent_override_by: Optional[int] = None
    agent_override_saved: Optional["Agent"] = None


@dataclass
class ManaCoin:
    """A unit of mana in a player's pool.

    ``color`` is one of "W", "U", "B", "R", "G", "C" (colorless), or
    "any" (a wildcard produced by effects like All-Fates Scroll's
    "{T}: Add one mana of any color"). An "any" coin can satisfy any
    colored requirement; colorless coins only satisfy generic
    requirements.

    ``spend_restriction`` gates what the coin can pay for. None =
    unrestricted. Known values: "artifact_spell" (Steelswarm Operator's
    first mana ability — "Spend this mana only to cast an artifact
    spell"); "artifact_activation" (Steelswarm Operator's second mana
    ability — "Spend this mana only to activate abilities of artifact
    sources"); "colorless_eldrazi" (Eldrazi Temple's second mana
    ability).
    """

    color: str
    spend_restriction: Optional[str] = None


def _clone_mana_coin(coin: ManaCoin) -> ManaCoin:
    """Fast clone for ManaCoin — same ``__new__`` + ``__dict__`` copy
    pattern as ``GameState.clone``'s per-object cloners. ManaCoin's
    two fields are immutable strings, so the shared __dict__ values
    are safe; only the dict itself is duplicated."""
    new = ManaCoin.__new__(ManaCoin)
    new.__dict__ = coin.__dict__.copy()
    return new


class LogBuffer(list[str]):
    """A list[str] with a global silent-mode switch.

    ``append(msg)`` early-returns when ``enabled`` is False. All other
    list operations behave exactly like a normal ``list``. The engine
    appends to ``state.log`` from hundreds of sites; turning this
    buffer off lets search/rollout code skip those string allocations
    without touching any call site.

    Reads still work — tests that inspect log contents continue to
    pass while the buffer is enabled (the default).
    """

    enabled: bool = True

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.enabled = True

    def append(self, msg: str) -> None:  # type: ignore[override]
        if not self.enabled:
            return
        list.append(self, msg)


@dataclass
class GameState:
    players: list[Player] = field(default_factory=list)
    battlefield: list[GameObject] = field(default_factory=list)
    stack: list[StackItem] = field(default_factory=list)
    active_player_idx: int = 0
    priority_player_idx: int = 0
    turn_number: int = 1
    step: Optional["Step"] = None
    next_object_id: int = 0
    log: LogBuffer = field(default_factory=LogBuffer)
    # Canonical game-wide RNG. Engine sites that need randomness (library
    # shuffles from Nexus, tutor shuffles, ward random-discard, etc.) pull
    # from ``state.rng`` so a run is reproducible from a single seed and
    # so search can fork a clone's RNG cleanly. ``simulate.setup_game``
    # seeds this from the caller-supplied seed.
    rng: random.Random = field(default_factory=random.Random)
    winner_id: Optional[int] = None
    is_draw: bool = False
    # EoE "Void" turn-state flags. Both are reset on cleanup (end of turn).
    # ``permanent_left_battlefield_this_turn`` is set whenever any nonland
    # permanent leaves the battlefield (destroy, exile, bounce, cease-to-
    # exist, warp-exile). ``spell_warped_this_turn`` is set when a spell
    # was cast via its warp alt-cost. The ``is_void_active`` helper returns
    # True when either flag is set, which is the Void trigger condition.
    permanent_left_battlefield_this_turn: bool = False
    spell_warped_this_turn: bool = False
    # Tracks (source_id, ability_index) pairs for triggered abilities that
    # have already fired this turn under the ``once_per_turn`` restriction.
    # Reset by run_cleanup_step.
    once_per_turn_fired: set[tuple[int, int]] = field(default_factory=set)
    # Delayed triggered abilities scheduled for a future end step. Each
    # entry is a dict: {"fire_at_turn": int, "controller_id": int,
    # "action": str, "target_id": int}.
    # Actions currently supported: "sacrifice".
    delayed_triggers: list[dict] = field(default_factory=list)
    # Source GameObject of the currently-resolving ability, if any. Set by
    # resolve_top_of_stack during ability resolution so effects like
    # "put a +1/+1 counter on this creature" can reach the source without
    # having to thread it through every resolve() signature.
    resolving_source: Optional[GameObject] = None
    # Value of {X} for the currently-resolving spell or ability. Mirrors
    # StackItem.x_value during resolution so effects can read X without
    # threading it through every resolve() signature. 0 when no X spell
    # is resolving.
    resolving_x_value: int = 0
    # Mirrors StackItem.kicked during resolution so effects can branch
    # on whether the spell was kicked without threading it through
    # every resolve() signature. False outside resolution.
    resolving_kicked: bool = False
    # Mirrors StackItem.additional_cost_choice_id during resolution so
    # effects (e.g. Close Encounter) can read the creature the caster
    # designated as an additional cost. None outside resolution.
    resolving_additional_cost_choice_id: Optional[int] = None
    # Amount of combat damage dealt by the source that is currently
    # firing a combat-damage trigger. 0 outside combat-trigger
    # resolution. Used by effects like Starwinder's "may draw that
    # many cards" that need to know the damage amount.
    resolving_combat_damage_amount: int = 0
    # Controller id of the creature dealing combat damage in a
    # currently-firing combat-damage-to-you trigger. None outside such
    # resolution. Used by Contested War Zone's "that creature's
    # controller gains control of this land".
    resolving_combat_damage_source_controller_id: Optional[int] = None
    # Number of +1/+1 counters being added during a resolving
    # counters-added observer trigger (Terrasymbiosis: "draw that many
    # cards"). 0 outside such resolution.
    resolving_counter_amount: int = 0
    # IDs of permanents scheduled to be sacrificed at end of combat.
    # Cleared during clear_combat_state after processing.
    # Used by Kavaron Harrier's attack token.
    pending_end_of_combat_sacrifices: list[int] = field(default_factory=list)
    # Player ids who have already created one or more tokens this turn.
    # Gates "the first time you would create tokens each turn"
    # replacement effects (Moonlit Meditation). Cleared at cleanup.
    players_who_created_tokens_this_turn: set[int] = field(default_factory=set)
    # Per-turn counter of how many times a tagged ability has resolved.
    # Keys are effect-specific labels (typically ("tag", source_id)).
    # Reset by run_cleanup_step. Used by Tannuk, Memorial Ensign's
    # "if this is the second time this ability has resolved" rider.
    ability_resolutions_this_turn: dict = field(default_factory=dict)
    # When True, combat damage assignment in combat._resolve_damage_step
    # is skipped entirely for the remainder of the turn. Set by Darkness
    # ({B} instant) and reset by run_cleanup_step. Non-combat damage
    # (direct damage spells, pingers, infect from non-combat sources)
    # is unaffected.
    prevent_combat_damage_this_turn: bool = False
    # FIFO queue of player ids scheduled to take an extra turn after
    # the current one wraps up. Populated by TakeExtraTurnAfterThisOne
    # (Nexus of Fate). Consumed by simulate.simulate_game between
    # turns: if the queue is non-empty, the next turn's active player
    # is the head of the queue instead of the natural next alive player.
    extra_turn_queue: list[int] = field(default_factory=list)

    def active_player(self) -> Player:
        return self.players[self.active_player_idx]

    def player_by_id(self, player_id: int) -> Player:
        for p in self.players:
            if p.id == player_id:
                return p
        raise KeyError(f"no player with id={player_id}")

    def index_of(self, player_id: int) -> int:
        for i, p in enumerate(self.players):
            if p.id == player_id:
                return i
        raise KeyError(f"no player with id={player_id}")

    def new_object(
        self, printing: CardPrinting, owner_id: int, zone: Zone
    ) -> GameObject:
        obj = GameObject(
            id=self.next_object_id,
            printing=printing,
            owner_id=owner_id,
            controller_id=owner_id,
            zone=zone,
        )
        self.next_object_id += 1
        return obj

    def is_over(self) -> bool:
        return self.winner_id is not None or self.is_draw

    def creatures_controlled_by(self, player_id: int) -> list[GameObject]:
        return [
            o for o in self.battlefield
            if o.controller_id == player_id and o.printing.is_creature
        ]

    def lands_controlled_by(self, player_id: int) -> list[GameObject]:
        return [
            o for o in self.battlefield
            if o.controller_id == player_id and o.printing.is_land
        ]

    def clone(self) -> "GameState":
        """Return an independent deep copy of this state, suitable for
        search rollouts.

        Semantics vs. ``copy.deepcopy(state)``:

        - CardPrinting refs are shared (frozen dataclasses with no
          mutable state). Same for frozensets and tuples of primitives.
        - All GameObjects are deep-copied. A ``{old_id: new_obj}`` map
          drives cross-reference rewiring so ``state.stack``'s StackItem
          sources and ``state.resolving_source`` point at the cloned
          objects.
        - Every zone list (battlefield + each player's library / hand /
          graveyard / exile / mana_pool) is a fresh list containing the
          cloned GameObjects.
        - ``state.log`` is a fresh empty ``LogBuffer`` with the same
          ``enabled`` flag — search rollouts don't need log history.
        - ``state.rng`` is a fresh ``random.Random`` seeded from the
          original's state, so the clone advances independently but
          deterministically.
        - ``Player.agent`` is **not** cloned — agents are decision-
          policy objects, not game state, and cloning them would both
          be wasteful and break mutable-agent contracts (RandomAgent's
          RNG, scheduled agent overrides). Search callers that need
          to vary the policy per rollout should swap the agent ref
          on the clone after calling ``.clone()``.

        GameObject integer id references (``attached_to``,
        ``exiled_by_source``, ``temp_original_controller_id``) carry
        integer ids — those stay valid without remapping because the
        new objects keep the same id.

        Performance: this is a search hot path (thousands of clones
        per MCTS decision). Per-object cloning uses a shallow
        ``object.__new__`` + ``__dict__`` copy rather than the
        dataclass __init__ with 30+ kwargs — the latter spends
        almost all its time in name-resolution overhead.
        ``GameObject.blocked_by`` is the only mutable per-object
        field; we duplicate that explicitly. Every other field is
        either an int / bool / None / frozenset / Enum (immutable)
        or a reference to a frozen-dataclass CardPrinting (also
        safe to share).
        """
        # Build the id->new_obj map by deep-copying every GameObject
        # referenced anywhere in the state. We walk zones in a fixed
        # order and copy each object exactly once.
        id_map: dict[int, GameObject] = {}

        def clone_obj(o: GameObject) -> GameObject:
            existing = id_map.get(o.id)
            if existing is not None:
                return existing
            # Fast clone: skip __init__ entirely, copy the __dict__ in
            # one C-level call, then duplicate the only mutable field.
            new = GameObject.__new__(GameObject)
            new.__dict__ = o.__dict__.copy()
            new.blocked_by = list(o.blocked_by)
            id_map[o.id] = new
            return new

        # Clone players (and every zone list on each player). Same
        # __new__ + __dict__ copy trick as clone_obj — avoids the
        # dataclass __init__'s 18+ kwarg dispatch. Agent is shared
        # (not game state). ManaCoin is a dataclass with two
        # immutable string fields and is never mutated post-creation
        # in the engine, so we copy via the same fast path.
        new_players: list[Player] = []
        for p in self.players:
            np = Player.__new__(Player)
            np.__dict__ = p.__dict__.copy()
            np.library = [clone_obj(o) for o in p.library]
            np.hand = [clone_obj(o) for o in p.hand]
            np.graveyard = [clone_obj(o) for o in p.graveyard]
            np.exile = [clone_obj(o) for o in p.exile]
            np.mana_pool = [_clone_mana_coin(c) for c in p.mana_pool]
            new_players.append(np)

        new_battlefield = [clone_obj(o) for o in self.battlefield]

        # Stack items must point at the cloned GameObject for their
        # source. All other fields are immutable; share by reference.
        new_stack: list[StackItem] = []
        for item in self.stack:
            ni = StackItem.__new__(StackItem)
            ni.__dict__ = item.__dict__.copy()
            ni.source = clone_obj(item.source)
            new_stack.append(ni)

        new_log = LogBuffer()
        new_log.enabled = self.log.enabled

        new_rng = random.Random()
        new_rng.setstate(self.rng.getstate())

        new_resolving_source = (
            clone_obj(self.resolving_source)
            if self.resolving_source is not None else None
        )

        new_state = GameState(
            players=new_players,
            battlefield=new_battlefield,
            stack=new_stack,
            active_player_idx=self.active_player_idx,
            priority_player_idx=self.priority_player_idx,
            turn_number=self.turn_number,
            step=self.step,
            next_object_id=self.next_object_id,
            log=new_log,
            rng=new_rng,
            winner_id=self.winner_id,
            is_draw=self.is_draw,
            permanent_left_battlefield_this_turn=(
                self.permanent_left_battlefield_this_turn
            ),
            spell_warped_this_turn=self.spell_warped_this_turn,
            once_per_turn_fired=set(self.once_per_turn_fired),
            delayed_triggers=[dict(d) for d in self.delayed_triggers],
            resolving_source=new_resolving_source,
            resolving_x_value=self.resolving_x_value,
            resolving_kicked=self.resolving_kicked,
            resolving_additional_cost_choice_id=(
                self.resolving_additional_cost_choice_id
            ),
            resolving_combat_damage_amount=(
                self.resolving_combat_damage_amount
            ),
            resolving_combat_damage_source_controller_id=(
                self.resolving_combat_damage_source_controller_id
            ),
            resolving_counter_amount=self.resolving_counter_amount,
            pending_end_of_combat_sacrifices=list(
                self.pending_end_of_combat_sacrifices
            ),
            players_who_created_tokens_this_turn=set(
                self.players_who_created_tokens_this_turn
            ),
            ability_resolutions_this_turn=dict(
                self.ability_resolutions_this_turn
            ),
            prevent_combat_damage_this_turn=(
                self.prevent_combat_damage_this_turn
            ),
            extra_turn_queue=list(self.extra_turn_queue),
        )
        return new_state
