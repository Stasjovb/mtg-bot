# Deploy: mtg-bot worker daemon

Operator guide for getting the mtg-bot worker daemon running on each
machine in the cluster. Companion to `docs/DISTRIBUTED_API_v2.md` (the
wire contract) and `docs/DISTRIBUTED_RUN_FLOW.md` (the runtime walk-
through).

## What's here

| File | OS | Purpose |
|---|---|---|
| `systemd/mtg-bot-worker.service` | Linux | systemd unit |
| `launchd/com.mtg-bot.worker.plist` | macOS | launchd plist |
| `windows/install-mtg-bot-worker.ps1` | Windows | Worker daemon Task Scheduler installer |
| `windows/install-mtg-bot-coordinator.ps1` | Windows (master only) | Coordinator Task Scheduler installer |

Each file is a template with placeholders. Fill them in for the
machine you're deploying on, install via the OS's native service
mechanism, then verify the daemon is up.

## Per-machine prerequisites

1. **Clone the repo** and create a Python 3.13 venv:

   ```bash
   git clone https://github.com/<you>/mtg-bot.git
   cd mtg-bot
   py -3.13 -m venv .venv-py313       # Windows
   python3.13 -m venv .venv-py313     # Linux/macOS
   .venv-py313/Scripts/python -m pip install -e .[dev]   # Windows
   .venv-py313/bin/python -m pip install -e .[dev]       # POSIX
   ```

2. **Install Tailscale and join the tailnet.** The worker daemon
   binds to the machine's tailnet IP so the coordinator can poll it.

   ```bash
   tailscale up
   tailscale ip -4   # note this — it's the daemon's --host
   ```

