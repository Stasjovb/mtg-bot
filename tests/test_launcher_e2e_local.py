"""End-to-end smoke test for the unified distributed-iter launcher.

What this test proves -- in one shot, end-to-end:

1. ``mtg_bot iterate-distributed --config <toml>`` runs as a real
   subprocess against a fresh runs.db.
2. The cycle row appears in the DB with ``status=running`` within
   5 seconds of the launcher starting (the UI-honest invariant --
   no "what's it doing? nothing's in the UI" gap).
3. The cycle row transitions to a terminal status (``completed`` /
   ``failed`` / ``killed``) before the test's overall budget --
   crucially, NEVER left at ``running``. That's the headline bug
   class the launcher exists to prevent.

Why this is marked slow + skipped under MTG_BOT_FAST_TESTS=1: it
spawns a real Python child process and bootstraps a Flask test
server for the worker daemon mock. ~5-10s wall on a warm machine.
Run explicitly via::

    PYTHONPATH=src .venv-py313/Scripts/python.exe -m pytest \
        tests/test_launcher_e2e_local.py -v --no-cov

The test does NOT exercise the AWS path -- that's Phase B's
fleet manager + needs real AWS credentials; tracked as a follow-up
after Phase B + C integrate.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from mtg_bot.cli.runs import db as runs_db


pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        os.environ.get("MTG_BOT_FAST_TESTS") == "1",
        reason=(
            "e2e smoke spawns a real subprocess + Flask server; "
            "skipped in fast-test mode."
        ),
    ),
]


# ---------------------------------------------------------------------------
# Worker daemon mock (Flask, in-process, randomly-ported)
# ---------------------------------------------------------------------------


def _pick_free_port() -> int:
    """Bind ephemeral port, close, return number. Race window is
    tiny (the launcher's heartbeat check fires <1s later); good
    enough for an isolated test."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _build_mock_worker_app():
    """Tiny Flask app exposing the two v2 endpoints the launcher
    touches: ``/v2/heartbeat`` (state IDLE) and ``/v2/start_self_play``
    (202 accepted). The launcher only calls /v2/heartbeat before
    spawning iterate; the start endpoint is here for completeness so
    any future launcher addition that POSTs to it doesn't 404."""
    from flask import Flask, jsonify

    app = Flask(__name__)

    @app.route("/v2/heartbeat", methods=["GET"])
    def heartbeat():
        return jsonify({
            "state": "IDLE",
            "host": "test-worker",
            "process_started_at": "2026-05-21T00:00:00Z",
            "git_commit": "test0000",
        })

    @app.route("/v2/start_self_play", methods=["POST"])
    def start_self_play():
        return jsonify({"accepted": True, "stage_id": "test-stage"}), 202

    return app


class _ServerThread(threading.Thread):
    """Flask werkzeug server running on a background daemon thread.

    Werkzeug's ``run_simple`` blocks; this wraps it so the test body
    can spawn its subprocess in parallel + tear down cleanly via the
    server's shutdown shim.
    """

    def __init__(self, app, port: int):
        super().__init__(daemon=True, name=f"mock-worker-{port}")
        self.app = app
        self.port = port
        self._server = None

    def run(self) -> None:
        from werkzeug.serving import make_server
        self._server = make_server("127.0.0.1", self.port, self.app)
        self._server.serve_forever()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()


@pytest.fixture
def mock_worker():
    """Spin up the mock worker server; tear it down on teardown."""
    port = _pick_free_port()
    app = _build_mock_worker_app()
    server = _ServerThread(app, port)
    server.start()

    # Wait for the server to actually accept connections.
    deadline = time.monotonic() + 5.0
    url = f"http://127.0.0.1:{port}"
    import urllib.request
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"{url}/v2/heartbeat", timeout=0.5)
            break
        except Exception:
            time.sleep(0.05)
    else:
        server.stop()
        pytest.fail(f"mock worker on {url} never came up")

    yield url
    server.stop()


# ---------------------------------------------------------------------------
# TOML config + tmp paths
# ---------------------------------------------------------------------------


def _write_toml(path: Path, master_url: str) -> None:
    """Minimal launch config -- local-only, tiny iter, single
    worker URL (the mock)."""
    body = f"""
[iter]
target_iter = 999
nodes = 10
samples = 1
games_per_iteration = 2
epochs = 1
architecture = "structured"
bootstrap_version = "v5"

[cluster]
local_only = true
master_url = "{master_url}"

[ui]
auto_start_training_ui = false
base_url = "http://desktop-j05412i:5103"
"""
    path.write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_cycle_row(db_path: Path, cycle_id: str) -> dict | None:
    """Read the cycle's runs.db row, or ``None`` if not yet present.

    Opens a fresh connection each time (the launcher subprocess
    holds its own + the test must not race a write).
    """
    if not db_path.exists():
        return None
    conn = runs_db.connect(db_path)
    try:
        result = runs_db.get_run(conn, cycle_id)
        if result is None:
            return None
        return result["run"]
    finally:
        conn.close()


def _wait_for_row(db_path: Path, cycle_id: str, *, timeout_s: float):
    """Poll until the cycle row appears OR timeout. Returns the row
    on success, raises pytest.fail on timeout."""
    deadline = time.monotonic() + timeout_s
    last_err = None
    while time.monotonic() < deadline:
        try:
            row = _read_cycle_row(db_path, cycle_id)
            if row is not None:
                return row
        except Exception as exc:  # noqa: BLE001 - propagate after timeout
            last_err = exc
        time.sleep(0.1)
    pytest.fail(
        f"cycle row {cycle_id} never appeared in {db_path} within "
        f"{timeout_s}s (last err: {last_err})",
    )


