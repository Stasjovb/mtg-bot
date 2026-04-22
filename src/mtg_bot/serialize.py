"""Convert a GameState into a plain dict for rendering (UI, JSON, logs).

Kept separate from the Flask layer so it can be unit-tested without spinning up
a web server.
"""

from __future__ import annotations

from typing import Any

from mtg_bot.game import GameObject, GameState


def serialize_permanent(obj: GameObject) -> dict[str, Any]:
    p = obj.printing
    return {
        "id": obj.id,
        "name": p.name,
        "type_line": p.type_line,
        "mana_cost": p.mana_cost_str,
        "power": p.power,
        "toughness": p.toughness,
        "is_creature": p.is_creature,
        "is_land": p.is_land,
        "keywords": sorted(p.keywords),
        "abilities": [a.describe() for a in p.triggered_abilities],
        "tapped": obj.tapped,
        "damage": obj.damage,
        "summoning_sick": obj.summoning_sick,
        "attacking": obj.attacking,
        "blocking": obj.blocking,
    }


def serialize_hand_card(obj: GameObject) -> dict[str, Any]:
    p = obj.printing
    return {
        "id": obj.id,
        "name": p.name,
        "mana_cost": p.mana_cost_str,
        "type_line": p.type_line,
        "power": p.power,
        "toughness": p.toughness,
        "keywords": sorted(p.keywords),
        "abilities": [a.describe() for a in p.triggered_abilities],
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
            "has_lost": p.has_lost,
            "lost_reason": p.lost_reason,
            "lands_played_this_turn": p.lands_played_this_turn,
            "battlefield": [
                serialize_permanent(o)
                for o in state.battlefield
                if o.controller_id == p.id
            ],
        })

    return {
        "turn_number": state.turn_number,
        "active_player_idx": state.active_player_idx,
        "priority_player_idx": state.priority_player_idx,
        "step": state.step.value if state.step is not None else None,
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
            }
            for item in state.stack
        ],
        "log": list(state.log),
        "winner_id": state.winner_id,
        "is_draw": state.is_draw,
        "is_over": state.is_over(),
    }
