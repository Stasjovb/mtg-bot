"""Tests for ``mtg_bot.cli.runs.janitor`` — the stale-running sweeper.

The janitor replaces the UI backfill's "stale-running heuristic":
running rows whose ``last_progress_at`` is older than a configurable
threshold get demoted to ``status='killed'`` so the UI doesn't keep
rendering them as if work were still in flight.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mtg_bot.cli.runs import db as runs_db
from mtg_bot.cli.runs.janitor import (
    DEFAULT_INTERVAL_SECONDS,
    DEFAULT_STALE_AFTER_HOURS,
    JanitorThread,
    run_once,
)
from mtg_bot.cli.runs.models import ProgressUpdate, Run


def _iso_hours_ago(hours: float) -> str:
    """ISO timestamp ``hours`` ago, second precision. Matches the
    shape ``upsert_progress`` writes into ``last_progress_at``."""
    when = datetime.now(timezone.utc) - timedelta(hours=hours)
    return when.isoformat(timespec="seconds")


def _insert_running(
    conn,
    run_id: str,
    *,
    started_at: str,
    last_progress_at=None,
) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            """
            INSERT INTO runs(
                run_id, kind, status, started_at, ended_at,
                git_commit, config_json, parent_run_id, label, notes,
                pid, host, training_history_json, last_progress_at,
                stop_requested
            ) VALUES (?, 'self_play', 'running', ?, NULL,
                      'abc', '{}', NULL, NULL, NULL,
                      NULL, NULL, NULL, ?, 0)
            """,
            (run_id, started_at, last_progress_at),
        )
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def _status(conn, run_id: str):
    row = conn.execute(
        "SELECT status, ended_at, notes FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


# ---- run_once ----------------------------------------------------------


def test_run_once_marks_stale_running_as_killed(tmp_path):
    """A row whose last_progress_at is 7 hours ago with stale-threshold
    6h should be demoted to killed."""
    db = tmp_path / "runs.db"
    seven_hours_ago = _iso_hours_ago(7.0)
    one_minute_ago = _iso_hours_ago(0.02)  # well under 6h threshold
    conn = runs_db.connect(db)
    try:
        _insert_running(
            conn, "stale_run",
            started_at=seven_hours_ago,
            last_progress_at=seven_hours_ago,
        )
        _insert_running(
            conn, "fresh_run",
            started_at=seven_hours_ago,
            last_progress_at=one_minute_ago,
        )
    finally:
        conn.close()

    marked = run_once(db, stale_after_hours=6.0)
    assert marked == 1

    conn = runs_db.connect(db)
    try:
        stale = _status(conn, "stale_run")
        fresh = _status(conn, "fresh_run")
    finally:
        conn.close()

    assert stale["status"] == "killed"
    assert stale["ended_at"] is not None
    assert "janitor" in (stale["notes"] or "")
    assert fresh["status"] == "running"


def test_run_once_uses_started_at_when_last_progress_at_is_null(tmp_path):
    """A row that registered ``running`` but never pushed progress
    has ``last_progress_at IS NULL``. The COALESCE fallback to
    ``started_at`` must catch it."""
    db = tmp_path / "runs.db"
    seven_hours_ago = _iso_hours_ago(7.0)
    conn = runs_db.connect(db)
    try:
        _insert_running(
            conn, "early_death",
            started_at=seven_hours_ago,
            last_progress_at=None,
        )
    finally:
        conn.close()

    marked = run_once(db, stale_after_hours=6.0)
    assert marked == 1

    conn = runs_db.connect(db)
    try:
        rec = _status(conn, "early_death")
    finally:
        conn.close()
    assert rec["status"] == "killed"


def test_run_once_leaves_terminal_rows_alone(tmp_path):
    """Already-completed / failed / killed rows must NOT be touched
    even if their last_progress_at is old."""
    db = tmp_path / "runs.db"
    seven_hours_ago = _iso_hours_ago(7.0)
    conn = runs_db.connect(db)
    try:
        for run_id, status in (
            ("done_run", "completed"),
            ("fail_run", "failed"),
            ("kill_run", "killed"),
        ):
            conn.execute(
                """
                INSERT INTO runs(
                    run_id, kind, status, started_at, ended_at,
                    git_commit, config_json, last_progress_at,
                    stop_requested
                ) VALUES (?, 'self_play', ?, ?, ?, 'abc', '{}', ?, 0)
                """,
                (run_id, status, seven_hours_ago, seven_hours_ago,
                 seven_hours_ago),
            )
    finally:
        conn.close()

    marked = run_once(db, stale_after_hours=6.0)
    assert marked == 0


def test_run_once_handles_missing_db_file(tmp_path):
    """Best-effort: a missing DB returns 0 rather than raising."""
    db = tmp_path / "does_not_exist.db"
    assert run_once(db) == 0


def test_run_once_appends_notes_when_present(tmp_path):
    """If notes is already set, the janitor appends rather than
    overwriting — so existing notes survive."""
    db = tmp_path / "runs.db"
    seven_hours_ago = _iso_hours_ago(7.0)
    conn = runs_db.connect(db)
    try:
        conn.execute(
            """
            INSERT INTO runs(
                run_id, kind, status, started_at,
                git_commit, config_json, notes, last_progress_at,
                stop_requested
            ) VALUES ('annotated', 'self_play', 'running', ?,
                      'abc', '{}', 'pre-existing notes', ?, 0)
            """,
            (seven_hours_ago, seven_hours_ago),
        )
    finally:
        conn.close()

    run_once(db, stale_after_hours=6.0)

    conn = runs_db.connect(db)
    try:
        rec = _status(conn, "annotated")
    finally:
        conn.close()
    assert "pre-existing notes" in rec["notes"]
    assert "janitor" in rec["notes"]


def test_run_once_threshold_is_configurable(tmp_path):
    """``stale_after_hours`` is the cutoff — at 24h, a 7h-old row
    is NOT stale."""
    db = tmp_path / "runs.db"
    seven_hours_ago = _iso_hours_ago(7.0)
    conn = runs_db.connect(db)
    try:
        _insert_running(
            conn, "borderline",
            started_at=seven_hours_ago,
            last_progress_at=seven_hours_ago,
        )
    finally:
        conn.close()

    # Threshold 24h — nothing should fire.
    assert run_once(db, stale_after_hours=24.0) == 0

    conn = runs_db.connect(db)
    try:
        rec = _status(conn, "borderline")
    finally:
        conn.close()
    assert rec["status"] == "running"


def test_run_once_real_time_smoke(tmp_path):
    """End-to-end smoke against real ``now``: insert a row stamped
    7h ago, sweep with threshold 1h, verify killed. Same shape as
    the brief's regression test."""
    db = tmp_path / "runs.db"
    seven_hours_ago = _iso_hours_ago(7.0)
    conn = runs_db.connect(db)
    try:
        _insert_running(
            conn, "smoke_run",
            started_at=seven_hours_ago,
            last_progress_at=seven_hours_ago,
        )
    finally:
        conn.close()

    marked = run_once(db, stale_after_hours=1.0)
    assert marked == 1

    conn = runs_db.connect(db)
    try:
        rec = _status(conn, "smoke_run")
    finally:
        conn.close()
    assert rec["status"] == "killed"
    assert rec["ended_at"] is not None


