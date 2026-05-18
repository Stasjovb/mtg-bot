# Bake-in pin scale-coverage gap — characterization + sentinel design

**Status:** Open finding from the G7 S6 scale-verify v2 run (`s6_scale_verify_v2.json`
at repo root, 300-game C4-class sweep on post-cycle-38 main `79b50dc5`).
**Scope:** A workflow-reliability gap, not an engine bug — the parity engine work
is being closed by sibling lanes. This doc + the new sentinel test
(`tests/test_bake_in_scale_sentinel.py`) close the **gap between bake-in green and
scale green** so future agents cannot ship a verify-first-green closure that
silently fails at scale.

---

## 1. The finding

`tests/test_rust_shadow_bakein.py` (24 pinned tests) +
`tests/test_g7_s6_scale_verify.py` (6 pinned cases + 1 negative-control) are
**ALL GREEN** on current main `b6316e65` (post G2+G3 merge + scale-verify v2
evidence commit). Yet the scale-verify v2 sweep on the same commit returned:

| Status            | Count |
|-------------------|------:|
| PASS              |   180 |
| FAIL_DIVERGENCE   |    18 |
| FAIL_TIMEOUT      |   102 |
| FAIL_EXCEPTION    |     0 |
| **Total**         |   300 |

That is, **18 real bake-in divergences at scale that the bake-in pin tests do not
see.** The shipped pin tests overstate closure relative to the scale sweep.

The cycle-37b worklog entry calls this out:

> "Bake-in pin tests ALL pass green (re-characterized to runs-to-terminal). But the
> SCALE sweep finds 18 residuals at different arch/seed combinations the bake-in
> pins don't cover. This is a real 'bake-in pins are insufficient sentinels at
> scale' finding — the pin tests over-state closure relative to the scale sweep."

This doc characterizes WHY the gap exists and the design of the new sentinel that
closes it.

---

## 2. Why the gap exists

### 2a. The bake-in pins are repro-specific by design

Both `tests/test_rust_shadow_bakein.py` and `tests/test_g7_s6_scale_verify.py`
encode one (archetype, seed) per pin. The full enumerated coverage across both
files is:

| File / pin                                            | (archetype, seed) |
|-------------------------------------------------------|-------------------|
| `test_rust_shadow_bakein.py` — Class-C warp-EXILE     | (1, 1)            |
| `test_rust_shadow_bakein.py` — Class-E mana-pool      | (1, 0)            |
| `test_rust_shadow_bakein.py` — Class-A ActivateAbility| (1, 0)            |
| `test_rust_shadow_bakein.py` — Class-D castset        | (1, 0)            |
| `test_rust_shadow_bakein.py` — Class-D 1of23          | (1, 0)            |
| `test_g7_s6_scale_verify.py` — Frontier (a)           | (2, 1)            |
| `test_g7_s6_scale_verify.py` — Frontier (b)           | (5, 0)            |
| `test_g7_s6_scale_verify.py` — Class A                | (2, 1)            |
| `test_g7_s6_scale_verify.py` — Class B                | (5, 0)            |
| `test_g7_s6_scale_verify.py` — Class C                | (1, 1)            |
| `test_g7_s6_scale_verify.py` — Class D                | (7, 0)            |
| `test_g7_s6_scale_verify.py` — Class E                | (1, 0)            |

**Five distinct repros**: arch1/s0, arch1/s1, arch2/s1, arch5/s0, arch7/s0.
This is the maximally efficient "one canonical repro per axis class" design.
Every closure-flip lands at one of these 5 repros. The classifier covers the
5-class enumerated frontier exhaustively; what each pin asserts is correctly
representative of its CLASS.

### 2b. Scale residuals do not coincide with the bake-in repros

The 18 scale-v2 FAIL_DIVERGENCE games are at:

```
arch5/s1, arch9/s1, arch9/s3, arch9/s4, arch10/s1, arch10/s2,
arch11/s1, arch11/s2, arch12/s1, arch12/s2, arch14/s4, arch16/s2,
arch17/s2, arch21/s4, arch38/s0, arch39/s3, arch42/s4, arch51/s0
```

Spanning 13 distinct archetypes (5, 9, 10, 11, 12, 14, 16, 17, 21, 38, 39, 42, 51).

**Overlap with the 5 bake-in repros: zero.** Not "near-zero" — exact zero.

Divergence-shape histogram:

