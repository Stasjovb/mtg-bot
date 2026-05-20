# Broader-archetype scale-verify — consolidated v5–v9 cross-slice synthesis

**Pure-synthesis cross-slice summary** of the broader-archetype-sweep series
(2026-05-19) covering archetypes 0–299 of the 17lands EoE deck pool, all
at `--shadow-max-steps 20000` natural-terminal cap on the `rust_shadow`
driver, real EoE production decks.

This doc collapses 5 separate slice docs into **one view for the
flip-readiness GO/NO-GO call**.

Source slice docs (read those for the unabbreviated per-slice methodology):

- [`G7_S6_TERMINAL_SCALE_EVIDENCE.md`](G7_S6_TERMINAL_SCALE_EVIDENCE.md) — v5_terminal, 0–59
- [`G7_S6_BROADER_ARCHETYPE_EVIDENCE.md`](G7_S6_BROADER_ARCHETYPE_EVIDENCE.md) — v6, 60–119
- [`G7_S6_BROADER_ARCHETYPE_V7_EVIDENCE.md`](G7_S6_BROADER_ARCHETYPE_V7_EVIDENCE.md) — v7, 120–179
- [`G7_S6_BROADER_ARCHETYPE_V8_EVIDENCE.md`](G7_S6_BROADER_ARCHETYPE_V8_EVIDENCE.md) — v8, 180–239
- [`G7_S6_BROADER_ARCHETYPE_V9_EVIDENCE.md`](G7_S6_BROADER_ARCHETYPE_V9_EVIDENCE.md) — v9, 240–299

Flip-gate context: [`FLIP_READINESS_EVIDENCE_2026_05_19.md`](FLIP_READINESS_EVIDENCE_2026_05_19.md).

Raw JSON artifacts (committed at repo root): `s6_scale_verify_v5_terminal.json`,
`s6_scale_verify_v6_broader_60_119.json`, `s6_scale_verify_v7_broader_120_179.json`,
`s6_scale_verify_v8_broader_180_239.json`, `s6_scale_verify_v9_broader_240_299.json`.

---

## §0 TL;DR

**Combined 1477/1500 (98.5%) PASS across 6.0% of the 5000-archetype deck
pool. 23 residual divergences distribute across 3 distinct axes:**

| Axis | Count | % of 1500 | Distinct slices |
|---|---:|---:|---|
| `STATE_EQ::fields:priority_player` (G5-family long-tail) | **15** | 1.00% | v6, v7, v8, v9 |
| `LEGAL_SET_EQ::fields:blocker` (Rust-extra blocker, NEW v8) | **4** | 0.27% | v8 only |
| `STATE_EQ::fields:battlefield` (+ graveyard variant, NEW v9) | **4** | 0.27% | v9 only |
| **total** | **23** | **1.53%** | — |

Zero FAIL_TIMEOUT, zero FAIL_EXCEPTION across all 1500 games. Every
divergence is a genuine per-step compare mismatch, not a cap proxy.

The picture is **not a single residual that's getting harder to hit at
higher archetype indices**. Each new slice surfaced a previously-unseen
axis, suggesting the residual surface is **broader** than the cycle-37
post-closure "single G5-family long-tail" picture would have predicted.

The user has two reasonable paths (§5 below): close all 3 axes pre-flip
for a cleaner evidence base, or flip now with the bake-in shadow-checker
as the post-flip safety net.

---

## §1 Headline table — slice-by-slice + cumulative

| Slice | Archetypes | Games | PASS | FAIL_DIV | Div rate | Wall (min) | New axis surfaced |
|---|---|---:|---:|---:|---:|---:|---|
| v5_terminal | 0–59 | 300 | 300 (100.0%) | 0 | 0.00% | 26.8 | — |
| v6 | 60–119 | 300 | 297 (99.0%) | 3 | 1.00% | 22.5 | priority_player |
| v7 | 120–179 | 300 | 299 (99.7%) | 1 | 0.33% | 26.2 | — (same axis as v6) |
| v8 | 180–239 | 300 | 291 (97.0%) | 9 | 3.00% | 21.8 | **blocker LEGAL_SET_EQ** |
| v9 | 240–299 | 300 | 290 (96.7%) | 10 | 3.33% | 24.6 | **battlefield STATE_EQ** |
| **Cumulative** | **0–299** | **1500** | **1477 (98.5%)** | **23** | **1.53%** | **121.9 (≈ 2h)** | **3 distinct axes** |

