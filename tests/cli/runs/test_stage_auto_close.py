"""Tests for coordinator-side auto-close of stages.

The contract: a stage's ``status`` flips from ``running`` →
``complete`` automatically when every ``game_idx`` has a row in the
results table AND no claims for the stage are still in-flight. No
external watcher / explicit ``POST /v2/stage/<id>/close`` call is
required for the natural-drain path.

These tests pair with :file:`test_v2_stage_close.py`, which covers
the explicit-close (early-stop) path. They share the same fixture
shape but exercise the auto-close trigger inside
``/v2/report_result``.
"""

from __future__ import annotations

import json
from pathlib import Path

from mtg_bot.cli import serve as serve_mod
from mtg_bot.cli.runs import queue_db


def _make_app(tmp_path: Path):
    # Sync dispatch (``report_executor=None``) so the auto-close
    # transition is observable on the next GET without racing the
    # background thread pool.
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
        report_executor=None,
    )


def _spec(*, n_games: int = 3, stage_id: str = "iter_009_self_play_v6"):
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


def _claim(client, stage_id: str, worker_id: str = "wA"):
    res = client.post(
        "/v2/claim",
        json={"worker_id": worker_id, "stage_id": stage_id},
    )
    assert res.status_code == 200, res.get_data(as_text=True)
    return res.get_json()


def _report(client, claim_id: str, *, outcome: str = "completed",
            winner: int | None = 0, shard_label: str = "wA"):
    # Phase 2B: JSON-only body; no npz/replay URIs needed for
    # auto-close tests (they only care about the results-row
    # bookkeeping the handler does post-fetch).
    return client.post(
        "/v2/report_result",
        json={"meta": {
            "claim_id": claim_id,
            "outcome": outcome,
            "winner": winner,
            "n_samples": 0,
            "duration_s": 1.0,
            "shard_label": shard_label,
        }},
    )


# ---- happy path ----------------------------------------------------------


def test_stage_auto_closes_when_all_games_report(tmp_path):
    """Report all 3 games; stage flips to ``complete`` without any
    /close call. ``complete_at`` is populated; ``drained_at`` stays
    None (natural-drain path skips the drained intermediate state)."""
    app = _make_app(tmp_path)
    client = app.test_client()
    stage_id = "iter_auto_basic"
    client.post("/v2/stage/create", json=_spec(n_games=3, stage_id=stage_id))
    for _ in range(3):
        claim = _claim(client, stage_id)
        res = _report(client, claim["claim_id"])
        assert res.status_code == 202
    body = client.get(f"/v2/stage/{stage_id}").get_json()
    assert body["status"] == "complete"
    assert body["complete_at"] is not None
    # Natural-drain skips the explicit drain step; drained_at stays None.
    assert body["drained_at"] is None
    assert body["n_games_done"] == 3
    assert body["n_games_in_flight"] == 0


def test_stage_does_not_auto_close_while_in_flight(tmp_path):
    """Report 2 of 3 games; the third claim is outstanding (held by a
    worker, not reported, not expired). Stage status stays
    ``running``; auto-close must wait for the last in-flight to land."""
    app = _make_app(tmp_path)
    client = app.test_client()
    stage_id = "iter_auto_inflight"
    client.post("/v2/stage/create", json=_spec(n_games=3, stage_id=stage_id))
    claim_a = _claim(client, stage_id, worker_id="wA")
    claim_b = _claim(client, stage_id, worker_id="wB")
    claim_c = _claim(client, stage_id, worker_id="wC")
    # Two report; the third stays in-flight.
    assert _report(client, claim_a["claim_id"], shard_label="wA").status_code == 202
    assert _report(client, claim_b["claim_id"], shard_label="wB").status_code == 202
    body = client.get(f"/v2/stage/{stage_id}").get_json()
    assert body["status"] == "running"
    assert body["complete_at"] is None
    assert body["n_games_done"] == 2
    assert body["n_games_in_flight"] == 1
    # Land the last one — now it auto-closes.
    assert _report(client, claim_c["claim_id"], shard_label="wC").status_code == 202
    body = client.get(f"/v2/stage/{stage_id}").get_json()
    assert body["status"] == "complete"
    assert body["complete_at"] is not None


