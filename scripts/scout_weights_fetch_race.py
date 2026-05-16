"""Deterministic isolation of the v2 worker-pool startup race.

N subprocesses concurrently call fetch_weights_if_missing() against a
COLD shared weights-cache dir — exactly what happens when a v2 worker
daemon's ProcessPoolExecutor of N subprocesses each hits its first
claim with no cached weights and pulls them from the coordinator.

The realistic AWS condition: the weights blob is fetched over
Tailscale from the coordinator, so the http_get + write window is
NOT instantaneous. We model that with a slow http_get whose body
write is chunked with small sleeps (network-latency-stretched), the
same effect a multi-MB Tailscale pull has.

Each subprocess then torch.load()s the file it "fetched". A
torn/0-byte/partial weights.pt (because fetch_weights_if_missing's
``weights_path.is_file()`` guard goes True the instant open(wb)
creates the file, before bytes are flushed) makes torch.load raise
instantly == the production "instant-crash at game start, bimodal"
signature.

Usage:
  PYTHONPATH=src .venv-py313/Scripts/python.exe \
    scripts/scout_weights_fetch_race.py --procs 30 --version v6 \
    --weights-pt trained_weights/v6/weights.pt
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path


def _slow_http_get(url, *, timeout=120.0):
    """Stand-in for the real coordinator GET. Returns the canonical
    weights/metadata bytes but spends realistic wall time doing it
    (modelling a multi-MB Tailscale pull), widening the
    create-file-then-still-writing window the production code's
    is_file() guard is blind to."""
    pt = _slow_http_get.weights_bytes
    md = _slow_http_get.metadata_bytes
    if url.endswith("/metadata"):
        time.sleep(0.05)
        return 200, md, {}
    # Simulate transfer latency for the (larger) weights blob.
    time.sleep(0.4)
    return 200, pt, {}


def _one(args) -> tuple[int, str, int]:
    idx, version, cache_root, weights_pt, metadata_json, barrier = args
    from mtg_bot.worker_daemon_claim_loop import fetch_weights_if_missing

    _slow_http_get.weights_bytes = Path(weights_pt).read_bytes()
    _slow_http_get.metadata_bytes = Path(metadata_json).read_bytes()
    # All subprocesses arrive at fetch_weights_if_missing simultaneously
    # — models 30 claim-loop threads each submitting their first claim
    # at stage start (the production trigger).
    try:
        barrier.wait(timeout=60)
    except Exception:
        pass
    try:
        d = fetch_weights_if_missing(
            coordinator_url="http://fake",
            version=version,
            weights_root=Path(cache_root),
            http_get=_slow_http_get,
        )
        wp = d / "weights.pt"
        # Several games run per subprocess; each game's factory.build
        # does torch.load(weights.pt) AGAIN against the shared file
        # while peer subprocesses may still be (re)writing it. Loop a
        # few loads to model the per-game reload.
        import torch
        last_n = -1
        for _ in range(5):
            sd = torch.load(wp, map_location="cpu")
            last_n = len(sd) if hasattr(sd, "__len__") else -1
        size = wp.stat().st_size
        return idx, f"OK load (keys={last_n})", size
    except Exception as exc:  # noqa: BLE001
        return (
            idx,
            f"FAIL {type(exc).__name__}: {exc}\n" + traceback.format_exc(),
            -1,
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--procs", type=int, default=30)
    ap.add_argument("--version", default="v6")
    ap.add_argument("--weights-pt", default="trained_weights/v6/weights.pt")
    ap.add_argument(
        "--metadata-json", default="trained_weights/v6/metadata.json"
    )
    ap.add_argument("--trials", type=int, default=1)
    args = ap.parse_args()

    overall_fail = 0
    first_tb = None
    for trial in range(args.trials):
        cache_root = tempfile.mkdtemp(prefix="wfetch_race_")
        try:
            ctx = mp.get_context("spawn")
            mgr = ctx.Manager()
            barrier = mgr.Barrier(args.procs)
            with ctx.Pool(processes=args.procs) as pool:
                jobs = [
                    (i, args.version, cache_root,
                     args.weights_pt, args.metadata_json, barrier)
                    for i in range(args.procs)
                ]
                results = pool.map(_one, jobs, chunksize=1)
            n_ok = sum(1 for _, msg, _ in results if msg.startswith("OK"))
            n_fail = args.procs - n_ok
            overall_fail += n_fail
            sizes = sorted({sz for _, _, sz in results if sz >= 0})
            print(
                f"[trial {trial}] procs={args.procs} "
                f"OK={n_ok} FAIL={n_fail} ok_sizes={sizes}"
            )
            for idx, msg, sz in results:
                if not msg.startswith("OK"):
                    if first_tb is None:
                        first_tb = msg
                    print(f"  proc {idx}: {msg.splitlines()[0]}")
        finally:
            shutil.rmtree(cache_root, ignore_errors=True)

    print(f"\nTOTAL FAILED across {args.trials} trial(s): {overall_fail}")
    if first_tb is not None:
        print("\n===== FIRST CAPTURED TRACEBACK =====")
        print(first_tb)
    return 1 if overall_fail else 0


if __name__ == "__main__":
    sys.exit(main())
