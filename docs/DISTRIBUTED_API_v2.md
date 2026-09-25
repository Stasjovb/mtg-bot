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

Worker asks "give me a game to play from this stage."

```json
// Request
{
  "worker_id": "greggs-macbook-pro",       // matches shards_config worker_url's identity
  "stage_id": "iter_009_self_play_v6"
}

// Response 200
{
  "claim_id": "iter_009_self_play_v6:0042",
  "game_idx": 42,
  "deck_indices": [1247, 3891],
  "seed": 9000042,
  "kind": "self_play",
  "weights": { "p0": "v6", "p1": "v6" },
  "nodes": 200,
  "samples": 4,
  "per_game_timeout_sec": 600.0,
  "capture_every": 20,
  "expires_at": "2026-05-15T18:54:32Z"
}

// Response 204 (stage drained OR queue exhausted)
// Response 404 (no such stage_id)
```

`claim_id` is the idempotency key for `report_result`. `expires_at`
is `now + claim_ttl_seconds` from the stage spec; after expiry the
coordinator marks the claim re-claimable.

**Self-play evaluator kind (2026-09-24).** Self-play claims also
carry, copied verbatim from the stage spec:

```json
{
  "evaluator": "heuristic",                  // "nn" (default) | "heuristic"
  "action_encoding_version": "canonical_v2",
  "structured_tokens": true,
  "structured_scalar_schema_version": 2,
  "root_dirichlet_alpha": 0.5,
  "root_dirichlet_eps": 0.25,
  "move_temperature": 1.0,
  "temperature_cutoff": 30
}
```

`evaluator` selects what drives the PIMC search on both seats:

* `"nn"` / absent — the historical path. The worker resolves
  `weights.p0`, fetches the blob + `metadata.json`, and discovers the
  action encoding / token schema from that metadata.
* `"heuristic"` — PIMC over `MtgHeuristicEvaluator`, no weights and
  no torch at all (the warm-start corpus path; see
  `mtg_bot.training.self_play_evaluator`). Because there is no
  version to discover metadata from, the three corpus-format fields
  above are **authoritative on the claim** and
  `action_encoding_version` is **required** — a worker that receives a
  heuristic claim without it raises rather than guessing.

**Old-worker interlock.** A heuristic stage carries
`weights: {"p0": "", "p1": ""}`. A worker running code that predates
the `evaluator` field does `weights.get("p0") or weights.get("new")`
and raises `self-play claim missing weights.p0` on every claim, so
the stage yields zero samples and `iterate` exits with
`self_play_yield_error`. This is deliberate: silently playing a
warm-start corpus stage with the NN would produce exactly the corpus
the stage exists to replace. Self-update every worker before running
a heuristic stage.

### `POST /v2/report_result`

Worker submits a finished game. **Phase 2B cutover (2026-05-21):**
the request body is now **JSON only** and carries **artifact URIs**,
not bytes. Workers upload the `.npz` (and optional replay
`.json.gz`) to shared storage (`file://` share or `s3://` bucket)
**before** POSTing, then send only the URI + declared size. The
coordinator responds **`202 Accepted`** in <10ms after a sync
validate / claim-lookup; the fetch + disk-write + DB upsert happen
on a background `ThreadPoolExecutor` (16 threads, single
process-wide instance). This is the load-bearing fix for the
cluster-scale POST bottleneck — see the
`project_mtg_bot_coord_wsgi` memory entry for the diagnosis.

