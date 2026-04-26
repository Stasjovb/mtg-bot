"""Combat: eligibility, declaration, and simultaneous damage."""

from __future__ import annotations

from mtg_bot.game import (
    GameObject,
    GameState,
    effective_keywords,
    effective_power,
    effective_toughness,
    is_creature_now,
)


def eligible_attackers(state: GameState, player_id: int) -> list[GameObject]:
    return [
        o for o in state.battlefield
        if o.controller_id == player_id
        and is_creature_now(o)
        and not o.tapped
        and (not o.summoning_sick or "haste" in effective_keywords(state, o))
        and "defender" not in effective_keywords(state, o)
    ]


def eligible_blockers(state: GameState, player_id: int) -> list[GameObject]:
    return [
        o for o in state.battlefield
        if o.controller_id == player_id
        and is_creature_now(o)
        and not o.tapped
    ]


def can_block(
    state: GameState, blocker: GameObject, attacker: GameObject
) -> bool:
    """Return True if ``blocker`` may legally declare a block against ``attacker``.

    Flying: a creature with flying can only be blocked by creatures with flying
    or reach.
    """
    attacker_kws = effective_keywords(state, attacker)
    blocker_kws = effective_keywords(state, blocker)
    if "flying" in attacker_kws:
        if not ("flying" in blocker_kws or "reach" in blocker_kws):
            return False
    return True


def declare_attackers(state: GameState, attacker_ids: list[int]) -> None:
    from mtg_bot.turn import tap_permanent, should_fire_trigger

    for oid in attacker_ids:
        obj = next(
            (o for o in state.battlefield if o.id == oid), None
        )
        if obj is None:
            # A prior attacker's trigger may have removed this one
            # (e.g., a sacrifice effect chained from becomes_tapped).
            # Skip silently — we still respect the agent's intent for
            # the remaining attackers.
            continue
        obj.attacking = True
        # Vigilance: attacking doesn't tap
        if "vigilance" not in effective_keywords(state, obj):
            tap_permanent(state, obj)
        state.log.append(f"{obj.printing.name} attacks")
        # Track "attacked with a Spacecraft this turn" for cost reductions.
        if obj.printing.is_spacecraft:
            state.player_by_id(
                obj.controller_id
            ).attacked_with_spacecraft_this_turn = True
        # Fire "whenever this creature attacks" triggers on the attacker.
        _fire_attacks_triggers(state, obj, should_fire_trigger)


def _fire_attacks_triggers(state: GameState, attacker, should_fire_trigger) -> None:
    from mtg_bot.game import is_void_active

    for i, ability in enumerate(attacker.printing.triggered_abilities):
        if ability.trigger != "attacks":
            continue
        if ability.requires_void and not is_void_active(state):
            continue
        if not should_fire_trigger(state, attacker.id, i, ability):
            continue
        state.log.append(
            f"{attacker.printing.name}'s attacks trigger fires"
        )
        state.resolving_source = attacker
        controller = state.player_by_id(attacker.controller_id)
        effect = ability.effect
        targets: tuple[tuple[str, int], ...] = ()
        if effect.requires_target():
            legal = effect.legal_targets(state, attacker.controller_id)
            if not legal:
                state.resolving_source = None
                state.log.append(
                    f"{attacker.printing.name}'s attacks trigger "
                    f"fizzles (no legal targets)"
                )
                continue
            if controller.agent is not None:
                chosen = controller.agent.choose_target(
                    state, attacker.controller_id, legal
                )
                if chosen is not None:
                    targets = (chosen,)
        try:
            effect.resolve(state, attacker.controller_id, targets)
        finally:
            state.resolving_source = None
    # Auras/Equipment attached to the attacker: fire their
    # "whenever enchanted/equipped creature attacks" triggers.
    # Matches Chorale of the Void (aura) and Atomic Microsizer (eq).
    for attached in list(state.battlefield):
        if attached.attached_to != attacker.id:
            continue
        is_aura = attached.printing.is_aura
        is_equipment = attached.printing.equipment_bonuses is not None
        if not (is_aura or is_equipment):
            continue
        wanted = (
            "enchanted_creature_attacks" if is_aura
            else "equipped_creature_attacks"
        )
        for i, ability in enumerate(attached.printing.triggered_abilities):
            if ability.trigger != wanted:
                continue
            if not should_fire_trigger(state, attached.id, i, ability):
                continue
            state.log.append(
                f"{attached.printing.name}'s attached-attacks trigger "
                f"fires"
            )
            state.resolving_source = attached
            ac_id = attached.controller_id
            controller = state.player_by_id(ac_id)
            effect = ability.effect
            targets: tuple[tuple[str, int], ...] = ()
            try:
                if effect.requires_target():
                    legal = effect.legal_targets(state, ac_id)
                    if not legal:
                        state.log.append(
                            f"{attached.printing.name}'s trigger "
                            f"fizzles (no legal targets)"
                        )
                        continue
                    if controller.agent is not None:
                        chosen = controller.agent.choose_target(
                            state, ac_id, legal
                        )
                        if chosen is not None:
                            targets = (chosen,)
                effect.resolve(state, ac_id, targets)
            finally:
                state.resolving_source = None


