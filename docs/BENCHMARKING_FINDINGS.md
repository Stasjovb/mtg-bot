# Benchmarking findings — single source of truth

This document memorializes **every** benchmarking result, with dates,
context, methodology, and the honest corrections made along the way.
It exists because the "GPU/SHM gives 3–10×" lore went in circles for a
full session: it was baked into `iterate.py` help text and dead flags,
sourced from a benchmark that could not even load the current network.
**If you are about to cite a performance multiplier, cite a row in
this doc with a date and a method — or measure it and add a row.**

Session span: **2026-05-16 → 2026-05-17.** Box = `desktop-j05412i`
("master", RTX 5090, Win11), the coordinator + shared dev box (other
high-velocity engine sessions run here concurrently). "Mac" =
`greggs-macbook-pro` (M4-class, Apple Silicon, **no usable CUDA** —
`auto_device()` returns CPU on Mac per
`project_mac_mps_slower_than_cpu`). Production self-play config used
throughout: **nodes=200, samples=4, weights v6 (`architecture:
structured`, `canonical_v2`)**, the real EoE 17lands deck pool.

---

## 0. Meta-lessons (read first)

- **"exit 0" ≠ success.** Multiple background tasks "completed exit 0"
  while every game crashed instantly. Always verify the *content*
  (completed/crashed counts, sample rows > 0), never the exit code.
- **A broken measurement tool yields confident, bogus numbers.** The
  "3–5×" came from `bench per-game-wall` timing 100 % crashed games.
- **Verify, don't assert.** Every root-cause flip in this doc came
  from pulling the real traceback, not reasoning from priors.
- **Ratio over absolutes on a shared box.** master is contended; only
  back-to-back same-window *ratios* (with a GPU/CPU sampler to detect
  skew) are trustworthy. Absolute games/hr drifts with box load.
- **The real signal for "is X worth it" is eval-gate strength across
  iterations**, not loss curves and not micro-benchmarks in isolation.
- **No unvalidated multipliers.** If it is not measured here, it is
  not a number.
- **Count the work, not the games.** sec/game conflates game length ×
  search budget × device regime; quote `ms/NN-eval` (depth-invariant,
  now instrumented — §2A) so a `--nodes` change can't silently move
  the number.

---

## 1. CPU economics — AWS spot vs local (2026-05-16)

**Method:** `~/.mtg_bot_aws/bench_stage.py` drove the real v2
distributed path (`POST /v2/stage/create` → `/v2/start_self_play` →
poll, per-game timing from the coordinator `queue.db`), production
depth, structured v6, ~realistic per-box `--n-workers`.

| host | type | games/hr | per-game mean | $/hr | **$/1000 games** | CPU% | notes |
|---|---|--:|--:|--:|--:|--:|---|
| Mac | local (owned) | 224.7 | 93.8 s | ~$0.01 elec | **~$0.04** | ~14% | 100 games, crashed=0; least-contended; not CPU-bound |
| master | local (owned) | 124.3 | ~390 s | ~$0.09 elec | **~$0.72** | ~19% | shared/contended → a *floor*, not true capability |
| c7i.4xlarge | AWS spot x86 | ~151.6 | 293 s | $0.265 | **~$1.75** | ~87% | 83-game partial (spot-reclaimed mid-run); CPU-bound |
| c7g.4xlarge | AWS spot ARM | 113.4 | 392 s | $0.193 | **~$1.70** | ~85% | clean; CPU-bound; ARM build path validated |
| ~~c7i.8xlarge~~ | AWS spot x86 | — | — | — | **INVALID** | — | 72/100 crashed @ `--n-workers=30` — see §6 |

**Conclusion:** AWS CPU spot ≈ **$1.70–1.75 / 1000 games**, x86 and
ARM converge (c7g cheapest $/vCPU-hr). Local owned HW ≈ electricity
only → AWS CPU spot is **~20–40× the per-game cost of local**. AWS
CPU spot is *not* economical to replace the local cluster; its only
justification is **elastic burst** at a known premium. Dedicated
right-sized 16-vCPU AWS boxes are CPU-bound; master/Mac are not
CPU-bound (low CPU% with pool full → NN-eval/serialization-gated,
not core-gated). The Mac (M4) is the fastest local node.

---

## 2. Depth / sample scaling (analysis, consistent with §1 data)

- Per-game wall ≈ **linear in `nodes`** (each MCTS sim ≈ one NN eval;
  possibly slightly sublinear from NN-eval caching). nodes 200→1600 ≈
  ~8×/game.
