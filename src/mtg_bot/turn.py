"""Turn structure: steps, turn-based actions, and state-based actions."""

from __future__ import annotations

from enum import Enum

from mtg_bot.game import (
    GameState, Zone, effective_keywords, effective_toughness, is_creature_now,
)


class Step(Enum):
    UNTAP = "untap"
    UPKEEP = "upkeep"
    DRAW = "draw"
    PRECOMBAT_MAIN = "precombat_main"
    BEGINNING_OF_COMBAT = "beginning_of_combat"
    DECLARE_ATTACKERS = "declare_attackers"
    DECLARE_BLOCKERS = "declare_blockers"
    COMBAT_DAMAGE = "combat_damage"
    END_OF_COMBAT = "end_of_combat"
    POSTCOMBAT_MAIN = "postcombat_main"
    END = "end"
    CLEANUP = "cleanup"


STEP_ORDER: tuple[Step, ...] = (
    Step.UNTAP, Step.UPKEEP, Step.DRAW,
    Step.PRECOMBAT_MAIN,
    Step.BEGINNING_OF_COMBAT, Step.DECLARE_ATTACKERS, Step.DECLARE_BLOCKERS,
    Step.COMBAT_DAMAGE, Step.END_OF_COMBAT,
    Step.POSTCOMBAT_MAIN,
    Step.END, Step.CLEANUP,
)

MAIN_STEPS: frozenset[Step] = frozenset({Step.PRECOMBAT_MAIN, Step.POSTCOMBAT_MAIN})
COMBAT_STEPS: frozenset[Step] = frozenset({
    Step.BEGINNING_OF_COMBAT, Step.DECLARE_ATTACKERS, Step.DECLARE_BLOCKERS,
    Step.COMBAT_DAMAGE, Step.END_OF_COMBAT,
})
# Untap and cleanup don't normally grant priority.
STEPS_WITH_PRIORITY: frozenset[Step] = frozenset(set(STEP_ORDER) - {Step.UNTAP, Step.CLEANUP})


def run_untap_step(state: GameState) -> None:
    ap = state.active_player()
    ap.lands_played_this_turn = 0
    # Phasing: "until its controller's next turn." At the start of the
    # phased creature's controller's untap step, phase it (and anything
    # attached to it) back in. Matches Robe of Stars' Astral Projection.
    for obj in state.battlefield:
        if obj.phased_out and obj.controller_id == ap.id:
            obj.phased_out = False
            state.log.append(f"{obj.printing.name} phases in")
    # Dominion Bracelet: if this player's next turn was scheduled for
    # an agent override, install it now (saving the original so
    # cleanup can revert).
    if ap.scheduled_agent_override is not None:
        ap.agent_override_saved = ap.agent
        ap.agent = ap.scheduled_agent_override
        ap.scheduled_agent_override = None
        state.log.append(
            f"P{ap.id}'s turn now controlled by "
            f"P{ap.scheduled_agent_override_by}"
        )
    # Pre-compute ids of permanents whose untap is prevented by an
    # attached aura/equipment with attached_prevents_untap=True
    # (Tractor Beam's "doesn't untap during its controller's untap
    # step").
    no_untap_ids = {
        att.attached_to for att in state.battlefield
        if att.attached_to is not None
        and att.printing.attached_prevents_untap
    }
    for obj in state.battlefield:
        if obj.controller_id == ap.id:
            # Stun counters: instead of untapping, remove one counter.
            if obj.stun_counters > 0:
                obj.stun_counters -= 1
                state.log.append(
                    f"{obj.printing.name} stays tapped (stun counter "
                    f"removed; {obj.stun_counters} remaining)"
                )
                continue
            if obj.id in no_untap_ids:
                state.log.append(
                    f"{obj.printing.name} stays tapped (attached-"
                    f"prevents-untap effect)"
                )
                continue
            obj.tapped = False
            obj.summoning_sick = False


def draw_card(state: GameState, player_id: int) -> None:
    p = state.player_by_id(player_id)
    if not p.library:
        p.has_lost = True
        p.lost_reason = "drew from empty library"
        return
    top = p.library.pop(0)
    top.zone = Zone.HAND
    p.hand.append(top)


