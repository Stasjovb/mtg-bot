# G7 S6 — Terminal-cap scale-verify evidence (`shadow_max_steps` raised 4000 → 20000)

**This is the FLIP-GATE EVIDENCE-BROADENING artifact** for the real-game-trajectory
parity axis of the SoT-flip gate the user raised on 2026-05-20. It mirrors the
`docs/G7_S6_SCALE_VERIFY_EVIDENCE.md` convention but addresses one specific
sub-gap of that document's "necessary but not sufficient" finding: **the
existing C4-class CE5-free sweep (`s6_scale_verify_v4.json` /
`s6_scale_verify_v5_ce5free.json`) ran at `--shadow-max-steps 4000`, which is
not natural terminal for 109/300 games (36.3%) — they all hit exactly step
4000 without converging.** Cross-refs:
[`G7_S6_SCALE_VERIFY_EVIDENCE.md`](G7_S6_SCALE_VERIFY_EVIDENCE.md) (the cap-4000
sweep), [`BAKE_IN_PIN_SCALE_COVERAGE_GAP.md`](BAKE_IN_PIN_SCALE_COVERAGE_GAP.md)
(sentinel + scale-verify-vN contract), [`SOT_FLIP_CUTOVER_PLAN.md`](SOT_FLIP_CUTOVER_PLAN.md)
§4 G7 row + §1 C4 criterion.

## Why this run (the gap it closes)

The 2026-05-20 user-defined flip-gate parity bar explicitly enumerated the
still-open evidence axes after the narrow CE5-free C4 cap=4000 sweep:

1. Full card pool (currently 314/475 covered, 196 PROBED — 161 BLOCKED) —
   separate lane.
2. **Real-game-trajectory surface — cap=4000 sampled, NOT real-game-end.**
   *This is the gap this artifact closes.*
3. Full test surface (parity_smoke, cross_engine_*, etc. — CE5-free re-proof) —
   separate lane (`feature/s7-ce5-deadcode-excision` pending review).
4. Deferred alt-cost flags (kicker / impending / granted-warp / Room-half /
   X / restricted-coin / convoke) — separate axis.

The cap-4000 v4/v5 result was `191 PASS / 0 FAIL_DIVERGENCE / 109 FAIL_TIMEOUT
/ 0 FAIL_EXCEPTION` out of 300 games. **All 109 FAIL_TIMEOUTs hit exactly
step 4000** (`s6_scale_verify_v4.json` per-game inspection — every TIMEOUT
game `actions_played == 4000`); the step cap is the only thing preventing
them from reaching natural terminal. The honest read is that v4 demonstrated
the CE5-free bake-in produces zero divergence at the per-step compare level
for ALL the games that converged inside cap-4000, but did NOT demonstrate the
same on the residual 109 that would have needed more steps.

A scaling-probe before this sweep confirmed the residual is largely
"cap-bound" rather than "structurally-uncloseable":

| Probe arch / seed (5/5 TIMEOUT in v4) | Result at `--shadow-max-steps 20000` |
|---|---|
| arch 6 / seed 0 | PASS at step 4909 (6.85s) |
| arch 19 / seed 0 | PASS at step 4510 (8.01s) |
| arch 26 / seed 0 | PASS at step 4452 (9.30s) |
| arch 29 / seed 0 | PASS at step 4425 (9.12s) |
| arch 38 / seed 0 | PASS at step 4084 (6.52s) |

5/5 probed ex-timeout arch/seed combos converge to clean PASS just past the
old cap of 4000 — a strong indication that the v4 timeouts are predominantly
"~4100-5500-step games" rather than divergences or genuinely-stuck random
walks.

## Exact scope swept