# ---- JanitorThread -----------------------------------------------------


def test_janitor_thread_runs_immediate_first_sweep(tmp_path):
    """``JanitorThread.start()`` fires the first sweep immediately
    so a freshly-started server doesn't wait a full interval before
    catching stale rows."""
    db = tmp_path / "runs.db"
    seven_hours_ago = _iso_hours_ago(7.0)
    conn = runs_db.connect(db)
    try:
        _insert_running(
            conn, "stale_immediate",
            started_at=seven_hours_ago,
            last_progress_at=seven_hours_ago,
        )
    finally:
        conn.close()

    j = JanitorThread(
        db,
        interval_seconds=300.0,  # would never tick in this test window
        stale_after_hours=6.0,
    )
    j.start()
    try:
        # Wait briefly for the first sweep to run. Janitor is a daemon
        # thread; a tight poll on its side-channel signal is fine.
        deadline = time.time() + 5.0
        while time.time() < deadline and j.last_marked == 0:
            time.sleep(0.02)
        assert j.last_marked == 1
    finally:
        j.stop(timeout=2.0)

    conn = runs_db.connect(db)
    try:
        rec = _status(conn, "stale_immediate")
    finally:
        conn.close()
    assert rec["status"] == "killed"


def test_janitor_thread_handles_db_errors_without_crashing(tmp_path):
    """A broken DB path mid-flight (file deleted) should NOT crash
    the thread — best-effort logging is the contract."""
    db = tmp_path / "runs.db"
    # No DB at the path → run_once returns 0 cleanly.
    j = JanitorThread(db, interval_seconds=300.0)
    j.start()
    try:
        time.sleep(0.2)  # let the first tick run
        assert j.last_marked == 0
    finally:
        j.stop(timeout=2.0)


def test_janitor_defaults_are_reasonable():
    """Sanity-check the constants the brief specifies."""
    assert DEFAULT_INTERVAL_SECONDS == 300  # 5 minutes
    assert DEFAULT_STALE_AFTER_HOURS == 6.0


def test_janitor_thread_stop_is_idempotent(tmp_path):
    """Calling stop() twice (or before start()) should not raise."""
    db = tmp_path / "runs.db"
    j = JanitorThread(db, interval_seconds=300.0)
    # Stop before start — no-op.
    j.stop(timeout=0.5)
    j.start()
    j.stop(timeout=2.0)
    # Stop again after stop — no-op.
    j.stop(timeout=0.5)
