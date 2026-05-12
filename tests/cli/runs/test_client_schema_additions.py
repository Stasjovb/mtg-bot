"""Client-level tests for the new ``runs`` columns landed in
``feature/runs-db-schema-additions``: ``pid`` / ``host`` defaults
on ``start_run``, ``last_progress_at`` auto-stamping (covered by
``push_progress``), and the new ``set_stop_requested`` helper.

The direct-SQLite transport is hit by setting
``MTG_BOT_RUN_DB_PATH``; the REST transport is hit via a stubbed
``urlopen``.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from mtg_bot.cli.runs import client, db as runs_db


def _clear_env(monkeypatch):
    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)


# ---- start_run: pid + host defaults ---------------------------------------


def test_start_run_direct_populates_pid_host_by_default(
    monkeypatch, tmp_path,
):
    """Without explicit pid/host, start_run pulls them from
    ``os.getpid()`` + ``platform.node()`` and writes them to the
    DB row."""
    _clear_env(monkeypatch)
    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", str(db_path))

    client.start_run(
        "r1", kind="eval", config_json="{}", git_commit="abc",
    )

    conn = runs_db.connect(db_path)
    try:
        rec = runs_db.get_run(conn, "r1")
    finally:
        conn.close()
    import os
    import platform
    assert rec["run"]["pid"] == os.getpid()
    assert rec["run"]["host"] == platform.node()


def test_start_run_direct_accepts_explicit_pid_host(
    monkeypatch, tmp_path,
):
    """Explicit ``pid``/``host`` override the auto-detection. Useful
    for tests and for wrappers that register on behalf of a child."""
    _clear_env(monkeypatch)
    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", str(db_path))

    client.start_run(
        "r1", kind="eval", config_json="{}", git_commit="abc",
        pid=99999, host="remote-host",
    )

    conn = runs_db.connect(db_path)
    try:
        rec = runs_db.get_run(conn, "r1")
    finally:
        conn.close()
    assert rec["run"]["pid"] == 99999
    assert rec["run"]["host"] == "remote-host"


def test_start_run_rest_includes_pid_host(monkeypatch):
    """REST transport: pid/host show up in the POST payload."""
    _clear_env(monkeypatch)
    monkeypatch.setenv("MTG_BOT_RUN_DB_URL", "http://master:5099")

    captured = {}

    class _Resp:
        def __init__(self, body: bytes):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["data"] = json.loads(req.data.decode("utf-8"))
        return _Resp(b'{"ok": true}')

    with patch("urllib.request.urlopen", fake_urlopen):
        client.start_run(
            "r1", kind="eval",
            config_json="{}", git_commit="abc",
        )

    assert "pid" in captured["data"]
    assert isinstance(captured["data"]["pid"], int)
    assert captured["data"]["pid"] > 0
    assert "host" in captured["data"]
    assert isinstance(captured["data"]["host"], str)
    assert captured["data"]["host"]  # not empty


def test_start_run_rest_passes_explicit_pid_host(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("MTG_BOT_RUN_DB_URL", "http://master:5099")

    captured = {}

    class _Resp:
        def __init__(self, body: bytes):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(req, timeout):
        captured["data"] = json.loads(req.data.decode("utf-8"))
        return _Resp(b'{}')

    with patch("urllib.request.urlopen", fake_urlopen):
        client.start_run(
            "r1", kind="eval",
            config_json="{}", git_commit="abc",
            pid=42, host="explicit-host",
        )

    assert captured["data"]["pid"] == 42
    assert captured["data"]["host"] == "explicit-host"


# ---- push_progress: last_progress_at auto-stamping -------------------------


def test_push_progress_stamps_last_progress_at_direct(
    monkeypatch, tmp_path,
):
    """The DB layer auto-stamps ``last_progress_at`` inside
    ``upsert_progress``. Hitting the client-level ``push_progress``
    must surface the same behavior end-to-end."""
    _clear_env(monkeypatch)
    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", str(db_path))

    client.start_run(
        "r1", kind="eval", config_json="{}", git_commit="abc",
    )

    conn = runs_db.connect(db_path)
    try:
        rec = runs_db.get_run(conn, "r1")
    finally:
        conn.close()
    assert rec["run"]["last_progress_at"] is None

    client.push_progress("r1", n_games_done=5)

    conn = runs_db.connect(db_path)
    try:
        rec = runs_db.get_run(conn, "r1")
    finally:
        conn.close()
    assert rec["run"]["last_progress_at"] is not None
    assert "T" in rec["run"]["last_progress_at"]


# ---- set_stop_requested: direct transport ----------------------------------


def test_set_stop_requested_direct(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", str(db_path))

    client.start_run(
        "r1", kind="eval", config_json="{}", git_commit="abc",
    )
    client.set_stop_requested("r1")

    conn = runs_db.connect(db_path)
    try:
        rec = runs_db.get_run(conn, "r1")
    finally:
        conn.close()
    assert rec["run"]["stop_requested"] == 1

    # Clear via value=False.
    client.set_stop_requested("r1", value=False)
    conn = runs_db.connect(db_path)
    try:
        rec = runs_db.get_run(conn, "r1")
    finally:
        conn.close()
    assert rec["run"]["stop_requested"] == 0


def test_set_stop_requested_no_transport_is_noop(monkeypatch, tmp_path):
    """With neither env var set, set_stop_requested is a no-op."""
    _clear_env(monkeypatch)
    # Should not raise; no DB file created.
    client.set_stop_requested("r1")
    assert not (tmp_path / "runs.db").exists()


def test_set_stop_requested_direct_swallows_errors(
    monkeypatch, tmp_path, capsys,
):
    """If the underlying DB call raises (e.g. corrupted DB), the
    client swallows the exception and emits a stderr warning —
    Phase 1 invariant."""
    _clear_env(monkeypatch)
    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", str(db_path))

    # Force the DB-side function to raise. ``set_stop_requested`` is
    # the one we want to misbehave; patch through the module the
    # client actually imports it from.
    def explode(conn, run_id, *, value=True):
        raise RuntimeError("boom")

    with patch.object(runs_db, "set_stop_requested", explode):
        client.set_stop_requested("r1")  # must not raise

    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "set_stop_requested" in err


# ---- set_stop_requested: REST transport ------------------------------------


def test_set_stop_requested_rest_posts(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("MTG_BOT_RUN_DB_URL", "http://master:5099")

    captured = {}

    class _Resp:
        def __init__(self, body: bytes):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["data"] = json.loads(req.data.decode("utf-8"))
        captured["method"] = req.get_method()
        return _Resp(b'{"ok": true}')

    with patch("urllib.request.urlopen", fake_urlopen):
        client.set_stop_requested("r1")

    assert captured["method"] == "POST"
    assert captured["url"] == "http://master:5099/run/r1/stop_request"
    assert captured["data"] == {"value": True}


def test_set_stop_requested_rest_value_false_passes_through(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("MTG_BOT_RUN_DB_URL", "http://master:5099")

    captured = {}

    class _Resp:
        def __init__(self, body: bytes):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(req, timeout):
        captured["data"] = json.loads(req.data.decode("utf-8"))
        return _Resp(b'{}')

    with patch("urllib.request.urlopen", fake_urlopen):
        client.set_stop_requested("r1", value=False)

    assert captured["data"] == {"value": False}


def test_set_stop_requested_rest_swallows_network_error(
    monkeypatch, capsys,
):
    _clear_env(monkeypatch)
    monkeypatch.setenv("MTG_BOT_RUN_DB_URL", "http://nosuchhost:9999")

    import urllib.error

    def fake_urlopen(req, timeout):
        raise urllib.error.URLError("nope")

    with patch("urllib.request.urlopen", fake_urlopen):
        client.set_stop_requested("r1")  # must not raise

    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "set_stop_requested" in err