def run_draw_step(state: GameState) -> None:
    draw_card(state, state.active_player().id)


def move_off_battlefield(
    state: GameState, obj: "GameObject", destination: str = "graveyard"
) -> None:
    """Remove ``obj`` from the battlefield and place it in ``destination``.

    ``destination`` is ``"graveyard"`` or ``"exile"``. Tokens cease to exist
    per rule 704.5d regardless of destination. Combat state (damage, tapped,
    attacking, blocking) is cleared.

    If the object was a creature (or a stationed Spacecraft) and
    ``destination`` is ``"graveyard"``, its "when this creature dies"
    triggered abilities fire after the zone change.

    Note: Indestructible is NOT checked here — the caller (destroy effect
    or SBA) is responsible for that gate. Exile bypasses indestructible
    normally.
    """
    if obj not in state.battlefield:
        return
    was_creature = is_creature_now(obj)
    # Mark Void state: any non-land permanent leaving the battlefield this
    # turn (including tokens ceasing to exist) enables Void triggers.
    if not obj.printing.is_land:
        state.permanent_left_battlefield_this_turn = True
    # Any attachment on this object: Equipment falls off (stays on
    # battlefield, attached_to cleared); Auras are sent to their
    # owners' graveyards.
    auras_to_bury: list = []
    for att in state.battlefield:
        if att.attached_to != obj.id:
            continue
        if att.printing.is_aura:
            auras_to_bury.append(att)
        else:
            att.attached_to = None
    for aura in auras_to_bury:
        state.log.append(
            f"{aura.printing.name} falls off and is buried"
        )
        move_off_battlefield(state, aura, destination="graveyard")
    state.battlefield.remove(obj)
    obj.damage = 0
    obj.marked_lethal = False
    obj.damaged_this_turn = False
    obj.tapped = False
    obj.attacking = False
    obj.blocking = None
    obj.blocked_by = []
    # If the departing permanent itself was Equipment, clear its
    # attachment state.
    obj.attached_to = None
    # If a warp-cast creature leaves the battlefield by any means (death,
    # exile, etc.) its pending end-step exile trigger no longer applies.
    obj.cast_via_warp = False
    if obj.printing.is_token:
        state.log.append(f"{obj.printing.name} token ceases to exist")
    elif destination == "graveyard":
        obj.zone = Zone.GRAVEYARD
        state.player_by_id(obj.owner_id).graveyard.append(obj)
    elif destination == "exile":
        obj.zone = Zone.EXILE
        state.player_by_id(obj.owner_id).exile.append(obj)
    else:
        raise ValueError(f"unknown destination: {destination!r}")

    # Fire "when this creature dies" triggers if applicable.
    if destination == "graveyard" and was_creature:
        _fire_dies_triggers(state, obj)

    # Observer trigger: "whenever a creature or artifact you control
    # dies" — fires on OTHER permanents the dying object's controller
    # controls (includes the source itself per oracle text — "this
    # creature or another creature or artifact you control dies").
    if destination == "graveyard" and (was_creature or obj.printing.is_artifact):
        _fire_your_creature_or_artifact_dies_triggers(state, obj)

    # Observer trigger: "whenever another creature you control dies or
    # is put into exile" — Syr Vondam, Sunstar Exemplar. Fires on both
    # graveyard and exile destinations, creatures only, excluding the
    # dying object (the "another" qualifier).
    if was_creature and destination in ("graveyard", "exile"):
        _fire_another_creature_dies_or_exiled_triggers(state, obj)

    # Generic "when this leaves the battlefield" triggers — fires for
    # artifacts, enchantments, and anything else with a matching
    # triggered ability. Used by Cryogen Relic ("enters or leaves →
    # draw a card").
    _fire_leaves_battlefield_triggers(state, obj)

    # Return any cards this object exiled with "until this leaves" to
    # their owner's battlefield. Applies whether the source is destroyed
    # or exiled itself.
    _release_exiled_until_leaves(state, obj.id)


