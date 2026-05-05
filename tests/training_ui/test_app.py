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


# --- Bench cards ----------------------------------------------------


def test_index_html_contains_bench_card_scaffolding():
    """Sanity that the bench card scaffolding (kind-tag.bench class,
    fillBenchCard JS function, pairings table CSS) is rendered into
    the page so the front-end can instantiate bench cards without a
    further fetch.
    """
    from pathlib import Path as _P
    from mtg_bot.training_ui.app import create_app

    app = create_app(_P("training_progress"))
    test_client = app.test_client()
    body = test_client.get("/").get_data(as_text=True)
    # CSS class for the bench tag.
    assert ".kind-tag.bench" in body
    # Per-pairing verdict pill class.
    assert ".verdict.stronger" in body
    # JS render path.
    assert "fillBenchCard" in body
    assert "pctOfBench" in body


def _bench_payload(run_id: str, **overrides) -> dict:
    payload = {
        "run_id": run_id,
        "kind": "bench",
        "status": "running",
        "started_at": "2026-05-04T12:00:00+00:00",
        "ended_at": None,
        "weights_path": "trained_weights/v10/weights.pt",
        "n_games_per_pairing": 8,
        "n_games_total": 16,
        "n_games_done": 5,
        "budgets": [[4, 200]],
        "include_belief": True,
        "belief_m_candidates": 8,
        "nn_device": "cpu",
        "elapsed_seconds": 480.2,
        "command": "scripts/bench_ismcts_vs_pimc_strength.py",
        "git_commit": "deadbeef",
        "notes": "",
        "pairings": [
            {
                "challenger": "ISMCTS-uniform",
                "defender": "PIMC",
                "n_games": 8,
                "samples": 4,
                "inner_nodes": 200,
                "total_iterations": 800,
                "started_at": "2026-05-04T12:00:00+00:00",
                "ended_at": None,
                "n_games_done": 5,
                "n_decided": 5,
                "challenger_wins": 4,
                "defender_wins": 1,
                "draws": 0,
                "crashed": 0,
                "elapsed_seconds": 480.2,
                "win_rate": 0.8,
                "ci_low": 0.376,
                "ci_high": 0.964,
                "verdict": "comparable",
                "status": "running",
            },
        ],
    }
    payload.update(overrides)
    return payload


def test_bench_run_appears_in_api_runs(client):
    c, progress_dir = client
    (progress_dir / "bench_v10.json").write_text(
        json.dumps(_bench_payload("bench_v10")),
        encoding="utf-8",
    )
    res = c.get("/api/runs")
    assert res.status_code == 200
    runs = res.get_json()["runs"]
    bench_runs = [r for r in runs if r.get("kind") == "bench"]
    assert len(bench_runs) == 1
    r = bench_runs[0]
    # All bench-shaped fields the UI renderer reads must round-trip.
    for key in (
        "run_id", "kind", "status", "started_at", "weights_path",
        "n_games_per_pairing", "n_games_total", "n_games_done",
        "budgets", "include_belief", "belief_m_candidates",
        "nn_device", "elapsed_seconds", "pairings",
    ):
        assert key in r, f"missing {key!r} in {r!r}"
    assert len(r["pairings"]) == 1
    p = r["pairings"][0]
    for key in (
        "challenger", "defender", "n_games", "n_games_done",
        "n_decided", "challenger_wins", "defender_wins", "draws",
        "crashed", "win_rate", "ci_low", "ci_high", "verdict",
        "status", "samples", "inner_nodes", "total_iterations",
    ):
        assert key in p, f"missing pairing field {key!r}"


def test_bench_run_detail_endpoint(client):
    c, progress_dir = client
    (progress_dir / "bench_v10.json").write_text(
        json.dumps(_bench_payload("bench_v10")),
        encoding="utf-8",
    )
    res = c.get("/api/runs/bench_v10")
    assert res.status_code == 200
    body = res.get_json()
    assert body["kind"] == "bench"
    assert body["pairings"][0]["verdict"] == "comparable"


def test_aggregated_run_machines_array_passes_through(client):
    """Aggregated distributed runs include a ``machines`` array; the
    API must pass it through unmodified so the per-machine sub-card
    renderer sees the precomputed per-host fields. The training UI
    turns each entry into a mini sub-card showing secs/game, crashes,
    and workers."""
    c, progress_dir = client
    payload = {
        "run_id": "iter_001_self_play_v6",
        "kind": "data_gen",
        "status": "running",
        "started_at": "2026-05-04T05:53:36+00:00",
        "n_games_total": 500,
        "n_games_done": 100,
        "n_workers": 30,
        "elapsed_seconds": 605.0,
        "machines": [
            {
                "label": "greggs-macbook-pro",
                "status": "running",
                "n_games_done": 60,
                "n_workers": 14,
                "crashed": 2,
                "elapsed_seconds": 600.0,
                "per_game_seconds": 10.0,
            },
            {
                "label": "desktop-j05412i",
                "status": "running",
                "n_games_done": 40,
                "n_workers": 16,
                "crashed": 0,
                "elapsed_seconds": 540.0,
                "per_game_seconds": 13.5,
            },
        ],
    }
    (progress_dir / "iter_001_self_play_v6.json").write_text(
        json.dumps(payload), encoding="utf-8",
    )
    res = c.get("/api/runs")
    assert res.status_code == 200
    runs = res.get_json()["runs"]
    assert len(runs) == 1
    machines = runs[0]["machines"]
    by_label = {m["label"]: m for m in machines}
    assert set(by_label) == {"greggs-macbook-pro", "desktop-j05412i"}
    mac = by_label["greggs-macbook-pro"]
    # Every field the UI's renderMachines() reads must round-trip.
    for key in (
        "label", "n_games_done", "n_workers", "crashed",
        "elapsed_seconds", "per_game_seconds",
    ):
        assert key in mac, f"missing {key!r} in machine entry"
    assert mac["per_game_seconds"] == 10.0
    assert mac["crashed"] == 2
    # Detail endpoint also exposes the machines array (the UI currently
    # polls /api/runs but the detail route shares _read_run_file).
    detail = c.get("/api/runs/iter_001_self_play_v6").get_json()
    assert len(detail["machines"]) == 2


def test_bench_completed_run_listed_with_others(client):
    """A completed bench run sits alongside training / eval / data-gen
    runs in /api/runs, sorted by started_at desc."""
    c, progress_dir = client
    _write_run(progress_dir, "v3_train",
               started_at="2026-05-04T11:00:00+00:00",
               status="completed")
    bench = _bench_payload(
        "bench_v10", status="completed",
        started_at="2026-05-04T12:00:00+00:00",
        ended_at="2026-05-04T12:30:00+00:00",
    )
    bench["pairings"][0]["status"] = "completed"
    bench["pairings"][0]["verdict"] = "stronger"
    (progress_dir / "bench_v10.json").write_text(
        json.dumps(bench), encoding="utf-8",
    )
    res = c.get("/api/runs")
    runs = res.get_json()["runs"]
    # bench_v10 sorts above v3_train (later started_at).
    assert [r["run_id"] for r in runs] == ["bench_v10", "v3_train"]
