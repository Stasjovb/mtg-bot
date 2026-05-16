"""Tests for ``GET /v2/healthz``."""

from __future__ import annotations

from pathlib import Path

from mtg_bot.cli import serve as serve_mod


def _make_app(tmp_path: Path):
    return serve_mod.create_app(
        repo_url="https://example.test/mtg-bot.git",
        master_pubkey="ssh-ed25519 KEY",
        master_tailnet_name="myhost",
        port=5099,
        queue_db_path=tmp_path / "queue.db",
        weights_root=tmp_path / "trained_weights",
        iterate_data_dir=tmp_path / "iterate_data",
        replays_root=tmp_path / "replays",
        shards_config_path=tmp_path / "shards.json",
        enable_heartbeat_poller=False,
    )


def _stage_spec(stage_id: str, n_games: int = 2):
    return {
        "stage_id": stage_id,
        "kind": "self_play",
        "weights": {"p0": "v5", "p1": "v5"},
        "nodes": 200,
        "samples": 4,
        "per_game_timeout_sec": 600.0,
        "capture_every": 20,
        "claim_ttl_seconds": 1200,
        "games": [
            {"game_idx": i, "deck_indices": [i, i + 1], "seed": 9000000 + i}
            for i in range(n_games)
        ],
    }


def test_healthz_shape_empty(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    res = client.get("/v2/healthz")
    assert res.status_code == 200
    body = res.get_json()
    assert body["status"] == "ok"
    assert body["queue_depths"] == {}
    assert isinstance(body["uptime_s"], float)
    assert body["uptime_s"] >= 0.0


def test_healthz_reports_queue_depths(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    client.post("/v2/stage/create", json=_stage_spec("stage_a", n_games=3))
    client.post("/v2/stage/create", json=_stage_spec("stage_b", n_games=5))
    res = client.get("/v2/healthz")
    body = res.get_json()
    assert body["status"] == "ok"
    assert body["queue_depths"] == {"stage_a": 3, "stage_b": 5}


def test_healthz_excludes_drained_stages(tmp_path):
    """After close, the stage's queued_games are deleted, so it
    drops out of the queue_depths map."""
    app = _make_app(tmp_path)
    client = app.test_client()
    client.post("/v2/stage/create", json=_stage_spec("stage_a", n_games=3))
    client.post("/v2/stage/stage_a/close", json={})
    res = client.get("/v2/healthz")
    body = res.get_json()
    assert body["queue_depths"] == {}
