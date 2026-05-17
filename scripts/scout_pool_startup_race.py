"""Throwaway repro: drive the v2 production self-play runner's
subprocess-pool path at HIGH n-workers against a small synthetic
stage, to reproduce the AWS c7i.8xlarge --n-workers 30 instant-crash.

Mimics ClaimLoopRunner.run's thread fan-out (N claim-loop threads all
dispatching into the shared ProcessPoolExecutor) without the HTTP /
coordinator round-trip, so the subprocess-pool STARTUP behaviour is
isolated and the per-game crashed-traceback (logged by the runner via
log.exception) is visible on local stderr.

Usage:
  PYTHONPATH=src .venv-py313/Scripts/python.exe \
    scripts/scout_pool_startup_race.py --n-workers 30 --n-games 120 \
    --nodes 32 --samples 1
"""
from __future__ import annotations

import argparse
import logging
import threading
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("scout")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-workers", type=int, default=30)
    ap.add_argument("--n-games", type=int, default=120)
    ap.add_argument("--nodes", type=int, default=32)
    ap.add_argument("--samples", type=int, default=1)
    ap.add_argument("--weights-version", default="v6")
    ap.add_argument("--coordinator-url", default="http://127.0.0.1:5099")
    ap.add_argument(
        "--weights-cache-root", default="trained_weights",
        help="Point at an EMPTY dir to repro the cold-cache fetch race.",
    )
    ap.add_argument("--deck-pool-path",
                    default="data/17lands/eoe_decks.json.gz")
    args = ap.parse_args()

    from mtg_bot.worker_daemon_production_runner import (
        build_self_play_runner,
    )

    events: list[tuple[float, str, dict]] = []
    ev_lock = threading.Lock()
    t_start = time.perf_counter()

    def log_event(name: str, payload: dict) -> None:
        with ev_lock:
            events.append((time.perf_counter() - t_start, name, payload))
        if name in ("pool_created", "weights_loaded", "deck_pool_loaded"):
            log.info("EVENT %s %s", name, payload)

    wcr = Path(args.weights_cache_root)
    runner = build_self_play_runner(
        coordinator_url=args.coordinator_url,
        stage_id="scout_race",
        n_workers=args.n_workers,
        weights_cache_root=wcr,
        worker_id="scout",
        log_event=log_event,
        deck_pool_path=args.deck_pool_path,
        use_subprocess_pool=True,
    )

    # setup() creates the ProcessPoolExecutor with max_workers=n_workers.
    runner.setup(
        args.coordinator_url, wcr,
        "self_play", args.n_workers,
    )
    log.info("runner.setup() done; pool n_workers=%d", args.n_workers)

    results: dict[str, int] = {
        "completed": 0, "crashed": 0, "timed_out": 0, "error": 0,
    }
    durations: list[float] = []
    res_lock = threading.Lock()

    def make_claim(game_idx: int) -> dict:
        return {
            "claim_id": f"c{game_idx}",
            "game_idx": game_idx,
            "seed": 1_000_000 + game_idx,
            "deck_indices": [game_idx % 2, (game_idx + 1) % 2],
            "weights": {"p0": args.weights_version,
                        "p1": args.weights_version},
            "nodes": args.nodes,
            "samples": args.samples,
            "per_game_timeout_sec": 120.0,
            "capture_every": 0,
        }

    next_idx = [0]
    idx_lock = threading.Lock()

    def thread_body(tid: int) -> None:
        while True:
            with idx_lock:
                gi = next_idx[0]
                if gi >= args.n_games:
                    return
                next_idx[0] += 1
            try:
                r = runner.play_one_game(make_claim(gi), "scout")
                with res_lock:
                    results[r.outcome] = results.get(r.outcome, 0) + 1
                    durations.append(r.duration_s)
            except Exception as exc:  # noqa: BLE001
                log.exception("thread %d game %d raised: %s", tid, gi, exc)
                with res_lock:
                    results["error"] += 1

    threads = [
        threading.Thread(target=thread_body, args=(i,),
                         name=f"claim-{i}", daemon=True)
        for i in range(args.n_workers)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    runner.teardown()

    durations.sort()
    n = len(durations)
    p50 = durations[n // 2] if n else 0.0
    log.info("=" * 60)
    log.info("RESULTS n_workers=%d n_games=%d", args.n_workers,
             args.n_games)
    log.info("outcomes: %s", results)
    if durations:
        log.info("duration p50=%.3fs min=%.3fs max=%.3fs",
                 p50, durations[0], durations[-1])
        instant = sum(1 for d in durations if d < 1.0)
        log.info("games < 1.0s (instant): %d / %d", instant, n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
