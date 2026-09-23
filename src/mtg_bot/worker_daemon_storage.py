"""Pluggable artifact uploader for worker daemons.

Workers POST per-game self-play results to the coordinator's
``/v2/report_result`` endpoint. Historically the ``.npz`` blob was
included in the POST as multipart form-data; that saturated the
coord's single-threaded WSGI handler under cluster scale (see
``project_mtg_bot_coord_wsgi`` memory). The new protocol is
"drop-off + small JSON ping": the worker uploads the blob to
shared storage (S3 or a local ``file://``-accessible path), then
POSTs the URI back to the coord. The coord rehydrates the bytes
into ``iterate_data/`` asynchronously off the request thread.

This module owns the worker side: the ``ArtifactUploader`` ABC,
the concrete ``LocalFileUploader``, the ``NullUploader`` for
tests, and an ``S3ArtifactUploader`` stub that Phase 2 will fill
in. The matching coord-side fetcher lives at
``mtg_bot.cli.runs.coordinator_artifact_fetcher``.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Literal, Optional
from urllib.parse import urlencode, urlparse


log = logging.getLogger(__name__)


ArtifactKind = Literal["npz", "replay"]

# Path of the coordinator's artifact drop-off endpoint. Shared with
# ``mtg_bot.cli.runs.v2_endpoints`` (which registers the route) so
# the two sides can never drift.
ARTIFACT_UPLOAD_PATH = "/v2/artifact/upload"


# Retry/backoff for S3 uploads on transient ClientError (throttling /
# 5xx). Three retries at 1s/3s/10s mirrors the worker daemon's
# ``RETRY_BACKOFF_S`` schedule so a flaky AWS endpoint behaves like a
# flaky coordinator endpoint from the worker's POV. Permission /
# bucket-not-found errors are fail-loud — they're operator bugs, not
# transient.
S3_RETRY_BACKOFF_S: tuple[float, ...] = (1.0, 3.0, 10.0)

# AWS error codes we consider transient. Anything else (e.g.
# ``AccessDenied``, ``NoSuchBucket``, ``InvalidAccessKeyId``) is an
# operator-config problem; retrying just delays the diagnostic.
_TRANSIENT_S3_ERROR_CODES: frozenset[str] = frozenset({
    "Throttling",
    "ThrottlingException",
    "RequestLimitExceeded",
    "RequestTimeout",
    "RequestTimeoutException",
    "SlowDown",
    "InternalError",
    "ServiceUnavailable",
    "InternalServerError",
})

# Retry/backoff for the HTTP uploader. Same 1s/3s/10s schedule as the
# S3 path so a flaky coordinator behaves like a flaky bucket from the
# worker's POV.
HTTP_RETRY_BACKOFF_S: tuple[float, ...] = (1.0, 3.0, 10.0)

# HTTP statuses we consider transient. 4xx (other than 429) means the
# request itself is wrong -- a bad key, an oversize body, the endpoint
# not enabled on the coord -- and retrying just delays the diagnostic.
_TRANSIENT_HTTP_STATUS: frozenset[int] = frozenset({
    408, 425, 429, 500, 502, 503, 504,
})

# Connect/read timeout for a single upload attempt. A 5 MB npz over
# Tailscale is sub-second; 120s is the "the coord is wedged" ceiling.
HTTP_UPLOAD_TIMEOUT_S: float = 120.0


def build_artifact_key(
    *,
    kind: ArtifactKind,
    stage_id: str,
    shard_label: str,
    claim_id: str,
) -> str:
    """Deterministic object key for an artifact upload.

    The key encodes the stage_id (so bucket lifecycle rules can
    clean by prefix), the shard_label (so artifacts from different
    workers don't collide), and the claim_id (so a retried upload
    overwrites its own object with byte-identical content -- the
    upload step is idempotent by construction).
    """
    safe_claim = claim_id.replace(":", "_").replace("/", "_")
    safe_shard = (shard_label or "unknown").replace("/", "_")
    ext = ".json.gz" if kind == "replay" else ".npz"
    return f"{stage_id}/{safe_shard}/{safe_claim}{ext}"


def _file_uri_to_path(uri: str) -> Path:
    """Parse a ``file://`` URI into a Path, handling Windows.

    Windows absolute paths look like ``file:///C:/foo/bar``; POSIX
    look like ``file:///abs/path``. ``urlparse(...).path`` returns
    ``/C:/foo/bar`` (Windows, leading slash + drive) or ``/abs/path``
    (POSIX). We strip the leading slash only when the next two
    chars look like ``X:`` (a drive letter).
    """
    parsed = urlparse(uri)
    path = parsed.path
    if len(path) >= 3 and path[0] == "/" and path[2] == ":":
        path = path[1:]
    return Path(path)


class ArtifactUploader(ABC):
    """Worker-side strategy for dropping result artifacts somewhere
    the coordinator can fetch them."""

    @abstractmethod
    def upload(
        self,
        payload: bytes,
        *,
        kind: ArtifactKind,
        stage_id: str,
        shard_label: str,
        claim_id: str,
    ) -> str:
        """Upload ``payload`` and return the URI the coord reads.

        Must be deterministic in (kind, stage_id, shard_label,
        claim_id) so retries are safe: same inputs produce the
        same URI and the same bytes overwrite the same object.
        """


class NullUploader(ArtifactUploader):
    """Drops artifacts on the floor; returns a ``null://`` URI.

    Used by tests that exercise the report path without caring
    about blob contents (e.g. unit tests for the claim-loop
    branching logic).
    """

    def upload(
        self, payload, *, kind, stage_id, shard_label, claim_id,
    ) -> str:
        key = build_artifact_key(
            kind=kind, stage_id=stage_id,
            shard_label=shard_label, claim_id=claim_id,
        )
        return f"null:///{key}"


class LocalFileUploader(ArtifactUploader):
    """Writes artifacts under a local directory; returns ``file://``.

    Used by:
    - tests that want to round-trip real bytes through the upload/
      fetch pair without standing up S3 (paired with
      ``LocalArtifactFetcher`` on the coord side);
    - production deployments where worker and coord share a
      filesystem (e.g. master + Mac on the same Tailnet with an
      SMB mount, or a single-host smoke).
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def upload(
        self, payload, *, kind, stage_id, shard_label, claim_id,
    ) -> str:
        key = build_artifact_key(
            kind=kind, stage_id=stage_id,
            shard_label=shard_label, claim_id=claim_id,
        )
        target = self.root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        # ``as_posix()`` normalizes Windows backslashes so the URI
        # is parseable across OS boundaries (coord on Windows, Mac
        # worker writing into an SMB-mounted path).
        return "file:///" + target.resolve().as_posix().lstrip("/")