def _fire_your_creature_or_artifact_dies_triggers(
    state: GameState, dead: "GameObject"
) -> None:
    """Push "whenever this or another creature or artifact you control
    dies" triggers on all permanents the dead object's controller
    controls onto the stack. The source of this observer trigger
    INCLUDES the dearly-departed (Susurian Voidborn: "this creature or
    another ... you control dies") — since ``dead`` has already been
    moved off the battlefield by the caller, we explicitly include it
    as a candidate observer so its own trigger fires too.
    """
    from mtg_bot.actions import push_triggered_ability

    controller_id = dead.controller_id
    candidates: list = [dead] + [
        o for o in state.battlefield if o.controller_id == controller_id
    ]
    for obs in candidates:
        if obs is not dead and obs.controller_id != controller_id:
            continue
        for i, ability in enumerate(obs.printing.triggered_abilities):
            if ability.trigger != "your_creature_or_artifact_dies":
                continue
            push_triggered_ability(
                state,
                source=obs,
                ability=ability,
                ability_index=i,
                controller_id=controller_id,
                label="creature-or-artifact-dies",
            )


def fire_counters_added_to_your_creature_triggers(
    state: GameState, controller_id: int, amount: int
) -> None:
    """Push "whenever you put one or more +1/+1 counters on a creature
    you control, ..." observer triggers onto the stack. ``amount`` is
    the effective count added (post-doubling). The amount is carried in
    the StackItem and exposed at resolve time via
    ``state.resolving_counter_amount`` for "you may draw that many"
    riders (Terrasymbiosis).
    """
    from mtg_bot.actions import push_triggered_ability

    for obs in list(state.battlefield):
        if obs.controller_id != controller_id:
            continue
        for i, ability in enumerate(obs.printing.triggered_abilities):
            if ability.trigger != "counters_added_to_your_creature":
                continue
            push_triggered_ability(
                state,
                source=obs,
                ability=ability,
                ability_index=i,
                controller_id=controller_id,
                label=f"counters-added (amount {amount})",
                counter_amount=amount,
            )


def _fire_another_creature_dies_or_exiled_triggers(
    state: GameState, dead: "GameObject"
) -> None:
    """Push "whenever another creature you control dies or is put into
    exile" observer triggers onto the stack. Iterates the dying
    creature's controller's battlefield; the dead object is already
    moved off so it's naturally excluded (matches "another").
    """
    from mtg_bot.actions import push_triggered_ability

    controller_id = dead.controller_id
    for obs in list(state.battlefield):
        if obs.controller_id != controller_id:
            continue
        for i, ability in enumerate(obs.printing.triggered_abilities):
            if ability.trigger != "another_creature_you_control_dies_or_exiled":
                continue
            push_triggered_ability(
                state,
                source=obs,
                ability=ability,
                ability_index=i,
                controller_id=controller_id,
                label="another-creature-dies-or-exiled",
            )


def _fire_leaves_battlefield_triggers(
    state: GameState, obj: "GameObject"
) -> None:
    """Push "when this leaves the battlefield" triggers on ``obj`` onto
    the stack after it's already been moved. resolving_source exposes
    the dearly departed during resolution.
    """
    from mtg_bot.actions import push_triggered_ability

    for i, ability in enumerate(obj.printing.triggered_abilities):
        if ability.trigger != "leaves_battlefield":
            continue
        push_triggered_ability(
            state,
            source=obj,
            ability=ability,
            ability_index=i,
            controller_id=obj.controller_id,
            label="leaves-battlefield",
        )


def _release_exiled_until_leaves(state: GameState, source_id: int) -> None:
    """Move any objects from exile back to the battlefield under their
    owner's control if they were exiled by the given source (Oblivion-
    Ring-style). Returns them as fresh ETBs so ETB triggers fire again.
    """
    from mtg_bot.actions import put_into_battlefield

    for p in state.players:
        released = [c for c in p.exile if c.exiled_by_source == source_id]
        for c in released:
            p.exile.remove(c)
            c.exiled_by_source = None
            state.log.append(
                f"{c.printing.name} returns from exile to "
                f"P{p.id}'s battlefield"
            )
            put_into_battlefield(state, c, p.id)


