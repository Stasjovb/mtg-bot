"""Action-recommendation API contract.

Consumed by the UI's "engine recommendations" panel. Two entry points:

- ``recommend_from_state(engine_state, *, name_to_id, n)`` — the real
  PIMC-driven path. Wraps the engine state in an MtgGameStateAdapter,
  runs PIMC with a small budget, ranks decisions by aggregated visit
  count, and returns them as Recommendation dicts. Sets
  ``engine = "pimc"`` in the result.
- ``recommend_from_snapshot(snap, n)`` — fallback stub for callers that
  only have a serialized snapshot (legacy tests, external consumers).
  Enumerates obvious options at sorcery timing with score 0.0 and
  ``engine = "stub"``.

The frontend renders against the response shape — it's the same in both
paths. Score is the decision's share of total root visits in the PIMC
case, 0.0 in the stub case.
"""

from __future__ import annotations

import random
import re
from typing import Any, Optional

from mtg_bot.actions import (
    Action, ActivateAbility, ActivateStation, CastSpell,
    DeclareAttackers, DeclareBlockers, PassPriority, PlayLand,
)
from mtg_bot.game import GameObject, GameState, Zone

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


def _approx_cmc(mana_cost: Optional[str]) -> int:
    """Sum the converted mana cost of a Scryfall-style cost string like
    ``{2}{W}{W}`` -> 4. ``X`` is treated as 0 (a permissive lower
    bound — even casting for X=0 still requires the named cost). Hybrid,
    phyrexian, and colorless pip symbols each count as 1 mana of generic
    value, which is the correct lower bound on what's required."""
    if not mana_cost:
        return 0
    total = 0
    for sym in re.findall(r"\{([^}]*)\}", mana_cost):
        if sym.isdigit():
            total += int(sym)
        elif sym.upper() == "X":
            continue
        else:
            total += 1
    return total


def _available_mana(player: dict[str, Any]) -> int:
    """Approximate amount of mana the player can produce right now: every
    untapped land plus any mana already floating in the pool. Used to
    filter out obviously-unaffordable spells in the replay-mode stub.

    Color requirements and tap-for-N producers (Sol Ring, etc.) are
    ignored. The real PIMC path uses ``recommend_from_state`` which
    checks legality against the live engine — this is only a coarse
    sanity filter so the panel doesn't suggest casting Banishing Light
    on turn 1."""
    untapped = 0
    for o in player.get("battlefield", []):
        if "land" in (o.get("type_line") or "").lower() and not o.get("tapped"):
            untapped += 1
    floating = len(player.get("mana_pool", []))
    return untapped + floating


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

    # Sorcery-speed actions (playing lands, casting non-instants) require
    # main phase + empty stack + the priority holder is also the active
    # player. Without the active-player check the stub recommended turn-1
    # spells to whoever held priority instead of the actual active player.
    is_sorcery_timing = (
        snap.get("step") in _SORCERY_STEPS
        and not snap.get("stack")
        and snap.get("active_player_idx") == priority_player_id
    )

    if is_sorcery_timing:
        available = _available_mana(player)
        for card in player.get("hand", []):
            if _is_land_card(card):
                if player.get("lands_played_this_turn", 0) == 0:
                    recs.append(_hand_card_rec(card, "PlayLand"))
            else:
                # Filter out spells the player obviously can't pay for.
                # The stub doesn't have engine access, so we approximate
                # via "untapped lands + floating mana >= cmc". Misses
                # color requirements but catches the common turn-1
                # "Cast Banishing Light with no mana" case.
                if _approx_cmc(card.get("mana_cost")) <= available:
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


# ------------------------------------------------------------------------
# PIMC-driven recommender. Real engine path.
# ------------------------------------------------------------------------