class HttpArtifactUploader(ArtifactUploader):
    """POSTs artifacts to the coordinator's ``/v2/artifact/upload``.

    This is the scheme for workers that do NOT share a filesystem
    with the coordinator and don't have an S3 bucket -- e.g. the Mac
    over Tailscale. The worker POSTs the raw bytes; the coordinator
    writes them under its own ``--artifact-upload-dir`` and replies
    with a coordinator-LOCAL ``file://`` URI. The worker hands that
    URI straight back on ``/v2/report_result`` and the coord's
    existing ``LocalArtifactFetcher`` rehydrates it unchanged -- no
    new fetcher scheme needed on the coord side.

    Idempotency: the artifact key is ``build_artifact_key(...)``,
    identical to every other uploader, and the coordinator overwrites
    the same path on a repeat POST. A retried upload therefore lands
    the same bytes at the same path and returns the same URI.

    Retry policy: transient HTTP statuses (429/5xx) and connection
    errors retry on ``HTTP_RETRY_BACKOFF_S`` (1s / 3s / 10s). Any
    other 4xx -- 400 bad key, 413 too large, 404 endpoint not
    enabled -- fails LOUDLY on the first attempt; those are operator
    bugs, not weather.

    ``urlopen`` is injectable for tests (the real one is
    ``urllib.request.urlopen``); no third-party HTTP dep.
    """

    def __init__(
        self,
        base_url: str,
        *,
        urlopen: Optional[Any] = None,
        timeout: float = HTTP_UPLOAD_TIMEOUT_S,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._urlopen = urlopen or urllib.request.urlopen

    def _endpoint(
        self,
        *,
        kind: ArtifactKind,
        stage_id: str,
        shard_label: str,
        claim_id: str,
    ) -> str:
        query = urlencode({
            "kind": kind,
            "stage_id": stage_id,
            "shard_label": shard_label or "unknown",
            "claim_id": claim_id,
        })
        return f"{self.base_url}{ARTIFACT_UPLOAD_PATH}?{query}"

    def _attempt(self, url: str, payload: bytes) -> str:
        req = urllib.request.Request(
            url, data=payload, method="POST",
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Length": str(len(payload)),
            },
        )
        with self._urlopen(req, timeout=self.timeout) as resp:
            raw = resp.read()
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"artifact upload to {url!r} returned non-JSON body "
                f"({raw[:200]!r})",
            ) from exc
        uri = body.get("uri") if isinstance(body, dict) else None
        if not uri:
            raise ValueError(
                f"artifact upload to {url!r} returned no 'uri' field: "
                f"{body!r}",
            )
        return str(uri)

    def upload(
        self, payload, *, kind, stage_id, shard_label, claim_id,
    ) -> str:
        url = self._endpoint(
            kind=kind, stage_id=stage_id,
            shard_label=shard_label, claim_id=claim_id,
        )
        last_err: Optional[BaseException] = None
        for attempt, delay in enumerate((0.0,) + tuple(HTTP_RETRY_BACKOFF_S)):
            if delay > 0:
                time.sleep(delay)
            try:
                return self._attempt(url, payload)
            except urllib.error.HTTPError as e:
                if e.code not in _TRANSIENT_HTTP_STATUS:
                    # Operator-config / request-shape bug. Fail loud
                    # with the server's own diagnostic attached.
                    detail = ""
                    try:
                        detail = e.read().decode("utf-8", "replace")[:500]
                    except Exception:  # noqa: BLE001 - best effort
                        pass
                    raise RuntimeError(
                        f"artifact upload to {url!r} failed with "
                        f"HTTP {e.code}: {detail or e.reason}",
                    ) from e
                last_err = e
                log.warning(
                    "[http_uploader] transient HTTP %s POSTing %s "
                    "attempt %d: %s", e.code, url, attempt, e,
                )
            except (urllib.error.URLError, OSError) as e:
                last_err = e
                log.warning(
                    "[http_uploader] transient connection error POSTing "
                    "%s attempt %d: %s", url, attempt, e,
                )
        assert last_err is not None
        raise last_err


