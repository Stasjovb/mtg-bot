"""Inference cost of ``--value-head-input trunk_no_printing``.

The identity-blind value head (see
``mtg_bot.training.structured_model.VALUE_HEAD_INPUT_TRUNK_NO_PRINTING``)
runs a SECOND trunk pass over embeddings with the printing lookups
dropped, so the question the operator actually has is "what does that
cost per NN eval at the shape self-play runs at".

Run it::

    PYTHONIOENCODING=utf-8 PYTHONPATH=src \
      .venv-py313/Scripts/python.exe scripts/bench_value_head_input.py

The production self-play shape is **batch 1 on CPU** (the worker
daemon is CPU-by-design and does not batch across games — see
CLAUDE.md and ``docs/BENCHMARKING_FINDINGS.md`` §4/§2A), so that row
is the one to quote. Results land in
``docs/SEARCH_LIMITATIONS.md`` / ``docs/SCALING_DIAGNOSTICS.md`` D5.

Ratios, not absolutes, are the trustworthy quantity here: the box is
shared and concurrently orchestrated, and both arms pay the same
contention.
"""

from __future__ import annotations

import argparse
import time

import torch

from mtg_bot.training.structured_model import (
    SUPPORTED_VALUE_HEAD_INPUTS,
    StructuredModel,
    StructuredModelConfig,
    make_dummy_batch,
)


def bench_one(
    device: str, mode: str, batch_size: int, seq_len: int, iters: int,
) -> float:
    """Mean forward-pass milliseconds for one routing."""
    cfg = StructuredModelConfig(value_head_input=mode)
    model = StructuredModel(cfg).to(device).eval()
    batch = {
        k: v.to(device)
        for k, v in make_dummy_batch(
            batch_size=batch_size, seq_len=seq_len, config=cfg, seed=0,
        ).items()
    }
    with torch.no_grad():
        for _ in range(10):  # warm up allocator / cuDNN autotune
            model(batch)
        if device == "cuda":
            torch.cuda.synchronize()
        start = time.perf_counter()
        for _ in range(iters):
            model(batch)
        if device == "cuda":
            torch.cuda.synchronize()
        end = time.perf_counter()
    return (end - start) / iters * 1000.0


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iters", type=int, default=60)
    parser.add_argument("--seq-len", type=int, default=64)
    parser.add_argument(
        "--batch-sizes", type=int, nargs="+", default=[1, 16, 256],
    )
    parser.add_argument(
        "--devices", nargs="+", default=None,
        help="Default: cpu, plus cuda when available.",
    )
    args = parser.parse_args(argv)

    devices = args.devices
    if devices is None:
        devices = ["cpu"]
        if torch.cuda.is_available():
            devices.append("cuda")
    # Single-threaded CPU matches the per-worker self-play process.
    torch.set_num_threads(1)
    for device in devices:
        for batch_size in args.batch_sizes:
            timings = {
                mode: bench_one(
                    device, mode, batch_size, args.seq_len, args.iters,
                )
                for mode in SUPPORTED_VALUE_HEAD_INPUTS
            }
            ratio = (
                timings["trunk_no_printing"] / timings["trunk"]
                if timings["trunk"] else float("nan")
            )
            print(
                f"{device:5} B={batch_size:<4} L={args.seq_len}: "
                f"trunk {timings['trunk']:.3f} ms | "
                f"trunk_no_printing "
                f"{timings['trunk_no_printing']:.3f} ms | {ratio:.2f}x"
            )


if __name__ == "__main__":
    main()
