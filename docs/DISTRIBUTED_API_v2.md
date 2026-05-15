# Distributed Coordination API — v2 (REST)

Replaces the SSH/scp/inline-Python sprawl in
`mtg_bot.training.distributed` with a single explicit REST contract
between a **coordinator** (one) and **workers** (N).

## Roles

Three roles, each with a tightly-scoped responsibility:

- **Coordinator** — work queue + result sink + weights store, plus
  **worker liveness tracker**. Reads the worker list from
  `shards_config.json` at startup and polls each worker's
  `/v2/heartbeat` every 10s, maintaining per-worker
  ALIVE/STALE/DEAD state and the latest health snapshot (CPU/mem/
  active-game count). One per cluster. Today this is the same
  process as `mtg_bot serve` (port 5099 on the master). Workers do
  not "register" — coordinator and orchestrator both read the same
  `shards_config.json`, so worker presence is a deploy-time config
  fact, not a runtime registration handshake.
- **Worker** — persistent daemon on each machine
  (master + Mac + Win10 + future AWS instances). Single-job-at-a-time
  state machine. Pulls work from the coordinator's queue while a
  stage is active. Self-reports rich health metrics via
  `/v2/heartbeat`.
- **Orchestrator** — the entity that initiates stages (today, the
  `mtg_bot iterate` CLI). Reads `shards_config.json` (same file as
  coordinator), POSTs `start_self_play` / `start_eval` to each
  worker, and submits the corresponding work batch to the
  coordinator's queue. NOT a long-lived service — runs as a
  one-shot CLI per iter.

A worker can crash and restart without the coordinator caring beyond
a brief STALE→DEAD→ALIVE state transition; the coordinator can
restart without workers caring (other than retrying the next
`/claim` after the brief blip). The shared `shards_config.json` is
the single source of truth for "which workers exist" — no
registration RPC.

Each network listener uses the tailnet trust model — any IP in the
tailnet can hit any endpoint, no per-request auth tokens.

## Coordinator endpoints

Base URL: `http://<coordinator-host>:5099`

### `POST /v2/claim`

Worker asks "give me a game to play."

```json
// Request
{
  "worker_id": "macbook-pro",
  "stage_id": "iter_008_self_play_v5"
}

// Response 200
{
  "claim_id": "iter_008_self_play_v5:game_0042",
  "game_idx": 42,
  "deck_indices": [1247, 3891],
  "seed": 8000042,
  "kind": "self_play",
  "weights": { "p0": "v5", "p1": "v5" }
}

// Response 204 (queue empty for that stage)
```

`claim_id` is the idempotency key for `report_result`. Coordinator
holds an in-flight set per worker; if a worker calls `/claim` a
second time without reporting the prior `claim_id`, the prior
in-flight claim is re-queued (worker crashed or restarted).

### `POST /v2/report_result`

Worker submits a finished game. **Note:** if the result includes an
`.npz` payload (self-play samples), the npz is streamed as multipart
in the same request — no separate file-transfer endpoint.

```json
// Request (multipart form)
//   field "meta" (application/json):
{
  "claim_id": "iter_008_self_play_v5:game_0042",
  "outcome": "completed",  // "completed" | "timed_out" | "crashed"
  "winner": 0,              // 0/1, or null on non-completed
  "n_samples": 1142,
  "duration_s": 31.4,
  "shard_label": "greggs-macbook-pro"
}
//   field "npz" (application/octet-stream): the chunk file

// Response 200
{ "accepted": true }
```

Eval results have the same shape minus the npz field. Replays (when
captured) are streamed under the same multipart payload, field
`replay` (`.json.gz`).

### `GET /v2/weights/<version>`

Worker fetches the canonical weights file. Coordinator caches the
file on disk; response is `application/octet-stream`. Workers cache
locally by version label — re-fetch only on cache miss.

### `GET /v2/weights/<version>/metadata`

Companion endpoint — returns the version's `metadata.json` (the
sidecar `NNPimcConfig.build` reads for structured-trunk hparams).

### `GET /v2/heartbeat`

Liveness only. Returns `{"status": "ok", "queue_depths": {...}}`.

## Worker endpoints

Base URL: `http://<worker-host>:5198` (new port for the worker daemon)

### `POST /v2/start_self_play`

Coordinator dispatches a stage. Worker fetches weights via
`/v2/weights/<version>` (cache-aware), spins up its `NNEvaluator` +
SHM server, and starts pulling from `/v2/claim` in the background.

```json
// Request
{
  "stage_id": "iter_008_self_play_v5",
  "weights_version": "v5",
  "nodes": 400,
  "samples": 4,
  "per_game_timeout_sec": 600.0,
  "n_workers": 8,
  "capture_every": 20,
  "coordinator_url": "http://desktop-j05412i:5099"
}

// Response 202 (accepted; running in background)
{ "stage_id": "...", "started_at": "2026-05-15T..." }

// Response 409 if worker is not IDLE (already running a stage)
{ "error": "worker_busy", "current_state": "SELF_PLAY_RUNNING" }
```

