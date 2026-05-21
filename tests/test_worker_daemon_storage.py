"""Tests for ``mtg_bot.worker_daemon_storage``.

Phase 1 surface: the ``ArtifactUploader`` ABC, the
``LocalFileUploader`` and ``NullUploader`` concrete impls, the
``uploader_from_uri`` factory, and the deterministic
``build_artifact_key`` helper. The ``S3ArtifactUploader`` stub is
intentionally uncovered (``# pragma: no cover``) -- Phase 2 will
add ``moto``-backed tests for it.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import pytest

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


# ---- S3 stub is not yet implemented -------------------------------------


def test_s3_uploader_phase1_stub_raises_not_implemented():
    # Document the contract: instantiating is fine (so factory
    # wiring works), but calling upload raises until Phase 2.
    up = S3ArtifactUploader(bucket="mtg-bot-artifacts-630589799985")
    with pytest.raises(NotImplementedError, match="Phase 2"):
        up.upload(
            b"x", kind="npz",
            stage_id="s", shard_label="w", claim_id="c",
        )


# ---- ABC contract -------------------------------------------------------


def test_abc_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        ArtifactUploader()  # type: ignore[abstract]