**Per-archetype 5/5 PASS rate:** v5=60/60, v6=57/60, v7=59/60, v8=52/60,
v9=52/60 → cumulative **280/300 archetypes ran 5/5 PASS (93.3%)**. 20
archetypes (6.7%) had ≥1 divergent game; no archetype had ≥3.

**Action-count distributions (PASS-only, per slice):**

| Slice | n | min | p25 | p50 | p75 | p95 | max | mean |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| v5_terminal | 300 | 542 | 1125 | 2461 | 4584 | 4941 | 5215 | 2763 |
| v6 | 297 | 473 | 966 | 1786 | 3319 | 4900 | 5080 | 2210 |
| v7 | 299 | 488 | 1160 | 2075 | 4557 | 4953 | 5126 | 2616 |
| v8 | 291 | 363 | 906 | 1279 | 3370 | 4927 | 5077 | 2152 |
| v9 | 290 | 363 | 924 | 1994 | 4544 | 4943 | 5215 | 2494 |

The p95 stays remarkably stable across slices (~4900–4953) and the max
never exceeds 5215. The cap=20000 leaves ~4× headroom over the worst
observed converger across all 1500 games — the natural-terminal
methodology is fully exercised.

**Divergence step distribution (all 23 residuals):** min=458, p25=968,
p50=1152, p75=1660, max=3791. **Every divergence surfaces well inside
the natural-terminal envelope** (max divergence step is 73% of the max
PASS action count, and 19% of the cap). No "near-terminal" divergence
shape — the residuals cluster in the mid-game.

---

## §2 Per-axis breakdown

### §2.1 Axis A — `STATE_EQ::fields:priority_player` (G5-family long-tail)

**Cumulative: 15 / 1500 games (1.00%); todo `c8d3a5f127e64b9a8e1f3a5b7c9d2e40`.**

| Slice | Count | Direction | Notes |
|---|---:|---|---|
| v5_terminal | 0 | — | did not surface |
| v6 | 3 | bidirectional (2 python-extra, 1 rust-extra) | arch=78+79 same step 1454 (near-duplicate decks) |
| v7 | 1 | rust-extra | arch=133 seed=3 step 1242 |
| v8 | 5 | bidirectional (1 python-extra, 4 rust-extra) | arch=228/229 same step 1830 (near-duplicate) |
| v9 | 6 | bidirectional (5 python-extra, 1 rust-extra) | arch=290/293 same step 968 (near-duplicate) |

**Direction histogram:** 8 python-extra, 7 rust-extra → **fully
bidirectional, 53/47 split**. Not a one-sided bug.

**Step clustering:** the 15 residuals cluster around step 458–1830 with
3 distinct same-step+same-shape pairs (arch=78/79@1454, arch=228/229@1830,
arch=290/293@968) — each pair is a near-duplicate-deck shape exercising
the same priority-loop edge case.

**Cross-slice growth pattern:** rate is rising slowly with archetype
index (0% → 1.00% → 0.33% → 1.67% → 2.00% per slice on this axis
alone). v7 is the only slice that bucks the trend; v8 + v9 settled into
~2%-ish for the axis. The axis is **reliably surfaced** at this scale,
not noise.

**Closure path hypothesis (from todo `c8d3a5f1`):** mirror the cycle-37
`86411a99` priority-port adapter closure pattern — a pure-Python
`src/mtg_bot/search/rust_engine_adapter.py:_run_priority_action` change
covering the long-tail edge case the original closure missed.
**Estimated cost: 1–2 orchestrator cycles** (verify-first trace of the
4 same-step pairs is the fast path to confirm a single root cause covers
multiple directions).

### §2.2 Axis B — `LEGAL_SET_EQ::fields:blocker` (NEW v8)

**Cumulative: 4 / 1500 games (0.27%); todo `d4f6a8c925e73b1a8f5d7c9b3a1e4f60`.**

**Surfaced only in v8** — orthogonal axis to priority_player. All 4
games have the same shape: **Rust's `legal_decisions` offers a `blocker`
action that Python's `legal_actions` does not admit.** Tuple shape
`(action_kind='blocker', attacker_id, blocker_id)`.

| v8 game | Step | Rust-extra blocker | Active player |
|---|---:|---|---:|
| arch=220 seed=2 | 1152 | `('blocker', 0, 60)` | 0 |
| arch=226 seed=2 | 498 | `('blocker', 61, 120)` | 1 |
| arch=228 seed=0 | 976 | `('blocker', 1, 63)` | 0 |
| arch=229 seed=0 | 976 | `('blocker', 1, 63)` | 0 (near-duplicate arch=228/229, same tuple) |

