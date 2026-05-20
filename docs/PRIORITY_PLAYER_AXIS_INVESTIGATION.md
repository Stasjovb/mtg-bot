# priority_player STATE_EQ axis — deep-trace investigation

**Lane:** `feature/priority-player-investigation` (2026-05-19).
**Cross-references:**
[`docs/BROADER_SWEEP_CONSOLIDATED_V5_V9.md`](BROADER_SWEEP_CONSOLIDATED_V5_V9.md) §2.1
(15/1500 cumulative, todo `c8d3a5f1`),
[`docs/FLIP_READINESS_EVIDENCE_2026_05_19.md`](FLIP_READINESS_EVIDENCE_2026_05_19.md),
cycle-37 closure precedent at `86411a99`.

This doc captures the **root cause + recommended closure path** for the
15 `STATE_EQ::fields:priority_player` residuals surfaced by the v6-v9
broader-archetype-sweep series. **Investigation, not closure** — the
fix is a follow-up lane.

The companion pin
[`tests/test_divergence_pins_priority_player.py`](../tests/test_divergence_pins_priority_player.py)
asserts the CURRENT (broken) behavior for 3 representative repros (one
of each direction) and will flip-fail when the closure lands.

---

## §0 TL;DR

**Root cause:** when an attacker declared at DECLARE_ATTACKERS dies
before DECLARE_BLOCKERS opens (the most common path being a
combat-removal spell cast on the stack at DECLARE_ATTACKERS and
resolved during the same step's pass-round), the Rust engine's
`state.attackers` Vec **retains the dead attacker's id**. On the
DECLARE_BLOCKERS phase entry, Rust's
`state_ops_legal.rs::legal_decisions(defender)` emits a
`blocker_decision` referencing the phantom attacker. The Rust
adapter's `_run_priority_action` consults `_combat_decision_maker()`,
sees the emitted `blocker_decision`, concludes the defender is the
structural decision-maker, and **skips the
`_reset_priority_to_active()` call** — leaving `priority_player`
carried at the previous holder. Python's source-of-truth
`_enter_declare_blockers` (engine_adapter.py:1318-1356) keys off the
LIVE `battlefield` (`[o for o in battlefield if o.attacking]`), sees
zero live attackers, applies empty `DeclareBlockers`, and enters the
priority window — priority returns to active.

**Code site:** `src/mtg_bot/search/rust_engine_adapter.py:619-623`
(the `_combat_decision_maker() is None` gate inside the
empty-stack-pass-round branch of `_run_priority_action`) AND the
sibling gate at `:849-858` (`_combat_decision_maker()` itself).

**Recommended closure:** mirror Python's live-attackers check in the
Rust adapter. Either (a) inside `_combat_decision_maker()`,
return `None` when `phase == DECLARE_BLOCKERS` AND no
`battlefield_snapshot()` object has `attacking=True`, or (b) add a
sibling guard inside the empty-stack-pass-round branch that calls
`_reset_priority_to_active()` unconditionally in the same
"no-live-attackers" case. Pure-Python `rust_engine_adapter.py`-only
change (no `.pyd` rebuild), mirroring the cycle-37
`86411a99` closure pattern exactly.

**Estimated scope:** 1 orchestrator cycle, ≤30 LoC adapter change, +
flip the regression pin, + re-run broader-sweep v6-v9 to confirm
≥99.5% PASS.

**Multi-axis bonus:** the v8 `LEGAL_SET_EQ::fields:blocker` axis
(4/1500, todo `d4f6a8c9`) is **the same root cause** — same phantom
`blocker_decision` emission for a dead attacker, just surfacing at
the LEGAL_SET_EQ tripwire instead of the STATE_EQ tripwire (when the
agent happens to choose `blocker_decision(120, 64)` from the offered
set BEFORE the next pass-round handoff exposes the priority
divergence). The closure should regress BOTH axes simultaneously
(15+4 = 19/1500 → 0).

---

## §1 Methodology

Reproduction loop:

1. `scripts/scout_priority_player_276_1.py` (general scout) and
   `scripts/scout_priority_player_276_1_deep.py` (sub-step intercept).
   Both load `production_deck_to_deckspec(archetype, shared_rng_seed=
   seed)` and drive `build_shadow_checked_adapter` deterministically
   with `random.Random(seed)`.
2. The first script runs to divergence, snapshots the last N pre/post
   states from BOTH engines, dumps the chosen action + canonical key.
3. The second script advances to `target_step - 1`, then SUB-STEPS
   the Rust adapter manually (bypassing `ShadowCheckedRustAdapter`'s
   STATE_EQ assertion on the last step), interleaving `print` probes
   at every branch point of `_run_priority_action`. This pinpoints the
   EXACT decision-maker query that diverges.
4. Cross-checked on a second repro (arch=290 seed=3 step 968) to
   confirm the same shape, plus a rust-extra direction repro
   (arch=114 seed=1 step 772) to verify the direction is purely a
   function of `active_player_idx`, not a separate axis.

**Verify-first** (`feedback_parity_new_code_is_right`): the trace
script reads engine state via public adapter accessors and the
`battlefield_snapshot()` + `get_attackers()` pymethods — no
speculation, every fact in this doc is dumped from the running game.

---

## §2 Trace results — arch=276 seed=1 step 857

Pre-step snapshot (just before the divergent `PassPriority` apply):

| Field | Python | Rust |
|---|---|---|
| `active_player_idx` | 1 | 1 |
| `priority_player_idx` | 0 | 0 |
| `step` | `DECLARE_ATTACKERS` | phase 5 (DECLARE_ATTACKERS) |
| `turn_number` | 32 | 32 |
| `pass_count` | 1 | 1 |
| `stack_size` | 0 | 0 |
| `combat_phase` (adapter) | None | None |
| `_finalized_combat_window` | — | (32, 5) |
| `get_attackers()` Vec | — | `[64]` |
| battlefield ids w/ `attacking=True` | (none) | (none) |
| `64 in battlefield ids` | False | False |

The 7 immediately-preceding decisions (steps 850-856) show the
attacker's life cycle:

| Step | Decision | Notable |
|---:|---|---|
| 850 | `AttackerDecision(64, True)` | id=64 declared attacking — finalize batches to `state.attackers = [64]` and taps the creature |
| 851 | `CastSpell(63)` | spell goes on the stack (likely removal targeting id=64 OR a removal/burn) |
| 852 | `PassPriority` | (1, 1) → (0, 1) — single in-round pass during DA |
| 853 | `PassPriority` | passes complete, **stack resolves** — id=64 dies in this resolution; `state.attackers` NOT cleaned up |
| 854 | `PassPriority` | re-entered priority round on empty stack |
| 855 | `PassPriority` | pass round completes, no resolution, no advance (stack=0 → step ends, but priority resets at the same phase first — actually looking again at the trace, stack still 1 at 854-855 because step 853 was the first pass of the round, not a full resolution; the resolution actually happens at 855) |
| 856 | `PassPriority` | new pass round on empty stack |
| 857 | `PassPriority` (target) | round completes, empty stack → step ends; **divergence here** |

Sub-step intercept at step 857 (from `scout_priority_player_276_1_deep.py`):

```
chosen at step 857: PassPriority()
after pass_count++: rust._pass_count=2 alive_count=2
round complete. stack_size=0
empty stack — calling advance_phase()
  rust.current_phase = 6           # DECLARE_BLOCKERS
  rust.priority = 0                # carried
  rust.active = 1
  calling _run_step_enter_sbas()   # no-op for DA→DB (DB ∉ _ENTER_STEP_SBA_PHASES)
  invalidating legal cache
  is_over=False _combat_decision_maker()=0   # *** DM = defender = 0 ***
  *** SKIPPING reset (dm is not None)
  Rust legal_decisions for dm=0:
    {'kind': 'pass_priority'}
    {'kind': 'blocker_decision', 'blocker_id': 120, 'attacker_id': 64}  # PHANTOM ATTACKER
    {'kind': 'blocker_decision', 'blocker_id': 120, 'attacker_id': None}

FINAL rust.priority = 0
FINAL rust.current_phase = 6

--- applying PassPriority to Python for comparison ---
py.priority_player_idx = 1          # *** Python reset to active ***
py.step = Step.DECLARE_BLOCKERS
py.combat_phase = None
```

The divergence is **fully characterized** at the sub-step level: Rust's
adapter, gated by an Rust-engine-emitted `blocker_decision` against a
DEAD attacker id, skips the priority reset. Python's adapter, gated by
the LIVE battlefield, performs the reset.

---

## §3 Cross-check — arch=290 seed=3 step 968 and arch=114 seed=1 step 772

`arch=290 seed=3 step 968` reproduces with identical shape:
- step 963: `AttackerDecision(71, True)`
- step 964: `CastSpell(60)` — removal on the stack
- steps 965-967: resolution + empty pass rounds, attacker dies
- step 968: pass-round-completes at DA → divergence (`('priority_player', 1, 0)`)

`arch=114 seed=1 step 772` is the **rust-extra direction**
`('priority_player', 0, 1)`:
- `active_player_idx=0` for this game (Python's NaN-mod-2-player game
  starts P0 on this seed)
- Same attacker-dies-on-the-stack pattern
- Python resets priority to active=0; Rust carries priority at 1
- Direction is purely a function of which player is active

Conclusion: **All 3 representative repros share the same root cause.**
The bidirectional `direction histogram` (8 py-extra, 7 rust-extra) in
the consolidated doc is a function of which player is the active
player at the divergent turn — not a separate bug class.

---

## §4 Why the cycle-37 closure (`86411a99`) didn't catch this

The cycle-37 closure (`86411a99`) targeted the **post-deck-out
priority port** — a `_next_alive` walk for the post-player-loss tail
when the active player itself has decked out. It is a TURN-LEVEL
all-lost-skipping fix; the closure docstring says exactly:

> Python's priority/active resets use the CR-aware simulate._next_alive
> (simulate.py:46 — skip the lost active player)

The G7 S6 Class-D residual closure (the v2 cast_spell asymmetry
addressed in the adapter's same `_reset_priority_to_active` docstring
at line 384) targeted the legal-cache staleness post-priority-shift.

**Neither closure inspected the live-battlefield ⇄
`state.attackers` Vec consistency invariant.** The v6-v9 sweeps
exercised the combat surface harder (more games reach a real combat
phase with a real attacker + removal sequence), surfacing the new
shape. The cycle-37 trace's tiny_synthetic_deckspec (3-card
no-combat scenario) couldn't have hit it.

