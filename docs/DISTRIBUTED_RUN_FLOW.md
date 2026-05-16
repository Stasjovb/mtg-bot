# Distributed Run Flow — v2 (REST)

Companion to [`DISTRIBUTED_API_v2.md`](DISTRIBUTED_API_v2.md). That doc
defines the endpoints; this one walks through how they string together
during deployment and during a typical `mtg_bot iterate` run.

## Topology recap

```
                          shards_config.json
                          (canonical list of
                           workers; read by
                           coordinator AND
                           orchestrator)
                                 │
        ┌────────────────────────┼────────────────────────┐
        │                        │                        │
        ▼                        ▼                        ▼
  ┌──────────┐            ┌──────────┐             ┌────────────┐
  │ Worker   │            │ Worker   │             │ Worker     │
  │ master   │            │ macbook  │             │ desktop-   │
  │ :5198    │            │ :5198    │             │ g72aptg    │
  └──────────┘            └──────────┘             │ :5198      │
        │                        │                 └────────────┘
        │                        │                        │
        │  GET /v2/weights        │                        │
        │  POST /v2/claim         │                        │
        │  POST /v2/report_result │                        │
        │  GET /v2/stage/<id>     │                        │
        └─────────────────┬──────┴────────────────────────┘
                          ▼
                  ┌────────────────┐         GET /v2/heartbeat
                  │ Coordinator    │ ◄────── (every 10s, per worker)
                  │ master:5099    │
                  └────────────────┘
                          ▲
                          │ POST /v2/stage/create
                          │ POST /v2/stage/<id>/close
                          │
                  ┌────────────────┐         POST /v2/start_self_play
                  │ Orchestrator   │ ──────► POST /v2/start_eval
                  │ (iterate CLI,  │         POST /v2/stop
                  │  one-shot)     │
                  └────────────────┘
```

Network listeners bind to the tailnet IP (`100.x.x.x`), not `0.0.0.0`.
Trust = "any IP in the tailnet."

## Initial deployment (one-time per cluster)

### Per-machine bootstrap (Mac / Win10 / future AWS)

1. **Install the project** — clone the repo, build the Python 3.13
   venv, run `pip install -e .[dev]`. Standard CLAUDE.md flow.
2. **Install the daemon as a native service:**
   - **Linux (systemd):** `/etc/systemd/system/mtg-bot-worker.service`
     points at `python -m mtg_bot.worker_daemon --host
     <tailnet-ip> --port 5198`. `Restart=on-failure`,
     `WantedBy=multi-user.target`.
   - **macOS (launchd):** `~/Library/LaunchAgents/com.mtg-bot.worker.plist`
     with `KeepAlive=true`, `RunAtLoad=true`, label `com.mtg-bot.worker`,
     stdout/stderr in `~/Library/Logs/mtg-bot/`.
   - **Windows (Task Scheduler):** task `MTGBotWorker`, trigger "At
     startup," action `python -m mtg_bot.worker_daemon ...`. Set
     `RestartCount=999` with 30s delay between restarts.
3. **Tailscale enrolled.** `tailscale up` brings the machine into the
   tailnet; the daemon listener uses the tailnet IP. No public-internet
   exposure.
4. **Pre-populate `shards_config.json`** with the machine's `worker_url`
   (e.g. `http://greggs-macbook-pro:5198`).

### Coordinator setup (one machine, currently the master)

The coordinator is the existing `mtg_bot serve` process, extended with
the v2 endpoints. No new service file — `mtg_bot serve` already runs
as a long-lived process. Listener stays on `:5099`.

On startup the coordinator:

1. Reads `shards_config.json` to build the worker list.
2. Opens the SQLite work-queue / claim-tracker DB at
   `coordinator_state/queue.db` (new sibling to `runs.db`).
3. Starts a background `HeartbeatPoller` thread that hits each
   worker's `/v2/heartbeat` every 10s. Each result updates the
   coordinator's in-memory `WorkerState` map (also persisted to
   `runs.db.run_progress.extra_json` so the UI sees it).
4. Starts the Flask app for `:5099` with all v2 endpoints registered.

