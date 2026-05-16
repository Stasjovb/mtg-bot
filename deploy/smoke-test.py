"""Cutover-day verification: drive a tiny end-to-end stage against
every worker URL in ``shards_config.json`` and report pass/fail per
worker.

This is an OPERATOR-RUN script, NOT a unit test. It hits real
network endpoints, so it should only be invoked once the worker
daemons + coordinator are running and visible on the tailnet.

Usage::

    PYTHONPATH=src .venv-py313/Scripts/python.exe deploy/smoke-test.py \\
        --shards-config shards_config.json \\
        --coordinator-url http://desktop-j05412i:5099 \\
        --games-per-worker 2

What it does, per worker URL in ``shards_config.json``:

1. ``POST <coordinator>/v2/stage/create`` with a tiny synthetic
   self-play stage (default 2 games, 32 nodes, 1 sample).
2. ``POST <worker>/v2/start_self_play`` with the stage_id +
   coordinator URL.
3. Poll ``GET <coordinator>/v2/stage/<id>`` every 5s for up to
   --timeout-s seconds (default 300) until ``status == "complete"``.
4. Fetch ``GET <worker>/v2/heartbeat`` for a final health snapshot.
5. Report pass / fail per worker; print the heartbeat snapshot.

A worker is "pass" iff its dedicated stage drains to ``complete``
within the timeout. Failures land as ``FAIL`` with the reason
(timeout, HTTP error, /heartbeat unreachable). Exit code is 0 iff
every worker passed.

For the operator: re-run this after every daemon restart, every
coordinator restart, and on cutover day before promoting the cluster
to a real iter.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional


DEFAULT_GAMES_PER_WORKER = 2
DEFAULT_NODES = 32
DEFAULT_SAMPLES = 1
DEFAULT_TIMEOUT_S = 300.0
DEFAULT_POLL_INTERVAL_S = 5.0
DEFAULT_HTTP_TIMEOUT_S = 15.0


def _http_get(url: str, *, timeout: float = DEFAULT_HTTP_TIMEOUT_S):
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, (e.read() or b"")
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        return 0, f"{type(e).__name__}: {e}".encode("utf-8")


def _http_post_json(url: str, payload: dict,
                    *, timeout: float = DEFAULT_HTTP_TIMEOUT_S):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, (e.read() or b"")
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        return 0, f"{type(e).__name__}: {e}".encode("utf-8")


def _load_worker_urls(path: Path) -> list[str]:
    """Read ``shards_config.json`` and return the URL list.

    Mirrors :func:`mtg_bot.distributed_rest_orchestrator.load_worker_urls`
    but kept self-contained so the smoke script can run from a
    minimal env without the project venv (just stdlib)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top-level must be an object")
    if "shards" in data or "workers" in data:
        raise ValueError(
            f"{path}: legacy shards-config shape detected. v2 uses "
            "{'worker_urls': [...]} — see docs/DISTRIBUTED_API_v2.md."
        )
    urls = data.get("worker_urls")
    if not isinstance(urls, list):
        raise ValueError(
            f"{path}: 'worker_urls' must be a list of strings"
        )
    return [u for u in urls if isinstance(u, str) and u]


def _build_stage_spec(stage_id: str, n_games: int,
                       nodes: int, samples: int,
                       weights_version: str) -> dict:
    """Build a tiny self-play stage spec. Two decks per game with
    deterministic indices — the coordinator's stage_create accepts
    any deck_indices the workers can resolve locally."""
    games = []
    for i in range(n_games):
        games.append({
            "game_idx": i,
            "deck_indices": [i % 2, (i + 1) % 2],
            "seed": 1_000_000 + i,
        })
    return {
        "stage_id": stage_id,
        "kind": "self_play",
        "weights": {"p0": weights_version, "p1": weights_version},
        "nodes": int(nodes),
        "samples": int(samples),
        "per_game_timeout_sec": 60.0,
        "capture_every": 0,
        "claim_ttl_seconds": 600,
        "games": games,
    }


