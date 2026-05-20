# G7 S6 — Broader archetype matrix scale-verify v9 (archetypes 240-299 at cap=20000)

Fifth in the broader-archetype-sweep series. Surfaces a **3rd distinct
divergence axis** (`STATE_EQ::fields:battlefield`) not seen in v5-v8.

| Slice | Archetypes | PASS | FAIL_DIVERGENCE breakdown | Wall (min) |
|---|---|---:|---|---:|
| v5_terminal | 0-59 | 300/300 | none | 26.8 |
| v6 | 60-119 | 297/300 | 3 priority_player | 22.5 |
| v7 | 120-179 | 299/300 | 1 priority_player | 26.2 |
| v8 | 180-239 | 291/300 | 5 priority_player + 4 blocker LEGAL_SET_EQ | 21.8 |
| **v9** | **240-299** | **290/300 (96.7%)** | **6 priority_player + 4 battlefield STATE_EQ NEW** | **24.6** |
| **Combined v5-v9** | **0-299 (300/5000 = 6.0% of pool)** | **1477/1500 (98.5%)** | **23** total across **3 distinct axes** | **121.9 (≈ 2h)** |

## v9 headline

| Outcome | Count | % | Δ vs v8 |
|---|---:|---:|---|
| **PASS** | **290** | 96.7% | **−1** |
| **FAIL_DIVERGENCE** | **10** | **3.3%** | **+1** |
| **FAIL_TIMEOUT** | 0 | 0.0% | 0 |
| **FAIL_EXCEPTION** | 0 | 0.0% | 0 |

Per-archetype 5/5 PASS: **52/60** (same as v8). Affected archetypes: 253, 257, 276, 280, 281, 290, 293.

## The 10 v9 divergences

### Priority_player axis (6 — continues v6/v7/v8 trend)

| Game | Step | Direction |
|---|---:|---|
| arch=276 seed=1 | 857 | python-extra `(1,0)` |
| arch=276 seed=3 | 1660 | python-extra `(1,0)` |
| arch=280 seed=1 | 749 | rust-extra `(0,1)` |
| arch=281 seed=0 | 1690 | python-extra `(1,0)` |
| arch=290 seed=3 | 968 | python-extra `(1,0)` |
| arch=293 seed=3 | 968 | python-extra `(1,0)` — arch=290/293 same step+shape |

Cumulative v6+v7+v8+v9 priority_player residuals: **15 / 1200 = 1.25%**.

### **NEW: Battlefield STATE_EQ axis (4)**

| Game | Step | Field detail (truncated) |
|---|---:|---|
| arch=253 seed=2 | 1147 | battlefield divergence with Forest/Lander/Plains/Swamp |
| arch=253 seed=3 | 3791 | battlefield divergence with Forest/Lander/Plains/Swamp |
| arch=257 seed=2 | 1147 | battlefield divergence with Forest/Human Soldier/Island/Plains |
| arch=281 seed=4 | 2358 | battlefield + graveyard_p0 divergence with Knight Luminary |

Distinct from the prior blocker LEGAL_SET_EQ axis (v8). These are STATE_EQ
(per-step state mismatch), specifically on the `battlefield` field — different
permanent multiset between Python and Rust at the divergence step.

The arch=253/257 step-1147 cluster suggests a deterministic deck-shape trigger
(same step, similar Forest/Plains/Lander/Swamp/Human-Soldier composition).
Knight Luminary in arch=281 with graveyard_p0 mismatch suggests a graveyard-
trigger / death-related effect interaction.

**Closure path hypothesis** (verify-first required): some permanent is in a
different zone between engines at the divergence step. Most likely causes:
- An ETB or DIES trigger fires once in one engine, twice (or zero) in the other
- A token created in one engine, not the other (echoes the cycle-39 Lander/Robot token-creation parity closures at `7693c669`/`df4028a7` but those were closed)
- A zone-change rider (e.g. modal "exile then return" or "create token equal to") that resolves asymmetrically

Filed as new follow-up todo `e5b7c9d8...`.

## Cumulative divergence axis summary (post-v9)

| Axis | Count | Distribution | Direction |
|---|---:|---|---|
| `STATE_EQ::fields:priority_player` | 15 | v6:3, v7:1, v8:5, v9:6 | bidirectional |
| `LEGAL_SET_EQ::fields:blocker` | 4 | v8 only | Rust-extra only |
| `STATE_EQ::fields:battlefield` (+ graveyard variant) | 4 | v9 only | mixed |
| **TOTAL** | **23 / 1200 (1.9%)** | | |

Each new slice has surfaced a new axis. Diminishing-marginal-evidence-per-slice
is starting to bind — v10 likely surfaces yet another axis. The pattern
suggests the residual surface is broader than initially thought, but each
individual axis is bounded (<20 occurrences across 6% of the deck pool).

## What this means for flip-readiness

The `FLIP_READINESS_EVIDENCE_2026_05_19.md` recommendation (GO-with-deferral)
remains tenable but the residual landscape is more complex:
- 3 distinct closure tasks now exist (priority_player + blocker LEGAL_SET_EQ + battlefield STATE_EQ)
- All 3 axes show bounded, deterministic patterns (same-step clusters, near-duplicate-deck pairs)
- All 3 axes are post-flip-tripwire-able via the shadow-checker bake-in

**Recommended sequencing:**
1. Close priority_player axis first (easiest; analogous to cycle-37 `86411a99`)
2. Close blocker LEGAL_SET_EQ axis (analogous to cycle-37 B1/C1 cast-side closures)
3. Investigate battlefield STATE_EQ axis (newest; verify-first required to characterize)
4. Run one more broader-sweep (v10) post-closures to confirm regression-free
5. THEN GO

The user retains the call on whether to GO with the 3 axes open (relying on
the bake-in shadow-checker) or wait for the closures.

## Lane recommendation

**Stop generating new broader-sweep slices for now.** Diminishing marginal
return. Better to:
- Investigate one of the 3 axes (verify-first trace + pin)
- Or run one more `mtg_bot iterate` smoke with the shadow-checker active (the bake-in exit criterion per `SOT_FLIP_CUTOVER_PLAN.md` §3)
- Or build a consolidated v5-v9 cross-slice summary doc for the user's GO decision

---

*Generated by `feature/broader-archetype-sweep-240-299` off main `1ad86a92`.
Pure measurement — zero `rust/src/` change, zero `src/` change.*