**Direction: one-sided (Rust-extra only).** No python-extra-blocker
shape surfaced.

**Step clustering:** arch=228 + arch=229 at the IDENTICAL step (976) +
IDENTICAL blocker tuple — same deterministic deck-shape trigger.

**Cross-slice growth pattern:** zero in v5/v6/v7, then 4 in v8, then
zero in v9 — **not a slowly-rising surface**, a one-slice cluster on
3 unique archetypes (220, 226, 228≈229). Could be archetype-specific
substrate (a creature with a specific keyword grant or summoning_sick
asymmetry that only exists in this archetype slice). Could equally be
the first hit of a wider axis that v10+ would expand — not enough
slices to discriminate.

**Closure path hypothesis (from todo `d4f6a8c9`):** C1-family analog —
the cycle-37 B1/C1 Slice 1/2/3 closures targeted CAST-side legal-set
asymmetries; this is the same shape on the BLOCKER emission site at
`rust/src/state_ops_legal.rs`. Likely candidates: a block-eligibility
gate (keyword grant, static ability, silent summoning_sick — cross-ref
TTT Pin 2 / Atomic Microsizer), or an attacker-side filter (menace,
evasion) handled asymmetrically. **Estimated cost: 1–2 orchestrator
cycles** for a C1-Slice-style predicate alignment.

### §2.3 Axis C — `STATE_EQ::fields:battlefield` (NEW v9)

**Cumulative: 4 / 1500 games (0.27%); todo `e5b7c9d836f84c2b9a6e8d0c4b2f5070`.**

**Surfaced only in v9** — orthogonal axis to both priority_player and
blocker. Per-step state mismatch on the `battlefield` field; one of
the 4 also carries a `graveyard_p0` sibling.

| v9 game | Step | Field detail (from divergence_shape_histogram) |
|---|---:|---|
| arch=253 seed=2 | 1147 | `battlefield` with Forest/Lander/Plains/Swamp |
| arch=253 seed=3 | 3791 | `battlefield` with Forest/Lander/Plains/Swamp (same arch, different seed) |
| arch=257 seed=2 | 1147 | `battlefield` with Forest/Human Soldier/Island/Plains |
| arch=281 seed=4 | 2358 | `battlefield + graveyard_p0` with Knight Luminary |

**Direction:** "mixed" per the v9 doc — verify-first trace required
to identify which engine's battlefield has the extra/missing permanent
(the JSON only carries the symmetric-diff field set, not the asymmetric
direction).

**Step clustering:** arch=253 seed=2 and arch=257 seed=2 both fail at
step 1147 with Forest/Plains/Lander composition — deterministic
deck-shape trigger. arch=281 seed=4 is the only game with a graveyard
sibling, suggesting a death-trigger / DIES interaction (Knight Luminary).

**Cross-slice growth pattern:** zero in v5–v8, then 4 in v9 — same
"one-slice cluster" shape as the blocker axis. Could be a new axis
that's archetype-localized to ~240–299, or could be the first hit of
a wider surface.

**Closure path hypothesis (from todo `e5b7c9d8`):** verify-first
required. Likely causes: ETB or DIES trigger fires once in one engine
vs twice (or zero) in the other; a token created in one engine, not
the other (echoes the cycle-39 Lander/Robot token-creation parity
closures at `7693c669`/`df4028a7`, but those were closed pre-v8 — v9
surfaces NEW members not in the cycle-39 closure set); or a
zone-change rider (modal "exile then return", "create token equal to")
that resolves asymmetrically. **Estimated cost: 1–2 orchestrator
cycles** depending on the specific effect identified.

---

## §3 Pattern analysis

### §3.1 Is the divergence rate stable, growing, or declining?

Per-slice rate: **0.00%, 1.00%, 0.33%, 3.00%, 3.33%**. The trend is
**slowly growing**, but not monotonically — v7 (0.33%) is the
local minimum between the v6 (1.00%) and v8 (3.00%) slices.

The growth is **dominated by new-axis surfacing**, not by the
priority_player axis intensifying:

- Priority_player axis rate per slice: 0.0%, 1.0%, 0.33%, 1.67%, 2.0%.
  Slow rise; bounded by ~2%.
