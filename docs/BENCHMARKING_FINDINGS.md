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
do not generalize to "SHM is always useless."

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
builder), `ab_shm.py` (SHM vs per-process, known-good seam),
`bench_sampler.py` / `gpu_sampler_shm.py` (heartbeat / `nvidia-smi`).

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
- Re-run §4 / §5 **isolated** (quiesce other sessions) for a pristine
  absolute, and **at Step-1 larger-trunk net scale** (the §5 SHM
  verdict is net-scale-specific).
- GPU economics (g5/g6.12xlarge $/1000-games) — blocked on the GPU
  quota; re-request deferred per user.
- Optional: delete dead `--use-shm-*` flags/fields + fix iterate
  help-text multipliers (§7).
- Full fix of `bench per-game-wall` for structured weights (§3) — or
  retire it in favor of the `ab_device.py` methodology.