| Shape                                                                          | Count |
|--------------------------------------------------------------------------------|------:|
| `LEGAL_SET_EQ::fields:cast_spell`                                              |    12 |
| `STATE_EQ::fields:Forest,Icetill Explorer,Island,Lander,Mountain,battlefield`  |     3 |
| `STATE_EQ::fields:life_p1`                                                     |     1 |
| `STATE_EQ::fields:Forest,Plains,Robot,Swamp,battlefield`                       |     1 |
| `STATE_EQ::fields:Germinating Wurm,exile_p1`                                   |     1 |

Per `scripts/scout_s6_classify.py`, this maps to:
- 12× **Class D** (`LEGAL_SET_EQ` + `cast_spell`)
- 5× **Class C** (`STATE_EQ` + `battlefield`/`exile`)
- 1× **UNCLASSIFIED** (`STATE_EQ` + `life_p1` — fields don't match the classifier's
  `priority_player` / battlefield / exile / mana_pool buckets; the classifier
  returns `?`. This is the in-flight UNCLASSIFIED life_p1 combat-damage residual
  the sibling lanes are working.)

### 2c. The structural cause

The bake-in pins are **per-class canonical repros** (one (arch, seed) per
class), but the scale space (60 arches × 5 seeds = 300 games) carries **many
distinct (arch, seed) combinations that exercise the same class** with different
deck composition, draw order, and combat geometry — and a class can stay open at
SOME (arch, seed) combinations while looking closed at OTHERS.

A class-canonical pin shows green iff its single chosen (arch, seed) reaches
terminal cleanly. It cannot see the rest of the class's residual surface.

When a class is closed at its canonical repro but NOT closed at other arch/seeds,
the bake-in goes green while the scale sweep stays red. That is the case here:
the 5-class inventory is at green for its canonical repros, but the 12+5+1 = 18
scale residuals are in OTHER (arch, seed) combinations of the same classes (plus
one in a new shape that exposes a classifier gap, the life_p1 UNCLASSIFIED).

This is not a bug in the bake-in pins — they faithfully characterize their
chosen repros — it is a coverage gap in the bake-in-as-scale-sentinel role.
**Bake-in pins are excellent class-repro tripwires; they were never meant to be
scale sentinels, and they aren't.**

---

## 3. Design of the closure: a new scale-aware sentinel class of pin

The fix is a NEW class of pin in `tests/test_bake_in_scale_sentinel.py`, NOT a
replacement for the per-repro bake-in pins. The per-repro pins remain the
authoritative class-canonical tripwires (they catch closure regressions LOUDLY
with byte-exact arch/seed/step targeting). The new sentinel adds the missing
"scale green" half of the contract.

### 3a. What the sentinel asserts

Four invariants over a SAMPLED scale sweep:

1. **Zero divergences.** `n_fail_divergence == 0`. This is the load-bearing
   invariant — if anything trips, the sentinel fails loud with the full
   classified output (arch/seed/kind/fields).

2. **Zero unclassified shapes.** Every divergence shape (when there is one)
   must map to a known class A-E via `scripts/scout_s6_classify.py`. An
   unclassified `?` shape means a NEW G-axis surfaced — surface LOUD.

3. **PASS-rate floor.** `n_pass / n_sample >= 0.40`. This is a sanity check
   that we are not silently degenerating to FAIL_TIMEOUT or
   ARCHETYPE_FILTERED everywhere. The floor is well below the v2 main rate
   (180/300 = 60%) but well above zero to catch pipeline degradation.

4. **No closed-axis regression.** No divergence message mentions `hand_p0`
   or `('blocker',` (the same regression guard `scout_s6_classify.py` uses
   for the closed S5a / combat-blocker axes).

If any invariant fails the test raises with a classified, per-(arch, seed)
breakdown so the failure is actionable, not just `assert False`. The output
shape is byte-consistent with `scout_s6_classify.py`'s frontier-class buckets
so existing operator muscle memory carries over.

### 3b. Sample design

The sentinel runs a DETERMINISTIC stratified subsample of the C4-class space
(arches 0-59 × seeds 0-4 = 300 games), drawn at fixed RNG seed so the same
sample runs every invocation and parity-checking against the v2 baseline stays
meaningful.

The sample is sized for two goals:
- **Catch the 18 residuals on current main** so the sentinel goes RED before
  sibling fixes land.
- **Stay under ~60-90s wall** so it remains usable as a pre-merge gate.

The 300-game sweep takes ~22 minutes serial. To hit a sub-60s budget the
sample must be small (≤ 20 games at ~3-5s per game). To still see the 18/300
= 6% residual rate reliably, the sample is **stratified** rather than uniform-random:

