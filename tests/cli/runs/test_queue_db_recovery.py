"""Coordinator-restart recovery: expired in-flight claims re-queue.

Simulates the "coordinator crashes mid-stage" path documented in
``docs/DISTRIBUTED_RUN_FLOW.md``. Workflow:

1. Build a queue.db with one stage, hand out a claim with a long TTL
   to one worker.
2. Roll the wall clock forward past the claim's TTL (by passing a
   future ``now_unix`` to :func:`queue_db.requeue_expired_claims`).
3. Spin up a fresh ``serve.create_app`` against the same queue.db —
   the boot path calls :func:`queue_db.requeue_expired_claims`, so
   the next ``/v2/claim`` should hand out the expired game again.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

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


def _spec():
    return {
        "stage_id": "iter_009_self_play_v6",
        "kind": "self_play",
        "weights": {"p0": "v5", "p1": "v5"},
        "nodes": 200,
        "samples": 4,
        "per_game_timeout_sec": 600.0,
        "capture_every": 20,
        # Use a short TTL (1s) so we can advance past it cheaply.
        "claim_ttl_seconds": 1,
        "games": [
            {"game_idx": 0, "deck_indices": [10, 20], "seed": 9000000},
        ],
    }


def test_expired_claim_is_requeued_on_recovery(tmp_path):
    # First boot: create stage, claim the only game.
    app1 = _make_app(tmp_path)
    client1 = app1.test_client()
    client1.post("/v2/stage/create", json=_spec())
    claim_resp = client1.post("/v2/claim", json={
        "worker_id": "wA", "stage_id": "iter_009_self_play_v6",
    })
    assert claim_resp.status_code == 200
    # Queue should now be empty until the TTL expires + recovery runs.
    res = client1.post("/v2/claim", json={
        "worker_id": "wB", "stage_id": "iter_009_self_play_v6",
    })
    assert res.status_code == 204

    # Roll the wall clock forward past the TTL by directly invoking
    # requeue_expired_claims with a far-future now_unix.
    conn = queue_db.connect(tmp_path / "queue.db")
    try:
        with queue_db.WRITE_LOCK:
            n = queue_db.requeue_expired_claims(
                conn, now_unix=time.time() + 3600,
            )
        assert n == 1
    finally:
        conn.close()

    # Fresh app against the same queue.db simulates the coordinator
    # restart; the boot path runs requeue_expired_claims a second
    # time (idempotent — no expired claims left).
    app2 = _make_app(tmp_path)
    client2 = app2.test_client()
    res = client2.post("/v2/claim", json={
        "worker_id": "wB", "stage_id": "iter_009_self_play_v6",
    })
    assert res.status_code == 200
    body = res.get_json()
    assert body["game_idx"] == 0


def test_expired_claim_is_requeued_lazily_on_next_claim(tmp_path):
    """No coordinator restart needed: once a claim's TTL lapses, the
    next ``/v2/claim`` that would otherwise answer 204 sweeps it back
    into the queue and hands it out. Regression for the 2026-09-25
    stall where a flapping worker held game 1499/1500 past its TTL
    and the stage never completed because the sweep only ran at boot."""
    app = _make_app(tmp_path)
    client = app.test_client()
    client.post("/v2/stage/create", json=_spec())  # claim_ttl_seconds=1
    first = client.post("/v2/claim", json={
        "worker_id": "wA", "stage_id": "iter_009_self_play_v6",
    })
    assert first.status_code == 200
    # Not yet expired: the queue is genuinely empty.
    res = client.post("/v2/claim", json={
        "worker_id": "wB", "stage_id": "iter_009_self_play_v6",
    })
    assert res.status_code == 204
    # Let the 1s TTL lapse (expires_at has whole-second resolution,
    # and the sweep uses strict '<', so wait past the next tick).
    time.sleep(2.1)
    res = client.post("/v2/claim", json={
        "worker_id": "wB", "stage_id": "iter_009_self_play_v6",
    })
    assert res.status_code == 200, res.data
    body = res.get_json()
    assert body["game_idx"] == 0
    # And it is a fresh claim (new claim owner), not the stale one.
    conn = queue_db.connect(tmp_path / "queue.db")
    try:
        rows = conn.execute(
            "SELECT worker_id, reported FROM claims "
            "WHERE stage_id = ? ORDER BY claimed_at",
            ("iter_009_self_play_v6",),
        ).fetchall()
    finally:
        conn.close()
    assert [r["worker_id"] for r in rows][-1] == "wB"


def test_recovery_path_runs_on_startup(tmp_path):
    """The serve.create_app factory itself runs requeue_expired_claims
    once at boot."""
    # Bootstrap a queue.db with one expired claim BEFORE building
    # the app. Direct DB writes, no REST.
    db_path = tmp_path / "queue.db"
    conn = queue_db.connect(db_path)
    try:
        queue_db.insert_stage(
            conn,
            stage_id="stage_x",
            kind="self_play",
            spec_json=json.dumps({
                "games": [{
                    "game_idx": 0,
                    "deck_indices": [1, 2],
                    "seed": 42,
                }],
            }),
            claim_ttl_seconds=1,
            games=[{
                "game_idx": 0,
                "deck_indices": [1, 2],
                "seed": 42,
            }],
        )
        # Manually insert an expired claim row (no queued_games row
        # — that was popped in the original claim).
        conn.execute(
            "INSERT INTO claims "
            "(claim_id, stage_id, game_idx, worker_id, "
            " claimed_at, expires_at, reported) "
            "VALUES (?, ?, ?, ?, ?, ?, 0)",
            (
                "stage_x:000000", "stage_x", 0, "wA",
                "1970-01-01T00:00:00Z", "1970-01-01T00:00:01Z",
            ),
        )
        # The corresponding queued_games row was already deleted by
        # claim_next_game when we'd normally have called it; emulate
        # that state.
        conn.execute(
            "DELETE FROM queued_games WHERE stage_id = 'stage_x'",
        )
    finally:
        conn.close()

    # Boot the app.
    app = _make_app(tmp_path)
    client = app.test_client()
    # The expired claim should have been re-queued; a fresh claim
    # call returns the game.
    res = client.post("/v2/claim", json={
        "worker_id": "wB", "stage_id": "stage_x",
    })
    assert res.status_code == 200
    body = res.get_json()
    assert body["game_idx"] == 0
