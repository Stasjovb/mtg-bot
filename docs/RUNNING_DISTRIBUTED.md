# Running the distributed flow (v2)

Day-to-day operations after the cluster is set up. For one-time
per-machine bootstrap (Python, venv, native services, Tailscale), see
[`SETUP_DISTRIBUTED.md`](SETUP_DISTRIBUTED.md). For the REST contract,
see [`DISTRIBUTED_API_v2.md`](DISTRIBUTED_API_v2.md). For the runtime
walkthrough of an `mtg_bot iterate` invocation, see
[`DISTRIBUTED_RUN_FLOW.md`](DISTRIBUTED_RUN_FLOW.md).

## Architecture at a glance

| Role | Host (today) | Process | Port |
|---|---|---|---|
| Coordinator | master (`desktop-j05412i`) | `mtg_bot serve` (v2 endpoints + heartbeat poller + queue.db) | 5099 |
| Worker | master (`desktop-j05412i`) | `mtg_bot.worker_daemon` (long-lived service) | 5198 |
| Worker | Mac (`greggs-macbook-pro`) | `mtg_bot.worker_daemon` (launchd) | 5198 |
| Worker | Win10 (`desktop-g72aptg`) | `mtg_bot.worker_daemon` (Task Scheduler) | 5198 |
| Orchestrator | master | `mtg_bot iterate` (one-shot CLI) | n/a |
| Training UI | master | `mtg_bot.training_ui` | 5003 |
| Hub dashboard | master | hub `app.py` | 9000 |

All inter-machine traffic is REST over Tailscale; trust = "any IP in
the tailnet."

The coordinator holds **all** stateful artifacts (npzs, weights,
queue.db, runs.db). Workers are stateless: a worker crash + restart
takes <90s for the coordinator to re-queue its in-flight claims and
re-deliver them to surviving workers.

## Cluster state as of 2026-09-23 (read this first)

| Role | Where | How it is started | URL the launcher should use |
|---|---|---|---|
| Coordinator | desktop (Windows-native) | `Start-ScheduledTask MTGBotCoordinator` (or hub entry `mtg_bot_serve`) | `http://100.115.252.110:5099` |
| Worker (desktop) | desktop, 16 workers, CUDA | `Start-ScheduledTask MTGBotWorkerLocal` (or hub entry `mtg_bot_worker_windows`) | `http://100.115.252.110:5198` |
| Worker (Mac) | `greggs-macbook-pro` (100.95.248.116), launchd `com.mtg-bot.worker`, 6 workers, bind `0.0.0.0` | always on; restart with `launchctl kickstart -k gui/$(id -u)/com.mtg-bot.worker` | `http://100.95.248.116:5198` (see Mac reachability below) |

* The WSL2 coordinator / training-UI path is on hold (offline since
  2026-05-13). The hub entries `mtg_bot_serve` (5099) and
  `mtg_bot_worker_windows` (5198) now point at the Windows-native
  commands; `mtg_bot_train_ui_windows` (5103) is the UI to use.
* **Do not start `MTGBotWorker`** (the original task): its
  `--weights-cache-root` points at the live `trained_weights/`
  registry, which crash-loops and corrupts version dirs on Windows.
  `MTGBotWorkerLocal` is the corrected replacement (separate cache
  `~/.mtg_bot_worker_weights`, run-level Limited so it can be edited
  without elevation).
* The coordinator task needs `mtg_bot` importable from
  `.venv-py313` (it does not set `PYTHONPATH`). If it exits with
  result 1 immediately, run
  `.venv-py313/Scripts/python.exe -m pip install --no-deps -e .`.
