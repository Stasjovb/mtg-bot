"""Tests for the REST endpoints touched by
``feature/runs-db-schema-additions``:

- ``POST /run/start`` accepts and persists ``pid`` + ``host``.
- ``POST /run/<id>/progress`` writes through to
  ``runs.last_progress_at`` (covered indirectly via /run/<id>).
- ``POST /run/<id>/stop_request`` is the new endpoint that flips
  the soft ``stop_requested`` flag; returns 404 when the run DB
  is disabled.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mtg_bot.cli import serve as serve_mod
from mtg_bot.cli.runs import db as runs_db


def _make_app(*, runs_db_path: Path | None) -> "serve_mod.Flask":
    return serve_mod.create_app(
        repo_url="https://example.test/mtg-bot.git",
        master_pubkey="ssh-ed25519 KEY",
        master_tailnet_name="myhost",
        port=5099,
        runs_db_path=runs_db_path,
    )


def _seed(client, run_id: str = "r1") -> None:
    res = client.post(
        "/run/start",
        json={
            "run_id": run_id, "kind": "eval",
            "config_json": "{}", "git_commit": "abc",
        },
    )
    assert res.status_code == 200


# ---- /run/start pid + host ------------------------------------------------


def test_run_start_persists_pid_host(tmp_path):
    db_path = tmp_path / "runs.db"
    app = _make_app(runs_db_path=db_path)
    client = app.test_client()
    res = client.post(
        "/run/start",
        json={
            "run_id": "r1",
            "kind": "eval",
            "config_json": "{}",
            "git_commit": "abc",
            "pid": 4242,
            "host": "desktop-j05412i",
        },
    )
    assert res.status_code == 200

    rec = client.get("/run/r1").get_json()
    assert rec["run"]["pid"] == 4242
    assert rec["run"]["host"] == "desktop-j05412i"


def test_run_start_pid_host_optional(tmp_path):
    """Omitting pid/host keeps them NULL on the row — old clients
    that haven't been updated must still work."""
    db_path = tmp_path / "runs.db"
    app = _make_app(runs_db_path=db_path)
    client = app.test_client()
    res = client.post(
        "/run/start",
        json={
            "run_id": "r1",
            "kind": "eval",
            "config_json": "{}",
            "git_commit": "abc",
        },
    )
    assert res.status_code == 200
    rec = client.get("/run/r1").get_json()
    assert rec["run"]["pid"] is None
    assert rec["run"]["host"] is None


# ---- /run/<id>/progress stamps last_progress_at ----------------------------


def test_progress_endpoint_updates_last_progress_at(tmp_path):
    db_path = tmp_path / "runs.db"
    app = _make_app(runs_db_path=db_path)
    client = app.test_client()
    _seed(client)

    pre = client.get("/run/r1").get_json()
    assert pre["run"]["last_progress_at"] is None

    res = client.post(
        "/run/r1/progress",
        json={"n_games_done": 1, "elapsed_seconds": 0.5},
    )
    assert res.status_code == 200

    post = client.get("/run/r1").get_json()
    assert post["run"]["last_progress_at"] is not None
    assert "T" in post["run"]["last_progress_at"]


# ---- /run/<id>/stop_request ------------------------------------------------


def test_stop_request_flips_flag(tmp_path):
    db_path = tmp_path / "runs.db"
    app = _make_app(runs_db_path=db_path)
    client = app.test_client()
    _seed(client)

    pre = client.get("/run/r1").get_json()
    assert pre["run"]["stop_requested"] == 0

    res = client.post("/run/r1/stop_request", json={})
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    assert body["run_id"] == "r1"
    assert body["stop_requested"] is True

    post = client.get("/run/r1").get_json()
    assert post["run"]["stop_requested"] == 1


def test_stop_request_explicit_value_true(tmp_path):
    db_path = tmp_path / "runs.db"
    app = _make_app(runs_db_path=db_path)
    client = app.test_client()
    _seed(client)
    res = client.post("/run/r1/stop_request", json={"value": True})
    assert res.status_code == 200
    assert res.get_json()["stop_requested"] is True


def test_stop_request_value_false_clears(tmp_path):
    db_path = tmp_path / "runs.db"
    app = _make_app(runs_db_path=db_path)
    client = app.test_client()
    _seed(client)

    # Set first.
    client.post("/run/r1/stop_request", json={"value": True})
    # Then clear.
    res = client.post("/run/r1/stop_request", json={"value": False})
    assert res.status_code == 200
    assert res.get_json()["stop_requested"] is False
    rec = client.get("/run/r1").get_json()
    assert rec["run"]["stop_requested"] == 0


