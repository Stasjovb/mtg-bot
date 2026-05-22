"""Tests for the ``/run/start_or_restart`` REST endpoint alias.

The endpoint shares its handler with the older ``/run/start`` route
(see :mod:`mtg_bot.cli.serve`); these tests exercise the aliased path
specifically because the unified launcher
(``mtg_bot iterate-distributed``) calls it under that name and we
want the alias to be an enforced part of the wire contract, not an
implementation accident.

The deeper behavioral coverage of ``insert_or_restart_run`` itself
(notes-prefixing, stop_requested clearing, pid overwrite, kind/status
validation) lives in :mod:`tests.cli.runs.test_insert_or_restart_run`.
This file owns the alias-endpoint smoke + the launcher-flow shape:
fresh ``inserted``, restart-after-failed ``restarted``, conflict on
``running``.
"""
from __future__ import annotations

import json
from pathlib import Path

from mtg_bot.cli import serve as serve_mod
from mtg_bot.cli.runs import db as runs_db


def _make_app(tmp_path: Path):
    return serve_mod.create_app(
        repo_url="https://example.test/mtg-bot.git",
        master_pubkey="ssh-ed25519 KEY",
        master_tailnet_name="myhost",
        port=5099,
        runs_db_path=tmp_path / "runs.db",
    )


def _payload(run_id: str = "iter_020_cycle", **overrides) -> dict:
    base = {
        "run_id": run_id,
        "kind": "iterate",
        "started_at": "2026-05-21T12:00:00+00:00",
        "git_commit": "abc1234",
        "config_json": json.dumps({"iter_idx": 20}),
    }
    base.update(overrides)
    return base


def test_alias_fresh_returns_200_inserted(tmp_path: Path):
    client = _make_app(tmp_path).test_client()
    resp = client.post("/run/start_or_restart", json=_payload("fresh-1"))
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["outcome"] == "inserted"
    assert body["run_id"] == "fresh-1"


def test_alias_restart_after_failed_returns_200_restarted(tmp_path: Path):
    app = _make_app(tmp_path)
    client = app.test_client()
    client.post("/run/start_or_restart", json=_payload("restart-1"))

    # Simulate the orchestrator dying mid-cycle.
    conn = runs_db.connect(tmp_path / "runs.db")
    runs_db.finish_run(conn, "restart-1", "failed", notes="boom")
    conn.close()

    resp = client.post(
        "/run/start_or_restart",
        json=_payload("restart-1", started_at="2026-05-21T13:00:00+00:00"),
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["outcome"] == "restarted"

    # And the DB row is back to running with cleared ended_at.
    conn = runs_db.connect(tmp_path / "runs.db")
    row = runs_db.get_run(conn, "restart-1")["run"]
    assert row["status"] == "running"
    assert row["ended_at"] is None
    conn.close()


def test_alias_conflict_on_running_returns_409(tmp_path: Path):
    client = _make_app(tmp_path).test_client()
    client.post("/run/start_or_restart", json=_payload("busy-1"))

    resp = client.post("/run/start_or_restart", json=_payload("busy-1"))
    assert resp.status_code == 409
    body = resp.get_json()
    assert body["ok"] is False
    assert body["outcome"] == "conflict"
    assert "non-restartable" in body["error"]


def test_alias_conflict_on_completed_returns_409(tmp_path: Path):
    app = _make_app(tmp_path)
    client = app.test_client()
    client.post("/run/start_or_restart", json=_payload("done-1"))
    conn = runs_db.connect(tmp_path / "runs.db")
    runs_db.finish_run(conn, "done-1", "completed")
    conn.close()

    resp = client.post("/run/start_or_restart", json=_payload("done-1"))
    assert resp.status_code == 409
    body = resp.get_json()
    assert body["outcome"] == "conflict"


def test_alias_disabled_when_runs_db_not_configured(tmp_path: Path):
    """When ``runs_db_path`` is unset, both endpoints 404 the same way."""
    app = serve_mod.create_app(
        repo_url="https://example.test/mtg-bot.git",
        master_pubkey="ssh-ed25519 KEY",
        master_tailnet_name="myhost",
        port=5099,
        runs_db_path=None,
    )
    client = app.test_client()
    resp = client.post("/run/start_or_restart", json=_payload("anything"))
    assert resp.status_code == 404


def test_alias_missing_field_returns_400(tmp_path: Path):
    client = _make_app(tmp_path).test_client()
    resp = client.post(
        "/run/start_or_restart",
        json={"run_id": "broken", "kind": "iterate"},  # missing git_commit
    )
    assert resp.status_code == 400
    assert "missing field" in resp.get_json()["error"]
