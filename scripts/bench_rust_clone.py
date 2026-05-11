"""Per-state-size perf bench for the Rust ``GameState.clone_once()``.

Clone throughput is parity-load-bearing because the cross-engine
trajectory walk (and any future lookahead-search built on the Rust
engine) does heavy cloning — one per decision branch. ``clone_once()``
is conceptually an ``Arc`` refcount bump on every zone vector, so the
per-call cost should be roughly flat across state sizes; this bench
makes that assumption testable. Parallels
``scripts/bench_rust_fingerprint.py`` and
``scripts/bench_rust_legal_decisions.py`` in shape.

Run from a worktree:
    PYTHONPATH=src .venv-py313/Scripts/python.exe \\
        scripts/bench_rust_clone.py

Writes a CSV to ``bench_results/clone_<UTC-timestamp>.csv`` with one
row per benchmarked state size; columns: ``label``, ``bf_size``,
``hand_size``, ``lib_size``, ``us_per_call``, ``iters``. Skips with
a hint if ``mtg_bot_engine`` isn't installed yet (run
``maturin develop --release -m rust/Cargo.toml``).
"""

from __future__ import annotations

import csv
import datetime as _dt
import pathlib
import time

try:
    import mtg_bot_engine
except ImportError:
    mtg_bot_engine = None


# (bf_per_side, hand_per_side, lib_per_side, label)
# Representative grid for the trajectory walker — smallest is a
# near-empty state, largest is an end-game-ish board with deep stacks
# in every zone. Same shape convention as the sibling bench scripts.
SIZES = [
    (1, 1, 5, "(1, 1, 5)"),
    (3, 3, 15, "(3, 3, 15)"),
    (5, 7, 30, "(5, 7, 30)"),
    (10, 15, 60, "(10, 15, 60)"),
    (20, 30, 90, "(20, 30, 90)"),
]

DEFAULT_ITERS = 10_000
WARMUP_ITERS = 200


def time_clone_ns(state, n: int) -> float:
    """Total wall-clock nanoseconds for ``n`` ``clone_once()`` calls.

    Uses ``clone_once()`` (not ``clone_n_times_micros``) so the
    measurement includes the PyO3 round-trip cost — that's the cost a
    Python caller (parity_smoke, trajectory walkers) actually pays per
    branch. The Rust-internal loop variant would understate cost for
    callers that hop the boundary on every clone.
    """
    # Warmup — exclude first-touch costs (any lazy caches, code-path
    # warmup). We're benchmarking the steady-state cost.
    for _ in range(WARMUP_ITERS):
        state.clone_once()
    start = time.perf_counter_ns()
    for _ in range(n):
        state.clone_once()
    return time.perf_counter_ns() - start


def run_bench(n: int = DEFAULT_ITERS) -> list[dict]:
    """Run the bench and return a list of per-size result rows."""
    if mtg_bot_engine is None:
        return []

    rows: list[dict] = []
    for bf, hand, lib, label in SIZES:
        state = mtg_bot_engine.make_synthetic_state(bf, hand, lib)
        total_ns = time_clone_ns(state, n)
        us_per_call = total_ns / n / 1_000.0
        rows.append(
            {
                "label": label,
                "bf_size": bf,
                "hand_size": hand,
                "lib_size": lib,
                "us_per_call": us_per_call,
                "iters": n,
            }
        )
    return rows


def print_table(rows: list[dict], n: int) -> None:
    """Print a small results table to stdout."""
    print(f"clone_once perf — N={n} iters per size")
    print()
    print("  size               | clone us/call")
    print("  -------------------|---------------")
    for r in rows:
        print(f"  {r['label']:<18} |   {r['us_per_call']:7.3f} us")


def write_csv(rows: list[dict], out_dir: pathlib.Path) -> pathlib.Path:
    """Write rows as a CSV under ``out_dir``; return the path written.

    Filename: ``clone_<UTC-timestamp>.csv``. The dir is created if it
    doesn't exist. Columns are ``label``, ``bf_size``, ``hand_size``,
    ``lib_size``, ``us_per_call``, ``iters`` — one row per benchmarked
    state size.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"clone_{stamp}.csv"
    fieldnames = [
        "label",
        "bf_size",
        "hand_size",
        "lib_size",
        "us_per_call",
        "iters",
    ]
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    return out_path


def main() -> None:
    if mtg_bot_engine is None:
        print(
            "rust engine: not installed — run "
            "`maturin develop --release -m rust/Cargo.toml`"
        )
        return

    print(f"Rust engine version: {mtg_bot_engine.__version__}")
    print()
    rows = run_bench(DEFAULT_ITERS)
    print_table(rows, DEFAULT_ITERS)
    # Default output dir is repo-relative ``bench_results/`` so the
    # bench writes alongside the other bench artifacts in this dir.
    out_dir = pathlib.Path(__file__).resolve().parents[1] / "bench_results"
    csv_path = write_csv(rows, out_dir)
    print()
    print(f"wrote: {csv_path}")


if __name__ == "__main__":
    main()
