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
    for oid in attacker_ids:
        obj = next(o for o in state.battlefield if o.id == oid)
        obj.attacking = True
        # Vigilance: attacking doesn't tap
        if "vigilance" not in effective_keywords(state, obj):
            obj.tapped = True
        state.log.append(f"{obj.printing.name} attacks")


def declare_blockers(state: GameState, assignments: dict[int, int]) -> None:
    """``assignments`` maps blocker id → attacker id."""
    for blocker_id, attacker_id in assignments.items():
        blocker = next(o for o in state.battlefield if o.id == blocker_id)
        attacker = next(o for o in state.battlefield if o.id == attacker_id)
        blocker.blocking = attacker_id
        attacker.blocked_by.append(blocker_id)
        state.log.append(f"{blocker.printing.name} blocks {attacker.printing.name}")


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
    # Event tuple layout: (kind, target_id, amount, source_keywords, source_controller_id)
    damage_events_typed: list[tuple[str, int, int, frozenset[str], int]] = []

    for attacker in state.battlefield:
        if not attacker.attacking:
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
                         blocker_kws, blocker.controller_id)
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
                 attacker_kws, attacker_controller)
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
                     attacker_kws, attacker_controller)
                )
                remaining -= assigned
            if has_trample and remaining > 0:
                damage_events_typed.append(
                    ("player", defending_player_id, remaining,
                     attacker_kws, attacker_controller)
                )
            for blocker in blockers:
                blocker_kws = effective_keywords(state, blocker)
                if not _deals_in_step(blocker_kws, first_strike_step=first_strike_step):
                    continue
                blocker_power = effective_power(state, blocker)
                if blocker_power > 0:
                    damage_events_typed.append(
                        ("creature", attacker.id, blocker_power,
                         blocker_kws, blocker.controller_id)
                    )

    for kind, target_id, amount, source_kws, source_controller in damage_events_typed:
        if amount <= 0:
            continue
        if kind == "player":
            p = state.player_by_id(target_id)
            p.life -= amount
            state.log.append(f"P{target_id} takes {amount} (life: {p.life})")
        else:
            obj = next((o for o in state.battlefield if o.id == target_id), None)
            if obj is not None:
                obj.damage += amount
                if "deathtouch" in source_kws:
                    obj.marked_lethal = True
        # Lifelink: the source's controller gains life equal to the damage
        # dealt, regardless of target kind.
        if "lifelink" in source_kws:
            gainer = state.player_by_id(source_controller)
            gainer.life += amount
            state.log.append(
                f"P{source_controller} gains {amount} life (life: {gainer.life})"
            )


def clear_combat_state(state: GameState) -> None:
    for obj in state.battlefield:
        obj.attacking = False
        obj.blocking = None
        obj.blocked_by = []
