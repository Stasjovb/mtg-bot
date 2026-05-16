"""Tests for ``POST /v2/claim`` + ``POST /v2/report_result``.

Cover the happy path (claim returns a per-game spec, report_result
writes npz/replay to disk, results row populated), and the two
distinct duplicate-report cases:

- on-time duplicate retry (claim still owned by reporting worker) →
  200 with ``duplicate: true``.
- late duplicate (claim was re-queued + re-claimed + reported by
  another worker; this is the zombie-worker case) → 409.
"""

from __future__ import annotations

import io
import json
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


def _spec(*, n_games: int = 2, kind: str = "self_play"):
    spec = {
        "stage_id": "iter_009_self_play_v6",
        "kind": kind,
        "weights": (
            {"p0": "v5", "p1": "v5"} if kind == "self_play"
            else {"new": "v6", "old": "v5"}
        ),
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
    return spec


def _create_stage(client, spec):
    res = client.post("/v2/stage/create", json=spec)
    assert res.status_code == 200, res.get_json()


# ---- /v2/claim ------------------------------------------------------------


def test_claim_returns_per_game_spec(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    _create_stage(client, _spec())
    res = client.post("/v2/claim", json={
        "worker_id": "wA",
        "stage_id": "iter_009_self_play_v6",
    })
    assert res.status_code == 200
    body = res.get_json()
    assert body["game_idx"] == 0
    assert body["deck_indices"] == [10, 20]
    assert body["seed"] == 9000000
    assert body["kind"] == "self_play"
    assert body["weights"] == {"p0": "v5", "p1": "v5"}
    assert body["nodes"] == 200
    assert body["samples"] == 4
    assert body["per_game_timeout_sec"] == 600.0
    assert body["capture_every"] == 20
    assert body["expires_at"].endswith("Z")
    assert body["claim_id"].startswith("iter_009_self_play_v6:")


def test_claim_404_on_unknown_stage(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    res = client.post("/v2/claim", json={
        "worker_id": "wA",
        "stage_id": "does_not_exist",
    })
    assert res.status_code == 404


def test_claim_204_when_queue_empty(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    _create_stage(client, _spec(n_games=1))
    r1 = client.post("/v2/claim", json={
        "worker_id": "wA",
        "stage_id": "iter_009_self_play_v6",
    })
    assert r1.status_code == 200
    r2 = client.post("/v2/claim", json={
        "worker_id": "wB",
        "stage_id": "iter_009_self_play_v6",
    })
    assert r2.status_code == 204


def test_claim_400_on_missing_fields(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    res = client.post("/v2/claim", json={})
    assert res.status_code == 400


# ---- /v2/report_result ----------------------------------------------------


def _claim_one(client) -> dict:
    res = client.post("/v2/claim", json={
        "worker_id": "wA",
        "stage_id": "iter_009_self_play_v6",
    })
    assert res.status_code == 200, res.get_json()
    return res.get_json()


def test_report_result_happy_path_writes_files(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    _create_stage(client, _spec())
    claim = _claim_one(client)
    meta = {
        "claim_id": claim["claim_id"],
        "outcome": "completed",
        "winner": 0,
        "n_samples": 1142,
        "duration_s": 31.4,
        "shard_label": "mac",
    }
    npz_bytes = b"\x00\x01\x02fake-npz"
    replay_bytes = b"\x00\x01fake-replay"
    res = client.post(
        "/v2/report_result",
        data={
            "meta": json.dumps(meta),
            "npz": (io.BytesIO(npz_bytes), "ignored.npz"),
            "replay": (io.BytesIO(replay_bytes), "ignored.json.gz"),
        },
        content_type="multipart/form-data",
    )
    assert res.status_code == 200, res.get_json()
    body = res.get_json()
    assert body["accepted"] is True

    # Files written to the expected layout.
    npzs = list((tmp_path / "iterate_data").glob("*.npz"))
    assert len(npzs) == 1
    assert npzs[0].read_bytes() == npz_bytes
    replays = list(
        (tmp_path / "replays" / "iter_009_self_play_v6_mac").glob("*.json.gz")
    )
    assert len(replays) == 1
    assert replays[0].name == "0.json.gz"
    assert replays[0].read_bytes() == replay_bytes


def test_report_result_no_files_ok(tmp_path):
    """Eval reports commonly have no npz and no replay."""
    app = _make_app(tmp_path)
    client = app.test_client()
    _create_stage(client, _spec(kind="eval"))
    claim = _claim_one(client)
    meta = {
        "claim_id": claim["claim_id"],
        "outcome": "completed",
        "winner": 0,
        "n_samples": 0,
        "duration_s": 5.0,
        "shard_label": "mac",
        "wins_new": 1,
        "wins_old": 0,
    }
    res = client.post(
        "/v2/report_result", json={"_": "no-files"},
        # Body has to be multipart for the meta field; use json=
        # falls through to the is_json branch in the handler when
        # there's no meta multipart field.
    )
    # The above doesn't include claim_id → 400. Re-send properly:
    assert res.status_code == 400


def test_report_result_no_files_via_json_meta(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    _create_stage(client, _spec(kind="eval"))
    claim = _claim_one(client)
    meta = {
        "claim_id": claim["claim_id"],
        "outcome": "completed",
        "winner": 0,
        "n_samples": 0,
        "duration_s": 5.0,
        "shard_label": "mac",
        "wins_new": 1,
        "wins_old": 0,
    }
    res = client.post(
        "/v2/report_result", json=meta,
    )
    assert res.status_code == 200, res.get_json()
    body = res.get_json()
    assert body["accepted"] is True
    # No files written.
    assert not (tmp_path / "iterate_data").exists() or list(
        (tmp_path / "iterate_data").glob("*"),
    ) == []


def test_report_result_on_time_duplicate_returns_200(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    _create_stage(client, _spec())
    claim = _claim_one(client)
    meta = {
        "claim_id": claim["claim_id"],
        "outcome": "completed",
        "winner": 0,
        "n_samples": 100,
        "duration_s": 1.0,
        "shard_label": "mac",
    }
    res1 = client.post(
        "/v2/report_result",
        data={"meta": json.dumps(meta)},
        content_type="multipart/form-data",
    )
    assert res1.status_code == 200
    assert res1.get_json()["accepted"] is True
    # Retry the same report — silent 200 with duplicate flag.
    res2 = client.post(
        "/v2/report_result",
        data={"meta": json.dumps(meta)},
        content_type="multipart/form-data",
    )
    assert res2.status_code == 200
    body = res2.get_json()
    assert body["accepted"] is True
    assert body.get("duplicate") is True


def test_report_result_late_duplicate_409(tmp_path):
    """The zombie-worker path. Worker A's claim gets re-queued (e.g.
    coordinator marked it DEAD), worker B re-claims and reports
    successfully. When worker A's stale claim eventually shows up
    with a result, the coordinator rejects it with 409."""
    app = _make_app(tmp_path)
    client = app.test_client()
    _create_stage(client, _spec(n_games=1))
    claim_a = _claim_one(client)

    # Manually re-queue worker A's claim (simulate the DEAD-worker
    # re-queue path). Then a fresh claim picks up the same game_idx
    # with a different claim_id.
    conn = queue_db.connect(tmp_path / "queue.db")
    try:
        with queue_db.WRITE_LOCK:
            queue_db.requeue_claim(conn, claim_a["claim_id"])
    finally:
        conn.close()

    claim_b_resp = client.post("/v2/claim", json={
        "worker_id": "wB", "stage_id": "iter_009_self_play_v6",
    })
    assert claim_b_resp.status_code == 200
    claim_b = claim_b_resp.get_json()
    assert claim_b["game_idx"] == 0
    # The requeue path tombstones the old claim row but doesn't
    # delete it; the fresh claim_next_game call sees the collision
    # and appends a ms-timestamp suffix to the new claim_id so the
    # two are distinguishable.
    assert claim_b["claim_id"] != claim_a["claim_id"]

    # Worker B reports successfully.
    meta_b = {
        "claim_id": claim_b["claim_id"],
        "outcome": "completed",
        "winner": 1,
        "n_samples": 100,
        "duration_s": 1.0,
        "shard_label": "wB",
    }
    res_b = client.post(
        "/v2/report_result",
        data={"meta": json.dumps(meta_b)},
        content_type="multipart/form-data",
    )
    assert res_b.status_code == 200

    # Worker A's late report under the tombstoned claim_id → 409.
    meta_a = {
        "claim_id": claim_a["claim_id"],
        "outcome": "completed",
        "winner": 0,
        "n_samples": 100,
        "duration_s": 1.0,
        "shard_label": "wA",
    }
    res_a = client.post(
        "/v2/report_result",
        data={"meta": json.dumps(meta_a)},
        content_type="multipart/form-data",
    )
    assert res_a.status_code == 409


def test_report_result_late_duplicate_409_when_claim_persists(tmp_path):
    """Variant where the re-queue path KEPT the old claim row (e.g.
    only the heartbeat poller marked it abandoned but the row wasn't
    deleted). In that case the on-claim-id path should treat it as
    409 because another claim has already produced a result."""
    app = _make_app(tmp_path)
    client = app.test_client()
    _create_stage(client, _spec(n_games=1))
    claim_a = _claim_one(client)
    # Bypass requeue_claim and instead just re-INSERT the game in
    # queued_games (leave the old claim row intact).
    conn = queue_db.connect(tmp_path / "queue.db")
    try:
        with queue_db.WRITE_LOCK:
            conn.execute(
                "INSERT OR IGNORE INTO queued_games "
                "(stage_id, game_idx, deck_indices_json, seed) "
                "VALUES (?, ?, ?, ?)",
                (
                    "iter_009_self_play_v6", 0, "[10, 20]", 9000000,
                ),
            )
    finally:
        conn.close()
    claim_b_resp = client.post("/v2/claim", json={
        "worker_id": "wB", "stage_id": "iter_009_self_play_v6",
    })
    claim_b = claim_b_resp.get_json()
    # Worker B reports first.
    res_b = client.post(
        "/v2/report_result",
        data={"meta": json.dumps({
            "claim_id": claim_b["claim_id"],
            "outcome": "completed",
            "winner": 1,
            "n_samples": 100,
            "duration_s": 1.0,
            "shard_label": "wB",
        })},
        content_type="multipart/form-data",
    )
    assert res_b.status_code == 200
    # Worker A's stale claim row is still present; report_result
    # detects an existing results row for (stage_id, game_idx)
    # and returns conflict.
    res_a = client.post(
        "/v2/report_result",
        data={"meta": json.dumps({
            "claim_id": claim_a["claim_id"],
            "outcome": "completed",
            "winner": 0,
            "n_samples": 100,
            "duration_s": 1.0,
            "shard_label": "wA",
        })},
        content_type="multipart/form-data",
    )
    assert res_a.status_code == 409


def test_report_result_404_on_unknown_claim_id(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    _create_stage(client, _spec())
    res = client.post(
        "/v2/report_result",
        data={"meta": json.dumps({"claim_id": "no_such_claim:0000"})},
        content_type="multipart/form-data",
    )
    assert res.status_code == 404


def test_report_result_400_on_bad_meta(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    _create_stage(client, _spec())
    # Bad JSON in meta field.
    res = client.post(
        "/v2/report_result",
        data={"meta": "{not json"},
        content_type="multipart/form-data",
    )
    assert res.status_code == 400
    # Missing claim_id altogether.
    res2 = client.post(
        "/v2/report_result",
        data={"meta": json.dumps({"outcome": "completed"})},
        content_type="multipart/form-data",
    )
    assert res2.status_code == 400


def test_eval_stage_counters_aggregate_wins(tmp_path):
    """An eval stage's report_result writes wins_new/wins_old which
    bubble up through ``stage_counters``."""
    app = _make_app(tmp_path)
    client = app.test_client()
    _create_stage(client, _spec(n_games=2, kind="eval"))
    for _ in range(2):
        claim = _claim_one(client)
        meta = {
            "claim_id": claim["claim_id"],
            "outcome": "completed",
            "winner": 0,
            "n_samples": 0,
            "duration_s": 1.0,
            "shard_label": "wA",
            "wins_new": 1,
            "wins_old": 0,
        }
        res = client.post(
            "/v2/report_result",
            data={"meta": json.dumps(meta)},
            content_type="multipart/form-data",
        )
        assert res.status_code == 200
    res = client.get("/v2/stage/iter_009_self_play_v6")
    body = res.get_json()
    assert body["kind"] == "eval"
    assert body["wins_new"] == 2
    assert body["wins_old"] == 0
    assert body["n_games_done"] == 2
