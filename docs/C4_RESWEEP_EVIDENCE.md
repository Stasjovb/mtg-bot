# C4 post-R76 scaled re-sweep — equivalence evidence (SOT-flip Step-0 / B3-S5 go/no-go gate)

**This is the C4 evidence the atomic SoT-flip (B3-S5) go/no-go is
gated on** (`docs/SOT_FLIP_CUTOVER_PLAN.md` §1 C4 / §2 Step 0). It is
the EVIDENCE-GENERATION artifact only — the GO/NO-GO decision itself
is the USER's (orchestrator-sequenced, explicitly out of scope of the
lane that produced this doc).

## Headline (HONEST)

**DIVERGED — flip NO-GO-until-closed.** **0 / 300** production-deck
games ran divergence-clean to the natural terminal through the
role-swapped `rust_shadow` bake-in at the flip-candidate commit
`e87a6ebe`. Every real-deck game trips the bake-in's 4-assertion
tripwire, **260 / 300 FAIL_DIVERGENCE** (238 STATE_EQ + 22
LEGAL_SET_EQ) and **40 / 300 FAIL_TIMEOUT** (degenerate land-only
random-walk games that never cast a spell and never reach terminal
within the step cap — **NOT** clean PASSes, **NOT** the parity-safe
turn-120 cap). **0 PASS, 0 FAIL_EXCEPTION, 0 ARCHETYPE_FILTERED.**

This is exactly what C4 exists to catch BEFORE the irreversible flip.
The dominant STATE_EQ shape is a single, distinct, pre-existing
NEW gap (**G7** — the bake-in's `_assert_state_eq` does not reconcile
the G3 "Rust resolves `CastSpell` atomically" axis the
`cross_engine.step_both` CE5 cast-vs-resolve mirror does). The
prior "Closing G6 unmasked NO G7 / the G4→G5→G6 chain is fully
CONVERGENT and CLOSED" claim is **TRUE ONLY ON THE TINY 3-CARD
SYNTHETIC SMOKE DECK** (which casts no spells); it does **not** hold
at scale on the admitted real-deck surface. The chain was **not
exhausted at scale**.

## Exact scope swept

