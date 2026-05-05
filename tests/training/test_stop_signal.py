"""Tests for the sentinel-file stop-run helper.

Producer-side stop propagation rests on five primitives in
``mtg_bot.training.stop_signal``:

* ``sentinel_path`` — pure path computation
* ``stop_requested`` — does the sentinel exist (own or cycle)
* ``write_stop`` — drops a sentinel; idempotent
* ``cleanup_orphans`` — sweep stale sentinels
* ``read_stop_payload`` — best-effort body parse for log lines

These tests cover happy paths and the awkward corners (missing dir,
unparseable body, idempotent re-write, cycle override).
"""

from __future__ import annotations

import json
from pathlib import Path

from mtg_bot.training.stop_signal import (
    cleanup_orphans, read_stop_payload, sentinel_path,
    stop_requested, write_stop,
)


def test_sentinel_path_is_dotprefixed(tmp_path: Path):
    p = sentinel_path(tmp_path, "iter_001_self_play_v6")
    assert p.parent == tmp_path
    assert p.name == ".STOP_iter_001_self_play_v6"


def test_stop_requested_false_for_missing_dir(tmp_path: Path):
    # No progress dir at all — the helper must NOT error or report a
    # stop. The producer might be polling before any progress files
    # exist.
    assert not stop_requested(tmp_path / "doesnt_exist", "anything")


def test_stop_requested_false_when_no_sentinel(tmp_path: Path):
    assert not stop_requested(tmp_path, "iter_001")


def test_write_stop_creates_sentinel(tmp_path: Path):
    path = write_stop(tmp_path, "iter_001", reason="test")
    assert path.is_file()
    assert path.name == ".STOP_iter_001"
    assert stop_requested(tmp_path, "iter_001")
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["run_id"] == "iter_001"
    assert body["reason"] == "test"
    assert body["requested_at"]


def test_write_stop_creates_progress_dir(tmp_path: Path):
    """The progress dir might not exist when the user clicks stop —
    the trainer creates it lazily on first write. write_stop should
    create it so the sentinel lands cleanly."""
    target = tmp_path / "training_progress"
    assert not target.exists()
    write_stop(target, "iter_001")
    assert target.is_dir()
    assert sentinel_path(target, "iter_001").is_file()


def test_write_stop_is_idempotent(tmp_path: Path):
    """Calling stop twice doesn't error and refreshes the body."""
    p1 = write_stop(tmp_path, "iter_001", reason="first")
    body1 = json.loads(p1.read_text(encoding="utf-8"))
    p2 = write_stop(tmp_path, "iter_001", reason="second")
    assert p1 == p2
    body2 = json.loads(p2.read_text(encoding="utf-8"))
    assert body2["reason"] == "second"
    # Timestamps may match at second granularity, but the call cannot
    # have raised. That's the load-bearing invariant for the UI.
    assert body2["run_id"] == body1["run_id"] == "iter_001"


def test_stop_requested_honors_cycle_id(tmp_path: Path):
    """A cycle-level sentinel must satisfy a child run's stop check —
    that's how the iter loop's stop fires for the in-flight self-play
    stage even when the user clicked stop on the cycle card."""
    write_stop(tmp_path, "iter_001_cycle")
    # Direct check on the child returns False — no own sentinel.
    assert not stop_requested(tmp_path, "iter_001_self_play_v6")
    # But with the cycle_id passed through, the child sees the stop.
    assert stop_requested(
        tmp_path, "iter_001_self_play_v6",
        cycle_id="iter_001_cycle",
    )


def test_stop_requested_skips_redundant_cycle_lookup(tmp_path: Path):
    """When cycle_id == run_id we shouldn't double-check the same
    file. (Functionally a no-op, but worth pinning so a future
    refactor doesn't accidentally tail-recurse.)"""
    write_stop(tmp_path, "single_run")
    assert stop_requested(
        tmp_path, "single_run", cycle_id="single_run",
    )


def test_cleanup_orphans_removes_unknown_sentinels(tmp_path: Path):
    # Drop three sentinels; declare only one as active.
    write_stop(tmp_path, "iter_001_cycle")
    write_stop(tmp_path, "iter_001_self_play_v6")
    write_stop(tmp_path, "old_dead_run")
    removed = cleanup_orphans(tmp_path, ["iter_001_cycle"])
    removed_names = sorted(p.name for p in removed)
    assert removed_names == [
        ".STOP_iter_001_self_play_v6", ".STOP_old_dead_run",
    ]
    assert sentinel_path(tmp_path, "iter_001_cycle").is_file()
    assert not sentinel_path(
        tmp_path, "iter_001_self_play_v6",
    ).is_file()
    assert not sentinel_path(tmp_path, "old_dead_run").is_file()


def test_cleanup_orphans_no_dir_is_noop(tmp_path: Path):
    assert cleanup_orphans(tmp_path / "nope", ["foo"]) == []


def test_cleanup_orphans_keeps_progress_jsons(tmp_path: Path):
    """The cleanup helper should ONLY touch .STOP_* sentinels — a
    bug here could nuke the per-run progress JSONs."""
    (tmp_path / "iter_001_cycle.json").write_text("{}")
    write_stop(tmp_path, "iter_001_cycle")
    write_stop(tmp_path, "old_dead_run")
    cleanup_orphans(tmp_path, ["iter_001_cycle"])
    assert (tmp_path / "iter_001_cycle.json").is_file()


def test_read_stop_payload_returns_body(tmp_path: Path):
    write_stop(tmp_path, "run_x", reason="ui-button")
    body = read_stop_payload(tmp_path, "run_x")
    assert body is not None
    assert body["reason"] == "ui-button"


def test_read_stop_payload_returns_none_when_missing(tmp_path: Path):
    assert read_stop_payload(tmp_path, "nope") is None


def test_read_stop_payload_returns_none_on_garbage(tmp_path: Path):
    """If somehow the sentinel body is unparseable, the helper
    returns None so callers don't blow up. Doesn't change the
    "stop requested" answer — consumers check existence
    separately."""
    path = sentinel_path(tmp_path, "broken")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json", encoding="utf-8")
    assert read_stop_payload(tmp_path, "broken") is None
    # But existence still counts as "stop requested".
    assert stop_requested(tmp_path, "broken")
