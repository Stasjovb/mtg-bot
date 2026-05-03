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
    # "Until your next turn" expiry: drop every continuous-effect
    # registry entry tagged ``expires_at="controller_untap"`` whose
    # ``expires_at_player_id`` is this active player. Matches Mouth of
    # the Storm's "creatures your opponents control get -3/-0 until
    # your next turn." — the bonus survives the cleanup step of the
    # casting turn AND the opponent's full turn, then clears right at
    # the start of the source-controller's next turn. Both the layer-7
    # ``pump_pt`` P/T contributions and layer-6 ``grant_keyword`` grants
    # under this lifetime are dropped here; the legacy
    # ``extended_temp_*`` mirror fields they previously fed have been
    # retired.
    state.expire_continuous_effects("controller_untap", player_id=ap.id)
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


def draw_n_cards(state: GameState, player_id: int, n: int) -> int:
    """Resolve a "draw N cards" event for ``player_id`` with replacement
    effects applied. Returns the effective count actually drawn.

    Use this whenever a single MTG event would draw one or more cards
    (the draw step, "draw a card" ETB triggers, "draw N" spells like
    Decode Transmissions). The Quantum-Riddler-style "draw that many
    plus one instead" replacement adjusts the count once per event,
    not once per card drawn — loop callers must use this helper
    rather than calling ``draw_card`` themselves N times.
    """
    from mtg_bot.game import effective_draw_count

    effective = effective_draw_count(state, player_id, n)
    for _ in range(effective):
        draw_card(state, player_id)
    return effective


def run_draw_step(state: GameState) -> None:
    draw_n_cards(state, state.active_player().id, 1)


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
    # Layer-2 control-grant reversion: drop every continuous-effect
    # entry sourced by THIS leaving object, then refresh the
    # ``controller_id`` cache on each affected target via
    # ``effective_controller``. When a target's last control_change
    # entry goes away, also clear its baseline-snapshot
    # ``controller_id_before_any_aura_swap`` so a future aura grant
    # captures a fresh baseline. Doing this BEFORE the cascading
    # aura-detach + bury logic keeps any downstream observers
    # reading the post-revert controller.
    from mtg_bot.game import effective_controller

    # ``only_static=True`` so UEOT grants this object made (e.g.,
    # Perigee Beckoner's granted dies-rider on itself) survive into
    # the dies-trigger fire below; cleanup wipes them at end of
    # turn.
    dropped = state.remove_continuous_effects_from_source(
        obj.id, only_static=True,
    )
    revert_targets: set[int] = {
        ce.target_id for ce in dropped
        if ce.layer == 2
        and ce.kind == "control_change"
        and ce.target_id is not None
    }
    for tid in revert_targets:
        target = next(
            (o for o in state.battlefield if o.id == tid), None
        )
        if target is None:
            continue
        new_controller = effective_controller(state, target)
        # If no more control_change entries remain for this target,
        # clear the captured baseline so a future aura grant starts
        # fresh.
        any_remaining = any(
            ce.layer == 2
            and ce.kind == "control_change"
            and ce.target_id == target.id
            for ce in state.continuous_effects
        )
        if not any_remaining:
            target.controller_id_before_any_aura_swap = None
        if new_controller != target.controller_id:
            target.controller_id = new_controller
            state.log.append(
                f"{target.printing.name} reverts to P{new_controller} "
                f"(no longer enchanted by {obj.printing.name})"
            )
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
            f"{aura.printing.name} is put into the graveyard "
            f"(enchanted permanent left the battlefield)"
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
        # Bump the per-turn death tracker BEFORE firing dies triggers
        # so an in-trigger ETB-replacement that reads
        # ``state.creatures_died_this_turn`` (via the
        # ``enters_with_plus_one_counter_if_creature_died_this_turn``
        # printing flag, e.g. Cackling Slasher) sees this very death
        # too. The tracker counts EVERY creature death — both players,
        # token or non-token — matching Cackling Slasher's
        # unqualified "if a creature died this turn" surface.
        state.creatures_died_this_turn += 1
        _fire_dies_triggers(state, obj)

    # Predicate-style ``Event.DIES`` dispatch. Phase-4 widens the
    # legacy creature-only DIES fire path to also cover artifacts so
    # the migrated ``your_creature_or_artifact_dies`` observer
    # (Susurian Voidborn) keeps firing on artifact deaths the same
    # way the legacy ``_fire_your_creature_or_artifact_dies_triggers``
    # used to. Predicates handle type-filtering downstream — a
    # ``IsCreature() & ...`` predicate won't match an artifact-only
    # death.
    if destination == "graveyard" and (was_creature or obj.printing.is_artifact):
        from mtg_bot.actions import dispatch_event as _dispatch_event_dies
        from mtg_bot.effects.predicates import Event as _Event_dies

        _dispatch_event_dies(
            state,
            _Event_dies.DIES,
            label="dies",
            extra_observers=[obj],
            obj=obj,
        )

    # Generic "when this leaves the battlefield" triggers — fires for
    # artifacts, enchantments, and anything else with a matching
    # triggered ability. Used by Cryogen Relic ("enters or leaves →
    # draw a card").
    _fire_leaves_battlefield_triggers(state, obj)

    # Return any cards this object exiled with "until this leaves" to
    # their owner's battlefield. Applies whether the source is destroyed
    # or exiled itself.
    _release_exiled_until_leaves(state, obj.id)

    # When an object leaves the battlefield, every continuous
    # effect that targets it ceases to apply (CR 400.7 — it's a
    # new object once it changes zones). Drop registry entries
    # where ``target_id == obj.id``. Done AFTER dies-trigger
    # firing so granted-trigger entries (Perigee Beckoner's
    # self-granted dies-rider) are still readable when the
    # trigger machinery walks them. Layer-1 copy entries from
    # sorceries (Cytoshape) get cleaned up here since their
    # source spell never goes through ``move_off_battlefield``.
    state.continuous_effects = [
        ce for ce in state.continuous_effects
        if ce.target_id != obj.id
    ]
    state._invalidate_layered_cache()
    # Layer-1 copy revert: if the leaving object was a copy
    # (Clone, Cytoshape, Mirage Mirror), restore the printing
    # from the captured ``original_printing`` snapshot so a
    # future reanimation enters as the printed object.
    from mtg_bot.game import revert_printing_if_no_layer1_copies
    revert_printing_if_no_layer1_copies(state, obj)


