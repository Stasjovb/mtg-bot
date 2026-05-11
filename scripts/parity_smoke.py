"""Parity smoke: run one game per engine, compare trajectories.

Records every agent decision (choose_action / declare_attackers /
declare_blockers / choose_target / choose_discard / choose_legend_keep)
along with a state-hash before each decision. Two engines running the
same seed and same decks should produce byte-identical trajectories.

Usage:
    PYTHONPATH=src python scripts/parity_smoke.py --seed 42
    PYTHONPATH=src python scripts/parity_smoke.py --mode initial-state --seed 42
    PYTHONPATH=src python scripts/parity_smoke.py --mode trajectory --seed 42 --num-decisions 20
    PYTHONPATH=src python scripts/parity_smoke.py --mode multi-seed --num-seeds 10 --num-decisions 20

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
    trajectory     — Rust-only. Build a synthetic state, walk N
                     decisions picked deterministically from
                     ``legal_decisions``, then clone the original
                     state and replay the same decision sequence —
                     assert the fingerprint trajectory is
                     byte-identical. Catches non-deterministic
                     mutation and clone-divergence bugs. Cross-engine
                     trajectory compare is deferred until Python's
                     ``legal.py:legal_actions`` and Rust's
                     ``legal_decisions`` have full coverage parity.
    multi-seed     — Run trajectory mode across K seeds and print an
                     aggregate summary table. Catches non-determinism
                     bugs that only surface at certain seeds — the
                     single-seed trajectory mode is necessary but not
                     sufficient since a fixed seed only exercises one
                     path through the legal space.
    field-diff     — Build a Rust synthetic state and print a
                     per-field OK/DIFFER diff between two parallel
                     views of it. Parity-debug primitive: when a
                     future trajectory smoke says "digests diverge at
                     decision 47", run this mode at that state to see
                     "life=20/19 — DIVERGE" instead of just two
                     mismatched digests. Supports
                     ``--inject-divergence FIELD`` to artificially
                     mutate one field on the right-hand view so the
                     diff machinery itself can be smoke-tested.

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
from typing import Any, Optional


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


# ---------- trajectory mode -----------------------------------------------


def _decision_summary(action: dict) -> str:
    """Render an Action dict as a short human-readable label.

    Used in failure diagnostics — the diff between the original and
    clone-replay paths cites the decision kind + card_id (when present)
    so a reader can tell at a glance whether the divergence is on a
    play_land, cast_spell, or pass_priority.
    """
    kind = action.get("kind", "?")
    if "card_id" in action:
        return f"{kind}(card_id={action['card_id']})"
    return kind


def _walk_trajectory(state, seed: int, num_decisions: int) -> tuple[list[dict], list[str]]:
    """Walk a Rust state through ``num_decisions`` deterministic decisions.

    Returns ``(decisions_taken, fingerprint_trajectory)`` where:

    - ``decisions_taken[i]`` is the action dict applied at step i.
    - ``fingerprint_trajectory`` is the list of fingerprints in
      ``[fp_initial, fp_after_step_0, fp_after_step_1, ...]`` order.
      Length is ``num_decisions + 1``.

    Decision selection: a single ``random.Random(seed)`` instance is
    seeded once and ``rng.choice(legal)`` is called per step. This is
    bit-identical across runs with the same seed.

    Stubbed-dispatch handling: ``ActivateAbility`` currently raises
    ``ValueError("ActivateAbility dispatch not implemented yet ...")``
    when applied (round 24 ships the variant + bridge but not the
    primitive). Such failures are caught and the offending action is
    re-picked — the rng state advances on each re-pick so the choice
    is still deterministic. After 16 consecutive re-pick attempts at
    one step we abort with RuntimeError (defensive: every legal action
    being a stubbed dispatch is a real bug, not a transient skip).

    Empty ``legal_decisions`` is a contract violation — PassPriority
    is always supposed to be at index 0 — and aborts immediately.
    """
    rng = random.Random(seed)
    decisions_taken: list[dict] = []
    trajectory: list[str] = [state.fingerprint()]

    for step in range(num_decisions):
        # Inner pick-loop: re-roll on a stubbed dispatch failure.
        max_retries = 16
        applied = False
        last_error: Exception | None = None
        for _ in range(max_retries):
            legal = state.legal_decisions(state.get_priority_player())
            if not legal:
                raise RuntimeError(
                    f"step {step}: legal_decisions returned an empty list "
                    f"(contract violation — PassPriority should always emit)"
                )
            choice = rng.choice(legal)
            try:
                state.apply_action(choice)
                decisions_taken.append(choice)
                trajectory.append(state.fingerprint())
                applied = True
                break
            except ValueError as e:
                # Stubbed dispatch (ActivateAbility today) — re-pick.
                # rng has already advanced from the rng.choice call, so
                # the retry picks a different element from the same
                # legal list (or, on the same element, the loop tries
                # again with a fresh choice).
                last_error = e
                continue
        if not applied:
            raise RuntimeError(
                f"step {step}: gave up after {max_retries} re-pick attempts "
                f"(every legal action raised; last error: {last_error!r})"
            )

    return decisions_taken, trajectory


def _replay_trajectory(state, decisions: list[dict]) -> list[str]:
    """Replay a recorded decision sequence on a fresh state and return
    the resulting fingerprint trajectory.

    Used for the clone-replay determinism check: walk the original
    state, clone it, then apply the SAME decision sequence to the
    clone and verify the fingerprint trajectory matches byte-for-byte.
    """
    trajectory = [state.fingerprint()]
    for action in decisions:
        state.apply_action(action)
        trajectory.append(state.fingerprint())
    return trajectory


@dataclass
class TrajectorySeedResult:
    """One seed's outcome from the trajectory walk + clone-replay check.

    Used by both ``run_trajectory_mode`` (single-seed) and
    ``run_multi_seed_mode`` (K seeds). The single-seed runner prints
    one of these and translates to an exit code; the multi-seed
    runner collects a list of them and prints an aggregate table.

    Fields:
      seed              — the seed the walk was driven with.
      n_decisions       — number of decisions actually applied. Equals
                          ``num_decisions`` on success; on a walk-time
                          ``RuntimeError`` it's the count completed
                          before the abort.
      final_fingerprint — last fingerprint in the original trajectory,
                          or ``None`` if the walk failed before any
                          state was produced.
      clone_match       — True iff the clone-replay trajectory is
                          byte-equal to the original. False on either
                          trajectory mismatch OR a clone-side
                          exception that the original walk didn't hit.
      error             — short error string if anything went wrong
                          (walk RuntimeError, clone-replay exception),
                          else None. Used for the "errors" column in
                          the multi-seed table.
      orig_trajectory   — full original trajectory (initial + after
                          each step). Populated when the walk
                          succeeded; left as an empty list on walk
                          failure. Carried so the single-seed runner
                          can print the divergence-step diagnostic
                          without recomputing.
      clone_trajectory  — full clone-replay trajectory. Empty list if
                          the clone-replay raised.
      decisions         — the decisions actually applied (so the
                          divergence-step diagnostic can render the
                          triggering action).
    """

    seed: int
    n_decisions: int = 0
    final_fingerprint: str | None = None
    clone_match: bool = False
    error: str | None = None
    orig_trajectory: list[str] = field(default_factory=list)
    clone_trajectory: list[str] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)


def _run_single_seed_trajectory(
    seed: int,
    num_decisions: int,
    num_battlefield: int,
    num_hand: int,
    num_library: int,
) -> TrajectorySeedResult:
    """Run the trajectory walk + clone-replay check for one seed and
    return a result struct (no printing — the caller decides whether
    to print a single-seed line or aggregate into a multi-seed table).

    Assumes ``mtg_bot_engine`` is importable; the caller is responsible
    for the up-front import-error handling.
    """
    import mtg_bot_engine

    res = TrajectorySeedResult(seed=seed)
    state = mtg_bot_engine.make_synthetic_state(
        num_battlefield, num_hand, num_library
    )
    # Clone BEFORE any mutation so the clone is byte-identical to the
    # starting state. If we cloned after walking, we'd be cloning the
    # post-walk state — meaningless for replay.
    clone = state.clone_once()

    try:
        decisions, orig_trajectory = _walk_trajectory(state, seed, num_decisions)
    except RuntimeError as e:
        res.error = f"walk: {type(e).__name__}: {e}"
        return res

    res.decisions = decisions
    res.orig_trajectory = orig_trajectory
    res.n_decisions = len(decisions)
    res.final_fingerprint = orig_trajectory[-1]

    try:
        clone_trajectory = _replay_trajectory(clone, decisions)
    except Exception as e:
        res.error = f"clone-replay: {type(e).__name__}: {e}"
        res.clone_match = False
        return res

    res.clone_trajectory = clone_trajectory
    res.clone_match = orig_trajectory == clone_trajectory
    return res


def run_trajectory_mode(
    seed: int,
    num_decisions: int,
    num_battlefield: int = 2,
    num_hand: int = 3,
    num_library: int = 5,
) -> int:
    """Run a Rust-only trajectory walk + clone-replay determinism check.

    Steps:
      1. Build a synthetic Rust state.
      2. Clone it BEFORE walking so the clone is byte-identical to
         the pre-walk state.
      3. Walk ``num_decisions`` decisions deterministically on the
         original state, recording each decision + fingerprint.
      4. Replay the same decision sequence on the clone.
      5. Assert the two fingerprint trajectories match step-by-step.
         Report the first divergence on failure.

    Returns 0 on PASS, 1 on FAIL, 2 on import / contract error.

    Thin wrapper around :func:`_run_single_seed_trajectory` — the
    helper does the actual walk + replay and returns a result struct;
    this function prints the single-seed status line and translates to
    an exit code. ``run_multi_seed_mode`` calls the helper directly
    so it can aggregate K results without printing per-seed full
    diagnostics.
    """
    try:
        import mtg_bot_engine  # noqa: F401  (used by helper)
    except ImportError as e:
        print(f"[trajectory] ERROR: mtg_bot_engine not built ({e})")
        print("  -> run `maturin develop --release -m rust/Cargo.toml`")
        return 2

    print("[python] (skipped — trajectory mode runs Rust-only for now)")

    result = _run_single_seed_trajectory(
        seed=seed,
        num_decisions=num_decisions,
        num_battlefield=num_battlefield,
        num_hand=num_hand,
        num_library=num_library,
    )

    # Walk-time failure (RuntimeError from _walk_trajectory) — abort
    # with scaffold-error exit code, since this signals a contract
    # violation (e.g. empty legal_decisions) rather than a parity bug.
    if result.error is not None and not result.orig_trajectory:
        print(f"[  rust] ERROR during trajectory walk: {result.error}")
        return 2

    # Clone-replay exception (original walk succeeded but clone raised):
    # itself a divergence — report + return 1.
    if result.error is not None and not result.clone_trajectory:
        print(
            f"[  rust] trajectory of {num_decisions} decisions, "
            f"final_hash={result.final_fingerprint}, clone-replay-matches=False"
        )
        print(
            f"PARITY: FAIL — clone-replay raised "
            f"{result.error} where original did not"
        )
        return 1

    print(
        f"[  rust] trajectory of {num_decisions} decisions, "
        f"final_hash={result.final_fingerprint}, "
        f"clone-replay-matches={result.clone_match}"
    )

    if result.clone_match:
        print(f"PARITY: PASS — Rust trajectory deterministic across seed={seed}")
        return 0

    # Find the first divergence step.
    orig_trajectory = result.orig_trajectory
    clone_trajectory = result.clone_trajectory
    decisions = result.decisions
    div_step = next(
        (
            i
            for i, (a, b) in enumerate(zip(orig_trajectory, clone_trajectory))
            if a != b
        ),
        min(len(orig_trajectory), len(clone_trajectory)),
    )
    print(f"PARITY: FAIL — clone-replay diverged at step {div_step}")
    # Decision at index `div_step - 1` is the one that caused the
    # divergence (it's the apply between trajectory[div_step - 1] and
    # trajectory[div_step]). At step 0 (initial fingerprint mismatch
    # before any decision) there's no triggering decision.
    if div_step == 0:
        print(
            f"  step 0 original: fp={orig_trajectory[0]} (pre-decision)"
        )
        print(
            f"  step 0 clone:    fp={clone_trajectory[0]} (pre-decision)"
        )
    else:
        decision_idx = div_step - 1
        decision_repr = _decision_summary(decisions[decision_idx])
        print(
            f"  step {div_step} original: fp={orig_trajectory[div_step]}, "
            f"decision={decision_repr}"
        )
        print(
            f"  step {div_step} clone:    fp={clone_trajectory[div_step]}, "
            f"decision={decision_repr}"
        )
    return 1


# ---------- multi-seed mode -----------------------------------------------


def run_multi_seed_mode(
    num_seeds: int,
    seed_start: int,
    num_decisions: int,
    num_battlefield: int = 2,
    num_hand: int = 3,
    num_library: int = 5,
) -> int:
    """Run trajectory mode across K seeds and print an aggregate summary.

    For each seed in ``[seed_start, seed_start + num_seeds)``:
      1. Build a fresh synthetic Rust state.
      2. Walk ``num_decisions`` deterministic decisions.
      3. Clone-replay them on a pre-walk clone.
      4. Record (seed, n_decisions, final_fp, clone_match, error).

    Prints a per-seed table + aggregate stats, then a final PASS/FAIL
    summary line. Returns 0 if every seed clone-replay-matched with
    no errors; 1 if any seed had a divergence or error; 2 on import
    failure.

    Catches non-determinism bugs that only manifest at specific
    seeds — the single-seed mode is necessary but not sufficient
    because a fixed seed only exercises one path through the legal
    space. By sweeping K seeds we tile that space and the chance
    that a real nondeterminism bug stays hidden drops sharply with K.
    """
    try:
        import mtg_bot_engine  # noqa: F401  (used by helper)
    except ImportError as e:
        print(f"[multi-seed] ERROR: mtg_bot_engine not built ({e})")
        print("  -> run `maturin develop --release -m rust/Cargo.toml`")
        return 2

    seed_end = seed_start + num_seeds
    print(
        f"[multi-seed] running {num_seeds} seeds ({seed_start}..{seed_end - 1}), "
        f"{num_decisions} decisions each, "
        f"board=({num_battlefield},{num_hand},{num_library})"
    )
    print()
    # Header: keep column widths in sync with the data rows below so
    # the table reads cleanly in a terminal.
    print("seed |   decisions | fingerprint  | clone-match | errors")
    print("-----|-------------|--------------|-------------|-------")

    results: list[TrajectorySeedResult] = []
    for seed in range(seed_start, seed_end):
        result = _run_single_seed_trajectory(
            seed=seed,
            num_decisions=num_decisions,
            num_battlefield=num_battlefield,
            num_hand=num_hand,
            num_library=num_library,
        )
        results.append(result)
        fp_display = result.final_fingerprint if result.final_fingerprint else "-"
        err_display = result.error if result.error else "-"
        print(
            f"{seed:>4} | {result.n_decisions:>11} | {fp_display:<12} | "
            f"{str(result.clone_match):<11} | {err_display}"
        )

    # Aggregate stats.
    all_match = all(r.clone_match for r in results)
    n_errors = sum(1 for r in results if r.error is not None)
    fingerprints = [r.final_fingerprint for r in results if r.final_fingerprint]
    unique_fingerprints = len(set(fingerprints))
    failing_seeds = [r for r in results if not r.clone_match or r.error is not None]

    uniq_note = ""
    if fingerprints:
        if unique_fingerprints == len(fingerprints):
            uniq_note = "  (every seed produced a unique trajectory)"
        else:
            uniq_note = (
                f"  ({len(fingerprints) - unique_fingerprints} collisions across "
                f"{len(fingerprints)} runs)"
            )

    print()
    print("aggregate:")
    print(f"  total seeds:       {num_seeds}")
    print(f"  all clone-match:   {all_match}")
    print(f"  unique fingerprints: {unique_fingerprints}{uniq_note}")
    print(f"  total errors:      {n_errors}")
    print()

    if all_match and n_errors == 0:
        print(
            f"PARITY: PASS — all {num_seeds} seeds clone-replay-matched"
        )
        return 0

    n_failed = len(failing_seeds)
    print(f"PARITY: FAIL — {n_failed} of {num_seeds} seeds failed")
    for r in failing_seeds:
        if r.error is not None:
            print(f"  seed {r.seed}: {r.error}")
        else:
            # No exception but clone_match is False — a fingerprint
            # mismatch between original and clone-replay. Cite the
            # first-divergence step the way single-seed mode does.
            div_step = next(
                (
                    i
                    for i, (a, b) in enumerate(
                        zip(r.orig_trajectory, r.clone_trajectory)
                    )
                    if a != b
                ),
                min(len(r.orig_trajectory), len(r.clone_trajectory)),
            )
            print(f"  seed {r.seed}: clone-replay diverged at step {div_step}")
    return 1


# ---------- field-diff mode ----------------------------------------------


# Canonical ordering of fields the field-diff mode reports on. Mirrors the
# fields that ``_hash_rust_state`` folds into its hash recipe, plus the
# scalar/zone fields the task brief specifically names. Keeping this list
# in module scope makes it easy to assert "every field in _hash_parts shows
# up in the diff table" in tests + lets the inject-divergence flag accept
# the same field names.
FIELD_DIFF_FIELDS: tuple[str, ...] = (
    "turn",
    "step",
    "phase",
    "active_player",
    "priority_player",
    "is_over",
    "is_draw",
    "winner_id",
    "life_p0",
    "life_p1",
    "hand_p0",
    "hand_p1",
    "library_p0",
    "library_p1",
    "graveyard_p0",
    "graveyard_p1",
    "exile_p0",
    "exile_p1",
    "mana_pool_p0",
    "mana_pool_p1",
    "battlefield",
    "stack",
)


def _build_field_view(state) -> dict:
    """Build a field-keyed view of a Rust GameState from its snapshot getters.

    Returns an ordered dict (insertion-order = ``FIELD_DIFF_FIELDS`` order)
    keyed by field name, with values being the comparable signatures:

      * scalar fields (life, active_player, ...) -> the raw value
      * zone fields (hand_p0, battlefield, ...) -> tuple of per-object
        8-tuples produced by ``_rust_zone_obj_sig``
      * stack -> tuple of per-stack-item 8-tuples produced by
        ``_rust_stack_obj_sig``
      * mana_pool_pN -> tuple of sorted ``(symbol, count)`` items

    Both the "python-side recipe walk" and the "Rust-direct snapshot walk"
    feed off ``_build_field_view`` — by construction both views start
    field-equal on a vanilla state, which is the field-diff mode's
    null-hypothesis baseline. The mode's value comes from the
    inject-divergence flag (smoke-test the smoke) and from a future
    bridge implementation that walks the Python GameState through a
    parallel ``_build_python_field_view`` -- left as a TODO for the next
    slice once Python-side snapshot getters land.

    Step and phase are both surfaced — Rust's ``state.step`` returns the
    enum string (e.g. ``"UNTAP"``) which corresponds to a sub-step; the
    ``phase`` field uses the same string today (we don't yet have a
    separate phase enum on the Rust side) but is plumbed in as its own
    diff slot so a future "phase != step" expansion doesn't break the
    table layout.
    """
    view: dict = {}
    view["turn"] = state.turn_number
    view["step"] = state.step
    view["phase"] = state.step  # same as step today, see docstring
    view["active_player"] = state.active_player_idx
    view["priority_player"] = state.priority_player_idx
    view["is_over"] = state.is_over()
    view["is_draw"] = state.is_draw
    view["winner_id"] = state.winner_id
    view["life_p0"] = state.get_life(0)
    view["life_p1"] = state.get_life(1)
    view["hand_p0"] = tuple(_rust_zone_obj_sig(d) for d in state.hand_snapshot(0))
    view["hand_p1"] = tuple(_rust_zone_obj_sig(d) for d in state.hand_snapshot(1))
    view["library_p0"] = tuple(
        _rust_zone_obj_sig(d) for d in state.library_snapshot(0)
    )
    view["library_p1"] = tuple(
        _rust_zone_obj_sig(d) for d in state.library_snapshot(1)
    )
    view["graveyard_p0"] = tuple(
        _rust_zone_obj_sig(d) for d in state.graveyard_snapshot(0)
    )
    view["graveyard_p1"] = tuple(
        _rust_zone_obj_sig(d) for d in state.graveyard_snapshot(1)
    )
    view["exile_p0"] = tuple(_rust_zone_obj_sig(d) for d in state.exile_snapshot(0))
    view["exile_p1"] = tuple(_rust_zone_obj_sig(d) for d in state.exile_snapshot(1))
    view["mana_pool_p0"] = tuple(sorted(state.mana_pool_snapshot(0).items()))
    view["mana_pool_p1"] = tuple(sorted(state.mana_pool_snapshot(1).items()))
    view["battlefield"] = tuple(
        _rust_zone_obj_sig(d) for d in state.battlefield_snapshot()
    )
    view["stack"] = tuple(_rust_stack_obj_sig(d) for d in state.stack_snapshot())
    return view


# Mapping of inject-divergence field name -> a transform that returns a
# *different* but type-compatible value. Used by --inject-divergence to
# smoke-test that the diff machinery actually detects per-field changes.
# Each transform takes the current value and returns a guaranteed-different
# replacement.
def _mutate_field_value(field: str, value):
    """Return a value guaranteed to differ from ``value`` for ``field``.

    The mutation is type-aware so the post-mutation view still type-checks
    when compared element-by-element. For scalar int fields we add 1; for
    booleans we negate; for the step/phase string we tack on a suffix; for
    zone tuples we replace with the empty tuple (clearly different from
    any non-empty zone, and also distinct from an already-empty zone when
    we use a sentinel marker — see below).

    For zones that are already empty in the vanilla state (graveyard,
    exile, stack), we inject a fake sentinel tuple so the post-mutation
    value is meaningfully different from the empty baseline.
    """
    sentinel_obj = ("__INJECTED__", 1, 0, 0, 0, None, 0, -1)
    sentinel_stack = (None, 0, 0, 0, 0, None, 0, -1)
    if field in ("turn",):
        return (value or 0) + 1
    if field in ("active_player", "priority_player"):
        return 1 - (value or 0)  # toggle 0 <-> 1
    if field in ("life_p0", "life_p1"):
        return (value if value is not None else 20) - 1
    if field == "winner_id":
        return 0 if value is None else None
    if field in ("is_over", "is_draw"):
        return not value
    if field in ("step", "phase"):
        return f"{value}__INJECTED__"
    if field in ("mana_pool_p0", "mana_pool_p1"):
        # Replace with a clearly-different mana set; tuple of sorted items
        # so the comparison signature stays type-uniform.
        return tuple(sorted({"W": 99}.items()))
    if field in (
        "hand_p0", "hand_p1", "library_p0", "library_p1",
        "graveyard_p0", "graveyard_p1", "exile_p0", "exile_p1",
        "battlefield",
    ):
        # Append a sentinel so empty zones still get a non-trivially-
        # different post-injection signature.
        return tuple(value) + (sentinel_obj,)
    if field == "stack":
        return tuple(value) + (sentinel_stack,)
    raise ValueError(
        f"_mutate_field_value: unknown field {field!r} "
        f"(no mutation recipe)"
    )


def run_field_diff_mode(
    seed: int,
    num_battlefield: int = 10,
    num_hand: int = 7,
    num_library: int = 50,
    inject_divergence: str | None = None,
) -> int:
    """Build a Rust synthetic state and report a per-field diff between
    two parallel views of it.

    Today both views are walked from the same Rust state via the snapshot
    getters — one through ``_hash_rust_state``'s recipe (the
    "python-recipe" view) and one direct (the "rust-direct" view). On a
    vanilla state they're identical by construction; the value of this
    mode is twofold:

      1. ``--inject-divergence FIELD`` artificially mutates one field on
         the rust-direct view after building it, so we can verify the
         diff actually catches per-field mismatches. Smoke-tests the
         smoke before the actually-divergent bridge case exists.
      2. When the future cross-engine bridge lands (Python engine wired
         in), one side switches to a Python-walked view and any read-
         side drift surfaces as a localized "life=20/19 — DIVERGE" entry
         instead of "different digest, good luck".

    Returns 0 if every field matches, 1 if any field differs, 2 on
    import error.

    The ``seed`` argument is informational today (make_synthetic_state is
    deterministic), matching the contract on ``run_initial_state_compare``.
    """
    try:
        import mtg_bot_engine
    except ImportError as e:
        print(f"[field-diff] ERROR: mtg_bot_engine not built ({e})")
        print("  -> run `maturin develop --release -m rust/Cargo.toml`")
        return 2

    # Accept unqualified per-player field names (e.g. "life" instead of
    # "life_p0") as a convenience — defaults to player 0. Matches the
    # task brief's CLI surface: `--inject-divergence life` is shorter
    # and reads more naturally than `--inject-divergence life_p0`.
    if inject_divergence is not None and inject_divergence not in FIELD_DIFF_FIELDS:
        # Try suffixing _p0 for the per-player family fields.
        candidate = f"{inject_divergence}_p0"
        if candidate in FIELD_DIFF_FIELDS:
            inject_divergence = candidate
        else:
            print(
                f"[field-diff] ERROR: unknown --inject-divergence field "
                f"{inject_divergence!r}; must be one of: "
                f"{', '.join(FIELD_DIFF_FIELDS)}"
            )
            return 2

    state = mtg_bot_engine.make_synthetic_state(
        num_battlefield, num_hand, num_library
    )

    # Both views come from the same _build_field_view today (see docstring
    # — the bridge to a Python-walked view is the next slice). For the
    # inject-divergence path we mutate ONE field on the right-hand side
    # to prove the diff actually fires.
    left = _build_field_view(state)
    right = _build_field_view(state)

    if inject_divergence is not None:
        right[inject_divergence] = _mutate_field_value(
            inject_divergence, right[inject_divergence]
        )

    # Walk every field in canonical order. For each field, emit one row
    # of the table — OK if equal, DIFFER with the two values if not.
    print(
        f"[field-diff] synthetic state "
        f"[bf={num_battlefield}, hand={num_hand}, lib={num_library}, seed={seed}]"
        + (
            f" (--inject-divergence {inject_divergence})"
            if inject_divergence is not None
            else ""
        )
    )
    print()
    # Column widths chosen so a 20-char field name + a "DIFFER" verdict +
    # short value reprs fit on a typical terminal line; long zone tuples
    # are truncated in the rendering helper.
    print("field             | status | left                                  | right")
    print("------------------|--------|---------------------------------------|--------")

    n_differ = 0
    for field in FIELD_DIFF_FIELDS:
        l_val = left.get(field)
        r_val = right.get(field)
        if l_val == r_val:
            print(f"{field:<17} | OK     | {_field_repr(l_val):<37} | (same)")
        else:
            n_differ += 1
            print(
                f"{field:<17} | DIFFER | "
                f"{_field_repr(l_val):<37} | {_field_repr(r_val)}"
            )

    print()
    if n_differ == 0:
        print(
            f"PARITY: PASS — all {len(FIELD_DIFF_FIELDS)} fields match between views"
        )
        return 0

    print(
        f"PARITY: FAIL — {n_differ} of {len(FIELD_DIFF_FIELDS)} fields differ"
    )
    return 1


def _field_repr(value, max_len: int = 35) -> str:
    """Render a field value as a short, single-line string.

    Long zone tuples get truncated with ``...`` so the table reads
    cleanly. Truncation is purely cosmetic for the printed table — the
    actual equality comparison is done on the unrendered values.
    """
    rendered = repr(value)
    if len(rendered) > max_len:
        return rendered[: max_len - 3] + "..."
    return rendered


def run_cross_engine_mode(
    seed: int,
    num_decisions: int,
    inject_divergence: bool = False,
) -> int:
    """Build matched Python + Rust states on the tiny synthetic deck,
    drive them through ``num_decisions`` PassPriority actions, and
    report a per-step divergence diagnostic.

    This is the FIRST cross-engine compare landing — round 27's Phase 5
    slice. Until this lands, ``parity_smoke.py`` has been able to
    inspect EITHER Rust state (trajectory / multi-seed / field-diff /
    initial-state) OR Python state (game-mode RandomAgent walk), but
    never bridged them.

    Output format:

    1. Initial state field views — print one line per field that
       differs between the two engines BEFORE any action is applied.
    2. Per-step walks — for each of the ``num_decisions`` steps,
       print the divergence list (or "(clean)" on a step with no
       new disagreement).
    3. Aggregate summary — count of unique-field divergences across
       all steps; for each, the gap-doc reference (or "NOVEL" if
       unmatched). The exit code is 0 only when there are zero
       divergences.

    ``inject_divergence`` (smoke-test-the-smoke): when True, the
    Rust state's player-0 life is set to 19 before the initial-state
    compare runs. This proves the harness CAN detect a fake
    cross-engine divergence at step 0 and exits non-zero. Mirrors
    the round-25 ``--mode field-diff --inject-divergence`` pattern.

    Returns 0 on parity-clean (which on the first slice is impossible
    without further engine work — but the inject-divergence path is
    deterministic about it), 1 on detected divergences, 2 on import
    error.
    """
    try:
        import mtg_bot_engine  # noqa: F401
    except ImportError as e:
        print(f"[cross-engine] ERROR: mtg_bot_engine not built ({e})")
        print("  -> run `maturin develop --release -m rust/Cargo.toml`")
        return 2

    try:
        from mtg_bot.parity.cross_engine import (
            tiny_synthetic_deckspec,
            walk_both,
        )
    except ImportError as e:
        print(f"[cross-engine] ERROR: mtg_bot.parity not importable ({e})")
        print("  -> make sure PYTHONPATH=src and src/mtg_bot/parity/ exists")
        return 2

    spec = tiny_synthetic_deckspec()
    result = walk_both(
        spec, n_decisions=num_decisions, inject_divergence=inject_divergence,
    )

    print(
        f"[cross-engine] tiny synthetic state (Forest + Grizzly Bears) "
        f"with seed={seed}, decisions={num_decisions}"
        + (" (--inject-divergence)" if inject_divergence else "")
    )

    if result.error is not None:
        print(f"[cross-engine] ERROR: aborted at step {result.aborted_at}: {result.error}")
        return 2

    # Initial state diff.
    print()
    print("== initial state (before any decision) ==")
    if not result.initial_divergences:
        print("  (no divergences — Python + Rust fingerprint blocks agree at step 0)")
    else:
        for d in result.initial_divergences:
            gap_tag = f"matches gap {d.known_gap}" if d.known_gap else "NOVEL"
            print(f"  DIFFER {d.field}: ({gap_tag})")
            print(f"    py:   {_short_repr(d.py_value)}")
            print(f"    rust: {_short_repr(d.rust_value)}")

    # Per-step walk.
    print()
    print(f"== driving {num_decisions} PassPriority decisions ==")
    for step in result.steps:
        if not step.divergences:
            print(f"  step {step.step_index}: (clean — both engines agree)")
            continue
        diverging_fields = [d.field for d in step.divergences]
        print(
            f"  step {step.step_index}: {len(step.divergences)} field(s) differ: "
            f"{', '.join(diverging_fields)}"
        )

    # Aggregate summary — one row per unique (field, gap) tuple.
    # The smoke harness's report value is "what's the lookup against
    # RUST_PARITY_GAPS.md?" — so dedupe by field+gap, not by step.
    print()
    print("== aggregate divergence summary ==")
    unique: dict[tuple[str, Optional[str]], FieldDivergenceAggregate] = {}
    for d in result.initial_divergences:
        unique.setdefault(
            (d.field, d.known_gap),
            FieldDivergenceAggregate(field=d.field, known_gap=d.known_gap),
        ).count += 1
    for step in result.steps:
        for d in step.divergences:
            unique.setdefault(
                (d.field, d.known_gap),
                FieldDivergenceAggregate(field=d.field, known_gap=d.known_gap),
            ).count += 1

    if not unique:
        print("  (no divergences across the full walk)")
        print()
        print("PARITY: PASS — Python and Rust agree on every field at every step")
        return 0

    print(
        f"  {len(unique)} unique field(s) diverged across "
        f"{1 + len(result.steps)} state observations"
    )
    for agg in unique.values():
        gap_tag = (
            f"matches gap {agg.known_gap}"
            if agg.known_gap
            else "NOVEL (not in RUST_PARITY_GAPS.md)"
        )
        print(f"  - {agg.field}: occurrences={agg.count}, {gap_tag}")

    print()
    print(f"PARITY: FAIL — {len(unique)} unique field divergences detected")
    return 1


@dataclass
class FieldDivergenceAggregate:
    """One row in the aggregate divergence summary table."""
    field: str
    known_gap: str | None = None
    count: int = 0


def _short_repr(value, max_len: int = 80) -> str:
    """Render a value as a short, single-line repr for the diff table."""
    s = repr(value)
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


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
        choices=("game", "initial-state", "trajectory", "multi-seed", "field-diff", "cross-engine"),
        default="game",
        help=(
            "Which parity check to run. 'game' (default) plays a full game on "
            "each engine and compares trajectories. 'initial-state' builds a "
            "Rust synthetic state and asserts its native fingerprint() matches "
            "a Python reimplementation of the hash recipe. 'trajectory' walks "
            "a Rust state through N decisions and asserts clone-replay "
            "determinism (Rust-only — cross-engine compare deferred). "
            "'multi-seed' runs 'trajectory' across K seeds and prints an "
            "aggregate summary. 'field-diff' builds a synthetic state, walks "
            "two parallel views of it, and prints a per-field OK/DIFFER table "
            "— the parity-debug primitive used to answer 'WHICH field "
            "diverged' once a trajectory smoke says digests don't match. "
            "'cross-engine' (round-27 Phase 5) builds matched Python + Rust "
            "states from the tiny synthetic deck, drives N PassPriority "
            "decisions on both, and reports per-step divergences with "
            "gap-doc lookup."
        ),
    )
    p.add_argument(
        "--inject-divergence",
        type=str,
        default=None,
        help=(
            "(field-diff) artificially mutate one field on the right-hand "
            "view post-snapshot so the diff machinery has something to "
            "detect. Smoke-test the smoke. Valid field names: "
            + ", ".join(FIELD_DIFF_FIELDS) + ". "
            "(cross-engine) when set to any truthy value, perturbs the "
            "Rust state's player-0 life by -1 before the initial compare, "
            "proving the harness flags an artificial cross-engine divergence."
        ),
    )
    p.add_argument(
        "--decisions",
        type=int,
        default=None,
        help=(
            "(cross-engine) number of PassPriority decisions to drive on "
            "BOTH engines. Falls back to --num-decisions when unset."
        ),
    )
    p.add_argument(
        "--num-decisions",
        type=int,
        default=20,
        help="(trajectory / multi-seed) number of decisions to apply per walk.",
    )
    p.add_argument(
        "--num-seeds",
        type=int,
        default=10,
        help="(multi-seed) number of seeds to run the trajectory walk on.",
    )
    p.add_argument(
        "--seed-start",
        type=int,
        default=0,
        help=(
            "(multi-seed) starting seed; sweep iterates "
            "[seed_start, seed_start + num_seeds)."
        ),
    )
    p.add_argument(
        "--num-battlefield",
        type=int,
        default=10,
        help=(
            "(initial-state / trajectory) per-player battlefield size for "
            "make_synthetic_state. Trajectory mode's default differs from "
            "initial-state (smaller state -> faster walk); pass explicitly "
            "when you want a specific size."
        ),
    )
    p.add_argument(
        "--num-hand",
        type=int,
        default=7,
        help="(initial-state / trajectory) per-player hand size for make_synthetic_state.",
    )
    p.add_argument(
        "--num-library",
        type=int,
        default=50,
        help="(initial-state / trajectory) per-player library size for make_synthetic_state.",
    )
    args = p.parse_args()

    if args.mode == "initial-state":
        return run_initial_state_compare(
            seed=args.seed,
            num_battlefield=args.num_battlefield,
            num_hand=args.num_hand,
            num_library=args.num_library,
        )

    if args.mode == "trajectory":
        return run_trajectory_mode(
            seed=args.seed,
            num_decisions=args.num_decisions,
            num_battlefield=args.num_battlefield,
            num_hand=args.num_hand,
            num_library=args.num_library,
        )

    if args.mode == "field-diff":
        return run_field_diff_mode(
            seed=args.seed,
            num_battlefield=args.num_battlefield,
            num_hand=args.num_hand,
            num_library=args.num_library,
            inject_divergence=args.inject_divergence,
        )

    if args.mode == "multi-seed":
        return run_multi_seed_mode(
            num_seeds=args.num_seeds,
            seed_start=args.seed_start,
            num_decisions=args.num_decisions,
            num_battlefield=args.num_battlefield,
            num_hand=args.num_hand,
            num_library=args.num_library,
        )

    if args.mode == "cross-engine":
        n_decisions = args.decisions if args.decisions is not None else args.num_decisions
        # In cross-engine mode --inject-divergence works as a flag rather
        # than a field-picker; any non-empty value (and the default truthy
        # case below) triggers the life-perturbation path. Mirrors the
        # field-diff contract where the flag is field-name-keyed; here
        # the smoke-test-the-smoke target is fixed (life_p0 -= 1) so the
        # flag is binary.
        inject = bool(args.inject_divergence)
        return run_cross_engine_mode(
            seed=args.seed,
            num_decisions=n_decisions,
            inject_divergence=inject,
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