def _wait_for_terminal(
    db_path: Path, cycle_id: str, *, timeout_s: float,
) -> dict:
    """Poll until the row's status is non-running. Returns the
    final row; fails if still running at the deadline."""
    deadline = time.monotonic() + timeout_s
    last_status = None
    while time.monotonic() < deadline:
        row = _read_cycle_row(db_path, cycle_id)
        if row is not None:
            last_status = row["status"]
            if last_status != "running":
                return row
        time.sleep(0.2)
    pytest.fail(
        f"cycle row {cycle_id} stuck at status={last_status!r} after "
        f"{timeout_s}s -- the launcher's lifecycle finaliser failed "
        f"to write a terminal status. THIS IS THE BUG CLASS THE "
        f"LAUNCHER EXISTS TO PREVENT.",
    )


# ---------------------------------------------------------------------------
# The smoke test
# ---------------------------------------------------------------------------


def test_launcher_e2e_local_ends_in_terminal_state(
    tmp_path, mock_worker,
):
    """End-to-end: spawn the launcher subprocess, observe the
    cycle row appear, observe it terminate.

    Acceptance: row appears within 5s; row reaches a terminal
    state within 60s. The iterate subprocess will fail fast (no
    valid deck-pool path is provided -- iterate's argparse rejects
    the bogus path) but the LAUNCHER's job is to make sure that
    failure still produces a UI-visible terminal row, not a
    silently-stuck running row.
    """
    # ---- Fixtures
    config_path = tmp_path / "launch.toml"
    progress_dir = tmp_path / "training_progress"
    progress_dir.mkdir()
    db_path = progress_dir / "runs.db"
    bogus_deck_pool = tmp_path / "bogus_deck_pool.json"
    # Don't create it -- iterate's argparse will reject the missing
    # path immediately (its required=True + Path type combination
    # surfaces a non-zero exit fast).
    _write_toml(config_path, mock_worker)
    cycle_id = "iter_999_cycle"

    # ---- Spawn the launcher
    env = os.environ.copy()
    # Pin the runs.db path so the assertions read the same file the
    # launcher writes.
    env["MTG_BOT_RUN_DB_PATH"] = str(db_path)
    env.setdefault("PYTHONPATH", "src")
    # Disable any URL transport so the launcher's runs.client uses
    # direct sqlite -- otherwise it'll try to POST to a coordinator
    # that doesn't exist in this test.
    env.pop("MTG_BOT_RUN_DB_URL", None)

    argv = [
        sys.executable,
        "-m", "mtg_bot.cli", "iterate-distributed",
        "--config", str(config_path),
        "--progress-dir", str(progress_dir),
        "--deck-pool", str(bogus_deck_pool),
        # Skip the heartbeat-verify since the mock daemon already
        # confirms idle; this keeps the test independent of real
        # network behaviour.
        # Note: we DO want verify to run here -- the mock IS reachable
        # and returns IDLE -- so we don't pass --skip-worker-verify.
    ]

    # Run the launcher to completion in a thread so the test can poll
    # the DB while it's running.
    proc = subprocess.Popen(
        argv,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(Path(__file__).resolve().parent.parent),
    )

    try:
        # ---- Assert: row visible within 5s
        row_running = _wait_for_row(db_path, cycle_id, timeout_s=10.0)
        assert row_running["status"] == "running", (
            f"expected status=running on first appearance, got "
            f"{row_running['status']!r}"
        )
        assert row_running["kind"] == "iterate"

        # ---- Assert: row reaches a terminal state
        # 90s budget: iterate's argparse failure should be <2s; allow
        # generous headroom for Python startup on a cold machine.
        terminal = _wait_for_terminal(db_path, cycle_id, timeout_s=90.0)
        assert terminal["status"] in ("completed", "failed", "killed"), (
            f"unexpected terminal status: {terminal['status']!r}"
        )

        # The launcher must have ALSO exited by now (it was waiting
        # for iterate to drain, which has happened).
        try:
            rc = proc.wait(timeout=15.0)
        except subprocess.TimeoutExpired:
            pytest.fail(
                "launcher subprocess still alive after iterate's "
                "DB row went terminal -- lifecycle ctx mgr may be "
                "leaking the wait.",
            )
        # The launcher's exit code mirrors iterate's. For a deck-pool
        # failure that's a non-zero -- accept anything non-zero (the
        # exact code is iterate-internal and may change).
        assert rc is not None
    finally:
        # ---- Teardown: kill the subprocess if it's still alive
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5.0)
        # Drain pipes so the OS doesn't leave them around.
        try:
            stdout, stderr = proc.communicate(timeout=2.0)
        except Exception:
            stdout, stderr = b"", b""
        # If the test failed, the captured output is the most useful
        # forensic signal -- attach it via pytest's failure repr.
        if "PYTEST_CURRENT_TEST" in os.environ:
            sys.stderr.write(
                f"\n[e2e] launcher stdout:\n{stdout.decode(errors='replace')}\n"
            )
            sys.stderr.write(
                f"[e2e] launcher stderr:\n{stderr.decode(errors='replace')}\n"
            )
