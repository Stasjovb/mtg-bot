"""Test the ``scripts/generate_training_data.py`` CLI surface.

Specifically: that ``--hang-dump-dir`` is recognized and threaded
through. The triage workflow needs this flag to capture
faulthandler traceback dumps when a worker timeout fires.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "generate_training_data.py"


def _run_help() -> str:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_REPO_ROOT / "src")
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--help"],
        capture_output=True, text=True, env=env, check=True,
    )
    return proc.stdout


def test_hang_dump_dir_flag_in_help():
    out = _run_help()
    assert "--hang-dump-dir" in out, (
        "expected --hang-dump-dir in CLI --help output"
    )


def test_per_game_timeout_flag_in_help():
    # Sanity: pre-existing flag still present (regression guard for
    # the edit that added --hang-dump-dir).
    out = _run_help()
    assert "--per-game-timeout-sec" in out