### `POST /v2/start_eval`

Same shape as `/start_self_play` but with two weight versions:

```json
{
  "stage_id": "eval_v_N_vs_v_M_500g",
  "new_version": "v10",
  "old_version": "v5",
  "nodes": 400,
  "samples": 4,
  ...
}
```

### `POST /v2/stop`

Coordinator says "stop the current stage gracefully." Worker drains
in-flight games (lets workers finish their current game), reports
results normally, then transitions to IDLE. Returns 200 with the
worker's state at the time of receipt.

### `GET /v2/heartbeat`

Returns the worker's state, stage progress, and rich machine
metrics. Coordinator polls every 10s for liveness; the UI also
reads it for the per-machine sub-card display.

```json
{
  "state": "SELF_PLAY_RUNNING",
  "current_stage_id": "iter_008_self_play_v5",
  "games_done": 142,
  "games_claimed_in_flight": 7,
  "last_progress_at": "2026-05-15T18:42:13Z",
  "error": null,
  "uptime_s": 31415,
  "host": {
    "pool_size": 8,
    "active_workers": 7,
    "cpu_percent": 78.4,
    "memory_percent": 62.1,
    "memory_used_gb": 19.8,
    "memory_total_gb": 32.0,
    "load_avg_1m": 6.8,
    "gpu_percent": 94.0,
    "gpu_memory_percent": 71.0
  }
}
```

`state` enum: `IDLE | SELF_PLAY_STARTING | SELF_PLAY_RUNNING |
EVAL_STARTING | EVAL_RUNNING | STOPPING | ERROR`.

`error` is non-null only in `ERROR` state — carries the last fatal
exception's repr for surfacing in the training UI.

`host` field semantics:
- `pool_size` — configured `n_workers` for the daemon's
  multiprocessing pool.
- `active_workers` — pool members currently executing a game (0
  when IDLE).
- `cpu_percent` — system-wide CPU utilization (via `psutil`), 1s
  sample window. NOT per-process; the whole machine.
- `memory_percent` / `memory_used_gb` / `memory_total_gb` —
  system-wide memory pressure.
- `load_avg_1m` — 1-minute load average on POSIX; on Windows
  this is the rolling 60s `cpu_percent` average (closest
  cross-platform analog).
- `gpu_percent` / `gpu_memory_percent` — present only on hosts
  with a GPU; resolved via `pynvml` (Windows/Linux NVIDIA) or
  `Metal Performance Shaders` Activity Monitor parsing (macOS).
  Absent fields are omitted on CPU-only hosts.

Workers compute the snapshot inline on each `/v2/heartbeat`. Cost
should be sub-millisecond — `psutil.cpu_percent(interval=None)`
samples since the last call, no blocking read.

## State machines

### Worker state machine

```
       start_self_play         (claim returns 204 OR stop)
IDLE ─────────────────► STARTING ──► RUNNING ───────────────────► STOPPING
  ▲                                     │                              │
  │                                     │ (worker pool exception)      │
  │                                     ▼                              │
  └─────── (clear) ──────  ERROR ◄──────                                │
                                                                       │
  ◄────────────────────────────── (all in-flight drained) ──────────────┘
```

Identical shape for the `EVAL_*` states.

### Coordinator's view of a worker

Coordinator polls each worker's `/v2/heartbeat` every 10s and
maintains derived liveness state per `worker_url`:

- `ALIVE` — heartbeat received in last 30s
- `STALE` — no heartbeat in 30-90s; in-flight claims still held;
  surfaced in the UI as a yellow indicator
- `DEAD` — no heartbeat in >90s; coordinator immediately re-queues
  all in-flight claims held by this worker (don't wait for the per-
  claim TTL) and surfaces a red indicator in the UI

When a DEAD worker's heartbeat returns (process restart), it
transitions back through STALE → ALIVE and resumes claiming. Its
re-queued prior claims have been redelivered to other workers; if
those eventually complete and the resurrected worker also reports
its old claim, the old claim's `/report_result` is 409'd by the
coordinator (the claim was reassigned).

The most recent heartbeat payload is cached per worker on the
coordinator and rendered by the UI's per-machine sub-cards (the
`machines[]` array the front-end consumes today).

### Abandonment detection: heartbeat AND claim TTL

Two layered mechanisms detect abandoned work:

1. **Heartbeat-driven** (primary, fast): coordinator notices a
   worker is DEAD within ~90s and re-queues its in-flight claims
   immediately. Handles the common case of process crash / machine
   reboot / network partition.
2. **Claim TTL** (defense-in-depth, slow): every `/claim` carries
   an expiration deadline (default: 2× `per_game_timeout_sec`, so
   1200s for the current 600s/game cap). Even if heartbeat-driven
   reclamation misses for some reason (coordinator restarted mid-
   stage, network split kept worker alive-but-isolated, etc.), the
   claim TTL guarantees eventual reclamation.

