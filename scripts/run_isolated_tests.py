"""Run tests marked ``isolated`` in their own pytest invocation.

Default ``pytest tests/`` skips these (they're sensitive to accumulated
interpreter state from preceding tests — typically C-level recursion
flakes in deepcopy or MCTS selection). Each isolated test gets a clean
pytest process here, which makes them deterministic.

Coverage is disabled because this script is meant for fast perf and
flake-isolated checks, not coverage tracking.

Usage:
    .venv/Scripts/python.exe scripts/run_isolated_tests.py [pytest-args...]
"""

from __future__ import annotations

import subprocess
import sys


def main(argv: list[str]) -> int:
    cmd = [
        sys.executable, "-m", "pytest",
        "-m", "isolated",
        "--no-cov",
        "--override-ini=addopts=",
        *argv,
    ]
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