- **A training sample = one recorded decision.** `samples ≈ games ×
  decisions_per_game`; `nodes` does **not** create samples — search
  sims are internal label computation for ONE move's target.
- Therefore "1000 games @ depth 200" vs "500 games @ depth 400" =
  **same self-play compute** (1000·200 = 500·400) but the latter is
  **~half the samples, higher per-sample target quality** — *not*
  "same samples, higher quality." Fewer-deeper trades sample
  count/coverage for label quality at fixed compute.
- Hypothetical "1000 games @ nodes=1600 in 1 hour": ≈ $13–20 of AWS
  CPU spot *if it could run* — but blocked: CPU per-game (~40–52 min
  on c7g) barely fits a 1-hr deadline (long tail lost), and ~60–80
  instances ≈ ~1000+ vCPU ≫ the 32-vCPU spot quota. This is the
  regime GPU is for (§4) — but GPU quota is blocked (§5).

---

## 2A. Units & methodology — count NN-evals, not games (instrumented 2026-05-17)

**Problem.** "games/hr" and "sec/game" conflate three independent
axes, so two runs are never comparable unless all three match:

```
game_wall ≈ decisions × samples × inner_nodes × cost_per_node  +  non_search_overhead
            └ game len ┘ └──── search budget ────┘ └ regime ┘     └ mulligans/SBAs/real-move sim ┘
```

Changing `--nodes` moves the unit; that opacity is a primary reason
the "3–10×" lore (§3, §7) survived. **The fix: normalise by the work
actually done.** Two depth-invariant units, now instrumented
(`mtg_bot.search.eval_counters`, branch
**`feature/eval-node-counters`**, pushed for review — **not merged**):

- **search nodes** — one `Budget.consume_node()` tick; the unit of
  intended search work.
- **NN-evaluated states** — a state that actually went through the
  network. Terminal leaves (exact ±1/0) and per-search NN-eval cache
  hits short-circuit *before* the evaluator, so neither counts. This
  is exactly the work GPU/SHM accelerate, so **`ms / NN-eval` is the
  cross-device, cross-depth comparison unit** (and `ms / search-node`
  the intended-work view). Their ratio (`nn_eval_fraction`) is itself
  the cache/terminal-skip diagnostic.

**Premise 1 — linearity, VERIFIED from code (not assumed).** Each
tree node stores its own state (`mcts.py:97`); expanding a child is
exactly one `parent.state.clone()` + one `apply(decision)`
(`mcts.py:941-942`) — **not** an O(depth) root replay — and the
search consumes exactly one node per budget tick in both the serial
(`mcts.py:654-657`) and batched (`mcts.py:725`) paths. So wall-time
is **linear in `inner_nodes`/`--nodes`**. *Honest nuance:*
`state.clone()` is O(state size) and state grows over a game
(permanents, graveyards), so `cost_per_node` drifts **upward within a
game**. It is constant w.r.t. the depth knob at a fixed decision, but
you **cannot** reconstruct game-wall as `nodes × constant` — always
use the *measured* per-game `ms/NN-eval`. The unit is for
comparison, not analytic extrapolation.

**Premise 2 — chokepoints, VERIFIED + one discovered nuance.**
Counted at `Budget.consume_node()` (nodes; covers serial/batched
MCTS *and* ISMCTS, all honour the Budget contract) and at the
**public evaluator-method boundary** post terminal/cache split — in
both `NNEvaluator` (6 sites) and `SharedTensorNNEvalClient` (4 sites,
counted client-side: a game's eval count is the same regardless of
where the SHM server runs the matmul). Counting at the public
boundary, not at `self.model(...)`, makes it architecture-agnostic
(structured-vs-MLP route through `_structured_forward` differently)
with no double/under-count. **Discovered (test surfaced it,
mechanism confirmed at `mcts.py:990`):** `nn_eval_states` can
*slightly exceed* `nodes`. PUCT issues a standalone
`evaluate_with_policy` forward to populate a node's policy cache on
first expansion (`_stamp_prior`); the **root** node is created in
`choose()` and never leaf-evaluated, so its prior forward is real NN
work with **no** matching budget tick. This is why `skipped` clamps
at 0 rather than asserting the naive identity `nn_eval_states +
skipped == nodes` — the clamp is the *designed* handling of this
(and of belief/opponent-policy forwards), not a fudge.
`nn_eval_states` remains the correct `ms/NN-eval` denominator (it is
every real forward); `nodes` is the budget unit; their ratio is a
diagnostic, **not** an identity. Counter cost is a sub-100ns
unsynchronised int add per node (no lock — search is single-threaded
per process; pool workers are separate processes) — <0.1 % of a
per-node clone+apply+forward, i.e. it does not perturb the very
measurement it feeds.

