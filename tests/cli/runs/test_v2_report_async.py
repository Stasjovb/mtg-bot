"""Focused tests for the ``/v2/report_result`` async dispatch path.

``test_v2_claim_report.py`` covers the handler contract with a
synchronous ``executor=None`` so post-POST DB state is observable
immediately. This file complements that with tests that exercise the
real ``ThreadPoolExecutor`` dispatch + the fetch-failure /
size-mismatch / idempotency edges that need a live executor (or a
stub fetcher that misbehaves).

Covers:
- 202 returns *before* the fetch / write / DB upsert lands; the post
  is non-blocking even with a slow fetcher.
- Background fetch failure (all 3 retries fail) writes an
  ``upload_failed`` row with the broken URI stamped into
  ``artifact_uri``.
- Size-mismatch (declared bytes != actual fetched bytes) is treated
  as a fetch failure → ``upload_failed`` row.
- Idempotency: the background job re-checks the claim's ``reported``
  flag at execution time and skips with an INFO log when a duplicate
  somehow slipped past the sync 409 path (e.g. a race between two
  request threads).
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from mtg_bot.cli import serve as serve_mod
from mtg_bot.cli.runs import queue_db
from mtg_bot.cli.runs.coordinator_artifact_fetcher import (
    ArtifactFetcher,
    LocalArtifactFetcher,
    MultiSchemeFetcher,
)


def _file_uri(path: Path) -> str:
    return "file:///" + path.as_posix().lstrip("/")


class _SlowFetcher(ArtifactFetcher):
    """LocalArtifactFetcher with a tunable sleep so we can prove the
    202 returns before the fetch finishes."""

    def __init__(self, delay_s: float, inner: ArtifactFetcher):
        self.delay_s = delay_s
        self.inner = inner
        self.fetched_at: list[float] = []

    def fetch(self, uri: str) -> bytes:
        time.sleep(self.delay_s)
        self.fetched_at.append(time.monotonic())
        return self.inner.fetch(uri)


class _AlwaysFailFetcher(ArtifactFetcher):
    """Raises on every fetch — drives the background job into the
    ``upload_failed`` row branch."""

    def __init__(self, message: str = "boom"):
        self.message = message
        self.calls = 0

    def fetch(self, uri: str) -> bytes:
        self.calls += 1
        raise RuntimeError(self.message)


def _make_app_with(
    tmp_path: Path,
    *,
    fetcher: ArtifactFetcher,
    executor,
):
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
        report_executor=executor,
    )


def _spec(*, n_games: int = 2):
    return {
        "stage_id": "iter_async_v1",
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


def _create_stage(client, spec):
    res = client.post("/v2/stage/create", json=spec)
    assert res.status_code == 200, res.get_json()


def _claim(client, worker_id: str = "wA"):
    res = client.post("/v2/claim", json={
        "worker_id": worker_id, "stage_id": "iter_async_v1",
    })
    assert res.status_code == 200, res.get_json()
    return res.get_json()


# ---- 202-before-fetch (proves the post is non-blocking) ----------------


def test_post_returns_202_before_background_fetch_completes(tmp_path):
    """With a 250ms-slow fetcher and a real ThreadPoolExecutor, the
    POST returns 202 in well under the fetch delay. Proves the sync
    portion of the handler does not block on the fetch."""
    npz_bytes = b"slow-but-correct"
    drop = tmp_path / "drop"
    drop.mkdir(parents=True, exist_ok=True)
    npz_path = drop / "x.npz"
    npz_path.write_bytes(npz_bytes)
    npz_uri = _file_uri(npz_path)

    slow = _SlowFetcher(delay_s=0.25, inner=LocalArtifactFetcher())
    fetcher = MultiSchemeFetcher(local=slow)
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="t")
    try:
        app = _make_app_with(tmp_path, fetcher=fetcher, executor=executor)
        client = app.test_client()
        _create_stage(client, _spec())
        claim = _claim(client)
        t0 = time.monotonic()
        res = client.post("/v2/report_result", json={
            "meta": {
                "claim_id": claim["claim_id"],
                "outcome": "completed", "winner": 0,
                "n_samples": 10, "duration_s": 1.0,
                "shard_label": "wA",
            },
            "npz_uri": npz_uri,
            "npz_size_bytes": len(npz_bytes),
        })
        elapsed = time.monotonic() - t0
        assert res.status_code == 202
        # The sync portion is O(ms): JSON parse + one SELECT.
        # We give a comfortable 100ms ceiling (much less than the
        # 250ms fetcher delay).
        assert elapsed < 0.15, (
            f"sync portion took {elapsed * 1000:.1f}ms; the handler "
            "is supposed to enqueue + return without waiting"
        )
        # Wait for the background job to finish so the assertions
        # below see settled state.
        executor.shutdown(wait=True)
    finally:
        # shutdown(wait=True) already ran in the happy path; this
        # is the cleanup-on-failure shim.
        if not getattr(executor, "_shutdown", False):
            executor.shutdown(wait=False)

    # The slow fetcher actually ran and wrote the npz to iterate_data.
    npzs = list((tmp_path / "iterate_data").glob("*.npz"))
    assert len(npzs) == 1
    assert npzs[0].read_bytes() == npz_bytes


# ---- fetch-failure → upload_failed row ---------------------------------


def test_fetch_failure_writes_upload_failed_row(tmp_path):
    """All 3 fetch retries fail → background job writes a results
    row with outcome='upload_failed', npz_path NULL, and
    artifact_uri stamped with the broken URI."""
    bad = _AlwaysFailFetcher(message="simulated 503")
    fetcher = MultiSchemeFetcher(local=bad)
    # Sync dispatch so the failure path is observable in-test.
    app = _make_app_with(tmp_path, fetcher=fetcher, executor=None)
    client = app.test_client()
    _create_stage(client, _spec())
    claim = _claim(client)
    broken_uri = "file:///does/not/matter/x.npz"

    # Patch the per-retry sleep so the 3 retries don't actually wait
    # 14 real seconds.
    import mtg_bot.cli.runs.v2_endpoints as v2_endpoints
    orig_sleep = time.sleep
    try:
        v2_endpoints.time.sleep = lambda *_a, **_k: None  # type: ignore[attr-defined]
        res = client.post("/v2/report_result", json={
            "meta": {
                "claim_id": claim["claim_id"],
                "outcome": "completed", "winner": 0,
                "n_samples": 5, "duration_s": 1.0,
                "shard_label": "wA",
            },
            "npz_uri": broken_uri,
            "npz_size_bytes": 100,
        })
    finally:
        v2_endpoints.time.sleep = orig_sleep  # type: ignore[attr-defined]
    assert res.status_code == 202

    # Background ran all 4 attempts (1 initial + 3 retries) and gave up.
    assert bad.calls == 4
    conn = queue_db.connect(tmp_path / "queue.db")
    try:
        row = conn.execute(
            "SELECT * FROM results WHERE claim_id = ?",
            (claim["claim_id"],),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["outcome"] == "upload_failed"
    assert row["npz_path"] is None
    assert row["artifact_uri"] == broken_uri


def test_size_mismatch_treated_as_fetch_failure(tmp_path, caplog):
    """If the declared size doesn't match the actual fetched bytes,
    the size-check raises inside the fetch+write step. With retries
    exhausted (the underlying bytes don't change between attempts),
    the job lands an upload_failed row."""
    drop = tmp_path / "drop"
    drop.mkdir(parents=True, exist_ok=True)
    actual = b"only-7"  # 6 bytes (the literal is 6 chars).
    npz_path = drop / "wrong_size.npz"
    npz_path.write_bytes(actual)
    uri = _file_uri(npz_path)

    fetcher = MultiSchemeFetcher(local=LocalArtifactFetcher())
    app = _make_app_with(tmp_path, fetcher=fetcher, executor=None)
    client = app.test_client()
    _create_stage(client, _spec())
    claim = _claim(client)

    import mtg_bot.cli.runs.v2_endpoints as v2_endpoints
    orig_sleep = time.sleep
    try:
        v2_endpoints.time.sleep = lambda *_a, **_k: None  # type: ignore[attr-defined]
        with caplog.at_level(logging.ERROR):
            res = client.post("/v2/report_result", json={
                "meta": {
                    "claim_id": claim["claim_id"],
                    "outcome": "completed", "winner": 0,
                    "n_samples": 5, "duration_s": 1.0,
                    "shard_label": "wA",
                },
                "npz_uri": uri,
                "npz_size_bytes": 999999,  # liar
            })
    finally:
        v2_endpoints.time.sleep = orig_sleep  # type: ignore[attr-defined]
    assert res.status_code == 202

    conn = queue_db.connect(tmp_path / "queue.db")
    try:
        row = conn.execute(
            "SELECT * FROM results WHERE claim_id = ?",
            (claim["claim_id"],),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["outcome"] == "upload_failed"
    # Error was logged loudly.
    assert any(
        "gave up after" in rec.message for rec in caplog.records
    )


# ---- background-job idempotency ----------------------------------------


def test_background_job_skips_if_already_reported(tmp_path, caplog):
    """If a race somehow lets a duplicate slip past the sync 409
    check (e.g. two request threads both pre-check the claim before
    either writes), the background job's own idempotency guard
    must skip the second run cleanly without re-writing the row.

    We exercise this by calling the job body directly with a claim
    that's already reported."""
    fetcher = MultiSchemeFetcher(local=LocalArtifactFetcher())
    app = _make_app_with(tmp_path, fetcher=fetcher, executor=None)
    client = app.test_client()
    _create_stage(client, _spec())
    claim = _claim(client)
    # First report goes through normally.
    res = client.post("/v2/report_result", json={
        "meta": {
            "claim_id": claim["claim_id"],
            "outcome": "completed", "winner": 0,
            "n_samples": 1, "duration_s": 1.0,
            "shard_label": "wA",
        },
    })
    assert res.status_code == 202
    # Snapshot the row so we can prove the skip path leaves it alone.
    conn = queue_db.connect(tmp_path / "queue.db")
    try:
        row_before = dict(conn.execute(
            "SELECT * FROM results WHERE claim_id = ?",
            (claim["claim_id"],),
        ).fetchone())
    finally:
        conn.close()

    # Drive the background job body directly for the SAME claim
    # (bypasses the sync 409 path).
    from mtg_bot.cli.runs.v2_endpoints import _process_report_job
    with caplog.at_level(logging.INFO):
        _process_report_job(
            claim_id=claim["claim_id"],
            stage_id="iter_async_v1",
            game_idx=0,
            shard_label="wA",
            meta={"claim_id": claim["claim_id"], "outcome": "completed"},
            npz_uri=None,
            replay_uri=None,
            npz_size_bytes=None,
            replay_size_bytes=None,
            iterate_data_dir=tmp_path / "iterate_data",
            replays_root=tmp_path / "replays",
            queue_db_path=tmp_path / "queue.db",
            fetcher=fetcher,
            heartbeat_poller_provider=None,
        )

    # Row is byte-identical: the skip path didn't touch it.
    conn = queue_db.connect(tmp_path / "queue.db")
    try:
        row_after = dict(conn.execute(
            "SELECT * FROM results WHERE claim_id = ?",
            (claim["claim_id"],),
        ).fetchone())
    finally:
        conn.close()
    assert row_after == row_before
    # The skip-path INFO log fired.
    assert any(
        "already reported (idempotent)" in rec.message
        for rec in caplog.records
    )