| Field | Value |
|---|---|
| Engine `.pyd` / SoT commit | **`cd330540`** (main HEAD, `Merge feature/rust-room-fully-unlocked-event: PURE-PYTHON bridge arm for room_fully_unlocked (4th pure-Python bridge fix; OO Pin 1 CLOSED after 13 rounds open)`) |
| Tooling commit (pure-Python verify, NO engine change) | `feature/trajectory-parity-terminal-scale` off `main` @ `cd330540` |
| Driver | `rust_shadow` (`ShadowCheckedRustAdapter`: Rust drives, Python shadow-checks lock-step; LEGAL_SET_EQ / CHOSEN_EQ / STATE_EQ / NO_RAISE; NO CE5, NO CE5-equivalent in the bake-in by design — same contract as v4) |
| Grid | `--archetypes 0-59 --seeds 0,1,2,3,4` = **300 games** (identical C4-class scale to v4) |
| Deck source | `--decks 17lands` (real EoE production decks via `load_production_deck` + `production_deck_to_deckspec` — the bench's two-step expansion; NO synthetic decks; identical to v4) |
| Caps | `--max-turns 120` (step_both-path arg, inert under rust_shadow); `--shadow-max-steps 20000` (**5× v4's 4000**) |
| Interpreter / env | shared canonical `.venv-py313`, `.pyd` already built on `main` @ `cd330540` (**no rebuild — pure-Python tooling**) |
| Exact command | `PYTHONPATH=src .venv-py313/Scripts/python.exe scripts/bench_trajectory_parity.py --archetypes 0-59 --seeds 0,1,2,3,4 --driver rust_shadow --shadow-max-steps 20000 --json-out s6_scale_verify_v5_terminal.json --verbose` |
| Raw artifact | **`s6_scale_verify_v5_terminal.json`** (committed alongside this doc; the corresponding `.log` is `.gitignore`d per the v4 convention) |

**Scale rationale.** The cap is raised exactly to where the probes showed the
residual converges (~4-6k steps for the slowest near-creatureless deck-out
races); 20000 is 4× the slowest observed converger to leave generous headroom
for the long tail without unbounded wall time. Per-step cost is ~1.7-2.1 ms
(see v4 doc + the 5 probes above); the worst case (all 109 ex-timeouts still
hitting cap) is bounded at `109 × 20000 × 2.1 ms ≈ 76 min` for the timeout
portion + `191 × ~3.5s ≈ 11 min` for the PASS portion = ~90 min — well under
the "raise honest-stop on hours" guidance in the lane brief. The real expected
wall is much lower since the probes confirm most timeouts convert.

## Headline

**Clean sweep: 300/300 PASS at cap=20000. Zero divergence, zero timeout, zero exception, zero archetype-filtered.**

| Outcome | Count | % | Δ vs v4 |
|---|---:|---:|---:|
| **PASS (natural terminal)** | **300** | **100.0%** | **+109 (from 191)** |
| **FAIL_DIVERGENCE** | **0** | 0.0% | 0 (same) |
| **FAIL_EXCEPTION** | **0** | 0.0% | 0 (same) |
| **FAIL_TIMEOUT (hit cap=20000)** | **0** | 0.0% | **−109 (from 109)** |
| **ARCHETYPE_FILTERED** | 0 | 0.0% | 0 (same) |
| **total games** | 300 | 100% | — |
| wall time | **1607.7s (26.8 min)** | | — |
| per-game wall | **5.36s avg** | | — |

### Action-count distribution (PASS only — i.e. all 300 games)

| Statistic | Value | Interpretation |
|---|---:|---|
| min actions to terminal | 542 | shortest natural game |
| median (p50) | 2461 | well inside v4's cap=4000 |
| p95 | 4941 | the long tail of deck-out races |
| max | **5215** | longest natural game in the grid |
| games requiring > 4000 actions | **109 (36.3%)** | exactly matches the v4 FAIL_TIMEOUT count |

The 36.3% of games that hit cap=4000 in v4 (`s6_scale_verify_v4.json`) are
the same 36.3% that here required between 4001 and 5215 actions to reach
natural terminal — confirming the prior agent's pilot read of the residual
as "cap-bound, not divergent." The **max natural game ran to 5215 actions**;
the cap=20000 setting left ~4× headroom over the worst observed converger.

### Per-archetype: every arch in 0–59 converged 5/5 PASS

The `summary.per_archetype` map shows `{"PASS": 5}` for all 60 archetypes —
no archetype-localized failure mode, no seed-localized failure mode. The
parity surface is uniform across the full C4-class admit-set at terminal.

## What flip-gate gap this closes

This artifact **fully closes axis 2** of the user's 2026-05-20 enumerated
flip-gate gaps:

> **Real-game-trajectory surface — cap=4000 sampled, NOT real-game-end.**

After this sweep, the real-game-trajectory parity surface is exercised
**end-to-end on 100.0% of the C4-class grid (300/300 games at natural
terminal)**, with **zero FAIL_DIVERGENCE**. The v4 finding ("191 PASS / 109
cap-bound TIMEOUTs") is now upgraded to "300 PASS / 0 cap-bound". The
109 v4 ex-timeouts are confirmed to be **cap-bound, NOT structurally-
uncloseable** — every one converged to a clean PASS between 4001 and
5215 actions. There is no residual TIMEOUT population at cap=20000.

The cap=20000 result is a **strict upgrade** over the v4 cap=4000 result on
this axis: any v4 PASS stayed PASS, and every v4 TIMEOUT converted to PASS.
This rules out the "the timeouts mask divergences that would have surfaced
between step 4000 and the natural terminal" reading of the v4 headline.

## What flip-gate gap remains open

Still open after this artifact (per the 2026-05-20 user enumeration):

1. **Full card pool** (axis 1) — separate lane (`feature/probe-batch-*`).
2. **Full test surface** (axis 3) — separate lane (`feature/s7-ce5-deadcode-excision`
   pending user review).
3. **Deferred alt-cost flags** (axis 4) — separate axis, no current emission
   site.

**No conditional residual remains on this axis.** `FAIL_TIMEOUT = 0` at
cap=20000 — there is no "converges past 20000 steps" tail to characterize.
The natural terminal of the worst game in the grid (max=5215 actions) sits
comfortably inside the cap with ~4× headroom. The v4 PASS-population step-
count distribution (p95 = 3484, max < 4000) extends here to a full-300
PASS-population distribution with p95 = 4941, max = 5215; the long tail is
finite and bounded.

## Methodology notes

* `--driver rust_shadow` exercises the EXACT CE5-free per-step compare contract
  of the cap-4000 v4/v5 sweep; the only knob changed is `--shadow-max-steps`.
  This is parity-safe by construction: raising the upper bound on an otherwise
  deterministic per-(spec, seed) decision loop can only convert
  FAIL_TIMEOUT → PASS/DIVERGENCE, never the reverse (see
  `rust_shadow.py:638-641` and the `bench_trajectory_parity.py:1256-1265`
  docstring).
* The bench script does NOT modify any production module. The artifact is a
  pure measurement, not a behavior change. No `rust/src/` changes, no
  `src/mtg_bot/` changes, no `cross_engine.py` changes, no `.pyd` rebuild.
* The artifact follows `feedback_no_fallback_hybrids` discipline: a
  `ShadowDivergenceError` is recorded as FAIL_DIVERGENCE (NOT a silent
  fallback to `step_both`), a Rust-side raw `apply_action` raise is recorded
  as FAIL_EXCEPTION, a non-terminal end-of-budget is FAIL_TIMEOUT.

---

*Generated by the trajectory-parity-terminal-scale lane
(`feature/trajectory-parity-terminal-scale` off `main` @ `cd330540`).
PURE-PYTHON measurement — zero `rust/src/` change, zero `src/` change, zero
`cross_engine.py`/`parity_smoke.py` change; the `.pyd` was NOT rebuilt.*