**Surfaced in:** `mtg_bot bench per-game-wall` (new "Search-work
units" stdout block) and `~/.mtg_bot_aws/ab_device.py` (the
structured-correct retrofit harness — new `ms_per_nn_eval` /
`ms_per_node` / `states_per_call` per arm + a depth-invariant
`ms/NN-eval` cross-arm headline).

**Retrofit — MEASURED 2026-05-17.** Gate green
(`feature/eval-node-counters` @ `40719405`, 12981 passed / 95.62 %);
box post-gate (not pristine — other engine sessions; *ratios
within a back-to-back window are the trustworthy quantity, absolutes
drift*, §0/§9). v6 structured, nodes=200/samples=4, 14 workers, 16
games/arm, **all arms 16/16 completed, 0 crashed**.

Run A — `ab_device.py`, cpu vs cuda back-to-back:

| arm | mean s/game | **ms/NN-eval** | ms/node | evals/game | states/call | games/hr |
|---|--:|--:|--:|--:|--:|--:|
| cpu | 439.9 | **5.21** | 4.61 | 84 420 | 5.89 | 49.8 |
| cuda | 221.3 | **2.69** | 2.40 | 82 178 | 5.85 | 94.9 |

→ **cpu/cuda = 1.93× in `ms/NN-eval`**, vs 1.99× per-game / 1.91×
throughput. The three agree (evals/game differ only ~3 %, random),
which **validates the instrumentation and re-expresses §4's ≈2×
depth-invariantly** — same conclusion, now portable across `--nodes`.

Run B — `ab_shm.py`, per-process cuda vs SHM-cuda back-to-back,
phase-tagged `nvidia-smi`:

| arm | mean s/game (p50 / p90) | **ms/NN-eval** | evals/game | games/hr | GPU util mean/max |
|---|--:|--:|--:|--:|--:|
| cuda (per-proc) | 186.7 (193 / 263) | **2.54** | 73 578 | 188.4 | **68 % / 93 %** |
| SHM cuda | 232.6 (179 / 397) | **2.99** | 77 820 | 94.6 | **9 % / 21 %** |

SHM server telemetry: 76 135 batches, 1.245 M requests, **mean batch
16.35** (real coalescing). Cross-window check: cuda `ms/NN-eval`
2.69 (A) vs 2.54 (B) ≈ 6 % — the expected contended-box absolute
drift; the within-window ratios stand.

**The unit sharpened §5 (important).** §5's headline "SHM ≈ 2×
slower" is a **throughput** figure (`games/hr` 0.50×) and it
reproduces here — but the depth-invariant unit shows the true
**per-eval** penalty is only **`ms/NN-eval` 2.99 / 2.54 ≈ 1.18×
(~18 %), not 2×.** The 2× throughput gap is mostly **latency
variance / pool-stall** (SHM p90 397 s vs 263 s; GPU starved to 9 %
mean while the workers wait on slot/RPC round-trips), not per-eval
compute. §5's verdict (**do not wire SHM at this net scale**) is
unchanged and reconfirmed; what changes is the *magnitude of the
barrier a larger trunk must clear* — see below.

**Crossover projection — LABELED, one measured anchor + analytic
batch-amortization (NOT a measured curve).** Anchor: at v6
(emb 128 / 2 layers / hidden 256) SHM adds ≈ **+0.45 ms/eval**
(2.99 − 2.54) of round-trip/slot overhead on a ~2.5 ms amortized
per-eval-node cost, and the SHM server measured **mean batch ≈
16.3**. SHM's *served* forward amortizes ~16× across coalesced
requests while the per-process forward does not, so SHM overtakes
per-process roughly where the **in-process forward cost exceeds the
RPC overhead net of batch amortization** — order ~0.4–0.5 ms of
forward. v6's structured forward is far below that (microseconds —
why SHM loses by 18 % here). A roadmap **Step-1 larger structured
trunk plausibly crosses it**; an ~18 % per-eval penalty is *far*
easier for a heavier forward to overcome than the "2×" the
throughput headline implied — which is exactly why measuring in the
right unit matters. **This is a projection, not a result: re-run
this A/B at Step-1 net scale before acting on it** (no
unvalidated-multiplier rule, §0; no Step-1 weights exist yet — §10,
CLAUDE.md).

---

## 3. The discredited "3–5× GPU" claim (2026-05-16 claim → 2026-05-17 root-caused)

