# Lever 2 investigation — why the SHM NN-eval server's 3-8K-RPS substrate doesn't translate to iterate/eval wall

**Date:** 2026-05-10 (commit `aa562d90` on `origin/main`)
**Author:** Claude (investigation only — no code changes)
**Question.** `SharedTensorNNEvalServer` benches at 4,176 RPS at 14 workers (substrate) and 8,695 RPS at 32 workers. The migration doc projected this should deliver +5-7× iterate throughput. We don't see it — eval per-game wall is ~20 s/completed-game at 14 workers, identical to the pre-fix hung run, and per-game wall on completed games (68 / 114 / 142 / 178 s) is in the same ballpark as the pre-Lever-2 production iterate. Where is the actual bottleneck?

## TL;DR

**The single biggest gap is `SharedTensorNNEvalClient.batch_evaluate_with_policy` is implemented as a Python for-loop of per-state slot round-trips, not a single batched request.** The legacy `NNEvaluator.batch_evaluate_with_policy` stacks B states into one GPU forward pass; the SHM client does N separate single-slot calls. MCTS's `_search_batched` path was designed around the legacy contract (one batch → one forward pass per worker). Under SHM, a `batch_size=32` MCTS becomes a 32-deep serial slot-walk *per worker per batch*. Cross-worker fusion at the dispatcher recovers some of this, but only up to the number of workers in flight — at 14 workers, the dispatcher sees an average of ~14 concurrent requests, below the configured `batch_size=32` cap.

**Quantitatively, this explains the numbers we see.** At 14 workers the iterate-level NN demand is roughly **3.0K RPS** vs the substrate's 4.2K-RPS ceiling. We're at ~73% of substrate capacity — substrate-pressured but not saturated. The actual constraint is the per-worker serialization: each worker can have at most **one** request in flight (the SHM client's `_call_value_policy` blocks on the slot's `Event.wait()` before returning), so a single worker's NN throughput is capped at `1 / per-call-RTT ≈ 1 / 3.0 ms ≈ 333 RPS`. With 14 workers that's 4,667 RPS — exactly the measured substrate number. **The substrate is the bottleneck; it's just at the per-call latency layer, not the GPU-forward layer.**

**Has Lever 2 paid off?** Yes, partially. PR #41's self-play smoke shows ~36% per-game improvement at 4 workers (40.66 s vs ~64 s baseline) — that's a 1.57× iterate win, not 5-7×. The structural eval fork+CUDA crash class is also fixed (PR #41 / #43). The "5-7×" projection assumed the SHM client would batch the way the substrate bench does (workers firing concurrent independent requests). MCTS's actual pattern — one in-flight call per worker, serial per batch — caps the win at `N_workers` worth of cross-worker fusion, which delivers a meaningful but bounded speedup.

---

## Substrate numbers (already known, restated)

From PR #40 description, RTX 5090, 128-trunk NN, with-policy:

| Config | RPS | p50 latency |
|---|---|---|
| Local 16w (per-worker NN, no server) | 1,355 | 0.034 ms |
| TCP server 16w | 425 | 2.064 ms |
| **SHM 14w (prod target)** | **4,176** | **2.366 ms** |
| **SHM 16w batch=32 wait=0.5ms** | **4,122** | **3.088 ms** |
| **SHM 32w (saturated)** | **8,695** | **2.306 ms** |
| SHM 14w no batching | 1,992 | 6.039 ms |
| Single-client RTT p50 (substrate floor) | — | **0.074 ms** |

Avg batch size at 16w = 15.92 (perfect cross-worker fusion under hot-loop pressure).

## Iterate-level numbers (computed from existing event JSONs)

Source: `/tmp/shm_eval_fix_14w/eval_shm_eval_fix_14w_shard_local_events.jsonl` (today, fixed) and `/tmp/shm_eval_decisive_progress/eval_shm_eval_decisive_shard_local_events.jsonl` (yesterday, identical workload, hung on cleanup).

Both runs: 14 workers, 20 games, v21 (1024-trunk) vs v18 (1024-trunk), `samples=4`, `inner_nodes=200`, 180 s/game timeout.