def fire_opponent_discards_triggers(
    state: GameState, discarding_player_id: int
) -> None:
    """Fire observer triggers on permanents controlled by players OTHER
    than ``discarding_player_id`` whose trigger type is
    ``"opponent_discards_a_card"``. Called after any single-card
    discard event.

    Triggers go on the stack via push_triggered_ability with the
    discarding player exposed as ``("player", id)`` in targets so
    effects like Entropic Battlecruiser's 1+ trigger can damage them.
    """
    from mtg_bot.actions import push_triggered_ability

    for obs in list(state.battlefield):
        if obs.controller_id == discarding_player_id:
            continue
        for i, ability in enumerate(obs.printing.triggered_abilities):
            if ability.trigger != "opponent_discards_a_card":
                continue
            push_triggered_ability(
                state,
                source=obs,
                ability=ability,
                ability_index=i,
                controller_id=obs.controller_id,
                label="opponent-discards",
                fixed_targets=(("player", discarding_player_id),),
            )


def should_fire_trigger(
    state: GameState, source_id: int, ability_index: int, ability
) -> bool:
    """True if ``ability`` on the permanent with id ``source_id`` may fire.

    Honors three independent gates:

    - ``ability.requires_void``: EoE Void rider — only fires while
      ``is_void_active(state)`` (a non-land permanent left the
      battlefield this turn or a spell was warped this turn).
    - ``ability.tier_threshold``: EoE Spacecraft tier gate — source must
      have at least that many charge counters.
    - ``ability.once_per_turn``: records the fire in
      ``state.once_per_turn_fired`` so the trigger fires at most once
      per turn. Eager record matches MTG semantics: the ability has
      "triggered" the moment its event happens, even if it later fails
      to find legal targets and fizzles off the stack.
    """
    from mtg_bot.game import is_void_active

    if getattr(ability, "requires_void", False) and not is_void_active(state):
        return False
    tier = getattr(ability, "tier_threshold", 0)
    if tier > 0:
        source = next((o for o in state.battlefield if o.id == source_id), None)
        if source is None or source.charge_counters < tier:
            return False
    if not getattr(ability, "once_per_turn", False):
        return True
    key = (source_id, ability_index)
    if key in state.once_per_turn_fired:
        return False
    state.once_per_turn_fired.add(key)
    return True


def sacrifice(state: GameState, obj: "GameObject") -> None:
    """Sacrifice ``obj``: move it to its owner's graveyard and fire any
    "whenever you sacrifice another creature or artifact" triggers on
    other permanents the sacrificed object's controller controls.

    Sacrifice bypasses indestructible (MTG rule 701.16a — sacrifice is
    not a "destroy" effect).
    """
    from mtg_bot.actions import push_triggered_ability

    controller_id = obj.controller_id
    was_creature = obj.printing.is_creature
    was_artifact = obj.printing.is_artifact
    move_off_battlefield(state, obj, destination="graveyard")
    if not (was_creature or was_artifact):
        return
    for other in list(state.battlefield):
        if other.id == obj.id:
            continue
        if other.controller_id != controller_id:
            continue
        for i, ability in enumerate(other.printing.triggered_abilities):
            if ability.trigger != "sacrifice_creature_or_artifact":
                continue
            push_triggered_ability(
                state,
                source=other,
                ability=ability,
                ability_index=i,
                controller_id=controller_id,
                label="sacrifice",
            )


def destroy(state: GameState, obj: "GameObject") -> bool:
    """Attempt to destroy ``obj``. Respects indestructible — the source is
    unaffected and True is returned only if the permanent actually moved
    to the graveyard.

    This is the entry point for EFFECT-based "destroy target X" clauses.
    State-based-action lethal damage uses its own indestructible gate in
    state_based_actions; sacrifice ignores indestructible entirely (it
    calls move_off_battlefield directly).
    """
    kws = effective_keywords(state, obj)
    if "indestructible" in kws:
        state.log.append(
            f"{obj.printing.name} is indestructible — destroy fizzles"
        )
        return False
    move_off_battlefield(state, obj, destination="graveyard")
    return True