# Per-recommendation-call PIMC budget. Conservative defaults so the
# UI feels responsive (~hundreds of ms on a recent CPU). Tune from
# real numbers when we have them; exposed as module-level constants
# so a future caller can swap them per-request without changing the
# function signature.
_PIMC_SAMPLES = 4
_PIMC_INNER_BUDGET_NODES = 200
_PIMC_RNG_SEED = 0  # deterministic recommendations for the same snapshot

_RECOMMEND_ENGINE_NAME = "pimc"
_RECOMMEND_ENGINE_VERSION = "0.1.0"


def recommend_from_state(
    engine_state: GameState,
    *,
    name_to_id: Optional[dict[str, str]] = None,
    n: int = 3,
) -> dict[str, Any]:
    """Real engine recommender.

    Wraps ``engine_state`` in an ``MtgGameStateAdapter``, runs PIMC
    with a small budget, ranks legal decisions by aggregated visit
    count, and returns the top-N as Recommendation dicts. Score is
    each decision's share of total root visits — so the visible
    numbers always sum to 1.0 across the returned list (modulo the
    top-N truncation).

    ``name_to_id`` maps card names to Scryfall ids for image rendering;
    pass the same dict the UI builds at startup. None disables image
    annotations (every recommendation gets ``scryfall_id = None``).

    Returns the empty-recommendations result when the game is over,
    matching the stub's behavior.
    """
    # Imported lazily because mtg_bot.search transitively pulls in a
    # large slice of the engine; recommend.py itself is imported by
    # ui.py at startup, and we don't want to drag the search stack
    # into modules that only call recommend_from_snapshot.
    from mtg_bot.search.budget import Budget
    from mtg_bot.search.engine_adapter import MtgGameStateAdapter
    from mtg_bot.search.heuristic_evaluator import MtgHeuristicEvaluator
    from mtg_bot.search.mcts import MCTS
    from mtg_bot.search.pimc import PIMC

    if engine_state.is_over():
        return _finalize_engine(
            recs=[],
            priority_player_id=engine_state.priority_player_idx,
        )

    adapter = MtgGameStateAdapter(engine_state.clone())
    if adapter.is_terminal():
        return _finalize_engine(
            recs=[],
            priority_player_id=engine_state.priority_player_idx,
        )

    viewer_id = adapter.active_player()

    def _make_inner() -> MCTS:
        return MCTS(
            evaluator=MtgHeuristicEvaluator(),
            budget_factory=lambda: Budget(
                max_nodes=_PIMC_INNER_BUDGET_NODES
            ),
            rng=random.Random(_PIMC_RNG_SEED),
        )

    pimc = PIMC(
        inner_factory=_make_inner,
        samples=_PIMC_SAMPLES,
        rng=random.Random(_PIMC_RNG_SEED),
    )
    visits = pimc.choose_with_visits(adapter, viewer_id)
    total = sum(visits.values()) or 1  # avoid div-by-zero on edge cases

    recs: list[dict[str, Any]] = []
    for decision, count in sorted(
        visits.items(), key=lambda kv: kv[1], reverse=True,
    ):
        rec = _decision_to_rec(
            decision, engine_state, name_to_id or {},
        )
        if rec is None:
            continue
        rec["score"] = count / total
        recs.append(rec)

    return _finalize_engine(recs[:n], priority_player_id=viewer_id)


def _finalize_engine(
    recs: list[dict[str, Any]], priority_player_id: int,
) -> dict[str, Any]:
    return {
        "priority_player_id": priority_player_id,
        "recommendations": recs,
        "engine": _RECOMMEND_ENGINE_NAME,
        "engine_version": _RECOMMEND_ENGINE_VERSION,
    }


