"""Tests for ``mtg_bot.cli.runs.coordinator_artifact_fetcher``.

Covers the ``ArtifactFetcher`` ABC, ``LocalArtifactFetcher``,
``MultiSchemeFetcher`` dispatch, and ``S3ArtifactFetcher`` (with
moto-backed boto3 client for happy-path + retry + fail-loud).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from mtg_bot.cli.runs.coordinator_artifact_fetcher import (
    ArtifactFetcher,
    LocalArtifactFetcher,
    MultiSchemeFetcher,
    S3ArtifactFetcher,
)


# ---- LocalArtifactFetcher -----------------------------------------------


def test_local_fetcher_reads_file_uri(tmp_path: Path):
    target = tmp_path / "blob.npz"
    target.write_bytes(b"deadbeef")
    uri = "file:///" + target.as_posix().lstrip("/")
    assert LocalArtifactFetcher().fetch(uri) == b"deadbeef"


def test_local_fetcher_rejects_non_file_scheme():
    with pytest.raises(ValueError, match="file://"):
        LocalArtifactFetcher().fetch("s3://bucket/key")


def test_local_fetcher_raises_on_missing_file(tmp_path: Path):
    uri = "file:///" + (tmp_path / "nope.npz").as_posix().lstrip("/")
    with pytest.raises(FileNotFoundError):
        LocalArtifactFetcher().fetch(uri)


# ---- MultiSchemeFetcher dispatch ----------------------------------------


def test_multi_scheme_dispatches_file_to_local(tmp_path: Path):
    blob = tmp_path / "x.npz"
    blob.write_bytes(b"AAA")
    fetcher = MultiSchemeFetcher()
    uri = "file:///" + blob.as_posix().lstrip("/")
    assert fetcher.fetch(uri) == b"AAA"


def test_multi_scheme_uses_injected_local_fetcher(tmp_path: Path):
    # Custom local fetcher is honored when explicitly provided
    # (lets tests intercept reads).
    seen: list[str] = []

    class _Spy(ArtifactFetcher):
        def fetch(self, uri: str) -> bytes:
            seen.append(uri)
            return b"spy"

    fetcher = MultiSchemeFetcher(local=_Spy())
    blob = tmp_path / "y.npz"
    uri = "file:///" + blob.as_posix().lstrip("/")
    assert fetcher.fetch(uri) == b"spy"
    assert seen == [uri]


def test_multi_scheme_s3_uri_without_s3_fetcher_raises():
    fetcher = MultiSchemeFetcher()  # no s3= injected
    with pytest.raises(RuntimeError, match="no S3 fetcher is"):
        fetcher.fetch("s3://mtg-bot-artifacts/key.npz")


def test_multi_scheme_unsupported_scheme_raises():
    with pytest.raises(ValueError, match="unsupported"):
        MultiSchemeFetcher().fetch("ftp://nope/path")


def test_multi_scheme_dispatches_s3_to_s3_fetcher():
    """When the s3 arm is configured the dispatcher hands the URI
    over verbatim. We swap in a stub fetcher rather than wiring
    moto here -- this test is about dispatch, not S3 mechanics."""

    seen: list[str] = []

    class _S3Spy(ArtifactFetcher):
        def fetch(self, uri: str) -> bytes:
            seen.append(uri)
            return b"s3-spy"

    fetcher = MultiSchemeFetcher(s3=_S3Spy())
    assert fetcher.fetch("s3://bkt/key.npz") == b"s3-spy"
    assert seen == ["s3://bkt/key.npz"]


# ---- S3ArtifactFetcher --------------------------------------------------


@pytest.fixture
def s3_bucket():
    """Stand up a moto-backed S3 bucket with a couple of objects."""
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="mtg-bot-artifacts-test")
        client.put_object(
            Bucket="mtg-bot-artifacts-test",
            Key="stg/wA/c1.npz",
            Body=b"npz-bytes-from-s3",
        )
        client.put_object(
            Bucket="mtg-bot-artifacts-test",
            Key="stg/wA/c1.json.gz",
            Body=b"replay-bytes-from-s3",
        )
        yield client


def test_s3_fetcher_happy_path(s3_bucket):
    fetcher = S3ArtifactFetcher(region="us-east-1", client=s3_bucket)
    got = fetcher.fetch("s3://mtg-bot-artifacts-test/stg/wA/c1.npz")
    assert got == b"npz-bytes-from-s3"


def test_s3_fetcher_replay_path(s3_bucket):
    fetcher = S3ArtifactFetcher(region="us-east-1", client=s3_bucket)
    got = fetcher.fetch("s3://mtg-bot-artifacts-test/stg/wA/c1.json.gz")
    assert got == b"replay-bytes-from-s3"


def test_s3_fetcher_404_fails_loud_no_retry(s3_bucket):
    """404 (NoSuchKey) is a permanent error -- fail immediately
    rather than burning the 14s retry budget."""
    fetcher = S3ArtifactFetcher(region="us-east-1", client=s3_bucket)
    with pytest.raises(ClientError) as exc_info:
        fetcher.fetch("s3://mtg-bot-artifacts-test/missing.npz")
    # moto returns 404 for missing keys.
    assert exc_info.value.response["ResponseMetadata"][
        "HTTPStatusCode"
    ] == 404


def test_s3_fetcher_403_fails_loud_no_retry():
    """403 (AccessDenied) is a permissions error -- same treatment
    as 404. We can't easily produce a real 403 from moto, so stub
    the client and assert no retries fired."""
    client = MagicMock()
    err_response = {
        "Error": {"Code": "AccessDenied", "Message": "denied"},
        "ResponseMetadata": {"HTTPStatusCode": 403},
    }
    client.get_object.side_effect = ClientError(err_response, "GetObject")
    fetcher = S3ArtifactFetcher(region="us-east-1", client=client)
    with pytest.raises(ClientError):
        fetcher.fetch("s3://bkt/k")
    # Only the initial attempt; no retries on a permission error.
    assert client.get_object.call_count == 1


def test_s3_fetcher_retries_on_5xx_then_succeeds(monkeypatch):
    """503 surfaces twice, then a real Body. The fetcher should
    sleep between attempts (we monkey-patch ``time.sleep`` to keep
    the test fast)."""
    sleeps: list[float] = []
    monkeypatch.setattr(
        "mtg_bot.cli.runs.coordinator_artifact_fetcher.time.sleep",
        lambda s: sleeps.append(s),
    )
    client = MagicMock()
    transient_err = ClientError(
        {
            "Error": {"Code": "ServiceUnavailable", "Message": "busy"},
            "ResponseMetadata": {"HTTPStatusCode": 503},
        },
        "GetObject",
    )
    body = MagicMock()
    body.read.return_value = b"finally"
    client.get_object.side_effect = [
        transient_err, transient_err, {"Body": body},
    ]
    fetcher = S3ArtifactFetcher(region="us-east-1", client=client)
    assert fetcher.fetch("s3://bkt/k") == b"finally"
    assert client.get_object.call_count == 3
    # Two backoff sleeps (1.0, 3.0) before the third attempt
    # succeeded; the 10.0s sleep is never reached.
    assert sleeps == [1.0, 3.0]


def test_s3_fetcher_retries_on_throttling_then_succeeds(monkeypatch):
    """429 (Throttling) is also retryable."""
    monkeypatch.setattr(
        "mtg_bot.cli.runs.coordinator_artifact_fetcher.time.sleep",
        lambda s: None,
    )
    client = MagicMock()
    throttle = ClientError(
        {
            "Error": {"Code": "Throttling", "Message": "slow down"},
            "ResponseMetadata": {"HTTPStatusCode": 429},
        },
        "GetObject",
    )
    body = MagicMock()
    body.read.return_value = b"ok"
    client.get_object.side_effect = [throttle, {"Body": body}]
    fetcher = S3ArtifactFetcher(region="us-east-1", client=client)
    assert fetcher.fetch("s3://bkt/k") == b"ok"
    assert client.get_object.call_count == 2


def test_s3_fetcher_gives_up_after_final_retry(monkeypatch):
    """Four transient failures (initial + 3 retries) → propagate
    the last exception."""
    monkeypatch.setattr(
        "mtg_bot.cli.runs.coordinator_artifact_fetcher.time.sleep",
        lambda s: None,
    )
    client = MagicMock()
    transient = ClientError(
        {
            "Error": {"Code": "InternalError", "Message": "boom"},
            "ResponseMetadata": {"HTTPStatusCode": 500},
        },
        "GetObject",
    )
    client.get_object.side_effect = [transient] * 4
    fetcher = S3ArtifactFetcher(region="us-east-1", client=client)
    with pytest.raises(ClientError):
        fetcher.fetch("s3://bkt/k")
    assert client.get_object.call_count == 4


def test_s3_fetcher_rejects_non_s3_uri():
    fetcher = S3ArtifactFetcher(client=MagicMock())
    with pytest.raises(ValueError, match="s3://"):
        fetcher.fetch("file:///tmp/x")


def test_s3_fetcher_rejects_missing_bucket():
    fetcher = S3ArtifactFetcher(client=MagicMock())
    with pytest.raises(ValueError, match="missing bucket"):
        fetcher.fetch("s3:///just/a/key")


def test_s3_fetcher_rejects_missing_key():
    fetcher = S3ArtifactFetcher(client=MagicMock())
    with pytest.raises(ValueError, match="missing key"):
        fetcher.fetch("s3://bucket-only")


def test_s3_fetcher_builds_default_client_lazily():
    """No injected client → first ``fetch`` call constructs one
    via ``boto3.client``. We verify the lazy build without
    actually hitting AWS."""
    with patch(
        "boto3.client", return_value=MagicMock()
    ) as boto_client:
        fetcher = S3ArtifactFetcher(region="us-west-2")
        # Not built at construction time.
        assert boto_client.call_count == 0
        body = MagicMock()
        body.read.return_value = b"x"
        fetcher._client = None  # force the lazy build path
        boto_client.return_value.get_object.return_value = {"Body": body}
        # Force lazy resolution via a real call.
        fetcher._get_client().get_object.return_value = {"Body": body}
        # _get_client builds once and reuses afterward.
        fetcher._get_client()
        boto_client.assert_called_once_with("s3", region_name="us-west-2")


# ---- ABC contract -------------------------------------------------------


def test_abc_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        ArtifactFetcher()  # type: ignore[abstract]