def fire_counters_added_to_your_creature_triggers(
    state: GameState, controller_id: int, amount: int, obj=None,
) -> None:
    """Dispatch the phase-8 predicate-style ``Event.COUNTERS_ADDED``
    event so observer triggers (Terrasymbiosis's "draw that many
    cards") fire. ``amount`` is the effective count added (post-
    doubling); it threads through ``counter_amount`` to each pushed
    StackItem and resolving effects read it via
    ``state.resolving_counter_amount``.

    The retained name and ``controller_id`` parameter are scaffolding
    from the dual-path migration era — the legacy walk over
    ``counters_added_to_your_creature`` string-key abilities was
    dropped once Terrasymbiosis migrated to the predicate path.
    Calls without ``obj`` are no-ops today (no observer can fire);
    kept for API stability with the single in-tree caller
    (``game.add_plus_one_counters``).
    """
    if obj is None:
        return
    from mtg_bot.actions import dispatch_event
    from mtg_bot.effects.predicates import Event as _Event

    dispatch_event(
        state, _Event.COUNTERS_ADDED,
        label=f"counters-added (amount {amount})",
        counter_amount=amount,
        obj=obj,
    )


def _fire_leaves_battlefield_triggers(
    state: GameState, obj: "GameObject"
) -> None:
    """Dispatch the ``Event.LEAVES_BATTLEFIELD`` event for ``obj``.

    Phase 4 migrated every static card from the legacy string-key
    ``trigger="leaves_battlefield"`` and
    ``"another_creature_you_control_dies_or_exiled"`` (the latter
    collapses cleanly to LEAVES_BATTLEFIELD because both death and
    exile leave the battlefield). The dispatcher walks battlefield
    observers AND ``extra_observers=[obj]`` so the departing object's
    own self-trigger (``IsSelf()``) is checked even though it's
    already been moved off the battlefield by the caller.
    ``resolving_source`` exposes the dearly departed during resolution.
    """
    from mtg_bot.actions import dispatch_event
    from mtg_bot.effects.predicates import Event

    dispatch_event(
        state,
        Event.LEAVES_BATTLEFIELD,
        label="leaves-battlefield",
        extra_observers=[obj],
        obj=obj,
    )


def _release_exiled_until_leaves(state: GameState, source_id: int) -> None:
    """Move any objects from exile back to the battlefield under their
    owner's control if they were exiled by the given source (Oblivion-
    Ring-style). Returns them as fresh ETBs so ETB triggers fire again.

    Honors the one-shot ``state.suppress_exiled_by_source_on_leave_for``
    flag: when it equals ``source_id``, the auto-return is skipped for
    THIS leave event and the flag is cleared. Used by
    ``SacrificeSelfPreservingExileLink`` to defeat the auto-return
    during Sothera, the Supervoid's end-step recall (the recall step
    pulls one tagged card out of exile manually BEFORE the source is
    sacrificed; without suppression, the remaining tagged cards would
    race back to their owners' battlefields, which the printed text
    doesn't say).
    """
    from mtg_bot.actions import put_into_battlefield

    if state.suppress_exiled_by_source_on_leave_for == source_id:
        # One-shot suppression: clear and skip.
        state.suppress_exiled_by_source_on_leave_for = None
        return
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
    """Dispatch the phase-8 predicate-style ``Event.DISCARDS_CARD``
    event so opponent-discards observer triggers (Entropic
    Battlecruiser, predicate ``Controlled(by=OPPONENT)``) fire.
    Called after any single-card discard event.

    The discarding player flows through as
    ``fixed_targets=(("player", id),)`` so the resolving effect can
    damage them without target selection. The legacy
    ``opponent_discards_a_card`` string-key walk was dropped once
    Entropic Battlecruiser migrated to the predicate path; the
    function name is preserved because ``effects/generic.py`` and
    ``effects/bespoke.py`` per-discard sites import it directly.
    """
    from mtg_bot.actions import dispatch_event
    from mtg_bot.effects.predicates import Event as _Event

    discarding_player = state.player_by_id(discarding_player_id)
    dispatch_event(
        state, _Event.DISCARDS_CARD, label="discards-card",
        fixed_targets=(("player", discarding_player_id),),
        player=discarding_player,
    )


