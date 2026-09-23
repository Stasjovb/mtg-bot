"""``mtg_bot serve`` exposes the per-lineage artifact directories.

The coordinator serves ``/v2/weights/<version>`` from ``weights_root``
and rehydrates reported ``.npz`` files into ``iterate_data_dir``.
Both used to be hard-wired to ``<repo-root>/trained_weights`` and
``<repo-root>/iterate_data``, which is wrong for a second lineage:
version labels (``v1``, ``v2``, ...) repeat across lineages, so a
coordinator left on the defaults would hand ``trained_weights/v1`` to
workers that were asked to play ``trained_weights_s2/v1``. These
tests pin that the CLI flags reach ``create_app`` and that omitting
them keeps the historical defaults (``None`` -> resolved inside
``create_app``).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mtg_bot.cli import serve as serve_mod


@pytest.fixture
def captured_create_app(monkeypatch, tmp_path):
    """Stub everything ``main()`` touches after argparse and record
    the kwargs it hands to ``create_app``."""
    seen: dict = {}

    def fake_create_app(**kwargs):
        seen.update(kwargs)
        return object()

    monkeypatch.setattr(serve_mod, "create_app", fake_create_app)
    monkeypatch.setattr(serve_mod, "_detect_repo_url", lambda _r: "x")
    monkeypatch.setattr(serve_mod, "_read_pubkey", lambda _p: "pk")
    monkeypatch.setattr(
        serve_mod, "_detect_master_tailnet_name", lambda: "master",
    )
    import waitress

    monkeypatch.setattr(waitress, "serve", lambda *_a, **_k: None)
    return seen


def test_lineage_dir_flags_reach_create_app(captured_create_app, tmp_path):
    weights = tmp_path / "trained_weights_s2"
    data = tmp_path / "iterate_data_s2"
    replays = tmp_path / "replays_s2"
    serve_mod.main([
        "--repo-root", str(tmp_path),
        "--weights-root", str(weights),
        "--iterate-data-dir", str(data),
        "--replays-root", str(replays),
        "--no-heartbeat-poller",
    ])
    assert captured_create_app["weights_root"] == weights
    assert captured_create_app["iterate_data_dir"] == data
    assert captured_create_app["replays_root"] == replays


def test_lineage_dir_flags_default_to_none(captured_create_app, tmp_path):
    serve_mod.main(["--repo-root", str(tmp_path), "--no-heartbeat-poller"])
    assert captured_create_app["weights_root"] is None
    assert captured_create_app["iterate_data_dir"] is None
    assert captured_create_app["replays_root"] is None
    assert isinstance(captured_create_app["repo_root"], Path)