If a zombie worker's stale claim eventually completes and is
reported after either mechanism re-queued it, the
`/report_result` returns `409 Conflict`. Idempotency-on-success is
keyed by `claim_id`: a second on-time `/report_result` for an
already-reported claim is a silent 200 (network retry).

## File-transfer model

| File | Direction | Endpoint | Notes |
|---|---|---|---|
| weights.pt | coord → worker | `GET /v2/weights/<v>` | worker caches by version |
| metadata.json | coord → worker | `GET /v2/weights/<v>/metadata` | same |
| npz samples | worker → coord | multipart in `/report_result` | per-game |
| replay .json.gz | worker → coord | multipart in `/report_result` | per-game when captured |
| git bundle | coord → worker | `GET /repo.bundle` | unchanged (existing endpoint) |

No separate file-pull endpoints on workers — all worker→coord file
traffic rides in the per-game `/report_result` POST. Avoids the
"coordinator polls worker for finished files" loop the SSH path uses.

## What replaces what

| Today | v2 REST |
|---|---|
| Master SSH-launches `mtg_bot shard` on Mac/Win10 | Orchestrator POSTs `/start_self_play` to worker daemon |
| Master SCP's `weights.pt` to remote `trained_weights/<v>/` | Worker `GET /v2/weights/<v>` (cached) |
| Master SCP's `metadata.json` alongside | Worker `GET /v2/weights/<v>/metadata` |
| Master SCP's npz / replay back from remote | Worker streams in `/report_result` multipart |
| Inline-Python orphan-sweep over SSH | Orchestrator POSTs `/stop` to the worker (or claim TTL expires) |
| Coordinator polls remote shard heartbeats | Coordinator polls `/v2/heartbeat` every 10s; ALIVE/STALE/DEAD state + machine health (CPU/mem/active-games) drives UI sub-cards and early re-queue on death |
| 90/360-min SSH wall-cap kills mid-stage | Long-lived daemon; no SSH session, no wall-cap |
| Per-iter SSH spawn / teardown | Worker daemon is persistent (systemd / launchd / Task Scheduler) |

## Resolved design decisions

| Question | Resolution |
|---|---|
| Auth model | **Tailscale-allowlist only.** Bind listeners to the tailnet IP. No tokens, no app-layer TLS. Trust model matches today's SSH-over-Tailscale. |
| Worker daemon supervision | **Native services from day one.** Phase 2 ships with `systemd` unit (Linux), `launchd` plist (Mac), Task Scheduler entry (Windows). Bootstrap doc lives in `docs/SETUP_DISTRIBUTED.md`. |
| Worker discovery | **Static `shards_config.json` is the single source of truth.** Coordinator AND orchestrator both read it — no `/workers/register` RPC. Coordinator polls each `worker_url`'s `/v2/heartbeat` every 10s for liveness + machine health (CPU/mem/active-games), maintains ALIVE/STALE/DEAD per worker, surfaces it in the UI's per-machine sub-cards. |
| Idempotency | `/report_result` keyed by `claim_id`. On-time duplicate = silent 200. Late duplicate (after claim TTL expired) = `409 Conflict`. |
| Backward compat | **Hard cut after migration.** SSH path stays runnable until local + Mac + Win10 are all on REST. Then `_push_weights_to_remote` / `_pull_remote_replays` / SSH-launch / orphan-sweep-via-SSH get deleted, not deprecated. |

## Phasing (from scoping discussion)

1. **Define + freeze this contract** — this doc, iterate on review.
2. **Build the worker daemon** (`mtg_bot.worker_daemon` Flask app) —
   single-job state machine, the `start_*` / `stop` / `heartbeat`
   endpoints. Existing `cli/shard.py` body becomes the
   `start_self_play` handler.
3. **Extend the coordinator** — add `/v2/claim` + `/v2/report_result`
   + `/v2/weights/<v>[/metadata]` to the port-5099 server. Reuses
   the existing queue mechanism under the hood.
4. **Migrate one shard at a time** — local first, then Mac, then
   Win10. SSH path stays runnable in parallel until all three are
   green.
5. **(Optional) Move master itself to AWS** — once the cluster is
   pure REST, the master's `5090` is still genuinely useful for the
   SHM server, but the *coordinator* role can run anywhere.

## Out of scope (deliberately, for this contract)

- The training step itself. `mtg_bot train` stays in-process on the
  master for now.
- The eval-gate watcher. It reads the DB; doesn't need to move.
- The training UI. Reads the same `runs.db`; coordinator continues
  to write to it.
- Multi-coordinator / leader election. One coordinator per cluster.
- Game-level parallelism within a worker. The worker's
  multiprocessing pool stays internal — `n_workers` is a worker-side
  config, not a coordinator concern.
