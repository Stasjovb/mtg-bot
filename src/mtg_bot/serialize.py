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
        "is_stationed": is_stationed(obj),
        "station_threshold": p.station_threshold,
        "charge_counters": obj.charge_counters,
        "keywords": sorted(effective_keywords(state, obj)),
        "abilities": [a.describe() for a in p.triggered_abilities],
        "static_abilities": [sa.describe() for sa in p.static_abilities],
        "warp_cost": p.warp_cost_str or None,
        "tapped": obj.tapped,
        "damage": obj.damage,
        "summoning_sick": obj.summoning_sick,
        "attacking": obj.attacking,
        "blocking": obj.blocking,
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
                "controller_id": item.controller_id,
                "is_ability": item.ability is not None,
                "ability_description": (
                    item.ability.describe() if item.ability is not None else None
                ),
                "targets": [
                    {"kind": kind, "id": tid} for kind, tid in item.targets
                ],
            }
            for item in state.stack
        ],
        "log": list(state.log),
        "winner_id": state.winner_id,
        "is_draw": state.is_draw,
        "is_over": state.is_over(),
    }