class S3ArtifactUploader(ArtifactUploader):
    """Uploads artifacts to an S3 bucket via boto3.

    Determinism + idempotency: the object key is
    ``build_artifact_key(...)`` prefixed with ``self.prefix`` (if non-
    empty). A retried upload writes byte-identical content to the same
    key — the second ``PutObject`` overwrites the first, the returned
    URI is unchanged. So upload retries are safe (the URI we hand back
    to the coord is the same one a peer worker would derive from the
    same claim_id).

    Retry policy: transient errors (throttling, S3 ``InternalError`` /
    ``ServiceUnavailable``, request timeouts) retry on the
    ``S3_RETRY_BACKOFF_S`` schedule (1s / 3s / 10s, 3 retries). Anything
    else — ``AccessDenied`` from a misconfigured IAM role, ``NoSuchBucket``
    from a wrong bucket name, an invalid signature — fails LOUDLY on the
    first attempt. Those are operator-config bugs; retrying just delays
    the diagnostic.
    """

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        *,
        client: Optional[Any] = None,
    ) -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        if client is not None:
            self._client = client
        else:  # pragma: no cover - real boto3 client init exercised only via integration
            import boto3  # noqa: PLC0415 — defer import so file:// users skip boto3
            self._client = boto3.client("s3")

    def _full_key(
        self,
        *,
        kind: ArtifactKind,
        stage_id: str,
        shard_label: str,
        claim_id: str,
    ) -> str:
        key = build_artifact_key(
            kind=kind, stage_id=stage_id,
            shard_label=shard_label, claim_id=claim_id,
        )
        if self.prefix:
            return f"{self.prefix}/{key}"
        return key

    def upload(
        self, payload, *, kind, stage_id, shard_label, claim_id,
    ) -> str:
        # Import inside the call so the module is importable on hosts
        # that don't install the ``[s3]`` extra (those hosts only need
        # ``file://`` / ``null://``, never instantiate this class, and
        # so never trigger the boto3 import).
        from botocore.exceptions import ClientError  # noqa: PLC0415

        full_key = self._full_key(
            kind=kind, stage_id=stage_id,
            shard_label=shard_label, claim_id=claim_id,
        )
        last_err: Optional[Exception] = None
        for attempt, delay in enumerate((0.0,) + tuple(S3_RETRY_BACKOFF_S)):
            if delay > 0:
                time.sleep(delay)
            try:
                self._client.put_object(
                    Bucket=self.bucket, Key=full_key, Body=payload,
                )
                return f"s3://{self.bucket}/{full_key}"
            except ClientError as e:
                code = (
                    e.response.get("Error", {}).get("Code", "")
                    if hasattr(e, "response") and isinstance(e.response, dict)
                    else ""
                )
                if code not in _TRANSIENT_S3_ERROR_CODES:
                    # Permission / bucket-not-found / etc — fail loud,
                    # no retries. Re-raise with the original exception
                    # so the operator sees the AWS-side diagnostic.
                    raise
                last_err = e
                log.warning(
                    "[s3_uploader] transient %s on PutObject "
                    "s3://%s/%s attempt %d: %s",
                    code, self.bucket, full_key, attempt, e,
                )
        # Exhausted the retry budget on transient errors. Re-raise
        # the last one so the claim-loop's error handling sees it.
        assert last_err is not None
        raise last_err