def _decision_to_rec(
    decision: Action,
    state: GameState,
    name_to_id: dict[str, str],
) -> Optional[dict[str, Any]]:
    """Translate one search-side ``Action`` into the Recommendation
    dict shape the UI expects. Returns None if the action type isn't
    one we know how to label — the caller filters those out so an
    unrecognized action never reaches the UI in mid-broken form.
    """
    if isinstance(decision, PassPriority):
        return _rec(
            label="Pass priority", action_type="PassPriority",
            source_id=None, source_name=None,
            scryfall_id=None, detail=None,
        )
    if isinstance(decision, PlayLand):
        card = _find_card_by_id(state, decision.card_id)
        name = card.printing.name if card else f"#{decision.card_id}"
        return _rec(
            label=f"Play {name}", action_type="PlayLand",
            source_id=decision.card_id, source_name=name,
            scryfall_id=name_to_id.get(name), detail=None,
        )
    if isinstance(decision, CastSpell):
        card = _find_card_by_id(state, decision.card_id)
        name = card.printing.name if card else f"#{decision.card_id}"
        bits: list[str] = []
        if card and card.printing.mana_cost is not None:
            bits.append(str(card.printing.mana_cost))
        if decision.use_warp:
            bits.append("warp")
        if decision.kicked:
            bits.append("kicker")
        detail = " · ".join(bits) if bits else None
        return _rec(
            label=f"Cast {name}", action_type="CastSpell",
            source_id=decision.card_id, source_name=name,
            scryfall_id=name_to_id.get(name), detail=detail,
        )
    if isinstance(decision, ActivateAbility):
        card = _find_card_by_id(state, decision.source_id)
        name = card.printing.name if card else f"#{decision.source_id}"
        return _rec(
            label=f"Activate ability of {name}",
            action_type="ActivateAbility",
            source_id=decision.source_id, source_name=name,
            scryfall_id=name_to_id.get(name),
            detail=f"ability {decision.ability_index}",
        )
    if isinstance(decision, ActivateStation):
        ship = _find_card_by_id(state, decision.spacecraft_id)
        crew = _find_card_by_id(state, decision.crew_id)
        ship_name = ship.printing.name if ship else f"#{decision.spacecraft_id}"
        crew_name = crew.printing.name if crew else f"#{decision.crew_id}"
        return _rec(
            label=f"Station {crew_name} on {ship_name}",
            action_type="ActivateStation",
            source_id=decision.spacecraft_id, source_name=ship_name,
            scryfall_id=name_to_id.get(ship_name),
            detail=f"crew: {crew_name}",
        )
    if isinstance(decision, DeclareAttackers):
        count = len(decision.attacker_ids)
        return _rec(
            label=(
                "Attack with no creatures" if count == 0
                else f"Attack with {count} creature{'s' if count != 1 else ''}"
            ),
            action_type="DeclareAttackers",
            source_id=None, source_name=None,
            scryfall_id=None, detail=None,
        )
    if isinstance(decision, DeclareBlockers):
        count = len(decision.assignments)
        return _rec(
            label=(
                "Don't block" if count == 0
                else f"Assign {count} blocker{'s' if count != 1 else ''}"
            ),
            action_type="DeclareBlockers",
            source_id=None, source_name=None,
            scryfall_id=None, detail=None,
        )
    return None


def _rec(
    *, label: str, action_type: str, source_id: Optional[int],
    source_name: Optional[str], scryfall_id: Optional[str],
    detail: Optional[str],
) -> dict[str, Any]:
    return {
        "label": label,
        "score": 0.0,  # caller overwrites
        "action_type": action_type,
        "source_id": source_id,
        "source_name": source_name,
        "scryfall_id": scryfall_id,
        "detail": detail,
    }


def _find_card_by_id(
    state: GameState, card_id: int,
) -> Optional[GameObject]:
    """Look up a GameObject by id across every zone the action types
    we care about reference (hand for cast/play, battlefield for
    activated abilities and stations). Walks zones in order; returns
    the first match. None if the id isn't on the board (shouldn't
    arise for legal decisions, but fail soft so the UI never crashes
    on a stale recommendation)."""
    for o in state.battlefield:
        if o.id == card_id:
            return o
    for p in state.players:
        for o in p.hand:
            if o.id == card_id:
                return o
    return None