def declare_blockers(state: GameState, assignments: dict[int, int]) -> None:
    """``assignments`` maps blocker id → attacker id."""
    from mtg_bot.game import effective_keywords
    from mtg_bot.turn import should_fire_trigger

    for blocker_id, attacker_id in assignments.items():
        blocker = next(o for o in state.battlefield if o.id == blocker_id)
        attacker = next(o for o in state.battlefield if o.id == attacker_id)
        if attacker.temp_unblockable:
            state.log.append(
                f"{attacker.printing.name} can't be blocked — "
                f"{blocker.printing.name}'s block is ignored"
            )
            continue
        blocker.blocking = attacker_id
        attacker.blocked_by.append(blocker_id)
        state.log.append(f"{blocker.printing.name} blocks {attacker.printing.name}")
        # Fire "whenever ~ blocks a creature with flying" triggers on
        # the blocker (Skystinger). Extend with more filters as needed.
        attacker_kws = effective_keywords(state, attacker)
        for i, ability in enumerate(blocker.printing.triggered_abilities):
            if ability.trigger != "blocks_creature_with_flying":
                continue
            if "flying" not in attacker_kws:
                continue
            if not should_fire_trigger(state, blocker.id, i, ability):
                continue
            state.log.append(
                f"{blocker.printing.name}'s blocks-flying trigger fires"
            )
            state.resolving_source = blocker
            try:
                ability.effect.resolve(state, blocker.controller_id, ())
            finally:
                state.resolving_source = None


def _deals_in_step(kws: frozenset[str], *, first_strike_step: bool) -> bool:
    """Whether a creature with ``kws`` deals damage in the given step.

    First-strike step: creatures with first strike or double strike.
    Regular step: creatures with double strike OR without first strike.
    Creatures with first strike only don't deal regular damage.
    """
    has_first = "first strike" in kws
    has_double = "double strike" in kws
    if first_strike_step:
        return has_first or has_double
    return has_double or not has_first


def _any_first_or_double_strike_in_combat(state: GameState) -> bool:
    for o in state.battlefield:
        if not (o.attacking or o.blocking is not None):
            continue
        kws = effective_keywords(state, o)
        if "first strike" in kws or "double strike" in kws:
            return True
    return False


def resolve_combat_damage(state: GameState, defending_player_id: int) -> None:
    """Assign and deal combat damage.

    If any creature in combat has first or double strike, damage is split
    into two steps with state-based actions between them:
      1. First-strike step: first-strike and double-strike creatures deal.
      2. Regular step: creatures without first strike (and double-strike
         creatures again) deal.
    Otherwise there's just the single regular step (common case).
    """
    from mtg_bot.turn import state_based_actions

    if _any_first_or_double_strike_in_combat(state):
        _resolve_damage_step(state, defending_player_id, first_strike_step=True)
        state_based_actions(state)
        if state.is_over():
            return
    _resolve_damage_step(state, defending_player_id, first_strike_step=False)