| Stratum                                              | n  | rationale                                                                                |
|------------------------------------------------------|---:|------------------------------------------------------------------------------------------|
| **A — residual-bearing arches**                      | 14 | one (arch, seed) per distinct scale-v2 divergence-bearing arch; covers all 5 shape classes |
| **B — clean controls**                               |  6 | random sample from arches with all-PASS in scale-v2; sanity check that healthy paths stay clean |
| **Total**                                            | 20 |                                                                                          |

Stratum A is the load-bearing one: by construction it guarantees the sentinel
catches the 18 residuals (each residual-bearing arch has at least one residual
seed in stratum A). Stratum B is the negative control — if Stratum B starts
showing divergences after sibling fixes land, that's a regression signal.

The stratified design has one trade-off vs uniform sampling: the sentinel
**cannot detect NEW residual-bearing arches that the v2 baseline did not see**.
That is an accepted limitation, mitigated by the fact that the **full** 300-game
scale-verify is run periodically (the orchestrator owns that cadence) and
re-stratification is a one-line edit to refresh the sentinel's Stratum A from
the latest scale-verify JSON.

This is explicitly NOT a hybrid fallback ("if scale finds something the pin
doesn't catch, skip it"). The pin catches what the stratified sample is targeted
to catch; the full 300-game scale-verify remains the wider sentinel that catches
the rest. The two layers compose.

### 3c. Wall-time budget

Per scale-v2 measurements (PASS ~3.3s, FAIL_TIMEOUT ~6.7s, FAIL_DIVERGENCE
~3.9s), 20 games serial costs roughly:

- All-PASS upper bound: 20 × 6.7s = 134s
- Realistic mix on red main (14 div, 6 pass): 14 × 3.9s + 6 × 3.3s ≈ 75s
- All-PASS lower bound after fixes land: 20 × 3.3s = 66s

Targeting **~90s typical, capped at ~150s**. This is firmly in `@pytest.mark.slow`
territory — it is NOT for the inner-loop pytest invocation and explicitly NOT
part of the 4-file core gate (whose wall-time discipline would balloon).

The sentinel is marked `@pytest.mark.slow` + skipped under `MTG_BOT_FAST_TESTS=1`
matching the project convention (`tests/test_worker_daemon_production_runner.py`
sets the precedent at line 962).

### 3d. Failure mode discipline

`feedback_silent_noop_pipelines` — sample-of-zero must fail loud. The sentinel
asserts `n_games_run == EXPECTED_SAMPLE_SIZE` so a misconfigured subsample
cannot silently shrink to zero and false-pass.

`feedback_no_fallback_hybrids` — no try/except wrapping the divergence detection;
ShadowDivergenceError + raw exceptions inside `drive_one_game_rust_shadow` flow
through the bench-script's existing GameResult shaping (already battle-tested by
the 300-game v2 run).

`feedback_parity_new_code_is_right` — not applicable; this is test infrastructure,
not parity logic.

---

## 4. Expected behavior across the closure timeline

| Main state                                              | Sentinel behavior                                |
|---------------------------------------------------------|--------------------------------------------------|
| Current main `b6316e65` (18 residuals open)             | **RED** — invariants 1, 2, or both fail loud     |
| Sibling Class-C lane lands (warp-5)                     | Still red (Class-D + UNCLASSIFIED still open)    |
| Sibling Class-D lane lands (cast_spell-12)              | Still red (UNCLASSIFIED life_p1 still open)      |
| Sibling UNCLASSIFIED lane lands (life_p1-1)             | **GREEN** — closure-flip-at-scale transition     |

The closure-flip pattern from the bake-in pin discipline applies cleanly here,
just at the scale level: the pin is RED today by design, and goes GREEN exactly
when scale-green is achieved.

---

## 5. Re-characterization rules (for future agents)

If the sentinel stops firing while the 300-game scale-verify still shows
residuals, the sample drifted out of coverage — RE-CHARACTERIZE the Stratum A
list from the latest scale-verify JSON (a 5-minute edit), DO NOT relax the
invariants.

If the sentinel fires on a SHAPE that does not appear in
`scripts/scout_s6_classify.py`, that is a new G-axis. File a focused follow-up,
add the new shape to the classifier, then update Stratum A if the new shape lives
at a new arch.

If the PASS-rate floor (40%) starts failing without divergences (lots of new
FAIL_TIMEOUT or ARCHETYPE_FILTERED), that is a pipeline degradation. Investigate
the underlying scale-v2-style behavior before adjusting the floor; the floor is
a backstop, not a knob.