- Blocker LEGAL_SET_EQ axis: 0.0%, 0.0%, 0.0%, 1.33%, 0.0%. One-slice
  spike, no v9 recurrence.
- Battlefield STATE_EQ axis: 0.0%, 0.0%, 0.0%, 0.0%, 1.33%. One-slice
  spike, no prior occurrence.

**The honest read:** the residual surface is broader than the
cycle-37 closure left behind. Each new 60-archetype slice has roughly
a coin-flip chance of surfacing a previously-unseen axis. **The v6
priority_player surface is real and consistent; the v8 and v9 new axes
are too small a sample to tell whether they're archetype-localized
clusters or wide axes the priority_player slices missed.**

### §3.2 Are residuals clustered or diffuse?

**Both**, depending on the axis.

- **Clustered.** 4 same-step+same-shape near-duplicate-deck pairs across
  the 23 residuals: arch=78/79@1454 (priority), arch=228/229@1830
  (priority), arch=290/293@968 (priority), arch=228/229@976 (blocker).
  Each pair is one root cause × 2 archetypes. If those collapse to
  1 underlying bug per pair, the **effective unique bug count is
  23 − 4 = 19, possibly lower**.
- **Diffuse within axis.** Within priority_player specifically, the
  15 residuals span 11 distinct archetypes and 4 distinct seed slots,
  with steps ranging 458–1830. The axis is not localized to one
  archetype family; it's a long-tail across multiple decks.

### §3.3 Are direction patterns one-sided or bidirectional?

| Axis | Direction split |
|---|---|
| priority_player | **bidirectional** (8 python-extra, 7 rust-extra ≈ 53/47) |
| blocker LEGAL_SET_EQ | **one-sided** (4 Rust-extra, 0 python-extra) |
| battlefield STATE_EQ | mixed (per v9 doc; verify-first required) |

The priority_player bidirectionality echoes the cycle-37 closure
pattern (which also closed both directions). The blocker axis is
one-sided — Rust admits a blocker Python rejects — which makes it a
cleaner closure target (mirror Python's predicate, or fix Python's
predicate if Rust is correct; the parity-new-code-is-right rule
prescribes inspecting which side matches the comprehensive rules).

### §3.4 How does this map to the 17lands long-tail structure?

The 17lands deck pool has 5000 archetypes; v5–v9 covers 300 of them
(6.0%). The 23 residuals are **0.46% of the swept games** and split
across **20 unique affected archetypes** (≤6.7% of swept archetypes,
≤0.4% of the full pool).

The deck-pool long-tail caveat from
[`FLIP_READINESS_EVIDENCE_2026_05_19.md`](FLIP_READINESS_EVIDENCE_2026_05_19.md)
§1: the **loader-admitted** flip surface is ~20% deck-weighted non-land,
not the full pool. The cards driving these 3 residual axes are all
**admitted** (they appear in the rust_shadow per-step compare; if they
weren't admitted, the C6 hard-admit boundary would raise
`NonAdmittedCardError` before any divergence could be measured). So
the residuals **are** on the actual flip surface.

**Extrapolation honest read:** at 1.53% cumulative rate across 6% of
archetypes, projecting linearly to 100% of admitted archetypes is
naive — but a Fermi estimate suggests the broader admitted population
likely carries on the order of **dozens** of priority_player-class
games, **single-digit** new-axis clusters per 60-archetype slice. The
total number of axes is bounded by the engine's actual divergence
surface, which is finite; v10+ slices would diminish the marginal
discovery rate **eventually**, but v5–v9 has not yet reached that
plateau.

---

## §4 Updated flip-gate posture vs `FLIP_READINESS_EVIDENCE_2026_05_19.md`

`FLIP_READINESS_EVIDENCE_2026_05_19.md` recommended **GO-with-deferral**
(Option B), with axis 2 (real-game-trajectory) marked **CLOSED on
C4-class** + v6's footnote mentioning the priority_player residual.
The v6+v7+v8+v9 slices were not folded back into the doc.

**Changes vs that doc:**

| Field | Prior doc state | After v5–v9 |
|---|---|---|
| Axis 2 (real-game-trajectory) | CLOSED on C4-class (0/300 div at cap=20000) | CLOSED on C4-class; 98.5% PASS across 1500 games (6.0% of pool); **3 distinct residual axes** |
| Residual axes flagged | 1 (priority_player, v6 only, 3 games) | **3 axes, 23 games** (priority_player×15, blocker LEGAL_SET_EQ×4, battlefield STATE_EQ×4) |
| Open flip-prep follow-ups | 1 (priority_player closure) | **3** (todos `c8d3a5f1`, `d4f6a8c9`, `e5b7c9d8`) |
| Recommendation | GO-with-deferral, Option B | **Decision now has finer gradation — see §6 Path A vs Path B framing below** |

