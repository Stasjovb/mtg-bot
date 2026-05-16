"""Tests for ``POST /v2/stage/<stage_id>/close``.

Verifies the drain → complete state transition + the 204 behavior
that drained stages return to subsequent ``/v2/claim`` calls.
"""

from __future__ import annotations

import json
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


def _spec(*, n_games: int = 3):
    return {
        "stage_id": "iter_009_self_play_v6",
        "kind": "self_play",
        "weights": {"p0": "v5", "p1": "v5"},
        "nodes": 200,
        "samples": 4,
        "per_game_timeout_sec": 600.0,
        "capture_every": 20,
        "claim_ttl_seconds": 1200,
        "games": [
            {
                "game_idx": i,
                "deck_indices": [i, i + 1],
                "seed": 9000000 + i,
            }
            for i in range(n_games)
        ],
    }


def test_close_marks_drained(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    client.post("/v2/stage/create", json=_spec())
    res = client.post(
        "/v2/stage/iter_009_self_play_v6/close",
        json={"reason": "manual"},
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["stage_id"] == "iter_009_self_play_v6"
    assert body["drained_at"] is not None
    # Stage status reflects the close.
    res_get = client.get("/v2/stage/iter_009_self_play_v6")
    body = res_get.get_json()
    # No in-flight claims → complete immediately on drain.
    assert body["status"] == "complete"


def test_close_drained_then_claim_returns_204(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    client.post("/v2/stage/create", json=_spec())
    res = client.post(
        "/v2/stage/iter_009_self_play_v6/close",
        json={"reason": "early_stop_pass"},
    )
    assert res.status_code == 200
    # Subsequent claims return 204.
    res2 = client.post("/v2/claim", json={
        "worker_id": "wA",
        "stage_id": "iter_009_self_play_v6",
    })
    assert res2.status_code == 204


def test_close_transitions_to_complete_when_inflight_drains(tmp_path):
    """Drain while a claim is in-flight → status stays 'drained'.
    Once that claim reports back, status flips to 'complete'."""
    app = _make_app(tmp_path)
    client = app.test_client()
    client.post("/v2/stage/create", json=_spec(n_games=2))
    claim_resp = client.post("/v2/claim", json={
        "worker_id": "wA",
        "stage_id": "iter_009_self_play_v6",
    })
    claim = claim_resp.get_json()
    # Close before the in-flight claim reports.
    client.post("/v2/stage/iter_009_self_play_v6/close", json={})
    res_get = client.get("/v2/stage/iter_009_self_play_v6")
    body = res_get.get_json()
    assert body["status"] == "drained"
    assert body["n_games_in_flight"] == 1
    # In-flight claim reports back.
    res_rep = client.post(
        "/v2/report_result",
        data={"meta": json.dumps({
            "claim_id": claim["claim_id"],
            "outcome": "completed",
            "winner": 0,
            "n_samples": 0,
            "duration_s": 1.0,
            "shard_label": "wA",
        })},
        content_type="multipart/form-data",
    )
    assert res_rep.status_code == 200
    # Now complete.
    res_get = client.get("/v2/stage/iter_009_self_play_v6")
    body = res_get.get_json()
    assert body["status"] == "complete"
    assert body["complete_at"] is not None


def test_close_idempotent(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    client.post("/v2/stage/create", json=_spec())
    r1 = client.post("/v2/stage/iter_009_self_play_v6/close", json={})
    r2 = client.post("/v2/stage/iter_009_self_play_v6/close", json={})
    assert r1.status_code == 200
    assert r2.status_code == 200


def test_close_404_on_unknown_stage(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    res = client.post(
        "/v2/stage/never_existed/close",
        json={"reason": "test"},
    )
    assert res.status_code == 404


def test_close_rejects_unsafe_stage_id(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    res = client.post(
        "/v2/stage/..%2Fetc/close",
        json={},
    )
    # Flask will decode the %2F itself; whether it reaches the route
    # or not, we just want it not to land a successful close.
    assert res.status_code in (400, 404)


def test_get_stage_404_on_unknown(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    res = client.get("/v2/stage/never_existed")
    assert res.status_code == 404
