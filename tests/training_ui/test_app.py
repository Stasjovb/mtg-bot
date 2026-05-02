"""Tests for the read-only Flask viewer in
``mtg_bot.training_ui.app``.

We use Flask's test client, no live server — the route handlers
read JSON files off disk, so we just seed a tmp directory with
synthetic progress files and assert on the responses.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mtg_bot.training_ui.app import create_app


def _write_run(progress_dir: Path, run_id: str, **fields) -> Path:
    """Drop a synthetic run file in ``progress_dir`` with sensible
    defaults; ``fields`` overrides individual keys."""
    payload = {
        "run_id": run_id,
        "started_at": "2026-05-02T12:00:00+00:00",
        "total_epochs": 30,
        "current_epoch": 30,
        "elapsed_seconds": 60.0,
        "per_epoch_seconds_avg": 2.0,
        "estimated_remaining_seconds": 0.0,
        "train_losses": [0.5, 0.4, 0.3],
        "val_losses": [0.55, 0.45, 0.35],
        "status": "completed",
        "git_commit": "abcdef0",
        "notes": "",
    }
    payload.update(fields)
    path = progress_dir / f"{run_id}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.fixture()
def client(tmp_path: Path):
    progress_dir = tmp_path / "training_progress"
    progress_dir.mkdir()
    app = create_app(progress_dir)
    app.config["TESTING"] = True
    return app.test_client(), progress_dir


def test_index_returns_html_page(client):
    c, _ = client
    res = c.get("/")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    # Sanity-check key DOM hooks the JS depends on.
    assert "<html" in body.lower()
    assert 'id="latest"' in body
    assert 'id="older"' in body
    assert 'id="refresh-indicator"' in body
    # Pulls Chart.js from CDN (no Python-side dep).
    assert "chart.js" in body.lower() or "chart.umd" in body.lower()


def test_api_runs_empty_dir(client):
    c, _ = client
    res = c.get("/api/runs")
    assert res.status_code == 200
    assert res.get_json() == {"runs": []}


def test_api_runs_lists_and_sorts_by_started_at_desc(client):
    c, progress_dir = client
    _write_run(progress_dir, "v1",
               started_at="2026-05-01T10:00:00+00:00",
               status="completed")
    _write_run(progress_dir, "v2",
               started_at="2026-05-02T11:00:00+00:00",
               status="running", current_epoch=15)
    _write_run(progress_dir, "v3",
               started_at="2026-05-03T09:00:00+00:00",
               status="failed", current_epoch=4)

    res = c.get("/api/runs")
    assert res.status_code == 200
    runs = res.get_json()["runs"]
    assert [r["run_id"] for r in runs] == ["v3", "v2", "v1"]

    # Spot-check the fields the page needs are present.
    latest = runs[0]
    for key in (
        "run_id", "started_at", "total_epochs", "current_epoch",
        "elapsed_seconds", "per_epoch_seconds_avg",
        "estimated_remaining_seconds", "train_losses", "val_losses",
        "status", "git_commit", "notes",
    ):
        assert key in latest, f"missing key {key!r} in {latest!r}"


def test_api_runs_skips_unparseable_files(client):
    c, progress_dir = client
    _write_run(progress_dir, "v1")
    # garbage file that should be silently skipped, not 500
    (progress_dir / "broken.json").write_text("{not json", encoding="utf-8")
    res = c.get("/api/runs")
    assert res.status_code == 200
    runs = res.get_json()["runs"]
    assert [r["run_id"] for r in runs] == ["v1"]


def test_api_run_detail_by_id(client):
    c, progress_dir = client
    _write_run(progress_dir, "v7", status="running", current_epoch=12)
    res = c.get("/api/runs/v7")
    assert res.status_code == 200
    body = res.get_json()
    assert body["run_id"] == "v7"
    assert body["status"] == "running"
    assert body["current_epoch"] == 12


def test_api_run_detail_404_for_unknown(client):
    c, _ = client
    res = c.get("/api/runs/nope")
    assert res.status_code == 404


def test_progress_dir_missing_at_create_time_still_serves(tmp_path: Path):
    """The trainer might not have written anything yet when the UI
    starts up. Don't crash on a missing dir — return an empty list."""
    app = create_app(tmp_path / "doesnt_exist_yet")
    client = app.test_client()
    res = client.get("/api/runs")
    assert res.status_code == 200
    assert res.get_json() == {"runs": []}


def test_run_id_falls_back_to_filename_stem(client):
    """A progress file missing the run_id key should still appear
    in /api/runs, identified by its filename stem. Defensive — we
    don't want a malformed write to make a run vanish from the UI."""
    c, progress_dir = client
    payload = {
        "started_at": "2026-05-02T00:00:00+00:00",
        "total_epochs": 10, "current_epoch": 1,
        "elapsed_seconds": 1.0, "per_epoch_seconds_avg": 1.0,
        "estimated_remaining_seconds": 9.0,
        "train_losses": [0.9], "val_losses": [0.95],
        "status": "running", "git_commit": None, "notes": "",
    }
    (progress_dir / "v_orphan.json").write_text(
        json.dumps(payload), encoding="utf-8",
    )
    res = c.get("/api/runs")
    runs = res.get_json()["runs"]
    assert any(r["run_id"] == "v_orphan" for r in runs)
