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

**RESULT (2026-05-18): CONFIRMED — pre-registered prediction held;
the anticipated falsifier did NOT trigger.** Ablation `v1` (20
epochs, same byte-identical 65-file dataset, scratch registry) vs
production `v5` (5 epochs), head-to-head at nodes=200, seats
alternated:

| metric | value |
|--|--|
| new (20ep) wins / old (5ep) wins / draws | **23 / 9 / 0** |
| new win-rate (decisive n=32) | **71.9 %** |
| Wilson 95 % CI | **[0.546, 0.844]** |
| gate (LB ≥ 0.525) | **PASS** (LB 0.546) → early-stopped |
| crashed | 0 |

**Verdict: more epochs IS gate-promotable strength.** Training v5's
*exact* architecture on its *exact* data for 20 epochs instead of 5
yields a net that clears the project's promotion gate against v5 —
the only variable changed was epochs (+ enabling early-stop).
**v5 was genuinely undertrained**; its `early_stop_patience=None`
5-epoch hard cap (flagged in D1) was leaving gate-promotable strength
unfit. This is the *cheapest possible* lever — no new self-play, no
deeper search, no architecture change.

**Statistical honesty:** n=32 is small (early-stop fired *because*
the effect is large); the CI is wide ([0.55, 0.84]) so the *point*
71.9 % is noisy. The robust claim is the gate criterion — "clears
the 0.525 promotion floor with Wilson-LB 0.546" — not "exactly
72 %".

**The loss curve mis-predicted this (recorded honestly).** The
pre-run expectation, read off the secondary loss readout, was the
*falsifier*: 20-epoch `val_value_loss` was noisy ~0.003–0.007 (best
0.00052 @e15, bouncing; total best-val 0.2090 → 0.2056, ~1.6 %, then
slight overfit past e14) and **`val_policy_loss` was dead-flat at
~0.205 for all 20 epochs** (D1's flat-policy finding holds at 20ep).
That looked like "marginal, mostly noise." The **gate said the
opposite.** Mechanism: a better-fit *value* head alone substantially
strengthens MCTS — value estimates drive PUCT selection and leaf
evaluation even with an unchanged policy prior. Loss magnitude badly
under-predicted the strength gain. This is the loss-≠-strength
principle cutting *against* the loss-based read — exactly why the
gate, not the curve, is the arbiter.

---

## Diagnostic 4 — the value head memorises game identity (2026-09-24, MEASURED)

**D1's "no overfit" read was an artefact of the split, and it
inverted once the s2 lineage was measured on a GAME-level held-out
split.** Every s2 version `v2`–`v7` (`trained_weights_s2/*/metadata.
json`) trains to value-MSE ≈0.005 while its held-out value loss sits
at **1.42–1.78** — *worse than the constant-0 predictor* (MSE 1.0
against ±1 outcome labels). At turn ≤3 the value head hit 94.8 %
outcome-sign agreement on training games and 48.2 % (a coin flip) on
held-out games. The deck pair and the exact card printings go
straight into `printing_embed`, so the model can key on game identity
and recall the stored outcome. The policy head is fine (top-1 0.62 vs
0.39 uniform); PUCT guided by saturated ±1 coin-flip values plays
worse than random.

Contributing settings, all since fixed (`feature/holdout-value-gate`):
`dropout 0.0`, Adam with no weight decay, and early stopping that
tracked `best_val_epoch` while SAVING the final epoch's weights.

Measured before/after, same 110-file / **180,582-row** subset of
`iterate_data_s2` (18,660 held-out rows), 3-epoch cap, production
trunk, RTX 5090, 3 seeds each (seed also drives the split, so the
pairs are matched):

| seed | before: MSE / r | after: MSE / r |
|--|--|--|
| 0 | 1.5526 / **0.203** | 1.0799 / **0.431** |
| 1 | 2.0530 / −0.068 | 1.6727 / 0.129 |
| 2 | 2.0164 / −0.064 | 1.6001 / 0.120 |
| **mean** | **1.874 / 0.024** | **1.451 / 0.226** |

("before" = `--dropout 0 --weight-decay 0 --keep-last-epoch`;
"after" = the new defaults `--dropout 0.1 --weight-decay 1e-4` +
restore-best.)

Two readings, both load-bearing:

1. **Regularisation + restore-best helps, monotonically and on every
   seed** (−23 % MSE, corr 0.02 → 0.23) — but it is **not a fix**.
   All six runs are still at or above the constant-0 predictor, so
   the held-out gate rejects all of them. Do not read the improvement
   as "solved".
2. **The trivial life-differential baseline beats the trained value
   head in every configuration** (corr 0.51–0.62 vs 0.02–0.23 on the
   same rows). Until a value head clears *that*, value-guided search
   is adding noise, not evaluation.

**Consequence for scaling decisions:** more epochs (D3) and more
data are now suspect as the automatic answer — at 180k rows with
per-game printings in the input, the extra epochs buy memorisation.
The ~3,000-game s2 pool has too few distinct deck pairs relative to
what the printing embedding can key on. Candidate next moves, in
increasing cost: heavier dropout / weight decay; dropping or
bottlenecking the printing embedding for the value head; many more
distinct deck pairs per iteration; a value target that isn't the
final-outcome label (e.g. bootstrapped / TD).

`mtg_bot train --architecture structured` now REFUSES to register a
version whose held-out value MSE is ≥ `--min-holdout-value-quality`
(default 1.0) and exits 3; `mtg_bot iterate` marks that cycle failed,
keeps `current_best`, and runs the next cycle. The metrics
(held-out MSE, corr, constant-0 MSE, life-diff baseline corr) land in
`metadata.json`, the progress JSON and the training card whether the
gate passes or fails.

---

## Synthesis — what this means for the next iterate cycle

As of 2026-05-18 **three of four levers are resolved, two validated**:

> **2026-09-24 amendment: read D4 before acting on the list below.**
> D4 measured the value head on a GAME-level held-out split and found
> it *worse than the constant-0 predictor* on every s2 version. That
> reverses D1's "no overfit" premise (D1's val split did not hold out
> whole games) and puts a caveat on D3's "more epochs, free strength"
> — past the memorisation point, extra epochs buy recall of stored
> outcomes. The depth lever (D2) is unaffected; it is about policy
> targets.