```jsonc
// Request — application/json (multipart is gone; non-JSON bodies 400)
{
  "meta": {
    "claim_id": "iter_009_self_play_v6:0042",   // required
    "outcome": "completed",                      // "completed" | "timed_out" | "crashed"
    "winner": 0,                                 // 0/1, or null on non-completed
    "n_samples": 1142,
    "duration_s": 31.4,
    "shard_label": "greggs-macbook-pro"
  },
  "npz_uri": "s3://mtg-bot-artifacts-630589799985/iter_009/wA/0042.npz",  // optional
  "replay_uri": "s3://mtg-bot-artifacts-630589799985/iter_009/wA/0042.json.gz",  // optional
  "npz_size_bytes": 524288,        // optional; coord verifies post-fetch, rejects on mismatch
  "replay_size_bytes": 87234       // optional
}

// Response 202 — accepted; background fetch+write+upsert enqueued
{ "accepted": true, "queued": true, "claim_id": "iter_009_self_play_v6:0042" }

// Response 400 — non-JSON body, missing `meta`, missing `meta.claim_id`, etc.
// Response 404 — unknown claim_id (no matching claim row).
// Response 409 — claim already reported (idempotent duplicate, or a
//                zombie-worker post against a claim that was re-queued
//                and re-reported by a different worker).
{ "accepted": false, "error": "claim already reported" }
```

Supported URI schemes:

- `file://<path>` — read from the local filesystem (or any
  SMB/NFS share mounted onto the coord's host).
- `s3://<bucket>/<key>` — read via `boto3 GetObject` with retry on
  transient 5xx / `429 Throttling` errors (1s / 3s / 10s backoff);
  `403` / `404` fail-loud immediately. Requires the `[s3]`
  pyproject extra (boto3) on the coord and the env var
  `MTG_BOT_COORD_ARTIFACT_BACKEND` set to `s3` or `auto`
  (see "Coord storage-backend selection" below).

Eval results have the same shape, just with no URI fields.

**Background-job failure semantics.** If the fetch fails (network
error, S3 unreachable, size mismatch vs. declared bytes, broken
URI), the background job retries 3× (1s / 3s / 10s) and then writes
a results row with `outcome="upload_failed"`, `npz_path=NULL`, and
`artifact_uri=<the broken URI>` so forensics can locate the broken
upload. The worker has already moved on, so the failure is **not**
surfaced via a 5xx HTTP status — the durable record is the
`upload_failed` row.

**Idempotency.** A duplicate POST for an already-reported `claim_id`
is rejected synchronously with `409` before enqueueing; the
background job itself is also idempotent (re-checks the claim's
`reported` flag at execution time and skips with an INFO log if
another job already landed).

**Latency.** The sync portion of the handler does only JSON
validation + a single `SELECT` on the claim row, so the worker's
POST returns in well under 10ms even at cluster scale. The
coordinator's serialization bottleneck (multipart parse + disk write
+ `WRITE_LOCK` upsert all on the request thread) is gone.

### `POST /v2/stage/create`

Orchestrator opens a new stage of work on the coordinator. The
coordinator allocates the per-stage queue, persists the spec, and
returns 200 with the canonical `stage_id`. Workers pulling on
`/v2/claim` for this `stage_id` get one game per call.

```json
// Request
{
  "stage_id": "iter_009_self_play_v6",   // proposed by orchestrator; idempotent
  "kind": "self_play",                    // "self_play" | "eval"
  "weights": { "p0": "v6", "p1": "v6" },  // eval uses {"new": "v6", "old": "v5"}
  "nodes": 200,
  "samples": 4,
  "per_game_timeout_sec": 600.0,
  "capture_every": 20,
  "claim_ttl_seconds": 1200,
  "games": [
    { "game_idx": 0, "deck_indices": [1247, 3891], "seed": 9000000 },
    { "game_idx": 1, "deck_indices": [42, 8123], "seed": 9000001 },
    // ... 1000 entries for self-play, 500 for eval
  ]
}

// Response 200
{ "stage_id": "iter_009_self_play_v6", "n_games_queued": 1000 }

// Response 409 if stage_id already exists with a different spec
```

A self-play stage may additionally carry `evaluator`,
`action_encoding_version`, `structured_tokens`,
`structured_scalar_schema_version`, `root_dirichlet_alpha`,
`root_dirichlet_eps`, `move_temperature` and `temperature_cutoff`;
the coordinator stores them in `spec_json` and copies them onto every
claim (see `POST /v2/claim`). Eval stages pin the exploration knobs
off and `evaluator` to `"nn"` so the promotion gate stays
deterministic-argmax.

