"""Tests for the coordinator-side HeartbeatPoller.

We exercise:

- Config loading (post-cutover ``worker_urls`` shape only; legacy
  ``shards`` / ``workers`` shapes raise ``LegacyShardsConfigError``).
- One full poll cycle against a fake worker that returns a heartbeat
  payload; ``last_heartbeat_at`` + ``last_heartbeat_payload`` update.
- Liveness transitions ALIVE → STALE → DEAD as the clock advances
  without fresh heartbeats.
- DEAD transition triggers the queue.db re-queue path for that
  worker's in-flight claims.
- DEAD → ALIVE on heartbeat resumption clears the in-flight set
  (the worker restarted IDLE).
- ``--no-heartbeat-poller`` skips the thread entirely.

The fake worker is a local Flask app on an ephemeral port. We use a
``http_get`` injection to bypass the real urllib path and steer at a
captured-response stub — that's enough to verify the poller's
state-machine logic without bringing up a server. (One end-to-end
test does stand up a real Flask server to lock down the URL
construction.)
"""

from __future__ import annotations

import json
import socket
import threading
from pathlib import Path
from typing import Any

import pytest
from flask import Flask, jsonify

from mtg_bot.cli import serve as serve_mod
from mtg_bot.cli.runs import queue_db
from mtg_bot.cli.runs.heartbeat_poller import (
    HeartbeatPoller,
    LegacyShardsConfigError,
    load_shards_config,
)


# ---- config loader --------------------------------------------------------


def test_load_shards_config_worker_urls_shape(tmp_path):
    """Post-cutover shape: ``{"worker_urls": [<str>, ...]}``."""
    cfg = tmp_path / "shards.json"
    cfg.write_text(json.dumps({
        "worker_urls": [
            "http://desktop:5198",
            "http://mac:5198",
        ],
    }))
    entries = load_shards_config(cfg)
    assert len(entries) == 2
    assert entries[0] == {"worker_url": "http://desktop:5198"}
    assert entries[1] == {"worker_url": "http://mac:5198"}


def test_load_shards_config_legacy_shards_raises(tmp_path):
    """Legacy ``{shards: [...]}`` (SSH era) is rejected with a clear
    migration message."""
    cfg = tmp_path / "shards.json"
    cfg.write_text(json.dumps({
        "shards": [
            {"host": "h1", "user": "u1", "repo_path": "/x"},
        ],
    }))
    with pytest.raises(LegacyShardsConfigError, match="legacy shards_config"):
        load_shards_config(cfg)


def test_load_shards_config_legacy_workers_raises(tmp_path):
    """The transitional ``{workers: [{worker_id, worker_url,
    n_workers}]}`` shape is also rejected — operators must migrate to
    the URL-only ``worker_urls`` shape."""
    cfg = tmp_path / "shards.json"
    cfg.write_text(json.dumps({
        "workers": [
            {"worker_id": "x", "worker_url": "http://x:5198", "n_workers": 1},
        ],
    }))
    with pytest.raises(LegacyShardsConfigError, match="legacy shards_config"):
        load_shards_config(cfg)


def test_load_shards_config_worker_urls_must_be_list(tmp_path):
    cfg = tmp_path / "shards.json"
    cfg.write_text(json.dumps({"worker_urls": "not-a-list"}))
    with pytest.raises(ValueError, match="must be a list"):
        load_shards_config(cfg)


def test_load_shards_config_missing_file(tmp_path):
    assert load_shards_config(tmp_path / "missing.json") == []


def test_load_shards_config_malformed(tmp_path):
    cfg = tmp_path / "shards.json"
    cfg.write_text("{not json")
    assert load_shards_config(cfg) == []


def test_load_shards_config_unknown_shape_returns_empty(tmp_path):
    cfg = tmp_path / "shards.json"
    cfg.write_text(json.dumps({"foo": "bar"}))
    assert load_shards_config(cfg) == []


# ---- liveness transitions -------------------------------------------------


