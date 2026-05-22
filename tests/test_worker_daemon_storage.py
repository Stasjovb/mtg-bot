"""Tests for ``mtg_bot.worker_daemon_storage``.

Surface: the ``ArtifactUploader`` ABC, the ``LocalFileUploader`` /
``NullUploader`` / ``S3ArtifactUploader`` concrete impls, the
``uploader_from_uri`` factory, and the deterministic
``build_artifact_key`` helper. The S3 path uses ``moto[s3]`` to mock
the AWS API in-process — no real network, no real creds.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from urllib.parse import urlparse

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from mtg_bot.worker_daemon_storage import (
    ArtifactUploader,
    LocalFileUploader,
    NullUploader,
    S3ArtifactUploader,
    build_artifact_key,
    uploader_from_uri,
)


# ---- build_artifact_key -------------------------------------------------


def test_build_artifact_key_npz_default_extension():
    key = build_artifact_key(
        kind="npz", stage_id="iter_020_sp_v13s",
        shard_label="mac-1", claim_id="abc:def",
    )
    assert key == "iter_020_sp_v13s/mac-1/abc_def.npz"


def test_build_artifact_key_replay_uses_json_gz_extension():
    key = build_artifact_key(
        kind="replay", stage_id="stg",
        shard_label="aws-warm", claim_id="c1",
    )
    assert key.endswith(".json.gz")


def test_build_artifact_key_sanitizes_separators_in_claim_id():
    # claim_id is allowed to contain ":" and "/" (some
    # orchestrators include path-like fragments); the key must
    # not introduce extra directory levels.
    key = build_artifact_key(
        kind="npz", stage_id="s",
        shard_label="w", claim_id="stage:00/game:42",
    )
    assert "/" not in key.split("/", 2)[2]  # last segment is flat


def test_build_artifact_key_missing_shard_falls_back_to_unknown():
    key = build_artifact_key(
        kind="npz", stage_id="s", shard_label="", claim_id="c1",
    )
    assert "/unknown/" in key


def test_build_artifact_key_is_deterministic():
    # Two calls with the same inputs produce the same key; this is
    # what makes upload retries idempotent.
    args = dict(
        kind="npz", stage_id="s", shard_label="w", claim_id="c1",
    )
    assert build_artifact_key(**args) == build_artifact_key(**args)


# ---- LocalFileUploader --------------------------------------------------


def test_local_uploader_writes_file_and_returns_file_uri(tmp_path: Path):
    up = LocalFileUploader(tmp_path)
    uri = up.upload(
        b"hello", kind="npz",
        stage_id="stg", shard_label="w", claim_id="c1",
    )
    assert uri.startswith("file:///")
    parsed = urlparse(uri)
    # urlparse strips the leading slash on Windows drive-letter
    # paths; on POSIX it stays. Either way the path should round-
    # trip back to bytes we wrote.
    raw = parsed.path
    if len(raw) >= 3 and raw[0] == "/" and raw[2] == ":":
        raw = raw[1:]
    assert Path(raw).read_bytes() == b"hello"


def test_local_uploader_creates_parent_dirs(tmp_path: Path):
    nested = tmp_path / "does" / "not" / "yet" / "exist"
    up = LocalFileUploader(nested)
    up.upload(
        b"x", kind="npz",
        stage_id="s", shard_label="w", claim_id="c",
    )
    # Parent dirs come into existence as needed.
    assert (nested / "s" / "w" / "c.npz").is_file()


def test_local_uploader_retry_overwrites_with_same_bytes(tmp_path: Path):
    # Determinism guarantee: retrying the upload writes byte-
    # identical content to the same key.
    up = LocalFileUploader(tmp_path)
    uri_a = up.upload(
        b"AAA", kind="npz",
        stage_id="s", shard_label="w", claim_id="c",
    )
    uri_b = up.upload(
        b"AAA", kind="npz",
        stage_id="s", shard_label="w", claim_id="c",
    )
    assert uri_a == uri_b


# ---- NullUploader -------------------------------------------------------


def test_null_uploader_returns_null_scheme_uri():
    up = NullUploader()
    uri = up.upload(
        b"x", kind="npz",
        stage_id="s", shard_label="w", claim_id="c",
    )
    assert uri.startswith("null:///")
    assert uri.endswith("c.npz")


# ---- uploader_from_uri factory ------------------------------------------


def test_factory_file_scheme_returns_local_uploader(tmp_path: Path):
    up = uploader_from_uri(f"file:///{tmp_path.as_posix().lstrip('/')}")
    assert isinstance(up, LocalFileUploader)


def test_factory_null_scheme_returns_null_uploader():
    up = uploader_from_uri("null://anywhere")
    assert isinstance(up, NullUploader)


def test_factory_unsupported_scheme_raises():
    with pytest.raises(ValueError, match="unsupported"):
        uploader_from_uri("ftp://nope/")


# ---- S3 uploader (Phase 2A — moto-backed) ------------------------------


_S3_REGION = "us-east-1"
_S3_BUCKET = "mtg-bot-artifacts-test"


@pytest.fixture
def s3_client(monkeypatch):
    """A moto-mocked boto3 S3 client + bucket.

    Sets dummy AWS creds in the environment so boto3's credential-
    resolution chain finds something even on hosts that have no real
    AWS config — moto intercepts the request before any real signing
    matters, but the SDK still demands the variables exist.
    """
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", _S3_REGION)
    with mock_aws():
        client = boto3.client("s3", region_name=_S3_REGION)
        client.create_bucket(Bucket=_S3_BUCKET)
        yield client


def test_s3_uploader_happy_put_returns_s3_uri_and_writes_bytes(s3_client):
    up = S3ArtifactUploader(bucket=_S3_BUCKET, client=s3_client)
    uri = up.upload(
        b"PAYLOAD", kind="npz",
        stage_id="iter_020_sp_v13s",
        shard_label="mac-1",
        claim_id="iter_020:000042",
    )
    # URI scheme + bucket + deterministic key derived from inputs.
    assert uri == (
        "s3://mtg-bot-artifacts-test/"
        "iter_020_sp_v13s/mac-1/iter_020_000042.npz"
    )
    # Bytes actually landed at the expected key.
    obj = s3_client.get_object(
        Bucket=_S3_BUCKET,
        Key="iter_020_sp_v13s/mac-1/iter_020_000042.npz",
    )
    assert obj["Body"].read() == b"PAYLOAD"


def test_s3_uploader_prefix_is_prepended_to_key(s3_client):
    up = S3ArtifactUploader(
        bucket=_S3_BUCKET, prefix="mtg-bot/prod/", client=s3_client,
    )
    uri = up.upload(
        b"X", kind="npz",
        stage_id="s", shard_label="w", claim_id="c1",
    )
    # Prefix's leading/trailing slashes are stripped, then joined with
    # the build_artifact_key result via a single '/'.
    assert uri == "s3://mtg-bot-artifacts-test/mtg-bot/prod/s/w/c1.npz"
    s3_client.head_object(
        Bucket=_S3_BUCKET, Key="mtg-bot/prod/s/w/c1.npz",
    )


def test_s3_uploader_empty_prefix_does_not_add_leading_slash(s3_client):
    up = S3ArtifactUploader(bucket=_S3_BUCKET, prefix="", client=s3_client)
    uri = up.upload(
        b"X", kind="npz",
        stage_id="s", shard_label="w", claim_id="c1",
    )
    # No empty path segment — the key starts with the stage_id.
    assert uri == "s3://mtg-bot-artifacts-test/s/w/c1.npz"


def test_s3_uploader_retry_overwrites_with_same_key_and_uri(s3_client):
    """Determinism: re-uploading with the same inputs writes byte-
    identical content to the same key and returns the same URI. This
    is what makes upload retries safe — the coordinator can fetch the
    URI once and get the correct bytes regardless of how many worker-
    side retries happened."""
    up = S3ArtifactUploader(bucket=_S3_BUCKET, client=s3_client)
    uri_a = up.upload(
        b"AAA", kind="npz",
        stage_id="s", shard_label="w", claim_id="c",
    )
    uri_b = up.upload(
        b"AAA", kind="npz",
        stage_id="s", shard_label="w", claim_id="c",
    )
    assert uri_a == uri_b
    obj = s3_client.get_object(
        Bucket=_S3_BUCKET, Key="s/w/c.npz",
    )
    assert obj["Body"].read() == b"AAA"


def test_s3_uploader_retries_on_throttling_then_succeeds(monkeypatch):
    """A transient ``Throttling`` ClientError retries on the
    backoff schedule and eventually succeeds. We use a hand-rolled
    mock client because moto doesn't surface throttling failures."""
    calls: list[int] = []

    class FlakyClient:
        def put_object(self, *, Bucket, Key, Body):
            calls.append(1)
            if len(calls) < 3:
                raise ClientError(
                    {"Error": {"Code": "Throttling", "Message": "slow down"}},
                    "PutObject",
                )
            return {"ETag": '"abc"'}

    # Skip the real backoff sleeps to keep the test wall-time tiny.
    from mtg_bot import worker_daemon_storage as _wds

    monkeypatch.setattr(_wds.time, "sleep", lambda *_a, **_k: None)
    up = S3ArtifactUploader(
        bucket=_S3_BUCKET, client=FlakyClient(),
    )
    uri = up.upload(
        b"X", kind="npz",
        stage_id="s", shard_label="w", claim_id="c",
    )
    assert uri == "s3://mtg-bot-artifacts-test/s/w/c.npz"
    assert len(calls) == 3  # 1 initial + 2 retries before success


