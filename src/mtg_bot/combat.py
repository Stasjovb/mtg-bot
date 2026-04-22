"""Combat: eligibility, declaration, and simultaneous damage."""

from __future__ import annotations

from mtg_bot.game import GameObject, GameState


def eligible_attackers(state: GameState, player_id: int) -> list[GameObject]:
    return [
        o for o in state.battlefield
        if o.controller_id == player_id
        and o.printing.is_creature
        and not o.tapped
        and (not o.summoning_sick or "haste" in o.printing.keywords)
    ]


def eligible_blockers(state: GameState, player_id: int) -> list[GameObject]:
    return [
        o for o in state.battlefield
        if o.controller_id == player_id
        and o.printing.is_creature
        and not o.tapped
    ]


def can_block(blocker: GameObject, attacker: GameObject) -> bool:
    """Return True if ``blocker`` may legally declare a block against ``attacker``.

    Flying: a creature with flying can only be blocked by creatures with flying
    or reach.
    """
    if "flying" in attacker.printing.keywords:
        if not (
            "flying" in blocker.printing.keywords
            or "reach" in blocker.printing.keywords
        ):
            return False
    return True


def declare_attackers(state: GameState, attacker_ids: list[int]) -> None:
    for oid in attacker_ids:
        obj = next(o for o in state.battlefield if o.id == oid)
        obj.attacking = True
        # Vigilance: attacking doesn't tap
        if "vigilance" not in obj.printing.keywords:
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


def resolve_combat_damage(state: GameState, defending_player_id: int) -> None:
    """Assign and deal all combat damage simultaneously."""
    # Stage 1: no first strike, no trample. Each attacker deals damage to its
    # blockers in blocker-declaration order (lethal to each before next). Without
    # trample, leftover damage past all blockers is lost.
    damage_events: list[tuple[str, int, int]] = []  # (kind, target_id, amount)

    for attacker in state.battlefield:
        if not attacker.attacking:
            continue
        blockers = [o for o in state.battlefield if o.id in attacker.blocked_by]
        attacker_power = attacker.printing.power or 0
        if not blockers:
            damage_events.append(("player", defending_player_id, attacker_power))
        else:
            remaining = attacker_power
            for i, blocker in enumerate(blockers):
                if remaining <= 0:
                    break
                need = max(0, (blocker.printing.toughness or 0) - blocker.damage)
                if i == len(blockers) - 1:
                    assigned = remaining
                else:
                    assigned = min(remaining, need)
                damage_events.append(("creature", blocker.id, assigned))
                remaining -= assigned
            for blocker in blockers:
                blocker_power = blocker.printing.power or 0
                if blocker_power > 0:
                    damage_events.append(("creature", attacker.id, blocker_power))

    for kind, target_id, amount in damage_events:
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


def clear_combat_state(state: GameState) -> None:
    for obj in state.battlefield:
        obj.attacking = False
        obj.blocking = None
        obj.blocked_by = []
