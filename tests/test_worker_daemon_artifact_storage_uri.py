"""Worker-daemon CLI flag + ``create_app`` wiring for
``--artifact-storage-uri`` (Phase 2A drop-off-protocol).

The new flag picks the worker's :class:`ArtifactUploader` (S3 /
file:// / null://). It's worker-owned config — set per-machine in
the native service file's ``ExecStart``, NOT carried in the
orchestrator's ``/v2/start_*`` request body, same shape as
``--n-workers`` / ``--deck-pool-path`` / ``--nn-device`` /
``--spot-watch``. These tests pin:

1. argparse — flag defaults to ``null://``, accepts any URI string.
2. ``create_app`` — instantiates the right uploader from the URI at
   boot (fail-fast for bad schemes).
3. ``ClaimLoopConfig`` wiring — the uploader the daemon built is
   threaded into the ``ClaimLoopConfig`` the runner factory gets.

The drop-off + JSON-ping wire shape itself is covered in
``test_worker_daemon_claim_loop.py``; this file owns only the CLI
and create_app plumbing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mtg_bot import worker_daemon
from mtg_bot import worker_daemon_claim_loop as cl
from mtg_bot.worker_daemon_storage import (
    LocalFileUploader,
    NullUploader,
    S3ArtifactUploader,
)


# ---------------------------------------------------------------------------
# Layer 1: argparse — default ``null://``, free-form URI string.
# ---------------------------------------------------------------------------


def test_parser_artifact_storage_uri_defaults_to_null():
    """Default keeps existing daemons + tests byte-identical to pre-
    flag behavior: blobs go to ``NullUploader`` (floor-drop), the
    claim-loop's JSON ping still ships, and the legacy multipart
    coord rejects on the missing blob — same loud-fail surface as
    pre-flag, no silent degradation."""
    parser = worker_daemon._build_parser()
    args = parser.parse_args([])
    assert args.artifact_storage_uri == "null://"


@pytest.mark.parametrize(
    "value",
    [
        "null://",
        "file:///tmp/artifacts",
        "s3://my-bucket",
        "s3://my-bucket/with/prefix",
    ],
)
def test_parser_artifact_storage_uri_accepts_supported_schemes(value):
    parser = worker_daemon._build_parser()
    args = parser.parse_args(["--artifact-storage-uri", value])
    assert args.artifact_storage_uri == value


# ---------------------------------------------------------------------------
# Layer 2: create_app builds the uploader at boot via uploader_from_uri.
# Bad schemes raise immediately — fail the daemon fast at boot rather
# than per-claim.
# ---------------------------------------------------------------------------


def test_create_app_default_artifact_uploader_is_null():
    app = worker_daemon.create_app(start_delay_s=0.01)
    assert app.config["ARTIFACT_STORAGE_URI"] == "null://"
    assert isinstance(app.config["ARTIFACT_UPLOADER"], NullUploader)


def test_create_app_file_uri_builds_local_uploader(tmp_path):
    uri = "file:///" + tmp_path.as_posix().lstrip("/")
    app = worker_daemon.create_app(
        start_delay_s=0.01, artifact_storage_uri=uri,
    )
    uploader = app.config["ARTIFACT_UPLOADER"]
    assert isinstance(uploader, LocalFileUploader)
    # Round-trip the URI to a Path and verify it points at tmp_path.
    assert uploader.root.resolve() == tmp_path.resolve()


def test_create_app_s3_uri_builds_s3_uploader(monkeypatch):
    """The s3:// scheme should produce an ``S3ArtifactUploader``
    pointed at the bucket / prefix encoded in the URI. We stub
    ``boto3.client`` so create_app doesn't need real AWS creds."""
    class _FakeBoto3:
        @staticmethod
        def client(name, *_args, **_kwargs):
            assert name == "s3"
            return object()  # opaque sentinel; tests never call put_object

    monkeypatch.setitem(__import__("sys").modules, "boto3", _FakeBoto3)
    app = worker_daemon.create_app(
        start_delay_s=0.01,
        artifact_storage_uri="s3://prod-bucket/artifacts/v1",
    )
    uploader = app.config["ARTIFACT_UPLOADER"]
    assert isinstance(uploader, S3ArtifactUploader)
    assert uploader.bucket == "prod-bucket"
    assert uploader.prefix == "artifacts/v1"