The coordinator does NOT need to talk to any worker before workers
talk to it — startup is order-independent. If a worker boots first,
its first heartbeat hits a 404 / connection-refused, the daemon
silently retries every 30s until the coordinator comes up.

### `shards_config.json` shape (post-migration)

```json
{
  "workers": [
    {
      "worker_id": "local",
      "worker_url": "http://desktop-j05412i:5198",
      "n_workers": 8
    },
    {
      "worker_id": "greggs-macbook-pro",
      "worker_url": "http://greggs-macbook-pro:5198",
      "n_workers": 6
    },
    {
      "worker_id": "desktop-g72aptg",
      "worker_url": "http://desktop-g72aptg:5198",
      "n_workers": 4
    }
  ]
}
```

Fields that died with SSH: `host` / `user` / `repo_path` /
`venv_python` / `ssh_port`. None of those are needed any more —
REST replaces them all.

## Steady-state heartbeat loop

Every 10s, the coordinator's `HeartbeatPoller`:

1. For each `worker_url` in `shards_config.json`:
   - `GET <worker_url>/v2/heartbeat` with a 3s timeout.
   - On 200: update `worker_state.last_heartbeat_at = now`, store the
     `host{}` snapshot for the UI, transition `STALE`→`ALIVE` if
     applicable, log a stage-progress delta if `games_done` advanced.
   - On timeout / connection error: leave `last_heartbeat_at`
     unchanged; the staleness check on the next tick decides whether
     to advance to STALE/DEAD.
2. For each worker: compare `now - last_heartbeat_at` to thresholds:
   - `<30s` → ALIVE
   - `30-90s` → STALE (UI shows yellow indicator; no action)
   - `>90s` → DEAD (UI shows red; **immediately re-queue all claims
     held by this worker**)
3. Persist the per-worker snapshot into `run_progress.extra_json` for
   the active stage so the UI's machine sub-cards render live data.

The poller is one thread; per-worker calls are sequential. With 3
workers × ~50ms typical RTT, one full poll cycle is ~150ms — fine
on a 10s budget.

## Walkthrough: a typical `mtg_bot iterate` run

Premise: `current_best = v5`, `iterations_completed = 8`, user runs
`mtg_bot iterate --bootstrap-version v5 --games-per-iteration 1000
--eval-games 500 ...`. Three workers all ALIVE.

### Phase 1 — Orchestrator boots

```
mtg_bot iterate    [stdout]
└── read iterate_state.json → current_best=v5, iter_id=iter_009
└── read shards_config.json → workers = [local, mac, win10]
└── compute games per shard: even-split or weighted by n_workers
    (currently even; n_workers is internal to the daemon)
```

### Phase 2 — Self-play stage setup

```
Orchestrator ──► Coordinator   POST /v2/stage/create
{
  "stage_id": "iter_009_self_play_v6",
  "kind": "self_play",
  "weights": {"p0": "v5", "p1": "v5"},
  "nodes": 200, "samples": 4,
  "per_game_timeout_sec": 600.0,
  "capture_every": 20,
  "claim_ttl_seconds": 1200,
  "games": [<1000 game specs with deck_indices + seed>]
}
Coordinator ──► Orchestrator   200 {"stage_id":...,"n_games_queued":1000}

Orchestrator ──► Worker(local)    POST /v2/start_self_play
                                  {"stage_id": "iter_009_...",
                                   "coordinator_url": "http://...:5099",
                                   "n_workers": 8}
Worker(local) ──► Orchestrator    202 {"stage_id":...,"started_at":...}

[same POST to Worker(mac) and Worker(win10)]
```

### Phase 3 — Workers warm up and start claiming

Each worker's `start_self_play` handler runs in the background:

```
Worker(mac):
  state IDLE → SELF_PLAY_STARTING

  if "v5" not in local weights cache:
    GET <coord>/v2/weights/v5            (200, ~40MB binary)
    GET <coord>/v2/weights/v5/metadata   (200, ~2KB JSON)
    save to local trained_weights/v5/

  spin up NNEvaluator + SHM server
  spawn multiprocessing.Pool(n_workers=6)
  for each pool worker, start the claim/play loop:

    state SELF_PLAY_STARTING → SELF_PLAY_RUNNING

    while True:
      POST <coord>/v2/claim {"worker_id":"mac","stage_id":"iter_009..."}
        → 200 {"claim_id":"iter_009_self_play_v6:0042","game_idx":42,
               "deck_indices":[...], "seed":..., "expires_at":...}
        OR 204 (no more work; transition to STOPPING then IDLE)

      run game 42 (PIMC, 200 nodes, 4 samples) → samples npz + outcome

      POST <coord>/v2/report_result  (multipart)
        meta: {"claim_id":"iter_009_self_play_v6:0042",
               "outcome":"completed","winner":0,"n_samples":1142,
               "duration_s":31.4,"shard_label":"mac"}
        npz:  <bytes>
        replay: <bytes>  (only on capture-every hits)
        → 200 {"accepted": true}
```

Meanwhile, the coordinator's `HeartbeatPoller` keeps ticking every
10s. The training UI fetches `/v2/stage/iter_009_self_play_v6`
periodically and renders the headline counters + per-machine
sub-cards (from the cached heartbeat snapshots).

### Phase 4 — Stage completion

When the coordinator's queue is empty (all 1000 games either
in-flight or done), `/v2/claim` returns 204. Each worker's pool
threads exit their loop, the pool joins, and the daemon transitions
back to IDLE.

```
Worker(mac):
  POST /v2/claim → 204
  state SELF_PLAY_RUNNING → STOPPING (drain in-flight games)
  ... in-flight games complete and POST /v2/report_result
  state STOPPING → IDLE
```

Orchestrator polls `GET /v2/stage/iter_009_self_play_v6` every 30s.
Once `status == "complete"` (all in-flight reported back, queue is
empty), it moves on:

```
Orchestrator:
  GET /v2/stage/iter_009_self_play_v6
    → {"status":"complete","n_games_done":987,"crashed":2,"timed_out":11}
```

The transition to `complete` is automatic — the coordinator's
`/v2/report_result` handler flips the stage's `status` the moment
the last in-flight game's result lands, no orchestrator-side
`/close` call required. (Self-play stages naturally drain this
way; eval stages either auto-close the same way once all 500/2000
games run OR are explicitly closed early by the Wilson-CI watcher
— see Phase 6.)

### Phase 5 — Train (in-process on master)

Train stage stays as it is today — `mtg_bot train` invoked as a
subprocess on the master, reading npzs from the coordinator's
artifact store (currently `iterate_data/` on the master, since the
coordinator runs there). No REST calls involved; training is purely
a master-local concern.

Produces `v6`, registers in `trained_weights/v6/` with metadata
sidecar.

### Phase 6 — Eval stage

```
Orchestrator ──► Coordinator   POST /v2/stage/create
{
  "stage_id": "eval_v6_vs_v5_500g",
  "kind": "eval",
  "weights": {"new": "v6", "old": "v5"},
  "nodes": 200, "samples": 4,
  "per_game_timeout_sec": 600.0,
  "capture_every": 0,
  "claim_ttl_seconds": 1200,
  "games": [<500 game specs>]
}
Coordinator ──► Orchestrator   200

Orchestrator ──► Worker(local,mac,win10)   POST /v2/start_eval
                                           {"stage_id":"eval_v6_vs_v5_500g",
                                            "coordinator_url":...,
                                            "n_workers":...}
```

Workers behave identically to self-play except each `/v2/claim`
response carries `weights: {new: "v6", old: "v5"}` and the
`/v2/report_result` payload reports `wins_new` / `wins_old` instead
of `n_samples`.

The eval early-stop watcher (already exists; one separate process on
the master) polls `GET /v2/stage/eval_v6_vs_v5_500g` every 5s.
When the Wilson 95% CI lower bound clears `EVAL_GATE_THRESHOLD`
(currently 0.525):

```
Watcher ──► Coordinator   POST /v2/stage/eval_v6_vs_v5_500g/close
                          {"reason": "early_stop_pass"}
Coordinator ──► Watcher   200

Subsequent worker /v2/claim calls for this stage_id → 204.
Workers drain in-flight games, report results, transition IDLE.
```

The orchestrator polls `GET /v2/stage/...` until status is
`complete`, reads the final `wins_new` / `wins_old`, applies the
0.525 gate, updates `iterate_state.json` (promote or not), and
exits.