def _resolve_damage_step(
    state: GameState, defending_player_id: int, *, first_strike_step: bool
) -> None:
    """Build and apply the damage events for one combat damage step."""
    # Darkness: "prevent all combat damage that would be dealt this
    # turn." Skip the entire damage pass — we still proceed through the
    # step so combat-damage-to-player triggers that key on actual
    # damage simply don't fire (no damage events to pair them with).
    if state.prevent_combat_damage_this_turn:
        state.log.append("combat damage prevented this turn (Darkness)")
        return
    # Event tuple layout:
    # (kind, target_id, amount, source_id, source_keywords, source_controller_id)
    damage_events_typed: list[
        tuple[str, int, int, int, frozenset[str], int]
    ] = []

    for attacker in state.battlefield:
        if not attacker.attacking:
            continue
        if attacker.phased_out:
            # Phased-out creatures don't exist for combat purposes.
            continue
        attacker_kws = effective_keywords(state, attacker)
        if not _deals_in_step(attacker_kws, first_strike_step=first_strike_step):
            # Attacker doesn't deal damage in this step; blockers of this
            # attacker may still deal damage back IF they qualify.
            blockers = [o for o in state.battlefield if o.id in attacker.blocked_by]
            for blocker in blockers:
                blocker_kws = effective_keywords(state, blocker)
                if not _deals_in_step(blocker_kws, first_strike_step=first_strike_step):
                    continue
                blocker_power = effective_power(state, blocker)
                if blocker_power > 0:
                    damage_events_typed.append(
                        ("creature", attacker.id, blocker_power,
                         blocker.id, blocker_kws, blocker.controller_id)
                    )
            continue

        blockers = [o for o in state.battlefield if o.id in attacker.blocked_by]
        attacker_power = effective_power(state, attacker)
        attacker_controller = attacker.controller_id
        has_trample = "trample" in attacker_kws
        has_deathtouch = "deathtouch" in attacker_kws
        if not blockers:
            damage_events_typed.append(
                ("player", defending_player_id, attacker_power,
                 attacker.id, attacker_kws, attacker_controller)
            )
        else:
            remaining = attacker_power
            for i, blocker in enumerate(blockers):
                if remaining <= 0:
                    break
                need = 1 if has_deathtouch else max(
                    0, effective_toughness(state, blocker) - blocker.damage
                )
                is_last = i == len(blockers) - 1
                if is_last and not has_trample:
                    assigned = remaining
                else:
                    assigned = min(remaining, need)
                damage_events_typed.append(
                    ("creature", blocker.id, assigned,
                     attacker.id, attacker_kws, attacker_controller)
                )
                remaining -= assigned
            if has_trample and remaining > 0:
                damage_events_typed.append(
                    ("player", defending_player_id, remaining,
                     attacker.id, attacker_kws, attacker_controller)
                )
            for blocker in blockers:
                blocker_kws = effective_keywords(state, blocker)
                if not _deals_in_step(blocker_kws, first_strike_step=first_strike_step):
                    continue
                blocker_power = effective_power(state, blocker)
                if blocker_power > 0:
                    damage_events_typed.append(
                        ("creature", attacker.id, blocker_power,
                         blocker.id, blocker_kws, blocker.controller_id)
                    )

    # Combat damage in MTG is simultaneous, so aggregate damage to each
    # player into a single end-of-step log line ("P0 takes 5 (life:
    # 15)") instead of one line per attacker. Creature damage,
    # lifelink, and infect-poison events stay per-source because each
    # one can independently matter for triggers and SBAs.
    player_life_damage: dict[int, int] = {}
    sources_hit_player: list[tuple[int, int, int]] = []
    for (
        kind, target_id, amount, source_id, source_kws, source_controller,
    ) in damage_events_typed:
        if amount <= 0:
            continue
        has_infect = "infect" in source_kws
        if kind == "player":
            p = state.player_by_id(target_id)
            if has_infect:
                # Infect: damage to a player becomes that many poison
                # counters instead of life loss. Per-event log preserved
                # so the source/amount remains traceable.
                p.poison_counters += amount
                state.log.append(
                    f"P{target_id} gets {amount} poison counter(s) "
                    f"from infect (now {p.poison_counters})"
                )
            else:
                p.life -= amount
                player_life_damage[target_id] = (
                    player_life_damage.get(target_id, 0) + amount
                )
            sources_hit_player.append((source_id, target_id, amount))
        else:
            obj = next((o for o in state.battlefield if o.id == target_id), None)
            if obj is not None:
                if has_infect:
                    # Infect: damage to a creature becomes -1/-1
                    # counters. The engine doesn't currently track
                    # -1/-1 counters as a distinct field; we fold
                    # them into temp_power/toughness bonuses (UEOT)
                    # as a simplification — functionally lethal for
                    # this-turn damage math, which is what infect
                    # generally ends up doing in our sim.
                    obj.temp_power_bonus -= amount
                    obj.temp_toughness_bonus -= amount
                    state.log.append(
                        f"{obj.printing.name} takes {amount} -1/-1 "
                        f"from infect"
                    )
                else:
                    obj.damage += amount
                    obj.damaged_this_turn = True
                if "deathtouch" in source_kws:
                    obj.marked_lethal = True
                # Fire "whenever enchanted creature is dealt damage"
                # observer triggers on auras attached to obj.
                _fire_enchanted_dealt_damage_triggers(
                    state, obj, amount,
                )
        # Lifelink: the source's controller gains life equal to the damage
        # dealt, regardless of target kind.
        if "lifelink" in source_kws:
            from mtg_bot.game import gain_life
            gain_life(state, source_controller, amount)
            gainer = state.player_by_id(source_controller)
            state.log.append(
                f"P{source_controller} gains {amount} life (life: {gainer.life})"
            )

    # Emit aggregated player-damage lines after all events applied so
    # the "(life: N)" reading reflects the final post-step total.
    for target_id, total in player_life_damage.items():
        p = state.player_by_id(target_id)
        state.log.append(
            f"P{target_id} takes {total} (life: {p.life})"
        )

    # Fire "whenever this creature deals combat damage to a player" triggers
    # for each (source, target_player) pair that actually dealt damage.
    _fire_combat_damage_to_player_triggers(state, sources_hit_player)


