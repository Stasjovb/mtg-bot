"""Tests for ``POST /v2/claim`` + ``POST /v2/report_result``.

Phase 2B cut the multipart-blob shape entirely: workers upload
artifacts to shared storage and POST a JSON body with the URIs.
The coord validates synchronously, enqueues the fetch+write+DB
upsert on a background executor, and returns 202.

Tests in this file run with a synchronous executor (``executor=None``
falls into the in-process dispatch path) so the post-POST DB and
filesystem state is observable immediately. The
``test_v2_report_async.py`` companion file covers ThreadPoolExecutor
semantics + idempotency edges that need a real Executor.

Covers:
- 202 ``queued: true`` happy path with file:// fetcher
  rehydrating npz + replay bytes into ``iterate_data`` / replays.
- 404 unknown claim_id.
- 409 on a duplicate POST (synchronous; the coord detects the
  already-reported claim before enqueueing).
- 400 on bad body shape (non-JSON, missing meta, missing
  claim_id).
- Eval no-files path (no npz_uri / replay_uri keys).
- Late-duplicate 409 via the zombie-worker requeue path.
"""

from __future__ import annotations

import json
from pathlib import Path

from mtg_bot.cli import serve as serve_mod
from mtg_bot.cli.runs import queue_db
from mtg_bot.cli.runs.coordinator_artifact_fetcher import (
    LocalArtifactFetcher,
    MultiSchemeFetcher,
)


# A file:// URI from a path (cross-platform: file:///C:/... on Win,
# file:///tmp/... on POSIX).
def _file_uri(path: Path) -> str:
    return "file:///" + path.as_posix().lstrip("/")


def _make_app(tmp_path: Path):
    # Sync dispatch (no executor) so test asserts on post-POST DB
    # state are deterministic.
    fetcher = MultiSchemeFetcher(local=LocalArtifactFetcher())
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
        artifact_fetcher=fetcher,
        report_executor=None,
    )


