"""Tests for the per-cycle ephemeral paths + shards_config renderer.

The launcher writes ALL per-cycle scratch files under
``training_progress/launches/<cycle_id>/`` -- this module ensures
two concurrent cycles never share a path, the renderer produces the
same JSON shape iterate's heartbeat-poller parses, and obviously-
wrong inputs (empty URL list, legacy dict-list, missing parent dir)
fail loudly rather than silently producing a no-worker config.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mtg_bot.cli.runs.heartbeat_poller import load_shards_config
from mtg_bot.launcher.state import (
    AWS_INSTANCES_FILENAME,
    LaunchPaths,
    SHARDS_CONFIG_FILENAME,
    render_shards_config,
    write_aws_instances_json,
)


# ---------------------------------------------------------------------------
# LaunchPaths
# ---------------------------------------------------------------------------


def test_for_cycle_no_io_at_construction(tmp_path: Path):
    """Constructing LaunchPaths must not touch the filesystem."""
    progress_root = tmp_path / "tp"
    paths = LaunchPaths.for_cycle(progress_root, "iter_007_cycle")
    assert paths.cycle_id == "iter_007_cycle"
    assert paths.progress_root == progress_root
    # No directories created yet.
    assert not paths.cycle_dir.exists()
    assert not progress_root.exists()


def test_cycle_dir_layout(tmp_path: Path):
    paths = LaunchPaths.for_cycle(tmp_path / "tp", "iter_021_cycle")
    assert paths.cycle_dir == tmp_path / "tp" / "launches" / "iter_021_cycle"
    assert paths.shards_config_path == (
        paths.cycle_dir / SHARDS_CONFIG_FILENAME
    )
    assert paths.aws_instances_path == (
        paths.cycle_dir / AWS_INSTANCES_FILENAME
    )
    assert SHARDS_CONFIG_FILENAME == "shards_config.json"
    assert AWS_INSTANCES_FILENAME == "aws_instances.json"


def test_ensure_creates_dir_and_parents(tmp_path: Path):
    """``ensure()`` materialises the per-cycle dir (idempotent)."""
    paths = LaunchPaths.for_cycle(
        tmp_path / "nested" / "tp", "iter_001_cycle",
    )
    returned = paths.ensure()
    assert returned is paths  # chainable
    assert paths.cycle_dir.is_dir()
    # Idempotent: second call is a no-op.
    paths.ensure()
    assert paths.cycle_dir.is_dir()


def test_two_cycles_get_distinct_dirs(tmp_path: Path):
    """Two concurrent launches must not share a path -- otherwise
    cycle B would clobber cycle A's shards_config mid-flight."""
    a = LaunchPaths.for_cycle(tmp_path, "iter_001_cycle")
    b = LaunchPaths.for_cycle(tmp_path, "iter_002_cycle")
    assert a.cycle_dir != b.cycle_dir
    assert a.shards_config_path != b.shards_config_path


# ---------------------------------------------------------------------------
# render_shards_config
# ---------------------------------------------------------------------------


def test_render_shards_config_writes_v2_shape(tmp_path: Path):
    out = render_shards_config(
        [
            "http://desktop-j05412i:5198",
            "http://greggs-macbook-pro:5198",
        ],
        tmp_path / "launches" / "iter_007_cycle" / "shards_config.json",
    )
    assert out.is_file()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data == {
        "worker_urls": [
            "http://desktop-j05412i:5198",
            "http://greggs-macbook-pro:5198",
        ],
    }


def test_rendered_file_round_trips_through_heartbeat_poller(tmp_path: Path):
    """The renderer's output is the same shape the heartbeat-poller
    parses -- guard against schema drift between writer + reader."""
    out = render_shards_config(
        ["http://win10-host:5198", "http://mac-host:5198"],
        tmp_path / "shards_config.json",
    )
    entries = load_shards_config(out)
    assert entries == [
        {"worker_url": "http://win10-host:5198"},
        {"worker_url": "http://mac-host:5198"},
    ]


def test_render_creates_parent_dir(tmp_path: Path):
    """Renderer creates missing parent dirs (the per-cycle dir may
    not exist yet on first call)."""
    target = tmp_path / "a" / "b" / "c" / "shards_config.json"
    assert not target.parent.exists()
    render_shards_config(["http://h:5198"], target)
    assert target.is_file()


def test_render_strips_whitespace_in_urls(tmp_path: Path):
    out = render_shards_config(
        ["  http://h1:5198  ", "http://h2:5198"],
        tmp_path / "shards_config.json",
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["worker_urls"] == ["http://h1:5198", "http://h2:5198"]


def test_render_rejects_empty_list(tmp_path: Path):
    with pytest.raises(ValueError, match="worker_urls is empty"):
        render_shards_config([], tmp_path / "shards_config.json")


def test_render_rejects_empty_url_string(tmp_path: Path):
    with pytest.raises(ValueError, match="empty URL string"):
        render_shards_config(
            ["http://h:5198", "   "],
            tmp_path / "shards_config.json",
        )


def test_render_rejects_legacy_dict_shape(tmp_path: Path):
    """A list of dicts is the pre-v2 legacy shape. Reject so a stale
    caller doesn't write a file the heartbeat-poller would
    ``LegacyShardsConfigError`` on."""
    with pytest.raises(ValueError, match="non-string entry"):
        render_shards_config(
            [{"worker_url": "http://h:5198"}],
            tmp_path / "shards_config.json",
        )


# ---------------------------------------------------------------------------
# write_aws_instances_json (stub for Phase B)
# ---------------------------------------------------------------------------


def test_aws_instances_stub_writes_empty(tmp_path: Path):
    out = write_aws_instances_json(tmp_path / "aws_instances.json")
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data == {"instances": [], "phase": "A-stub"}


def test_aws_instances_filled(tmp_path: Path):
    """Phase B will pass the real instance list; the stub already
    accepts it so the wire format is stable."""
    out = write_aws_instances_json(
        tmp_path / "aws_instances.json",
        [
            {"instance_id": "i-abc", "public_ip": "1.2.3.4",
             "tailnet_ip": "100.1.2.3", "az": "us-east-1a"},
        ],
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["phase"] == "filled"
    assert len(data["instances"]) == 1
    assert data["instances"][0]["instance_id"] == "i-abc"


def test_aws_instances_creates_parent_dir(tmp_path: Path):
    target = tmp_path / "a" / "b" / "aws_instances.json"
    assert not target.parent.exists()
    write_aws_instances_json(target)
    assert target.is_file()
