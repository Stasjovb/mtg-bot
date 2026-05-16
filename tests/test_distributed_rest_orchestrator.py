"""Tests for :mod:`mtg_bot.distributed_rest_orchestrator`.

Covers the three orchestrator steps in isolation:

- ``start_workers`` parallel POST + happy path / 409 / network error
  fan-out.
- ``poll_stage`` loop terminates on ``status == "complete"`` /
  ``stop_check`` / timeout.
- ``run_stage`` end-to-end wires the three steps in order.
- ``make_self_play_stage_spec`` / ``make_eval_stage_spec`` produce the
  correct ``StageSpec`` shapes.

All HTTP is mocked via the injectable ``http_post_json`` / ``http_get_json``
hooks on the public functions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mtg_bot import distributed_rest_orchestrator as orch


# ---------------------------------------------------------------------------
# load_worker_urls
# ---------------------------------------------------------------------------


def test_load_worker_urls_reads_new_shape(tmp_path):
    cfg = tmp_path / "shards.json"
    cfg.write_text(json.dumps({
        "worker_urls": [
            "http://desktop:5198",
            "http://mac:5198",
        ],
    }))
    urls = orch.load_worker_urls(cfg)
    assert urls == ["http://desktop:5198", "http://mac:5198"]


def test_load_worker_urls_missing_file_returns_empty(tmp_path):
    assert orch.load_worker_urls(tmp_path / "nope.json") == []


def test_load_worker_urls_rejects_legacy_shards(tmp_path):
    cfg = tmp_path / "shards.json"
    cfg.write_text(json.dumps({"shards": [{"host": "h"}]}))
    with pytest.raises(Exception):  # LegacyShardsConfigError
        orch.load_worker_urls(cfg)


# ---------------------------------------------------------------------------
# start_workers
# ---------------------------------------------------------------------------


def test_start_workers_happy_path_parallel_post():
    """All workers return 202 -> response payloads aggregated."""
    calls: list[tuple[str, dict]] = []

    def fake_post(url, payload, *, timeout=30.0):
        calls.append((url, dict(payload)))
        return 202, json.dumps({
            "stage_id": payload["stage_id"],
            "stage_started_at": "2026-05-15T18:00:00Z",
        }).encode("utf-8")

    payloads = orch.start_workers(
        worker_urls=["http://w1:5198", "http://w2:5198"],
        stage_id="iter_009_self_play_v6",
        coordinator_url="http://coord:5099",
        kind="self_play",
        http_post_json=fake_post,
    )
    assert len(payloads) == 2
    assert all(p["stage_id"] == "iter_009_self_play_v6" for p in payloads)
    # URLs hit are the correct endpoint
    urls_hit = sorted(c[0] for c in calls)
    assert urls_hit == [
        "http://w1:5198/v2/start_self_play",
        "http://w2:5198/v2/start_self_play",
    ]
    # Request body has ONLY stage_id + coordinator_url (no n_workers).
    for _, body in calls:
        assert set(body.keys()) == {"stage_id", "coordinator_url"}


def test_start_workers_eval_endpoint():
    """Eval kind routes to /v2/start_eval."""
    urls_hit: list[str] = []

    def fake_post(url, payload, *, timeout=30.0):
        urls_hit.append(url)
        return 202, b'{"stage_id": "e", "stage_started_at": "x"}'

    orch.start_workers(
        worker_urls=["http://w1:5198"],
        stage_id="eval_v6_vs_v5",
        coordinator_url="http://coord:5099",
        kind="eval",
        http_post_json=fake_post,
    )
    assert urls_hit == ["http://w1:5198/v2/start_eval"]


def test_start_workers_raises_on_409():
    def fake_post(url, payload, *, timeout=30.0):
        return 409, json.dumps({"error": "worker_busy"}).encode("utf-8")

    with pytest.raises(orch.StartWorkerError, match="worker_busy"):
        orch.start_workers(
            worker_urls=["http://w1:5198"],
            stage_id="s",
            coordinator_url="http://coord:5099",
            kind="self_play",
            http_post_json=fake_post,
        )


def test_start_workers_raises_on_500():
    def fake_post(url, payload, *, timeout=30.0):
        return 500, b"internal error"

    with pytest.raises(orch.StartWorkerError, match="status=500"):
        orch.start_workers(
            worker_urls=["http://w1:5198"],
            stage_id="s",
            coordinator_url="http://coord:5099",
            kind="self_play",
            http_post_json=fake_post,
        )


def test_start_workers_collects_per_worker_failures():
    """If one worker fails and another succeeds, the error message
    mentions only the failing URL."""

    def fake_post(url, payload, *, timeout=30.0):
        if "w2" in url:
            return 409, b'{"error": "worker_busy"}'
        return 202, b'{"stage_id": "s", "stage_started_at": "x"}'

    with pytest.raises(orch.StartWorkerError) as exc:
        orch.start_workers(
            worker_urls=["http://w1:5198", "http://w2:5198"],
            stage_id="s",
            coordinator_url="http://coord:5099",
            kind="self_play",
            http_post_json=fake_post,
        )
    assert "w2" in str(exc.value)
    assert "w1" not in str(exc.value)


# ---------------------------------------------------------------------------
# poll_stage
# ---------------------------------------------------------------------------


def test_poll_stage_returns_when_complete():
    responses = [
        {"status": "running", "n_games_done": 5, "crashed": 0, "timed_out": 0},
        {"status": "running", "n_games_done": 99, "crashed": 1, "timed_out": 0},
        {"status": "complete", "n_games_done": 100, "crashed": 1, "timed_out": 0},
    ]
    seen = iter(responses)
    sleeps: list[float] = []

    def fake_get(url, *, timeout=30.0):
        return 200, json.dumps(next(seen)).encode("utf-8")

    def fake_sleep(s):
        sleeps.append(s)

    result = orch.poll_stage(
        coordinator_url="http://coord:5099",
        stage_id="s1",
        poll_interval_s=0.001,
        sleep=fake_sleep,
        http_get=fake_get,
    )
    assert result.status == "complete"
    assert result.n_games_done == 100
    assert result.crashed == 1
    # Two sleeps before the third "complete" response.
    assert len(sleeps) == 2


def test_poll_stage_404_raises():
    def fake_get(url, *, timeout=30.0):
        return 404, b'{"error": "no such stage_id"}'

    with pytest.raises(RuntimeError, match="not found"):
        orch.poll_stage(
            coordinator_url="http://coord:5099",
            stage_id="missing",
            poll_interval_s=0.001,
            sleep=lambda s: None,
            http_get=fake_get,
        )


def test_poll_stage_stop_check_exits_early():
    """stop_check returning True exits the poll with the last
    observed counters (NOT 'complete')."""
    observed: list[dict] = []
    payload = {"status": "running", "n_games_done": 42}

    def fake_get(url, *, timeout=30.0):
        observed.append(payload)
        return 200, json.dumps(payload).encode("utf-8")

    stop_after_first = {"count": 0}

    def stop_check():
        stop_after_first["count"] += 1
        return stop_after_first["count"] > 1

    result = orch.poll_stage(
        coordinator_url="http://coord:5099",
        stage_id="s2",
        poll_interval_s=0.001,
        sleep=lambda _s: None,
        http_get=fake_get,
        stop_check=stop_check,
    )
    # Exits with running state (NOT complete) after stop_check fires.
    assert result.status == "running"
    assert result.n_games_done == 42


def test_poll_stage_returns_eval_counters():
    """When the stage is eval, wins_new/wins_old/draws are surfaced."""

    def fake_get(url, *, timeout=30.0):
        return 200, json.dumps({
            "status": "complete",
            "n_games_done": 100,
            "crashed": 0, "timed_out": 0,
            "wins_new": 56, "wins_old": 39, "draws": 5,
        }).encode("utf-8")

    result = orch.poll_stage(
        coordinator_url="http://coord:5099",
        stage_id="eval_v6_vs_v5",
        poll_interval_s=0.001,
        sleep=lambda _s: None,
        http_get=fake_get,
    )
    assert result.wins_new == 56
    assert result.wins_old == 39
    assert result.draws == 5


# ---------------------------------------------------------------------------
# run_stage end-to-end
# ---------------------------------------------------------------------------


def test_run_stage_threads_three_steps_in_order():
    """run_stage POSTs /create, POSTs /start_self_play to each worker,
    then polls /stage/<id> to completion."""
    posts: list[tuple[str, dict]] = []
    gets: list[str] = []

    def fake_post(url, payload, *, timeout=30.0):
        posts.append((url, dict(payload)))
        if url.endswith("/v2/stage/create"):
            return 200, json.dumps({
                "stage_id": payload["stage_id"],
                "n_games_queued": len(payload["games"]),
            }).encode("utf-8")
        if url.endswith("/v2/start_self_play"):
            return 202, b'{"stage_id": "s", "stage_started_at": "x"}'
        return 500, b"unexpected"

    def fake_get(url, *, timeout=30.0):
        gets.append(url)
        return 200, json.dumps({
            "status": "complete",
            "n_games_done": 4,
            "crashed": 0, "timed_out": 0,
        }).encode("utf-8")

    spec = orch.make_self_play_stage_spec(
        stage_id="iter_test_self_play_v6",
        n_games=4,
        base_seed=42,
        deck_pool_size=10,
        weights_version="v6",
        nodes=200, samples=4,
        per_game_timeout_sec=600.0,
    )
    result = orch.run_stage(
        coordinator_url="http://coord:5099",
        worker_urls=["http://w1:5198", "http://w2:5198"],
        spec=spec,
        poll_interval_s=0.001,
        sleep=lambda _s: None,
        http_post_json=fake_post,
        http_get_json=fake_get,
    )
    assert result.status == "complete"
    assert result.n_games_done == 4
    # /v2/stage/create posted exactly once, /v2/start_self_play to
    # both workers.
    create_posts = [p for p in posts if p[0].endswith("/v2/stage/create")]
    start_posts = [p for p in posts if "/v2/start_self_play" in p[0]]
    assert len(create_posts) == 1
    assert len(start_posts) == 2
    assert {p[0] for p in start_posts} == {
        "http://w1:5198/v2/start_self_play",
        "http://w2:5198/v2/start_self_play",
    }
    # /v2/stage/<id> polled at least once.
    assert any(g.endswith("/v2/stage/iter_test_self_play_v6") for g in gets)


def test_run_stage_raises_when_create_409_mismatch():
    """A 409 from /v2/stage/create -> spec mismatch -> RuntimeError."""

    def fake_post(url, payload, *, timeout=30.0):
        if url.endswith("/v2/stage/create"):
            return 409, json.dumps({"error": "different spec"}).encode("utf-8")
        raise AssertionError("should not reach /v2/start_*")

    spec = orch.make_self_play_stage_spec(
        stage_id="bad",
        n_games=2, base_seed=0, deck_pool_size=4,
        weights_version="v6", nodes=200, samples=4,
        per_game_timeout_sec=60.0,
    )
    with pytest.raises(RuntimeError, match="different spec"):
        orch.run_stage(
            coordinator_url="http://coord:5099",
            worker_urls=["http://w1:5198"],
            spec=spec,
            poll_interval_s=0.001,
            sleep=lambda _s: None,
            http_post_json=fake_post,
            http_get_json=lambda u, **k: (200, b"{}"),
        )


# ---------------------------------------------------------------------------
# Spec builders
# ---------------------------------------------------------------------------


def test_make_self_play_stage_spec_shape():
    spec = orch.make_self_play_stage_spec(
        stage_id="iter_009_self_play_v6",
        n_games=1000,
        base_seed=9000000,
        deck_pool_size=5000,
        weights_version="v6",
        nodes=200, samples=4,
        per_game_timeout_sec=600.0,
        capture_every=20,
        claim_ttl_seconds=1200,
    )
    assert spec.kind == "self_play"
    assert spec.weights == {"p0": "v6", "p1": "v6"}
    assert spec.nodes == 200
    assert spec.samples == 4
    assert spec.per_game_timeout_sec == 600.0
    assert spec.capture_every == 20
    assert spec.claim_ttl_seconds == 1200
    assert len(spec.games) == 1000
    # Each game has the required keys.
    g0 = spec.games[0]
    assert set(g0.keys()) >= {"game_idx", "deck_indices", "seed"}
    assert g0["game_idx"] == 0
    assert isinstance(g0["deck_indices"], list)
    assert len(g0["deck_indices"]) == 2
    assert g0["deck_indices"][0] != g0["deck_indices"][1]


def test_make_eval_stage_spec_shape():
    spec = orch.make_eval_stage_spec(
        stage_id="eval_v6_vs_v5_500g",
        n_games=500,
        base_seed=1234,
        deck_pool_size=100,
        new_version="v6",
        old_version="v5",
        nodes=200, samples=4,
        per_game_timeout_sec=600.0,
    )
    assert spec.kind == "eval"
    assert spec.weights == {"new": "v6", "old": "v5"}
    assert len(spec.games) == 500


def test_build_self_play_games_zero_games():
    assert orch.build_self_play_games(
        n_games=0, base_seed=0, deck_pool_size=10,
    ) == []


def test_build_self_play_games_rejects_zero_pool():
    with pytest.raises(ValueError, match="positive"):
        orch.build_self_play_games(
            n_games=1, base_seed=0, deck_pool_size=0,
        )


def test_build_self_play_games_custom_picker():
    def picker(game_idx):
        return (game_idx * 2, game_idx * 2 + 1)

    games = orch.build_self_play_games(
        n_games=3, base_seed=100, deck_pool_size=1000,
        deck_picker=picker,
    )
    assert [g["deck_indices"] for g in games] == [[0, 1], [2, 3], [4, 5]]
    assert [g["seed"] for g in games] == [100, 101, 102]


def test_stage_spec_to_dict_round_trips():
    spec = orch.make_self_play_stage_spec(
        stage_id="x",
        n_games=2,
        base_seed=0,
        deck_pool_size=10,
        weights_version="v6",
        nodes=200, samples=4,
        per_game_timeout_sec=60.0,
    )
    d = spec.to_dict()
    assert d["stage_id"] == "x"
    assert d["kind"] == "self_play"
    assert d["nodes"] == 200
    assert len(d["games"]) == 2