3. **Pre-stage the deck pool** at `data/17lands/eoe_decks.json.gz`
   (the daemon's default; override via `--deck-pool-path`).

## Linux (systemd)

```bash
# 1. Copy the unit, edit the placeholders.
sudo cp deploy/systemd/mtg-bot-worker.service \
    /etc/systemd/system/mtg-bot-worker.service
sudo $EDITOR /etc/systemd/system/mtg-bot-worker.service
#   replace ${USER}, ${HOME}, ${REPO_ROOT}, ${VENV_PYTHON},
#   ${TAILNET_IP}, ${N_WORKERS}

# 2. Enable + start.
sudo systemctl daemon-reload
sudo systemctl enable mtg-bot-worker
sudo systemctl start mtg-bot-worker

# 3. Verify.
sudo systemctl status mtg-bot-worker
journalctl -u mtg-bot-worker -f
curl http://<tailnet-ip>:5198/v2/heartbeat
```

## macOS (launchd)

```bash
# 1. Copy the plist, edit the placeholders.
cp deploy/launchd/com.mtg-bot.worker.plist ~/Library/LaunchAgents/
$EDITOR ~/Library/LaunchAgents/com.mtg-bot.worker.plist
#   replace {{HOME}}, {{REPO_ROOT}}, {{VENV_PYTHON}}, {{TAILNET_IP}},
#   {{N_WORKERS}}

# 2. Load.
launchctl load -w ~/Library/LaunchAgents/com.mtg-bot.worker.plist

# 3. Verify.
launchctl list | grep mtg-bot
tail -f ~/Library/Logs/mtg-bot/worker.out.log
curl http://<tailnet-ip>:5198/v2/heartbeat
```

## Windows (Task Scheduler)

Run from **elevated** PowerShell (Task Scheduler with SYSTEM principal
needs admin).

### Worker daemon (every Windows machine)

```powershell
cd <repo-root>
.\deploy\windows\install-mtg-bot-worker.ps1 `
  -TailnetIP "100.96.1.7" `
  -NWorkers 4 `
  -RepoRoot "C:\Users\gregg\projects\mtg-bot" `
  -VenvPython "C:\Users\gregg\projects\mtg-bot\.venv-py313\Scripts\python.exe"

# Verify
Get-ScheduledTask -TaskName MTGBotWorker
Get-ScheduledTaskInfo -TaskName MTGBotWorker

# Start now (or reboot)
Start-ScheduledTask -TaskName MTGBotWorker

# Heartbeat smoke check
Invoke-RestMethod -Uri "http://<tailnet-ip>:5198/v2/heartbeat"
```

### Coordinator (master only — one per cluster)

The coordinator runs ONLY on the master. It's the existing
`mtg_bot serve` process extended with the v2 endpoints + heartbeat
poller + queue.db; the install script just wraps it in a
Task-Scheduler-as-SYSTEM entry.

```powershell
cd <repo-root>
.\deploy\windows\install-mtg-bot-coordinator.ps1 `
  -RepoRoot "C:\Users\gregg\projects\mtg-bot" `
  -VenvPython "C:\Users\gregg\projects\mtg-bot\.venv-py313\Scripts\python.exe"

# Verify
Get-ScheduledTask -TaskName MTGBotCoordinator
Get-ScheduledTaskInfo -TaskName MTGBotCoordinator

# Start now
Start-ScheduledTask -TaskName MTGBotCoordinator

# Health check
Invoke-RestMethod -Uri "http://127.0.0.1:5099/v2/healthz"
```

### Cleanup of the cutover-day one-shot smoke task

The cutover-day smoke registered an `MTGBotWorkerSmoke` one-shot
task on Win10 (and possibly the master) to get a daemon running
without elevation. After installing the proper persistent
`MTGBotWorker` task, remove the one-shot:

```powershell
Unregister-ScheduledTask -TaskName MTGBotWorkerSmoke -Confirm:$false
```

## Verify the daemon is up (any OS)

```bash
curl http://<tailnet-ip>:5198/v2/heartbeat | jq .
```

A healthy daemon returns 200 with a body like:

```json
{
  "worker_id": "greggs-macbook-pro",
  "state": "IDLE",
  "current_stage_id": null,
  "games_done": 0,
  "games_claimed_in_flight": 0,
  "last_progress_at": null,
  "error": null,
  "uptime_s": 12.4,
  "process_started_at": "2026-05-15T18:00:00Z",
  "host": {
    "pool_size": 0,
    "active_workers": 0,
    "cpu_percent": 4.2,
    "memory_percent": 38.1,
    "memory_used_gb": 12.2,
    "memory_total_gb": 32.0,
    "load_avg_1m": 0.4
  }
}
```

## Cutover-day playbook

Once each machine in the cluster has a daemon running and ALIVE per
the coordinator's heartbeat poller:

1. **Bring up the coordinator.** On the master:

   ```bash
   cd <mtg-bot>
   .venv-py313/Scripts/python -m mtg_bot.cli serve   # port 5099
   ```

   The v2 blueprint registers automatically; the heartbeat poller
   reads `shards_config.json` on startup.

2. **Update `shards_config.json`** to the URL-only post-cutover
   shape (this is checked into the repo as a reference; copy to the
   master's working directory):

   ```json
   {
     "worker_urls": [
       "http://desktop-j05412i:5198",
       "http://greggs-macbook-pro:5198",
       "http://desktop-g72aptg:5198"
     ]
   }
   ```

3. **Confirm coordinator sees every worker as ALIVE.** The training
   UI's per-machine sub-cards should turn green within ~10s of
   coordinator boot (the heartbeat poller's first tick).

   Or query the coordinator's heartbeat-poller state directly:

   ```bash
   curl http://desktop-j05412i:5099/v2/healthz | jq .
   ```

4. **Run the cutover-day smoke script** before promoting the cluster
   to a real iter:

   ```bash
   PYTHONPATH=src .venv-py313/Scripts/python.exe deploy/smoke-test.py \
       --shards-config shards_config.json \
       --coordinator-url http://desktop-j05412i:5099 \
       --weights-version v6 \
       --games-per-worker 2
   ```

   The script POSTs a tiny synthetic stage (2 games, 32 nodes,
   1 sample) to each worker via the v2 REST contract, polls each
   stage to `complete` (or times out after `--timeout-s`, default
   300s), and reports pass/fail per worker plus a final
   `/v2/heartbeat` snapshot. Exit code is 0 iff every worker passes.

   Re-run after every daemon restart, coordinator restart, and on
   cutover day before promoting the cluster to a real iter.

5. **Run `mtg_bot iterate`** as usual. The orchestrator reads the
   URL list, builds the stage spec, POSTs `/v2/stage/create` on the
   coordinator, POSTs `/v2/start_self_play` on each worker, polls
   the stage to `complete`, then moves on to train + eval.

6. **Stop the cluster** with `systemctl stop`, `launchctl unload`,
   or `Stop-ScheduledTask`. Each daemon's `/v2/stop` endpoint is
   also available for graceful drain on individual workers.

## Worker-owned config

Each daemon's CLI flags are baked into the native service file's
invocation. The orchestrator NEVER overrides these — `n_workers`,
`deck_pool_path`, `weights_cache_root` are decided per-machine. See
`docs/DISTRIBUTED_API_v2.md` "Worker-owned config" section for the
rationale.

| Flag | Default | When to override |
|---|---|---|
| `--host` | `127.0.0.1` | Production: the machine's tailnet IP. |
| `--port` | `5198` | Only if 5198 is taken. |
| `--n-workers` | `cpu_count() - 2` | Tune per host: Mac 8-core → 6; Win10 6-core → 4; master 24-core → 16. |
| `--deck-pool-path` | `data/17lands/eoe_decks.json.gz` | Smoke tests against a small pool. |
| `--weights-cache-root` | `trained_weights` | Shared filesystem deployments where weights live elsewhere. |
| `--worker-id` | hostname | Two daemons on the same box; otherwise leave alone. |
| `--spot-watch` | OFF | **AWS EC2 spot workers only.** See below. |

## AWS EC2 spot workers — `--spot-watch`

EC2 **spot** instances can be reclaimed by AWS with a ~2-minute
warning. By default a reclaimed worker just dies mid-game: its
in-flight claims then sit unreclaimed until the coordinator marks it
`DEAD` (~90s of missed heartbeats) or the slower claim-TTL sweep
fires (1200s default). That ~90s is wasted cluster time on every
spot reclaim.

`--spot-watch` (a worker-owned flag, OFF by default — leave it OFF on
on-prem workers and in tests) starts a daemon-thread poller that
watches the EC2 instance-metadata interruption endpoint (IMDSv2). On
the ~2-minute reclaim warning it triggers **the exact same graceful
drain as `POST /v2/stop`**: the worker stops claiming new games and
finishes/reports (or releases) its in-flight game locally, in
seconds. **Net effect: the ~90s heartbeat-DEAD reclaim lag is
removed from the common spot-reclaim case** — the coordinator gets
the games back almost immediately instead of waiting out the
liveness timeout.

**Enable it on the EC2 service file.** Add the flag to the daemon's
`ExecStart` (systemd is the EC2-Linux deployment vehicle — see the
"Linux (systemd)" section; the shipped
`deploy/systemd/mtg-bot-worker.service` has a commented `--spot-watch`
line ready to uncomment):

```ini
ExecStart=${VENV_PYTHON} -m mtg_bot.worker_daemon \
  --host ${TAILNET_IP} \
  --port 5198 \
  --n-workers ${N_WORKERS} \
  --deck-pool-path ${REPO_ROOT}/data/17lands/eoe_decks.json.gz \
  --weights-cache-root ${REPO_ROOT}/trained_weights \
  --spot-watch
```

If you bootstrap EC2 spot instances via **user-data** that templates
the unit (or runs the daemon directly), append `--spot-watch` to the
same invocation. No other config is needed — IMDSv2 is on by default
on EC2 and the endpoint is link-local; nothing leaves the instance.

### Operational notes / caveats

- **Win here is "stop claiming + faster LOCAL drain", not instant
  coordinator reclaim.** As of this feature the v2 coordinator has
  **no** proactive per-worker "reclaim my claims now" endpoint. A
  game still running when the instance finally vanishes falls back
  to the existing heartbeat / claim-TTL reclaim — same as today,
  just with no *new* claims piled on and the common
  finishes-in-time case fully drained. A coordinator-side
  instant-reclaim endpoint is possible future work (noted in
  `docs/DISTRIBUTED_API_v2.md`), deliberately out of scope here.
- **On-prem / non-AWS workers must NOT set `--spot-watch`.** Off
  AWS there is no IMDS at `169.254.169.254`; the poller would just
  log tolerated transport errors forever (harmless, but pointless
  noise). The flag is OFF by default precisely so this is opt-in.
- **A flaky IMDS call never kills the watcher or the daemon.**
  Transport/parse failures are logged and polling continues; the
  daemon's `/v2/heartbeat` stays responsive throughout. The watcher
  fires its drain **exactly once** and only on a real interruption
  notice — IMDS errors never spuriously drain a healthy worker.
- **Spot reclaim is still a reclaim.** `--spot-watch` makes the
  drain graceful and fast; it does not prevent the instance going
  away. A game that takes longer than AWS's ~2-minute warning to
  finish is still lost on that instance and re-queued by the
  coordinator's existing fallback — `--spot-watch` only guarantees
  no *new* work is claimed once the warning lands.

## Troubleshooting

| Symptom | Probable cause | Fix |
|---|---|---|
| `Connection refused` on `/v2/heartbeat` | daemon not running, or `--host` is `127.0.0.1` and you're hitting the tailnet IP | Check service status; restart with the tailnet IP. |
| Coordinator shows worker as STALE/DEAD | daemon process crashed; supervisor will restart on its own backoff | `journalctl -u mtg-bot-worker -f` / `~/Library/Logs/mtg-bot/worker.err.log` to find the exception. |
| `/v2/start_self_play` 409 `worker_busy` | previous stage didn't drain | `POST /v2/stop` to that worker, or wait for natural drain. |
| Stage stuck at `running` | one worker has a stale claim past its TTL | Coordinator's heartbeat-driven re-queue (~90s) or claim TTL sweep (1200s default) will recover; check coordinator logs. |