### `GET /v2/stage/<stage_id>`

Anyone reads aggregate progress for a stage. Used by the
orchestrator to wait for completion, by the eval watcher to
compute Wilson CIs for early-stop, by the training UI for the
headline numbers.

```json
{
  "stage_id": "iter_009_self_play_v6",
  "kind": "self_play",
  "status": "running",     // "queued" | "running" | "drained" | "complete"
  "n_games_total": 1000,
  "n_games_queued": 412,
  "n_games_in_flight": 24,
  "n_games_done": 564,
  "wins_new": null,         // populated for eval stages only
  "wins_old": null,
  "draws": 0,
  "crashed": 1,
  "timed_out": 4,
  "upload_failed": 0,       // results the coord could NOT fetch
  "started_at": "2026-05-15T18:30:00Z",
  "drained_at": null,
  "complete_at": null
}
```

`status` flips to `complete` **automatically** once every `game_idx`
has a row in the results table and no claims are still in-flight —
no explicit `/close` call is required for the natural-drain path.
The transition fires inside the coordinator's `/v2/report_result`
handler the moment the last in-flight game reports, so an
orchestrator polling this endpoint sees `complete` on the first GET
after the final result lands. (The explicit `/close` endpoint below
still exists for early-stop scenarios where the orchestrator wants
to abandon residual queued work.) A stage created with
`games: []` (zero work) is auto-closed at creation time and reads
`complete` on the very first GET.

`upload_failed` counts results rows the coordinator wrote with
`outcome='upload_failed'` — the worker finished the game and reported
it, but the coordinator could not fetch the artifact from the URI the
worker gave it. **Those games still count in `n_games_done` and
`n_samples`**, which is why a stage can read "500/500 done, 1M
samples" with nothing on disk. The same count also appears on each
entry of the `machines[]` array, so you can see which worker is
dropping data. `mtg_bot iterate` treats a non-zero total as a hard
error. (Absent on pre-2026-09-23 coordinators; consumers default it
to 0.)

### `POST /v2/artifact/upload`

Drop-off endpoint for workers running
`--artifact-storage-uri http://<coordinator>:5099` — i.e. workers
that share neither a filesystem nor an S3 bucket with the
coordinator (the Mac, over Tailscale).

Body is the **raw artifact bytes** (`application/octet-stream`). The
key fields travel as query params (or `X-Artifact-*` headers):

| Param | Values |
|---|---|
| `kind` | `npz` \| `replay` |
| `stage_id` | `[A-Za-z0-9_.\-:]+` |
| `shard_label` | `[A-Za-z0-9_.\-:]+` (defaults to `unknown`) |
| `claim_id` | `[A-Za-z0-9_.\-:]+` |

The coordinator writes the bytes to
`<--artifact-upload-dir>/<build_artifact_key(...)>` (write-then-rename,
so a retried POST is an atomic overwrite) and responds:

```json
// 200
{ "uri": "file:///C:/.../artifact_uploads/<stage>/<shard>/<claim>.npz",
  "key": "<stage>/<shard>/<claim>.npz",
  "bytes": 283914 }
```

The returned `uri` is **coordinator-local**: the worker echoes it
verbatim in its `/v2/report_result` body and the coordinator's
existing `LocalArtifactFetcher` rehydrates it. No new fetcher scheme.

Errors: `400` bad/missing key fields or a key that escapes the upload
dir, `413` body over the 64 MB cap, `503` when the coordinator was
started without an artifact-upload dir. The worker-side
`HttpArtifactUploader` retries `429`/`5xx` and connection errors on a
1s/3s/10s schedule and fails loudly on any other 4xx.

### `POST /v2/stage/<stage_id>/close`

Orchestrator (or the early-stop watcher) signals "no more work for
this stage." Coordinator marks the stage as `drained`: subsequent
`/v2/claim` calls for this stage return 204 and any pending entries
in the queue are dropped. Already-in-flight claims still report
back normally. When in-flight drops to 0, status becomes `complete`.