- A background agent's GPU-vs-CPU micro-bench (2026-05-16) reported
  "CPU can't finish a 200/4 game in 150 s; GPU ~93 s ⇒ ≥3–5×". It
  used `bench per-game-wall`.
- **2026-05-17 root cause (real traceback):** `bench per-game-wall`
  builds the legacy flat `_ValuePolicyMLP` config — it does **not**
  thread `architecture=` from metadata — so it **cannot load
  structured v5+ checkpoints at all**: every game crashes instantly
  in `load_state_dict` (`missing trunk.0.weight` / `unexpected
  cls_token…`). It was timing **100 % crashed games**. The "3–5×"
  was never a valid measurement. (It also had a separate stale
  `enable_mulligans=` kwarg `TypeError`.)
- Fix branch `feature/fix-per-game-wall-kwarg` (commit `562e4e48`,
  pushed for review, **not merged**): removes the stale kwarg, adds
  `--device`, and a prominent in-code `.. WARNING::` that the tool is
  still unfit for structured weights. A *full* fix (thread
  architecture/policy metadata into its `NNPimcConfig`) was
  deliberately not done.
- Equally important: the subsequent **over-correction toward "GPU is
  unused / ≈1×"** was *also* wrong. It conflated the GPU question
  with the worker-daemon path, which is CPU-by-design (§6).

---

## 4. Decisive GPU vs CPU A/B — VALIDATED (2026-05-17)

**Method:** `~/.mtg_bot_aws/ab_device.py` — mirrors the **production**
`worker_daemon_production_runner._build_nn_pimc_config` exactly (passes
`architecture=` from metadata → loads structured v6 correctly; the
thing `per_game_wall` got wrong), only overriding device. 1-game
structured-v6 smoke validated (completed=1, crashed=0) **before** the
A/B. nodes=200, samples=4, v6, **14 workers**, 16 games/arm,
back-to-back same box, `nvidia-smi` per-arm sampler.

| arm | mean s/game | p50 | p90 | games/hr | crashed | GPU util mean/max |
|---|--:|--:|--:|--:|--:|--:|
| CPU | 468 | 489 | 729 | 48.6 | 0 | 8% / 22% (idle, expected) |
| **CUDA** | 220 | 214 | 292 | 94.6 | 0 | **42% / 93%** (genuinely used) |

**Result: `device=cuda` ≈ 2.13× faster per game, ≈1.95× higher
throughput than `device=cpu`.** Real and validated (sampler confirms
the cuda arm used the 5090, cpu arm left it idle). **Not 3–5×; not
≈1×. ≈2×.** Caveat: contended box → the *ratio* is the trustworthy
quantity; absolutes drift. This is **per-process** eval (no SHM).

---

## 5. SHM (batched eval server) A/B — VALIDATED: NOT worth it (2026-05-17)

**Method:** known-good SHM seam only (`config.py build()` →
`SharedTensorNNEvalClient` via `maybe_get_worker_handle`,
`SharedTensorNNEvalServer().start()` + pool initializer) — **no
hand-rolled SHM**. 1-game structured smoke validated first. Same
depth/v6/14-workers/16-games, back-to-back same window.

| arm | mean s/game | games/hr | GPU util mean/median |
|---|--:|--:|--:|
| per-process `cuda` | 192 | **183** | **67% / 89%** (saturated) |
| **SHM** cuda | 238 | **92** | **13% / 13%** (nearly idle) |

**Result: SHM ≈ 0.5× the throughput of per-process cuda — i.e. ~2×
SLOWER, not faster.** Mechanism: v6's structured trunk is tiny
(emb_dim 128, 2 layers, hidden 256) → a batched forward is
microseconds; the SHM round-trip (slot acquire → shared-tensor write →
queue → dispatcher → event) costs more than the per-process in-worker
forward it replaces. Telemetry confirmed real batching (1.2 M
requests, mean batch 16.3) — it simply has nothing to amortize at
this net scale. **Verdict: do NOT wire SHM into the daemon at the
current network scale.** Caveat (preserved, important): specific to
today's tiny v6 trunk; the roadmap's Step-1 *larger* structured net
could flip the GPU-compute-vs-RPC balance — **re-run this A/B then**;
do not generalize to "SHM is always useless." **Update (§2A retrofit,
2026-05-17):** re-expressed in `ms/NN-eval`, the per-*eval* penalty
is only ~1.18× (~18 %), not 2× — the 2× here is a *throughput*
artifact (latency variance / GPU-starved pool-stall). Verdict
unchanged; the barrier a larger trunk must clear is smaller than the
throughput headline implied. See §2A.