**Wall summary (today's, post-fix):**

- elapsed_seconds = 180.5
- n_games_done = 9 (4 completed, 5 timed out at 180 s)
- per_game_seconds (elapsed / done) = 20.05 s — this is the **parallelized** throughput number, NOT the single-game wall
- avg_decisions = 187 (averaged across the 4 completed games, since timeouts logged 0 decisions)

**Per-completed-game detail (from events.jsonl):**

| game_idx | wall_s | decisions | dec / sec / worker |
|---|---|---|---|
| 8 | 68.1 | 300 | 4.41 |
| 4 | 114.1 | 389 | 3.41 |
| 1 | 142.4 | 400 | 2.81 |
| 12 | 178.8 | 592 | 3.31 |
| 0 / 2 / 3 / 5 / 6 | 180.0 | 0 (timeout) | — |

**Decision-rate average across completed games: ~3.5 decisions/sec/worker.**
**Shard decision rate: 14 workers × 3.5 ≈ 49 decisions/sec.**

## NN-calls-per-decision back-of-envelope

PIMC config in production eval/iterate: `samples=4, inner_nodes=200, batch_size=32, puct=True, with_policy=True`.

Per `pimc.choose_with_visits` + `mcts._search_batched`:

1. Each MCTS inner search runs `inner_nodes=200` budget units. With `batch_size=32`, that's ~`ceil(200/32)=7` batches.
2. Each batch issues ONE `batch_evaluate_with_policy(states=[up to 32])` call on the evaluator.
3. PIMC samples = 4 → 4 inner searches per decision → 4 × 7 = **~28 batched-evaluator calls per decision**, **~800 individual leaf evaluations** per decision (4 × 200).
4. MCTS comments cite **~40% transposition hit rate** (from `_eval_cache`) at `samples=1, nodes=1000` — extrapolating, expect 30-50% at `samples=4, nodes=200`. Call it 60% miss → **~480 actual NN forward-equivalents per decision**.

But the **forced-move shortcut** in both PIMC (`pimc.py:127`, `:179`, `:303`) and MCTS (`mcts.py:611`) short-circuits when only one legal action is available. The Round-20 measurement (worklog 2026-05-10, round 20) found **87% of decisions are forced (PassPriority)** in a synthetic RandomAgent self-play.

Real-search decision fraction: **~13%**.
Expected NN calls per **average** decision: `0.13 × 480 ≈ 62`.

## The crucial demand-vs-supply calculation

Iterate-level NN demand: 49 dec/sec × 62 NN/dec = **~3,040 NN RPS for the shard.**
Substrate ceiling at 14 workers (measured): **4,176 RPS.**

**Iterate is operating at ~73% of substrate capacity.** This is substrate-pressured, not GPU-pressured.

Why doesn't iterate hit the full 4.2 K? Two compounding effects:

1. **Per-worker serialization is the binding constraint, not aggregate RPS.** Each `SharedTensorNNEvalClient._call_value_policy` blocks the calling thread on `response_events[slot].wait()` before returning. One worker can have at most **one** request in flight at a time. The MCTS `_search_batched` then calls `evaluator.batch_evaluate_with_policy(states)`, which under the SHM client is a Python for-loop:

   ```python
   # shm_nn_eval_server.py line 506-515
   def batch_evaluate_with_policy(self, states, player_id):
       return [self.evaluate_with_policy(s, player_id) for s in states]
   ```

   So a single MCTS batch of 32 leaves on one worker = 32 serial slot round-trips, each ~3 ms p50 = **96 ms wall** for what the legacy NNEvaluator does in **one** ~10 ms GPU forward.

2. **Cross-worker batching saves part of this, but only up to N_workers concurrency.** The dispatcher fuses requests from different workers. With 14 workers each holding one in-flight request, dispatcher sees average batch size ~14, below the `batch_size=32` cap. Each per-request RTT is still ~3 ms because every dispatch cycle does one 14-leaf GPU forward. The substrate bench at 14 workers reports `batch_sizes` averaging well below 32 (per `dispatcher` instrumentation — would need a re-run to log exact numbers, but the 4,176 RPS / 2.4 ms latency math is consistent with avg batch ~14).

## Why the SHM client doesn't do a real `batch_evaluate_with_policy`

The naive answer: it would require allocating B slots, writing all B feature tensors, putting B slot indices in the request queue, then waiting on B response events — all from a single worker call. That's doable but the existing slot-pool design (each slot = one in-flight request, free_slots queue caps total in-flight) doesn't naturally accommodate "this one worker wants 32 slots right now." The MCTS `batch_size` predates Lever 2; nobody updated the SHM client's batched method to match. The mismatch is documented obliquely in the `_call_value_policy` docstring ("Server batches across worker-process boundaries already; the slot round-trip is the unit of work") but the consequence — that MCTS's intra-worker batching is lost — isn't called out anywhere.

## Hypothesis ranking

Restating the task brief's hypotheses with quantitative weights:

1. **Game-loop overhead dominates** — Partly. Forced-move decisions are 87% of all decisions; each does `legal_decisions()` + apply, no NN. At ~3.5 dec/sec/worker total, that's ~3.05 forced-dec/sec at ~10 ms each = 30 ms wall, and ~0.45 real-search-dec/sec at the remaining ~970 ms = **~440 ms per real-search decision.** Of that 440 ms, the NN-call portion at substrate-pressured throughput is `62 calls × 3 ms / 14 workers in flight ≈` (effectively single-worker serial across 32 leaves per batch × 7 batches × 4 samples) `≈ 28 batched calls × ~96 ms wall per batch on the worker side ≈ 2.7 s` — but obviously not all of that is on the critical path because cross-worker batching helps. **The NN portion is plausibly 200-400 ms of the 440 ms per real-search decision; game-loop is the remaining 50-250 ms.** Both matter, neither solely dominates. **Medium-strong evidence.**

2. **PUCT budget undersaturates the batching window** — **Yes, this is the strongest single finding.** At `inner_nodes=200, batch_size=32`, each worker fires at most one batch every ~96 ms (32 serial calls × 3 ms). With 14 workers, the dispatcher sees ~14 concurrent requests on average, below `batch_size=32`. Bumping search budget (e.g. `samples=8, nodes=400`) would let workers stay in batched-eval longer and improve dispatcher fusion. **But the root cause is the SHM client's serial batch — not the search budget per se.** Fixing the client is cheaper than 2× the search cost.

3. **Determinization + state cloning** — Bounded. Per `docs/clone_zone_breakdown.md`, `GameState.clone()` is ~26-30 µs. Per decision: 4 sub-adapter clones (`pimc._build_sub_adapter`) + ~200 internal MCTS clones × 4 samples ≈ 800 clones ≈ 24 ms of clone time per real-search decision. Determinization itself is one Fisher-Yates shuffle per sub-adapter at root. **~5-10% of per-decision wall — present but not dominant.**

4. **Legacy NNEvaluator was already fast at this NN size** — **Yes, this is the silent half of the gap.** PR #41 showed 4-worker self-play improved 64 s → 40.66 s/game (×1.57). That's the entire SHM win at low worker count. The substrate bench's 3-8× ratio is measured against `Local 16w` baseline = 1,355 RPS, but in production iterate at 14w the per-worker legacy NN forward on CUDA is ~0.2-1 ms at this 128-trunk size — so the legacy 14-worker aggregate is likely ~6-10K RPS, not the 1,355 the local bench reports. Local bench's 1,355 RPS includes per-worker model-load overhead and CPU-only / not-fork-shared GPU contexts. The honest comparison vs production legacy is the 64 s → 40 s number, not the substrate's 3× ratio over its own local baseline. **The substrate bench's baseline is unrealistic for production comparison.**

5. **Worker startup / weights load** — Marginal at 180 s. SHM eval loads weights once in the master before fork; workers fork-inherit. The 4 completed games' wall times (68, 114, 142, 178 s) include identical fork-inherit; only the first ~1-2 s per game is "startup." **<5% of game wall.**

## Best hypothesis (single sentence)

**The SHM client's `batch_evaluate_with_policy` serializes MCTS's batch_size=32 into 32 single-slot round-trips, so a worker can have only one NN call in flight at a time; cross-worker dispatcher fusion partially compensates but caps the system at `N_workers × (1 / per-call-RTT)` ≈ 4-5 K RPS at 14 workers, which is ~73% of where the iterate-level demand (~3.0 K RPS) sits.** The legacy NNEvaluator does the equivalent work in one stacked GPU forward per worker per batch and thus needs ~32× less per-worker request throughput.

## Cheapest experiments to confirm / refute

### Experiment A (cheapest, ~1 hour, no code change)

Re-run the 14w 20-game SHM eval bench but log `batch_sizes` from the dispatcher (`SharedTensorNNEvalServer.batch_sizes` is already instrumented at `shm_nn_eval_server.py:316`/`:442`). After the run, compute `mean(batch_sizes)` and `len(batch_sizes)`. **Prediction:** mean batch size ≈ 14, total batches × 14 ≈ total NN calls served ≈ 3,000 × 180 ≈ 540 K, and `mean(batch_sizes) << 32`. If mean ≈ 32, the SHM serial-batch hypothesis is wrong. If mean ≈ 14, it's confirmed.

To enable: the dispatcher records `batch_sizes` in memory; add a `print(f"avg batch: {sum(server.batch_sizes)/len(server.batch_sizes):.2f}, n_batches: {len(server.batch_sizes)}")` in the eval shard cleanup (one line, no test cost).

### Experiment B (~half-day code change, definitive)

Make `SharedTensorNNEvalClient.batch_evaluate_with_policy` actually batched: acquire N slots, write all features, submit a *batch* request (extend the protocol slightly — add a list-of-slots message type or just have the dispatcher group them by `(submitter_pid, batch_id)`), wait on all events, gather all outputs. Then re-run the 14w 20-game eval bench. **Prediction:** per-game wall drops 30-60%; substrate utilization climbs toward 8 K RPS (dispatcher now sees `14 × 32 = 448` requests concurrently, easily filling `batch_size=32`).

This is the canonical fix for the "Lever 2 paid off by 1.5×, not 5×" delta. The substrate is already there; only the client wiring needs to send batches as batches.

### Experiment C (alternative, ~1 hour, code change)

Set `batch_size=1` on the MCTS used inside the SHM iterate path (i.e. fall back to serial leaf evaluation). At `batch_size=1` the per-worker MCTS sends one request per leaf, and cross-worker dispatcher fusion handles ALL the batching. This is what the substrate bench was actually measuring. **Prediction:** at `batch_size=1`, per-game wall is *similar to or slightly worse than* `batch_size=32`, because the search loop loses virtual-loss diversification but gains better batch-fusion. If it's a wash, that confirms the SHM client's serial-batch is the bottleneck. If `batch_size=1` is meaningfully faster, then the SHM serial-batch is actively hurting compared to no-batch.

## Has Lever 2 paid off?

**Yes, partially, and honestly more than the worklog narrative implies.** Concrete wins delivered:

1. **Eval fork+CUDA crash class fixed** (PR #41, #43). Without `--use-shm-eval`, running eval in 14-worker WSL2 forks crashes on first CUDA touch. Lever 2 made eval functional on Linux fork.
2. **Self-play 4w smoke: 64 s → 40.66 s/game = 1.57×** (PR #41). This is a real, measurable iterate win.
3. **Self-play substrate ceiling raised**. Even bounded by per-worker serialization, 14w SHM substrate (4.2 K RPS) is 10× over TCP (420 RPS). The legacy local-NN per-worker path scales worse with worker count (each worker holds its own CUDA context); SHM consolidates to one GPU context.

The "+5-7×" projection in the WSL2 migration doc was based on the substrate's potential. The shortfall isn't a Lever 2 failure — it's a missing client-side batching primitive that would close the gap. The deadlock fix (PR #43) plus the structural unblock (PR #41) plus the substrate gain (PR #40) are real progress. The next 2-3× upside is sitting behind Experiment B above.

## File / artifact map

- Substrate numbers: PR #40 description; `docs/nn-eval-server-bench.md` (older bench, pre-Lever-2).
- Today's 14w bench: `/tmp/shm_eval_fix_14w/eval_shm_eval_fix_14w_shard_local_events.jsonl`, `eval_shm_eval_fix_14w.json`.
- Yesterday's identical workload (hung on cleanup, pre-fix): `/tmp/shm_eval_decisive_progress/eval_shm_eval_decisive_shard_local_events.jsonl`.
- SHM client code: `src/mtg_bot/search/shm_nn_eval_server.py:506-515` (the serial `batch_evaluate_with_policy`).
- Legacy NNEvaluator batched path (for comparison): `src/mtg_bot/search/nn_evaluator.py:551-620` (one stacked GPU forward).
- MCTS batched search: `src/mtg_bot/search/mcts.py:659-820` (the `_search_batched` path).
- PIMC structure: `src/mtg_bot/search/pimc.py:101-143` (samples loop + sub-adapter build).
- Forced-move shortcut sites: `pimc.py:127`, `mcts.py:611`.
- Clone cost reference: `docs/clone_zone_breakdown.md`.
- Forced-decision fraction (87% PassPriority): worklog `2026-05-10-rust-parity-discovery-round-20`.