def test_auto_close_handles_drained_stage(tmp_path):
    """Explicit /close arrives first (status → drained), then the last
    in-flight game reports. Final state is ``complete`` with BOTH
    ``drained_at`` AND ``complete_at`` populated — the explicit-close
    timestamp survives the auto-close transition."""
    app = _make_app(tmp_path)
    client = app.test_client()
    stage_id = "iter_auto_drained"
    client.post("/v2/stage/create", json=_spec(n_games=2, stage_id=stage_id))
    claim_a = _claim(client, stage_id, worker_id="wA")
    claim_b = _claim(client, stage_id, worker_id="wB")
    # Report only the first; the second is in-flight when /close fires.
    assert _report(client, claim_a["claim_id"], shard_label="wA").status_code == 202
    close_res = client.post(
        f"/v2/stage/{stage_id}/close",
        json={"reason": "early_stop_pass"},
    )
    assert close_res.status_code == 200
    body = client.get(f"/v2/stage/{stage_id}").get_json()
    assert body["status"] == "drained"
    assert body["drained_at"] is not None
    assert body["complete_at"] is None
    # The last in-flight claim reports back; auto-close finishes the job.
    assert _report(client, claim_b["claim_id"], shard_label="wB").status_code == 202
    body = client.get(f"/v2/stage/{stage_id}").get_json()
    assert body["status"] == "complete"
    assert body["drained_at"] is not None
    assert body["complete_at"] is not None


def test_auto_close_idempotent_under_late_duplicate_reports(tmp_path):
    """All N report, stage auto-closes. A late-duplicate report under
    the same claim_id is rejected with ``409 Conflict`` (Phase 2B
    cutover: the handler short-circuits before enqueueing the
    background job when the claim is already reported) — it must
    not reopen / re-trigger auto-close. ``complete_at`` is unchanged
    after the duplicate."""
    app = _make_app(tmp_path)
    client = app.test_client()
    stage_id = "iter_auto_dup"
    client.post("/v2/stage/create", json=_spec(n_games=2, stage_id=stage_id))
    claim_a = _claim(client, stage_id, worker_id="wA")
    claim_b = _claim(client, stage_id, worker_id="wB")
    assert _report(client, claim_a["claim_id"]).status_code == 202
    assert _report(client, claim_b["claim_id"]).status_code == 202
    body = client.get(f"/v2/stage/{stage_id}").get_json()
    assert body["status"] == "complete"
    first_complete_at = body["complete_at"]
    assert first_complete_at is not None
    # Duplicate of an already-reported claim → 409 (sync rejection).
    dup = _report(client, claim_a["claim_id"])
    assert dup.status_code == 409
    body = client.get(f"/v2/stage/{stage_id}").get_json()
    assert body["status"] == "complete"
    assert body["complete_at"] == first_complete_at


def test_auto_close_with_crashed_and_timed_out_results(tmp_path):
    """``crashed`` and ``timed_out`` are terminal outcomes — they
    count toward "done" the same as ``completed`` for the auto-close
    trigger. Mixed outcomes still close the stage."""
    app = _make_app(tmp_path)
    client = app.test_client()
    stage_id = "iter_auto_mixed"
    client.post("/v2/stage/create", json=_spec(n_games=3, stage_id=stage_id))
    claim_a = _claim(client, stage_id, worker_id="wA")
    claim_b = _claim(client, stage_id, worker_id="wB")
    claim_c = _claim(client, stage_id, worker_id="wC")
    assert _report(client, claim_a["claim_id"], outcome="completed").status_code == 202
    assert _report(
        client, claim_b["claim_id"], outcome="crashed", winner=None,
    ).status_code == 202
    assert _report(
        client, claim_c["claim_id"], outcome="timed_out", winner=None,
    ).status_code == 202
    body = client.get(f"/v2/stage/{stage_id}").get_json()
    assert body["status"] == "complete"
    assert body["n_games_done"] == 3
    assert body["crashed"] == 1
    assert body["timed_out"] == 1
    assert body["complete_at"] is not None


# ---- abandoned-tombstone accounting --------------------------------------