| Field | Value |
|---|---|
| Flip-candidate commit (engine `.pyd` / SoT) | **`e87a6ebe`** (`resync: cycle 17 — SoT-flip G6 CLOSED + G4->G5->G6 CONVERGENT CHAIN FULLY CLOSED, bake-in CLEAN to terminal (@ 30a5cebe)`) |
| Tooling commit (pure-Python harness, no engine change) | `49d10234` on `feature/c4-resweep` (worktree off `e87a6ebe`) |
| Driver | `rust_shadow` (the role-swapped `ShadowCheckedRustAdapter` bake-in: Rust drives, Python shadow-checks in lock-step; LEGAL_SET_EQ / CHOSEN_EQ / STATE_EQ / NO_RAISE) |
| Grid | `--archetypes 0-59 --seeds 0,1,2,3,4` = **300 games** (the round-76-class scale: 60 archetypes × 5 seeds) |
| Deck source | `--decks 17lands` (real EoE production decks via `load_production_deck` + `production_deck_to_deckspec` — the bench's `setup_matched_game_from_real_decks` two-step expansion; NO synthetic decks) |
| Caps | `--max-turns 120` (step_both-path arg, inert under rust_shadow); `--shadow-max-steps 4000` (the rust_shadow decision-step upper bound) |
| Interpreter / env | shared `.venv-py313`, `.pyd` already built on `main` (no rebuild — pure-Python tooling) |
| Exact command | `PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe scripts/bench_trajectory_parity.py --archetypes 0-59 --seeds 0,1,2,3,4 --max-turns 120 --driver rust_shadow --json-out c4_resweep.json --verbose` |
| Raw artifact | **`c4_resweep.json`** (committed alongside this doc — the orchestrator/user inspect the raw evidence directly) |

**Scale rationale.** A timing probe (`--archetypes 0-2 --seeds 0,1`,
6 games) measured ~2.7 s/game; the full round-76-class 300-game grid
completed in **964.4 s wall** (~16 min), per-game **3.215 s**. No
scale-down was needed — the full round-76-class scale ran in a
reasonable single-run wall-time and is the credible scaled sample
the brief specified. (Per-game rose slightly from the probe because
the 40 FAIL_TIMEOUT games each burn the full 4000-step cap at
~7 s; the 260 FAIL_DIVERGENCE games trip at ~3 s.)

## Result — full counts

| Outcome | Count | % |
|---|---:|---:|
| **PASS** | **0** | **0.0%** |
| **FAIL_DIVERGENCE** | **260** | 86.7% |
| &nbsp;&nbsp;— STATE_EQ | 238 | 79.3% |
| &nbsp;&nbsp;— LEGAL_SET_EQ | 22 | 7.3% |
| &nbsp;&nbsp;— CHOSEN_EQ | 0 | 0.0% |
| &nbsp;&nbsp;— NO_RAISE | 0 | 0.0% |
| **FAIL_TIMEOUT** | **40** | 13.3% |
| **ARCHETYPE_FILTERED** | **0** | 0.0% |
| **FAIL_EXCEPTION** | **0** | 0.0% |
| **total games** | **300** | |
| wall time | 964.4 s | |
| per-game wall | 3.215 s | |
| archetypes 5/5 FAIL_DIVERGENCE | 52 / 60 | |

Divergence-step distribution (FAIL_DIVERGENCE games, step at which
the tripwire fired): min **122**, p25 **251**, median **412**, p75
**810**, max **3051**. The tiny synthetic smoke deck runs clean to
terminal in ~152 steps and casts no spell — every real-deck game
trips on its first stack-using cast, well inside this distribution.

All 40 FAIL_TIMEOUT games hit **exactly step 4000** (the
`--shadow-max-steps` cap): degenerate land-only random-walk mirrors
where the uniform-random driver never assembled a castable spell and
the game never reached a terminal. These are explicitly **NOT** clean
PASSes and **NOT** the documented parity-safe turn-120 deck-out cap
(`docs/bench_trajectory_parity_smoke.md` round-70/72) — under the
`rust_shadow` driver the abstract decision loop has no turn analog;
the step cap is a pure upper bound and a residual at it is a game the
random driver could not progress, not a parity verdict.

## Divergence shapes (verbatim)

**Dominant — STATE_EQ (238 games), the G7 cast-resolve axis.** 159
distinct field-shape histogram keys, but they are one root cause: the
real cards differ per deck (`Galactic Wayfarer`, `Icetill Explorer`,
`Eumidian Terrabotanist`, `Exosuit Savior`, `Knight Luminary`,
`Starbreach Whale`, `Hullcarver`, …) while the structural shape is
invariant — `battlefield` + `stack` (+ caster `hand_pX` /
`mana_pool_pX`):

Representative (`archetype 0 seed 0`, step 596):

```
[STATE_EQ] compare_fields divergences (undocumented — the genuine
bad-flip signal): [('battlefield', (... Rust has the just-cast
permanent on the bf, stack empty ...), (... Python does NOT yet have
it on the bf ...)), ('stack', ((None, 0, 0, 0, 0, None, 0, 12),), ())]
```

i.e. **Rust `apply(CastSpell)` resolved the spell atomically**
(spell → battlefield, stack emptied, caster's hand/mana reduced)
while **Python `apply(CastSpell)` put the spell on the stack** pending
the priority-pass / resolution step the locked-in full
stack-and-priority Python rules engine requires. `_assert_state_eq`
runs *immediately* after `apply()` with **no post-`CastSpell`
stack-drain**, so it compares a resolved Rust state against an
on-the-stack Python state. The `cross_engine.step_both` comparator
**does** reconcile this via its **CE5 cast-vs-resolve mirror**
(`src/mtg_bot/parity/cross_engine.py:10313` — drains BOTH stacks via
`resolve_top_of_stack_python` / `resolve_top_of_stack_rust` after a
`cast_spell` action); the role-swapped bake-in has no equivalent.
This is the **G3 "Rust resolves atomically — accepted C6-fenced
caveat"** axis (acknowledged for the *LEGAL_SET_EQ* contract in the
`rust_shadow` module docstring + `canon_decision`) leaking into
STATE_EQ. Pinned: `docs/SEARCH_LIMITATIONS.md` G7 OPEN section;
`docs/SOT_FLIP_CUTOVER_PLAN.md` §4 ledger row **G7 (OPEN)**.

**Secondary — LEGAL_SET_EQ (22 games), the C1/B1 keystone axis (a
SEPARATE, already-OPEN blocker — NOT a new finding).** Verbatim:

```
[LEGAL_SET_EQ] rust\py=["('cast_spell', 76, False, False, False,
False, None)"] py\rust=[] (active_player=1)
```

Rust's `legal_decisions` offers a `CastSpell` Python's raw
`legal_actions` does not — the **C1 `legal_decisions` ==
`legal_actions` mana/target/additional-cost asymmetry** that
`SOT_FLIP_CUTOVER_PLAN.md` §1 C1 / §4 B1 already track as the
keystone HARD flip-blocker (**PARTIALLY CLOSED — Slice 1 mana DONE
`f1f09bbb`; Slices 2 target-satisfiability / 3 additional-cost NOT
fully landed**). This re-sweep INDEPENDENTLY CONFIRMS B1 is still
open at scale on the admitted real-deck surface (the
single-script-replay construction that makes the asymmetry benign
today is exactly what the flip removes). It is NOT a new G-series
divergence — it is the expected residual of the already-tracked
keystone B1, surfaced by the role-swapped contract precisely as the
plan predicts. Both axes (G7 STATE_EQ ∧ B1 LEGAL_SET_EQ) must be
closed before a flip GO.

## Per-archetype breakdown (summary)

60 archetypes (0–59) × 5 seeds. **52 / 60 archetypes are 5/5
FAIL_DIVERGENCE.** The remaining 8 are a mix of FAIL_DIVERGENCE +
FAIL_TIMEOUT (no archetype produced a single PASS — the FAIL_TIMEOUT
games are the degenerate land-only random walks, not parity
successes). Full per-(archetype,seed) records + the 159-key shape
histogram + the per-archetype status table are in the committed
`c4_resweep.json` (`summary.per_archetype`,
`summary.divergence_shape_histogram`, `games[]`).

## Fenced scope (NO overclaim)

This is **full-game-trajectory equivalence on the C4∧C6
loader-admitted real-deck surface** (the population the bench
exercises), driven through the role-swapped `rust_shadow` bake-in —
**NOT** the whole 475-card pool, and NOT the 64.6% whole-pool
Effect+bridge byte-equal headline (`POOL_PARITY.md` — a different,
more optimistic denominator;
`SOT_FLIP_CUTOVER_PLAN.md` §1.1). The deck-weighted loader-admit is
~52% of real deck slots / ~20% of non-land slots, Forest-padded
(`LOADER_ADMIT_COMPLETENESS_ANALYSIS.md`); this evidence speaks to
full-trajectory equivalence on that admitted surface only, and the
honest read is that on that surface the bake-in is **NOT** yet
divergence-clean.

## Disposition — NO-GO-until-closed

Per `docs/SOT_FLIP_CUTOVER_PLAN.md` §2 Step-0 + the brief's Step-4
disposition rule, this is a **genuine finding — flip NO-GO-until the
surfaced gaps close**. It is NOT papered. Two distinct axes:

1. **G7 (NEW, dominant — 238/300):** the bake-in's STATE_EQ does not
   reconcile the G3 atomic-`CastSpell`-resolve axis. Pinned + filed +
   flagged for the orchestrator as the **next single deliberate flip
   lane** (the G4→G5→G6→**G7** chain was not exhausted at scale — the
   smoke deck simply never casts a spell). Fix scope: port the
   `step_both` CE5 cast-vs-resolve stack-drain into
   `ShadowCheckedRustAdapter.apply()` before `_assert_state_eq` on a
   stack-using decision — pure-Python `rust_shadow.py`-only,
   `decision_source="python"` byte-unchanged, no Rust/`.pyd` (the
   same shape + discipline as the G4/G5/G6 closures). Ledger row
   **G7 (OPEN)**; `SEARCH_LIMITATIONS.md` G7 OPEN section; todo filed
   (`hub/data/mtg_bot/todos.json`).

2. **B1 (already-OPEN keystone — 22/300 LEGAL_SET_EQ):** the C1
   `legal_decisions == legal_actions` mana/target/additional-cost
   asymmetry, PARTIALLY CLOSED (Slices 2/3 outstanding). This
   re-sweep independently confirms it is still open at scale; it was
   already the head of the critical path (`SOT_FLIP_CUTOVER_PLAN.md`
   §4 B1) — no new ledger row needed, but it is a co-blocker of the
   flip GO.

**Recommendation: flip NO-GO until G7 closes AND B1 (C1 Slices 2/3)
lands**, then a fresh C4 re-sweep through this same `--driver
rust_shadow` harness must run divergence-clean before the user's
B3-S5 atomic-flip GO decision. The atomic-flip decision itself
remains the USER's — explicitly out of scope of this
evidence-generation lane.

---

*Generated by the C4 post-R76 scaled re-sweep lane. Verify-first
confirmed the C4 definition against live `SOT_FLIP_CUTOVER_PLAN.md`
§1/§2/§4 + the round-76 section of `bench_trajectory_parity_smoke.md`
+ `rust_shadow.py` + `test_rust_shadow_bakein.py` before building the
driver. Tooling: `--driver rust_shadow` on
`scripts/bench_trajectory_parity.py` +
`rust_shadow.drive_shadow_game_to_terminal` +
`tests/test_bench_rust_shadow_driver.py` (commit `49d10234`). 4-file
core gate 1532 UNMOVED; `test_rust_shadow_bakein` 11 + rust-adapter
14 green; `check_audit_coverage_staleness` exit 0; no
rust/cards.rs/cross_engine.py / Effect/bridge/_SAFE_* count touched.*