This endpoint is for **early-stop / abandon-residual-work** flows
(e.g. the eval watcher's Wilson-CI pass/fail). It's NOT required
for the natural-drain path — the coordinator auto-closes stages
on its own once every game has reported a result (see the
`/v2/stage/<id>` note above).

```json
// Request
{ "reason": "early_stop_pass" }   // free-form; logged for forensics

// Response 200
{ "stage_id": "...", "drained_at": "2026-05-15T19:14:32Z" }
```

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

Orchestrator tells the worker "start pulling work for this stage."
Worker pre-fetches weights via `/v2/weights/<version>` (cache-aware),
spins up its `NNEvaluator` + SHM server, and starts a background
loop that pulls from `coordinator_url`'s `/v2/claim`.

```json
// Request
{
  "stage_id": "iter_009_self_play_v6",
  "coordinator_url": "http://desktop-j05412i:5099",
  "n_workers": 8
}

// Response 202 (accepted; running in background)
{ "stage_id": "...", "started_at": "2026-05-15T..." }

// Response 409 if worker is not IDLE (already running a stage)
{ "error": "worker_busy", "current_state": "SELF_PLAY_RUNNING" }
```

The worker doesn't need per-game knobs (nodes / samples / timeouts /
weights versions) in this request — each `/v2/claim` response carries
them, since the coordinator's stage spec is the source of truth.

### `POST /v2/start_eval`

Identical shape; coordinator's stage spec just has `kind: "eval"`
with `weights: {new, old}` instead of `{p0, p1}`.

```json
{
  "stage_id": "eval_v6_vs_v5_500g",
  "coordinator_url": "http://desktop-j05412i:5099",
  "n_workers": 8
}
```

### `POST /v2/stop`

Coordinator says "stop the current stage gracefully." Worker drains
in-flight games (lets workers finish their current game), reports
results normally, then transitions to IDLE. Returns 200 with the
worker's state at the time of receipt.

### `POST /v2/self_update`

Operator/orchestrator tells the worker "refresh your code." The
worker pulls the coordinator's existing `GET /repo.bundle`
(Tailscale-only — no GitHub creds, so ephemeral AWS workers update
with nothing but tailnet access), `git reset --hard`s to the
requested ref, **conditionally** rebuilds the Rust engine + deps,
then re-execs itself in place (`os.execv` — supervisor-independent).

```json
// Request
{
  "coordinator_url": "http://desktop-j05412i:5099",
  "ref": "main"                                    // optional, default "main"
}

// Response 202 (accepted; running in background)
{
  "accepted": true,
  "old_commit": "abc1234",   // short SHA before update (null on non-git deploy)
  "ref": "main",
  "coordinator_url": "http://desktop-j05412i:5099"
}

// Response 400 if coordinator_url is missing
{ "error": "coordinator_url is required" }

// Response 409 if the worker is not IDLE
{ "error": "worker_busy", "current_state": "SELF_PLAY_RUNNING" }
```

**IDLE-only**, exactly like `/v2/start_*` — a worker mid-stage (or
mid-update) is refused with 409. Stop the worker first (`/v2/stop`)
or wait for natural drain.

**Conditional rebuild.** The worker diffs the old vs. target commit
and only runs `maturin develop --release` when `rust/`,
`Cargo.toml`, `Cargo.lock`, or `pyproject.toml` changed;
`pip install -e .` only when `pyproject.toml` changed. A code-only
commit skips the multi-minute build and re-execs immediately — the
"only rebuild the engine when the engine changed" property without
physically splitting the engine into its own package (caveat in
`deploy/README.md`).