---

## 6. Cluster crash root causes (diagnosis corrected — memorialized)

The crash diagnosis flipped; record the correction so it is not
re-litigated:

- **Mac/Win10 smoke crashes + Mac economics crashes (2026-05-16/17).**
  Earlier (wrong) diagnosis: "stale Rust `.pyd` build." **True cause:
  poisoned weights cache** — a stale `v6/metadata.json` (old MLP era,
  no `architecture`) paired with a structured `v6/weights.pt` →
  `NNEvaluator` builds the wrong model class → `load_state_dict`
  RuntimeError → 100 % instant crash. Fixed by purging the cache so
  the daemon re-fetched a coherent pair; the durable fix is branch
  **`feature/fix-weights-cache-coherency`** (merged): atomic coherent
  (metadata, weights) pair + loud `PoisonedWeightsCacheError`. The
  Mac was *also* under-provisioned (no Rust toolchain / no `maturin`)
  — real but orthogonal to the crash.
- **c7i.8xlarge 72/100 crash @ `--n-workers=30` (2026-05-16).** Cause:
  **TOCTOU torn-read of a cold `weights.pt`** — `is_file()` returns
  true the instant `open(wb)` truncates; many spawn subprocesses on a
  cold cache `torch.load` a 0-byte/partial file. Bimodal
  instant-crash-or-normal, depth-independent, high-`n-workers`-only,
  Windows-masked. Fixed: branch **`feature/fix-worker-pool-startup-
  race`** (merged): atomic temp→`os.replace` publish + per-version
  inter-process lock.
- **Worker-daemon self-play is CPU-by-design.**
  `_build_nn_pimc_config` hardcodes `device=None`. So the validated
  §4 ~2× is **unrealized in production** until opt-in GPU is wired —
  branch **`feature/worker-daemon-gpu-device`** (in progress as of
  2026-05-17; opt-in `--nn-device`, default cpu, per-worker resolve
  mirroring `run_shard_pull`, push-for-review not merge).

---

## 7. Structural debt / misleading lore uncovered (2026-05-17)

- `iterate.py` `--use-shm-self-play` / `--use-shm-eval` /
  `--use-shm-server` flags are **parsed but consumed by nothing**.
- `SelfPlayJobSpec.use_shm_server` / `EvalJobSpec.use_shm_server` are
  **dead fields**; `run_shard_local` + the SSH orchestrator were
  deleted in the v2 cutover.
- iterate help text advertises "PR #40: 3–10× NN throughput / PR #41:
  ~36% per-game" — **these do not reproduce** for production
  structured-v6 self-play; the inverse held (§5). This lore is a
  primary reason the SHM thread went in circles. **Recommended
  follow-up:** delete the dead flags/fields, correct/remove the
  help-text claims (honesty hygiene; not auto-done — flagged).
- `mtg_bot bench per-game-wall` broken on main pre-existing (§3).
- Known **pre-existing** test conditions, independent of all the
  above (confirmed identical on clean main): 7 Rust-`.pyd`-staleness
  failures (shared-venv compiled `.pyd` drifts vs source — do **not**
  rebuild the shared `.pyd` to "fix" it); `tests/training/
  test_self_play.py::test_run_match_parallel_alternate_seats_
  neutralizes_p0_bias` is a seed-flake.

---

## 8. AWS operational findings (2026-05-16)

- New-account **verification hold** (`PendingVerification`) blocked
  all EC2 launches in-region; cleared on AWS's side in minutes.
- New-account **Standard-spot throttle** (`MaxSpotInstanceCount
  Exceeded`) despite a nominal 32-vCPU quota; cleared after
  verification. On-demand worked as the interim unblock for the
  canary.
- **us-east-1f is spot-capacity-starved for the c7 family** — it
  reclaimed the c7i.4xlarge mid-bench and blocked c7i.8xlarge. Use
  us-east-1a/b/c/d; diversify AZs / mixed-type fleet.
- **GPU G/VT quota = 0** for *both* spot (L-3819A6DF) and on-demand
  (L-DB2E81BA). Increase requests → `CASE_OPENED` (AWS Support
  human review; effectively a soft denial on a 1-day-old account; a
  large 96-vCPU ask). Small re-request **deferred per user**. GPU
  benching (g5/g6.12xlarge) is therefore not runnable today.