def tap_permanent(state: GameState, obj: "GameObject") -> None:
    """Tap ``obj`` and push any of its "becomes_tapped" triggered abilities
    onto the stack.

    Also pushes "enchanted_permanent_becomes_tapped" triggers on any Aura
    attached to ``obj`` — this is how Cryoshatter ("when enchanted
    creature becomes tapped, destroy it") works.

    If the object is already tapped, this is a no-op (no re-trigger).
    """
    from mtg_bot.actions import push_triggered_ability

    if obj.tapped:
        return
    obj.tapped = True
    for i, ability in enumerate(obj.printing.triggered_abilities):
        if ability.trigger != "becomes_tapped":
            continue
        push_triggered_ability(
            state,
            source=obj,
            ability=ability,
            ability_index=i,
            controller_id=obj.controller_id,
            label="becomes-tapped",
        )
    # Auras attached to ``obj`` whose oracle text is
    # "whenever enchanted permanent becomes tapped, ..." (Cryoshatter).
    # Snapshot to avoid mid-iteration surprises.
    for aura in list(state.battlefield):
        if not aura.printing.is_aura:
            continue
        if aura.attached_to != obj.id:
            continue
        for i, ability in enumerate(aura.printing.triggered_abilities):
            if ability.trigger != "enchanted_permanent_becomes_tapped":
                continue
            push_triggered_ability(
                state,
                source=aura,
                ability=ability,
                ability_index=i,
                controller_id=aura.controller_id,
                label="enchanted-permanent-becomes-tapped",
            )


def fire_landfall_triggers(state: GameState, new_land: "GameObject") -> None:
    """Push "Landfall — whenever a land you control enters" triggers onto
    the stack for permanents the new land's controller controls.

    Called from every code path that puts a land onto the battlefield
    (PlayLand, SearchLibraryForBasicLandTapped, etc.). Honors
    etb_trigger_multiplier by pushing N times.
    """
    from mtg_bot.actions import push_triggered_ability
    from mtg_bot.game import etb_trigger_multiplier

    controller = new_land.controller_id
    firings = etb_trigger_multiplier(state, controller)
    # Snapshot to avoid mid-iteration surprises if a trigger ETBs something.
    for obj in list(state.battlefield):
        if obj.controller_id != controller:
            continue
        for i, ability in enumerate(obj.printing.triggered_abilities):
            if ability.trigger != "landfall":
                continue
            for _ in range(firings):
                push_triggered_ability(
                    state,
                    source=obj,
                    ability=ability,
                    ability_index=i,
                    controller_id=controller,
                    label="landfall",
                )


def fire_opponent_plays_land_triggers(
    state: GameState, land_controller_id: int,
) -> None:
    """Fire "Whenever an opponent plays a land" triggers on every
    non-controller's permanents.

    Called from ``actions.play_land`` only (NOT from effects that
    merely put a land onto the battlefield — "plays a land" is the
    land-drop action per 305.1). For each opposing player we scan
    their permanents and push every matching trigger onto the stack
    under that opponent's control (so Burgeoning's "you may put a land
    from your hand onto the battlefield" resolves under the enchantment's
    controller).
    """
    from mtg_bot.actions import push_triggered_ability

    for p in state.players:
        if p.id == land_controller_id:
            continue
        for obj in list(state.battlefield):
            if obj.controller_id != p.id:
                continue
            for i, ability in enumerate(obj.printing.triggered_abilities):
                if ability.trigger != "opponent_plays_land":
                    continue
                push_triggered_ability(
                    state,
                    source=obj,
                    ability=ability,
                    ability_index=i,
                    controller_id=p.id,
                    label="opponent-plays-land",
                )


