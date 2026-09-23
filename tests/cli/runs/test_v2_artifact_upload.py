"""Tests for ``POST /v2/artifact/upload`` (coordinator drop-off).

Workers that share neither a filesystem nor an S3 bucket with the
coordinator run ``--artifact-storage-uri http://<coord>:5099``. They
POST the raw ``.npz`` / replay bytes here; the coordinator writes
them under ``--artifact-upload-dir`` keyed by
``build_artifact_key(...)`` and replies with a coordinator-LOCAL
``file://`` URI. The worker echoes that URI on
``/v2/report_result`` and the coordinator's existing
``LocalArtifactFetcher`` rehydrates it unchanged.

Covered here:
- happy path: bytes land on disk, response carries the file:// URI.
- idempotency: a repeat POST with the same key overwrites in place
  and returns the same URI.
- validation: bad kind / stage_id / claim_id, path traversal, empty
  body, oversize body.
- 503 when the endpoint is disabled (``artifact_upload_dir=None``).
- full round trip over a REAL WSGI server: HttpArtifactUploader ->
  endpoint -> LocalArtifactFetcher returns identical bytes.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from flask import Flask

from mtg_bot.cli.runs.coordinator_artifact_fetcher import LocalArtifactFetcher
from mtg_bot.cli.runs.v2_endpoints import (
    MAX_ARTIFACT_UPLOAD_BYTES,
    build_v2_blueprint,
    _safe_upload_target,
)
from mtg_bot.worker_daemon_storage import (
    HttpArtifactUploader,
    build_artifact_key,
)


def _make_app(tmp_path: Path, *, upload_dir: Path | None, **kwargs) -> Flask:
    app = Flask(__name__)
    app.register_blueprint(build_v2_blueprint(
        queue_db_path=tmp_path / "queue.db",
        weights_root=tmp_path / "weights",
        iterate_data_dir=tmp_path / "iterate_data",
        replays_root=tmp_path / "replays",
        process_started_at_monotonic=0.0,
        report_executor=None,
        artifact_upload_dir=upload_dir,
        **kwargs,
    ))
    app.testing = True
    return app


def _post(client, blob: bytes, **params):
    q = {
        "kind": "npz",
        "stage_id": "iter_021_sp_v5",
        "shard_label": "mac-1",
        "claim_id": "iter_021_sp_v5:7",
    }
    q.update(params)
    return client.post(
        "/v2/artifact/upload",
        query_string={k: v for k, v in q.items() if v is not None},
        data=blob,
        content_type="application/octet-stream",
    )


# ---- happy path ---------------------------------------------------------


def test_upload_writes_bytes_and_returns_file_uri(tmp_path):
    up_dir = tmp_path / "artifact_uploads"
    client = _make_app(tmp_path, upload_dir=up_dir).test_client()
    blob = b"\x93NUMPY-ish-bytes" * 32

    res = _post(client, blob)
    assert res.status_code == 200
    body = res.get_json()

    expected_key = build_artifact_key(
        kind="npz", stage_id="iter_021_sp_v5",
        shard_label="mac-1", claim_id="iter_021_sp_v5:7",
    )
    assert body["key"] == expected_key
    assert body["bytes"] == len(blob)
    assert body["uri"].startswith("file:///")
    assert (up_dir / expected_key).read_bytes() == blob
    # The URI the coord hands back must be fetchable by the coord's
    # own LocalArtifactFetcher -- that's the whole point.
    assert LocalArtifactFetcher().fetch(body["uri"]) == blob


def test_upload_accepts_key_fields_via_headers(tmp_path):
    """Query params are the primary carrier, but headers work too --
    useful for proxies that strip query strings."""
    up_dir = tmp_path / "uploads"
    client = _make_app(tmp_path, upload_dir=up_dir).test_client()
    res = client.post(
        "/v2/artifact/upload",
        headers={
            "X-Artifact-kind": "replay",
            "X-Artifact-stage-id": "stage1",
            "X-Artifact-shard-label": "win10",
            "X-Artifact-claim-id": "stage1:3",
        },
        data=b"gzipped-replay",
        content_type="application/octet-stream",
    )
    assert res.status_code == 200, res.get_data(as_text=True)
    assert res.get_json()["key"].endswith(".json.gz")


def test_upload_is_idempotent_overwrites_same_path(tmp_path):
    up_dir = tmp_path / "uploads"
    client = _make_app(tmp_path, upload_dir=up_dir).test_client()
    first = _post(client, b"AAAA")
    second = _post(client, b"BBBB")
    assert first.get_json()["uri"] == second.get_json()["uri"]
    key = first.get_json()["key"]
    assert (up_dir / key).read_bytes() == b"BBBB"
    # No stray temp files left behind by the write-then-rename.
    assert not list(up_dir.rglob("*.tmp"))


def test_upload_creates_nested_dirs(tmp_path):
    up_dir = tmp_path / "deep" / "not" / "created" / "yet"
    client = _make_app(tmp_path, upload_dir=up_dir).test_client()
    res = _post(client, b"data")
    assert res.status_code == 200
    assert up_dir.is_dir()


def test_missing_shard_label_defaults_to_unknown(tmp_path):
    up_dir = tmp_path / "uploads"
    client = _make_app(tmp_path, upload_dir=up_dir).test_client()
    res = _post(client, b"data", shard_label=None)
    assert res.status_code == 200
    assert "/unknown/" in res.get_json()["key"]


# ---- validation ---------------------------------------------------------


def test_disabled_endpoint_returns_503(tmp_path):
    client = _make_app(tmp_path, upload_dir=None).test_client()
    res = _post(client, b"data")
    assert res.status_code == 503
    assert "artifact-upload-dir" in res.get_json()["error"]


@pytest.mark.parametrize("kind", ["", "weights", "NPZ"])
def test_bad_kind_is_400(tmp_path, kind):
    client = _make_app(tmp_path, upload_dir=tmp_path / "u").test_client()
    res = _post(client, b"data", kind=kind)
    assert res.status_code == 400
    assert "kind" in res.get_json()["error"]


@pytest.mark.parametrize("stage_id", ["", "has space", "has/slash"])
def test_bad_stage_id_is_400(tmp_path, stage_id):
    client = _make_app(tmp_path, upload_dir=tmp_path / "u").test_client()
    res = _post(client, b"data", stage_id=stage_id)
    assert res.status_code == 400


def test_bad_claim_id_is_400(tmp_path):
    client = _make_app(tmp_path, upload_dir=tmp_path / "u").test_client()
    res = _post(client, b"data", claim_id="has/slash")
    assert res.status_code == 400


def test_path_traversal_stage_id_is_rejected(tmp_path):
    """``..`` passes the ``[A-Za-z0-9_.\\-:]+`` allowlist (dots are
    legal in a stage_id) -- the traversal guard is what stops it."""
    up_dir = tmp_path / "uploads"
    client = _make_app(tmp_path, upload_dir=up_dir).test_client()
    res = _post(client, b"pwned", stage_id="..")
    assert res.status_code == 400
    assert "escapes" in res.get_json()["error"]
    # Nothing written anywhere near the parent dir.
    assert not list(tmp_path.glob("*.npz"))


def test_empty_body_is_400(tmp_path):
    client = _make_app(tmp_path, upload_dir=tmp_path / "u").test_client()
    res = _post(client, b"")
    assert res.status_code == 400
    assert "empty" in res.get_json()["error"]


def test_oversize_body_is_413(tmp_path):
    up_dir = tmp_path / "uploads"
    client = _make_app(
        tmp_path, upload_dir=up_dir, max_artifact_upload_bytes=64,
    ).test_client()
    res = _post(client, b"x" * 65)
    assert res.status_code == 413
    assert "too large" in res.get_json()["error"]
    assert not list(up_dir.rglob("*.npz"))


def test_default_cap_is_generous_enough_for_real_npzs():
    """Real self-play npzs are ~250 KB - 5 MB; the cap must not be
    anywhere near that."""
    assert MAX_ARTIFACT_UPLOAD_BYTES >= 32 * 1024 * 1024


# ---- the traversal helper directly --------------------------------------


@pytest.mark.parametrize("key", ["../evil.npz", "a/../../evil.npz", ""])
def test_safe_upload_target_rejects_escapes(tmp_path, key):
    assert _safe_upload_target(tmp_path, key) is None


def test_safe_upload_target_accepts_normal_key(tmp_path):
    target = _safe_upload_target(tmp_path, "stage/shard/claim.npz")
    assert target is not None
    assert target == tmp_path / "stage" / "shard" / "claim.npz"


# ---- end-to-end round trip over a real WSGI server ----------------------


def test_round_trip_uploader_server_fetcher(tmp_path):
    """The load-bearing test: a real ``HttpArtifactUploader`` POSTing
    over a real socket to the real blueprint, then the coordinator's
    ``LocalArtifactFetcher`` reading the returned URI back and
    getting byte-identical content."""
    from werkzeug.serving import make_server

    up_dir = tmp_path / "artifact_uploads"
    app = _make_app(tmp_path, upload_dir=up_dir)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        uploader = HttpArtifactUploader(f"http://127.0.0.1:{port}")
        blob = bytes(range(256)) * 400  # ~100 KB of non-text bytes
        uri = uploader.upload(
            blob, kind="npz", stage_id="iter_021_sp_v5",
            shard_label="mac-1", claim_id="iter_021_sp_v5:42",
        )
        assert uri.startswith("file:///")
        assert LocalArtifactFetcher().fetch(uri) == blob

        # Re-upload (the retry case): same URI, same bytes.
        uri2 = uploader.upload(
            blob, kind="npz", stage_id="iter_021_sp_v5",
            shard_label="mac-1", claim_id="iter_021_sp_v5:42",
        )
        assert uri2 == uri
        assert LocalArtifactFetcher().fetch(uri2) == blob
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_round_trip_client_error_surfaces_loudly(tmp_path):
    """A 400 from the endpoint must reach the worker as a loud
    RuntimeError, not a silent drop -- the whole point of this
    feature."""
    from werkzeug.serving import make_server

    app = _make_app(tmp_path, upload_dir=None)  # endpoint disabled
    server = make_server("127.0.0.1", 0, app, threaded=True)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        import mtg_bot.worker_daemon_storage as _wds
        sleeps: list[float] = []
        real_sleep = _wds.time.sleep
        _wds.time.sleep = lambda s: sleeps.append(s)
        try:
            uploader = HttpArtifactUploader(f"http://127.0.0.1:{port}")
            with pytest.raises(Exception) as exc:
                uploader.upload(
                    b"x", kind="npz", stage_id="s",
                    shard_label="w", claim_id="c",
                )
            assert "503" in str(exc.value)
        finally:
            _wds.time.sleep = real_sleep
    finally:
        server.shutdown()
        thread.join(timeout=5)