def _spec(*, n_games: int = 2, kind: str = "self_play"):
    return {
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


def _create_stage(client, spec):
    res = client.post("/v2/stage/create", json=spec)
    assert res.status_code == 200, res.get_json()


def _drop_npz(tmp_path: Path, name: str, body: bytes) -> str:
    drop = tmp_path / "worker_drop"
    drop.mkdir(parents=True, exist_ok=True)
    target = drop / name
    target.write_bytes(body)
    return _file_uri(target)


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


# ---- /v2/report_result happy paths ---------------------------------------


def _claim_one(client) -> dict:
    res = client.post("/v2/claim", json={
        "worker_id": "wA",
        "stage_id": "iter_009_self_play_v6",
    })
    assert res.status_code == 200, res.get_json()
    return res.get_json()


def _claim_one_as(client, worker_id: str) -> dict:
    res = client.post("/v2/claim", json={
        "worker_id": worker_id,
        "stage_id": "iter_009_self_play_v6",
    })
    assert res.status_code == 200, res.get_json()
    return res.get_json()


def test_report_result_happy_path_returns_202_and_writes_files(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    _create_stage(client, _spec())
    claim = _claim_one(client)
    npz_bytes = b"\x00\x01\x02fake-npz"
    replay_bytes = b"\x00\x01fake-replay"
    npz_uri = _drop_npz(tmp_path, "wA_c0.npz", npz_bytes)
    replay_uri = _drop_npz(tmp_path, "wA_c0.json.gz", replay_bytes)
    res = client.post("/v2/report_result", json={
        "meta": {
            "claim_id": claim["claim_id"],
            "outcome": "completed",
            "winner": 0,
            "n_samples": 1142,
            "duration_s": 31.4,
            "shard_label": "mac",
        },
        "npz_uri": npz_uri,
        "replay_uri": replay_uri,
        "npz_size_bytes": len(npz_bytes),
        "replay_size_bytes": len(replay_bytes),
    })
    assert res.status_code == 202, res.get_json()
    body = res.get_json()
    assert body["accepted"] is True
    assert body["queued"] is True
    assert body["claim_id"] == claim["claim_id"]

    # The sync executor ran the job in-process: files exist now.
    npzs = list((tmp_path / "iterate_data").glob("*.npz"))
    assert len(npzs) == 1
    assert npzs[0].read_bytes() == npz_bytes
    replays = list(
        (tmp_path / "replays" / "iter_009_self_play_v6_mac").glob("*.json.gz")
    )
    assert len(replays) == 1
    assert replays[0].name == "0.json.gz"
    assert replays[0].read_bytes() == replay_bytes

    # record_report fired -- the result row carries npz_path +
    # artifact_uri pointing back at the worker drop for forensics.
    conn = queue_db.connect(tmp_path / "queue.db")
    try:
        row = conn.execute(
            "SELECT * FROM results WHERE claim_id = ?",
            (claim["claim_id"],),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["outcome"] == "completed"
    assert row["artifact_uri"] == npz_uri
    assert row["npz_path"] is not None
    assert row["replay_path"] is not None


def test_report_result_no_uris_json_body_ok(tmp_path):
    """Eval reports commonly have no npz / replay -- a body with
    just ``meta`` and no URI fields is accepted."""
    app = _make_app(tmp_path)
    client = app.test_client()
    _create_stage(client, _spec(kind="eval"))
    claim = _claim_one(client)
    res = client.post("/v2/report_result", json={
        "meta": {
            "claim_id": claim["claim_id"],
            "outcome": "completed",
            "winner": 0,
            "n_samples": 0,
            "duration_s": 5.0,
            "shard_label": "mac",
            "wins_new": 1,
            "wins_old": 0,
        },
    })
    assert res.status_code == 202, res.get_json()
    body = res.get_json()
    assert body["accepted"] is True
    assert body["queued"] is True
    # No files written.
    assert not (tmp_path / "iterate_data").exists() or list(
        (tmp_path / "iterate_data").glob("*"),
    ) == []


def test_report_result_npz_only_no_replay(tmp_path):
    """Self-play with no capture-every hit: npz but no replay."""
    app = _make_app(tmp_path)
    client = app.test_client()
    _create_stage(client, _spec())
    claim = _claim_one(client)
    npz_bytes = b"npz-only-bytes"
    npz_uri = _drop_npz(tmp_path, "npz_only.npz", npz_bytes)
    res = client.post("/v2/report_result", json={
        "meta": {
            "claim_id": claim["claim_id"],
            "outcome": "completed",
            "winner": 0,
            "n_samples": 50,
            "duration_s": 2.0,
            "shard_label": "mac",
        },
        "npz_uri": npz_uri,
        "npz_size_bytes": len(npz_bytes),
    })
    assert res.status_code == 202
    npzs = list((tmp_path / "iterate_data").glob("*.npz"))
    assert len(npzs) == 1
    # No replay directory created.
    assert not (tmp_path / "replays").exists() or not list(
        (tmp_path / "replays").rglob("*.json.gz"),
    )


# ---- /v2/report_result error / validation paths --------------------------


def test_report_result_404_on_unknown_claim_id(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    _create_stage(client, _spec())
    res = client.post("/v2/report_result", json={
        "meta": {"claim_id": "no_such_claim:0000"},
    })
    assert res.status_code == 404


def test_report_result_400_on_missing_claim_id(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    _create_stage(client, _spec())
    res = client.post("/v2/report_result", json={
        "meta": {"outcome": "completed"},
    })
    assert res.status_code == 400


def test_report_result_400_on_missing_meta(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    _create_stage(client, _spec())
    res = client.post("/v2/report_result", json={"npz_uri": "x"})
    assert res.status_code == 400


def test_report_result_400_on_non_json_body(tmp_path):
    """Multipart is dead; sending one fails fast."""
    app = _make_app(tmp_path)
    client = app.test_client()
    _create_stage(client, _spec())
    res = client.post(
        "/v2/report_result",
        data={"meta": json.dumps({"claim_id": "x"})},
        content_type="multipart/form-data",
    )
    assert res.status_code == 400


def test_report_result_400_on_non_dict_body(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    _create_stage(client, _spec())
    res = client.post("/v2/report_result", json=["not", "a", "dict"])
    assert res.status_code == 400


# ---- /v2/report_result duplicate / conflict paths ------------------------


def test_report_result_synchronous_409_on_duplicate(tmp_path):
    """Idempotent POST: the second post for the same claim_id hits
    the sync 409 path (the claim's ``reported`` flag is 1 once the
    first job lands). No second job is enqueued."""
    app = _make_app(tmp_path)
    client = app.test_client()
    _create_stage(client, _spec())
    claim = _claim_one(client)
    body = {
        "meta": {
            "claim_id": claim["claim_id"],
            "outcome": "completed",
            "winner": 0,
            "n_samples": 100,
            "duration_s": 1.0,
            "shard_label": "mac",
        },
    }
    res1 = client.post("/v2/report_result", json=body)
    assert res1.status_code == 202
    res2 = client.post("/v2/report_result", json=body)
    assert res2.status_code == 409
    body2 = res2.get_json()
    assert body2["accepted"] is False


def test_report_result_late_duplicate_409(tmp_path):
    """Zombie-worker path. Worker A claims; coord marks the claim
    abandoned (DEAD-worker handler); worker B re-claims and reports
    successfully. Worker A's late report hits the sync 409 path
    because the claim's ``reported`` flag is 1 (set by
    ``requeue_claim``'s tombstone)."""
    app = _make_app(tmp_path)
    client = app.test_client()
    _create_stage(client, _spec(n_games=1))
    claim_a = _claim_one(client)

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
    assert claim_b["claim_id"] != claim_a["claim_id"]

    res_b = client.post("/v2/report_result", json={
        "meta": {
            "claim_id": claim_b["claim_id"],
            "outcome": "completed",
            "winner": 1,
            "n_samples": 100,
            "duration_s": 1.0,
            "shard_label": "wB",
        },
    })
    assert res_b.status_code == 202

    # Worker A's late report is rejected synchronously: the
    # tombstone set claim_a.reported=1, so the up-front
    # already-reported check hits.
    res_a = client.post("/v2/report_result", json={
        "meta": {
            "claim_id": claim_a["claim_id"],
            "outcome": "completed",
            "winner": 0,
            "n_samples": 100,
            "duration_s": 1.0,
            "shard_label": "wA",
        },
    })
    assert res_a.status_code == 409


# ---- counters surfaced through report_result -----------------------------


def test_eval_stage_counters_aggregate_wins(tmp_path):
    """An eval stage's report_result writes wins_new/wins_old which
    bubble up through ``stage_counters``."""
    app = _make_app(tmp_path)
    client = app.test_client()
    _create_stage(client, _spec(n_games=2, kind="eval"))
    for _ in range(2):
        claim = _claim_one(client)
        res = client.post("/v2/report_result", json={
            "meta": {
                "claim_id": claim["claim_id"],
                "outcome": "completed",
                "winner": 0,
                "n_samples": 0,
                "duration_s": 1.0,
                "shard_label": "wA",
                "wins_new": 1,
                "wins_old": 0,
            },
        })
        assert res.status_code == 202
    res = client.get("/v2/stage/iter_009_self_play_v6")
    body = res.get_json()
    assert body["kind"] == "eval"
    assert body["wins_new"] == 2
    assert body["wins_old"] == 0
    assert body["n_games_done"] == 2


def test_stage_counters_carries_n_samples_and_total_duration(tmp_path):
    """Aggregate response includes summed ``n_samples`` and
    ``total_duration_s`` from the per-game results."""
    app = _make_app(tmp_path)
    client = app.test_client()
    _create_stage(client, _spec(n_games=2))
    payloads = [
        {"n_samples": 7, "duration_s": 4.5, "shard_label": "wA"},
        {"n_samples": 5, "duration_s": 2.5, "shard_label": "wA"},
    ]
    for p in payloads:
        claim = _claim_one(client)
        res = client.post("/v2/report_result", json={
            "meta": {
                "claim_id": claim["claim_id"],
                "outcome": "completed",
                "winner": 0,
                **p,
            },
        })
        assert res.status_code == 202
    body = client.get("/v2/stage/iter_009_self_play_v6").get_json()
    assert body["n_samples"] == 12
    assert body["total_duration_s"] == 7.0
    assert body["n_games_done"] == 2


def test_stage_counters_machines_per_worker_breakdown(tmp_path):
    """When multiple workers report games, ``machines`` carries one
    row per shard_label with that worker's done/samples/crashed/
    timed_out + duration sums. Workers with only in-flight claims
    (no reports yet) still surface with ``n_in_flight > 0``."""
    app = _make_app(tmp_path)
    client = app.test_client()
    _create_stage(client, _spec(n_games=4))

    reports = [
        ("wA", {"outcome": "completed", "winner": 0, "n_samples": 10, "duration_s": 5.0, "shard_label": "wA"}),
        ("wA", {"outcome": "completed", "winner": 1, "n_samples": 12, "duration_s": 6.0, "shard_label": "wA"}),
        ("wB", {"outcome": "completed", "winner": 0, "n_samples": 8, "duration_s": 3.0, "shard_label": "wB"}),
        ("wB", {"outcome": "timed_out", "winner": None, "n_samples": 0, "duration_s": 600.0, "shard_label": "wB", "timed_out": 1}),
    ]
    for worker_id, meta_extra in reports:
        claim = _claim_one_as(client, worker_id)
        res = client.post("/v2/report_result", json={
            "meta": {"claim_id": claim["claim_id"], **meta_extra},
        })
        assert res.status_code == 202

    body = client.get("/v2/stage/iter_009_self_play_v6").get_json()
    assert body["n_games_done"] == 4
    assert body["n_samples"] == 30
    assert body["timed_out"] == 1

    machines = {m["label"]: m for m in body["machines"]}
    assert set(machines.keys()) == {"wA", "wB"}
    assert machines["wA"]["n_games_done"] == 2
    assert machines["wA"]["n_samples"] == 22
    assert machines["wA"]["total_duration_s"] == 11.0
    assert machines["wA"]["timed_out"] == 0
    assert machines["wA"]["n_in_flight"] == 0
    assert machines["wB"]["n_games_done"] == 2
    assert machines["wB"]["n_samples"] == 8
    assert machines["wB"]["timed_out"] == 1
    assert body["n_workers"] == 2


def test_stage_counters_surfaces_in_flight_worker_before_first_report(tmp_path):
    """A worker that has claimed but not yet reported still appears in
    ``machines`` with ``n_in_flight > 0`` so the UI can show the
    machine card as soon as work is dispatched."""
    app = _make_app(tmp_path)
    client = app.test_client()
    _create_stage(client, _spec(n_games=3))
    claim_b = _claim_one_as(client, "wB")
    assert claim_b is not None
    claim_a = _claim_one_as(client, "wA")
    res = client.post("/v2/report_result", json={
        "meta": {
            "claim_id": claim_a["claim_id"],
            "outcome": "completed", "winner": 0,
            "n_samples": 3, "duration_s": 1.0, "shard_label": "wA",
        },
    })
    assert res.status_code == 202

    body = client.get("/v2/stage/iter_009_self_play_v6").get_json()
    machines = {m["label"]: m for m in body["machines"]}
    assert "wA" in machines
    assert "wB" in machines
    assert machines["wA"]["n_games_done"] == 1
    assert machines["wA"]["n_in_flight"] == 0
    assert machines["wB"]["n_games_done"] == 0
    assert machines["wB"]["n_in_flight"] == 1
    assert body["n_workers"] == 2


def test_claim_carries_self_play_exploration_knobs(tmp_path):
    """The four self-play exploration knobs on the stage spec are
    copied verbatim into every claim so workers can build their
    per-game search config from them."""
    app = _make_app(tmp_path)
    client = app.test_client()
    spec = _spec()
    spec.update({
        "root_dirichlet_alpha": 0.5,
        "root_dirichlet_eps": 0.2,
        "move_temperature": 0.8,
        "temperature_cutoff": 12,
    })
    _create_stage(client, spec)
    body = _claim_one(client)
    assert body["root_dirichlet_alpha"] == 0.5
    assert body["root_dirichlet_eps"] == 0.2
    assert body["move_temperature"] == 0.8
    assert body["temperature_cutoff"] == 12


def test_claim_knobs_default_to_none_for_legacy_stage_spec(tmp_path):
    """A stage created without the knobs (older orchestrator) yields
    ``None`` for each so the worker falls back to data_gen defaults."""
    app = _make_app(tmp_path)
    client = app.test_client()
    _create_stage(client, _spec())
    body = _claim_one(client)
    for key in (
        "root_dirichlet_alpha", "root_dirichlet_eps",
        "move_temperature", "temperature_cutoff",
    ):
        assert key in body
        assert body[key] is None
