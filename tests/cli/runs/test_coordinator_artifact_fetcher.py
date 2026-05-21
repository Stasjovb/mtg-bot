"""Tests for ``mtg_bot.cli.runs.coordinator_artifact_fetcher``.

Phase 1 surface: ``ArtifactFetcher`` ABC, ``LocalArtifactFetcher``,
``MultiSchemeFetcher`` (dispatcher). ``S3ArtifactFetcher`` is a
Phase-1 stub (uncovered behind ``# pragma: no cover``); Phase 2
will land moto-backed tests for it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

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


# ---- S3 stub is not yet implemented -------------------------------------


def test_s3_fetcher_phase1_stub_raises_not_implemented():
    f = S3ArtifactFetcher(region="us-east-1")
    with pytest.raises(NotImplementedError, match="Phase 2"):
        f.fetch("s3://bucket/key.npz")


# ---- ABC contract -------------------------------------------------------


def test_abc_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        ArtifactFetcher()  # type: ignore[abstract]
