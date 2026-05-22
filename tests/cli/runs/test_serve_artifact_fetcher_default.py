"""Pin the default artifact-fetcher wiring on ``serve.create_app``.

iter_020 (2026-05-21) produced 45 ``upload_failed`` rows in queue.db
despite the worker-uploaded ``.npz`` objects existing + being
readable in S3. Root cause: ``serve.create_app`` only constructed
the ``S3ArtifactFetcher`` arm when ``MTG_BOT_COORD_ARTIFACT_BACKEND``
was set to ``s3`` / ``auto``. The coord ran with that env var unset,
so the ``MultiSchemeFetcher`` returned ``s3=None``, and every
``s3://`` URI bounced with ``RuntimeError: received an s3:// URI but
no S3 fetcher is configured`` inside ``_fetch_and_record`` -- which
the executor's retry loop dutifully repeated 4x before recording
``outcome=upload_failed`` with no fetch ever having occurred.

These tests pin the post-fix behavior: default is opt-OUT (you have
to set ``MTG_BOT_COORD_ARTIFACT_BACKEND=local`` to explicitly disable
S3); any other value or unset constructs both arms. boto3 import
stays lazy inside ``S3ArtifactFetcher._get_client`` so constructing
the arm is free on hosts that never see an s3:// URI.
"""
from __future__ import annotations

from pathlib import Path

from mtg_bot.cli import serve as serve_mod
from mtg_bot.cli.runs.coordinator_artifact_fetcher import (
    LocalArtifactFetcher,
    MultiSchemeFetcher,
    S3ArtifactFetcher,
)


def _make_app(tmp_path: Path, **kwargs):
    return serve_mod.create_app(
        repo_url="https://example.test/mtg-bot.git",
        master_pubkey="ssh-ed25519 KEY",
        master_tailnet_name="myhost",
        port=5099,
        queue_db_path=tmp_path / "queue.db",
        weights_root=tmp_path / "trained_weights",
        iterate_data_dir=tmp_path / "iterate_data",
        replays_root=tmp_path / "replays",
        shards_config_path=tmp_path / "shards.json",
        enable_heartbeat_poller=False,
        report_executor=None,
        **kwargs,
    )


def test_default_fetcher_includes_s3_arm(tmp_path: Path, monkeypatch):
    """Default (env var unset) constructs both local + S3 arms.

    This is the iter_020 regression pin: an unset env var must NOT
    drop the S3 arm to None.
    """
    monkeypatch.delenv("MTG_BOT_COORD_ARTIFACT_BACKEND", raising=False)
    app = _make_app(tmp_path)
    fetcher = app.extensions["v2_artifact_fetcher"]
    assert isinstance(fetcher, MultiSchemeFetcher)
    assert isinstance(fetcher._local, LocalArtifactFetcher)
    assert isinstance(fetcher._s3, S3ArtifactFetcher), (
        "iter_020 regression: default coord fetcher dropped the S3 arm "
        "when MTG_BOT_COORD_ARTIFACT_BACKEND was unset, which silently "
        "failed every worker-side s3:// upload as upload_failed."
    )


def test_explicit_local_backend_drops_s3_arm(tmp_path: Path, monkeypatch):
    """``MTG_BOT_COORD_ARTIFACT_BACKEND=local`` is the opt-out path
    for hosts that genuinely never want S3 -- the legacy behavior
    before the 2026-05-22 default flip."""
    monkeypatch.setenv("MTG_BOT_COORD_ARTIFACT_BACKEND", "local")
    app = _make_app(tmp_path)
    fetcher = app.extensions["v2_artifact_fetcher"]
    assert isinstance(fetcher, MultiSchemeFetcher)
    assert fetcher._s3 is None


def test_explicit_s3_or_auto_backend_keeps_s3_arm(
    tmp_path: Path, monkeypatch,
):
    """``s3`` and ``auto`` both keep the S3 arm -- back-compat for
    operators who set the env var explicitly during the opt-in era."""
    for value in ("s3", "auto"):
        monkeypatch.setenv("MTG_BOT_COORD_ARTIFACT_BACKEND", value)
        app = _make_app(tmp_path)
        fetcher = app.extensions["v2_artifact_fetcher"]
        assert isinstance(fetcher._s3, S3ArtifactFetcher), (
            f"backend={value} should keep S3 arm"
        )


def test_injected_fetcher_is_used_as_is(tmp_path: Path, monkeypatch):
    """Explicit ``artifact_fetcher=`` injection bypasses the default
    wiring entirely (tests rely on this to stub the fetch path)."""
    monkeypatch.delenv("MTG_BOT_COORD_ARTIFACT_BACKEND", raising=False)
    stub = MultiSchemeFetcher(local=LocalArtifactFetcher(), s3=None)
    app = _make_app(tmp_path, artifact_fetcher=stub)
    assert app.extensions["v2_artifact_fetcher"] is stub
    # And the stub's S3 arm stays None -- the env-var path did not
    # mutate the injected fetcher.
    assert stub._s3 is None