- Spot interruption is real (c7i.4xlarge reclaimed mid-run). Handled
  by branch **`feature/spot-interruption`** (merged): `--spot-watch`
  IMDS poller → graceful drain on the 2-min notice.
- Workers are credential-free by design: code via coordinator
  `/repo.bundle` + `/v2/self_update`; weights via `/v2/weights`;
  deck pool via S3 presigned URL. Budget alarm: $75/mo.

---

## 9. Reproduce / tooling

Ops scratch harnesses (NOT product code; in `~/.mtg_bot_aws/`):
`bench_stage.py` (distributed-stage economics), `ab_device.py`
(per-process cpu-vs-cuda via the production structured-correct config
builder; **now also emits `ms/NN-eval` / `ms/node` / `states/call`
per arm — §2A**), `ab_run_units.sh` (the §2A retrofit runner; points
at the instrumented `feature/eval-node-counters` worktree), `ab_shm.py`
(SHM vs per-process, known-good seam), `bench_sampler.py` /
`gpu_sampler_shm.py` (heartbeat / `nvidia-smi`).

Methodology requirements (learned the hard way):
- Construct the eval config via `_build_nn_pimc_config` (reads
  `architecture` from metadata) — never the legacy
  weights_path+hidden_sizes-only path (loads `_ValuePolicyMLP`,
  cannot load structured v5+).
- Windows path trap: pass `C:/...` absolute paths, **not** Git-bash
  `/c/...` (Windows Python mangles `/c/...` → `\c\...` →
  `FileNotFoundError`).
- Validate every harness with a 1-game structured smoke (completed≥1,
  crashed=0) before trusting any A/B.
- On the shared box, run arms back-to-back in one window and report
  the **ratio** + a GPU/CPU sampler; absolutes are noise.
- Per-game evaluator build at production depth (~hundreds of s/game)
  makes per-game CUDA-init overhead ~noise (~1–5 %); fine to ignore.

---

## 10. Open items / next benchmarks

- `feature/worker-daemon-gpu-device` (opt-in `--nn-device`) — the
  lever that actually captures the validated §4 ~2×. Awaiting review.
- **§2A retrofit** — ✅ DONE 2026-05-17 (`feature/eval-node-counters`
  @ `40719405`, gate green): cpu/cuda = 1.93× `ms/NN-eval` (validates
  §4); SHM per-eval penalty ~1.18× (sharpens §5). Remaining: re-run
  the SHM crossover A/B **at Step-1 larger-trunk net scale** to
  confirm/refute the labeled projection (blocked: no Step-1 weights
  exist yet).
- Re-run §4 / §5 **isolated** (quiesce other sessions) for a pristine
  absolute, and **at Step-1 larger-trunk net scale** (the §5 SHM
  verdict is net-scale-specific).
- GPU economics (g5/g6.12xlarge $/1000-games) — blocked on the GPU
  quota; re-request deferred per user.
- Optional: delete dead `--use-shm-*` flags/fields + fix iterate
  help-text multipliers (§7).
- Full fix of `bench per-game-wall` for structured weights (§3) — or
  retire it in favor of the `ab_device.py` methodology.


## 6. Rust engine vs Python engine — cross-engine throughput (2026-06-01)

First fair head-to-head now that the **non-DSK EoE pool is 100% byte-equal cross-engine** (every card driven byte-identically through both engines). Box = `desktop-j05412i` (Win11, py3.13, `.venv-py313`).

**Method.** Both engines implement the SAME 8-method `search.protocol.GameState` (`MtgGameStateAdapter` = Python `mtg_bot.game`, `RustGameStateAdapter` = the `mtg_bot_engine` pyd), built from one `cross_engine.build_matched_states(spec)` via `engine_adapter_factory`. Workload = full **random-playout games** (seeded policy: pick `legal_decisions()[rng.randrange(len)]` until terminal), 30 seeds, median per-game wall, 4-game warmup. Primitive `clone` = best-of-5 over 20k/2k iters with warmup.

**Results.**

| Workload | Rust | Python | Speedup |
|---|---|---|---|
| `clone()` primitive | 0.35 us | 11.9 us | **~34x** |
| full game — `slightly_bigger_deckspec` (~201 steps) | 1.25 ms | 2.33 ms | **1.9x** |
| full game — `multi_blocker_deckspec`, combat-heavy (~354 steps) | 2.44 ms | 6.79 ms | **2.8x** |