def test_s3_uploader_fails_loud_on_permission_error_no_retry(monkeypatch):
    """``AccessDenied`` is an operator-config bug; the uploader must
    raise on the first attempt rather than burn the retry budget on
    something that won't get better."""
    calls: list[int] = []

    class DeniedClient:
        def put_object(self, *, Bucket, Key, Body):
            calls.append(1)
            raise ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "nope"}},
                "PutObject",
            )

    from mtg_bot import worker_daemon_storage as _wds

    monkeypatch.setattr(_wds.time, "sleep", lambda *_a, **_k: None)
    up = S3ArtifactUploader(
        bucket=_S3_BUCKET, client=DeniedClient(),
    )
    with pytest.raises(ClientError, match="AccessDenied"):
        up.upload(
            b"X", kind="npz",
            stage_id="s", shard_label="w", claim_id="c",
        )
    assert len(calls) == 1  # one attempt — no retry burn


def test_s3_uploader_retries_exhausted_raises_last_transient_error(
    monkeypatch,
):
    """If the throttling never clears within the retry budget, the
    last ClientError surfaces so the claim-loop's error handling sees
    it (the loop's own retry/back-off then either succeeds on a later
    game or marks the daemon ERROR)."""
    calls: list[int] = []

    class AlwaysThrottlingClient:
        def put_object(self, *, Bucket, Key, Body):
            calls.append(1)
            raise ClientError(
                {"Error": {"Code": "SlowDown", "Message": "too fast"}},
                "PutObject",
            )

    from mtg_bot import worker_daemon_storage as _wds

    monkeypatch.setattr(_wds.time, "sleep", lambda *_a, **_k: None)
    up = S3ArtifactUploader(
        bucket=_S3_BUCKET, client=AlwaysThrottlingClient(),
    )
    with pytest.raises(ClientError, match="SlowDown"):
        up.upload(
            b"X", kind="npz",
            stage_id="s", shard_label="w", claim_id="c",
        )
    # 1 initial + len(S3_RETRY_BACKOFF_S) retries = 4 attempts total.
    assert len(calls) == 1 + len(_wds.S3_RETRY_BACKOFF_S)


def test_s3_uploader_factory_returns_s3_uploader_for_s3_scheme():
    """The factory wiring + the no-pragma path through ``uploader_from_uri``
    builds an S3ArtifactUploader with the parsed bucket + prefix."""
    # Constructing through the factory pulls in the real boto3 client
    # path; patch it so we don't need AWS creds for this construct
    # test.
    fake = MagicMock()
    import mtg_bot.worker_daemon_storage as _wds

    real_init = _wds.S3ArtifactUploader.__init__

    def patched_init(self, bucket, prefix="", *, client=None):
        real_init(self, bucket, prefix, client=client or fake)

    _wds.S3ArtifactUploader.__init__ = patched_init
    try:
        up = uploader_from_uri("s3://my-bucket/some/prefix")
        assert isinstance(up, S3ArtifactUploader)
        assert up.bucket == "my-bucket"
        assert up.prefix == "some/prefix"
    finally:
        _wds.S3ArtifactUploader.__init__ = real_init


# ---- ABC contract -------------------------------------------------------


def test_abc_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        ArtifactUploader()  # type: ignore[abstract]
