"""Tests for ``POST /v2/stage/create``.

Cover the happy path, idempotency on identical re-submission, the 409
on spec drift, and the small set of input validation failures.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mtg_bot.cli import serve as serve_mod
from mtg_bot.cli.runs import queue_db


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


def _stage_spec(stage_id: str = "iter_009_self_play_v6", *, n_games: int = 3):
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
            {
                "game_idx": i,
                "deck_indices": [10 + i, 20 + i],
                "seed": 9000000 + i,
            }
            for i in range(n_games)
        ],
    }


def test_stage_create_happy_path(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    res = client.post("/v2/stage/create", json=_stage_spec())
    assert res.status_code == 200
    body = res.get_json()
    assert body["stage_id"] == "iter_009_self_play_v6"
    assert body["n_games_queued"] == 3
    # Verify persistence: the row + the queued games are written.
    conn = queue_db.connect(tmp_path / "queue.db")
    try:
        stage = queue_db.get_stage(conn, "iter_009_self_play_v6")
        assert stage is not None
        assert stage["kind"] == "self_play"
        assert stage["status"] == "running"
        n_queued = conn.execute(
            "SELECT COUNT(*) AS c FROM queued_games WHERE stage_id=?",
            ("iter_009_self_play_v6",),
        ).fetchone()["c"]
        assert n_queued == 3
    finally:
        conn.close()


def test_stage_create_is_idempotent_on_identical_spec(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    spec = _stage_spec()
    res1 = client.post("/v2/stage/create", json=spec)
    assert res1.status_code == 200
    res2 = client.post("/v2/stage/create", json=spec)
    assert res2.status_code == 200
    assert res2.get_json()["n_games_queued"] == 3
    # No duplicate rows in queued_games.
    conn = queue_db.connect(tmp_path / "queue.db")
    try:
        n_queued = conn.execute(
            "SELECT COUNT(*) AS c FROM queued_games WHERE stage_id=?",
            ("iter_009_self_play_v6",),
        ).fetchone()["c"]
        assert n_queued == 3
    finally:
        conn.close()


def test_stage_create_409_on_spec_drift(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    spec_a = _stage_spec()
    res1 = client.post("/v2/stage/create", json=spec_a)
    assert res1.status_code == 200
    spec_b = _stage_spec()
    spec_b["nodes"] = 400  # different spec
    res2 = client.post("/v2/stage/create", json=spec_b)
    assert res2.status_code == 409
    assert "different spec" in res2.get_json()["error"]


@pytest.mark.parametrize(
    "mutator,bad_field",
    [
        (lambda s: s.pop("stage_id"), "stage_id"),
        (lambda s: s.update(kind="not_a_kind"), "kind"),
        (lambda s: s.update(games=[]), "games"),
        (lambda s: s.update(claim_ttl_seconds=0), "claim_ttl_seconds"),
        (lambda s: s.update(claim_ttl_seconds="abc"), "claim_ttl_seconds"),
    ],
)
def test_stage_create_400_on_bad_input(tmp_path, mutator, bad_field):
    app = _make_app(tmp_path)
    client = app.test_client()
    spec = _stage_spec()
    mutator(spec)
    res = client.post("/v2/stage/create", json=spec)
    assert res.status_code == 400
    body = res.get_json()
    assert bad_field in body["error"] or "required" in body["error"]


def test_stage_create_rejects_unsafe_stage_id(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    spec = _stage_spec(stage_id="../etc/passwd")
    res = client.post("/v2/stage/create", json=spec)
    assert res.status_code == 400


def test_stage_create_rejects_missing_game_fields(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    spec = _stage_spec()
    spec["games"][1] = {"game_idx": 1}  # missing deck_indices + seed
    res = client.post("/v2/stage/create", json=spec)
    assert res.status_code == 400