**Verification is via `/v2/heartbeat`, not this response.** Because
the daemon re-execs, the 202 ships before the work runs. Poll
`/v2/heartbeat`: on success a *fresh* process comes up with
`uptime_s` reset, an advanced `git_commit`, `state: IDLE`, and
`last_update: null`. On a no-delta fetch the same process returns to
`IDLE` with `last_update.phase = "up_to_date"`. On a
fetch/reset/build failure the daemon goes `ERROR` with the detail in
both `error` and `last_update.error` (no re-exec — an operator
intervenes; safe because self-update only runs from IDLE, so no game
is in flight). `last_update.phase` progresses
`fetching → resetting → building → reexec` (or `up_to_date` /
`error`).
### Worker-side spot-interruption watcher (`--spot-watch`)

Not an endpoint — a worker-local poller, opt-in via the daemon's
`--spot-watch` CLI flag (default OFF; on-prem workers and the test
suite are unaffected). Enable it only on AWS EC2 **spot** workers
(bake the flag into the EC2 service file / user-data).

When enabled, a daemon thread polls the EC2 instance-metadata
interruption endpoint via IMDSv2:

1. `PUT http://169.254.169.254/latest/api/token` with header
   `X-aws-ec2-metadata-token-ttl-seconds: 21600` → an opaque token.
2. `GET http://169.254.169.254/latest/meta-data/spot/instance-action`
   with header `X-aws-ec2-metadata-token: <token>`, every 5s
   (configurable). Steady-state response is **HTTP 404** (no
   interruption). A **401** means the token expired — the watcher
   transparently re-fetches and retries.

AWS publishes a ~2-minute reclaim warning as **HTTP 200** with body
`{"action": "terminate"|"stop", "time": "<iso8601>"}`. On the first
sighting the watcher fires its callback **exactly once** and stops
polling. The daemon wires that callback to **the same graceful path
`POST /v2/stop` triggers** (`mark_stopping` → the claim loop's
`stop_requested` flag): the worker stops claiming new games and
drains its in-flight game locally. No new worker state — `STOPPING`
is reused.

**Interruption == fast graceful drain.** Without `--spot-watch`, an
AWS-reclaimed worker dies abruptly mid-game and its in-flight claims
sit unreclaimed until the coordinator marks it `DEAD` (~90s of
missed heartbeats — see "Abandonment detection" below) or the slower
claim-TTL sweep fires. With `--spot-watch` the worker uses the
~2-minute warning to stop claiming and finish/report (or release)
its in-flight game within seconds, so the ~90s heartbeat-DEAD
reclaim lag is removed from the common spot-reclaim case.

**Scope: local drain only.** As of this feature the v2 coordinator
has **no** proactive per-worker "reclaim my claims now" endpoint
(the surface is `/v2/stage/*`, `/v2/claim`, `/v2/report_result`,
`/v2/weights/<v>`, `/v2/healthz`). The watcher deliberately does NOT
invent one — a game still running when the instance finally vanishes
falls back to the existing heartbeat / claim-TTL reclaim, exactly as
today, just with no *new* claims piled on. **Future work:** a
coordinator-side endpoint the watcher could call on interruption to
release this worker's claims instantly (turning the residual fallback
into an immediate reclaim) is a possible follow-up; out of scope
here.

A flaky/erroring IMDS call is tolerated — it is logged and polling
continues; it never kills the watcher or the daemon and never
spuriously triggers a drain.

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
  "git_commit": "abc1234",
  "last_update": null,
  "artifact_storage_uri": "http://100.115.252.110:5099",
  "game_crashes": 2,
  "pool_resets": 2,
  "pool_generation": 3,
  "max_consecutive_crashes": 5,
  "last_crash_detail": "Traceback (most recent call last): ...",
  "thread_recovery": {
    "0": {"crashes": 1, "pool_resets": 1, "consecutive_crashes": 0},
    "3": {"crashes": 1, "pool_resets": 1, "consecutive_crashes": 0}
  },
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
EVAL_STARTING | EVAL_RUNNING | STOPPING | ERROR | UPDATING`.

`error` is non-null only in `ERROR` state — carries the last fatal
exception's repr for surfacing in the training UI.

`git_commit` — short SHA of the worker's current checkout, resolved
once per process (a successful self-update re-execs, so the fresh
process reports the advanced commit). `null` on a non-git deploy.
The orchestrator uses this to confirm a `/v2/self_update` landed.

`last_update` — the most recent `/v2/self_update` progress dict
(`{phase, old_commit, target_commit, rebuild_rust, rebuild_deps,
error?, at}`) or `null` on a fresh process that has not run one.
`phase` ∈ `fetching | resetting | building | reexec | up_to_date |
error`.

`artifact_storage_uri` — the worker's `--artifact-storage-uri`
verbatim (`file://` / `http://` / `https://` / `s3://` / `null://`).
The launcher's pre-flight **refuses** to dispatch a cycle to a worker
advertising `null://`: its games would complete and count toward the
stage totals while every `.npz` was dropped on the floor. Absent on
pre-2026-09-23 daemons, which pass the check unchanged.