def test_create_app_rejects_unsupported_scheme():
    """A bad URI fails fast at create_app — better than crashing the
    first time a worker tries to report a result."""
    with pytest.raises(ValueError, match="unsupported artifact storage URI"):
        worker_daemon.create_app(
            start_delay_s=0.01,
            artifact_storage_uri="gs://not-supported-yet",
        )


# ---------------------------------------------------------------------------
# Layer 3: the uploader stored on app.config is the same instance the
# ClaimLoopConfig handed to the runner factory carries. (Sharing one
# instance means file/s3 client setup happens once at daemon boot,
# not per claim.)
# ---------------------------------------------------------------------------


def test_create_app_threads_artifact_uploader_into_claim_loop_config(
    tmp_path,
):
    captured: list = []

    def recording_factory(kind, cfg, cbs):
        captured.append(cfg)
        # No-op runner: we only care about the cfg snapshot.
        return cl.CallableGameRunner(
            lambda claim, label: cl.GameResult(
                outcome="completed", winner=None, n_samples=0,
                duration_s=0.0,
            ),
            None,
            None,
        )

    uri = "file:///" + tmp_path.as_posix().lstrip("/")
    app = worker_daemon.create_app(
        start_delay_s=0.01,
        artifact_storage_uri=uri,
        runner_factory=recording_factory,
    )
    app.testing = True
    client = app.test_client()
    resp = client.post(
        "/v2/start_self_play",
        json={"stage_id": "s1", "coordinator_url": "http://coord:5099"},
    )
    assert resp.status_code == 202
    assert captured, "runner factory was never invoked"
    # Same instance — not just an equal-but-different uploader.
    assert captured[0].artifact_uploader is app.config["ARTIFACT_UPLOADER"]
    assert isinstance(captured[0].artifact_uploader, LocalFileUploader)


def test_create_app_default_threads_null_uploader_into_claim_loop_config():
    """Default ``null://`` flows through — the existing test suite's
    daemons (which don't pass ``artifact_storage_uri=``) keep getting
    a NullUploader, byte-identical to the pre-flag default for
    ``ClaimLoopConfig``."""
    captured: list = []

    def recording_factory(kind, cfg, cbs):
        captured.append(cfg)
        return cl.CallableGameRunner(
            lambda claim, label: cl.GameResult(
                outcome="completed", winner=None, n_samples=0,
                duration_s=0.0,
            ),
            None,
            None,
        )

    app = worker_daemon.create_app(
        start_delay_s=0.01, runner_factory=recording_factory,
    )
    app.testing = True
    client = app.test_client()
    resp = client.post(
        "/v2/start_self_play",
        json={"stage_id": "s1", "coordinator_url": "http://coord:5099"},
    )
    assert resp.status_code == 202
    assert isinstance(captured[0].artifact_uploader, NullUploader)


# ---------------------------------------------------------------------------
# Layer 4: /v2/heartbeat advertises the configured storage URI so the
# launcher can pre-flight it. Without this the 2026-09-23 cycle had no
# way to notice both daemons were on the null:// default until after
# 500 games had been played and thrown away.
# ---------------------------------------------------------------------------


def test_heartbeat_exposes_default_null_artifact_storage_uri():
    app = worker_daemon.create_app(start_delay_s=0.01)
    app.testing = True
    body = app.test_client().get("/v2/heartbeat").get_json()
    assert body["artifact_storage_uri"] == "null://"


def test_heartbeat_exposes_configured_artifact_storage_uri(tmp_path):
    uri = "file:///" + tmp_path.as_posix().lstrip("/")
    app = worker_daemon.create_app(
        start_delay_s=0.01, artifact_storage_uri=uri,
    )
    app.testing = True
    body = app.test_client().get("/v2/heartbeat").get_json()
    assert body["artifact_storage_uri"] == uri


def test_heartbeat_artifact_storage_uri_matches_app_config():
    """The heartbeat must report the SAME value ``create_app`` built
    the uploader from -- not a separately-parsed copy that could
    drift."""
    app = worker_daemon.create_app(
        start_delay_s=0.01,
        artifact_storage_uri="http://desktop-j05412i:5099",
    )
    app.testing = True
    body = app.test_client().get("/v2/heartbeat").get_json()
    assert body["artifact_storage_uri"] == app.config["ARTIFACT_STORAGE_URI"]
