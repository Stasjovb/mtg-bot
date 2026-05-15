# Distributed Coordination API — v2 (REST)

Replaces the SSH/scp/inline-Python sprawl in
`mtg_bot.training.distributed` with a single explicit REST contract
between a **coordinator** (one) and **workers** (N).

## Roles

- **Coordinator** — owns the work queue, the canonical weights/metadata
  store, and the per-job lifecycle state. One per cluster. Today this
  is the same process as `mtg_bot serve` (port 5099 on the master).
- **Worker** — runs as a persistent daemon on each machine
  (master + Mac + Win10 + future AWS instances). Single-job-at-a-time
  state machine. Pulls work from the coordinator's queue while a stage
  is active.

Each node is "a Flask server with a documented API." Same tailnet
trust model as today (any IP in the tailnet can hit any endpoint;
no per-request auth tokens — defer until we add untrusted nodes).

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

Returns the worker's state + a snapshot. Coordinator polls this
every 10s.

```json
{
  "state": "SELF_PLAY_RUNNING",
  "current_stage_id": "iter_008_self_play_v5",
  "games_done": 142,
  "games_claimed_in_flight": 7,
  "last_progress_at": "2026-05-15T18:42:13Z",
  "error": null,
  "uptime_s": 31415
}
```

`state` enum: `IDLE | SELF_PLAY_STARTING | SELF_PLAY_RUNNING |
EVAL_STARTING | EVAL_RUNNING | STOPPING | ERROR`.

`error` is non-null only in `ERROR` state — carries the last fatal
exception's repr for surfacing in the training UI.

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

Coordinator maintains per-worker state derived from heartbeats:

- `ALIVE` — heartbeat received in last 30s
- `STALE` — no heartbeat in 30-90s; still trust in-flight claims
- `DEAD` — no heartbeat in >90s; re-queue all in-flight claims for
  this worker, mark stage as "minus one worker"

When DEAD transitions back to ALIVE (e.g., worker restart), worker
re-registers and coordinator resumes assigning work.

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
| Master SSH-launches `mtg_bot shard` on Mac/Win10 | Coord posts `/start_self_play` to worker daemon |
| Master SCP's `weights.pt` to remote `trained_weights/<v>/` | Worker `GET /v2/weights/<v>` (cached) |
| Master SCP's `metadata.json` alongside | Worker `GET /v2/weights/<v>/metadata` |
| Master SCP's npz / replay back from remote | Worker streams in `/report_result` multipart |
| Inline-Python orphan-sweep over SSH | Coord checks worker heartbeat + state; can issue `/stop` |
| 90/360-min SSH wall-cap kills mid-stage | Heartbeats run forever; no wall-cap problem |
| Per-iter SSH spawn / teardown | Worker daemon is persistent (systemd / launchd / Win Task Scheduler) |

## Open design points

1. **Worker daemon process supervision.** Need a `systemd` unit on
   Linux, a `launchd` plist on Mac, and a Task Scheduler entry on
   Windows. One-time per-machine bootstrap. Doc lives in
   `docs/SETUP_DISTRIBUTED.md`.

2. **TLS / auth.** Tailscale-allowlist on the listener (`--host
   100.x.x.x` instead of `0.0.0.0`) is enough for our trust model.
   Public AWS instances reach the coordinator via Tailscale too.

3. **Worker discovery.** Static `shards_config.json` lists worker
   URLs (same shape as today, just URL instead of SSH host). Future
   work: dynamic registration via `POST /v2/workers/register`.

4. **Idempotency.** `report_result` is keyed by `claim_id`. Duplicate
   reports (worker retries on network blip) return 200 with the
   prior result; coordinator does NOT double-count.

5. **Backward compat.** The SSH path stays runnable until all three
   on-prem shards have switched. Hard cut after that — the
   `_push_weights_to_remote` + `_pull_remote_replays` + SSH-launch
   functions get deleted, not deprecated.

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
