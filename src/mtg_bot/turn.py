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

    # Generic "when this leaves the battlefield" triggers — fires for
    # artifacts, enchantments, and anything else with a matching
    # triggered ability. Used by Cryogen Relic ("enters or leaves →
    # draw a card").
    _fire_leaves_battlefield_triggers(state, obj)

    # Return any cards this object exiled with "until this leaves" to
    # their owner's battlefield. Applies whether the source is destroyed
    # or exiled itself.
    _release_exiled_until_leaves(state, obj.id)


def _fire_leaves_battlefield_triggers(
    state: GameState, obj: "GameObject"
) -> None:
    """Run "when this leaves the battlefield" triggers on ``obj`` after
    it's already been moved. resolving_source exposes the dearly
    departed for effects that need it. Resolves target selection via
    the controller's agent for targeted inner effects."""
    controller = state.player_by_id(obj.controller_id)
    for ability in obj.printing.triggered_abilities:
        if ability.trigger != "leaves_battlefield":
            continue
        state.log.append(
            f"{obj.printing.name}'s leaves-battlefield ability triggers"
        )
        state.resolving_source = obj
        effect = ability.effect
        targets: tuple[tuple[str, int], ...] = ()
        if effect.requires_target():
            legal = effect.legal_targets(state, obj.controller_id)
            if not legal:
                state.resolving_source = None
                state.log.append(
                    f"{obj.printing.name}'s leaves-battlefield trigger "
                    f"fizzles (no legal targets)"
                )
                continue
            if controller.agent is not None:
                chosen = controller.agent.choose_target(
                    state, obj.controller_id, legal
                )
                if chosen is not None:
                    targets = (chosen,)
        try:
            effect.resolve(state, obj.controller_id, targets)
        finally:
            state.resolving_source = None


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

    Simplification: Fires directly (no stack). The discarding player's
    id is exposed via a target ``("player", id)`` so effects like
    Entropic Battlecruiser's 1+ trigger can damage them.
    """
    for obs in list(state.battlefield):
        if obs.controller_id == discarding_player_id:
            continue
        for i, ability in enumerate(obs.printing.triggered_abilities):
            if ability.trigger != "opponent_discards_a_card":
                continue
            if not should_fire_trigger(state, obs.id, i, ability):
                continue
            state.log.append(
                f"{obs.printing.name}'s opponent-discards trigger fires"
            )
            state.resolving_source = obs
            try:
                ability.effect.resolve(
                    state, obs.controller_id,
                    (("player", discarding_player_id),),
                )
            finally:
                state.resolving_source = None


def should_fire_trigger(
    state: GameState, source_id: int, ability_index: int, ability
) -> bool:
    """True if ``ability`` on the permanent with id ``source_id`` may fire.

    Honors both ``ability.tier_threshold`` (EoE Spacecraft tier gate:
    source must have at least that many charge counters) and
    ``ability.once_per_turn`` (records fire in state.once_per_turn_fired
    to prevent a second fire this turn).
    """
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
            if not should_fire_trigger(state, other.id, i, ability):
                continue
            state.log.append(
                f"{other.printing.name}'s sacrifice-trigger fires"
            )
            state.resolving_source = other
            try:
                ability.effect.resolve(state, controller_id, ())
            finally:
                state.resolving_source = None


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
    """Tap ``obj`` and fire any of its "becomes_tapped" triggered abilities.

    If the object is already tapped, this is a no-op (no re-trigger).
    Current EoE cards using this trigger are untargeted — if a future card
    requires a target we'd add the same target-selection branch used in
    run_beginning_of_combat_triggers.
    """
    if obj.tapped:
        return
    obj.tapped = True
    for i, ability in enumerate(obj.printing.triggered_abilities):
        if ability.trigger != "becomes_tapped":
            continue
        if not should_fire_trigger(state, obj.id, i, ability):
            continue
        state.log.append(
            f"{obj.printing.name}'s becomes-tapped ability triggers"
        )
        state.resolving_source = obj
        # Handle optional targeting for becomes-tapped (Nanoform Sentinel
        # needs "another target permanent").
        effect = ability.effect
        targets: tuple[tuple[str, int], ...] = ()
        if effect.requires_target():
            controller = state.player_by_id(obj.controller_id)
            legal = effect.legal_targets(state, obj.controller_id)
            if not legal:
                state.resolving_source = None
                state.log.append(
                    f"{obj.printing.name}'s becomes-tapped trigger fizzles "
                    f"(no legal targets)"
                )
                continue
            if controller.agent is not None:
                chosen = controller.agent.choose_target(
                    state, obj.controller_id, legal
                )
                if chosen is not None:
                    targets = (chosen,)
        try:
            effect.resolve(state, obj.controller_id, targets)
        finally:
            state.resolving_source = None


def fire_landfall_triggers(state: GameState, new_land: "GameObject") -> None:
    """Fire "Landfall — whenever a land you control enters" triggers on
    permanents the new land's controller controls.

    Called from every code path that puts a land onto the battlefield
    (PlayLand, SearchLibraryForBasicLandTapped, etc.).
    """
    controller = new_land.controller_id
    # Snapshot to avoid mid-iteration surprises if a trigger ETBs something.
    for obj in list(state.battlefield):
        if obj.controller_id != controller:
            continue
        for ability in obj.printing.triggered_abilities:
            if ability.trigger != "landfall":
                continue
            state.log.append(f"{obj.printing.name}'s landfall triggers")
            state.resolving_source = obj
            try:
                ability.effect.resolve(state, obj.controller_id, ())
            finally:
                state.resolving_source = None


def _fire_dies_triggers(state: GameState, dead: "GameObject") -> None:
    """Run "dies" triggered abilities on ``dead``, then fire any
    "creature_you_control_with_counter_dies" triggers on other permanents
    the dying creature's controller controls.

    Fires directly (no stack) for consistency with other trigger events
    in this engine. Source is exposed via state.resolving_source for
    effects that need it.
    """
    for ability in dead.printing.triggered_abilities:
        if ability.trigger != "dies":
            continue
        state.log.append(f"{dead.printing.name}'s dies ability triggers")
        state.resolving_source = dead
        try:
            ability.effect.resolve(state, dead.controller_id, ())
        finally:
            state.resolving_source = None
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
                if not should_fire_trigger(state, obj.id, i, ability):
                    continue
                state.log.append(
                    f"{obj.printing.name}'s counter-creature-dies "
                    f"trigger fires"
                )
                state.resolving_source = obj
                try:
                    ability.effect.resolve(state, controller, ())
                finally:
                    state.resolving_source = None


def run_beginning_of_combat_triggers(state: GameState) -> None:
    """Fire "At the beginning of combat on your turn" triggered abilities.

    Targets are selected via the controller's agent just like ETBs. Fires
    as a turn-based action (no stack) for consistency with our other
    trigger events.
    """
    ap_id = state.active_player().id
    for obj in list(state.battlefield):
        if obj.controller_id != ap_id:
            continue
        for i, ability in enumerate(obj.printing.triggered_abilities):
            if ability.trigger != "beginning_of_combat":
                continue
            if not should_fire_trigger(state, obj.id, i, ability):
                continue
            # Target selection mirrors _trigger_etb_abilities.
            targets: tuple[tuple[str, int], ...] = ()
            effect = ability.effect
            if effect.requires_target():
                legal = effect.legal_targets(state, ap_id)
                if not legal:
                    state.log.append(
                        f"{obj.printing.name}'s beginning-of-combat "
                        f"trigger fizzles (no legal targets)"
                    )
                    continue
                controller = state.player_by_id(ap_id)
                chosen = controller.agent.choose_target(state, ap_id, legal)
                if chosen is None:
                    continue
                targets = (chosen,)
            state.log.append(
                f"{obj.printing.name}'s beginning-of-combat ability triggers"
            )
            state.resolving_source = obj
            try:
                effect.resolve(state, ap_id, targets)
            finally:
                state.resolving_source = None


def run_delayed_end_step_triggers(state: GameState) -> None:
    """Fire any delayed triggers scheduled for this end step.

    Scheduled by effects like CreateLanderAndScheduleSacrificeNextEndStep
    (Kav Landseeker). Entries are data dicts so the state stays
    pickle-friendly. Currently supported actions: "sacrifice" — sacrifice
    the target object if it's still on the battlefield.
    """
    ap_id = state.active_player().id
    remaining: list[dict] = []
    for entry in state.delayed_triggers:
        if (
            entry["fire_at_turn"] == state.turn_number
            and entry["controller_id"] == ap_id
        ):
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
        else:
            remaining.append(entry)
    state.delayed_triggers = remaining


def run_beginning_of_end_step_triggers(state: GameState) -> None:
    """Fire "At the beginning of your end step, ..." triggered abilities on
    permanents controlled by the active player. EoE "Void —" abilities carry
    a requires_void flag and only fire when is_void_active(state).

    Simplified model: triggers fire directly (no stack) — functionally
    equivalent in our current rules set where nothing can counter a
    triggered ability.
    """
    from mtg_bot.game import is_void_active

    ap_id = state.active_player().id
    # Snapshot the battlefield so mid-iteration effects don't confuse us.
    candidates = list(state.battlefield)
    void_is_active = is_void_active(state)
    ap = state.player_by_id(ap_id)
    for obj in candidates:
        if obj.controller_id != ap_id:
            continue
        for ability in obj.printing.triggered_abilities:
            if ability.trigger != "beginning_of_end_step":
                continue
            if ability.requires_void and not void_is_active:
                continue
            state.log.append(
                f"{obj.printing.name}'s end-step ability triggers"
            )
            state.resolving_source = obj
            # Target selection (mirrors _trigger_etb_abilities).
            effect = ability.effect
            targets: tuple[tuple[str, int], ...] = ()
            if effect.requires_target():
                legal = effect.legal_targets(state, ap_id)
                if not legal:
                    state.resolving_source = None
                    state.log.append(
                        f"{obj.printing.name}'s end-step trigger fizzles "
                        f"(no legal targets)"
                    )
                    continue
                if ap.agent is not None:
                    chosen = ap.agent.choose_target(state, ap_id, legal)
                    if chosen is not None:
                        targets = (chosen,)
            try:
                effect.resolve(state, obj.controller_id, targets)
            finally:
                state.resolving_source = None


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
        obj.temp_power_bonus = 0
        obj.temp_toughness_bonus = 0
        obj.temp_keywords = frozenset()
        # Revert "gain control until end of turn" effects.
        if obj.temp_original_controller_id is not None:
            obj.controller_id = obj.temp_original_controller_id
            obj.temp_original_controller_id = None
    # Reset turn-scoped Void tracking so next turn starts fresh.
    state.permanent_left_battlefield_this_turn = False
    state.spell_warped_this_turn = False
    # Reset per-player spell counters for "your Nth spell" triggers.
    for p in state.players:
        p.spells_cast_this_turn = 0
        p.attacked_with_spacecraft_this_turn = False
    # Reset once-per-turn trigger tracking.
    state.once_per_turn_fired.clear()


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
