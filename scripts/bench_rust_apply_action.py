"""Per-state-size perf bench for the Rust ``GameState.apply_action()``.

Every game tick in ``scripts/parity_smoke.py --mode trajectory`` calls
``state.apply_action(action_dict)`` to advance the state, so this
primitive's per-call cost bounds the 1000-game parity smoke wall-time.
Parallels ``scripts/bench_rust_clone.py``,
``scripts/bench_rust_fingerprint.py``, and
``scripts/bench_rust_legal_decisions.py`` in shape — same SIZES grid,
same warmup convention, same CSV-under-``bench_results/`` output.

We benchmark the cheapest-to-construct, always-legal action —
``{"kind": "pass_priority", "player_id": 0}`` — so the measurement
isolates the *dispatch + primitive mutation* cost. ``pass_priority``
exists on every legal-decisions emission (round 22 of the porting
status) and the dispatch arm in
``rust/src/state_ops_actions.rs::apply_action`` just calls
``self.pass_priority()`` cross-file via ``call_method0``, so this is a
lower bound on apply_action throughput. Other action kinds
(play_land, cast_spell, declare_attackers, ...) add primitive-specific
work on top.

Because ``apply_action`` mutates the state, we clone the source state
before each call so the bench measures *exactly one* apply_action per
loop iter (rather than N-deep state-mutation drift). The reported
``apply_us`` subtracts the per-iter clone overhead measured in a
separate clone-only loop on the same state, giving a clean per-call
number for the apply_action component.

Run from a worktree:
    PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \\
        scripts/bench_rust_apply_action.py

Writes a CSV to ``bench_results/apply_action_<UTC-timestamp>.csv`` with
one row per benchmarked state size; columns: ``label``, ``bf_size``,
``hand_size``, ``lib_size``, ``combined_us``, ``clone_us``,
``apply_us``, ``iters``. Skips with a hint if ``mtg_bot_engine`` isn't
installed yet (run ``maturin develop --release -m rust/Cargo.toml``).
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
# Representative grid for the trajectory walker — mirrors
# ``scripts/bench_rust_clone.py`` so the three steady-state-per-step
# primitives line up across the same state shapes.
SIZES = [
    (1, 1, 5, "(1, 1, 5)"),
    (3, 3, 15, "(3, 3, 15)"),
    (5, 7, 30, "(5, 7, 30)"),
    (10, 15, 60, "(10, 15, 60)"),
    (20, 30, 90, "(20, 30, 90)"),
]

DEFAULT_ITERS = 10_000
WARMUP_ITERS = 200
PLAYER_ID = 0
# Action dict used for every measured call. ``pass_priority`` is the
# cheapest legal action — always emitted by ``legal_decisions``, and
# its apply-side dispatch is a single cross-file ``call_method0``
# into ``state_ops_priority::pass_priority``. Using a fixed dict
# avoids per-iter dict-construction noise.
PASS_PRIORITY_ACTION = {"kind": "pass_priority", "player_id": PLAYER_ID}


def time_clone_plus_apply_ns(state, n: int) -> float:
    """Total wall-clock nanoseconds for ``n`` ``(clone + apply_action)``
    pairs.

    ``apply_action`` mutates state, so we clone before each call to
    keep every measured iter applying to a fresh state. The reported
    metric subtracts the clone-only baseline (see
    ``time_clone_only_ns``) to isolate the apply_action component.

    Uses ``apply_action`` (not a Rust-internal loop variant) so the
    measurement includes PyO3 round-trip cost — that's the cost a
    Python caller (parity_smoke, trajectory walkers) actually pays
    per tick.
    """
    # Warmup — exclude first-touch costs (any lazy caches, code-path
    # warmup). We're benchmarking the steady-state cost.
    for _ in range(WARMUP_ITERS):
        s = state.clone_once()
        s.apply_action(PASS_PRIORITY_ACTION)
    start = time.perf_counter_ns()
    for _ in range(n):
        s = state.clone_once()
        s.apply_action(PASS_PRIORITY_ACTION)
    return time.perf_counter_ns() - start


def time_clone_only_ns(state, n: int) -> float:
    """Total wall-clock nanoseconds for ``n`` ``clone_once()`` calls.

    Same loop shape as ``time_clone_plus_apply_ns`` so the subtraction
    (combined - clone-only) cleanly isolates the apply_action
    component without timer-resolution drift between differently-
    shaped loops.
    """
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
        combined_ns = time_clone_plus_apply_ns(state, n)
        clone_ns = time_clone_only_ns(state, n)
        combined_us = combined_ns / n / 1_000.0
        clone_us = clone_ns / n / 1_000.0
        apply_us = max(0.0, combined_us - clone_us)
        rows.append(
            {
                "label": label,
                "bf_size": bf,
                "hand_size": hand,
                "lib_size": lib,
                "combined_us": combined_us,
                "clone_us": clone_us,
                "apply_us": apply_us,
                "iters": n,
            }
        )
    return rows


def print_table(rows: list[dict], n: int) -> None:
    """Print a small results table to stdout."""
    print(
        f"apply_action perf — N={n} iters per size, "
        f"action={PASS_PRIORITY_ACTION}"
    )
    print()
    print(
        "  size               | clone+apply us | clone us/call | apply_action us"
    )
    print(
        "  -------------------|----------------|---------------|----------------"
    )
    for r in rows:
        print(
            f"  {r['label']:<18} |    {r['combined_us']:7.3f} us  |"
            f"   {r['clone_us']:6.3f} us   |    {r['apply_us']:7.3f} us"
        )


def write_csv(rows: list[dict], out_dir: pathlib.Path) -> pathlib.Path:
    """Write rows as a CSV under ``out_dir``; return the path written.

    Filename: ``apply_action_<UTC-timestamp>.csv``. The dir is created
    if it doesn't exist. Columns: ``label``, ``bf_size``, ``hand_size``,
    ``lib_size``, ``combined_us``, ``clone_us``, ``apply_us``,
    ``iters`` — one row per benchmarked state size.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"apply_action_{stamp}.csv"
    fieldnames = [
        "label",
        "bf_size",
        "hand_size",
        "lib_size",
        "combined_us",
        "clone_us",
        "apply_us",
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