The original Option B recommendation (axis 4 alt-cost deferral, bake-in
safety net) is **structurally unchanged** — the 3 newly-characterized
residual axes are all of the **same character** as the original axis-2
"residual" call: small-count, well-understood-shape, post-flip-tripwire-able
via the shadow-checker bake-in. The Option B reasoning (the bake-in is
the strictly-better tooling for surfacing these classes of issue
post-flip) **applies equally** to the 3 broader-sweep residuals as to
the axis-4 alt-cost flags.

**What CHANGES the calculus:** the residual axis count went 1 → 3 with
each new slice adding a new axis. The user's GO call should account for
this trend; the next slice (v10+) is moderately likely to add a 4th
axis. There is no a-priori reason to expect axis discovery to plateau
at 3.

---

## §5 Closure sequencing recommendation

If the user chooses Path A (close axes pre-flip — see §6 below), the
recommended sequencing for maximum leverage:

1. **Priority_player first (cycle-37 adapter pattern; easiest).**
   - Largest count (15/23) — closing this drops cumulative residuals to 8/1500 (0.53%)
   - Known closure shape (mirror `86411a99` adapter fix)
   - Bidirectional axis with same-step+near-duplicate-deck pairs — one
     root cause likely covers multiple residuals
   - Pure-Python `rust_engine_adapter.py` change (no `.pyd` rebuild)
   - Estimated 1–2 orchestrator cycles
2. **Blocker LEGAL_SET_EQ second (C1-Slice analog).**
   - One-sided (Rust-extra only) — cleaner closure target than
     bidirectional axes
   - Same-step+same-tuple near-duplicate pair (arch=228/229) suggests
     one underlying predicate fixes both
   - Estimated 1–2 cycles
3. **Battlefield STATE_EQ third (newest; verify-first required).**
   - Smallest sample (4 residuals from 1 slice) — most uncertain
     closure shape until traced
   - Possible cousin to cycle-39 token-creation closures
   - Verify-first trace needed before sizing the closure
   - Estimated 1–3 cycles depending on root cause

**Total Path-A estimate:** ~4–8 orchestrator cycles, plus one v10
broader-sweep re-run to confirm regression-free.

The sequencing is **easiest-known-shape first**; an alternative is
**largest-count first** which gives the same ordering by accident.

---

## §6 Decision framing — Path A vs Path B

Two reasonable paths. **The user decides.**

### Path A — close all 3 axes before flip

**Pros:**

- Cleaner evidence base. Post-closure broader-sweep returns to ≥99.5%
  PASS (or higher), removing the "3 distinct axes" footnote from the
  flip-readiness narrative.
- The 3 axes are characterized concretely (todos `c8d3a5f1`,
  `d4f6a8c9`, `e5b7c9d8`) — closure is well-scoped, not exploratory.
- Closure work happens with the Python SoT still authoritative — any
  closure-side bug stays caught by the existing per-step compare
  before flip.
- Reduces post-flip operational load (fewer tripwires firing during
  bake-in; cleaner separation of axis 4 alt-cost work from broader-sweep
  residual work).

**Cons:**

- ~4–8 orchestrator cycles of delay (Path A) before the flip itself
  (~1 cycle).
- The v10+ slices may surface a 4th axis during closure work — adding
  more axes to close, potentially indefinitely.
- Each closure cycle is itself a Rust-change parity risk (closures
  touch `rust/src/` or the adapter), and the pre-flip-only testing
  surface is **less sensitive** to introduced issues than the post-flip
  bake-in shadow-checker would be (bake-in runs every per-step compare
  on real iterate self-play).
- The cycle-37 closure that covered the original G5-family residual
  did not catch these long-tail variants. There's an honest risk the
  same closure pattern produces another long-tail variant, ad
  infinitum.

### Path B — flip now with bake-in shadow-checker as the safety net

**Pros:**

- Fastest ship — the flip itself is ~1 cycle once gated.
- The bake-in shadow-checker is **strictly more sensitive** to all 3
  residual axes than the broader-sweep bench (per-step compare on real
  iterate self-play, not a fixed 300-game grid).
