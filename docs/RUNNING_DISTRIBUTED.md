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
  (default `training_progress/`).
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
