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
that dispatches by URI scheme, and an ``S3ArtifactFetcher`` stub
that Phase 2 will fill in. The matching worker-side uploader
lives at ``mtg_bot.worker_daemon_storage``.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse


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


class S3ArtifactFetcher(ArtifactFetcher):  # pragma: no cover - Phase 2
    """Reads ``s3://`` URIs via boto3 ``GetObject``.

    Phase 1 stub: raises ``NotImplementedError``. Phase 2 wires
    the boto3 client + retry/backoff + size verification. Class
    shape locked in here so the dispatcher and serve.py wiring
    can refer to a stable import while Phase 2 lands.
    """

    def __init__(self, region: str = "us-east-1") -> None:
        self.region = region

    def fetch(self, uri: str) -> bytes:
        raise NotImplementedError(
            "S3ArtifactFetcher is a Phase-1 stub; Phase 2 wires "
            "the boto3 GetObject path."
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
            return self._s3.fetch(uri)  # pragma: no cover - Phase 2
        raise ValueError(
            f"unsupported artifact URI scheme: {scheme!r} "
            f"(supported: file://, s3://)"
        )
