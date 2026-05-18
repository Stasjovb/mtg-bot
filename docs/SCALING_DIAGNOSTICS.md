# Scaling diagnostics — which lever is the binding constraint?

Decides where future training compute should go: **trunk width/depth
vs search depth vs data quantity vs belief (Step 2/4)**. Method:
cheap, pre-registered diagnostics, **eval-gate-adjudicated** (the
project's truth metric — playing strength, not loss curves). Same
"add a dated row, don't assert from priors" discipline as
`BENCHMARKING_FINDINGS.md`.

Context: production is the **small structured trunk** (`emb 128 /
n_layers 2 / hidden 256`, v-chain `v1`–`v10`, `current_best v5`,
`architecture: structured` — Steps 1+3 of the NN roadmap landed; the
observable-input-representation ceiling is *spent*, so "scale the
input" is no longer a lever). Box is the shared, concurrently-
orchestrated `desktop-j05412i`; per the §0/§9 contended-box rule,
**ratios within a run are the trustworthy quantity** — and win-rate
is intrinsically contention-robust (load slows both seats equally),
so the verdicts below are valid even on a busy box.

---

## Diagnostic 1 — underfit / overfit (2026-05-17, FREE from v5 `training_history`)

v5: 5 epochs, 653,656 samples, `val_split 0.1`, `early_stop_patience
= None` (early-stop **entirely disabled** — a hard 5-epoch budget cut).

| epoch | val **value** loss | val **policy** loss | val tot / train tot |
|--|--|--|--|
| 1 | 0.0375 | 0.2067 | 0.244 / 0.414 |
| 3 | 0.0118 | 0.2060 | 0.218 / 0.223 |
| 5 | **0.0039** | **0.2051** | **0.209 / 0.219** |

Three inferences:

1. **Trunk width is NOT the binding constraint.** Val ≤ train at
   every epoch (negative gap) ⇒ no overfitting (which alone would
   contraindicate a bigger net); and value train-loss still falling
   ⇒ not capacity-saturated either. No signal points at width.
2. **Value head is undertrained.** Budget-truncated at 5 epochs
   (early-stop disabled) with val-value loss still falling −63% in
   the final epoch — not converged. ⇒ more epochs / data is a cheap
   lever (Diagnostic 3 tests whether it converts to *strength*).
3. **Policy head is target-limited.** Flat from epoch 1 (~0.205,
   <1% move) while the value head on the *same trunk* drops ~10× ⇒
   not a capacity/representation wall (the trunk clearly learns) but
   a **weak teaching signal**: the MCTS policy targets at depth-200
   carry little signal ⇒ the lever is **search depth**, not width.

---

## Diagnostic 2 — policy-improvement gap (2026-05-17, CONFIRMED)

**Causal test** of D1's inference (3): freeze v5, give one seat more
inference search, measure head-to-head win-rate at the deployment
config. Harness `~/.mtg_bot_aws/policy_gap.py` (structured-correct
config per `_build_nn_pimc_config`; v5 weights both seats; seats
alternated per game; Wilson 95% CI; early-stop at the 0.525
`EVAL_GATE_THRESHOLD`).

**Pre-registered prediction** (written before the run): `v5@400` and
`v5@800` each beat `v5@200` with Wilson-LB ≥ 0.525, monotone, not
plateauing by 800. **Falsifier:** CI brackets ~0.5 ⇒ not
depth-limited (target-encoding/representation ceiling) ⇒ redirect
off raw depth.

**Result:**

| pairing | deep win-rate | n decisive | Wilson 95% LB | verdict |
|--|--|--|--|--|
| `v5@400` vs `v5@200` | **66.2 %** | 68 | **0.543** | depth-limited (≥ gate) |
| `v5@800` vs `v5@200` | **72.2 %** | 36 | **0.560** | depth-limited (≥ gate) |

`all gate-significant = True; monotone (Wilson-LB non-decreasing with
depth) = True` — the pre-registered prediction held **exactly**.

**Conclusion: v5's policy is depth-limited, confirmed causally on the
eval-gate truth metric.** More search than the deployment depth
extracts a **gate-promotable** strength gain the raw policy leaves on
the table (66 % at 2×, 72 % at 4×, monotone non-plateauing). This is
the AlphaZero virtuous cycle's actual bottleneck here: weak depth-200
policy targets → weak prior → weakly-guided search. **Deeper
self-play search → sharper policy targets → stronger trained nets**
is now an *empirically validated* lever, not an inference.

---

## Diagnostic 3 — epochs ablation (PRE-REGISTERED; RUNNING)

Tests D1 inference (2) — the *value-head* lever — causally and
cheaply. Controlled: re-train v5's exact architecture on v5's
**byte-identical 65-file dataset** (copied, not `--window-recent`,
which would now grab different newer files), changing **only**
`epochs 5 → 20` + `early_stop_patience None → 3`; scratch registry
(zero production-chain pollution); eval the result vs v5 head-to-head
at **nodes = 200 (deployment depth)**, Wilson CI, 0.525 gate. Full
pre-registration (prediction + falsifier + method): `~/.mtg_bot_aws/
epochs_ablation_PREREG.md`. Harness `epochs_ablation_eval.py`;
one-shot `run_epochs_ablation.sh`. Fired 2026-05-17 after D2 cleared
(GPU-bound; not run concurrently).

**Pre-registered prediction:** more-trained net beats v5 with Wilson
LB ≥ 0.525. **Falsifier (anticipated):** CI brackets ~0.5 / UB <
0.525 despite a lower val-value loss ⇒ *loss ↓ ≠ strength ↑* ⇒
epochs alone is NOT the lever; redirect to data quantity + depth.

> **RESULT: PENDING** — fill on completion (win-rate, Wilson CI,
> verdict, and the secondary readout: where the ablation's val-value
> loss plateaus vs v5's 0.0039).

---

## Synthesis — what this means for the next iterate cycle

As of 2026-05-17 the evidence is unambiguous on two of four levers:

- **Trunk width — NOT indicated.** D1: no overfit, value head still
  learning on the current trunk. Scaling width has the *least*
  supporting evidence; do not do it on a hunch.
- **Search depth — VALIDATED high-leverage lever (D2).** Raising
  self-play `--nodes` above 200 produces a gate-promotable strength
  gain (monotone through 4×). This is the expensive lever (more
  compute/game) but it is now *evidence-backed*, and the just-enabled
  per-process `--nn-device cuda` worker (validated ≈2×,
  `BENCHMARKING_FINDINGS` §4/§2A) directly offsets the added
  per-game cost. Economics of deeper self-play: `BENCHMARKING_
  FINDINGS` §1/§2 (per-game ≈ linear in `--nodes`).
- **More epochs / data — cheap *complementary* value-head lever
  (D3 pending).** Verdict from the running ablation; gate-adjudicated,
  not assumed (loss ↓ ≠ strength ↑ is the registered caveat).
- **Belief (roadmap Step 2/4) — the next *representational*
  frontier, but NOT the current binding constraint.** Revisit only
  if/when depth + training-budget are exhausted.

**Recommended next production change:** raise self-play search depth
(the validated lever), with `--epochs` + a sane `--early-stop-
patience` folded in if D3 confirms the value-head win — both
adjudicated by the eval gate across iterations, never by loss curves
alone.