def uploader_from_uri(uri: str) -> ArtifactUploader:
    """Factory: parse a storage-root URI and return the matching
    uploader.

    Supported schemes:
    - ``file:///abs/dir`` -> ``LocalFileUploader`` rooted at that
      directory (created on first ``upload`` call if missing).
    - ``s3://bucket/prefix`` -> ``S3ArtifactUploader`` (Phase 2).
    - ``http://host:port`` / ``https://...`` ->
      ``HttpArtifactUploader`` POSTing to the coordinator's
      ``/v2/artifact/upload``. Use this for workers that share
      neither a filesystem nor a bucket with the coordinator.
    - ``null://`` -> ``NullUploader`` (test/dev only).

    Raises ``ValueError`` for unrecognized schemes.
    """
    parsed = urlparse(uri)
    scheme = parsed.scheme
    if scheme == "file":
        return LocalFileUploader(_file_uri_to_path(uri))
    if scheme == "s3":
        prefix = parsed.path.lstrip("/")
        return S3ArtifactUploader(bucket=parsed.netloc, prefix=prefix)
    if scheme in ("http", "https"):
        return HttpArtifactUploader(uri)
    if scheme == "null":
        return NullUploader()
    raise ValueError(
        f"unsupported artifact storage URI scheme: {scheme!r} "
        f"(supported: file://, s3://, http://, https://, null://)"
    )
