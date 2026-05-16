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

```bash
PYTHONPATH=src .venv-py313/Scripts/python.exe -m mtg_bot.cli iterate \
    --bootstrap-version v6 \
    --shards-config shards_config.json \
    --queue-url http://desktop-j05412i:5099 \
    --games-per-iteration 1000 \
    --eval-games 2000 \
    --acceptance-threshold 0.525
```

What happens (see [`DISTRIBUTED_RUN_FLOW.md`](DISTRIBUTED_RUN_FLOW.md)
for the gritty step-by-step):

1. Orchestrator reads `shards_config.json` for the worker URL list.
2. Orchestrator POSTs `/v2/stage/create` on the coordinator with the
   self-play stage spec (1000 games, deck indices, seeds).
3. Orchestrator POSTs `/v2/start_self_play` to every worker URL in
   parallel. Each worker accepts (202) and starts pulling games via
   `/v2/claim`.
4. Orchestrator polls `GET /v2/stage/<id>` every 5s until
   `status == "complete"`.
5. Aggregates npzs from `iterate_data/` (each worker streamed them
   back via `/v2/report_result` multipart) and runs `mtg_bot train`
   in-process on the master.
6. Builds an eval stage spec, POSTs `/v2/stage/create`, POSTs
   `/v2/start_eval` to each worker, polls until complete.
7. Reads `wins_new` / `wins_old` off the final `GET /v2/stage/<id>`,
   applies the 0.525 gate, promotes or keeps best version.

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
- [`../deploy/README.md`](../deploy/README.md) — operator install
  guide.
