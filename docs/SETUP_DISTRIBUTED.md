# Setting up a distributed mtg-bot cluster (v2)

This is the **one-time per-machine bootstrap** doc. For day-to-day
operations — running iterations, monitoring, aborting — see
[`RUNNING_DISTRIBUTED.md`](RUNNING_DISTRIBUTED.md). For the wire
contract, see [`DISTRIBUTED_API_v2.md`](DISTRIBUTED_API_v2.md).

The cluster is one **coordinator** (the master, `mtg_bot serve` on
port 5099) plus N **workers** (Mac, Win10, future AWS instances —
each running `mtg_bot.worker_daemon` on port 5198 as a long-lived
native service). All traffic is REST over Tailscale; trust =
"any IP in the tailnet."

## High-level per-machine setup

For each worker machine:

1. Install the project: clone the repo + create a Python 3.13 venv +
   `pip install -e .[dev]`.
2. Install Tailscale and join the tailnet.
3. Install the worker daemon as a native service for the OS
   (systemd / launchd / Task Scheduler). The deploy templates in
   [`../deploy/`](../deploy/) cover all three platforms.
4. Edit the master's `shards_config.json` to add this machine's
   tailnet URL.
5. Verify the daemon is up via `curl http://<tailnet-ip>:5198/v2/heartbeat`.

The [`deploy/README.md`](../deploy/README.md) operator guide walks
through each platform in detail. The remainder of this doc covers
the parts that span multiple machines (coordinator setup, the shared
config file, the day-one cutover checklist).

## Coordinator setup (master, one-time)

The coordinator is the existing `mtg_bot serve` process on port 5099,
extended with the v2 endpoints. No new service file — `mtg_bot serve`
runs as a long-lived process on the master and re-uses the existing
port-5099 bind.

```bash
cd <mtg-bot-checkout>
.venv-py313/Scripts/python -m mtg_bot.cli serve   # Windows
.venv-py313/bin/python -m mtg_bot.cli serve       # POSIX
```

On startup the coordinator:

1. Reads `shards_config.json` to learn the worker URLs.
2. Opens the SQLite queue DB at `training_progress/coordinator_state/queue.db`.
3. Starts the `HeartbeatPoller` background thread (polls every 10s).
4. Registers the v2 endpoints on the Flask app.

Startup is order-independent: workers booting before the coordinator
silently retry their first heartbeats every ~30s.

## `shards_config.json` shape (post-cutover)

The file lives at the repo root on the master. Post-cutover shape is
URL-only:

```json
{
  "worker_urls": [
    "http://desktop-j05412i:5198",
    "http://greggs-macbook-pro:5198",
    "http://desktop-g72aptg:5198"
  ]
}
```

Per-worker operational config (`n_workers`, `deck_pool_path`,
`weights_cache_root`, the daemon's listener bind) is NOT in this
file. Each worker daemon owns its own via CLI flags baked into the
native service file — see [`../deploy/README.md`](../deploy/README.md).

The legacy SSH-era shape (`{"shards": [{"host", "user", "repo_path",
...}]}`) and the transitional shape (`{"workers": [{"worker_id",
"worker_url", "n_workers"}]}`) are both rejected by the loader with
a clear migration message.

## Day-one cutover checklist

1. **Stop the old SSH-based iterate.** No more `mtg_bot iterate
   --shards-config ...` runs against the legacy SSH path; that
   subcommand body is gone.
2. **Install the worker daemon on every machine.** See
   [`../deploy/README.md`](../deploy/README.md). Each should reach
   IDLE state and respond to `/v2/heartbeat`.
3. **Update `shards_config.json`** to the URL-only shape (above).
4. **Start the coordinator** (`mtg_bot serve` on the master).
5. **Verify the coordinator sees every worker as ALIVE** — the
   training UI's per-machine sub-cards turn green within ~10s.
6. **Run `mtg_bot iterate`** — the orchestrator reads the URL list,
   POSTs `/v2/stage/create` on the coordinator, POSTs
   `/v2/start_self_play` to each worker, polls `/v2/stage/<id>`
   until `status == "complete"`.

## What you no longer need

The SSH-era setup required several artifacts that the cutover
removes:

- **SSH keys distributed to every remote.** The REST contract is
  trust-on-tailnet; no per-request auth tokens, no per-host SSH
  agents.
- **`scp`-compatible remote paths** matching the master's layout.
  Each daemon writes locally to its own `weights_cache_root`.
- **Code sync via `git pull` over SSH / git-bundle.** Each machine
  runs a long-lived daemon at its current commit; coordinated
  redeploys go through `systemctl restart` etc.
- **`run_self_play_shard.py` and `mtg_bot shard`.** The daemon's
  Flask handlers replace the SSH-launched shard process entirely.

## Troubleshooting

See [`../deploy/README.md`](../deploy/README.md) "Troubleshooting"
section for the symptom → cause → fix table.

## Related docs

- [`DISTRIBUTED_API_v2.md`](DISTRIBUTED_API_v2.md) — REST contract.
- [`DISTRIBUTED_RUN_FLOW.md`](DISTRIBUTED_RUN_FLOW.md) — runtime
  walkthrough of an `mtg_bot iterate` run.
- [`RUNNING_DISTRIBUTED.md`](RUNNING_DISTRIBUTED.md) — day-to-day
  ops.
- [`../deploy/README.md`](../deploy/README.md) — operator install
  guide.