## Failure scenarios

### A worker process dies mid-stage

```
Worker(mac):
  [crash — SIGKILL, OOM, exception in pool]
  daemon process exits
  native service (launchd) auto-restarts the daemon
  daemon comes up IDLE

Coordinator:
  next 10s heartbeat → connection refused
  next 30s → worker marked STALE
  next 90s → worker marked DEAD
  → re-queue all in-flight claims held by mac
  → /v2/claim from local + win10 picks them up
  → eventually mac comes back ALIVE, but has no current_stage_id
    → orchestrator does NOT re-dispatch (stage is already running;
      new workers join via the next iter)
```

If the worker's claims expire before the coordinator notices DEAD
(unlikely with 90s heartbeat window vs 1200s claim TTL), the
claim-TTL mechanism re-queues them as a fallback.

### Coordinator crashes mid-stage

```
Coordinator:
  [crash — process exit]
  systemd / Task Scheduler restarts mtg_bot serve
  Coordinator boots, reads coordinator_state/queue.db
  → recovers stage queues + in-flight claims
  → HeartbeatPoller restarts

Workers:
  next /v2/claim or /v2/report_result → connection refused
  daemon retry loop (exponential backoff, max 30s)
  on coordinator return:
    in-flight claim's POST /v2/report_result → 200 (idempotent on claim_id)
    OR 409 (claim was redelivered — drop the result; loop continues)
  state stays SELF_PLAY_RUNNING throughout the blip

Orchestrator:
  GET /v2/stage/<id> retries until 200
```

The coordinator's queue.db is the durability boundary — it must
fsync on stage_create and on claim_dequeue/report_result.

### Orchestrator crashes mid-iter

The orchestrator is a one-shot CLI; if the user's iterate process
dies, the stages it created on the coordinator keep running. The
user re-launches `mtg_bot iterate --resume iter_009`, which checks
the coordinator's `GET /v2/stage/iter_009_self_play_v6` status,
fast-forwards over completed phases, and picks up at the next
incomplete phase.

### User Ctrl-C the iterate

Orchestrator catches SIGINT, POSTs `/v2/stage/<id>/close` for the
current stage, optionally POSTs `/v2/stop` to each worker (graceful
drain), then exits. User can resume later.

### Network partition (one worker isolated)