def _verify_worker(
    *,
    worker_url: str,
    coordinator_url: str,
    weights_version: str,
    games_per_worker: int,
    nodes: int,
    samples: int,
    timeout_s: float,
    poll_interval_s: float,
) -> dict[str, Any]:
    """Run the 4-step smoke sequence for one worker URL. Returns a
    dict ``{worker_url, status: "pass"|"fail", reason, heartbeat}``.
    """
    short = worker_url.rstrip("/").rsplit("/", 1)[-1] or worker_url
    stage_id = f"smoke_{short}_{int(time.time())}"
    print(f"[smoke] {worker_url}: stage_id={stage_id}")

    # 1. POST /v2/stage/create on the coordinator.
    create_url = coordinator_url.rstrip("/") + "/v2/stage/create"
    spec = _build_stage_spec(
        stage_id, games_per_worker, nodes, samples, weights_version,
    )
    status, body = _http_post_json(create_url, spec)
    if status != 200:
        return {
            "worker_url": worker_url,
            "status": "fail",
            "reason": f"/v2/stage/create returned {status}: {body[:200]!r}",
            "heartbeat": None,
        }

    # 2. POST /v2/start_self_play on the worker.
    start_url = worker_url.rstrip("/") + "/v2/start_self_play"
    status, body = _http_post_json(start_url, {
        "stage_id": stage_id,
        "coordinator_url": coordinator_url,
    })
    if status != 202:
        return {
            "worker_url": worker_url,
            "status": "fail",
            "reason": f"/v2/start_self_play returned {status}: {body[:200]!r}",
            "heartbeat": _fetch_heartbeat(worker_url),
        }

    # 3. Poll the stage to completion.
    stage_url = coordinator_url.rstrip("/") + f"/v2/stage/{stage_id}"
    deadline = time.monotonic() + timeout_s
    last_status: Optional[str] = None
    while True:
        status, body = _http_get(stage_url)
        if status == 200:
            try:
                payload = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError:
                payload = {}
            last_status = payload.get("status")
            done = int(payload.get("n_games_done", 0))
            in_flight = int(payload.get("n_games_in_flight", 0))
            print(
                f"[smoke] {worker_url}: stage_status={last_status} "
                f"done={done} in_flight={in_flight}"
            )
            if last_status == "complete":
                return {
                    "worker_url": worker_url,
                    "status": "pass",
                    "reason": (
                        f"completed: done={payload.get('n_games_done')} "
                        f"crashed={payload.get('crashed')} "
                        f"timed_out={payload.get('timed_out')}"
                    ),
                    "heartbeat": _fetch_heartbeat(worker_url),
                }
        elif status == 404:
            return {
                "worker_url": worker_url,
                "status": "fail",
                "reason": f"/v2/stage/{stage_id} = 404 (stage missing)",
                "heartbeat": _fetch_heartbeat(worker_url),
            }
        if time.monotonic() >= deadline:
            return {
                "worker_url": worker_url,
                "status": "fail",
                "reason": (
                    f"timeout after {timeout_s}s; "
                    f"last_status={last_status!r}"
                ),
                "heartbeat": _fetch_heartbeat(worker_url),
            }
        time.sleep(poll_interval_s)


def _fetch_heartbeat(worker_url: str) -> Optional[dict]:
    status, body = _http_get(
        worker_url.rstrip("/") + "/v2/heartbeat",
    )
    if status != 200:
        return {"error": f"status={status} body={body[:200]!r}"}
    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return {"error": "non-json body"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--shards-config", type=Path,
        default=Path("shards_config.json"),
        help="Path to shards_config.json. Default shards_config.json.",
    )
    parser.add_argument(
        "--coordinator-url", required=True,
        help=(
            "Coordinator base URL (the master's mtg_bot serve, "
            "e.g. http://desktop-j05412i:5099)."
        ),
    )
    parser.add_argument(
        "--weights-version", default="v6",
        help=(
            "Weights label to use for the smoke stage. The version's "
            "weights must be registered in trained_weights/<label>/ on "
            "the coordinator. Default v6."
        ),
    )
    parser.add_argument(
        "--games-per-worker", type=int,
        default=DEFAULT_GAMES_PER_WORKER,
        help=f"Default {DEFAULT_GAMES_PER_WORKER}.",
    )
    parser.add_argument(
        "--nodes", type=int, default=DEFAULT_NODES,
        help=f"MCTS max_nodes (default {DEFAULT_NODES}).",
    )
    parser.add_argument(
        "--samples", type=int, default=DEFAULT_SAMPLES,
        help=f"PIMC samples (default {DEFAULT_SAMPLES}).",
    )
    parser.add_argument(
        "--timeout-s", type=float, default=DEFAULT_TIMEOUT_S,
        help=f"Per-worker stage timeout (default {DEFAULT_TIMEOUT_S}s).",
    )
    parser.add_argument(
        "--poll-interval-s", type=float, default=DEFAULT_POLL_INTERVAL_S,
        help=(
            f"Stage-poll interval (default {DEFAULT_POLL_INTERVAL_S}s)."
        ),
    )
    args = parser.parse_args(argv)

    print(f"[smoke] loading {args.shards_config}")
    try:
        worker_urls = _load_worker_urls(args.shards_config)
    except (OSError, ValueError) as e:
        print(f"[smoke] FATAL: {e}", file=sys.stderr)
        return 2
    if not worker_urls:
        print(
            f"[smoke] FATAL: {args.shards_config} has zero worker_urls",
            file=sys.stderr,
        )
        return 2
    print(f"[smoke] {len(worker_urls)} workers: {worker_urls}")
    print(f"[smoke] coordinator: {args.coordinator_url}")

    results: list[dict] = []
    for worker_url in worker_urls:
        result = _verify_worker(
            worker_url=worker_url,
            coordinator_url=args.coordinator_url,
            weights_version=args.weights_version,
            games_per_worker=args.games_per_worker,
            nodes=args.nodes,
            samples=args.samples,
            timeout_s=args.timeout_s,
            poll_interval_s=args.poll_interval_s,
        )
        results.append(result)

    # Summary table.
    print()
    print("=" * 70)
    print(f"{'WORKER':<40} {'STATUS':<6} REASON")
    print("-" * 70)
    n_pass = 0
    for r in results:
        if r["status"] == "pass":
            n_pass += 1
        print(f"{r['worker_url']:<40} {r['status']:<6} {r['reason']}")
    print("=" * 70)
    print(f"[smoke] result: {n_pass}/{len(results)} workers passed")
    print()

    # Heartbeat dump.
    for r in results:
        hb = r["heartbeat"]
        if hb is None:
            continue
        print(f"[smoke] heartbeat {r['worker_url']}:")
        print(json.dumps(hb, indent=2, default=str))

    return 0 if n_pass == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