- **Trunk width — NOT indicated.** D1: no overfit, value head still
  learning on the current trunk. Scaling width has the *least*
  supporting evidence; do not do it on a hunch. (D4 amends the
  premise: the value head DOES overfit — it memorises game identity —
  so "no overfit" is not an argument for more width either.)
- **Search depth — VALIDATED high-leverage lever (D2).** Raising
  self-play `--nodes` above 200 produces a gate-promotable strength
  gain (monotone through 4×). This is the expensive lever (more
  compute/game) but it is now *evidence-backed*, and the just-enabled
  per-process `--nn-device cuda` worker (validated ≈2×,
  `BENCHMARKING_FINDINGS` §4/§2A) directly offsets the added
  per-game cost. Economics of deeper self-play: `BENCHMARKING_
  FINDINGS` §1/§2 (per-game ≈ linear in `--nodes`).
- **More epochs — VALIDATED, and the CHEAPEST lever (D3, 2026-05-18).**
  20ep vs 5ep on identical data/arch ⇒ 71.9 % (Wilson-LB 0.546 ≥
  gate). v5 was undertrained by its 5-epoch hard cap. Zero extra
  cost — no new self-play, no deeper search, just adequate epochs +
  early-stop patience in the training config. Complementary to depth
  (epochs = fit the targets you have; depth = make better targets).
- **Belief (roadmap Step 2/4) — the next *representational*
  frontier, but NOT the current binding constraint.** Revisit only
  if/when depth + training-budget are exhausted.

**Recommended next production change (priority order, both
gate-validated):**

1. **Immediately, ~zero cost: fix the training config.** v5's
   5-epoch hard cap (`early_stop_patience=None`) under-fit a
   gate-promotable amount of strength (D3). The next training — and
   a re-train of the current best on its existing data — should use
   adequate `--epochs` (≥20) **+** a real `--early-stop-patience`
   (e.g. 3–5). No new self-play, no extra per-game compute. Highest
   ROI available.
2. **Then, costlier: raise self-play `--nodes`** (D2 — better policy
   targets; per-game ≈ linear in nodes, offset by the enabled
   `--nn-device cuda` ≈2×). Size it via the Stage-A knee + Stage-B
   iso-compute sweep.

Both adjudicated by the eval gate across iterations, never by loss
curves alone — D3 is the standing reminder that loss magnitude can
badly mis-predict strength in *either* direction.