def test_stop_request_no_body_defaults_to_true(tmp_path):
    """Empty body (no JSON) treated as ``value=True``."""
    db_path = tmp_path / "runs.db"
    app = _make_app(runs_db_path=db_path)
    client = app.test_client()
    _seed(client)
    # No json= -> empty body. Flask returns None from
    # get_json(silent=True); handler should treat absent value as
    # True.
    res = client.post("/run/r1/stop_request")
    assert res.status_code == 200
    assert res.get_json()["stop_requested"] is True


def test_stop_request_unknown_run_no_error(tmp_path):
    """Setting the flag on a non-existent run_id should not error —
    the producer would already be gone or never started."""
    db_path = tmp_path / "runs.db"
    app = _make_app(runs_db_path=db_path)
    client = app.test_client()
    # Don't seed.
    res = client.post("/run/nope/stop_request", json={"value": True})
    assert res.status_code == 200


def test_stop_request_disabled_returns_404():
    """When runs_db_path is None, the new endpoint returns 404 —
    parallels every other run-DB endpoint."""
    app = _make_app(runs_db_path=None)
    client = app.test_client()
    res = client.post("/run/r1/stop_request", json={})
    assert res.status_code == 404
    assert "not configured" in res.get_json()["error"]


# ---- janitor wiring -------------------------------------------------------


def test_create_app_starts_janitor_when_runs_db_enabled(tmp_path):
    """When ``runs_db_path`` is set, ``create_app`` spins up a
    background :class:`JanitorThread` that periodically demotes
    stale ``running`` rows. The thread is exposed on
    ``app.extensions["runs_janitor"]`` so tests / ops can poke it.
    """
    db_path = tmp_path / "runs.db"
    app = serve_mod.create_app(
        repo_url="https://example.test/mtg-bot.git",
        master_pubkey="ssh-ed25519 KEY",
        master_tailnet_name="myhost",
        port=5099,
        runs_db_path=db_path,
        # Tiny interval so the test doesn't wait minutes.
        janitor_interval_seconds=0.05,
        janitor_stale_after_hours=1.0,
    )
    try:
        assert "runs_janitor" in app.extensions
        janitor = app.extensions["runs_janitor"]
        # Thread is running and ticking.
        assert janitor._thread is not None  # noqa: SLF001
        assert janitor._thread.is_alive()  # noqa: SLF001
    finally:
        app.extensions["runs_janitor"].stop(timeout=1.0)


def test_create_app_no_janitor_when_runs_db_disabled():
    """``runs_db_path=None`` -> no janitor thread; the
    ``app.extensions`` slot is absent so callers can branch on its
    presence."""
    app = _make_app(runs_db_path=None)
    assert "runs_janitor" not in app.extensions


def test_create_app_janitor_marks_stale_row(tmp_path):
    """Smoke: seed a stale ``running`` row, start the app, wait
    briefly, assert the row is killed."""
    from datetime import datetime, timedelta, timezone

    db_path = tmp_path / "runs.db"
    # Pre-create the DB and seed a stale row.
    conn = runs_db.connect(db_path)
    try:
        seven_hours_ago = (
            datetime.now(timezone.utc) - timedelta(hours=7)
        ).isoformat(timespec="seconds")
        conn.execute(
            """
            INSERT INTO runs(
                run_id, kind, status, started_at,
                git_commit, config_json, last_progress_at,
                stop_requested
            ) VALUES ('stale_row', 'self_play', 'running', ?,
                      'abc', '{}', ?, 0)
            """,
            (seven_hours_ago, seven_hours_ago),
        )
    finally:
        conn.close()

    app = serve_mod.create_app(
        repo_url="https://example.test/mtg-bot.git",
        master_pubkey="ssh-ed25519 KEY",
        master_tailnet_name="myhost",
        port=5099,
        runs_db_path=db_path,
        janitor_interval_seconds=300.0,  # won't tick again
        janitor_stale_after_hours=6.0,
    )
    try:
        import time as _time
        janitor = app.extensions["runs_janitor"]
        deadline = _time.time() + 5.0
        while _time.time() < deadline and janitor.last_marked == 0:
            _time.sleep(0.02)
        assert janitor.last_marked == 1
    finally:
        app.extensions["runs_janitor"].stop(timeout=1.0)

    conn = runs_db.connect(db_path)
    try:
        row = conn.execute(
            "SELECT status, ended_at FROM runs WHERE run_id = 'stale_row'",
        ).fetchone()
    finally:
        conn.close()
    assert row["status"] == "killed"
    assert row["ended_at"] is not None
