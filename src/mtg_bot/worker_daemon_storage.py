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

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import urlparse


ArtifactKind = Literal["npz", "replay"]


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


class S3ArtifactUploader(ArtifactUploader):  # pragma: no cover - Phase 2
    """Uploads artifacts to an S3 bucket via boto3.

    Phase 1 stub: raises ``NotImplementedError``. Phase 2 will
    implement the boto3 client + multipart upload + retry/backoff
    + size verification header. The class shape is locked in here
    so the worker-side factory + the coord-side fetcher can refer
    to a stable import path while Phase 2 lands.
    """

    def __init__(self, bucket: str, prefix: str = "") -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")

    def upload(
        self, payload, *, kind, stage_id, shard_label, claim_id,
    ) -> str:
        raise NotImplementedError(
            "S3ArtifactUploader is a Phase-1 stub; Phase 2 wires "
            "the boto3 PutObject path. Use LocalFileUploader for "
            "now."
        )


def uploader_from_uri(uri: str) -> ArtifactUploader:
    """Factory: parse a storage-root URI and return the matching
    uploader.

    Supported schemes:
    - ``file:///abs/dir`` -> ``LocalFileUploader`` rooted at that
      directory (created on first ``upload`` call if missing).
    - ``s3://bucket/prefix`` -> ``S3ArtifactUploader`` (Phase 2).
    - ``null://`` -> ``NullUploader`` (test/dev only).

    Raises ``ValueError`` for unrecognized schemes.
    """
    parsed = urlparse(uri)
    scheme = parsed.scheme
    if scheme == "file":
        return LocalFileUploader(_file_uri_to_path(uri))
    if scheme == "s3":  # pragma: no cover - Phase 2
        prefix = parsed.path.lstrip("/")
        return S3ArtifactUploader(bucket=parsed.netloc, prefix=prefix)
    if scheme == "null":
        return NullUploader()
    raise ValueError(
        f"unsupported artifact storage URI scheme: {scheme!r} "
        f"(supported: file://, s3://, null://)"
    )