The partitioned worker stops getting `/v2/claim` responses (or its
heartbeat poll responses 200 but `/v2/claim` fails). Daemon retries
with backoff. Coordinator sees the worker as DEAD after 90s
(heartbeat times out from coordinator's side) and re-queues its
claims. When the partition heals, the worker's `/v2/claim` returns
204 (work is done elsewhere or the stage is closed), and it
transitions to IDLE.

## State machine summary

```
                    ┌─────┐
                    │IDLE │◄────────────────────┐
                    └──┬──┘                     │
       start_self_play │  start_eval             │
                       ▼                         │
              ┌────────────────┐                 │
              │ SELF_PLAY_     │ ──drain done──► │
              │   STARTING     │                 │
              └────────┬───────┘                 │
                       │ pool ready              │
                       ▼                         │
              ┌────────────────┐ /v2/stop or     │
              │ SELF_PLAY_     │ /v2/claim=204   │
              │   RUNNING      │ ────────────►   │
              └────────┬───────┘                 │
                       │ exception               │
                       ▼                         │
                  ┌────────┐  acknowledge        │
                  │ ERROR  │ ─────────────────────┤
                  └────────┘                     │
                                                 │
              ┌────────────────┐                 │
              │ STOPPING       │ ────drained────►│
              └────────────────┘
```

EVAL_STARTING / EVAL_RUNNING have the same shape; states are unioned
on the wire (`state` enum), not duplicated as separate machines.

## What's deliberately NOT in this flow

- Training. Stays on the master as a subprocess invoked by the
  orchestrator. No REST involvement.
- The training UI. Reads `runs.db` and renders. The coordinator's
  heartbeat poller writes per-worker snapshots into `run_progress`
  rows so the existing UI code paths keep working unchanged.
- Replay rendering. Replays are pulled to the master via
  `/v2/report_result` multipart; the existing `/api/runs/<id>/replays`
  endpoint serves them.
- The eval early-stop watcher's "is this a STOP sentinel?" check.
  Watcher now reads coordinator's `/v2/stage/<id>` JSON instead of
  filesystem JSONs; sentinel mechanism becomes
  `POST /v2/stage/<id>/close`.
- Multi-coordinator failover. One coordinator. If the master is down,
  the cluster is down.

## Phasing reminder (from API doc)

1. **Contract** (this + the API doc) — frozen for review.
2. **Worker daemon** (`mtg_bot.worker_daemon`) — Flask app + state
   machine + native service files. Existing `cli/shard.py` body
   becomes the `start_self_play` handler. Heartbeat metrics via
   `psutil` + `pynvml`.
3. **Coordinator extension** — add `/v2/stage/*`, `/v2/claim`,
   `/v2/report_result`, `/v2/weights/<v>[/metadata]` to the
   port-5099 server. Add the `HeartbeatPoller` thread and the
   `queue.db` durability layer.
4. **Migrate one shard at a time** — local first, then Mac, then
   Win10. SSH path stays runnable in parallel until all three are
   green.
5. **Hard cut** — delete `_push_weights_to_remote`,
   `_pull_remote_replays`, `run_shard_remote`, the orphan-sweep-via-SSH
   helpers, `cli/shard.py` (replaced by the daemon's handlers).

## Phase 3 implementation decisions

Decisions made while implementing Phase 3 (commits on
`feature/coordinator-v2-endpoints`):

- **Blueprint location.** The v2 endpoints live in a new module
  `src/mtg_bot/cli/runs/v2_endpoints.py` that exposes a
  `build_v2_blueprint(...)` factory. `mtg_bot.cli.serve.create_app`
  imports + registers it when `queue_db_path` (or `progress_dir`) is
  set. Existing `/run/*` and `/queue/*` endpoints are untouched.
- **queue.db default path.** When the caller passes `progress_dir`
  without `queue_db_path`, the factory derives
  `<progress_dir>/coordinator_state/queue.db` — colocated with the
  existing `runs.db` and per the run-flow doc. Pass an explicit
  `queue_db_path` to override.
- **shards_config.json shape.** Both the new
  `{"workers": [{worker_id, worker_url, n_workers}]}` shape and the
  legacy `{"shards": [{host, user, repo_path, ...}]}` shape are
  parsed by `heartbeat_poller.load_shards_config`. Legacy entries
  that lack a `worker_url` are silently skipped by the poller, so
  the migration can run side-by-side with the SSH path.
- **report_result file layout.** Npzs go to
  `iterate_data/<stage_id>_<shard_label>_<safe_claim_id>.npz` and
  replays go to `replays/<stage_id>_<shard_label>/<game_idx>.json.gz`
  — close to the existing chunk-naming convention so train + UI keep
  reading from the same directories without code changes.
- **Late-duplicate detection.** `queue_db.requeue_claim` tombstones
  the old claim row (`reported=1` with `report_json={"abandoned":
  true}`) instead of deleting. `record_report` distinguishes the
  abandoned tombstone (returns `"conflict"` → 409) from a genuine
  on-time duplicate (returns `"duplicate"` → silent 200), giving the
  worker a clear "your work was reassigned" signal.
- **Claim_id uniqueness across re-claims.** When `claim_next_game`
  detects a primary-key collision on the base claim_id (i.e. a
  prior abandoned claim for the same `game_idx`), it appends an
  `int(now_unix * 1000)` suffix so old and new claim_ids are
  distinguishable. Worker libraries should treat the claim_id as
  opaque.
- **HeartbeatPoller liveness re-queue scope.** A DEAD transition
  re-queues all claim_ids the coordinator's in-memory tracker
  believes the worker holds. The set is populated on `/v2/claim`
  and pruned on `/v2/report_result`; it does NOT survive
  coordinator restart. After restart, the claim-TTL sweep (run on
  startup) is the recovery mechanism. The two are layered per the
  API doc.
- **Existing endpoints untouched.** No changes to `mtg_bot serve`'s
  pre-Phase-3 surface (`/queue/*`, `/run/*`, `/setup_remote.*`,
  `/repo.bundle`). Existing tests keep passing.
