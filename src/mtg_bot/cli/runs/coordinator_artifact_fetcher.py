"""Coordinator-side fetcher for worker-uploaded artifacts.

The new ``/v2/report_result`` accepts JSON with ``npz_uri`` /
``replay_uri`` fields instead of multipart ``.npz`` blobs. The
coord uses an ``ArtifactFetcher`` to pull the bytes from the URI
and rehydrates them into ``iterate_data/`` so the trainer (which
still reads local paths) keeps working unchanged.

Fetches happen on a background ``ThreadPoolExecutor`` so the
POST handler returns 202 immediately -- the request thread does
not block on the network read or the disk write.

This module owns the coord side: the ``ArtifactFetcher`` ABC,
the concrete ``LocalArtifactFetcher``, a ``MultiSchemeFetcher``
that dispatches by URI scheme, and the ``S3ArtifactFetcher``
that wraps ``boto3 GetObject`` with retry/backoff. The matching
worker-side uploader lives at ``mtg_bot.worker_daemon_storage``.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse


# Retry schedule applied by ``S3ArtifactFetcher.fetch`` on transient
# errors (5xx, throttling). Total worst-case wait before giving up is
# 1 + 3 + 10 = 14s; the per-attempt boto3 client also has its own
# socket-level retries on top.
_S3_RETRY_BACKOFF_SECONDS = (1.0, 3.0, 10.0)

# HTTP status codes (boto3 surfaces these on the underlying
# ``ClientError.response["ResponseMetadata"]["HTTPStatusCode"]``).
# 5xx + 429 are retryable; everything else (incl. 403/404) is fail-
# loud — retrying a permissions error or a missing-key error just
# wastes time.
_S3_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


def _file_uri_to_path(uri: str) -> Path:
    """Parse a ``file://`` URI into a Path. See the matching helper
    in ``worker_daemon_storage`` -- duplicated here so the coord
    module has no worker-side dependency."""
    parsed = urlparse(uri)
    path = parsed.path
    if len(path) >= 3 and path[0] == "/" and path[2] == ":":
        # Windows: file:///C:/foo -> /C:/foo -> C:/foo
        path = path[1:]
    return Path(path)


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    """``s3://bucket/key/path`` -> ``("bucket", "key/path")``.

    Raises ``ValueError`` on a malformed URI (missing bucket, empty
    key). The fetcher uses this so a bad URI fails up-front rather
    than turning into a boto3 client error mid-retry-loop.
    """
    parsed = urlparse(uri)
    if parsed.scheme != "s3":
        raise ValueError(
            f"S3ArtifactFetcher only handles s3:// URIs, "
            f"got scheme={parsed.scheme!r}",
        )
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    if not bucket:
        raise ValueError(f"s3 URI missing bucket: {uri!r}")
    if not key:
        raise ValueError(f"s3 URI missing key: {uri!r}")
    return bucket, key


class ArtifactFetcher(ABC):
    """Coordinator-side strategy for pulling artifact bytes from
    a worker-uploaded URI."""

    @abstractmethod
    def fetch(self, uri: str) -> bytes:
        """Return the artifact bytes. Raises on any error; the
        caller's async executor handles retry + failure logging."""


class LocalArtifactFetcher(ArtifactFetcher):
    """Reads ``file://`` URIs from the local filesystem (or an
    SMB/NFS share mounted there)."""

    def fetch(self, uri: str) -> bytes:
        parsed = urlparse(uri)
        if parsed.scheme != "file":
            raise ValueError(
                f"LocalArtifactFetcher only handles file:// URIs, "
                f"got scheme={parsed.scheme!r}"
            )
        return _file_uri_to_path(uri).read_bytes()


class S3ArtifactFetcher(ArtifactFetcher):
    """Reads ``s3://`` URIs via boto3 ``GetObject``.

    Retries transient errors (5xx, throttling) with 1s/3s/10s
    backoff. 403/404 fail-loud immediately — those are
    configuration/permission errors that no amount of retry will
    fix; the caller's async executor logs the failure and writes
    an ``upload_failed`` row.

    ``client`` is exposed for tests so a moto-backed boto3 client
    can be injected without monkey-patching ``boto3.client``. In
    production we build the client lazily at first use; that keeps
    import time cheap on machines that have boto3 installed but
    don't actually use S3.
    """

    def __init__(
        self,
        region: str = "us-east-1",
        *,
        client: Optional[Any] = None,
    ) -> None:
        self.region = region
        self._explicit_client = client
        self._client: Optional[Any] = client

    def _get_client(self) -> Any:
        if self._client is None:
            # Local import so the module is importable on hosts
            # without boto3 installed -- the import error only
            # surfaces when an S3 fetch is actually attempted.
            import boto3  # noqa: WPS433
            self._client = boto3.client("s3", region_name=self.region)
        return self._client

    def fetch(self, uri: str) -> bytes:
        from botocore.exceptions import ClientError  # noqa: WPS433

        bucket, key = _parse_s3_uri(uri)
        client = self._get_client()
        last_exc: Optional[BaseException] = None
        # One initial attempt + len(backoff) retries.
        for attempt in range(len(_S3_RETRY_BACKOFF_SECONDS) + 1):
            try:
                response = client.get_object(Bucket=bucket, Key=key)
                return response["Body"].read()
            except ClientError as exc:
                status = (
                    exc.response.get("ResponseMetadata", {})
                    .get("HTTPStatusCode")
                )
                if status not in _S3_RETRYABLE_STATUS:
                    # 403 / 404 / 400 / etc. — fail-loud immediately.
                    raise
                last_exc = exc
                if attempt >= len(_S3_RETRY_BACKOFF_SECONDS):
                    # Final attempt failed; propagate.
                    raise
                time.sleep(_S3_RETRY_BACKOFF_SECONDS[attempt])
        # Unreachable: the loop either returns, raises, or sleeps.
        raise RuntimeError(  # pragma: no cover - defensive
            f"S3ArtifactFetcher.fetch exhausted retries without "
            f"raising for uri={uri!r}; last_exc={last_exc!r}",
        )


class MultiSchemeFetcher(ArtifactFetcher):
    """Dispatches a URI to the matching fetcher by scheme.

    The coord constructs one of these at boot time with whichever
    backends are configured (local always, s3 optionally based on
    ``MTG_BOT_COORD_ARTIFACT_BACKEND``).
    """

    def __init__(
        self,
        *,
        local: Optional[ArtifactFetcher] = None,
        s3: Optional[ArtifactFetcher] = None,
    ) -> None:
        self._local = local or LocalArtifactFetcher()
        self._s3 = s3

    def fetch(self, uri: str) -> bytes:
        parsed = urlparse(uri)
        scheme = parsed.scheme
        if scheme == "file":
            return self._local.fetch(uri)
        if scheme == "s3":
            if self._s3 is None:
                raise RuntimeError(
                    "received an s3:// URI but no S3 fetcher is "
                    "configured (set MTG_BOT_COORD_ARTIFACT_BACKEND "
                    "or pass s3= to MultiSchemeFetcher)"
                )
            return self._s3.fetch(uri)
        raise ValueError(
            f"unsupported artifact URI scheme: {scheme!r} "
            f"(supported: file://, s3://)"
        )