- The 3 axes become **post-flip closure work** with **better tooling**.
- The flip is **reversible** (one-flag `decision_source` revert);
  Steps 5/6 (Python rules-engine retirement) **stay gated** on bake-in
  closing green.
- This is the path
  [`FLIP_READINESS_EVIDENCE_2026_05_19.md`](FLIP_READINESS_EVIDENCE_2026_05_19.md)
  §7 recommended — the broader-sweep evidence does not invalidate that
  recommendation's structure, only refines the residual surface.

**Cons:**

- Post-flip, the bake-in shadow-checker will be **non-zero on per-game
  divergences during the first real iterate** — every divergent game
  is a SHADOW_DIVERGENCE event. Operator must distinguish "expected
  3-axis residual" from "new regression". The 3 todos describe the
  expected residual shapes; ops-side filtering is non-trivial.
- The user's 2026-05-20 bar was explicitly tightened from the narrow
  C4-CE5-free proof; shipping with 3 known open residual axes is a
  weaker proof base than Path A's "regression-free broader-sweep".
- If post-flip the shadow-checker surfaces a 4th axis (per §3.1's
  trend), the bake-in exit criterion is harder to satisfy.

### Trade-off summary

|  | Path A | Path B |
|---|---|---|
| Time to flip | +4–8 cycles | +0–1 cycles |
| Evidence base at flip | Regression-free broader-sweep | 3 known open axes, post-flip-tripwire-able |
| Risk shape | Closure-side parity bugs caught by Python SoT | Bake-in surfaces residuals + any new regression simultaneously |
| Reversibility | Same (flag flip; Steps 5/6 gated) | Same |
| Operational complexity post-flip | Lower (cleaner bake-in window) | Higher (per-game expected-residual filtering) |

The user's settled posture per
[`FLIP_READINESS_EVIDENCE_2026_05_19.md`](FLIP_READINESS_EVIDENCE_2026_05_19.md)
§7 is that **the bake-in is the strictly-better testing surface** for
residual closure — that argues for Path B. The user's 2026-05-20 bar's
explicit tightening argues for Path A. **No recommendation in this doc.**

---

## §7 Methodology notes (cross-slice)

- All 5 slices use the **identical** `--driver rust_shadow
  --shadow-max-steps 20000 --decks 17lands` contract. The only knob
  changed across slices is `--archetypes` range.
- Each slice ran on a different main HEAD commit as sibling lanes
  merged:
  - v5_terminal @ `cd330540` (merged `ddc0bf6e`)
  - v6 @ `f8f1e103`
  - v7 @ `820ba720`
  - v8 @ `3b7809ed`
  - v9 @ `1ad86a92`
- Pure measurement — zero `rust/src/` change, zero `src/mtg_bot/`
  change, zero `cross_engine.py` change in any slice. No `.pyd`
  rebuild attributable to these lanes.
- All slice docs follow `feedback_no_fallback_hybrids` discipline:
  `ShadowDivergenceError` recorded as FAIL_DIVERGENCE (not silent
  fallback); Rust-side `apply_action` raise as FAIL_EXCEPTION;
  non-terminal end-of-budget as FAIL_TIMEOUT.
- No FAIL_TIMEOUT and no FAIL_EXCEPTION across 1500 games — every
  game converged to natural terminal or to a recorded divergence.

---

## §8 Lane recommendation going forward

Aligned with the v9 doc's "stop generating new slices" recommendation
+ this synthesis:

1. **Stop running new broader-archetype slices** (v10+) until at least
   one of the 3 axes is closed. Diminishing marginal evidence per
   slice; the residual axes are now well-characterized.
2. **Path-A-leaning agents:** pick up the priority_player closure
   (todo `c8d3a5f1`) — highest leverage, known shape.
3. **Path-B-leaning agents:** prep the bake-in shadow-checker exit
   criterion (`SOT_FLIP §3`) — run `mtg_bot iterate` with the
   shadow-checker active and characterize the per-iter divergence-event
   distribution against the 3 expected residual shapes.
4. **Either way:** the broader-sweep bench (`bench_trajectory_parity.py
   --archetypes X-Y --shadow-max-steps 20000`) is the regression gate
   to re-run **after each axis closure** to confirm progress. Same
   methodology, same denominator.

---

*Generated by `feature/broader-sweep-consolidated` off main `fee5888d`
(post-v9-merge HEAD). Pure synthesis — zero engine change, zero test
change, zero `rust/src/` touch, zero `.pyd` rebuild. Direct merge to
main authorized by user for this session.*
