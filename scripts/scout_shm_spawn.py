"""Scout: can the SHM substrate (torch share_memory_, mp.Queue, mp.Event)
actually work on Windows with spawn start method?

Throwaway diagnostic — not for production. Tests the simplest possible
substrate: parent creates shared tensor + queue + event, spawns a child
that reads tensor, signals event, parent reads back."""

from __future__ import annotations

import multiprocessing as mp
import sys
import time

import torch


def _child(t, q, ev, idx):
    """Worker reads from shared tensor, writes back, signals event."""
    val = float(t[idx, 0].item())
    print(f"  [child] tensor[{idx},0] = {val}", flush=True)
    t[idx, 0] = val * 10 + idx
    q.put(("done", idx, val))
    ev.set()
    print(f"  [child] event set, exiting", flush=True)


def main() -> int:
    print(f"platform: {sys.platform}", flush=True)
    print(f"start methods: {mp.get_all_start_methods()}", flush=True)
    print(f"default ctx: {mp.get_start_method(allow_none=True)}", flush=True)

    ctx = mp.get_context("spawn")
    print(f"using ctx: {ctx}", flush=True)

    t = torch.zeros(4, 4, dtype=torch.float32).share_memory_()
    for i in range(4):
        t[i, 0] = float(i + 1) * 1.5
    print(f"parent tensor pre-spawn: {t[:, 0].tolist()}", flush=True)

    q: "mp.Queue[tuple]" = ctx.Queue()
    ev = ctx.Event()

    p = ctx.Process(target=_child, args=(t, q, ev, 2), daemon=True)
    p.start()
    print(f"parent started child pid {p.pid}", flush=True)

    if not ev.wait(timeout=30):
        print("FAIL: event not set within 30s", flush=True)
        return 1
    print(f"parent saw event", flush=True)

    msg = q.get(timeout=5)
    print(f"parent got queue msg: {msg}", flush=True)

    p.join(timeout=10)
    print(f"parent tensor post-join: {t[:, 0].tolist()}", flush=True)
    # Child wrote val * 10 + idx where val = parent's pre-spawn t[idx,0] = (idx+1)*1.5
    # For idx=2: val=4.5, expected = 4.5 * 10 + 2 = 47.0
    expected = 47.0
    actual = t[2, 0].item()
    if abs(actual - expected) < 1e-6:
        print(f"PASS: shared-memory write-through visible from parent (got {actual})", flush=True)
        return 0
    else:
        print(f"FAIL: expected {expected}, got {actual}", flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
