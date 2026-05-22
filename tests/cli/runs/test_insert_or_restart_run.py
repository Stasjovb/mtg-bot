"""Tests for ``mtg_bot.cli.runs.db.insert_or_restart_run`` and the
``/run/start`` REST endpoint's idempotent-on-restart behavior.

Why this exists: today's iter_020 launches all left the runs.db
``iter_020_cycle`` row at ``status=failed`` because the original
orchestrator died and the relaunch's ``insert_run`` raised
``IntegrityError`` (silently caught + logged as a warning by the
runs.client). The UI then faithfully showed ``failed`` even
while a brand-new orchestrator was actively driving the cycle.
``insert_or_restart_run`` closes that gap: failed/killed rows
are overwritten in place, running/completed rows are protected.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from mtg_bot.cli import serve as serve_mod
from mtg_bot.cli.runs import db as runs_db
from mtg_bot.cli.runs.models import Run


def _make_run(run_id: str = "r1", **overrides) -> Run:
    base = dict(
        run_id=run_id,
        kind="iterate",
        status="running",
        started_at="2026-05-21T12:00:00+00:00",
        git_commit="abc1234",
        config_json=json.dumps({"iter_idx": 20}),
    )
    base.update(overrides)
    return Run(**base)


# ---- insert_or_restart_run: outcomes -----------------------------------


def test_fresh_run_returns_inserted(tmp_path: Path):
    conn = runs_db.connect(tmp_path / "runs.db")
    outcome = runs_db.insert_or_restart_run(conn, _make_run("fresh-1"))
    assert outcome == "inserted"
    row = runs_db.get_run(conn, "fresh-1")
    assert row is not None
    assert row["run"]["status"] == "running"
    conn.close()


def test_restart_of_failed_run_returns_restarted_and_clears_ended_at(
    tmp_path: Path,
):
    conn = runs_db.connect(tmp_path / "runs.db")
    runs_db.insert_run(conn, _make_run("cycle-1"))
    runs_db.finish_run(
        conn, "cycle-1", "failed", notes="TimeoutError: timed out",
    )
    pre = runs_db.get_run(conn, "cycle-1")["run"]
    assert pre["status"] == "failed"
    assert pre["ended_at"] is not None

    relaunch = _make_run(
        "cycle-1",
        started_at="2026-05-21T13:00:00+00:00",
        git_commit="def5678",
        config_json=json.dumps({"iter_idx": 20, "nodes": 800}),
        pid=99999,
    )
    outcome = runs_db.insert_or_restart_run(conn, relaunch)
    assert outcome == "restarted"

    post = runs_db.get_run(conn, "cycle-1")["run"]
    assert post["status"] == "running"
    assert post["ended_at"] is None
    assert post["started_at"] == "2026-05-21T13:00:00+00:00"
    assert post["git_commit"] == "def5678"
    assert post["config_json"] == json.dumps({"iter_idx": 20, "nodes": 800})
    assert post["pid"] == 99999
    conn.close()


def test_restart_of_killed_run_returns_restarted(tmp_path: Path):
    conn = runs_db.connect(tmp_path / "runs.db")
    runs_db.insert_run(conn, _make_run("cycle-2"))
    runs_db.finish_run(conn, "cycle-2", "killed", notes="user-aborted")
    outcome = runs_db.insert_or_restart_run(conn, _make_run("cycle-2"))
    assert outcome == "restarted"
    assert runs_db.get_run(conn, "cycle-2")["run"]["status"] == "running"
    conn.close()


def test_restart_appends_prior_status_into_notes(tmp_path: Path):
    conn = runs_db.connect(tmp_path / "runs.db")
    runs_db.insert_run(conn, _make_run("cycle-3"))
    runs_db.finish_run(
        conn, "cycle-3", "failed", notes="prior-attempt-1 notes",
    )
    runs_db.insert_or_restart_run(
        conn, _make_run("cycle-3", notes="relaunch attempt"),
    )
    post = runs_db.get_run(conn, "cycle-3")["run"]
    assert "[restart] prior status=failed" in post["notes"]
    assert "relaunch attempt" in post["notes"]
    conn.close()


def test_running_run_returns_conflict_and_does_not_overwrite(
    tmp_path: Path,
):
    conn = runs_db.connect(tmp_path / "runs.db")
    runs_db.insert_run(
        conn, _make_run("cycle-4", pid=11111),
    )
    outcome = runs_db.insert_or_restart_run(
        conn, _make_run("cycle-4", pid=22222),
    )
    assert outcome == "conflict"
    # Row was NOT overwritten -- the live producer's pid is intact.
    assert runs_db.get_run(conn, "cycle-4")["run"]["pid"] == 11111
    conn.close()


def test_completed_run_returns_conflict(tmp_path: Path):
    conn = runs_db.connect(tmp_path / "runs.db")
    runs_db.insert_run(conn, _make_run("cycle-5"))
    runs_db.finish_run(conn, "cycle-5", "completed")
    outcome = runs_db.insert_or_restart_run(conn, _make_run("cycle-5"))
    assert outcome == "conflict"
    assert runs_db.get_run(conn, "cycle-5")["run"]["status"] == "completed"
    conn.close()


def test_invalid_kind_raises(tmp_path: Path):
    conn = runs_db.connect(tmp_path / "runs.db")
    with pytest.raises(ValueError, match="kind must be one of"):
        runs_db.insert_or_restart_run(
            conn, _make_run("bad", kind="bogus"),
        )
    conn.close()


def test_invalid_status_raises(tmp_path: Path):
    conn = runs_db.connect(tmp_path / "runs.db")
    with pytest.raises(ValueError, match="status must be one of"):
        runs_db.insert_or_restart_run(
            conn, _make_run("bad", status="bogus"),
        )
    conn.close()


def test_restart_clears_stop_requested_flag(tmp_path: Path):
    # Force-kill sets stop_requested=1; relaunch needs to clear it
    # so the new producer's poll loop doesn't immediately exit.
    conn = runs_db.connect(tmp_path / "runs.db")
    runs_db.insert_run(conn, _make_run("cycle-6"))
    runs_db.set_stop_requested(conn, "cycle-6", value=True)
    runs_db.finish_run(conn, "cycle-6", "killed")
    runs_db.insert_or_restart_run(conn, _make_run("cycle-6"))
    post = runs_db.get_run(conn, "cycle-6")["run"]
    assert post["stop_requested"] == 0
    conn.close()


# ---- REST endpoint integration -----------------------------------------


def _make_app(tmp_path: Path):
    return serve_mod.create_app(
        repo_url="https://example.test/mtg-bot.git",
        master_pubkey="ssh-ed25519 KEY",
        master_tailnet_name="myhost",
        port=5099,
        runs_db_path=tmp_path / "runs.db",
    )


def _run_payload(run_id: str = "rest-1", **overrides) -> dict:
    base = {
        "run_id": run_id,
        "kind": "iterate",
        "status": "running",
        "started_at": "2026-05-21T12:00:00+00:00",
        "git_commit": "abc1234",
        "config_json": json.dumps({"iter_idx": 20}),
    }
    base.update(overrides)
    return base


def test_rest_fresh_run_returns_inserted(tmp_path: Path):
    app = _make_app(tmp_path)
    client = app.test_client()
    resp = client.post("/run/start", json=_run_payload("rest-fresh"))
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["outcome"] == "inserted"


def test_rest_restart_of_failed_returns_200_restarted(tmp_path: Path):
    app = _make_app(tmp_path)
    client = app.test_client()
    client.post("/run/start", json=_run_payload("rest-restart"))

    # Mark it failed (simulating the orchestrator dying).
    conn = runs_db.connect(tmp_path / "runs.db")
    runs_db.finish_run(conn, "rest-restart", "failed", notes="died")
    conn.close()

    resp = client.post(
        "/run/start",
        json=_run_payload(
            "rest-restart", started_at="2026-05-21T14:00:00+00:00",
        ),
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["outcome"] == "restarted"

    # And the DB row is back to running with cleared ended_at.
    conn = runs_db.connect(tmp_path / "runs.db")
    row = runs_db.get_run(conn, "rest-restart")["run"]
    assert row["status"] == "running"
    assert row["ended_at"] is None
    conn.close()


def test_rest_conflict_on_running_returns_409(tmp_path: Path):
    app = _make_app(tmp_path)
    client = app.test_client()
    client.post("/run/start", json=_run_payload("rest-running"))
    resp = client.post("/run/start", json=_run_payload("rest-running"))
    assert resp.status_code == 409
    body = resp.get_json()
    assert body["ok"] is False
    assert body["outcome"] == "conflict"
    assert "non-restartable" in body["error"]


def test_rest_conflict_on_completed_returns_409(tmp_path: Path):
    app = _make_app(tmp_path)
    client = app.test_client()
    client.post("/run/start", json=_run_payload("rest-completed"))
    conn = runs_db.connect(tmp_path / "runs.db")
    runs_db.finish_run(conn, "rest-completed", "completed")
    conn.close()
    resp = client.post("/run/start", json=_run_payload("rest-completed"))
    assert resp.status_code == 409
