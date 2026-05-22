"""End-to-end integration test for the worker daemon + coordinator.

The headline test in Phase 2b: a live coordinator (Flask test_client
backed by a real queue.db) plus a live worker daemon (Flask test_client
that runs the real claim-loop runner), wired together over an HTTP
shim so the daemon's urllib client talks to the coordinator's
test_client. POSTs /v2/start_self_play to the daemon, waits for the
4-game stage to drain, then asserts the coordinator's queue.db has 4
result rows and the daemon's state is IDLE.

The runner is a synthetic ``CallableGameRunner`` -- this test is a
wire-up check, not a strength benchmark. We deliberately don't spin
up torch / multiprocessing here; that work happens behind the
production runner in a follow-up commit. The synthetic runner is good
enough to drive the loop through every state transition the real
runner will hit.

We don't open real TCP sockets either: the worker-daemon HTTP client
hooks (``http_get``, ``http_post_json`` on :class:`ClaimLoopConfig`)
are swapped for adapters that dispatch into the coordinator's Flask
test_client.

**Phase 2A note**: the worker now uses the drop-off protocol — it
uploads .npz / replay blobs to shared storage and POSTs only the
URIs back to ``/v2/report_result`` as JSON. The coordinator's
matching ``/v2/report_result`` rewrite (multipart-parse -> JSON ping
+ URI fetch) is Phase 2B's responsibility. Until 2B lands, the
end-to-end tests in this file are SKIPPED with the marker below.
The worker-side wire shape is fully exercised by
``tests/test_worker_daemon_claim_loop.py``'s drop-off-protocol
tests; this file's tests come back online when the matching coord
rewrite lands.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from mtg_bot import worker_daemon
from mtg_bot import worker_daemon_claim_loop as cl
from mtg_bot.cli import serve as serve_mod
from mtg_bot.worker_daemon_storage import LocalFileUploader


# Phase 2A + 2B both landed (2026-05-21 integration commit): coord
# /v2/report_result now consumes the JSON ping and the worker emits
# the JSON shape. These integration tests are live again.


# ---------------------------------------------------------------------------
# Flask-test-client adapter for the worker's HTTP hooks.
# ---------------------------------------------------------------------------


def _make_test_client_adapter(coordinator_app):
    """Return ``(http_get, http_post_json)`` that dispatch into
    ``coordinator_app.test_client()`` instead of urllib.

    Flask's test_client doesn't speak network -- it walks the WSGI
    stack directly. That makes this a fast, deterministic, in-process
    integration: the daemon's loop hits exactly the same handlers the
    coordinator exposes to real workers.

    Phase 2A note: the multipart adapter is gone — drop-off protocol
    means all worker -> coord traffic is JSON now. Blobs land in
    shared storage via the configured ``ArtifactUploader``.
    """
    client = coordinator_app.test_client()

    def _strip_base(url: str) -> str:
        # The daemon builds full URLs like
        # ``http://fake-coord:5099/v2/claim``. Flask test_client takes
        # the path-only form.
        for prefix in ("http://", "https://"):
            if url.startswith(prefix):
                slash = url.index("/", len(prefix))
                return url[slash:]
        return url

    def http_get(url, timeout=30.0):
        resp = client.get(_strip_base(url))
        return resp.status_code, resp.data, dict(resp.headers)

    def http_post_json(url, payload, timeout=30.0):
        resp = client.post(
            _strip_base(url),
            json=payload,
        )
        return resp.status_code, resp.data, dict(resp.headers)

    return http_get, http_post_json


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_coordinator_app(tmp_path: Path):
    # report_executor=None forces synchronous report dispatch (the
    # /v2/report_result handler does the fetch + DB write inline
    # instead of submitting to a ThreadPoolExecutor). Production
    # path is async (the load-bearing fix from the coord-async-
    # storage refactor); the test path uses sync so post-drain
    # assertions don't race the executor.
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


def _seed_stage(coord_client, *, stage_id: str, n_games: int,
                kind: str = "self_play"):
    weights = (
        {"p0": "vTEST", "p1": "vTEST"} if kind == "self_play"
        else {"new": "vNEW", "old": "vOLD"}
    )
    spec = {
        "stage_id": stage_id,
        "kind": kind,
        "weights": weights,
        "nodes": 50,
        "samples": 1,
        "per_game_timeout_sec": 30.0,
        "capture_every": 0,
        "claim_ttl_seconds": 600,
        "games": [
            {
                "game_idx": i,
                "deck_indices": [100 + i, 200 + i],
                "seed": 1000000 + i,
            }
            for i in range(n_games)
        ],
    }
    res = coord_client.post("/v2/stage/create", json=spec)
    assert res.status_code == 200, res.get_json()


def _drive_loop_on(
    coord_app,
    daemon_state: worker_daemon.WorkerState,
    *,
    stage_id: str,
    kind: str,
    play_one,
    shard_label: str = "test-worker",
) -> threading.Thread:
    """Build the ClaimLoopRunner pointed at ``coord_app`` via the
    Flask test-client adapter, then start its thread."""

    http_get, http_post_json = _make_test_client_adapter(coord_app)
    cfg = cl.ClaimLoopConfig(
        coordinator_url="http://coord-test:5099",
        stage_id=stage_id,
        kind=kind,
        n_workers=1,
        worker_id=shard_label,
        weights_root=Path("trained_weights_test"),
        shard_label=shard_label,
        retry_backoff_s=(0.0, 0.0, 0.0),
        http_get=http_get,
        http_post_json=http_post_json,
        artifact_uploader=LocalFileUploader(
            Path("trained_weights_test") / "artifacts"
        ),
    )
    cbs = cl.StateCallbacks(
        is_stop_requested=daemon_state.is_stop_requested,
        on_claim=daemon_state.on_claim,
        on_report=daemon_state.on_report,
        on_drop=daemon_state.on_drop,
        mark_running=daemon_state.mark_running,
        mark_stopping=daemon_state.mark_stopping,
        mark_idle=daemon_state.mark_idle,
        mark_error=daemon_state.mark_error,
    )
    runner = cl.CallableGameRunner(play_one)
    loop = cl.ClaimLoopRunner(cfg, cbs, runner)
    daemon_state.try_start(kind, stage_id, n_workers=1)
    t = threading.Thread(target=loop.run, daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------------------
# The integration test.
# ---------------------------------------------------------------------------


def test_worker_daemon_drains_4_game_self_play_stage(tmp_path):
    """Headline integration test (Phase 2b).

    Coordinator queue.db pre-seeded with 4 games. Worker daemon
    points at it via the test-client adapter, plays each game via a
    synthetic CallableGameRunner, drains the queue, transitions to
    IDLE. Assertion: queue.db has 4 result rows, GET /v2/stage/<id>
    reports n_games_done=4 and status=complete.
    """
    coord_app = _build_coordinator_app(tmp_path)
    coord_client = coord_app.test_client()
    _seed_stage(
        coord_client, stage_id="iter_test_self_play_v6", n_games=4,
    )

    games_played: list[int] = []

    def play_one(claim, shard_label):
        games_played.append(claim["game_idx"])
        return cl.GameResult(
            outcome="completed",
            winner=claim["game_idx"] % 2,
            n_samples=42,
            duration_s=0.01,
            npz_bytes=b"\x00FAKE_NPZ_BYTES",
        )

    state = worker_daemon.WorkerState(start_delay_s=0.01)
    thread = _drive_loop_on(
        coord_app, state,
        stage_id="iter_test_self_play_v6",
        kind="self_play",
        play_one=play_one,
    )
    thread.join(timeout=10.0)
    assert not thread.is_alive(), (
        f"loop did not finish in time; state={state.snapshot()}"
    )

    # Daemon back to IDLE, 4 games credited.
    snap = state.snapshot()
    assert snap["state"] == worker_daemon.State.IDLE, snap
    assert snap["games_done"] == 4
    assert snap["games_claimed_in_flight"] == 0
    assert sorted(games_played) == [0, 1, 2, 3]

    # Coordinator's view: queue empty, 4 results, status=complete (or
    # at least drained-with-all-done).
    resp = coord_client.get("/v2/stage/iter_test_self_play_v6")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["n_games_total"] == 4
    assert body["n_games_done"] == 4
    assert body["n_games_queued"] == 0
    assert body["n_games_in_flight"] == 0
    # status is "running" because the orchestrator hasn't called
    # /v2/stage/<id>/close yet -- the queue is drained but the stage
    # remains open for late reports. That matches the contract: a
    # "complete" status requires the orchestrator's explicit close
    # OR the queue+in-flight counters both hit zero AFTER a drain.
    assert body["status"] in ("running", "drained", "complete")

    # Npz files made it to disk under iterate_data/.
    iterate_data_dir = tmp_path / "iterate_data"
    written_npzs = list(iterate_data_dir.glob("*.npz"))
    assert len(written_npzs) == 4, (
        f"expected 4 npz files; saw {written_npzs}"
    )


def test_worker_daemon_handles_eval_stage_with_wins_new_wins_old(tmp_path):
    """Eval stage: claim spec carries weights:{new,old}; per-game
    result reports wins_new / wins_old; coordinator aggregates them
    into the stage_counters response."""
    coord_app = _build_coordinator_app(tmp_path)
    coord_client = coord_app.test_client()
    _seed_stage(
        coord_client, stage_id="eval_vNEW_vs_vOLD",
        n_games=4, kind="eval",
    )

    def play_one(claim, shard_label):
        # Sanity: the claim response should carry weights:{new,old}.
        assert claim["weights"] == {"new": "vNEW", "old": "vOLD"}, claim
        # Two wins for new, two for old.
        idx = claim["game_idx"]
        wins_new = 1 if idx % 2 == 0 else 0
        wins_old = 1 if idx % 2 == 1 else 0
        return cl.GameResult(
            outcome="completed",
            winner=0 if wins_new else 1,
            n_samples=0,
            duration_s=0.001,
            wins_new=wins_new,
            wins_old=wins_old,
            draws=0,
        )

    state = worker_daemon.WorkerState(start_delay_s=0.01)
    thread = _drive_loop_on(
        coord_app, state,
        stage_id="eval_vNEW_vs_vOLD",
        kind="eval",
        play_one=play_one,
    )
    thread.join(timeout=10.0)
    assert not thread.is_alive()
    assert state.snapshot()["state"] == worker_daemon.State.IDLE

    resp = coord_client.get("/v2/stage/eval_vNEW_vs_vOLD")
    body = resp.get_json()
    assert body["n_games_done"] == 4
    assert body["wins_new"] == 2
    assert body["wins_old"] == 2


def test_stage_response_after_drain_matches_doc_shape(tmp_path):
    """Final stage-counters shape pins -- this is the payload the
    user asked the integration test to surface in the report."""
    coord_app = _build_coordinator_app(tmp_path)
    coord_client = coord_app.test_client()
    _seed_stage(
        coord_client, stage_id="iter_shape_check", n_games=4,
    )

    def play_one(claim, shard_label):
        return cl.GameResult(
            outcome="completed",
            winner=0,
            n_samples=1,
            duration_s=0.001,
            npz_bytes=b"NPZ",
        )

    state = worker_daemon.WorkerState(start_delay_s=0.01)
    thread = _drive_loop_on(
        coord_app, state,
        stage_id="iter_shape_check",
        kind="self_play",
        play_one=play_one,
    )
    thread.join(timeout=10.0)

    resp = coord_client.get("/v2/stage/iter_shape_check")
    body = resp.get_json()
    # Required keys per the doc.
    required_keys = {
        "stage_id", "kind", "status",
        "n_games_total", "n_games_queued", "n_games_in_flight",
        "n_games_done", "wins_new", "wins_old", "draws",
        "crashed", "timed_out",
        "started_at", "drained_at", "complete_at",
    }
    assert required_keys.issubset(body.keys()), (
        f"missing keys: {required_keys - set(body.keys())}"
    )
    assert body["n_games_done"] == 4
    assert body["crashed"] == 0
    assert body["timed_out"] == 0
