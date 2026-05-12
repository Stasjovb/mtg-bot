"""Scout: can we drive a ProcessPoolExecutor with a SHM handle via spawn
on Windows, using `initializer` to install the handle in each worker?

Mirrors the production wire-up shape used in distributed.py."""

from __future__ import annotations

import concurrent.futures as cf
import dataclasses
import multiprocessing as mp
import sys
import time
from typing import Any

import torch


@dataclasses.dataclass
class Handle:
    free_slots: "mp.Queue[int]"
    request_queue: "mp.Queue[int]"
    response_events: list[Any]
    tensor: torch.Tensor
    n_slots: int


_WORKER_HANDLE: Handle | None = None


def set_worker_handle(h: Handle) -> None:
    global _WORKER_HANDLE
    _WORKER_HANDLE = h
    print(
        f"  [worker {mp.current_process().pid}] handle installed, "
        f"tensor shape={tuple(h.tensor.shape)}",
        flush=True,
    )


def worker_task(input_val: float) -> float:
    """Simulate a single NN eval: acquire slot, write input, wait, read."""
    h = _WORKER_HANDLE
    assert h is not None
    slot = h.free_slots.get(timeout=5)
    try:
        h.tensor[slot, 0] = input_val
        h.request_queue.put(slot)
        if not h.response_events[slot].wait(timeout=10):
            return -999.0
        h.response_events[slot].clear()
        out = float(h.tensor[slot, 1].item())
        return out
    finally:
        h.free_slots.put(slot)


def dispatch_loop(h: Handle, stop_evt) -> None:
    """Mini-dispatcher: read slot, compute output = input * 2 + 1, signal."""
    while not stop_evt.is_set():
        try:
            slot = h.request_queue.get(timeout=0.2)
        except Exception:
            continue
        if slot == -1:
            return
        val = float(h.tensor[slot, 0].item())
        h.tensor[slot, 1] = val * 2 + 1
        h.response_events[slot].set()


def main() -> int:
    n_slots = 4
    n_workers = 3
    ctx = mp.get_context("spawn")

    t = torch.zeros(n_slots, 2, dtype=torch.float32).share_memory_()
    free_slots = ctx.Queue()
    for i in range(n_slots):
        free_slots.put(i)
    request_queue = ctx.Queue()
    response_events = [ctx.Event() for _ in range(n_slots)]

    h = Handle(
        free_slots=free_slots,
        request_queue=request_queue,
        response_events=response_events,
        tensor=t,
        n_slots=n_slots,
    )

    # Dispatcher runs in the parent process (a thread suffices).
    import threading
    stop_evt = threading.Event()
    dispatch_thread = threading.Thread(
        target=dispatch_loop, args=(h, stop_evt), daemon=True,
    )
    dispatch_thread.start()
    print(f"[parent] dispatcher started", flush=True)

    inputs = [3.0, 7.5, 1.0, 12.0, 99.0, -5.5, 0.0]
    with cf.ProcessPoolExecutor(
        max_workers=n_workers,
        mp_context=ctx,
        initializer=set_worker_handle,
        initargs=(h,),
    ) as exe:
        futs = [exe.submit(worker_task, v) for v in inputs]
        results = [f.result(timeout=30) for f in futs]

    print(f"[parent] inputs:  {inputs}", flush=True)
    print(f"[parent] outputs: {results}", flush=True)
    expected = [v * 2 + 1 for v in inputs]
    print(f"[parent] expect:  {expected}", flush=True)

    stop_evt.set()
    request_queue.put(-1)
    dispatch_thread.join(timeout=3)

    if all(abs(r - e) < 1e-5 for r, e in zip(results, expected)):
        print("PASS: SHM substrate works over spawn on Windows", flush=True)
        return 0
    print("FAIL: outputs did not match expected", flush=True)
    return 2


if __name__ == "__main__":
    sys.exit(main())