Crash-recovery counters (all zero on a healthy worker):

- `game_crashes` — games that died mid-play and were reported with
  `outcome: "crashed"` while the claim thread survived and kept
  claiming. Includes both `BrokenProcessPool` deaths and game bodies
  that threw.
- `pool_resets` — `ProcessPoolExecutor` rebuilds. A pool whose worker
  subprocess dies hard is permanently unusable (every later `submit()`
  raises), so the daemon swaps in a fresh executor. All N claim
  threads see the same death; the rebuild is deduped to one.
- `pool_generation` — monotonic id of the live pool. Bumps on setup
  and on every rebuild.
- `max_consecutive_crashes` — the daemon's `--max-consecutive-crashes`
  (default 5). A claim thread that hits this many crashes in a row
  *without* a clean game in between parks the daemon in `ERROR`.
- `last_crash_detail` — tail of the most recent crash traceback, for
  triage without SSHing to the box. `null` until the first crash.
- `thread_recovery` — per-claim-thread breakdown keyed by thread id
  (string): `crashes`, `pool_resets`, and the live
  `consecutive_crashes` streak (reset to 0 by any clean game).

The crashed game itself is reported to the coordinator with the
traceback in `meta.traceback`, so `claims.report_json` distinguishes a
dead pool from a game body that threw.

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

`UPDATING` is a separate IDLE-gated branch: `IDLE ──/v2/self_update──►
UPDATING`, then either the process re-execs (a brand-new `IDLE`
daemon replaces it), `UPDATING ──(no delta)──► IDLE`, or
`UPDATING ──(fetch/build fail)──► ERROR`. `/v2/start_*` and a second
`/v2/self_update` both 409 while `UPDATING`; `/v2/stop` is a no-op
that reports `UPDATING` (it must not race the re-exec). A worker
re-execing mid-update looks exactly like a normal process restart to
the coordinator (brief STALE, then ALIVE) — see "Coordinator's view"
below.

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
   reboot / network partition. For AWS spot workers this ~90s lag
   is the window `--spot-watch` shrinks to seconds — see
   "Worker-side spot-interruption watcher" above: the worker stops
   claiming + drains locally on the ~2-minute reclaim warning
   instead of vanishing mid-game and waiting out the heartbeat-DEAD
   timeout.
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
| npz samples | worker → shared storage | `file://` share or `s3://` bucket | uploaded **before** the `/report_result` POST; URI only is sent over REST (Phase 2B cutover) |
| replay .json.gz | worker → shared storage | same | optional per-game; URI only in `/report_result` |
| git bundle | coord → worker | `GET /repo.bundle` | unchanged endpoint; consumed by `/v2/self_update` (worker-initiated `git fetch` of the bundle, no GitHub creds) |

`/report_result` no longer carries any binary payload — only the
JSON envelope with the URIs. The coord rehydrates each URI on its
background executor and writes the bytes to `iterate_data/` /
`replays/` under the same deterministic filenames as before
(`<stage_id>_<shard_label>_<safe_claim_id>.npz`,
`<stage_id>_<shard_label>/<game_idx>.json.gz`), so the trainer (and
every downstream consumer of those paths) keeps working unchanged.

