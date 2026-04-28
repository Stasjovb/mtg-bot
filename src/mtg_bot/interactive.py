"""Human-vs-bot interactive game sessions.

Each session runs the game loop on a background thread.  The
``InteractiveAgent`` blocks on every decision the human player must make,
serialising the available options to a dict that the Flask polling endpoint
returns to the browser.  When the browser POSTs a response the agent is
unblocked, applies the human choice, and the game thread continues until
the next decision point (which may be the bot's turn, resolved instantly by
RandomAgent, or another human decision).

Public surface used by ui.py:
  - ``create_session(...)`` — factory that starts the game thread
  - ``InteractiveSession`` — holds current snapshot, pending decision, result
  - ``_SESSIONS`` — module-level registry (dict keyed by session_id)
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import uuid4

from mtg_bot.actions import (
    Action,
    ActivateAbility,
    ActivateStation,
    CastSpell,
    PassPriority,
    PlayLand,
)
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.game import GameState, effective_activated_abilities

DECISION_TIMEOUT = 600  # 10 minutes of inactivity kills the game thread
_SESSION_LIMIT = 20     # evict oldest sessions when exceeded


class SessionTimeoutError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Option-serialisation helpers
# ---------------------------------------------------------------------------

def _find_obj(state: GameState, obj_id: int):
    for p in state.players:
        for zone_list in (p.hand, p.library, p.graveyard, p.exile):
            for obj in zone_list:
                if obj.id == obj_id:
                    return obj
    for obj in state.battlefield:
        if obj.id == obj_id:
            return obj
    for item in state.stack:
        if item.source.id == obj_id:
            return item.source
    return None


def _card_opt(state: GameState, obj_id: int, n2id: dict) -> dict:
    obj = _find_obj(state, obj_id)
    if obj is None:
        return {"id": obj_id, "name": f"Card #{obj_id}", "scryfall_id": None}
    name = obj.printing.name
    return {"id": obj_id, "name": name, "scryfall_id": n2id.get(name)}


def _bf_opt(state: GameState, obj_id: int, n2id: dict) -> dict:
    for obj in state.battlefield:
        if obj.id == obj_id:
            name = obj.printing.name
            return {"id": obj_id, "name": name, "scryfall_id": n2id.get(name)}
    return {"id": obj_id, "name": f"Permanent #{obj_id}", "scryfall_id": None}


def _serialize_action(state: GameState, action: Action, n2id: dict) -> dict:
    if isinstance(action, PassPriority):
        return {"type": "pass", "label": "Pass priority"}

    if isinstance(action, PlayLand):
        obj = _find_obj(state, action.card_id)
        name = obj.printing.name if obj else f"Card #{action.card_id}"
        return {
            "type": "play_land",
            "label": f"Play {name}",
            "card_id": action.card_id,
            "name": name,
            "scryfall_id": n2id.get(name),
        }

    if isinstance(action, CastSpell):
        obj = _find_obj(state, action.card_id)
        name = obj.printing.name if obj else f"Card #{action.card_id}"
        suffix = ""
        if action.use_warp:
            suffix = " [Warp]"
        elif action.cast_for_free:
            suffix = " [Free]"
        elif action.kicked:
            suffix = " [Kicked]"
        elif obj is not None and obj.printing.mana_cost_str:
            suffix = f" [{obj.printing.mana_cost_str}]"
        return {
            "type": "cast_spell",
            "label": f"Cast {name}{suffix}",
            "card_id": action.card_id,
            "name": name,
            "scryfall_id": n2id.get(name),
            "use_warp": action.use_warp,
            "kicked": action.kicked,
            "cast_for_free": action.cast_for_free,
        }

    if isinstance(action, ActivateAbility):
        obj = _find_obj(state, action.source_id)
        if obj is not None:
            abilities = effective_activated_abilities(state, obj)
            if 0 <= action.ability_index < len(abilities):
                ability_desc = abilities[action.ability_index].describe()
            else:
                ability_desc = f"Ability {action.ability_index}"
            name = obj.printing.name
        else:
            name = f"Permanent #{action.source_id}"
            ability_desc = f"Ability {action.ability_index}"
        return {
            "type": "activate",
            "label": f"{name}: {ability_desc}",
            "source_id": action.source_id,
            "ability_index": action.ability_index,
            "name": name,
            "scryfall_id": n2id.get(name) if obj else None,
        }

    if isinstance(action, ActivateStation):
        sc = _find_obj(state, action.spacecraft_id)
        crew = _find_obj(state, action.crew_id)
        sc_name = sc.printing.name if sc else f"Spacecraft #{action.spacecraft_id}"
        crew_name = crew.printing.name if crew else f"Creature #{action.crew_id}"
        return {
            "type": "station",
            "label": f"Station {sc_name} (crew {crew_name})",
            "spacecraft_id": action.spacecraft_id,
            "crew_id": action.crew_id,
        }

    return {"type": "unknown", "label": repr(action)}


# ---------------------------------------------------------------------------
# InteractiveAgent
# ---------------------------------------------------------------------------

class InteractiveAgent(Agent):
    """Blocks on every decision method and waits for a browser response."""

    name = "human"

    def __init__(self, n2id: dict[str, str]):
        self._n2id = n2id
        self._lock = threading.Lock()
        self._pending: Optional[dict] = None
        self._response_event = threading.Event()
        self._raw_response: Any = None
        self.timed_out = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ask(self, pending: dict) -> Any:
        with self._lock:
            self._pending = pending
            self._response_event.clear()
        if not self._response_event.wait(timeout=DECISION_TIMEOUT):
            self.timed_out = True
            raise SessionTimeoutError("Human player timed out")
        with self._lock:
            resp = self._raw_response
            self._pending = None
            self._raw_response = None
        return resp

    def get_pending(self) -> Optional[dict]:
        with self._lock:
            return dict(self._pending) if self._pending is not None else None

    def submit_response(self, response: Any) -> None:
        with self._lock:
            self._raw_response = response
        self._response_event.set()

    # ------------------------------------------------------------------
    # Agent interface — all 16 decision methods
    # ------------------------------------------------------------------

    def choose_action(self, state, player_id, legal):
        options = [
            {"idx": i, **_serialize_action(state, a, self._n2id)}
            for i, a in enumerate(legal)
        ]
        resp = self._ask({"type": "choose_action", "options": options})
        idx = int(resp["idx"])
        if not 0 <= idx < len(legal):
            raise ValueError(f"choose_action idx {idx} out of range 0..{len(legal)-1}")
        return legal[idx]

    def declare_attackers(self, state, player_id, eligible):
        options = [
            {"id": o.id, "name": o.printing.name,
             "scryfall_id": self._n2id.get(o.printing.name)}
            for o in eligible
        ]
        resp = self._ask({"type": "declare_attackers", "eligible": options})
        return [int(x) for x in resp.get("ids", [])]

    def declare_blockers(self, state, player_id, eligible, attackers):
        resp = self._ask({
            "type": "declare_blockers",
            "eligible": [
                {"id": o.id, "name": o.printing.name,
                 "scryfall_id": self._n2id.get(o.printing.name)}
                for o in eligible
            ],
            "attackers": [
                {"id": o.id, "name": o.printing.name,
                 "scryfall_id": self._n2id.get(o.printing.name)}
                for o in attackers
            ],
        })
        raw = resp.get("assignments", {})
        return {int(k): int(v) for k, v in raw.items()}

    def choose_target(self, state, player_id, legal_targets):
        if not legal_targets:
            return None
        options = []
        for kind, tid in legal_targets:
            if kind == "player":
                label = f"Player {tid}"
            elif kind == "stack":
                item = state.stack[tid] if 0 <= tid < len(state.stack) else None
                label = item.source.printing.name if item else f"Stack item {tid}"
            else:
                obj = _find_obj(state, tid)
                label = obj.printing.name if obj else f"Permanent #{tid}"
            options.append({"kind": kind, "id": tid, "label": label})
        resp = self._ask({
            "type": "choose_target",
            "options": options,
            "can_decline": False,
        })
        if resp.get("decline"):
            return None
        idx = int(resp["idx"])
        if not 0 <= idx < len(legal_targets):
            raise ValueError(f"choose_target idx {idx} out of range")
        return legal_targets[idx]

    def choose_discard(self, state, player_id, hand_card_ids):
        cards = [_card_opt(state, cid, self._n2id) for cid in hand_card_ids]
        resp = self._ask({"type": "choose_discard", "cards": cards})
        return int(resp["id"])

    def choose_surveil(self, state, player_id, top_card_id):
        card = _card_opt(state, top_card_id, self._n2id)
        resp = self._ask({"type": "choose_surveil", "card": card})
        return bool(resp.get("mill", False))

    def choose_sacrifice(self, state, player_id, legal_object_ids):
        objects = [_bf_opt(state, oid, self._n2id) for oid in legal_object_ids]
        resp = self._ask({"type": "choose_sacrifice", "objects": objects})
        return int(resp["id"])

    def choose_mode(self, state, player_id, mode_descriptions):
        modes = [{"idx": i, "description": d} for i, d in enumerate(mode_descriptions)]
        resp = self._ask({"type": "choose_mode", "modes": modes})
        idx = int(resp["idx"])
        if not 0 <= idx < len(mode_descriptions):
            raise ValueError(f"choose_mode idx {idx} out of range")
        return idx

    def choose_modes(self, state, player_id, mode_descriptions):
        modes = [{"idx": i, "description": d} for i, d in enumerate(mode_descriptions)]
        resp = self._ask({"type": "choose_modes", "modes": modes})
        indices = [int(i) for i in resp.get("indices", [0])]
        if not indices:
            indices = [0]
        return indices

    def choose_pay_shock_life(self, state, player_id, life_cost):
        resp = self._ask({
            "type": "choose_yes_no",
            "prompt": f"Pay {life_cost} life to enter untapped?",
            "life_cost": life_cost,
        })
        return bool(resp.get("yes", False))

    def choose_card_from_opponent_hand(self, state, player_id, opponent_hand_ids):
        cards = [_card_opt(state, cid, self._n2id) for cid in opponent_hand_ids]
        resp = self._ask({
            "type": "choose_card",
            "prompt": "Choose a card from opponent's hand",
            "cards": cards,
            "can_decline": False,
        })
        return int(resp["id"])

    def choose_card_from_library(self, state, player_id, option_ids):
        if not option_ids:
            return None
        cards = [_card_opt(state, cid, self._n2id) for cid in option_ids]
        resp = self._ask({
            "type": "choose_card",
            "prompt": "Search your library — choose a card",
            "cards": cards,
            "can_decline": True,
        })
        if resp.get("decline"):
            return None
        return int(resp["id"])

    def choose_x(self, state, player_id, card_name, upper_bound):
        resp = self._ask({
            "type": "choose_x",
            "card_name": card_name,
            "upper_bound": upper_bound,
        })
        val = int(resp.get("value", upper_bound))
        return max(0, min(val, upper_bound))

    def choose_devour_lands(self, state, player_id, land_ids):
        objects = [_bf_opt(state, oid, self._n2id) for oid in land_ids]
        resp = self._ask({
            "type": "choose_multi_ids",
            "prompt": "Choose lands to sacrifice (Devour)",
            "objects": objects,
            "can_decline": True,
        })
        return [int(x) for x in resp.get("ids", [])]

    def choose_mana_color(self, state, player_id, options):
        resp = self._ask({"type": "choose_mana_color", "options": list(options)})
        color = resp.get("color", options[0])
        if color not in options:
            return options[0]
        return color

    def choose_yes_no(self, state, player_id, prompt):
        resp = self._ask({"type": "choose_yes_no", "prompt": prompt})
        return bool(resp.get("yes", True))

    def choose_convoke_creatures(self, state, player_id, candidates,
                                  remaining_generic, remaining_colored):
        objects = [_bf_opt(state, oid, self._n2id) for oid in candidates]
        resp = self._ask({
            "type": "choose_multi_ids",
            "prompt": "Choose creatures to tap for Convoke",
            "objects": objects,
            "can_decline": True,
        })
        return [int(x) for x in resp.get("ids", [])]

    def choose_sac_for_mana(self, state, player_id, candidates,
                             remaining_generic, remaining_colored):
        objects = [_bf_opt(state, oid, self._n2id) for oid, _produces in candidates]
        resp = self._ask({
            "type": "choose_multi_ids",
            "prompt": "Choose permanents to sacrifice for mana",
            "objects": objects,
            "can_decline": True,
        })
        return [int(x) for x in resp.get("ids", [])]

    def choose_legend_keep(self, state, player_id, legend_object_ids):
        objects = [_bf_opt(state, oid, self._n2id) for oid in legend_object_ids]
        resp = self._ask({
            "type": "choose_one_id",
            "prompt": "Legend rule — choose which to keep",
            "objects": objects,
        })
        oid = int(resp["id"])
        if oid not in legend_object_ids:
            return legend_object_ids[0]
        return oid


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

@dataclass
class InteractiveSession:
    session_id: str
    human_player_id: int
    human_agent: InteractiveAgent
    game_thread: threading.Thread
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _snapshot: Optional[dict] = field(default=None, repr=False)
    _is_over: bool = False
    _result: Optional[dict] = None

    def update_snapshot(self, snap: dict) -> None:
        with self._lock:
            self._snapshot = snap

    def mark_over(self, result: dict) -> None:
        with self._lock:
            self._is_over = True
            self._result = result

    def get_state(self) -> dict:
        with self._lock:
            return {
                "snapshot": self._snapshot,
                "pending": self.human_agent.get_pending(),
                "is_over": self._is_over,
                "result": self._result,
                "human_player_id": self.human_player_id,
            }

    @property
    def is_over(self) -> bool:
        with self._lock:
            return self._is_over


# ---------------------------------------------------------------------------
# Session registry and factory
# ---------------------------------------------------------------------------

_SESSIONS: dict[str, InteractiveSession] = {}
_SESSIONS_LOCK = threading.Lock()


def _evict_oldest() -> None:
    while len(_SESSIONS) >= _SESSION_LIMIT:
        oldest_id = next(iter(_SESSIONS))
        _SESSIONS.pop(oldest_id, None)


def create_session(
    *,
    seed: int,
    colors: list[str],
    human_player_id: int,
    n2id: dict[str, str],
    enrich_fn,
    max_turns: int = 300,
) -> InteractiveSession:
    """Build a session, start the game thread, register it, and return it.

    ``enrich_fn(snap_dict) -> dict`` is called for each snapshot to
    annotate card dicts with scryfall_ids (closure from create_app that
    already has ``name_to_id`` in scope).

    ``human_player_id`` is 0 or 1; the other player gets a ``RandomAgent``.
    """
    from mtg_bot.simulate import simulate_game

    session_id = uuid4().hex
    human_agent = InteractiveAgent(n2id)
    bot_agent = RandomAgent()

    if human_player_id == 0:
        agents: list[Agent] = [human_agent, bot_agent]
    else:
        agents = [bot_agent, human_agent]

    session = InteractiveSession(
        session_id=session_id,
        human_player_id=human_player_id,
        human_agent=human_agent,
        game_thread=threading.Thread(target=None, daemon=True),  # replaced below
    )

    def run() -> None:
        try:
            state = simulate_game(
                agents=agents,
                colors=colors,
                seed=seed,
                max_turns=max_turns,
                on_snapshot=lambda s: session.update_snapshot(enrich_fn(s)),
                snapshot_granularity="step",
            )
            session.mark_over({
                "winner_id": state.winner_id,
                "is_draw": state.is_draw,
                "turn_number": state.turn_number,
            })
        except SessionTimeoutError:
            session.mark_over({"timed_out": True})
        except Exception as exc:  # noqa: BLE001
            session.mark_over({"error": str(exc)})

    t = threading.Thread(target=run, daemon=True, name=f"game-{session_id[:8]}")
    # Replace the placeholder thread
    object.__setattr__(session, "game_thread", t)
    t.start()

    with _SESSIONS_LOCK:
        _evict_oldest()
        _SESSIONS[session_id] = session

    return session


def get_session(session_id: str) -> Optional[InteractiveSession]:
    with _SESSIONS_LOCK:
        return _SESSIONS.get(session_id)