def should_fire_trigger(
    state: GameState,
    source_id: int,
    ability_index: int,
    ability,
    *,
    skip_once_per_turn: bool = False,
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

    ``skip_once_per_turn`` suppresses the once_per_turn ledger check when
    the caller provides its own deduplication (e.g. the aggregated
    counter-creature-combat-damage fire path in ``combat.py`` uses the
    ``aggregated_pairs`` set for deduplication and must not be constrained
    by the per-ability once_per_turn gate).
    """
    from mtg_bot.game import is_void_active

    if getattr(ability, "requires_void", False) and not is_void_active(state):
        return False
    tier = getattr(ability, "tier_threshold", 0)
    if tier > 0:
        source = next((o for o in state.battlefield if o.id == source_id), None)
        if source is None or source.charge_counters < tier:
            return False
    if skip_once_per_turn or not getattr(ability, "once_per_turn", False):
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

    The fire path also routes "whenever you sacrifice an artifact"
    triggers (Biotech Specialist) when the sacrificed object was an
    artifact.

    Sacrifice bypasses indestructible (MTG rule 701.16a — sacrifice is
    not a "destroy" effect).
    """
    was_creature = obj.printing.is_creature
    was_artifact = obj.printing.is_artifact
    move_off_battlefield(state, obj, destination="graveyard")
    if not (was_creature or was_artifact):
        return
    # Phase-8 predicate-style dispatch: fire IS_SACRIFICED with the
    # sacrificed permanent as subject. The legacy per-key walks for
    # ``sacrifice_creature_or_artifact`` (Lightless Evangel) and
    # ``sacrifice_artifact`` (Biotech Specialist) were dropped once
    # both migrated to the predicate path — the predicate
    # ``(IsCreature() | IsArtifact()) & Controlled(YOU) & ~IsSelf()``
    # (Lightless) and ``IsArtifact() & Controlled(YOU) & ~IsSelf()``
    # (Biotech) reproduce the same firing scope. The sacrificed
    # object has already been moved to the graveyard so we include it
    # via ``extra_observers`` (no observer in scope today triggers off
    # its own sacrifice, but parity with DIES / LEAVES_BATTLEFIELD
    # keeps the dispatch surface uniform).
    from mtg_bot.actions import dispatch_event
    from mtg_bot.effects.predicates import Event as _Event

    dispatch_event(
        state, _Event.IS_SACRIFICED, label="sacrifice",
        extra_observers=[obj],
        obj=obj,
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
    """Tap ``obj`` and push any becomes-tapped triggered abilities onto
    the stack.

    Phase-7 commit 3 migrated every static
    ``trigger="becomes_tapped"`` and
    ``trigger="enchanted_permanent_becomes_tapped"`` site to
    predicate-style ``event=Event.BECOMES_TAPPED`` with either
    ``IsSelf()`` (this creature becomes tapped — the tapped permanent
    itself fires) or ``IsHost()`` (enchanted permanent becomes tapped
    — an attached aura fires; Cryoshatter), so the two legacy walks
    that previously hardcode-matched those string keys had no live
    entries left and were dropped. The function is now a thin
    ``dispatch_event`` forwarder — both ``IsSelf`` and ``IsHost``
    flow through the single dispatcher sweep because the predicates
    key off independent attributes (``subject is source`` for
    ``IsSelf``; ``source.attached_to == subject.id`` for ``IsHost``).

    Already-tapped objects are still a no-op (no re-trigger).
    """
    from mtg_bot.actions import dispatch_event
    from mtg_bot.effects.predicates import Event

    if obj.tapped:
        return
    obj.tapped = True
    dispatch_event(
        state, Event.BECOMES_TAPPED,
        label="becomes-tapped", obj=obj,
    )


def fire_landfall_triggers(state: GameState, new_land: "GameObject") -> None:
    """Push landfall triggers onto the stack for permanents the new
    land's controller controls.

    Called from bespoke effects that put a land onto the battlefield
    OUTSIDE of the standard ``_play_land`` / ``_trigger_etb_abilities``
    pipeline (Burgeoning's "put a land card from your hand",
    fetchland-style "search your library for a basic land", and so
    on). The standard ``_play_land`` path drives landfall through
    ``_trigger_etb_abilities`` instead — calling this on top of that
    would double-fire.

    Fires both legacy ``trigger="landfall"`` string-key abilities
    (dead after the phase-2 migration but kept here in step with the
    rest of the ``_fire_*`` family — phase 3 sweeps the legacy
    branch) and predicate-style ``event=Event.ENTERS,
    predicate=IsLand() & Controlled(YOU)`` abilities via
    ``dispatch_event``. The dispatcher itself applies
    ``etb_trigger_multiplier`` for ENTERS, so the legacy loop here
    multiplies its own firings independently.
    """
    from mtg_bot.actions import dispatch_event, push_triggered_ability
    from mtg_bot.effects.predicates import Event
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
    # Dispatch the predicate-style ENTERS event so phase-2-migrated
    # landfall abilities fire from this code path as well.
    dispatch_event(state, Event.ENTERS, label="landfall", obj=new_land)


def fire_opponent_plays_land_triggers(
    state: GameState, land_controller_id: int, land=None,
) -> None:
    """Dispatch the phase-8 predicate-style ``Event.PLAYS_LAND`` event
    so every land-play observer (Burgeoning's
    ``Controlled(by=OPPONENT)`` and The Endstone's land-half
    ``Controlled(YOU)``) fires from a single sweep.

    Called from ``actions.play_land`` only (NOT from effects that
    merely put a land onto the battlefield — "plays a land" is the
    land-drop action per 305.1). The predicate dispatcher walks every
    battlefield permanent; ``Controlled(by=OPPONENT,
    subject="controller")`` evaluates true for sources whose
    controller is NOT the land's controller (so Burgeoning's "you may
    put a land from your hand onto the battlefield" resolves under the
    enchantment's controller).

    ``land`` is the land permanent that was played (the dispatch
    subject). The retained name and the optional ``land=`` keyword
    are scaffolding from the dual-path migration era — direct callers
    in tests pre-date the dispatch infrastructure and pass
    ``land_controller_id`` only; once Burgeoning's tests pivoted to
    pass a synthetic land via the ``_fire_played_land`` helper the
    legacy ``opponent_plays_land`` string-key walk had no live
    entries left and was dropped. Calls without ``land`` are no-ops
    today (no observer can fire); kept for API stability.
    """
    if land is None:
        return
    from mtg_bot.actions import dispatch_event
    from mtg_bot.effects.predicates import Event as _Event

    land_controller = state.player_by_id(land_controller_id)
    dispatch_event(
        state, _Event.PLAYS_LAND, label="plays-land",
        land=land, controller=land_controller,
    )


def _fire_dies_triggers(state: GameState, dead: "GameObject") -> None:
    """Resolve UEOT-granted dies-rider effects on ``dead``.

    Phase 4 migrated every static card from the legacy string-key
    ``trigger="dies"`` (and the family of
    ``"creature_you_control_with_counter_dies"`` /
    ``"nontoken_creature_you_control_with_counter_dies"`` /
    ``"your_creature_or_artifact_dies"`` keys) to predicate-style
    ``event=Event.DIES`` abilities. Those fire from
    ``move_off_battlefield`` via ``dispatch_event``, so all that
    remains here is the UEOT-granted-rider path.

    The granted rider lives on a layer-6 ``grant_triggered_ability``
    registry entry against the dying object (Perigee Beckoner's pump
    grants exactly this). The rider isn't represented in the
    printed-ability ledger so we resolve it directly rather than
    push it through
    ``push_triggered_ability`` (which would require broadening the
    ledger key type). ``resolving_source`` is set to the dying object
    so the granted effect can read it. Mirrors the dealt-damage path
    in ``combat._fire_enchanted_dealt_damage_triggers``.

    Both legacy ``trigger="dies"`` and predicate-style
    ``event=Event.DIES`` granted shapes are recognized so any future
    granted rider on either shape continues to work.
    """
    from mtg_bot.effects.predicates import Event
    from mtg_bot.game import effective_triggered_abilities

    granted_only = [
        ab for ab in effective_triggered_abilities(state, dead)
        if ab not in dead.printing.triggered_abilities
    ]
    for ability in granted_only:
        is_legacy_dies = ability.trigger == "dies"
        is_predicate_dies = ability.matches_event(
            Event.DIES, {"obj": dead}, dead, state,
        )
        if not (is_legacy_dies or is_predicate_dies):
            continue
        state.log.append(
            f"{dead.printing.name}'s granted dies trigger fires"
        )
        state.resolving_source = dead
        try:
            ability.effect.resolve(state, dead.controller_id, ())
        finally:
            state.resolving_source = None


def run_beginning_of_upkeep_triggers(state: GameState) -> None:
    """Push "At the beginning of your upkeep" triggered abilities onto
    the stack for permanents the active player controls.

    Phase-6 commit 2 migrated every static
    ``trigger="beginning_of_upkeep"`` site to predicate-style
    ``event=Event.BEGINNING_OF_UPKEEP, predicate=Controlled(YOU)``,
    so the legacy walk over ``obj.printing.triggered_abilities`` here
    has no live entries left. The function is now a thin
    ``dispatch_event`` forwarder — ``Controlled(YOU)`` against the
    active-player subject filters to permanents the active player
    controls (the legacy ``obj.controller_id != ap_id`` skip), and
    the dispatcher's ``source.controller_id`` push matches the
    legacy ``controller_id=ap_id`` resolution because the predicate
    already gates ``source.controller_id == ap_id``.
    """
    from mtg_bot.actions import dispatch_event
    from mtg_bot.effects.predicates import Event

    dispatch_event(
        state, Event.BEGINNING_OF_UPKEEP,
        label="beginning-of-upkeep", player=state.active_player(),
    )


def run_beginning_of_combat_triggers(state: GameState) -> None:
    """Push "At the beginning of combat on your turn" triggered
    abilities onto the stack for permanents the active player
    controls.

    Phase-6 commit 2 migrated every static
    ``trigger="beginning_of_combat"`` site to predicate-style
    ``event=Event.BEGINNING_OF_COMBAT, predicate=Controlled(YOU)``;
    the legacy walk is gone. See ``run_beginning_of_upkeep_triggers``
    for the controller/predicate equivalence rationale.
    """
    from mtg_bot.actions import dispatch_event
    from mtg_bot.effects.predicates import Event

    dispatch_event(
        state, Event.BEGINNING_OF_COMBAT,
        label="beginning-of-combat", player=state.active_player(),
    )


def _find_object_by_id(state: GameState, obj_id: int):
    """Find a GameObject by id across every zone (battlefield + each
    player's library/hand/graveyard/exile). Returns None if no
    GameObject with that id exists anywhere — only possible for
    tokens that ceased to exist (CR 704.5d).
    """
    for o in state.battlefield:
        if o.id == obj_id:
            return o
    for p in state.players:
        for zone in (p.library, p.hand, p.graveyard, p.exile):
            for o in zone:
                if o.id == obj_id:
                    return o
    return None


def run_delayed_end_step_triggers(state: GameState) -> None:
    """Push fires-now delayed triggers onto the stack as real
    triggered abilities.

    Each entry in ``state.delayed_triggers`` whose ``fire_at_turn``
    matches the current turn AND whose ``controller_id`` matches the
    active player gets converted into a synthetic
    ``TriggeredAbility(event=BEGINNING_OF_END_STEP, predicate=Always(),
    effect=<entry-effect>)`` and pushed via ``push_triggered_ability``.
    Players then get priority during the end step's priority loop, and
    the standard ``resolve_top_of_stack`` path drains the stack.

    Push order is the same as the pre-existing iteration order over
    ``state.delayed_triggers`` (FIFO scheduling order). Items are
    pushed onto a LIFO stack, so they resolve in reverse-scheduling
    order — the most recently scheduled delayed trigger resolves
    first. MTG's APNAP rule for simultaneous triggers from a single
    player would order these per-controller-choice, but our engine's
    delayed-trigger collection is single-player anyway (the active
    player), so the LIFO-of-scheduling-order is a deterministic stand-in.

    The ``state.resolving_source`` plumbing happens automatically
    through the standard ``resolve_top_of_stack`` path: when a
    StackItem's ability resolves, ``state.resolving_source`` is set
    to ``item.source`` for the duration of the effect's resolve. The
    delayed-trigger effects (``WarpExileSelf``, ``SacrificeSourceDelayed``,
    ``RemoveChargeCountersFromSourceDelayed``,
    ``ReturnExiledPermanentToOwnerTapped``) all read from there or
    from their own stored ids.

    Entries with a missing source (only possible for tokens that
    ceased to exist before fire time) consume the entry without
    pushing — there's no observable game state difference vs.
    pushing a no-op trigger.

    Legacy string-action entries (``"sacrifice"`` / ``"remove_charge_counters"``)
    are no longer supported here — their producers were migrated to
    the effect-shape path in the same commit that introduced this
    refactor. Any leftover string-action entry is a bug; we raise
    ``ValueError`` rather than silently bypass the stack.
    """
    from mtg_bot.actions import push_triggered_ability
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import Always, Event

    ap_id = state.active_player().id
    remaining: list[dict] = []
    to_push: list[dict] = []
    for entry in state.delayed_triggers:
        fires_now = (
            entry["fire_at_turn"] == state.turn_number
            and entry["controller_id"] == ap_id
        )
        if fires_now:
            to_push.append(entry)
        else:
            remaining.append(entry)
    state.delayed_triggers = remaining

    for entry in to_push:
        if "effect" not in entry:
            raise ValueError(
                "delayed_triggers entry without 'effect' key — legacy "
                "string-action entries are no longer supported. Migrate "
                "the producer to push an Effect instance with source_id."
            )
        effect = entry["effect"]
        source_id = entry.get("source_id")
        source = (
            _find_object_by_id(state, source_id)
            if source_id is not None else None
        )
        if source is None:
            # Token ceased to exist (or no source_id was scheduled);
            # the trigger has nothing to act on. Mirrors pre-refactor
            # silent-no-op behavior. Skip the push.
            continue
        ability = TriggeredAbility(
            event=Event.BEGINNING_OF_END_STEP,
            predicate=Always(),
            effect=effect,
        )
        push_triggered_ability(
            state,
            source=source,
            ability=ability,
            ability_index=-1,  # not a real index — synthetic ability
            controller_id=entry["controller_id"],
            label="delayed",
        )


def run_beginning_of_postcombat_main_triggers(state: GameState) -> None:
    """Push "At the beginning of your second main phase" triggered
    abilities onto the stack for permanents the active player controls.

    Mirrors ``run_beginning_of_upkeep_triggers`` /
    ``run_beginning_of_combat_triggers`` exactly — the
    ``Controlled(YOU)`` predicate against the active-player subject
    filters to permanents the active player controls, and the
    dispatcher's ``source.controller_id`` push matches the legacy
    upkeep/combat resolution rationale (the predicate already gates
    ``source.controller_id == ap_id``).

    Models the DSK Survival ability-word trigger family — every
    printed Survival creature in Duskmourn carries a
    ``TriggeredAbility(event=BEGINNING_OF_POSTCOMBAT_MAIN,
    predicate=IsSelf() & IsTapped(), …)`` shape. Called from
    ``simulate.run_step`` (and its search-engine equivalent) at the
    start of the post-combat main phase, before priority opens.
    """
    from mtg_bot.actions import dispatch_event
    from mtg_bot.effects.predicates import Event

    dispatch_event(
        state, Event.BEGINNING_OF_POSTCOMBAT_MAIN,
        label="beginning-of-postcombat-main",
        player=state.active_player(),
    )


def run_impending_decrement_turn_based_action(state: GameState) -> None:
    """Remove one time counter from each impending-active permanent
    the active player controls. When the count hits 0, clear
    ``impending_active`` and the permanent becomes a creature again
    (its printed creature type stops being suppressed by
    ``is_creature_now``).

    Modeled as a turn-based action at the beginning of each end
    step (CR 705-style turn-based bookkeeping, mirroring the printed
    Impending reminder text "At the beginning of your end step,
    remove a time counter from it"). Runs BEFORE
    ``run_beginning_of_end_step_triggers`` so an Overlord whose
    last counter is removed this end step is a creature in time
    for any "at the beginning of your end step" trigger that keys
    off creature presence on the same player's end step.

    Only the active player's permanents tick — the Impending
    reminder is "At the beginning of YOUR end step" — so an
    Overlord's controller has to reach their own end step to
    advance it. The active-player gate matches the printed text.
    """
    ap_id = state.active_player().id
    for obj in state.battlefield:
        if not obj.impending_active:
            continue
        if obj.controller_id != ap_id:
            continue
        obj.time_counters -= 1
        if obj.time_counters <= 0:
            obj.time_counters = 0
            obj.impending_active = False
            state.log.append(
                f"{obj.printing.name} loses its last time counter; "
                f"becomes a creature"
            )
        else:
            state.log.append(
                f"{obj.printing.name} loses a time counter "
                f"({obj.time_counters} remaining)"
            )


def run_beginning_of_end_step_triggers(state: GameState) -> None:
    """Push end-step triggers for the current end step onto the stack.

    Handles two predicate shapes that share ``Event.BEGINNING_OF_END_STEP``:

    - ``predicate=Controlled(YOU)`` — fires only on the active
      player's end step for permanents they control (standard oracle
      "At the beginning of your end step").
    - ``predicate=Always()`` — fires on every player's end step
      regardless of which player controls the source (Ragost's "At
      the beginning of each end step, if you gained life this turn,
      untap Ragost").

    Phase-6 commit 2 migrated every static
    ``trigger="beginning_of_end_step"`` and
    ``trigger="beginning_of_each_end_step"`` site to one of the two
    predicate shapes above; the legacy ``trigger`` walk is gone. The
    dispatcher's ``source.controller_id`` push matches the legacy
    resolver for BOTH variants — for the "your" variant the predicate
    already gates ``source.controller_id == ap_id``, and for the
    each-end-step variant the legacy code already resolved under
    ``source.controller_id`` (not the active player), so collapsing
    onto the dispatcher preserves both behaviors verbatim.
    """
    from mtg_bot.actions import dispatch_event
    from mtg_bot.effects.predicates import Event

    dispatch_event(
        state, Event.BEGINNING_OF_END_STEP,
        label="end-step", player=state.active_player(),
    )


def run_cleanup_step(state: GameState) -> None:
    ap = state.active_player()
    # CR 402.2: by default the active player discards down to 7 at
    # cleanup. Steaming Sauna's static ``You have no maximum hand
    # size`` (and any future ``grants_no_max_hand_size``-flagged
    # static) suspends that rule for its controller while active.
    # Walk the battlefield for any source under ``ap``'s control
    # whose ``_active_static_abilities`` (room_half-aware) includes
    # a ``grants_no_max_hand_size=True`` entry; skip the discard
    # loop when found.
    from mtg_bot.game import _active_static_abilities
    no_max_hand_size = any(
        getattr(static, "grants_no_max_hand_size", False)
        for obj in state.battlefield
        if obj.controller_id == ap.id
        for static in _active_static_abilities(obj)
    )
    if not no_max_hand_size:
        while len(ap.hand) > 7:
            card = ap.hand.pop()
            card.zone = Zone.GRAVEYARD
            ap.graveyard.append(card)
    # Layer-6/7 UEOT continuous effects expire at cleanup. Drop every
    # registry entry tagged ``expires_at="cleanup"`` (Phase 2+
    # migration: keyword grants from pump effects, eventually
    # P/T pumps and granted abilities). Effects still using the
    # bespoke ``temp_*`` fields are cleared in the per-object loop
    # below; both code paths run together until full migration.
    state.expire_continuous_effects("cleanup")
    # UEOT layer-1 copy effects (Cytoshape, Mirage Mirror): when
    # the layer-1 entry expired above, the affected object's
    # ``printing`` mutation needs to revert. Walk the battlefield
    # and revert any object that has ``original_printing`` set
    # but no remaining layer-1 ``is_copy`` entries.
    from mtg_bot.game import (
        effective_controller, revert_printing_if_no_layer1_copies,
    )
    for obj in state.battlefield:
        revert_printing_if_no_layer1_copies(state, obj)
    # UEOT layer-2 control_change effects (Mutinous Massacre,
    # Systems Override): when the layer-2 entry expired above,
    # the cached ``obj.controller_id`` is stale. Recompute via
    # ``effective_controller`` and clear
    # ``controller_id_before_any_aura_swap`` for any object whose
    # last control_change entry is now gone.
    for obj in state.battlefield:
        obj.controller_id = effective_controller(state, obj)
        any_remaining = any(
            ce.layer == 2
            and ce.kind == "control_change"
            and ce.target_id == obj.id
            for ce in state.continuous_effects
        )
        if not any_remaining:
            obj.controller_id_before_any_aura_swap = None
    # Layer-4 ``add_type "creature"`` cache rebuild: when an
    # ApplyEffect-rewritten ``BecomeType`` entry expired above, the
    # cached ``permanent_is_creature`` flag is stale. The registry is
    # the source of truth — keep the cache True only while at least
    # one layer-4 ``add_type "creature"`` entry still targets the
    # object. Without this rebuild, a finite-lifetime ``BecomeType
    # (types_to_add=("creature",))`` (manland animation, e.g. Raging
    # Ravine via the new pattern) would leave the permanent stuck as
    # a creature after cleanup.
    for obj in state.battlefield:
        if not obj.permanent_is_creature:
            continue
        still_creature = any(
            ce.layer == 4
            and ce.kind == "add_type"
            and ce.target_id == obj.id
            and ce.params == ("creature",)
            for ce in state.continuous_effects
        )
        if not still_creature:
            obj.permanent_is_creature = False
    for obj in state.battlefield:
        obj.damage = 0
        obj.marked_lethal = False
        obj.damaged_this_turn = False
        obj.temp_power_bonus = 0
        obj.temp_toughness_bonus = 0
        # Regenerate shield: unconsumed shields wear off at cleanup.
        obj.regeneration_shield = False
        # UEOT "gain control" reverts are handled above by the layer-2
        # ``control_change`` registry path (``expire_continuous_effects
        # ("cleanup")`` + the controller-refresh loop). The legacy
        # ``temp_original_controller_id`` field has been retired.
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
    # Reset the per-turn creature-death tracker (Cackling Slasher's
    # "if a creature died this turn" rider). The tracker is incremented
    # in ``move_off_battlefield`` for every creature dies event the
    # engine fires; clearing it here scopes the rider to a single turn.
    state.creatures_died_this_turn = 0
    # Darkness-style combat-damage prevention expires at end of turn.
    state.prevent_combat_damage_this_turn = False
    # Reset per-player spell counters for "your Nth spell" triggers.
    for p in state.players:
        p.spells_cast_this_turn = 0
        p.noncreature_spells_cast_this_turn = 0
        p.attacked_this_turn = []
        p.life_gained_this_turn = 0
        p.lands_entered_this_turn = 0
        p.artifacts_entered_under_your_control_this_turn = 0
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
    """Apply state-based actions until quiescent (CR 704.3 — SBAs are
    checked continuously and applied repeatedly until none apply).
    Returns True if any pass made changes.

    Internally calls ``_state_based_actions_pass`` in a loop. The
    iteration cap (``_SBA_MAX_PASSES``) defends against pathological
    cycles — none should occur with the rules we model, but the
    cap converts a runaway into an early bailout instead of a hang.
    """
    any_changed = False
    for _ in range(_SBA_MAX_PASSES):
        if not _state_based_actions_pass(state):
            break
        any_changed = True
    return any_changed


_SBA_MAX_PASSES = 50


def _state_based_actions_pass(state: GameState) -> bool:
    """Single SBA application pass. Returns True if any changes were
    made. Public callers should use ``state_based_actions``, which
    loops this until quiescent.

    CR 704.5 SBAs implemented (audit numbering):
    - 704.5a: player at 0 or less life loses.
    - 704.5b: drawing from empty library (handled in
      ``draw_card``, not here).
    - 704.5c: 10+ poison counters loses.
    - 704.5d: tokens cease to exist (in
      ``move_off_battlefield``).
    - 704.5f: creature with toughness ≤ 0 → graveyard.
    - 704.5g: creature with damage ≥ toughness → destroyed.
    - 704.5h: marked-lethal → destroyed.
    - 704.5i: planeswalker with 0 loyalty → graveyard.
    - 704.5j: legend rule (per-controller, per-name).
    - 704.5n (audit) / 704.5r (current CR): +1/+1 vs -1/-1
      counter cancellation.
    - 704.5n (audit) / 704.5q (current CR): aura on illegal
      target → graveyard.
    - 704.5p (audit): equipment on illegal target → unattach.
    - 704.5r (audit): saga at chapter count → graveyard.
    - 701.15: regeneration shield (handled in the destroyed
      pass — not strictly an SBA).

    KNOWN GAPS:
    - 704.5k (audit) / 704.5o (current CR): world rule.
      Not implemented. No World cards are in the EoE pool.
    - 704.5s (audit) / 704.5u (current CR): battle with 0
      defense → graveyard. Not implemented. No Battles in EoE.
    - 21+ commander damage from one source: not implemented.
      Engine doesn't track commander damage by source.
    - Token in non-battlefield zone other than via leave-play:
      not actively scrubbed. Cards moved to a hand/library
      from a non-battlefield zone are not currently a token-
      bearing path.
    """
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

    # Legend rule (CR 704.5j): if a player controls two or more
    # legendary permanents with the same name, that player chooses
    # one of them, and the rest are put into their owners'
    # graveyards. Group by (controller_id, printed_name) over
    # legendary permanents only.
    legend_groups: dict[tuple[int, str], list] = {}
    for obj in state.battlefield:
        if not obj.printing.is_legendary:
            continue
        key = (obj.controller_id, obj.printing.name)
        legend_groups.setdefault(key, []).append(obj)
    for (ctrl_id, _name), group in legend_groups.items():
        if len(group) < 2:
            continue
        controller = state.player_by_id(ctrl_id)
        if controller.agent is not None:
            keep_id = controller.agent.choose_legend_keep(
                state, ctrl_id, [o.id for o in group],
            )
        else:
            keep_id = group[0].id
        for obj in group:
            if obj.id == keep_id:
                continue
            state.log.append(
                f"{obj.printing.name} put into graveyard "
                f"(legend rule; P{ctrl_id} kept #{keep_id})"
            )
            move_off_battlefield(state, obj, destination="graveyard")
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

    # Saga age (CR 704.5r in audit numbering): if a saga has lore
    # counters greater than or equal to its final chapter number,
    # its controller sacrifices it (goes to owner's graveyard).
    sagas_to_bury: list = []
    for obj in state.battlefield:
        if obj.printing.is_saga and obj.lore_counters >= obj.printing.chapter_count:
            sagas_to_bury.append(obj)
    for saga in sagas_to_bury:
        state.log.append(
            f"{saga.printing.name} sacrificed "
            f"(lore counter ≥ chapter count {saga.printing.chapter_count})"
        )
        move_off_battlefield(state, saga, destination="graveyard")
        changed = True

    # +1/+1 vs -1/-1 counter cancellation (CR 704.5r in current CR;
    # labelled 704.5n in this codebase's audit). When a permanent
    # has both kinds, N pairs are removed where N is the smaller
    # count. Cancellation can drive toughness back above 0 / below
    # 0 → run BEFORE the destroyed-creature pass above? No, after,
    # because cancellation is a separate SBA pass. The
    # state_based_actions LOOP handles cascading: after this
    # cancellation, the next pass re-evaluates 704.5f/g.
    for obj in state.battlefield:
        if obj.plus_one_counters > 0 and obj.minus_one_counters > 0:
            n = min(obj.plus_one_counters, obj.minus_one_counters)
            obj.plus_one_counters -= n
            obj.minus_one_counters -= n
            state.log.append(
                f"{obj.printing.name}: {n} +1/+1 and {n} -1/-1 "
                f"counters cancel"
            )
            changed = True

    # Aura attachment legality (CR 704.5q in current CR; this
    # codebase historically labelled it 704.5n): an Aura attached to
    # an
    # illegal target (or unattached) goes to its owner's graveyard.
    # The target is illegal if it's no longer on the battlefield, or
    # no longer satisfies the Aura's printed enchant restriction
    # (e.g., enchant creature with the target turned non-creature
    # by a Lignified manland's animation expiring).
    auras_to_bury: list = []
    for obj in state.battlefield:
        if not obj.printing.is_aura:
            continue
        if obj.attached_to is None:
            auras_to_bury.append(obj)
            continue
        target = next(
            (o for o in state.battlefield if o.id == obj.attached_to),
            None,
        )
        if target is None:
            auras_to_bury.append(obj)
            continue
        kind = obj.printing.aura_enchant_type
        if kind == "creature":
            if not is_creature_now(target):
                auras_to_bury.append(obj)
        elif kind == "artifact":
            if not target.printing.is_artifact:
                auras_to_bury.append(obj)
        elif kind == "land":
            if not target.printing.is_land:
                auras_to_bury.append(obj)
        # Other kinds (e.g., player-enchant) aren't in scope.
    for aura in auras_to_bury:
        state.log.append(
            f"{aura.printing.name} put into graveyard "
            f"(no legal enchant target)"
        )
        move_off_battlefield(state, aura, destination="graveyard")
        changed = True

    # Equipment attachment legality (CR 704.5p): an Equipment
    # attached to an illegal permanent (non-creature, gone) becomes
    # unattached but stays on the battlefield. Default scope:
    # Equipment must be attached to a creature.
    for obj in state.battlefield:
        if obj.printing.is_aura:
            continue
        if "Equipment" not in obj.printing.subtypes:
            continue
        if obj.attached_to is None:
            continue
        target = next(
            (o for o in state.battlefield if o.id == obj.attached_to),
            None,
        )
        if target is None or not is_creature_now(target):
            obj.attached_to = None
            state.log.append(
                f"{obj.printing.name} unattaches "
                f"(no longer attached to a creature)"
            )
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
