"""Run pytest in parallel via pytest-xdist with a retry on transient
crashes.

Two responsibilities:

1. **Default to parallel** (``-n 8``). On a typical multi-core
   machine that's a ~3-4x speedup vs sequential, with stable
   coverage. ``-n auto`` (= one worker per logical CPU, often
   32 on a developer box) was unstable here — coverage tracing
   plus high worker count crashed individual workers (xdist
   ``KeyError: <WorkerController gw3>``). Eight is the sweet
   spot: max speedup before flakes.

   Override with ``MTG_BOT_PYTEST_WORKERS=N`` (any value
   accepted by ``-n``, including ``auto`` or ``0``). ``0``
   means run sequentially (no ``-n`` flag).

   Override with explicit ``-n`` in argv to win over both.

2. **Retry on transient crash.** Python 3.13 + coverage.py
   intermittently corrupt state during the simulation sweep
   tests. Retried once on:
       - Access violation (process segfaults, exit code 139 or
         3221225477)
       - Pytest INTERNALERROR (tb_lineno is None after trace
         corruption)
       - A sweep-test assertion failure (game state went wrong
         under tracing, but the same test passes without
         coverage)

   None reproducible in isolation. A single rerun almost
   always succeeds. Real test failures fail consistently, so
   one retry distinguishes transient-crash from real-failure
   without hiding bugs.

Usage:
    .venv/Scripts/python.exe scripts/run_tests.py [pytest-args...]
"""

from __future__ import annotations

import os
import subprocess
import sys

# Process-level crash codes (always retry).
_CRASH_EXIT_CODES = {
    139,           # Linux / MSYS bash: SIGSEGV
    -1073741819,   # Windows 0xC0000005 as signed int
    3221225477,    # Windows 0xC0000005 STATUS_ACCESS_VIOLATION
}

# Substrings in captured output that point at the coverage flake rather
# than a real test failure. If we see one of these, retry even on a
# plain exit-1 (which pytest uses for both crashes it caught and for
# ordinary test failures).
_TRANSIENT_MARKERS = (
    "Windows fatal exception: access violation",
    "INTERNALERROR>",
    "TypeError: unsupported operand type(s) for -: 'NoneType' and 'int'",
    # The sweep tests in these files pass in isolation but occasionally fail
    # as an assertion under coverage — same Python 3.13 bug, different symptom.
    "tests/test_simulation_coverage.py::",
    "tests/test_coverage_catchup_ss.py::test_broader_simulation_sweep",
    "tests\\test_simulation_coverage.py::",
    "tests\\test_coverage_catchup_ss.py::test_broader_simulation_sweep",
)


def _is_transient(code: int, output: str) -> bool:
    if code in _CRASH_EXIT_CODES:
        return True
    return any(m in output for m in _TRANSIENT_MARKERS)


_DEFAULT_WORKERS = "8"


def _resolve_workers(argv: list[str]) -> str | None:
    """Return the worker count to use, or None for sequential.

    Precedence:
    1. Explicit ``-n`` in argv: respected as-is (caller wins).
    2. ``MTG_BOT_PYTEST_WORKERS`` env var: ``"0"`` for sequential,
       any other string passed through to ``-n``.
    3. Default: ``-n 8``.
    """
    if any(a == "-n" or a.startswith("-n") for a in argv):
        return None
    override = os.environ.get("MTG_BOT_PYTEST_WORKERS")
    if override is not None:
        if override == "0":
            return None
        return override
    return _DEFAULT_WORKERS


def main(argv: list[str]) -> int:
    workers = _resolve_workers(argv)
    extra: list[str] = []
    if workers is not None:
        extra = ["-n", workers]
    cmd = [sys.executable, "-m", "pytest", *extra, *argv]
    last_output = ""
    for attempt in range(2):
        result = subprocess.run(cmd, capture_output=True, text=True)
        # Mirror output to our stdout/stderr in real observable order.
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        combined = result.stdout + result.stderr
        if result.returncode == 0:
            return 0
        if attempt == 0 and _is_transient(result.returncode, combined):
            print(
                f"[run_tests] transient failure (exit {result.returncode}); "
                "retrying once",
                file=sys.stderr,
            )
            last_output = combined
            continue
        return result.returncode
    print("[run_tests] transient failure persisted across two runs — giving up",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
