"""Action-recommendation API contract.

Consumed by the UI's "engine recommendations" panel. Exposes a single function
(``recommend_from_snapshot``) that returns the top-N moves the engine would
suggest at a given game state, each with a score. This file only ships a
**stub** implementation — it reads the serialized snapshot, enumerates
plausible actions, and gives every one a score of 0.0. The real evaluator
is being built in a separate workstream and is expected to replace the
scoring loop while preserving the output shape.

The contract (see ``Recommendation`` and ``RecommendationResult`` below)
is the interface the frontend depends on. Anything outside this module can
change freely — anything in the returned dict is a promise.
"""

from __future__ import annotations

from typing import Any

# ------------------------------------------------------------------------
# Output schema. Frozen: the UI renders against these field names.
# ------------------------------------------------------------------------
#
# A single recommendation:
#   {
#     "label":       str,                   # human readable, e.g. "Cast Goblin Runner"
#     "score":       float,                 # larger = better for priority player
#     "action_type": str,                   # "CastSpell" | "PlayLand" | "PassPriority"
#                                           #  | "ActivateAbility" | "ActivateStation"
#                                           #  | "DeclareAttackers" | "DeclareBlockers"
#     "source_id":    int | None,           # GameObject.id the action acts on, if any
#     "source_name":  str | None,           # card name, for rendering
#     "scryfall_id":  str | None,           # Scryfall id for card image
#     "detail":       str | None,           # optional subtitle (mana cost, P/T, etc.)
#   }
#
# A full result:
#   {
#     "snapshot_idx":       int,
#     "priority_player_id": int,
#     "recommendations":    list[Recommendation],
#     "engine":             str,            # identifies the implementation
#     "engine_version":     str,
#   }
#
# Stub implementations MAY return score=0.0 for everything and SHOULD set
# ``engine = "stub"`` so the UI can render a "not yet evaluated" hint.


_SORCERY_STEPS = {"precombat_main", "postcombat_main"}


def _is_land_card(card: dict[str, Any]) -> bool:
    type_line = (card.get("type_line") or "").lower()
    return "land" in type_line


def _hand_card_rec(card: dict[str, Any], action_type: str) -> dict[str, Any]:
    verb = "Play" if action_type == "PlayLand" else "Cast"
    rec: dict[str, Any] = {
        "label": f"{verb} {card['name']}",
        "score": 0.0,
        "action_type": action_type,
        "source_id": card.get("id"),
        "source_name": card["name"],
        "scryfall_id": card.get("scryfall_id"),
        "detail": None,
    }
    mana = card.get("mana_cost")
    if mana and action_type != "PlayLand":
        rec["detail"] = mana
    return rec


def recommend_from_snapshot(
    snap: dict[str, Any],
    n: int = 3,
) -> dict[str, Any]:
    """Stub recommender.

    Reads the serialized snapshot, enumerates the most obvious options for
    whoever has priority, and returns them scored at 0.0. The real engine
    replaces the scoring + ranking; the shape this function returns is the
    frontend-facing contract and must not change.
    """
    priority_player_id = snap["priority_player_idx"]
    player = next(
        (p for p in snap["players"] if p["id"] == priority_player_id),
        None,
    )
    recs: list[dict[str, Any]] = []

    if player is None or snap.get("is_over"):
        return _finalize(recs, priority_player_id, n)

    # Always include a Pass option — this is the safest ground truth.
    recs.append({
        "label": "Pass priority",
        "score": 0.0,
        "action_type": "PassPriority",
        "source_id": None,
        "source_name": None,
        "scryfall_id": None,
        "detail": None,
    })

    # Most interesting choices are at sorcery timing: main phase, empty stack,
    # you have priority (which is what priority_player_idx tells us).
    is_sorcery_timing = (
        snap.get("step") in _SORCERY_STEPS
        and not snap.get("stack")
    )

    if is_sorcery_timing:
        for card in player.get("hand", []):
            if _is_land_card(card):
                if player.get("lands_played_this_turn", 0) == 0:
                    recs.append(_hand_card_rec(card, "PlayLand"))
            else:
                recs.append(_hand_card_rec(card, "CastSpell"))

    return _finalize(recs, priority_player_id, n)


def _finalize(
    recs: list[dict[str, Any]],
    priority_player_id: int,
    n: int,
) -> dict[str, Any]:
    return {
        "priority_player_id": priority_player_id,
        "recommendations": recs[:n],
        "engine": "stub",
        "engine_version": "0.0.1",
    }