def _fire_dies_triggers(state: GameState, dead: "GameObject") -> None:
    """Push "dies" triggered abilities of ``dead`` onto the stack, then
    push any "creature_you_control_with_counter_dies" triggers on other
    permanents the dying creature's controller controls.

    The dead object is no longer on the battlefield by the time this
    runs; ``state.resolving_source`` will point to it during resolution
    so effects can read its former state.
    """
    from mtg_bot.actions import push_triggered_ability

    for i, ability in enumerate(dead.printing.triggered_abilities):
        if ability.trigger != "dies":
            continue
        push_triggered_ability(
            state,
            source=dead,
            ability=ability,
            ability_index=i,
            controller_id=dead.controller_id,
            label="dies",
        )
    # "Whenever a creature you control with a +1/+1 counter on it dies" —
    # only fires if the dying creature actually had a +1/+1 counter.
    if dead.plus_one_counters > 0:
        controller = dead.controller_id
        for obj in list(state.battlefield):
            if obj.controller_id != controller:
                continue
            for i, ability in enumerate(obj.printing.triggered_abilities):
                if ability.trigger != "creature_you_control_with_counter_dies":
                    continue
                push_triggered_ability(
                    state,
                    source=obj,
                    ability=ability,
                    ability_index=i,
                    controller_id=controller,
                    label="counter-creature-dies",
                )


def run_beginning_of_upkeep_triggers(state: GameState) -> None:
    """Push "At the beginning of your upkeep" triggered abilities onto
    the stack for permanents the active player controls."""
    from mtg_bot.actions import push_triggered_ability

    ap_id = state.active_player().id
    for obj in list(state.battlefield):
        if obj.controller_id != ap_id:
            continue
        for i, ability in enumerate(obj.printing.triggered_abilities):
            if ability.trigger != "beginning_of_upkeep":
                continue
            push_triggered_ability(
                state,
                source=obj,
                ability=ability,
                ability_index=i,
                controller_id=ap_id,
                label="beginning-of-upkeep",
            )


def run_beginning_of_combat_triggers(state: GameState) -> None:
    """Push "At the beginning of combat on your turn" triggered abilities
    onto the stack for permanents the active player controls."""
    from mtg_bot.actions import push_triggered_ability

    ap_id = state.active_player().id
    for obj in list(state.battlefield):
        if obj.controller_id != ap_id:
            continue
        for i, ability in enumerate(obj.printing.triggered_abilities):
            if ability.trigger != "beginning_of_combat":
                continue
            push_triggered_ability(
                state,
                source=obj,
                ability=ability,
                ability_index=i,
                controller_id=ap_id,
                label="beginning-of-combat",
            )


def run_delayed_end_step_triggers(state: GameState) -> None:
    """Fire any delayed triggers scheduled for this end step.

    Two entry shapes are supported:

    1. Hardcoded string-``action`` entries (legacy): currently
       ``"sacrifice"`` (Kav Landseeker's scheduled sac) and
       ``"remove_charge_counters"`` (Systems Override's 10-counter
       reset). Each specifies a ``target_id`` pointing to a battlefield
       permanent.

    2. Arbitrary ``effect`` entries: the entry carries an Effect
       instance, resolved with optional ``source_id`` (sets
       ``state.resolving_source`` during resolution). Used by
       Mystifying Maze's "return the exiled creature at the next end
       step tapped" scheduling. Effect instances are frozen dataclasses
       so the state stays pickle-friendly.

    Both shapes require ``fire_at_turn`` to match the current turn
    number and ``controller_id`` to match the active player.
    """
    ap_id = state.active_player().id
    remaining: list[dict] = []
    for entry in state.delayed_triggers:
        fires_now = (
            entry["fire_at_turn"] == state.turn_number
            and entry["controller_id"] == ap_id
        )
        if not fires_now:
            remaining.append(entry)
            continue

        if "effect" in entry:
            effect = entry["effect"]
            source_id = entry.get("source_id")
            source = (
                next(
                    (o for o in state.battlefield if o.id == source_id),
                    None,
                )
                if source_id is not None else None
            )
            prior = state.resolving_source
            state.resolving_source = source
            try:
                effect.resolve(state, entry["controller_id"], ())
            finally:
                state.resolving_source = prior
            state.log.append(
                f"delayed effect fires: {effect.describe()}"
            )
            continue

        # Legacy string-action path.
        target = next(
            (o for o in state.battlefield
             if o.id == entry["target_id"]),
            None,
        )
        if target is not None and entry["action"] == "sacrifice":
            state.log.append(
                f"delayed trigger: P{ap_id} sacrifices "
                f"{target.printing.name}"
            )
            sacrifice(state, target)
        elif (
            target is not None
            and entry["action"] == "remove_charge_counters"
        ):
            amount = entry.get("amount", 1)
            target.charge_counters = max(
                0, target.charge_counters - amount
            )
            state.log.append(
                f"delayed trigger: remove {amount} charge counters "
                f"from {target.printing.name} "
                f"(now {target.charge_counters})"
            )
        # Even if target is gone, we're done with this entry.
    state.delayed_triggers = remaining