* **Mac reachability (resolved 2026-09-23):** the Mac had TWO tailscaled
  instances -- Homebrew `tailscaled` (node `greggs-macbook-pro-1`,
  100.77.31.125, ran Tailscale SSH) and Tailscale.app (node
  `greggs-macbook-pro`, 100.95.248.116). With both running, inbound
  TCP to either tailnet IP timed out from the desktop (replies left via
  the other daemon's utun). The Homebrew one was removed
  (`sudo brew services stop tailscale; brew uninstall tailscale`), so
  the Mac is now ONLY `greggs-macbook-pro` / **100.95.248.116**; the
  `-1` node and 100.77.31.125 are dead. The worker daemon binds
  `0.0.0.0`, so the LAN IP 192.168.0.111 also works as a fallback.
* Mac checkout: `~/projects/mtg-bot` on `main`; update with
  `git pull --ff-only origin main && .venv-py313/bin/python -m pip
  install -q -e .` then restart the launchd job. (Its stale May
  shard output was moved to `iterate_data.stale_2026-05/`.)
* **S3 backup of the lineage:** `scripts/s2/backup_to_s3.sh` syncs
  `iterate_data_s2/`, `iterate_data_s2_v1corpus/`, `trained_weights_s2/`,
  `training_progress_s2/`, `ladder_runs/` and `replays_s2/` to
  `s3://mtg-bot-artifacts-630589799985/s2/` (us-east-1, desktop
  `mtg-bot-admin` credentials). Run it after every corpus batch / promoted
  version; restore with the reverse `aws s3 sync`. The flat training store
  (`%TEMP%\mtg_bot_structured_dataset_*`) must stay on local disk (memmap).
* Scalar-schema-v2 lineage (`trained_weights_s2/`): launch via
  `scripts/s2/run_distributed.sh [n]` (config
  `configs/launch/s2.toml`; `DRY_RUN=1` prints the argv). It cannot
  share the coordinator's runs.db with the old lineage until the
  run-label-prefix change lands (old `iter_001_cycle`... rows return
  409 from `/run/start_or_restart`); the wrapper will pass
  `--run-label-prefix s2_` once it does.

## Daily-ops checklist (master)

Run these once when you sit down at the desktop:

1. **Hub dashboard** — start if not already running:
   ```bash
   cd "C:\Users\Gregg Keithley\hub" && python app.py
   ```
   Reachable at [http://localhost:9000](http://localhost:9000) /
   [http://desktop-j05412i:9000](http://desktop-j05412i:9000) over
   Tailscale.

2. **Training UI** — start via the hub or directly:
   ```bash
   .venv-py313/Scripts/python.exe -u -m mtg_bot.training_ui \
       --port 5003 \
       --progress-dir "C:\Users\Gregg Keithley\Documents\Claude\Projects\mtg-bot\training_progress"
   ```
   Reachable at [http://desktop-j05412i:5003](http://desktop-j05412i:5003).

3. **Coordinator** — start `mtg_bot serve` on port 5099. Reads
   `shards_config.json` to learn worker URLs, starts the heartbeat
   poller, registers v2 endpoints.
   ```bash
   .venv-py313/Scripts/python.exe -m mtg_bot.cli serve
   ```

4. **Verify worker liveness.** Each worker's daemon should already
   be running under its native service supervisor (systemd / launchd
   / Task Scheduler). Confirm:
   ```bash
   curl http://greggs-macbook-pro:5198/v2/heartbeat | jq .state
   curl http://desktop-g72aptg:5198/v2/heartbeat | jq .state
   curl http://desktop-j05412i:5198/v2/heartbeat | jq .state
   ```
   Each should return `"IDLE"`. The training UI's per-machine sub-
   cards turn green once the coordinator's heartbeat poller has
   ticked at least once (10s after coordinator start).

## Artifact storage (every production worker MUST set this)

A worker does not POST its `.npz` back to the coordinator any more --
it *drops the blob off* somewhere the coordinator can read, then POSTs
the URI. Where it drops off is decided by the worker's own
`--artifact-storage-uri` flag, baked into its service file.

**The default is `null://`, which throws the artifact away.** It is
test-only. A `null://` worker plays its games, reports them, and the
coordinator's stage view happily counts them (`n_games_done`,
`n_samples`) -- but the report job can't fetch `null://...`, so it
writes an `outcome='upload_failed'` row and no `.npz` ever lands in
`iterate_data*/`. That is exactly what happened on 2026-09-23: 500
games across both daemons, stage view reporting 500 done / ~1M
samples, zero files on disk, `mtg_bot iterate` dying on
`ZeroDivisionError`.

| Machine | `--artifact-storage-uri` | Why |
|---|---|---|
| Desktop worker (same box as the coordinator) | `file:///C:/Users/Gregg Keithley/mtg_bot_artifacts_s2` | Coordinator reads the path directly; no network hop. |
| Mac worker | `http://100.115.252.110:5099` | No shared filesystem. POSTs the bytes to the coordinator's `/v2/artifact/upload`, which writes them locally and hands back a coordinator-local `file://` URI. |
| AWS workers | `s3://<bucket>/<prefix>` | Requires the `[s3]` extra. |
| Tests / throughput smokes only | `null://` | Blobs dropped on the floor. **The launcher now refuses it.** |

Worker launch, desktop:

```bash
.venv-py313/Scripts/python.exe -m mtg_bot.worker_daemon \
    --n-workers 16 --nn-device cuda \
    --weights-cache-root "$HOME/.mtg_bot_worker_weights" \
    --artifact-storage-uri "file:///C:/Users/Gregg Keithley/mtg_bot_artifacts_s2"
```

Worker launch, Mac:

```bash
.venv-py313/bin/python -m mtg_bot.worker_daemon \
    --n-workers 6 --host 0.0.0.0 \
    --artifact-storage-uri http://100.115.252.110:5099
```

Coordinator (the `http://` scheme needs a landing dir; the default is
`<repo-root>/artifact_uploads`):

```bash
.venv-py313/Scripts/python.exe -m mtg_bot.cli serve \
    --iterate-data-dir iterate_data_s2 \
    --artifact-upload-dir "C:\Users\Gregg Keithley\mtg_bot_artifact_uploads"
```

The upload dir is the raw drop-off zone keyed by claim; the report job
rehydrates from there into `--iterate-data-dir` under the training
filenames. **`--iterate-data-dir` on the coordinator must equal
`--data-dir` on `mtg_bot iterate`** -- if they differ, the npzs land
somewhere iterate never globs, which looks identical to the `null://`
failure from iterate's side.

Guardrails added 2026-09-23 (all of them fail the run, none of them
paper over it):

* `/v2/heartbeat` reports `artifact_storage_uri`, and
  `mtg_bot iterate-distributed` refuses to dispatch to a worker
  advertising `null://`. Override with
  `MTG_BOT_ALLOW_NULL_ARTIFACTS=1` only for a throughput smoke whose
  output you intend to discard.
* `GET /v2/stage/<id>` reports `upload_failed` (total and per
  machine). `mtg_bot iterate` treats `upload_failed > 0` -- or a
  self-play stage that yielded 0 samples -- as a hard error and exits
  non-zero with a message naming `--data-dir`, the stage id, and both
  usual causes.
* `mtg_bot <subcommand>` propagates the subcommand's non-zero return
  as its own exit code, so a wrapper script can't read a failed cycle
  as success and relaunch it.

Quick check before a cycle:

```bash
curl -s http://100.115.252.110:5198/v2/heartbeat | jq .artifact_storage_uri
curl -s http://100.95.248.116:5198/v2/heartbeat  | jq .artifact_storage_uri
```

Neither should print `"null://"`.

## Running an iteration

The unified `mtg_bot iterate-distributed` launcher is the canonical
entrypoint. One TOML config + one command -- the launcher pre-
registers the cycle row in `runs.db` (so the UI sees it immediately),
auto-starts the training UI if it's not up, prints a clickable
Tailscale link, then spawns `mtg_bot iterate` as a child subprocess
with the right argv. The cycle row is **guaranteed** to end with a
terminal status (`completed` / `failed` / `killed`) -- no more
silently-stuck "running" rows after a launcher crash / signal /
hard kill.

```bash
mtg_bot iterate-distributed --config configs/launch/iter_021.toml
```

The launcher prints to **stderr** (so it survives stdout redirection)
right after the cycle row lands in runs.db:

```
[launcher] cycle iter_021_cycle started.
Track in UI: http://desktop-j05412i:5103/run/iter_021_cycle
```

### TOML config

See [`configs/launch/iter_TEMPLATE.toml`](../configs/launch/iter_TEMPLATE.toml)
for the canonical template (copy + edit). Four sections, all
optional fields take defaults from `mtg_bot.launcher.config`:

- **`[iter]`** — what training cycle to run: `target_iter` (the
  `iter_NNN` label the cycle_id derives from; the only field
  without a sensible default), `bootstrap_version`, `nodes`,
  `samples`, `games_per_iteration`, `epochs`, `architecture`. The
  launcher hand-merges these into the corresponding `mtg_bot
  iterate` flags. `label_prefix` (default `""`) namespaces every
  generated run label for a SECOND training lineage — see
  "Running a second lineage" below.
- **`[cluster]`** — which workers: `local_only` (true short-circuits
  the AWS fleet; today this MUST be true — Phase B fills the AWS
  path), `master_url` / `mac_url` / `win10_url` (heartbeat targets;
  the launcher refuses to dispatch unless every configured worker's
  `/v2/heartbeat` returns IDLE).
- **`[aws]`** — parsed-but-ignored today; Phase B's fleet manager
  consumes it. Fields: `count`, `instance_type`, `az_fallback`,
  `storage_uri`. The Tailscale auth key the workers join with is
  NOT a TOML field: export `MTG_BOT_TAILSCALE_AUTHKEY=tskey-auth-...`
  in the launcher host's environment before launching with
  `count > 0`; the launcher injects it into the worker user-data
  and refuses to launch without it. (A literal key used to be
  committed in `scripts/aws/user-data.worker.warm.sh`; it was
  removed 2026-09-22 and must be revoked/rotated in the Tailscale
  admin console.)
- **`[ui]`** — `auto_start_training_ui` (best-effort: probe
  `base_url`; if not up, ask the hub on port 9000 to start
  `mtg_bot_train_ui_windows`); `base_url` (defaults to
  `http://desktop-j05412i:5103` per the project's Tailscale-only
  link policy).

### CLI overrides

Any TOML key can be overridden on the command line via
`--<section>.<key> <value>`:

```bash
mtg_bot iterate-distributed --config configs/launch/iter_021.toml \
    --iter.nodes 800 \
    --iter.games-per-iteration 16000 \
    --cluster.local-only
```

Bare bool flags (no value) default to `true` — `--cluster.local-only`
is equivalent to `--cluster.local-only true`. Dashes in keys are
normalised to underscores (`--cluster.local-only` -> `local_only`).
Unknown sections / keys fail loudly with `exit 2` and a clear
message rather than silently dropping into a no-op.

### Other CLI flags

- `--config PATH` — the TOML. Optional only if every required field
  is supplied via overrides.
- `--progress-dir PATH` — root for runs.db + per-cycle ephemeral dirs
  (default `training_progress/`). Forwarded all the way down: launcher
  -> `iterate --progress-dir` -> `train --progress-dir`, so a lineage
  launched with `--progress-dir training_progress_s2` keeps ALL of its
  stage cards (including the trainer's own default progress JSON) out
  of the first lineage's directory.
- `--deck-pool PATH` — forwarded to `iterate --deck-pool`.
- `--queue-url URL` — forwarded to `iterate --queue-url`. Defaults
  to `http://<first_worker_host>:5099`.
- `--dry-run` — resolve config + render shards_config but DON'T
  spawn iterate. Prints the resolved argv. Useful for validating a
  TOML before a live launch.
- `--skip-worker-verify` — skip the heartbeat IDLE check. Use only
  when testing the launcher itself (no live workers) — production
  launches should always verify.
- `--force-resume-from-failed-cycle` — suppress the "cycle row
  already exists" guard when the existing row is in a non-restartable
  state. Reserved for future strict-mode behaviour; today the
  runs.client swallows conflicts as warnings.

### Bounding the training window

`iterate` passes the whole `--data-dir` to the trainer by default, so
training wall-time (and RAM) grows with the accumulated history. Two
knobs bound it, and they are NOT interchangeable:

- `--window-recent N` — the last **N iterations**. Files are grouped
  by the `<prefix>iter_NNN` label in their filename and every file of
  the N highest iteration indices is kept. This is the one you
  normally want.
- `--window-recent-files N` — the **N most recently modified files**
  (the pre-2026-09-24 meaning of `--window-recent`). Use it when the
  binding constraint is a file/row count rather than a cycle count —
  e.g. the desktop's 64 GB RAM ceiling at ~4M rows.

The distinction matters because the distributed pipeline rehydrates
**one `.npz` per GAME** while the local loop writes one per
**iteration**: under the old file-count semantics, `--window-recent 3`
trained a distributed cycle on three games (observed 2026-09-23, 7,278
rows). Files whose names carry no iteration label are always kept, with
a warning naming them.

### Running a second lineage (`label_prefix`)

The coordinator's `runs.db` is global and `run_id` is its primary
key: `/run/start_or_restart` answers HTTP 409 when a row with the
same id already exists in `running` / `completed`. A second training
lineage — its own registry root (e.g. `trained_weights_s2/`) with
`iterate_state.json` restarting at `iterations_completed = 0` —
would therefore try to claim `iter_001_cycle`, which the original
lineage already owns.

Set `[iter].label_prefix` (or `--iter.label-prefix s2_`) to move the
whole lineage into its own namespace. Every generated name picks it
up — cycle id, self-play / train / eval stage ids, the progress-JSON
filenames, the self-play `.npz` basenames and the replay
sub-directories:

```
s2_iter_001_cycle
s2_iter_001_self_play_v1
s2_iter_001_train_v2
s2_iter_001_eval_v2_vs_v1
```

The launcher forwards it to the child as `mtg_bot iterate
--run-label-prefix s2_`. Both sides compute the id through
`mtg_bot.run_labels`, so the row the launcher pre-registers is the
row iterate writes to. A trailing `_` is added if you leave it off.
The default `""` reproduces the original lineage's ids exactly.

Give the second lineage its **own** `--registry-root` and
`--data-dir`. A shared `--data-dir` is rejected at startup: the
foreign-npz guard is lineage-scoped, so the other lineage's
`iter_*.npz` files count as foreign and iterate exits rather than
silently training on mixed data. A shared `--progress-dir` works for
naming (all files are prefixed) but the stale-STOP-sentinel sweep at
the top of each cycle is not lineage-scoped — prefer a separate
progress dir when two lineages run concurrently.

### What happens under the hood

See [`DISTRIBUTED_RUN_FLOW.md`](DISTRIBUTED_RUN_FLOW.md) for the
gritty step-by-step of the iterate subprocess; the launcher's pre-
and post-flight is:

1. Parse TOML + CLI overrides into `LaunchConfig`; validate.
2. (Optional) Auto-start training UI via hub if not responding.
3. Verify every `[cluster]` worker URL's `/v2/heartbeat == IDLE`.
4. Render per-cycle `shards_config.json` under
   `training_progress/launches/<cycle_id>/`.
5. Pre-register the cycle row in `runs.db` (`status=running`).
6. Print the clickable Tailscale link to stderr.
7. Spawn `mtg_bot iterate ...` as a child subprocess + wait.
8. On any exit path (normal, signal, exception, atexit), funnel
   through one finaliser that writes a terminal status to the DB
   row. The runs.db row is **never** left at `running`.

For the REST contract every worker speaks, see
[`DISTRIBUTED_API_v2.md`](DISTRIBUTED_API_v2.md).

## Warm-start corpus: heuristic-guided self-play (2026-09-24)

The AlphaZero loop bootstraps from a random-init net, and an
uninformative evaluator degenerates the PIMC/PUCT search. Ladder
results at the production depth (`nodes 100 / samples 2`):

| Agent | vs `random` |
|---|---|
| `heuristic_pimc` | **182-18** |
| s2 best net | 68-132 |
| s2 `v1` (random init) | 8-16 |

`heuristic_pimc` also beats the nets 191-9, and is ~18x cheaper per
game (measured locally 2026-09-24: 1.68 s/game vs 30.2 s/game, both
at `nodes 100 / samples 2` with 4 worker processes on the desktop).
So the first corpus should be generated by the heuristic, not by the
random-init net.

```bash
# N batches of S2_GAMES_PER_BATCH games each, across the cluster.
S2_GAMES_PER_BATCH=1500 scripts/s2/gen_heuristic_corpus.sh 7
```

or by hand (one batch):

```bash
.venv-py313/Scripts/python.exe -m mtg_bot.cli iterate-distributed   --config configs/launch/s2.toml --iter.target_iter 7   --iter.games_per_iteration 1500   --registry-root trained_weights_s2 --progress-dir training_progress_s2   --deck-pool data/17lands/eoe_decks.json.gz   --queue-url http://100.115.252.110:5099   --data-dir iterate_data_s2 --scalar-schema-version 2   --self-play-evaluator heuristic --corpus-only --corpus-batch 7   --per-game-timeout-sec 900 --seed 1
```

What each new flag does:

* `--self-play-evaluator heuristic` — both seats run PIMC over
  `MtgHeuristicEvaluator`. No weights are fetched anywhere; the npz
  schema is byte-identical to an NN shard (scalar-schema-v2
  structured tokens, `canonical_v2` action encoding, action-history
  tokens, value + visit-count targets, `game_ids`), so
  `mtg_bot train` consumes it unchanged.
* `--corpus-only` — run the self-play stage and stop. No train, no
  eval, no promotion; `iterate_state.json` is left untouched so the
  NN lineage resumes exactly where it was.
* `--corpus-batch N` — **required** when batching across separate
  launcher invocations. `--corpus-only` never advances
  `iterations_completed`, so without it every invocation derives the
  same `stage_id`, the coordinator treats it as the already-drained
  stage, answers 204 to every claim, and the run silently produces no
  games. The wrapper derives `N` from the shards already on disk.

**Self-update every worker first.** A heuristic stage carries empty
`weights` on purpose: a worker on pre-`evaluator` code raises
`missing weights.p0` on every claim and the stage yields zero samples
(`iterate` then exits with the `self_play_yield_error` message). That
is the intended loud failure — the alternative is silently generating
another NN-driven corpus.

Stage / shard names carry `heuristic` instead of a version label
(`s2_iter_007_self_play_heuristic`), so the corpus is distinguishable
on disk and in `runs.db` from the NN lineage's shards.

## Monitoring

| What | Where | Notes |
|---|---|---|
| Per-iter stage progress | Training UI :5003 | reads `runs.db` |
| Coordinator's view of each worker | UI per-machine sub-cards | heartbeat poller's cached `host{}` snapshot |
| Stage drain progress | `GET http://desktop-j05412i:5099/v2/stage/<id>` | live counters |
| Worker daemon logs | `journalctl -u mtg-bot-worker` / `~/Library/Logs/mtg-bot/` / Event Viewer | per-machine |
| Coordinator logs | wherever `mtg_bot serve` was launched | stdout |

## Aborting a run

Multiple options, depending on what you want to stop:

- **Abort the iter loop** (orchestrator):
  - From the training UI: click the cycle's Stop button. The UI writes
    a stop sentinel; the orchestrator's polling loop sees it and exits.
  - From the shell: Ctrl-C the `mtg_bot iterate` process. The orchestrator
    catches SIGINT, POSTs `/v2/stage/<id>/close` for the current stage,
    optionally POSTs `/v2/stop` to each worker, then exits.

- **Stop a single worker** (graceful drain):
  ```bash
  curl -X POST http://greggs-macbook-pro:5198/v2/stop \
       -H 'Content-Type: application/json' \
       -d '{"reason":"manual_drain"}'
  ```
  The daemon transitions RUNNING → STOPPING → IDLE once its in-flight
  game finishes.

- **Force-kill a worker** (when graceful drain isn't viable):
  ```bash
  ssh greggs-macbook-pro 'launchctl unload ~/Library/LaunchAgents/com.mtg-bot.worker.plist'
  # or, no ssh:
  # at the Mac itself: System Preferences > General > Login Items
  ```
  The coordinator notices `/v2/heartbeat` is dead within ~90s, marks
  the worker DEAD, and re-queues its in-flight claims to surviving
  workers.

- **Close a stage early** (e.g. eval-gate watcher decides PASS / FAIL):
  ```bash
  curl -X POST http://desktop-j05412i:5099/v2/stage/<id>/close \
       -H 'Content-Type: application/json' \
       -d '{"reason":"early_stop_pass"}'
  ```
  Subsequent `/v2/claim` calls return 204; in-flight games still
  report normally; status flips to `complete` once drain hits 0.

## What's no longer needed (v2 cutover removed these)

- **SSH key management.** REST over Tailscale; no SSH at all.
- **`git pull` over SSH from the master before each iter.** Each
  worker daemon runs on its own commit; coordinated redeploys go
  through `systemctl restart` etc.
- **`mtg_bot shard` subcommand.** The daemon's Flask handlers
  replaced it entirely.
- **`run_self_play_shard.py` shim** + the SSH-launched orphan
  sweep.
- **`--bundle-url` / `--shard-ssh-timeout-min` flags** on
  `mtg_bot iterate`. The argparser dropped them.

## Related docs

- [`SETUP_DISTRIBUTED.md`](SETUP_DISTRIBUTED.md) — one-time per-
  machine bootstrap.
- [`DISTRIBUTED_API_v2.md`](DISTRIBUTED_API_v2.md) — REST contract.
- [`DISTRIBUTED_RUN_FLOW.md`](DISTRIBUTED_RUN_FLOW.md) — runtime
  walkthrough.
- [`../configs/launch/iter_TEMPLATE.toml`](../configs/launch/iter_TEMPLATE.toml)
  — copy-and-edit launcher config.
- [`../deploy/README.md`](../deploy/README.md) — operator install
  guide.

## Legacy manual flow (deprecated)

**Do not use; left for forensics on pre-launcher iters.**

Pre-launcher (iter_001 through iter_005 era) the operator drove the
cycle by hand:

1. Edit `shards_config.json` in the repo root to list the worker URLs.
2. Run `mtg_bot iterate` directly:
   ```bash
   PYTHONPATH=src .venv-py313/Scripts/python.exe -m mtg_bot.cli iterate \
       --bootstrap-version v6 \
       --shards-config shards_config.json \
       --queue-url http://desktop-j05412i:5099 \
       --games-per-iteration 1000 \
       --eval-games 2000 \
       --acceptance-threshold 0.525
   ```
3. Run the eval-early-stop watcher in a second terminal so eval
   could stop on Wilson 95% CI clearance:
   ```bash
   python scripts/eval_early_stop_watcher.py \
       --alpha 0.025 --min-decisive 30
   ```

The problems this flow had that the launcher fixes:

- Cycle row sometimes stuck at `running` in the UI when iterate
  segfaulted / was hard-killed / the launcher PC rebooted mid-run.
  The launcher's lifecycle ctx mgr guarantees a terminal status.
- Two concurrent launches could trample each other's
  `shards_config.json`. The launcher renders a per-cycle ephemeral
  file under `training_progress/launches/<cycle_id>/`.
- Worker-IDLE pre-flight was a manual `curl` step; the launcher
  refuses to dispatch unless every configured worker reports IDLE.
- No clickable link to the cycle's UI card; the launcher prints one
  to stderr right after the row lands.

Old `iterate` invocations still work (the launcher just composes
the same argv internally), but new operators should use the
launcher unconditionally.