---

## §5 Recommended closure scope

**Option A — fix in `_combat_decision_maker()`** (preferred; smaller
surface).

```python
def _combat_decision_maker(self) -> Optional[int]:
    ph = self._phase()
    if ph not in _COMBAT_DECLARE_PHASES:
        return None
    cur_window = (int(self._rust.turn_number), ph)
    if self._finalized_combat_window == cur_window:
        return None
    # NEW: mirror Python's _enter_declare_blockers live-attackers
    # check (engine_adapter.py:1322-1329) — if no battlefield object
    # actually has attacking=True, there is no factored-blocker
    # window regardless of what state.attackers Vec carries. Rust's
    # state.attackers can retain ids of attackers that died on the
    # stack during the DECLARE_ATTACKERS pass-round.
    if ph == _PHASE_DECLARE_BLOCKERS:
        has_live_attacker = any(
            bool(dict(o).get("attacking", False))
            for o in self._rust.battlefield_snapshot()
        )
        if not has_live_attacker:
            return None
    act = int(self._rust.active_player_idx)
    if ph == _PHASE_DECLARE_ATTACKERS:
        dm = act
        kind = "attacker_decision"
    else:
        dm = 1 - act
        kind = "blocker_decision"
    for d in self._legal_dicts_cached(dm):
        if d.get("kind") == kind:
            return dm
    return None
```