def run_beginning_of_end_step_triggers(state: GameState) -> None:
    """Push end-step triggers for the current end step onto the stack.

    Handles two trigger types:
    - ``beginning_of_end_step`` — fires only on the active player's
      end step for permanents they control (standard oracle "At the
      beginning of your end step").
    - ``beginning_of_each_end_step`` — fires on every player's end
      step regardless of which player controls the source (Ragost's
      "At the beginning of each end step, if you gained life this
      turn, untap Ragost").
    """
    from mtg_bot.actions import push_triggered_ability

    ap_id = state.active_player().id
    candidates = list(state.battlefield)
    for obj in candidates:
        for i, ability in enumerate(obj.printing.triggered_abilities):
            is_each = ability.trigger == "beginning_of_each_end_step"
            is_yours = (
                ability.trigger == "beginning_of_end_step"
                and obj.controller_id == ap_id
            )
            if not (is_each or is_yours):
                continue
            # Each-end-step triggers resolve under the SOURCE's
            # controller, not the active player. Standard end-step
            # triggers resolve under the active player.
            ctrl_id = obj.controller_id if is_each else ap_id
            push_triggered_ability(
                state,
                source=obj,
                ability=ability,
                ability_index=i,
                controller_id=ctrl_id,
                label="end-step",
            )


def run_end_step_warp_exile(state: GameState) -> None:
    """At the beginning of the end step, exile every creature that was cast
    via its warp cost. The card moves to its owner's exile zone and is marked
    ``warped`` so it can be re-cast from exile at its normal cost later.

    Simplified model for Stage 3: warp triggers do not go on the stack — the
    exile is applied as a turn-based action. Functionally equivalent while
    there's nothing in the engine that could counter a triggered ability.
    """
    to_warp = [o for o in state.battlefield if o.cast_via_warp]
    for obj in to_warp:
        state.log.append(f"{obj.printing.name} is warp-exiled")
        move_off_battlefield(state, obj, destination="exile")
        # move_off_battlefield cleared cast_via_warp and (for non-tokens)
        # placed obj in its owner's exile. Tokens shouldn't end up with
        # cast_via_warp set — tokens aren't cast — but defend anyway.
        if not obj.printing.is_token:
            obj.warped = True


def run_cleanup_step(state: GameState) -> None:
    ap = state.active_player()
    while len(ap.hand) > 7:
        card = ap.hand.pop()
        card.zone = Zone.GRAVEYARD
        ap.graveyard.append(card)
    for obj in state.battlefield:
        obj.damage = 0
        obj.marked_lethal = False
        obj.damaged_this_turn = False
        obj.temp_power_bonus = 0
        obj.temp_toughness_bonus = 0
        obj.temp_keywords = frozenset()
        obj.temp_unblockable = False
        obj.temp_base_pt_override = None
        obj.temp_is_creature = False
        # Regenerate shield: unconsumed shields wear off at cleanup.
        obj.regeneration_shield = False
        # Revert "gain control until end of turn" effects.
        if obj.temp_original_controller_id is not None:
            obj.controller_id = obj.temp_original_controller_id
            obj.temp_original_controller_id = None
    # Expire impulse-cast flags on exiled cards — "may play this
    # turn" lasts only until the end of the turn.
    for p in state.players:
        for c in p.exile:
            c.playable_from_exile_this_turn = False
    # Empty each player's mana pool. MTG's real rule empties at end of
    # each step/phase; our simplified engine holds mana across phases
    # within a turn and clears at cleanup.
    for p in state.players:
        if p.mana_pool:
            state.log.append(
                f"P{p.id}'s mana pool empties "
                f"({len(p.mana_pool)} coin(s) lost)"
            )
            p.mana_pool.clear()
    # Reset first-time-tokens-created gate (Moonlit Meditation).
    state.players_who_created_tokens_this_turn.clear()
    # Reset turn-scoped Void tracking so next turn starts fresh.
    state.permanent_left_battlefield_this_turn = False
    state.spell_warped_this_turn = False
    # Darkness-style combat-damage prevention expires at end of turn.
    state.prevent_combat_damage_this_turn = False
    # Reset per-player spell counters for "your Nth spell" triggers.
    for p in state.players:
        p.spells_cast_this_turn = 0
        p.noncreature_spells_cast_this_turn = 0
        p.attacked_with_spacecraft_this_turn = False
        p.life_gained_this_turn = 0
        # Revert Dominion Bracelet agent override (applied at untap).
        if p.agent_override_saved is not None:
            state.log.append(
                f"P{p.id}'s agent override expires"
            )
            p.agent = p.agent_override_saved
            p.agent_override_saved = None
            p.scheduled_agent_override_by = None
    # Reset once-per-turn trigger tracking.
    state.once_per_turn_fired.clear()
    # Reset per-turn ability-resolution counters.
    state.ability_resolutions_this_turn.clear()


