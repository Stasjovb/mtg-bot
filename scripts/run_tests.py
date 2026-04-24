"""Run pytest with a retry when Python 3.13 + coverage hits its known crash.

There is an intermittent bug where Python 3.13 + coverage.py corrupt state
during the simulation sweep tests. It manifests as any of:

    - Access violation (process segfaults, exit code 139 or 3221225477)
    - Pytest INTERNALERROR (tb_lineno is None after trace corruption)
    - A sweep-test assertion failure (game state went wrong under tracing,
      but the same test passes without coverage)

All three are non-deterministic and not reproducible in isolation with a
minimal tracer. A single rerun almost always succeeds. Real test failures
fail consistently, so one retry is enough to distinguish transient-crash
from real-failure without hiding bugs.

Usage:
    .venv/Scripts/python.exe scripts/run_tests.py [pytest-args...]
"""

from __future__ import annotations

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


def main(argv: list[str]) -> int:
    cmd = [sys.executable, "-m", "pytest", *argv]
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