def _fire_enchanted_dealt_damage_triggers(
    state: GameState, obj: "GameObject", amount: int,
) -> None:
    """Fire "whenever enchanted creature is dealt damage" triggers on
    auras attached to ``obj``. Amount exposed via
    state.resolving_combat_damage_amount for effects that want to
    read it (e.g., Pain for All's echo-damage-to-each-opponent).
    """
    from mtg_bot.turn import should_fire_trigger

    for aura in list(state.battlefield):
        if aura.attached_to != obj.id:
            continue
        if not aura.printing.is_aura:
            continue
        for i, ability in enumerate(aura.printing.triggered_abilities):
            if ability.trigger != "enchanted_creature_dealt_damage":
                continue
            if not should_fire_trigger(state, aura.id, i, ability):
                continue
            state.log.append(
                f"{aura.printing.name}'s dealt-damage trigger fires"
            )
            state.resolving_source = aura
            state.resolving_combat_damage_amount = amount
            try:
                ability.effect.resolve(state, aura.controller_id, ())
            finally:
                state.resolving_source = None
                state.resolving_combat_damage_amount = 0


def _fire_combat_damage_to_player_triggers(
    state: GameState, sources_hit_player: list[tuple[int, int, int]]
) -> None:
    """For each (source_id, target_player_id, amount) triple, fire:
    - the source's own ``combat_damage_to_player`` triggers (via the
      stack — opponents get a chance to respond at instant speed),
    - observer triggers on other permanents whose controllers see one
      of their own (nontoken artifact) creatures dealing combat damage
      (Virulent Silencer), and
    - "whenever a creature you control deals combat damage to a player"
      observer triggers (Starwinder's draw-that-many).

    The source's-own trigger goes on the stack as a StackItem with the
    damage amount stashed in ``combat_damage_amount`` so the effect can
    still read "that many" when it eventually resolves. Targets are
    picked at trigger time, matching the ETB-trigger flow.

    Observer triggers (artifact-creature-damage, your-creature-damage,
    creature-deals-combat-damage-to-you) currently still resolve
    immediately; reaching for the stack on those is a separate concern.
    During those immediate resolutions,
    ``state.resolving_combat_damage_amount`` carries the damage amount.
    """
    from mtg_bot.actions import _format_log_targets
    from mtg_bot.game import StackItem
    from mtg_bot.turn import should_fire_trigger

    for source_id, target_player, amount in sources_hit_player:
        source = next(
            (o for o in state.battlefield if o.id == source_id), None
        )
        if source is None:
            continue  # source died from simultaneous damage
        # Source's own triggers — go on the stack so opponents get a
        # window to respond at instant speed before the ability resolves.
        for i, ability in enumerate(source.printing.triggered_abilities):
            if ability.trigger != "combat_damage_to_player":
                continue
            if not should_fire_trigger(state, source.id, i, ability):
                continue
            controller_id = source.controller_id
            effect = ability.effect
            targets: tuple[tuple[str, int], ...] = ()
            min_t, max_t = effect.target_count_range()
            if max_t > 0:
                state.resolving_source = source
                state.resolving_combat_damage_amount = amount
                try:
                    legal = effect.legal_targets(state, controller_id)
                finally:
                    state.resolving_source = None
                    state.resolving_combat_damage_amount = 0
                if not legal and min_t > 0:
                    state.log.append(
                        f"{source.printing.name}'s "
                        f"combat-damage-to-player trigger has no legal "
                        f"targets; trigger fizzles"
                    )
                    continue
                controller = state.player_by_id(controller_id)
                chosen_list: list[tuple[str, int]] = []
                remaining = list(legal)
                for _ in range(max_t):
                    if not remaining:
                        break
                    if controller.agent is None:  # pragma: no cover
                        break
                    pick = controller.agent.choose_target(
                        state, controller_id, remaining
                    )
                    if pick is None or pick not in remaining:
                        break
                    chosen_list.append(pick)
                    remaining.remove(pick)
                if len(chosen_list) < min_t:  # pragma: no cover
                    state.log.append(
                        f"{source.printing.name}'s "
                        f"combat-damage-to-player trigger had no target "
                        f"chosen; trigger fizzles"
                    )
                    continue
                targets = tuple(chosen_list)
            state.stack.append(
                StackItem(
                    source=source,
                    controller_id=controller_id,
                    ability=ability,
                    targets=targets,
                    combat_damage_amount=amount,
                )
            )
            state.log.append(
                f"{source.printing.name}'s combat-damage-to-player "
                f"trigger goes on the stack"
                + _format_log_targets(state, targets)
            )

        # Observer: "whenever a nontoken artifact creature you control
        # deals combat damage to a player".
        if (
            source.printing.is_artifact
            and source.printing.is_creature
            and not source.printing.is_token
        ):
            for obs in list(state.battlefield):
                if obs.controller_id != source.controller_id:
                    continue
                for i, ability in enumerate(obs.printing.triggered_abilities):
                    if ability.trigger != (
                        "your_nontoken_artifact_creature_"
                        "combat_damage_to_player"
                    ):
                        continue
                    if not should_fire_trigger(state, obs.id, i, ability):
                        continue
                    state.log.append(
                        f"{obs.printing.name}'s artifact-creature-damage "
                        f"trigger fires (P{target_player} was hit)"
                    )
                    state.resolving_source = obs
                    state.resolving_combat_damage_amount = amount
                    try:
                        ability.effect.resolve(
                            state, obs.controller_id,
                            (("player", target_player),),
                        )
                    finally:
                        state.resolving_source = None
                        state.resolving_combat_damage_amount = 0

        # Observer: "whenever a creature you control deals combat
        # damage to a player" — Starwinder.
        for obs in list(state.battlefield):
            if obs.controller_id != source.controller_id:
                continue
            for i, ability in enumerate(obs.printing.triggered_abilities):
                if ability.trigger != (
                    "your_creature_combat_damage_to_player"
                ):
                    continue
                if not should_fire_trigger(state, obs.id, i, ability):
                    continue
                state.log.append(
                    f"{obs.printing.name}'s creature-damage-to-player "
                    f"trigger fires (P{target_player} took {amount})"
                )
                state.resolving_source = obs
                state.resolving_combat_damage_amount = amount
                try:
                    ability.effect.resolve(
                        state, obs.controller_id,
                        (("player", target_player),),
                    )
                finally:
                    state.resolving_source = None
                    state.resolving_combat_damage_amount = 0

        # Observer: "whenever a creature deals combat damage to you" —
        # fires on permanents the hit player controls. Used by
        # Contested War Zone's "that creature's controller gains
        # control of this land".
        attacker_controller_id = source.controller_id
        for obs in list(state.battlefield):
            if obs.controller_id != target_player:
                continue
            for i, ability in enumerate(obs.printing.triggered_abilities):
                if ability.trigger != "creature_deals_combat_damage_to_you":
                    continue
                if not should_fire_trigger(state, obs.id, i, ability):
                    continue
                state.log.append(
                    f"{obs.printing.name}'s combat-damage-to-you trigger "
                    f"fires (P{target_player} was hit by "
                    f"{source.printing.name})"
                )
                state.resolving_source = obs
                state.resolving_combat_damage_amount = amount
                state.resolving_combat_damage_source_controller_id = (
                    attacker_controller_id
                )
                try:
                    ability.effect.resolve(state, obs.controller_id, ())
                finally:
                    state.resolving_source = None
                    state.resolving_combat_damage_amount = 0
                    state.resolving_combat_damage_source_controller_id = None


def clear_combat_state(state: GameState) -> None:
    # Process "sacrifice at end of combat" schedules (Kavaron Harrier
    # attack token). Done before attacking flags clear so the sacrifice
    # still resolves with combat state intact if any observer cares.
    if state.pending_end_of_combat_sacrifices:
        from mtg_bot.turn import sacrifice as _sacrifice

        scheduled = list(state.pending_end_of_combat_sacrifices)
        state.pending_end_of_combat_sacrifices = []
        for tid in scheduled:
            obj = next((o for o in state.battlefield if o.id == tid), None)
            if obj is not None:
                state.log.append(
                    f"end of combat: sacrifice {obj.printing.name}"
                )
                _sacrifice(state, obj)
    for obj in state.battlefield:
        obj.attacking = False
        obj.blocking = None
        obj.blocked_by = []
