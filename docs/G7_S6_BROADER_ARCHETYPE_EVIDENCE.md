# G7 S6 — Broader archetype matrix scale-verify v6 (archetypes 60-119 at cap=20000)

Sibling artifact to [`G7_S6_TERMINAL_SCALE_EVIDENCE.md`](G7_S6_TERMINAL_SCALE_EVIDENCE.md)
(the cap=20000 sweep on archetypes 0-59 = "C4-class") and
[`FLIP_READINESS_EVIDENCE_2026_05_19.md`](FLIP_READINESS_EVIDENCE_2026_05_19.md).
**Closes/widens the same flip-gate axis 2 measurement** at a second 60-archetype
slice (60-119), at the same per-archetype density (5 seeds each = 300 games).
Together v5 (0-59) + v6 (60-119) cover 120/5000 archetypes = 2.4% of the deck
pool at terminal-run cap=20000.

## Why this run

The v5_terminal artifact answered "does real-game-trajectory parity hold on the
C4-class archetype set" (YES — 300/300 PASS). It did NOT answer "does that hold
beyond C4-class". The 17lands deck pool has ~5000 archetypes; v5 covers
1.2%. The user's 2026-05-20 flip-gate bar explicitly calls out the
archetype-coverage axis as one of the residual concerns. **v6 extends the same
methodology to archetypes 60-119** — same per-arch density, same cap, same
driver, same deck source.

## Exact scope swept

| Field | Value |
|---|---|
| Engine `.pyd` / SoT commit | `f8f1e103` (main HEAD post-MMM-merge, post-PPP-merge, post-S7-merge, post-trajectory-v5-merge) |
| Tooling commit | `feature/broader-archetype-sweep` off `f8f1e103` |
| Driver | `rust_shadow` (identical contract to v5_terminal) |
| Grid | `--archetypes 60-119 --seeds 0,1,2,3,4` = **300 games** |
| Deck source | `--decks 17lands` (real EoE production decks) |
| Cap | `--shadow-max-steps 20000` (same as v5_terminal) |
| Exact command | `PYTHONPATH=src .venv-py313/Scripts/python.exe scripts/bench_trajectory_parity.py --archetypes 60-119 --seeds 0,1,2,3,4 --driver rust_shadow --shadow-max-steps 20000 --json-out s6_scale_verify_v6_broader_60_119.json --verbose` |
| Raw artifact | `s6_scale_verify_v6_broader_60_119.json` + `s6_scale_verify_v6_broader_60_119.log` |

## Headline

| Outcome | Count | % | Δ vs v5_terminal (0-59) |
|---|---:|---:|---|
| **PASS (natural terminal)** | **297** | 99.0% | **−3** (was 300/300) |
| **FAIL_DIVERGENCE** | **3** | **1.0%** | **+3** (was 0) |
| **FAIL_TIMEOUT** | 0 | 0.0% | 0 |
| **FAIL_EXCEPTION** | 0 | 0.0% | 0 |
| **total games** | 300 | 100% | — |
| wall time | 22.5 min | | −4.3 min |

**Per-archetype 5/5 PASS rate: 57/60 archetypes** (vs v5's 60/60).

## The 3 newly-surfaced divergences

All 3 belong to the **G5-family priority_player axis** that prior cycles
documented as the dominant residual pre-cycle-37 (`feature/g5-priority-port`
closure landed at commit `86411a99`). The C4 sample (archetypes 0-59) never
surfaced this axis at terminal cap=20000; the 60-119 slice does.

| Game | Step | Python priority_player | Rust priority_player | Shape |
|---|---:|---:|---:|---|
| arch=78 seed=2 | 1454 | 1 | 0 | python-side-extra-priority |
| arch=79 seed=2 | 1454 | 1 | 0 | python-side-extra-priority |
| arch=114 seed=1 | 772 | 0 | 1 | rust-side-extra-priority |

**Observations:**
* arch=78 + arch=79 both fail at the **identical step number (1454)** and
  identical priority shape — strongly suggests the two archetypes share a
  near-duplicate deck shape that exercises the same priority-loop edge case.
* arch=114 fails in the OPPOSITE direction (Rust has priority, Python doesn't)
  — this is symmetric to the prior closure's pattern; not a one-sided bug.
* All 3 divergences are at the `STATE_EQ::fields:priority_player` per-step
  compare. No CHOSEN_EQ / LEGAL_SET_EQ / battlefield / stack / exile / library
  divergences surfaced.
* No `FAIL_TIMEOUT` games — the cap=20000 methodology is fully exercised; the
  failures are genuine divergences, not timeout proxies.

**This is the highest-value finding of this sweep.** Filed as follow-up todo
`broader-sweep-priority-player-residuals` for a sibling lane to characterize
+ pin + close per the project's existing divergence-pin cadence. Closure path
will likely mirror the cycle-37 `86411a99` priority-port adapter fix
(pure-Python `rust_engine_adapter.py:_run_priority_action` change — no `.pyd`
rebuild needed) applied to whichever edge case the 60-119 slice exercises.

## What flip-gate gap this closes vs leaves open

**Closed:** the question "does C4-cap=20000-clean parity extrapolate beyond
the 0-59 archetype slice with the same per-arch density?" The honest answer
is: **mostly yes (99.0%)**, with a single recurring divergence axis (priority_player,
3/300, dominantly G5-family).

**Still open** (post-v6, before the priority_player closure):
* The 3 priority_player residuals must be characterized + closed before any
  flip-gate evidence base claims "divergence-clean at scale". The flip-readiness
  doc's GO-with-deferral recommendation is **unchanged** by this finding (axis
  1 was already PARTIAL; this just refines the residual shape), but the
  honest read for the user's GO call is: **wait for priority_player residual
  closure OR ship with explicit acceptance of a ~1% divergence rate at
  broader scale**.
* Archetypes 120-4999 (97.6% of the deck pool) remain unswept at terminal
  cap=20000. The methodology is proven; further widening is a function of
  wall time + diminishing marginal evidence weight.
* Loader-admit denominator caveat (from `FLIP_READINESS_EVIDENCE_2026_05_19.md`):
  the actual flip surface is ~20% deck-weighted non-land, and the C6 hard-admit
  pin (`66485d6d`) fails-loud on non-admitted cards — so 5000-archetype-coverage
  is not strictly required for flip safety.

## Methodology notes

* Identical `--driver rust_shadow` contract to v5_terminal — same per-step
  compare, same CE5-free harness, same cap=20000.
* The bench script was NOT modified; pure measurement at a different archetype
  range.
* The agent originally assigned this lane bailed mid-bench (after 15/300
  games). Orchestrator restarted the bench in a parent shell that survived
  the agent exit — full 300/300 run completed cleanly in 22.5 min.
* `.pyd` byte-identity: the shared canonical `.pyd` at
  `.venv-py313/Lib/site-packages/mtg_bot_engine/` was loaded from main
  `f8f1e103` at bench start and remained in-memory throughout. Sibling lanes
  may have overwritten the on-disk `.pyd` during the run but loaded-module
  cache semantics ensured the bench used a consistent build start-to-finish.

---

*Generated by `feature/broader-archetype-sweep` off main `f8f1e103`. Pure
measurement — zero `rust/src/` change, zero `src/` change, zero
`cross_engine.py` change; `.pyd` was NOT rebuilt by this lane.*
