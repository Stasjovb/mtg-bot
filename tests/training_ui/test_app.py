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
    assert 'id="active"' in body
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


def test_api_runs_skips_per_shard_files_from_distributed_runs(client):
    """Distributed runs write per-shard JSONs alongside the
    rolled-up aggregate. The aggregate has no ``_shard_`` in its
    filename; per-shard cards would just clutter the listing. UI
    skips anything matching ``*_shard_*.json``."""
    c, progress_dir = client
    _write_run(progress_dir, "iter_001_self_play_v6",
               started_at="2026-05-04T10:00:00+00:00",
               status="running")
    # Mimics what run_shard_pull writes per-shard.
    _write_run(progress_dir, "iter_001_self_play_v6_shard_local",
               started_at="2026-05-04T10:00:00+00:00",
               status="running")
    _write_run(progress_dir, "iter_001_self_play_v6_shard_macbook",
               started_at="2026-05-04T10:00:00+00:00",
               status="running")
    res = c.get("/api/runs")
    assert res.status_code == 200
    runs = res.get_json()["runs"]
    assert [r["run_id"] for r in runs] == ["iter_001_self_play_v6"]


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


def test_api_run_replays_no_replays_dir(client):
    """A run that didn't capture replays returns an empty list with
    a human-readable note rather than 404 — the UI shows a 'capture
    off' chip in that case."""
    c, progress_dir = client
    _write_run(progress_dir, "iter_001_self_play_v6", replays_dir=None)
    res = c.get("/api/runs/iter_001_self_play_v6/replays")
    assert res.status_code == 200
    payload = res.get_json()
    assert payload["count"] == 0
    assert payload["replays"] == []
    assert "did not capture" in payload["note"]


def test_api_run_replays_lists_files(client, tmp_path: Path):
    """When replays_dir is set and exists, the endpoint returns the
    contained .json.gz files with subpaths suitable for the main UI's
    ``/api/load_replay/<subpath>`` route."""
    c, progress_dir = client
    rep_dir = tmp_path / "replays" / "iter_001_self_play_v6"
    rep_dir.mkdir(parents=True)
    (rep_dir / "game_seed42_idx0000.json.gz").write_bytes(b"")
    (rep_dir / "game_seed42_idx0025.json.gz").write_bytes(b"")
    (rep_dir / "ignore_me.txt").write_text("not a replay")
    _write_run(
        progress_dir, "iter_001_self_play_v6",
        replays_dir=str(rep_dir),
    )
    res = c.get("/api/runs/iter_001_self_play_v6/replays")
    assert res.status_code == 200
    payload = res.get_json()
    assert payload["count"] == 2
    subpaths = [r["subpath"] for r in payload["replays"]]
    assert subpaths == [
        "iter_001_self_play_v6/game_seed42_idx0000.json.gz",
        "iter_001_self_play_v6/game_seed42_idx0025.json.gz",
    ]


def test_api_run_replays_dir_missing(client):
    """If replays_dir was set but the directory doesn't exist on
    disk (e.g. iterate aborted before any capture, or a stale path),
    return empty + a hint rather than crashing the UI."""
    c, progress_dir = client
    _write_run(
        progress_dir, "iter_001_self_play_v6",
        replays_dir="/no/such/path",
    )
    res = c.get("/api/runs/iter_001_self_play_v6/replays")
    assert res.status_code == 200
    payload = res.get_json()
    assert payload["count"] == 0
    assert "does not exist" in payload["note"]


def test_api_run_replays_unknown_run(client):
    c, _ = client
    res = c.get("/api/runs/nope/replays")
    assert res.status_code == 404


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