**Headline finding (the honest, load-bearing one).** Raw engine primitives are **10-40x** faster in Rust (clone ~34x — it's an `Arc` refcount bump vs a deep Python copy), but **full-game throughput is only ~1.9-2.8x**. Reason: BOTH search-protocol adapters reimplement the priority/search loop in **Python** — only the engine *primitive calls* (`apply_action`/`legal_decisions`/`resolve_top_of_stack`/`apply_sbas`) cross into Rust. So per-step cost is dominated by the **Python orchestration layer** (priority loop, decision codec, cross-engine bridge), not the engine. The Rust engine is NOT the full-game bottleneck under the current architecture. Combat-heavy decks show more (2.8x) because combat is more engine-work-per-step relative to orchestration. To realize more of the 34x, the orchestration/search loop itself must move to Rust (the direction the B3 `RustGameStateAdapter` was partially building — `rust_engine_adapter.py` docstring §3.1).

**Caveats (don't over-cite).** (1) SYNTHETIC deckspecs, not the real EoE 17lands pool (`data/17lands/eoe_decks.json.gz` is gitignored + absent locally) — real decks are larger/richer and could shift the ratio. (2) Random-playout policy, NOT NN/PIMC-guided. In **production self-play the NN-eval dominates wall-time** (see §2A/§4), so the engine's *share* of per-game cost is even smaller there — i.e. swapping to the Rust engine buys LESS than 1.9-2.8x end-to-end in NN-guided self-play, not more. (3) The search-protocol adapters are B3-S1 PARTIAL (not full byte-parity at the search layer — hence the slight 201-vs-203 step-count drift); the proven 100% parity is at the `trajectory.py` field-view level. (4) Single box, exploratory median/best-of-5 — not a pinned CI bench. A committed `scripts/bench_rust_vs_python.py` was not added; reproduce inline via `build_matched_states` + the two `engine_adapter_factory` builders.

### 6a. The decisive split — NN-eval dominates, so a Rust search-port is NOT worth it (2026-06-01)

Follow-up to §6's "the orchestration is the bottleneck" finding: **that was a RANDOM playout (zero NN-evals)**. Under the real production config it's the NN, not the engine, that dominates.

**Method.** Loaded the production **structured v5** net (`emb_dim 128 / n_layers 2 / hidden 256`, `canonical_v2`, via `NNEvaluator.from_metadata`), wrapped `evaluate_with_policy`/`batch_evaluate_with_policy` to accumulate NN wall-time, played 4 NN-guided games (synthetic decks, 40 searched-decisions each, single-legal-action moves taken without search per the production fast-path), PUCT `nodes=200` `batch_size=1` on CPU. 27,591 NN-evals total.

| Component | Wall | Share |
|---|---:|---:|
| **NN-eval** (state tokenize + transformer forward) | 98.2 s | **85.0%** |
| Engine + search orchestration (clone/apply/legal/tree/codec) | 17.3 s | **15.0%** |

Per-NN-eval ≈ **3.6 ms** (structured transformer, CPU, b=1).

**Verdict — do NOT port search to Rust for production self-play.** With NN-eval at 85%, a PERFECT Rust port of the *entire* engine+search+orchestration (the other 15%) caps end-to-end speedup at **~1.18x** — months of work (mcts/pimc/priority-loop + the NN-FFI boundary, §6 Tiers 1-2) for ~18%. The §6 random-playout 1.9-2.8x was on the non-NN portion, which is a SMALL slice of real per-game wall. **The entire leverage is the NN path**: GPU (§4: validated ~2x/eval — would shift NN to ~73%, raising the search-port ceiling only to ~1.36x, still not worth it), batched-PUCT (`batch_size>1`), a smaller/faster net, or fewer nodes. Caveats: CPU (the worker-daemon default per CLAUDE.md), synthetic decks, b=1, single box.

### 6b. Sizing the NN levers — batched-PUCT wins, GPU does NOT (2026-06-01, RTX 5090)

Sizing the two §6a levers concretely. Structured v5, `nodes=200`, single box (RTX 5090 + Win11 CPU).

**Per-eval microbench** (`batch_evaluate_with_policy`, us/eval = call/batch):

| batch | CPU us | CUDA us |
|---:|---:|---:|
| 1 | 2173 | **5246** (slower — kernel-launch overhead on a tiny net) |
| 8 | 888 | 803 |
| 32 | 625 | 261 |
| 64 | 579 | **169** |

CUDA amortizes 20x (b1->b32) vs CPU 3.5x; at a TRUE batch of 64, CUDA is ~13x faster per eval than the CPU b=1 baseline.

**End-to-end self-play (one game, the number that matters):**

| config | game | NN% | vs cpu-b1 |
|---|---:|---:|---:|
| cpu b=1 (baseline) | 30.5 s | 86% | 1.00x |
| **cpu b=32** | **12.4 s** | 68% | **2.45x** |
| cuda b=1 | 47.9 s | 91% | **0.64x (SLOWER)** |
| cuda b=32 | 12.5 s | 69% | 2.43x (only TIES cpu b=32) |

**The load-bearing finding: GPU does not help this net/search; batched-PUCT does.** GPU b=1 is a net LOSS (kernel overhead). GPU b=32 only ties CPU b=32 — because PUCT at `nodes=200` can't produce a batch of 32 independent leaves per forward (effective batch ~4-8, exactly where CUDA == CPU in the microbench). The GPU's 13x per-eval edge requires batches the tree can't supply. Matches the §5 SHM-server finding (cross-worker batching was 2x SLOWER at this net scale).

**Recommendation.** (1) **Ship batched-PUCT (`batch_size~32`): free ~2.45x, CPU-only, a config change.** (2) **Do NOT use GPU** at this net/search scale (worker-daemon CPU-by-default is correct). (3) After batching, NN is still ~68%, so the Rust engine+search-port ceiling rises only to ~1.47x — still not worth months. (4) GPU becomes worth revisiting ONLY with a search that yields LARGE batches (root/leaf-parallel across many concurrent games) — the unexplored lever; the prior cross-worker SHM attempt (§5) failed. Caveats: 1 game/config, synthetic decks, single box.

**CORRECTION (verified 2026-06-01, same session): batched-PUCT b=32 is ALREADY the production default — nothing to "ship".** `NNPimcConfig.batch_size` defaults to 32, `NNPimcConfig.build()` threads it (+`puct=True`) into `MCTS`, and every NN site sets it explicitly: `cli/iterate.py` self-play (`:567`) + both eval seats (`:1019`/`:1032`), `cli/capture.py` (`:85`), `cli/bench_kinds/per_game_wall.py` (`:89`), `worker_daemon_production_runner.py` (`:169`). The only `batch_size=1` is the heuristic eval seat (no NN forward to batch — correct). Landed with `feature/batched-puct` + the Phase-2c production runner. **So the `cuda/cpu b=32` rows above ARE current production; the `b=1` baseline is counterfactual.** Implication: production already realizes the ~2.45x; the live NN share is ~68% (the b=32 row), so the Rust engine+search-port ceiling in *actual* production is ~1.47x (not the 1.18x computed from the counterfactual b=1). b=32 is also near the CPU plateau (b=64 is only 579 vs 625 us/eval), so bumping it buys ~nothing. Net: no code change available here — the one free lever was already pulled; remaining throughput requires the large-batch search re-architecture (§6b item 4).

## 7. `effective_power` / layered-read hot path — closure removal (2026-09-23)

**Method.** Synthetic 12-permanent battlefield (3 of them carrying a
layer-6 `ContinuousModifier` anthem), 30,000 `effective_power(state,
target)` calls, `.venv-py313` (CPython 3.13.14) on desktop-j05412i
while the 20-worker `iterate_s2` self-play run was live — so both rows
are same-box, same-load.

| build | us / `effective_power` call |
|---|---:|
| before (generator expressions in `_compute_effective_pt` / `_static_bonuses` / `_source_layer6_wiped`) | 11.3 – 12.2 |
| after (explicit loops, no cell variables) | **6.1** |

**Why it got faster.** The dominant cost was the two layer-7e
`sorted((ce for ce in state.continuous_effects if ...), key=...)`
walks in `_compute_effective_pt`: each call built a generator frame,
materialized a list and sorted it — then discarded the order and used
only the element COUNT (each `switch_pt` entry contributes one swap, so
only the parity matters). Counting with an explicit loop removes the
generator frame, the list and the sort. `_static_bonuses` and
`_source_layer6_wiped` lost their genexps too.

**The change was made for correctness, not speed** — see the
"closure-free hot path" note on `mtg_bot.game._static_bonuses`. A genexp
that reads an enclosing local turns that local into a CELL variable
sharing the frame's `localsplus` array with the fast locals, and two
production self-play crashes (a `cell` object arriving as the `source`
loop variable; a `ContinuousModifier` arriving in place of a
`static_abilities` tuple) point at exactly that array under CPython
3.13's specializing interpreter. The ~2x is a side effect.

**Caveat.** Micro-benchmark on a synthetic board. `effective_power` is
~850k calls per self-play game per the 2026-05-02 profile, but the
end-to-end share was NOT re-measured — do not quote a game-level
speed-up from this row.
