"""Parity smoke: run one game per engine, compare trajectories.

Records every agent decision (choose_action / declare_attackers /
declare_blockers / choose_target / choose_discard / choose_legend_keep)
along with a state-hash before each decision. Two engines running the
same seed and same decks should produce byte-identical trajectories.

Usage:
    PYTHONPATH=src python scripts/parity_smoke.py --seed 42
    PYTHONPATH=src python scripts/parity_smoke.py --mode initial-state --seed 42

Modes:
    game           — Run a full game with RandomAgent on each engine.
                     Rust side stubs out until ``legal_decisions`` /
                     full ``apply_action`` coverage land. Default.
    initial-state  — Build a Rust synthetic state and compare its
                     native ``fingerprint()`` against a Python-side
                     re-implementation of ``hash_state`` that reads
                     the state via the round-21/22 snapshot getters.
                     Fast regression gate on the parity primitive: if
                     either engine ever drifts on the hash recipe,
                     this trips immediately.

Exit codes:
    0 — both engines agree (or only one engine ran successfully and
        printed its trajectory).
    1 — engines diverged. First-divergence index + a context window
        printed.
    2 — scaffold error (e.g., import failure).

Phase 1 status: Rust side is a stub that raises NotImplementedError
in ``--mode game``. The ``--mode initial-state`` path is fully wired
end-to-end as of round 23 (make_state + fingerprint).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import traceback
from dataclasses import dataclass, field
from typing import Any


# ---------- state hashing -------------------------------------------------

def _zone_signature(zone: list[Any]) -> tuple:
    """Hashable signature of a zone (battlefield / hand / library / ...).

    Sensitive to order (zones are lists in Python — battlefield order is
    insertion timestamp, hand/library order matters for top-of-deck and
    "first match" tie-breaking). Uses (printing_id, tapped, summoning_sick,
    damage, counters, attached_to, controller_id) so per-permanent state
    that affects gameplay is captured.
    """
    sig = []
    for obj in zone:
        sig.append(
            (
                getattr(obj, "printing", None) and obj.printing.name,
                int(getattr(obj, "tapped", False)),
                int(getattr(obj, "summoning_sick", False)),
                getattr(obj, "damage", 0),
                getattr(obj, "counters", 0),
                getattr(obj, "attached_to", None),
                getattr(obj, "controller_id", None),
                getattr(obj, "id", None),
            )
        )
    return tuple(sig)


def _hash_parts(parts: list) -> str:
    """SHA1 of a JSON-serialized ``parts`` list, truncated to 12 hex chars.

    Factored out so the dict-shim variant for the Rust state and the
    classic attribute-walking variant for the Python state hit the same
    serializer + truncation. The Rust ``fingerprint()`` mirrors the
    Python ``json.dumps(parts, default=repr, sort_keys=False)`` exactly;
    keeping the JSON kwargs in one place protects against accidental
    drift (e.g. someone flipping `sort_keys=True` in a refactor would
    invalidate every pinned baseline).
    """
    blob = json.dumps(parts, default=repr, sort_keys=False).encode("utf-8")
    return hashlib.sha1(blob).hexdigest()[:12]


def hash_state(state) -> str:
    """SHA1 of the gameplay-relevant invariants of a Python GameState.

    Attribute-walking variant — reads ``state.players[i].life`` /
    ``.hand`` / ... directly. The Rust mirror is :func:`_hash_rust_state`
    which reads the same shape through the round-21 / round-22 snapshot
    getters (``hand_snapshot`` / ``battlefield_snapshot`` / ...) instead
    of Python attributes.
    """
    parts: list = [
        state.turn_number,
        getattr(state, "step", None) and state.step.name if hasattr(getattr(state, "step", None), "name") else getattr(state, "step", None),
        state.active_player_idx,
        getattr(state, "priority_player_idx", None),
        state.is_over(),
        getattr(state, "is_draw", False),
        getattr(state, "winner_id", None),
    ]
    for p in state.players:
        parts.append((
            p.id,
            p.life,
            getattr(p, "has_lost", False),
            _zone_signature(p.hand),
            _zone_signature(p.library),
            _zone_signature(p.graveyard),
            _zone_signature(getattr(p, "exile", [])),
            tuple(sorted((p.mana_pool or {}).items())) if isinstance(getattr(p, "mana_pool", None), dict) else getattr(p, "mana_pool", None),
        ))
    # Battlefield is centralized on GameState in Python; objects carry
    # controller_id so per-player ownership is captured in _zone_signature.
    parts.append(_zone_signature(getattr(state, "battlefield", [])))
    parts.append(_zone_signature(getattr(state, "stack", [])))
    return _hash_parts(parts)


# ---------- Rust-state mirror of hash_state -------------------------------

def _rust_zone_obj_sig(d: dict) -> tuple:
    """Mirror ``_zone_signature``'s per-object 8-tuple from a snapshot dict.

    Rust ``hand_snapshot`` / ``library_snapshot`` / ``graveyard_snapshot``
    / ``exile_snapshot`` / ``battlefield_snapshot`` all return lists of
    dicts with the same key set:

        {id, printing_id, printing_name, tapped, summoning_sick,
         damage, counters, controller_id, zone}

    The Python ``_zone_signature`` produces an 8-tuple
    ``(printing_name | None, int(tapped), int(summoning_sick), damage,
       counters, attached_to, controller_id, id)``.

    Rust doesn't track ``attached_to`` yet (auras are out of scope for
    round 22/23), so we emit ``None`` for that slot — matching the
    ``Value::Null`` the Rust ``fingerprint()`` emits in the same position.
    """
    return (
        d["printing_name"],
        int(d["tapped"]),
        int(d["summoning_sick"]),
        d["damage"],
        d["counters"],
        None,  # attached_to — not modeled on the Rust side
        d["controller_id"],
        d["id"],
    )


def _rust_stack_obj_sig(d: dict) -> tuple:
    """Stack items have a different snapshot shape than zone permanents.

    The Rust ``stack_snapshot`` returns dicts of shape
    ``{source_obj_id, controller}`` (a stack item carries only an obj
    reference + its controller; per-permanent fields like tapped/damage
    are nonsensical for a card-on-the-stack).

    The Rust ``fingerprint()`` still emits stack items as the same
    8-tuple shape as zone objects — with the per-permanent slots zeroed
    or nulled — so the hash recipe stays uniform. We mirror that exactly:

        (None, 0, 0, 0, 0, None, controller, source_obj_id)
    """
    return (None, 0, 0, 0, 0, None, d["controller"], d["source_obj_id"])


def _hash_rust_state(state) -> str:
    """SHA1-12 fingerprint of a Rust GameState, reading via snapshot getters.

    Two ways to fingerprint a Rust state exist in this codebase:

    * ``state.fingerprint()`` — the native pymethod, builds the hash
      blob in Rust (see ``rust/src/state_ops_fingerprint.rs``).
    * ``_hash_rust_state(state)`` — this function, builds the hash
      blob in Python by walking the dict-form snapshots.

    They MUST produce byte-equal output. ``--mode initial-state``
    asserts that on a freshly built synthetic state — if either side
    ever drifts on the hash recipe, the harness trips immediately.
    """
    # Top-level scalars.
    step = state.step  # Rust pymethod already returns the Step.<NAME> string.
    parts: list = [
        state.turn_number,
        step,
        state.active_player_idx,
        state.priority_player_idx,
        state.is_over(),
        state.is_draw,
        state.winner_id,
    ]
    # Per-player tuples — life via get_life, has_lost derived from life<=0,
    # zone signatures via snapshot getters, mana pool as sorted dict items.
    for player_id in (0, 1):
        life = state.get_life(player_id)
        mana = state.mana_pool_snapshot(player_id)
        parts.append((
            player_id,
            life,
            life <= 0,
            tuple(_rust_zone_obj_sig(d) for d in state.hand_snapshot(player_id)),
            tuple(_rust_zone_obj_sig(d) for d in state.library_snapshot(player_id)),
            tuple(_rust_zone_obj_sig(d) for d in state.graveyard_snapshot(player_id)),
            tuple(_rust_zone_obj_sig(d) for d in state.exile_snapshot(player_id)),
            tuple(sorted(mana.items())),
        ))
    # Battlefield is split across players in Rust but `battlefield_snapshot`
    # already concatenates p0's then p1's in that order, which is what the
    # Rust fingerprint emits.
    parts.append(tuple(_rust_zone_obj_sig(d) for d in state.battlefield_snapshot()))
    parts.append(tuple(_rust_stack_obj_sig(d) for d in state.stack_snapshot()))
    return _hash_parts(parts)


# ---------- recording agent -----------------------------------------------

@dataclass
class DecisionRecord:
    method: str          # which Agent method was called
    player_id: int
    state_hash: str      # state hash BEFORE the decision
    decision: str        # repr of the returned decision
    n_legal: int         # how many legal options were offered

    def as_tuple(self) -> tuple:
        # Used for trajectory hashing. State hash + decision is enough.
        return (self.method, self.player_id, self.state_hash, self.decision, self.n_legal)


class RecordingAgent:
    """Wraps another Agent and records every method call it receives.

    Forwards ALL Agent methods via ``__getattr__`` so we don't need to
    enumerate ``choose_action`` / ``choose_permanent_to_tap`` / ... by
    hand — there are 25+ of them on the Agent base class and missing
    one silently breaks games. Every call gets a DecisionRecord with
    the state-hash before the call and the repr of the chosen result.
    """

    name = "RecordingAgent"

    def __init__(self, inner, log: list[DecisionRecord]):
        # Use object.__setattr__ to avoid triggering our own
        # ``__getattr__`` proxy during construction.
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_log", log)

    def __getattr__(self, name: str):
        # ``__getattr__`` only fires when normal lookup fails — so every
        # Agent method (which we don't define here) lands here.
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        def wrapper(*args, **kwargs):
            # Convention across every Agent method: arg0 = state, arg1 =
            # player_id. Some methods take a 3rd "legal options" arg —
            # peek for an int-able length when available.
            state = args[0] if args else None
            player_id = args[1] if len(args) > 1 and isinstance(args[1], int) else -1
            n_legal = -1
            if len(args) >= 3:
                try:
                    n_legal = len(args[2])
                except TypeError:
                    pass
            result = attr(*args, **kwargs)
            self._log.append(
                DecisionRecord(
                    method=name,
                    player_id=player_id,
                    state_hash=hash_state(state) if state is not None else "",
                    decision=repr(result),
                    n_legal=n_legal,
                )
            )
            return result

        return wrapper


# ---------- engine runners ------------------------------------------------

@dataclass
class TrajectoryResult:
    engine: str
    log: list[DecisionRecord] = field(default_factory=list)
    final_hash: str | None = None
    decisions: int = 0
    turn: int = 0
    winner: int | None = None
    is_draw: bool = False
    error: str | None = None

    def trajectory_hash(self) -> str | None:
        if self.error is not None:
            return None
        blob = json.dumps([r.as_tuple() for r in self.log] + [self.final_hash], default=repr).encode("utf-8")
        return hashlib.sha1(blob).hexdigest()[:12]


def run_python_engine(seed: int, colors: list[str], max_turns: int) -> TrajectoryResult:
    res = TrajectoryResult(engine="python")
    try:
        from mtg_bot.simulate import simulate_game
        from mtg_bot.agents import RandomAgent

        sub_rng = random.Random(seed)
        inner_agents = [RandomAgent(rng=random.Random(sub_rng.randint(0, 10**9))) for _ in colors]
        wrapped = [RecordingAgent(a, res.log) for a in inner_agents]

        state = simulate_game(
            agents=wrapped,
            colors=colors,
            seed=seed,
            max_turns=max_turns,
            verbose=False,
        )
        res.final_hash = hash_state(state)
        res.decisions = len(res.log)
        res.turn = state.turn_number
        res.winner = getattr(state, "winner_id", None)
        res.is_draw = getattr(state, "is_draw", False)
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
    return res


def run_rust_engine(seed: int, colors: list[str], max_turns: int) -> TrajectoryResult:
    """Phase 1 stub: raises NotImplementedError.

    Phase 2 wires this to a Rust GameState exposed via PyO3 — a drop-in
    for the Python GameState that emits Action objects identical to the
    Python ones for the same input. Until then the harness reports
    `error=NotImplementedError(setup)` and the divergence index is
    `setup` (i.e., we never even started).
    """
    res = TrajectoryResult(engine="rust")
    res.error = "NotImplementedError: Rust GameState bridge not built yet (Phase 2)"
    return res


# ---------- comparison ----------------------------------------------------

def find_first_divergence(a: TrajectoryResult, b: TrajectoryResult) -> int | str | None:
    """Return the index of the first divergent record, or 'setup' / None."""
    if a.error and b.error:
        return "both_errored"
    if a.error:
        return f"setup ({a.engine})"
    if b.error:
        return f"setup ({b.engine})"
    n = min(len(a.log), len(b.log))
    for i in range(n):
        if a.log[i].as_tuple() != b.log[i].as_tuple():
            return i
    if len(a.log) != len(b.log):
        return n
    if a.final_hash != b.final_hash:
        return "final_hash"
    return None


def print_result(res: TrajectoryResult) -> None:
    if res.error:
        first_line = res.error.splitlines()[0]
        print(f"[{res.engine:>6}] ERROR: {first_line}")
    else:
        outcome = (
            "draw" if res.is_draw
            else f"p{res.winner} wins" if res.winner is not None
            else "max_turns_hit"
        )
        print(
            f"[{res.engine:>6}] {res.decisions} decisions, "
            f"turn {res.turn}, {outcome}, "
            f"trajectory_hash={res.trajectory_hash()}"
        )


# ---------- initial-state mode --------------------------------------------

def run_initial_state_compare(
    seed: int,
    num_battlefield: int = 10,
    num_hand: int = 7,
    num_library: int = 50,
) -> int:
    """Build a Rust synthetic state and compare its native fingerprint to
    a Python-side reimplementation of the same hash recipe.

    The ``seed`` argument is currently informational — ``make_synthetic_state``
    is deterministic (no shuffling), so the seed doesn't shape the state.
    It's accepted so the CLI surface matches the game mode and to leave
    room for a future variant that calls ``shuffle_library_with_seed``
    or otherwise threads randomness into the test state.

    Returns 0 on PASS, 1 on FAIL, 2 on import error.
    """
    try:
        import mtg_bot_engine
    except ImportError as e:
        print(f"[initial-state] ERROR: mtg_bot_engine not built ({e})")
        print("  -> run `maturin develop --release -m rust/Cargo.toml`")
        return 2

    state = mtg_bot_engine.make_synthetic_state(num_battlefield, num_hand, num_library)
    rust_fp = state.fingerprint()
    shim_fp = _hash_rust_state(state)

    if rust_fp == shim_fp:
        print(
            f"PARITY: PASS — fingerprint match ({rust_fp}) "
            f"[bf={num_battlefield}, hand={num_hand}, lib={num_library}, seed={seed}]"
        )
        return 0

    print(
        f"PARITY: FAIL — fingerprint mismatch on synthetic state "
        f"[bf={num_battlefield}, hand={num_hand}, lib={num_library}, seed={seed}]"
    )
    print(f"  rust.fingerprint()       = {rust_fp}")
    print(f"  _hash_rust_state(state)  = {shim_fp}")
    print("  -> the Rust fingerprint() recipe and the Python shim have drifted.")
    print("     Inspect rust/src/state_ops_fingerprint.rs against")
    print("     scripts/parity_smoke.py:_hash_rust_state and reconcile.")
    return 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--colors", default="G,R", help="Comma-separated decklist colors (default G,R)")
    p.add_argument("--max-turns", type=int, default=30)
    p.add_argument(
        "--engine",
        choices=("python", "rust", "both"),
        default="both",
        help="Which engine(s) to run (game mode only). 'both' runs both and compares.",
    )
    p.add_argument(
        "--mode",
        choices=("game", "initial-state"),
        default="game",
        help=(
            "Which parity check to run. 'game' (default) plays a full game on "
            "each engine and compares trajectories. 'initial-state' builds a "
            "Rust synthetic state and asserts its native fingerprint() matches "
            "a Python reimplementation of the hash recipe."
        ),
    )
    p.add_argument(
        "--num-battlefield",
        type=int,
        default=10,
        help="(initial-state) per-player battlefield size for make_synthetic_state.",
    )
    p.add_argument(
        "--num-hand",
        type=int,
        default=7,
        help="(initial-state) per-player hand size for make_synthetic_state.",
    )
    p.add_argument(
        "--num-library",
        type=int,
        default=50,
        help="(initial-state) per-player library size for make_synthetic_state.",
    )
    args = p.parse_args()

    if args.mode == "initial-state":
        return run_initial_state_compare(
            seed=args.seed,
            num_battlefield=args.num_battlefield,
            num_hand=args.num_hand,
            num_library=args.num_library,
        )

    colors = args.colors.split(",")

    py_res = None
    rs_res = None
    if args.engine in ("python", "both"):
        py_res = run_python_engine(args.seed, colors, args.max_turns)
        print_result(py_res)
    if args.engine in ("rust", "both"):
        rs_res = run_rust_engine(args.seed, colors, args.max_turns)
        print_result(rs_res)

    if args.engine != "both":
        return 0 if (py_res or rs_res).error is None else 2

    div = find_first_divergence(py_res, rs_res)
    if div is None:
        print(f"PARITY: PASS — {py_res.decisions} decisions match")
        return 0

    print(f"PARITY: FAIL — first divergence at: {div}")
    if isinstance(div, int):
        lo = max(0, div - 2)
        hi = min(min(len(py_res.log), len(rs_res.log)), div + 3)
        print(f"  context [{lo}:{hi}]:")
        for i in range(lo, hi):
            marker = " <- " if i == div else "   "
            py = py_res.log[i] if i < len(py_res.log) else None
            rs = rs_res.log[i] if i < len(rs_res.log) else None
            print(f"  {marker}#{i}")
            print(f"      py: {py}")
            print(f"      rs: {rs}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