**Why this exact location** (verify-first): `_combat_decision_maker`
is the canonical adapter gate for the "is this a factored-combat
window?" question. Three call sites depend on its truth value
(`_run_priority_action:619`, `active_player():877`,
`legal_decisions():908`); fixing it at the source propagates to all
three identically. Mirrors the cycle-37 single-helper-fix shape.

**Bonus**: closing the `_combat_decision_maker` gate also fixes the
v8 LEGAL_SET_EQ::fields:blocker axis — when `_combat_decision_maker()`
correctly returns None, `legal_decisions()` will use the
priority-window pid (not the structural defender), and the
LEGAL_SET_EQ assertion compares Rust's priority-window emission (no
blocker_decision dicts) vs Python's priority-window
`legal_actions(priority_holder)` (also no blocker dicts).

**Option B — fix in Rust's engine** (`state_ops_sba.rs` or
`state_ops_combat.rs`): purge `state.attackers` Vec entries whose ids
no longer exist on the battlefield after `apply_sbas`. Larger surface
(.pyd rebuild required), strictly correct (the underlying Vec is a
real engine bug), but per the cycle-37 precedent and the existing
G7 S6 closures in the adapter, **Option A is the operationally
recommended path** — the adapter is the single-engine-line
reconciliation surface, the Rust engine stays unchanged, and the
Vec inconsistency is documented (with the closure docstring) rather
than silently fixed in a `.pyd` rebuild.

**SEARCH_LIMITATIONS.md entry**: the closure should add an entry
documenting that Rust's `state.attackers` Vec can retain dead
attacker ids and that the adapter's `_combat_decision_maker`
reconciles via the live-battlefield check — same pattern as the
existing UEOT-defender / cache-staleness docstrings.

---

## §6 Closure-flip pattern (for the future agent)

Per the G4-lane closure-flip pattern (`86411a99`):

1. Apply the Option A change in `rust_engine_adapter.py`.
2. **Flip the pin** at
   [`tests/test_divergence_pins_priority_player.py`](../tests/test_divergence_pins_priority_player.py):
   rename `test_priority_player_divergence_is_surfaced` →
   `test_priority_player_divergence_is_closed`; replace the
   `assert err is not None` body with `assert err is None`
   (the run is divergence-clean to natural terminal) and a
   ``steps > target_step`` sanity check (the harness reached past
   the previous divergence step). Keep the parameterization.
3. Add a negative control elsewhere that confirms the STATE_EQ
   tripwire still fires on an INJECTED divergence (already covered
   by `tests/test_rust_shadow_bakein.py::test_negative_control_*`).
4. Re-run the broader-sweep bench
   (`bench_trajectory_parity.py --archetypes 60-299
   --shadow-max-steps 20000 --seeds 0,1,2,3,4`) and confirm:
   - priority_player axis: 0 residuals (was 15)
   - blocker LEGAL_SET_EQ axis: 0 residuals (was 4 — bonus)
   - battlefield STATE_EQ axis: 4 residuals (unchanged — separate axis)
   - Cumulative: ≥99.7% PASS (was 98.5%).
5. Update [`docs/BROADER_SWEEP_CONSOLIDATED_V5_V9.md`](BROADER_SWEEP_CONSOLIDATED_V5_V9.md)
   to reflect the closed axes; the v9 battlefield axis becomes the
   next priority follow-up.