def test_auto_close_does_not_count_abandoned_claim_tombstones(tmp_path):
    """An abandoned-tombstone claim (TTL-expired or DEAD-worker
    re-queue) is NOT a terminal report. The underlying game goes
    back on the queue under a fresh claim_id; until *that* reports
    back, the stage is not done.

    This pins the design decision: the auto-close ``done`` count is
    "every ``game_idx`` has a results row," NOT "every claim_id is
    reported (including abandoned tombstones)."
    """
    app = _make_app(tmp_path)
    client = app.test_client()
    stage_id = "iter_auto_tomb"
    client.post("/v2/stage/create", json=_spec(n_games=2, stage_id=stage_id))
    # Worker A grabs both games.
    claim_a = _claim(client, stage_id, worker_id="wA")
    claim_b = _claim(client, stage_id, worker_id="wA")
    # Worker A abandons claim_b (e.g. TTL-expired / DEAD).
    db_path = tmp_path / "queue.db"
    conn = queue_db.connect(db_path)
    try:
        requeued = queue_db.requeue_claim(conn, claim_b["claim_id"])
        assert requeued is True
    finally:
        conn.close()
    # Reporting claim_a alone is not enough — game_idx 1 still has no
    # results row, even though claim_b is tombstoned with reported=1.
    assert _report(client, claim_a["claim_id"]).status_code == 202
    body = client.get(f"/v2/stage/{stage_id}").get_json()
    assert body["status"] == "running", (
        "abandoned-tombstone claim must not count toward done"
    )
    assert body["n_games_done"] == 1
    # Re-claim + report the re-queued game; now the stage closes.
    claim_b2 = _claim(client, stage_id, worker_id="wB")
    assert claim_b2["game_idx"] == 1
    assert _report(client, claim_b2["claim_id"], shard_label="wB").status_code == 202
    body = client.get(f"/v2/stage/{stage_id}").get_json()
    assert body["status"] == "complete"
    assert body["n_games_done"] == 2


# ---- degenerate empty-stage case -----------------------------------------


def test_empty_stage_is_auto_closed_at_creation(tmp_path):
    """``games: []`` is the degenerate corner — zero work, "already
    drained." The auto-close fires inside ``insert_stage`` so the
    orchestrator's very first ``GET /v2/stage/<id>`` reads
    ``status: 'complete'``.

    Note: the v2 endpoint validates ``games[]`` as non-empty, so we
    exercise this purely at the ``queue_db`` layer where the
    invariant lives.
    """
    db_path = tmp_path / "queue.db"
    conn = queue_db.connect(db_path)
    try:
        queue_db.insert_stage(
            conn,
            stage_id="empty_stage",
            kind="self_play",
            spec_json=json.dumps({"games": []}),
            claim_ttl_seconds=1200,
            games=[],
        )
        counters = queue_db.stage_counters(conn, "empty_stage")
    finally:
        conn.close()
    assert counters is not None
    assert counters["status"] == "complete"
    assert counters["n_games_total"] == 0
    assert counters["n_games_done"] == 0
    assert counters["complete_at"] is not None


# ---- direct queue_db unit tests ------------------------------------------


def test_maybe_auto_close_stage_no_op_when_already_complete(tmp_path):
    """Calling ``_maybe_auto_close_stage`` on a stage that's already
    ``complete`` must not touch the row — ``complete_at`` is stable."""
    db_path = tmp_path / "queue.db"
    conn = queue_db.connect(db_path)
    try:
        queue_db.insert_stage(
            conn,
            stage_id="already_done",
            kind="self_play",
            spec_json=json.dumps({"games": []}),
            claim_ttl_seconds=1200,
            games=[],
        )
        first = queue_db.get_stage(conn, "already_done")
        original_complete_at = first["complete_at"]
        # Second call should be a true no-op.
        queue_db._maybe_auto_close_stage(conn, "already_done")
        after = queue_db.get_stage(conn, "already_done")
        assert after["complete_at"] == original_complete_at
        assert after["status"] == "complete"
    finally:
        conn.close()


def test_maybe_auto_close_stage_handles_unknown_stage(tmp_path):
    """Unknown stage_id is a silent no-op — never raises."""
    db_path = tmp_path / "queue.db"
    conn = queue_db.connect(db_path)
    try:
        # Should not raise; no row to update is fine.
        queue_db._maybe_auto_close_stage(conn, "does_not_exist")
    finally:
        conn.close()
