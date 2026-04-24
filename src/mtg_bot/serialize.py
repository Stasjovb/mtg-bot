"""Convert a GameState into a plain dict for rendering (UI, JSON, logs).

Kept separate from the Flask layer so it can be unit-tested without spinning up
a web server.
"""

from __future__ import annotations

from typing import Any

from mtg_bot.game import (
    GameObject,
    GameState,
    effective_keywords,
    effective_power,
    effective_toughness,
    is_creature_now,
    is_stationed,
    is_void_active,
)


def _attachment(state: GameState, obj: GameObject) -> dict[str, Any] | None:
    """Return ``{id, name}`` for the permanent this Equipment/Aura is attached
    to, or None if unattached."""
    if obj.attached_to is None:
        return None
    for other in state.battlefield:
        if other.id == obj.attached_to:
            return {"id": other.id, "name": other.printing.name}
    return None


def _attacking_defender(state: GameState, obj: GameObject) -> dict[str, Any] | None:
    """For an attacking creature, return ``{kind, id, name}`` identifying the
    opponent it's swinging at. None if not attacking. The engine currently
    always routes attacks at the next living opponent in turn order; this
    helper mirrors that rule so the UI can render an unambiguous arrow."""
    if not obj.attacking:
        return None
    start = (obj.controller_id + 1) % len(state.players)
    idx = start
    for _ in range(len(state.players)):
        p = state.players[idx]
        if not p.has_lost:
            return {"kind": "player", "id": p.id, "name": f"Player {p.id}"}
        idx = (idx + 1) % len(state.players)
    return None


def serialize_permanent(state: GameState, obj: GameObject) -> dict[str, Any]:
    p = obj.printing
    return {
        "id": obj.id,
        "name": p.name,
        "type_line": p.type_line,
        "mana_cost": p.mana_cost_str,
        "power": p.power,
        "toughness": p.toughness,
        "effective_power": effective_power(state, obj) if is_creature_now(obj) else None,
        "effective_toughness": effective_toughness(state, obj) if is_creature_now(obj) else None,
        "is_creature": p.is_creature,
        "is_creature_now": is_creature_now(obj),
        "is_land": p.is_land,
        "is_token": p.is_token,
        "is_spacecraft": p.is_spacecraft,
        "is_planeswalker": p.loyalty is not None,
        "is_stationed": is_stationed(obj),
        "station_threshold": p.station_threshold,
        "charge_counters": obj.charge_counters,
        "loyalty_counters": obj.loyalty_counters,
        "stun_counters": obj.stun_counters,
        "attached_to": _attachment(state, obj),
        "keywords": sorted(effective_keywords(state, obj)),
        "abilities": [a.describe() for a in p.triggered_abilities],
        "static_abilities": [sa.describe() for sa in p.static_abilities],
        "warp_cost": p.warp_cost_str or None,
        "tapped": obj.tapped,
        "damage": obj.damage,
        "summoning_sick": obj.summoning_sick,
        "attacking": obj.attacking,
        "attacking_defender": _attacking_defender(state, obj),
        "blocking": obj.blocking,
        "blocked_by": list(obj.blocked_by),
        "plus_one_counters": obj.plus_one_counters,
    }


def serialize_hand_card(obj: GameObject) -> dict[str, Any]:
    p = obj.printing
    return {
        "id": obj.id,
        "name": p.name,
        "mana_cost": p.mana_cost_str,
        "warp_cost": p.warp_cost_str or None,
        "type_line": p.type_line,
        "power": p.power,
        "toughness": p.toughness,
        "keywords": sorted(p.keywords),
        "abilities": [a.describe() for a in p.triggered_abilities],
        "warped": obj.warped,
    }


def _resolve_target(state: GameState, kind: str, tid: int) -> dict[str, Any]:
    """Look up the human-readable target referenced by ``(kind, id)`` on the
    stack. Returns ``{kind, id, name}`` where ``name`` is None if the target
    can't be found (already left the battlefield, etc.)."""
    if kind == "player":
        return {"kind": kind, "id": tid, "name": f"Player {tid}"}
    for o in state.battlefield:
        if o.id == tid:
            return {"kind": kind, "id": tid, "name": o.printing.name}
    for item in state.stack:
        if item.source.id == tid:
            return {"kind": kind, "id": tid, "name": item.source.printing.name}
    return {"kind": kind, "id": tid, "name": None}


def serialize_state(state: GameState, reveal_hands: bool = True) -> dict[str, Any]:
    """Return a render-ready dict.

    When ``reveal_hands`` is False, hand contents are hidden (only the count is
    returned). Useful if we later want to hide the opponent's hand.
    """
    players: list[dict[str, Any]] = []
    for p in state.players:
        players.append({
            "id": p.id,
            "life": p.life,
            "hand_size": len(p.hand),
            "hand": [serialize_hand_card(c) for c in p.hand] if reveal_hands else [],
            "library_size": len(p.library),
            "graveyard": [c.printing.name for c in p.graveyard],
            "graveyard_size": len(p.graveyard),
            "exile": [serialize_hand_card(c) for c in p.exile],
            "exile_size": len(p.exile),
            "has_lost": p.has_lost,
            "lost_reason": p.lost_reason,
            "lands_played_this_turn": p.lands_played_this_turn,
            "poison_counters": p.poison_counters,
            "mana_pool": [
                {"color": c.color, "spend_restriction": c.spend_restriction}
                for c in p.mana_pool
            ],
            "battlefield": [
                serialize_permanent(state, o)
                for o in state.battlefield
                if o.controller_id == p.id
            ],
        })

    return {
        "turn_number": state.turn_number,
        "active_player_idx": state.active_player_idx,
        "priority_player_idx": state.priority_player_idx,
        "step": state.step.value if state.step is not None else None,
        "void_active": is_void_active(state),
        "permanent_left_battlefield_this_turn": state.permanent_left_battlefield_this_turn,
        "spell_warped_this_turn": state.spell_warped_this_turn,
        "players": players,
        "stack": [
            {
                "id": item.source.id,
                "name": item.source.printing.name,
                "mana_cost": item.source.printing.mana_cost_str or None,
                "controller_id": item.controller_id,
                "is_ability": item.ability is not None,
                "ability_description": (
                    item.ability.describe() if item.ability is not None else None
                ),
                "targets": [
                    _resolve_target(state, kind, tid) for kind, tid in item.targets
                ],
                "x_value": item.x_value,
                "kicked": item.kicked,
                "countered": item.countered,
            }
            for item in state.stack
        ],
        "log": list(state.log),
        "winner_id": state.winner_id,
        "is_draw": state.is_draw,
        "is_over": state.is_over(),
    }