## Coord storage-backend selection

Worker-side schemes (`--artifact-storage-uri`):

| Scheme | Uploader | Use when |
|---|---|---|
| `file:///abs/dir` | `LocalFileUploader` | Worker and coordinator share a filesystem (same box, or an SMB/NFS mount). |
| `http://host:port` / `https://...` | `HttpArtifactUploader` | No shared FS, no bucket. POSTs to the coordinator's `/v2/artifact/upload`; the reply is a coordinator-local `file://` URI. |
| `s3://bucket/prefix` | `S3ArtifactUploader` | AWS burst workers (needs the `[s3]` extra). |
| `null://` | `NullUploader` | **Tests only.** Drops the blob; the launcher refuses it. |

Both ends share a URI scheme; the coord chooses **which fetcher
backends to wire up** at boot via the env var
`MTG_BOT_COORD_ARTIFACT_BACKEND`:

| Value | Configured fetcher backends |
|---|---|
| _unset_ (default) | `file://` only. `s3://` URIs in a report POST raise; safe default for on-prem / local dev. |
| `s3` | `file://` + `s3://`. Builds `boto3.client("s3", region_name="us-east-1")` lazily on first fetch. |
| `auto` | Same as `s3` today (placeholder for future heuristic selection). |

Set the env var on the coord process only — workers pick their own
upload destination via the matching worker-side
`MTG_BOT_WORKER_ARTIFACT_BACKEND` (covered in the worker daemon
docs). The two ends are independent: a coord with the `s3` backend
will still happily serve a worker that uploads `file://` URIs to a
shared SMB mount, and vice versa.

### S3 bucket provisioning

For the production AWS-bursting flow the user already provisioned
the bucket `mtg-bot-artifacts-630589799985` in `us-east-1`.
Minimum requirements for a fresh bucket:

1. **Bucket region** matches `S3ArtifactFetcher(region=...)` — the
   default is `us-east-1`. Cross-region fetches still work but eat
   inter-region bandwidth and add latency.
2. **IAM** — the coord's instance / user needs
   `s3:GetObject` on `arn:aws:s3:::<bucket>/*`. Workers need
   `s3:PutObject` on the same prefix. Bucket policies live next to
   the deploy templates.
3. **Lifecycle policy** (recommended) — auto-expire artifacts
   after N days. The coord persists the npz to local disk on
   successful fetch, so the S3 copy is just the transport, not the
   long-term record.
4. **Public access** — disabled. The trust model is IAM + VPC, not
   public URLs.

To enable S3 on the coord:

```bash
export MTG_BOT_COORD_ARTIFACT_BACKEND=s3
# fail-loud at first fetch if boto3 isn't installed:
pip install -e ".[s3]"
```

The S3 fetcher retries transient errors (5xx, 429) at 1s / 3s / 10s
and fails-loud on 403 / 404 (those are configuration errors that
no retry will fix; the background job marks the row
`upload_failed` and logs at ERROR).

## What replaces what

| Today | v2 REST |
|---|---|
| Master SSH-launches `mtg_bot shard` on Mac/Win10 | Orchestrator POSTs `/start_self_play` to worker daemon |
| Master SCP's `weights.pt` to remote `trained_weights/<v>/` | Worker `GET /v2/weights/<v>` (cached) |
| Master SCP's `metadata.json` alongside | Worker `GET /v2/weights/<v>/metadata` |
| Master SCP's npz / replay back from remote | Worker uploads to shared storage (`file://` / `s3://`) and `/report_result` carries the URI only; coord rehydrates on a background executor |
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
| Code distribution to workers | **`/v2/self_update` pulls the coordinator's `/repo.bundle`, never `git pull origin`.** Tailscale-only trust model — no GitHub creds on any worker, so ephemeral AWS instances update with nothing but tailnet access. IDLE-gated; conditional Rust/deps rebuild; `os.execv` re-exec (supervisor-independent — systemd is `Restart=on-failure`, so a clean exit would NOT restart). |

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