class _FakeClock:
    def __init__(self, t: float = 0.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def _bootstrap_queue_db(tmp_path: Path) -> Path:
    """Create a queue.db with one stage + one in-flight claim held by
    worker ``wA`` at ``http://wA:5198``."""
    db_path = tmp_path / "queue.db"
    conn = queue_db.connect(db_path)
    try:
        queue_db.insert_stage(
            conn,
            stage_id="stage_x",
            kind="self_play",
            spec_json=json.dumps({
                "games": [{
                    "game_idx": 0, "deck_indices": [1, 2], "seed": 42,
                }],
            }),
            claim_ttl_seconds=1200,
            games=[{"game_idx": 0, "deck_indices": [1, 2], "seed": 42}],
        )
        # claim_next_game would pop the queued row + write claims.
        # Do that directly so test setup mirrors the in-flight state.
        with queue_db.WRITE_LOCK:
            conn.execute(
                "DELETE FROM queued_games WHERE stage_id='stage_x'",
            )
            conn.execute(
                "INSERT INTO claims "
                "(claim_id, stage_id, game_idx, worker_id, "
                " claimed_at, expires_at, reported) "
                "VALUES (?, ?, ?, ?, ?, ?, 0)",
                (
                    "stage_x:000000", "stage_x", 0, "wA",
                    "2026-05-15T00:00:00Z",
                    "2026-05-15T01:00:00Z",
                ),
            )
    finally:
        conn.close()
    return db_path


def _shards_config_with(tmp_path: Path, worker_url: str) -> Path:
    cfg = tmp_path / "shards.json"
    cfg.write_text(json.dumps({
        "worker_urls": [worker_url],
    }))
    return cfg


def test_poller_alive_on_heartbeat(tmp_path):
    db = _bootstrap_queue_db(tmp_path)
    cfg = _shards_config_with(tmp_path, "http://wA:5198")
    clock = _FakeClock(t=100.0)
    responses = {
        "http://wA:5198": {"worker_id": "wA", "state": "SELF_PLAY_RUNNING"},
    }
    poller = HeartbeatPoller(
        queue_db_path=db,
        shards_config_path=cfg,
        poll_interval_s=0.05,
        clock=clock,
        http_get=lambda url, _t: responses.get(url),
    )
    poller.tick()
    states = poller.worker_states()
    assert states["http://wA:5198"]["liveness"] == "ALIVE"
    assert (
        states["http://wA:5198"]["last_heartbeat_payload"]
        == {"worker_id": "wA", "state": "SELF_PLAY_RUNNING"}
    )


def test_poller_stale_then_dead_re_queues_inflight_claims(tmp_path):
    db = _bootstrap_queue_db(tmp_path)
    cfg = _shards_config_with(tmp_path, "http://wA:5198")
    clock = _FakeClock(t=100.0)
    responses = {
        "http://wA:5198": {"worker_id": "wA", "state": "SELF_PLAY_RUNNING"},
    }
    poller = HeartbeatPoller(
        queue_db_path=db,
        shards_config_path=cfg,
        poll_interval_s=0.05,
        clock=clock,
        http_get=lambda url, _t: responses.get(url),
    )
    # First tick: ALIVE.
    poller.tick()
    poller.track_claim("wA", "stage_x:000000")
    assert poller.worker_states()["http://wA:5198"]["liveness"] == "ALIVE"

    # Worker goes silent: subsequent ticks see no payload.
    responses.clear()
    # Advance into STALE band (40s since last hb).
    clock.t = 140.0
    poller.tick()
    assert poller.worker_states()["http://wA:5198"]["liveness"] == "STALE"
    # No re-queue yet — the queued_games row was popped at setup
    # and stays popped.
    conn = queue_db.connect(db)
    try:
        n_queued = conn.execute(
            "SELECT COUNT(*) AS c FROM queued_games WHERE stage_id='stage_x'",
        ).fetchone()["c"]
        assert n_queued == 0
    finally:
        conn.close()

    # Advance past STALE → DEAD (200s since last hb > 90s).
    clock.t = 300.0
    poller.tick()
    assert poller.worker_states()["http://wA:5198"]["liveness"] == "DEAD"
    # DEAD-transition re-queues the in-flight claim.
    conn = queue_db.connect(db)
    try:
        n_queued = conn.execute(
            "SELECT COUNT(*) AS c FROM queued_games WHERE stage_id='stage_x'",
        ).fetchone()["c"]
        assert n_queued == 1
        # Claim row is tombstoned (reported=1 with abandoned flag).
        claim = conn.execute(
            "SELECT reported, report_json FROM claims "
            "WHERE claim_id = 'stage_x:000000'",
        ).fetchone()
        assert claim["reported"] == 1
        assert "abandoned" in claim["report_json"]
    finally:
        conn.close()
    # In-flight set cleared on the DEAD transition.
    assert poller.worker_states()["http://wA:5198"]["in_flight_claim_ids"] == []


def test_poller_dead_to_alive_clears_inflight(tmp_path):
    db = _bootstrap_queue_db(tmp_path)
    cfg = _shards_config_with(tmp_path, "http://wA:5198")
    clock = _FakeClock(t=100.0)
    responses = {"http://wA:5198": None}
    poller = HeartbeatPoller(
        queue_db_path=db,
        shards_config_path=cfg,
        poll_interval_s=0.05,
        clock=clock,
        http_get=lambda url, _t: responses.get(url),
    )
    # First mark ALIVE so we can transit through DEAD.
    responses["http://wA:5198"] = {"worker_id": "wA", "state": "RUNNING"}
    poller.tick()
    poller.track_claim("wA", "stage_x:000000")
    # DEAD.
    responses["http://wA:5198"] = None
    clock.t = 300.0
    poller.tick()
    assert poller.worker_states()["http://wA:5198"]["liveness"] == "DEAD"
    # Worker comes back.
    responses["http://wA:5198"] = {"worker_id": "wA", "state": "IDLE"}
    clock.t = 305.0
    poller.tick()
    state = poller.worker_states()["http://wA:5198"]
    assert state["liveness"] == "ALIVE"
    assert state["in_flight_claim_ids"] == []


def test_poller_track_claim_unknown_worker_is_noop(tmp_path):
    db = _bootstrap_queue_db(tmp_path)
    cfg = _shards_config_with(tmp_path, "http://wA:5198")
    poller = HeartbeatPoller(
        queue_db_path=db,
        shards_config_path=cfg,
        poll_interval_s=0.05,
        http_get=lambda url, _t: None,
    )
    # Unknown worker_id; should be a no-op (no crash, no tracking).
    poller.track_claim("unknown-worker", "stage_x:000000")
    # The worker_url for wA still has no in-flight claims.
    assert (
        poller.worker_states()["http://wA:5198"]["in_flight_claim_ids"]
        == []
    )


def test_untrack_claim_removes_from_all_workers(tmp_path):
    """Post-cutover, worker_id → url mapping is learned from heartbeat
    payloads. A poll cycle has to fire first so the poller knows
    wA lives at http://wA:5198."""
    db = _bootstrap_queue_db(tmp_path)
    cfg = _shards_config_with(tmp_path, "http://wA:5198")
    poller = HeartbeatPoller(
        queue_db_path=db,
        shards_config_path=cfg,
        poll_interval_s=0.05,
        http_get=lambda url, _t: {"worker_id": "wA", "state": "RUNNING"},
    )
    # Tick first so the poller learns wA → http://wA:5198 from the
    # heartbeat payload.
    poller.tick()
    poller.track_claim("wA", "stage_x:000000")
    assert (
        poller.worker_states()["http://wA:5198"]["in_flight_claim_ids"]
        == ["stage_x:000000"]
    )
    poller.untrack_claim("stage_x:000000")
    assert (
        poller.worker_states()["http://wA:5198"]["in_flight_claim_ids"]
        == []
    )


def test_poller_skips_non_string_worker_urls(tmp_path):
    """Non-string entries in worker_urls are silently skipped."""
    db = _bootstrap_queue_db(tmp_path)
    cfg = tmp_path / "shards.json"
    cfg.write_text(json.dumps({
        "worker_urls": [
            None,  # skipped
            "http://wB:5198",
            42,  # skipped
        ],
    }))
    poller = HeartbeatPoller(
        queue_db_path=db,
        shards_config_path=cfg,
        poll_interval_s=0.05,
        http_get=lambda url, _t: None,
    )
    states = poller.worker_states()
    assert list(states.keys()) == ["http://wB:5198"]


# ---- start/stop lifecycle --------------------------------------------------


def test_poller_start_stop(tmp_path):
    db = _bootstrap_queue_db(tmp_path)
    cfg = _shards_config_with(tmp_path, "http://wA:5198")
    calls = []
    poller = HeartbeatPoller(
        queue_db_path=db,
        shards_config_path=cfg,
        poll_interval_s=0.01,
        http_get=lambda url, _t: calls.append(url) or {"state": "IDLE"},
    )
    poller.start()
    # Idempotent: second start() is a no-op while running.
    poller.start()
    # Give it a few cycles.
    import time as _time
    _time.sleep(0.1)
    poller.stop(timeout=1.0)
    assert len(calls) > 0


# ---- end-to-end against a real in-process Flask server ---------------------


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def fake_worker_server():
    """Spin up a tiny Flask app on an ephemeral port that mimics
    ``/v2/heartbeat`` so we can test the default urllib-based
    http_get path end-to-end. Shuts down at the end of the test."""
    app = Flask(__name__)

    @app.route("/v2/heartbeat", methods=["GET"])
    def hb():
        return jsonify({"state": "SELF_PLAY_RUNNING", "uptime_s": 42})

    port = _free_port()
    thread = threading.Thread(
        target=lambda: app.run(
            host="127.0.0.1", port=port, debug=False,
            use_reloader=False,
        ),
        daemon=True,
    )
    thread.start()
    # Wait for the server to bind. Try a few times with backoff.
    import time as _time
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            _time.sleep(0.02)
    yield f"http://127.0.0.1:{port}"
    # No clean shutdown of the Flask dev server is necessary — it's
    # a daemon thread; the test process owns it.


def test_poller_default_http_get_against_real_server(
    tmp_path, fake_worker_server,
):
    db = _bootstrap_queue_db(tmp_path)
    cfg = _shards_config_with(tmp_path, fake_worker_server)
    poller = HeartbeatPoller(
        queue_db_path=db,
        shards_config_path=cfg,
        poll_interval_s=0.05,
        http_timeout_s=2.0,
    )
    poller.tick()
    states = poller.worker_states()
    payload = states[fake_worker_server]["last_heartbeat_payload"]
    assert payload is not None
    assert payload["state"] == "SELF_PLAY_RUNNING"
    assert states[fake_worker_server]["liveness"] == "ALIVE"


def test_poller_default_http_get_returns_none_on_unreachable(
    tmp_path,
):
    db = _bootstrap_queue_db(tmp_path)
    bogus = "http://127.0.0.1:1"  # nothing listening
    cfg = _shards_config_with(tmp_path, bogus)
    poller = HeartbeatPoller(
        queue_db_path=db,
        shards_config_path=cfg,
        poll_interval_s=0.05,
        http_timeout_s=0.2,
    )
    poller.tick()
    states = poller.worker_states()
    # last_heartbeat_at stays None; liveness stays UNKNOWN.
    assert states[bogus]["last_heartbeat_at"] is None
    assert states[bogus]["liveness"] == "UNKNOWN"


# ---- integration with serve.create_app ------------------------------------


def test_no_heartbeat_poller_flag_skips_thread(tmp_path):
    app = serve_mod.create_app(
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
    assert "v2_heartbeat_poller" not in app.extensions


def test_default_create_app_starts_heartbeat_poller(tmp_path):
    cfg = tmp_path / "shards.json"
    cfg.write_text(json.dumps({"worker_urls": []}))
    app = serve_mod.create_app(
        repo_url="https://example.test/mtg-bot.git",
        master_pubkey="ssh-ed25519 KEY",
        master_tailnet_name="myhost",
        port=5099,
        queue_db_path=tmp_path / "queue.db",
        weights_root=tmp_path / "trained_weights",
        iterate_data_dir=tmp_path / "iterate_data",
        replays_root=tmp_path / "replays",
        shards_config_path=cfg,
        enable_heartbeat_poller=True,
        heartbeat_poll_interval_s=10.0,
    )
    poller = app.extensions.get("v2_heartbeat_poller")
    assert poller is not None
    poller.stop(timeout=2.0)
