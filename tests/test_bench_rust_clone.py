"""Tests for ``scripts/bench_rust_clone.py``.

The bench itself is a perf measurement, not a correctness check —
these tests cover (a) the bench script's inner loop runs end-to-end
without exploding on the smallest state, (b) the perf numbers are
sane enough to catch a catastrophic regression on the largest state,
(c) ``run_bench`` + ``write_csv`` produces a well-formed CSV with at
least one row per benchmarked state size, and (d) the bench's CSV
contains rows for at least three distinct state sizes.

Skipped when ``mtg_bot_engine`` isn't installed.
"""

from __future__ import annotations

import csv
import importlib.util
import pathlib
import sys

import pytest

pytest.importorskip("mtg_bot_engine")


# Load the bench module by path so the tests don't depend on
# ``scripts/`` being importable as a package.
_BENCH_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "scripts"
    / "bench_rust_clone.py"
)


def _load_bench():
    spec = importlib.util.spec_from_file_location(
        "bench_rust_clone", _BENCH_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("bench_rust_clone", module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def bench():
    return _load_bench()


def test_bench_runs_on_smallest_size(bench):
    """Mini stress test: the bench's inner loop runs end-to-end on the
    smallest state without raising. Uses a tiny iteration count so
    the test stays fast.
    """
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(1, 1, 5)
    total_ns = bench.time_clone_ns(state, n=50)
    assert total_ns > 0


def test_bench_well_under_one_second_per_call_on_largest(bench):
    """Catastrophic perf regression guard: a single ``clone_once()``
    call on the largest benchmarked size must be far under 1 second.
    The current measurement is well under 1us; a 1e6x slowdown would
    still pass this assertion. The only thing it can't is a complete
    hang.
    """
    import mtg_bot_engine

    state = mtg_bot_engine.make_synthetic_state(20, 30, 90)
    # 100 iters keeps the test under a second even if perf cratered
    # by 50x; the threshold below is the real regression guard.
    total_ns = bench.time_clone_ns(state, n=100)
    per_call_seconds = total_ns / 100 / 1e9
    assert per_call_seconds < 1.0, (
        f"clone_once() is taking {per_call_seconds:.3f}s per call "
        f"on the (20, 30, 90) state — catastrophic regression"
    )


def test_run_bench_writes_csv_with_distinct_sizes(bench, tmp_path):
    """End-to-end smoke: ``run_bench`` + ``write_csv`` writes a CSV
    under the given dir with a row per benchmarked state size, and
    the rows cover at least 3 distinct ``(bf_size, hand_size,
    lib_size)`` triples. Use a tiny iteration count so the test
    stays fast — perf-quality numbers aren't the point here, well-
    formedness is.
    """
    rows = bench.run_bench(n=50)
    csv_path = bench.write_csv(rows, tmp_path)
    assert csv_path.exists()
    assert csv_path.parent == tmp_path
    assert csv_path.name.startswith("clone_") and csv_path.name.endswith(
        ".csv"
    )

    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        out_rows = list(reader)

    # One row per benchmarked size.
    assert len(out_rows) == len(bench.SIZES)
    # Required columns are present and populated.
    for row in out_rows:
        assert set(row.keys()) >= {
            "label",
            "bf_size",
            "hand_size",
            "lib_size",
            "us_per_call",
            "iters",
        }
        # ``us_per_call`` should parse as a positive float.
        assert float(row["us_per_call"]) > 0.0
        assert int(row["iters"]) == 50

    distinct_triples = {
        (row["bf_size"], row["hand_size"], row["lib_size"]) for row in out_rows
    }
    assert len(distinct_triples) >= 3, (
        f"expected at least 3 distinct state sizes, got {distinct_triples}"
    )