def state_based_actions(state: GameState) -> bool:
    """Apply state-based actions. Returns True if any changes were made."""
    changed = False

    for p in state.players:
        if not p.has_lost and p.life <= 0:
            p.has_lost = True
            p.lost_reason = "life total <= 0"
            changed = True
        if not p.has_lost and p.poison_counters >= 10:
            p.has_lost = True
            p.lost_reason = "10+ poison counters"
            changed = True

    # Planeswalker SBA (rule 704.5i): a planeswalker with 0 loyalty
    # counters is put into its owner's graveyard.
    planeswalkers_to_bury: list = []
    for obj in state.battlefield:
        if obj.printing.is_planeswalker and obj.loyalty_counters <= 0:
            planeswalkers_to_bury.append(obj)
    for pw in planeswalkers_to_bury:
        state.log.append(
            f"{pw.printing.name} has 0 loyalty and is put into "
            f"graveyard"
        )
        move_off_battlefield(state, pw, destination="graveyard")
        changed = True

    destroyed = []
    for obj in state.battlefield:
        if not is_creature_now(obj):
            continue
        tough = effective_toughness(state, obj)
        kws = effective_keywords(state, obj)
        # Indestructible: lethal damage and "destroy" effects don't kill it,
        # but toughness <= 0 still does (state-based action, rule 704.5f).
        if tough <= 0:
            destroyed.append(obj)
        elif "indestructible" in kws:
            continue
        elif obj.damage >= tough or obj.marked_lethal:
            destroyed.append(obj)

    for obj in destroyed:
        # Regenerate (Swarmyard et al.): if the creature has a
        # regeneration shield, the destruction is replaced — remove
        # all damage, tap, remove from combat, consume the shield.
        # Rule 701.15: toughness-based destruction (tough <= 0) is
        # NOT regeneratable; only lethal-damage / marked_lethal /
        # "destroy" paths are. Our SBA path here lumps those together;
        # we gate on not-zero-toughness to match the rule.
        tough = effective_toughness(state, obj)
        if obj.regeneration_shield and tough > 0:
            obj.damage = 0
            obj.marked_lethal = False
            obj.tapped = True
            obj.attacking = False
            obj.blocking = None
            obj.blocked_by = []
            obj.regeneration_shield = False
            state.log.append(
                f"{obj.printing.name} regenerates "
                "(tapped, damage cleared)"
            )
            changed = True
            continue
        # Log before moving (move_off_battlefield logs for tokens too).
        if not obj.printing.is_token:
            state.log.append(f"{obj.printing.name} destroyed (lethal damage)")
        move_off_battlefield(state, obj, destination="graveyard")
        changed = True

    alive = [p for p in state.players if not p.has_lost]
    if len(alive) == 0 and not state.is_draw:
        state.is_draw = True
        changed = True
    elif (
        len(alive) == 1
        and state.winner_id is None
        and len(state.players) > 1
    ):
        state.winner_id = alive[0].id
        changed = True

    return changed
