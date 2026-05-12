"""Tests for ``scripts/eval_early_stop_watcher.py``.

Covers the three read transports (jsons / db / rest), the source
auto-resolver, the ``--once`` end-to-end loop with the STOP sentinel
written for PASS / FAIL, and the lookback filter that drops stale
``running`` rows.

The Wilson CI math itself (``_wilson_ci``, ``_decision``) is
indirectly covered by the end-to-end tests — feeding wins/losses that
make the CI straddle / clear / fall below the threshold and asserting
on sentinel presence.
"""

from __future__ import annotations

import importlib
import io
import json
import os
import sqlite3
import sys
import urllib.error
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import pytest

from mtg_bot.cli.runs import db as runs_db
from mtg_bot.cli.runs.models import ProgressUpdate, Run
from mtg_bot.training.gate import EVAL_GATE_THRESHOLD
from mtg_bot.training.stop_signal import sentinel_path


# ----- module loader --------------------------------------------------------
#
# The watcher lives under ``scripts/`` (intentionally — it's an ops
# helper, not a library) and isn't on the import path by default.
# Reload from disk per test so each test sees a clean module state.


@pytest.fixture
def watcher():
    scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    if "eval_early_stop_watcher" in sys.modules:
        del sys.modules["eval_early_stop_watcher"]
    mod = importlib.import_module("eval_early_stop_watcher")
    yield mod
    if "eval_early_stop_watcher" in sys.modules:
        del sys.modules["eval_early_stop_watcher"]


# ----- helpers --------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(ts: datetime) -> str:
    return ts.isoformat(timespec="seconds")


def _write_eval_json(
    progress_dir: Path, run_id: str, *,
    wins_new: int, wins_old: int, draws: int = 0,
    status: str = "running",
    cycle_id: Optional[str] = None,
    started_at: Optional[datetime] = None,
) -> Path:
    """Write an eval progress JSON that matches the producer's shape
    closely enough for the watcher to read it."""
    progress_dir.mkdir(parents=True, exist_ok=True)
    body = {
        "run_id": run_id,
        "status": status,
        "wins_new": wins_new,
        "wins_old": wins_old,
        "draws": draws,
        "cycle_id": cycle_id,
        "started_at": _iso(started_at or _now()),
    }
    # Match the watcher's filename filter: must contain ``_eval_``,
    # must not contain ``_shard_``.
    path = progress_dir / f"{run_id}.json"
    if "_eval_" not in path.name:
        path = progress_dir / f"{run_id}_eval_x.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


@contextmanager
def _seeded_db(
    db_path: Path,
    *,
    runs: Iterable[dict[str, Any]],
):
    """Open a freshly-seeded runs.db, insert the given run + progress
    pairs, yield. Each entry in ``runs`` is a dict with
    ``run_id``, ``status``, ``started_at`` (datetime), ``wins_new``,
    ``wins_old``, plus optional ``parent_run_id`` / ``extra_json`` /
    ``draws`` / ``kind``."""
    conn = runs_db.connect(db_path)
    try:
        for entry in runs:
            run = Run(
                run_id=entry["run_id"],
                kind=entry.get("kind", "eval"),
                status=entry["status"],
                started_at=_iso(entry["started_at"]),
                git_commit="deadbeef",
                config_json="{}",
                parent_run_id=entry.get("parent_run_id"),
            )
            runs_db.insert_run(conn, run)
            update = ProgressUpdate(
                run_id=entry["run_id"],
                shard_label=None,
                wins_new=entry["wins_new"],
                wins_old=entry["wins_old"],
                draws=entry.get("draws", 0),
                extra_json=entry.get("extra_json"),
            )
            runs_db.upsert_progress(conn, update)
            for label, w_new, w_old in entry.get("shards", []):
                # Per-shard rows must be ignored by the watcher
                # (they don't carry the totals we want).
                shard_update = ProgressUpdate(
                    run_id=entry["run_id"],
                    shard_label=label,
                    wins_new=w_new,
                    wins_old=w_old,
                )
                runs_db.upsert_progress(conn, shard_update)
    finally:
        conn.close()
    yield


def _run_once(watcher, **kwargs) -> str:
    """Run ``watcher.main`` with ``--once`` and return captured stdout.

    Accepted kwargs: ``progress_dir`` (Path), ``source``, ``db_path``,
    ``api_url``, ``min_decisive``, ``threshold``.
    """
    progress_dir = kwargs.pop("progress_dir")
    argv = ["--once", "--progress-dir", str(progress_dir)]
    if "source" in kwargs:
        argv += ["--source", kwargs.pop("source")]
    if "db_path" in kwargs:
        argv += ["--db-path", str(kwargs.pop("db_path"))]
    if "api_url" in kwargs:
        argv += ["--api-url", kwargs.pop("api_url")]
    if "min_decisive" in kwargs:
        argv += ["--min-decisive", str(kwargs.pop("min_decisive"))]
    if "threshold" in kwargs:
        argv += ["--threshold", str(kwargs.pop("threshold"))]
    assert not kwargs, f"unexpected kwargs: {kwargs}"
    buf = io.StringIO()
    with redirect_stdout(buf):
        watcher.main(argv)
    return buf.getvalue()


# ----- _resolve_source ------------------------------------------------------


def test_resolve_source_auto_prefers_rest_over_db(watcher, monkeypatch):
    monkeypatch.setenv("MTG_BOT_RUN_DB_URL", "http://x:5099")
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", "/some/runs.db")
    assert watcher._resolve_source("auto") == "rest"


def test_resolve_source_auto_uses_db_when_only_path_set(watcher, monkeypatch):
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", "/some/runs.db")
    assert watcher._resolve_source("auto") == "db"


def test_resolve_source_auto_falls_back_to_jsons(watcher, monkeypatch):
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    assert watcher._resolve_source("auto") == "jsons"


def test_resolve_source_passthrough(watcher):
    """An explicit --source value short-circuits env detection."""
    for mode in ("jsons", "db", "rest"):
        assert watcher._resolve_source(mode) == mode


# ----- _load_statuses dispatch ----------------------------------------------


def test_load_statuses_db_requires_path(watcher):
    with pytest.raises(ValueError, match="--source db requires"):
        watcher._load_statuses(
            "db", progress_dir=Path("."), db_path=None, api_url=None,
        )


def test_load_statuses_rest_requires_url(watcher):
    with pytest.raises(ValueError, match="--source rest requires"):
        watcher._load_statuses(
            "rest", progress_dir=Path("."), db_path=None, api_url="",
        )


def test_load_statuses_unknown_mode(watcher):
    with pytest.raises(ValueError, match="unknown source"):
        watcher._load_statuses(
            "xyzzy", progress_dir=Path("."), db_path=None, api_url=None,
        )


# ----- JSON transport -------------------------------------------------------


def test_jsons_mode_writes_stop_on_pass(watcher, tmp_path):
    """20-1 (n=21) doesn't have enough decisive games at default
    min_decisive=30; but 100-0 with min_decisive=30 clears the
    Wilson lower-bound past 0.51 easily."""
    progress_dir = tmp_path / "progress"
    _write_eval_json(
        progress_dir, "iter_001_eval_new_vs_old",
        wins_new=100, wins_old=0, cycle_id=None,
    )
    out = _run_once(
        watcher, progress_dir=progress_dir, source="jsons",
    )
    # Filename-pattern fallback recovers cycle_id from the run_id.
    assert sentinel_path(progress_dir, "iter_001_cycle").exists()
    # Per-run sentinel is NOT written when a cycle is resolvable.
    assert not sentinel_path(
        progress_dir, "iter_001_eval_new_vs_old",
    ).exists()
    assert "PASS" in out


def test_jsons_mode_writes_stop_on_fail(watcher, tmp_path):
    progress_dir = tmp_path / "progress"
    _write_eval_json(
        progress_dir, "iter_002_eval_new_vs_old",
        wins_new=0, wins_old=100,
    )
    out = _run_once(
        watcher, progress_dir=progress_dir, source="jsons",
    )
    assert sentinel_path(progress_dir, "iter_002_cycle").exists()
    assert "FAIL" in out


def test_jsons_mode_no_stop_when_ci_straddles(watcher, tmp_path):
    """50-50 → CI symmetrical around 50%, straddles 51%."""
    progress_dir = tmp_path / "progress"
    _write_eval_json(
        progress_dir, "iter_003_eval_new_vs_old",
        wins_new=50, wins_old=50,
    )
    out = _run_once(
        watcher, progress_dir=progress_dir, source="jsons",
    )
    assert not sentinel_path(progress_dir, "iter_003_cycle").exists()
    assert "straddles" in out


def test_jsons_mode_skips_below_min_decisive(watcher, tmp_path):
    """3-0 is decisive in spirit but n=3 < min_decisive=30."""
    progress_dir = tmp_path / "progress"
    _write_eval_json(
        progress_dir, "iter_004_eval_a_vs_b", wins_new=3, wins_old=0,
    )
    out = _run_once(
        watcher, progress_dir=progress_dir, source="jsons",
    )
    assert not sentinel_path(progress_dir, "iter_004_cycle").exists()
    # No "straddles" message either — n < min_decisive returns None.
    assert "straddles" not in out


def test_jsons_mode_skips_non_running_status(watcher, tmp_path):
    progress_dir = tmp_path / "progress"
    _write_eval_json(
        progress_dir, "iter_005_eval_a_vs_b",
        wins_new=100, wins_old=0, status="completed",
    )
    _run_once(watcher, progress_dir=progress_dir, source="jsons")
    assert not sentinel_path(progress_dir, "iter_005_cycle").exists()


def test_jsons_mode_handles_malformed_json(watcher, tmp_path):
    """A half-written JSON shouldn't crash the watcher."""
    progress_dir = tmp_path / "progress"
    progress_dir.mkdir()
    (progress_dir / "iter_006_eval_garbage.json").write_text(
        "{not json",
    )
    _write_eval_json(
        progress_dir, "iter_006_eval_a_vs_b",
        wins_new=100, wins_old=0,
    )
    _run_once(watcher, progress_dir=progress_dir, source="jsons")
    # Good one still triggers.
    assert sentinel_path(progress_dir, "iter_006_cycle").exists()


def test_jsons_mode_skips_missing_run_id(watcher, tmp_path):
    progress_dir = tmp_path / "progress"
    progress_dir.mkdir()
    (progress_dir / "iter_007_eval_oops.json").write_text(
        json.dumps({"status": "running", "wins_new": 1, "wins_old": 0}),
    )
    _run_once(watcher, progress_dir=progress_dir, source="jsons")
    # No run_id => silently skipped, no sentinel anywhere.
    assert list(progress_dir.glob(".STOP_*")) == []


def test_jsons_mode_skips_shard_files(watcher, tmp_path):
    """Per-shard progress files (``*_shard_*``) must be ignored —
    they don't carry the aggregate totals."""
    progress_dir = tmp_path / "progress"
    progress_dir.mkdir()
    # Shard file with deceptively decisive numbers.
    shard = {
        "run_id": "iter_008_eval_a_vs_b_shard_1",
        "status": "running",
        "wins_new": 100, "wins_old": 0,
    }
    (progress_dir / "iter_008_eval_a_vs_b_shard_1.json").write_text(
        json.dumps(shard),
    )
    _run_once(watcher, progress_dir=progress_dir, source="jsons")
    assert list(progress_dir.glob(".STOP_*")) == []


def test_jsons_mode_no_progress_dir(watcher, tmp_path):
    """A missing progress dir is a no-op, not a crash."""
    missing = tmp_path / "nope"
    _run_once(watcher, progress_dir=missing, source="jsons")
    # Sentinel dir is created by write_stop only if write_stop is
    # called — which it isn't, since no files were found.
    assert not missing.exists() or not list(missing.glob(".STOP_*"))


# ----- DB transport ---------------------------------------------------------


def test_db_mode_writes_stop_on_pass(watcher, tmp_path):
    db_path = tmp_path / "runs.db"
    with _seeded_db(
        db_path,
        runs=[
            {
                "run_id": "iter_010_eval_new_vs_old",
                "status": "running",
                "started_at": _now() - timedelta(minutes=5),
                "wins_new": 80, "wins_old": 0,
                "parent_run_id": None,
            },
        ],
    ):
        progress_dir = tmp_path / "progress"
        out = _run_once(
            watcher, progress_dir=progress_dir,
            source="db", db_path=db_path,
        )
    assert sentinel_path(progress_dir, "iter_010_cycle").exists()
    assert "PASS" in out


def test_db_mode_writes_stop_on_fail(watcher, tmp_path):
    db_path = tmp_path / "runs.db"
    with _seeded_db(
        db_path,
        runs=[
            {
                "run_id": "iter_011_eval_new_vs_old",
                "status": "running",
                "started_at": _now() - timedelta(minutes=5),
                "wins_new": 0, "wins_old": 80,
            },
        ],
    ):
        progress_dir = tmp_path / "progress"
        out = _run_once(
            watcher, progress_dir=progress_dir,
            source="db", db_path=db_path,
        )
    assert sentinel_path(progress_dir, "iter_011_cycle").exists()
    assert "FAIL" in out


def test_db_mode_no_stop_when_ci_straddles(watcher, tmp_path):
    db_path = tmp_path / "runs.db"
    with _seeded_db(
        db_path,
        runs=[
            {
                "run_id": "iter_012_eval_new_vs_old",
                "status": "running",
                "started_at": _now() - timedelta(minutes=5),
                "wins_new": 50, "wins_old": 50,
            },
        ],
    ):
        progress_dir = tmp_path / "progress"
        out = _run_once(
            watcher, progress_dir=progress_dir,
            source="db", db_path=db_path,
        )
    assert not sentinel_path(progress_dir, "iter_012_cycle").exists()
    assert "straddles" in out


def test_db_mode_lookback_filters_stale_running(watcher, tmp_path):
    """A ``running`` row that started 48h ago is presumed zombie state
    the janitor didn't clean up. The watcher must skip it even if
    its numbers would otherwise trip the gate."""
    db_path = tmp_path / "runs.db"
    with _seeded_db(
        db_path,
        runs=[
            {
                "run_id": "iter_013_eval_stale",
                "status": "running",
                "started_at": _now() - timedelta(hours=48),
                "wins_new": 200, "wins_old": 0,
            },
            {
                "run_id": "iter_013_eval_fresh",
                "status": "running",
                "started_at": _now() - timedelta(minutes=2),
                "wins_new": 200, "wins_old": 0,
            },
        ],
    ):
        progress_dir = tmp_path / "progress"
        _run_once(
            watcher, progress_dir=progress_dir,
            source="db", db_path=db_path,
        )
    # Fresh one triggers; stale one is skipped.
    assert sentinel_path(progress_dir, "iter_013_cycle").exists()
    # No sentinel from the stale run.
    assert len(list(progress_dir.glob(".STOP_*"))) == 1


def test_db_mode_uses_aggregate_row_only(watcher, tmp_path):
    """Per-shard rows carry per-shard win counts. The watcher must
    NOT sum them on top of the aggregate row — only the aggregate
    (shard_label IS NULL) counts toward the gate decision."""
    db_path = tmp_path / "runs.db"
    with _seeded_db(
        db_path,
        runs=[
            {
                "run_id": "iter_014_eval_a_vs_b",
                "status": "running",
                "started_at": _now() - timedelta(minutes=5),
                # Aggregate: 50-50 (straddles → no stop).
                "wins_new": 50, "wins_old": 50,
                # Shard rows look like a slam dunk; if the watcher
                # accidentally counted them too we'd see PASS.
                "shards": [("shard_a", 100, 0), ("shard_b", 100, 0)],
            },
        ],
    ):
        progress_dir = tmp_path / "progress"
        out = _run_once(
            watcher, progress_dir=progress_dir,
            source="db", db_path=db_path,
        )
    assert not sentinel_path(progress_dir, "iter_014_cycle").exists()
    assert "straddles" in out


def test_db_mode_skips_other_kinds(watcher, tmp_path):
    db_path = tmp_path / "runs.db"
    with _seeded_db(
        db_path,
        runs=[
            {
                "run_id": "self_play_001",
                "kind": "self_play",
                "status": "running",
                "started_at": _now() - timedelta(minutes=5),
                "wins_new": 100, "wins_old": 0,
            },
        ],
    ):
        progress_dir = tmp_path / "progress"
        _run_once(
            watcher, progress_dir=progress_dir,
            source="db", db_path=db_path,
        )
    # No eval-kind row to check; nothing should be written.
    assert not progress_dir.exists() or not list(
        progress_dir.glob(".STOP_*"),
    )


def test_db_mode_skips_completed_runs(watcher, tmp_path):
    db_path = tmp_path / "runs.db"
    with _seeded_db(
        db_path,
        runs=[
            {
                "run_id": "iter_016_eval_a_vs_b",
                "status": "completed",
                "started_at": _now() - timedelta(minutes=5),
                "wins_new": 100, "wins_old": 0,
            },
        ],
    ):
        # Mark as terminal via lifecycle (we inserted as completed,
        # but the schema requires ended_at on terminal — easier just
        # to assert no sentinel).
        progress_dir = tmp_path / "progress"
        _run_once(
            watcher, progress_dir=progress_dir,
            source="db", db_path=db_path,
        )
    assert not progress_dir.exists() or not list(
        progress_dir.glob(".STOP_*"),
    )


def test_db_mode_missing_db_file_is_noop(watcher, tmp_path):
    """If the DB path doesn't exist, return [] rather than crash."""
    missing_db = tmp_path / "absent.db"
    progress_dir = tmp_path / "progress"
    _run_once(
        watcher, progress_dir=progress_dir,
        source="db", db_path=missing_db,
    )
    assert not progress_dir.exists() or not list(
        progress_dir.glob(".STOP_*"),
    )


def test_db_mode_prefers_parent_run_id_for_cycle(watcher, tmp_path):
    """When parent_run_id is set on the run, the watcher should
    target the parent's sentinel rather than recover from the
    filename pattern."""
    # First insert the parent (iterate cycle) so the FK passes.
    db_path = tmp_path / "runs.db"
    conn = runs_db.connect(db_path)
    try:
        parent = Run(
            run_id="iter_017_cycle",
            kind="iterate",
            status="running",
            started_at=_iso(_now()),
            git_commit="deadbeef",
            config_json="{}",
        )
        runs_db.insert_run(conn, parent)
    finally:
        conn.close()
    with _seeded_db(
        db_path,
        runs=[
            {
                "run_id": "iter_017_eval_a_vs_b",
                "status": "running",
                "started_at": _now() - timedelta(minutes=5),
                "wins_new": 100, "wins_old": 0,
                "parent_run_id": "iter_017_cycle",
            },
        ],
    ):
        progress_dir = tmp_path / "progress"
        _run_once(
            watcher, progress_dir=progress_dir,
            source="db", db_path=db_path,
        )
    assert sentinel_path(progress_dir, "iter_017_cycle").exists()


def test_db_mode_extra_json_cycle_id(watcher, tmp_path):
    """When parent_run_id isn't set but extra_json carries
    cycle_id, use it."""
    db_path = tmp_path / "runs.db"
    with _seeded_db(
        db_path,
        runs=[
            {
                "run_id": "standalone_eval_abc",  # not iter_-prefixed
                "status": "running",
                "started_at": _now() - timedelta(minutes=5),
                "wins_new": 100, "wins_old": 0,
                "extra_json": json.dumps({"cycle_id": "iter_018_cycle"}),
            },
        ],
    ):
        progress_dir = tmp_path / "progress"
        _run_once(
            watcher, progress_dir=progress_dir,
            source="db", db_path=db_path,
        )
    assert sentinel_path(progress_dir, "iter_018_cycle").exists()


def test_db_mode_standalone_eval_no_cycle(watcher, tmp_path):
    """A standalone (non-iterate) eval has no cycle — the sentinel
    targets the run_id directly."""
    db_path = tmp_path / "runs.db"
    with _seeded_db(
        db_path,
        runs=[
            {
                "run_id": "standalone_v16_vs_v13",
                "status": "running",
                "started_at": _now() - timedelta(minutes=5),
                "wins_new": 100, "wins_old": 0,
            },
        ],
    ):
        progress_dir = tmp_path / "progress"
        _run_once(
            watcher, progress_dir=progress_dir,
            source="db", db_path=db_path,
        )
    assert sentinel_path(progress_dir, "standalone_v16_vs_v13").exists()


def test_db_mode_extra_json_garbage(watcher, tmp_path):
    """Malformed extra_json doesn't crash — fall through to filename
    pattern resolution."""
    db_path = tmp_path / "runs.db"
    with _seeded_db(
        db_path,
        runs=[
            {
                "run_id": "iter_019_eval_a_vs_b",
                "status": "running",
                "started_at": _now() - timedelta(minutes=5),
                "wins_new": 100, "wins_old": 0,
                "extra_json": "{not json",
            },
        ],
    ):
        progress_dir = tmp_path / "progress"
        _run_once(
            watcher, progress_dir=progress_dir,
            source="db", db_path=db_path,
        )
    # Filename pattern recovers iter_019_cycle.
    assert sentinel_path(progress_dir, "iter_019_cycle").exists()


# ----- REST transport -------------------------------------------------------


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _fake_urlopen_factory(routes: dict[str, Any]):
    """Build an ``urlopen``-shaped callable that returns canned JSON
    per URL prefix. ``routes`` maps URL → either a dict (returned as
    JSON body) or an Exception subclass / instance (raised)."""

    def fake_urlopen(req, timeout=None):  # noqa: ARG001 (timeout unused)
        url = req.full_url if hasattr(req, "full_url") else req.get_full_url()
        # Match longest prefix.
        match = None
        for prefix in sorted(routes, key=len, reverse=True):
            if url.startswith(prefix):
                match = routes[prefix]
                break
        if match is None:
            raise urllib.error.URLError(f"unmocked URL: {url}")
        if isinstance(match, BaseException) or (
            isinstance(match, type) and issubclass(match, BaseException)
        ):
            raise match() if isinstance(match, type) else match
        body = json.dumps(match).encode("utf-8")
        return _FakeResponse(body)

    return fake_urlopen


def test_rest_mode_writes_stop_on_pass(watcher, tmp_path, monkeypatch):
    started = _iso(_now() - timedelta(minutes=5))
    listing = {
        "runs": [
            {
                "run_id": "iter_020_eval_a_vs_b",
                "kind": "eval",
                "status": "running",
                "started_at": started,
                "parent_run_id": None,
            },
        ],
    }
    detail = {
        "run": {
            "run_id": "iter_020_eval_a_vs_b",
            "kind": "eval",
            "status": "running",
            "started_at": started,
            "parent_run_id": None,
        },
        "progress": [
            {
                "run_id": "iter_020_eval_a_vs_b",
                "shard_label": None,
                "wins_new": 100, "wins_old": 0, "draws": 0,
                "extra_json": None,
            },
            {
                "run_id": "iter_020_eval_a_vs_b",
                "shard_label": "shard_a",  # ignored
                "wins_new": 50, "wins_old": 0,
            },
        ],
    }
    routes = {
        "http://m:5099/runs": listing,
        "http://m:5099/run/iter_020_eval_a_vs_b": detail,
    }
    monkeypatch.setattr(
        watcher.urllib.request, "urlopen", _fake_urlopen_factory(routes),
    )
    progress_dir = tmp_path / "progress"
    out = _run_once(
        watcher, progress_dir=progress_dir,
        source="rest", api_url="http://m:5099",
    )
    assert sentinel_path(progress_dir, "iter_020_cycle").exists()
    assert "PASS" in out


def test_rest_mode_writes_stop_on_fail(watcher, tmp_path, monkeypatch):
    started = _iso(_now() - timedelta(minutes=5))
    listing = {
        "runs": [
            {
                "run_id": "iter_021_eval_a_vs_b",
                "kind": "eval", "status": "running",
                "started_at": started,
            },
        ],
    }
    detail = {
        "run": {
            "run_id": "iter_021_eval_a_vs_b",
            "kind": "eval", "status": "running",
            "started_at": started,
        },
        "progress": [
            {
                "shard_label": None,
                "wins_new": 0, "wins_old": 100, "draws": 0,
            },
        ],
    }
    routes = {
        "http://m:5099/runs": listing,
        "http://m:5099/run/iter_021_eval_a_vs_b": detail,
    }
    monkeypatch.setattr(
        watcher.urllib.request, "urlopen", _fake_urlopen_factory(routes),
    )
    progress_dir = tmp_path / "progress"
    out = _run_once(
        watcher, progress_dir=progress_dir,
        source="rest", api_url="http://m:5099",
    )
    assert sentinel_path(progress_dir, "iter_021_cycle").exists()
    assert "FAIL" in out


def test_rest_mode_no_stop_when_ci_straddles(watcher, tmp_path, monkeypatch):
    started = _iso(_now() - timedelta(minutes=5))
    listing = {"runs": [
        {"run_id": "iter_022_eval_a_vs_b", "kind": "eval",
         "status": "running", "started_at": started},
    ]}
    detail = {
        "run": listing["runs"][0],
        "progress": [
            {"shard_label": None, "wins_new": 50, "wins_old": 50},
        ],
    }
    routes = {
        "http://m:5099/runs": listing,
        "http://m:5099/run/iter_022_eval_a_vs_b": detail,
    }
    monkeypatch.setattr(
        watcher.urllib.request, "urlopen", _fake_urlopen_factory(routes),
    )
    progress_dir = tmp_path / "progress"
    out = _run_once(
        watcher, progress_dir=progress_dir,
        source="rest", api_url="http://m:5099",
    )
    assert not sentinel_path(progress_dir, "iter_022_cycle").exists()
    assert "straddles" in out


def test_rest_mode_listing_url_error_is_noop(watcher, tmp_path, monkeypatch):
    routes = {"http://m:5099/runs": urllib.error.URLError("conn refused")}
    monkeypatch.setattr(
        watcher.urllib.request, "urlopen", _fake_urlopen_factory(routes),
    )
    progress_dir = tmp_path / "progress"
    _run_once(
        watcher, progress_dir=progress_dir,
        source="rest", api_url="http://m:5099",
    )
    assert not progress_dir.exists() or not list(
        progress_dir.glob(".STOP_*"),
    )


def test_rest_mode_detail_url_error_skips_run(watcher, tmp_path, monkeypatch):
    """If the detail call fails for one run, the watcher skips
    that run but keeps going for others."""
    started = _iso(_now() - timedelta(minutes=5))
    listing = {"runs": [
        {"run_id": "iter_023_eval_a", "kind": "eval",
         "status": "running", "started_at": started},
        {"run_id": "iter_024_eval_b", "kind": "eval",
         "status": "running", "started_at": started},
    ]}
    detail_b = {
        "run": listing["runs"][1],
        "progress": [
            {"shard_label": None, "wins_new": 100, "wins_old": 0},
        ],
    }
    routes = {
        "http://m:5099/runs": listing,
        "http://m:5099/run/iter_023_eval_a": urllib.error.URLError("timeout"),
        "http://m:5099/run/iter_024_eval_b": detail_b,
    }
    monkeypatch.setattr(
        watcher.urllib.request, "urlopen", _fake_urlopen_factory(routes),
    )
    progress_dir = tmp_path / "progress"
    _run_once(
        watcher, progress_dir=progress_dir,
        source="rest", api_url="http://m:5099",
    )
    assert sentinel_path(progress_dir, "iter_024_cycle").exists()
    assert not sentinel_path(progress_dir, "iter_023_cycle").exists()


def test_rest_mode_lookback_client_side_filter(watcher, tmp_path, monkeypatch):
    """Even if the API ignores ``since=``, the watcher filters
    client-side by ``started_at``."""
    stale = _iso(_now() - timedelta(hours=48))
    listing = {"runs": [
        {"run_id": "iter_025_eval_stale", "kind": "eval",
         "status": "running", "started_at": stale},
    ]}
    detail = {
        "run": listing["runs"][0],
        "progress": [
            {"shard_label": None, "wins_new": 100, "wins_old": 0},
        ],
    }
    routes = {
        "http://m:5099/runs": listing,
        "http://m:5099/run/iter_025_eval_stale": detail,
    }
    monkeypatch.setattr(
        watcher.urllib.request, "urlopen", _fake_urlopen_factory(routes),
    )
    progress_dir = tmp_path / "progress"
    _run_once(
        watcher, progress_dir=progress_dir,
        source="rest", api_url="http://m:5099",
    )
    # Stale row filtered client-side → no sentinel.
    assert not progress_dir.exists() or not list(
        progress_dir.glob(".STOP_*"),
    )


def test_rest_mode_skips_run_without_id(watcher, tmp_path, monkeypatch):
    started = _iso(_now() - timedelta(minutes=5))
    listing = {"runs": [
        {"kind": "eval", "status": "running", "started_at": started},
    ]}
    routes = {"http://m:5099/runs": listing}
    monkeypatch.setattr(
        watcher.urllib.request, "urlopen", _fake_urlopen_factory(routes),
    )
    progress_dir = tmp_path / "progress"
    _run_once(
        watcher, progress_dir=progress_dir,
        source="rest", api_url="http://m:5099",
    )
    assert not progress_dir.exists() or not list(
        progress_dir.glob(".STOP_*"),
    )


def test_rest_mode_handles_malformed_listing(watcher, tmp_path, monkeypatch):
    """If /runs returns something that isn't ``{"runs": [...]}``,
    yield an empty list rather than crash."""
    routes = {"http://m:5099/runs": ["not", "a", "dict"]}
    monkeypatch.setattr(
        watcher.urllib.request, "urlopen", _fake_urlopen_factory(routes),
    )
    progress_dir = tmp_path / "progress"
    _run_once(
        watcher, progress_dir=progress_dir,
        source="rest", api_url="http://m:5099",
    )
    assert not progress_dir.exists() or not list(
        progress_dir.glob(".STOP_*"),
    )


def test_rest_mode_detail_falls_back_to_listing_run(watcher, tmp_path, monkeypatch):
    """If /run/<id> returns a partial payload (missing 'run'), the
    watcher uses the listing row for the run-level fields."""
    started = _iso(_now() - timedelta(minutes=5))
    listing_run = {
        "run_id": "iter_026_eval_a_vs_b", "kind": "eval",
        "status": "running", "started_at": started,
        "parent_run_id": None,
    }
    listing = {"runs": [listing_run]}
    detail = {
        # 'run' key omitted on purpose.
        "progress": [
            {"shard_label": None, "wins_new": 100, "wins_old": 0},
        ],
    }
    routes = {
        "http://m:5099/runs": listing,
        "http://m:5099/run/iter_026_eval_a_vs_b": detail,
    }
    monkeypatch.setattr(
        watcher.urllib.request, "urlopen", _fake_urlopen_factory(routes),
    )
    progress_dir = tmp_path / "progress"
    _run_once(
        watcher, progress_dir=progress_dir,
        source="rest", api_url="http://m:5099",
    )
    assert sentinel_path(progress_dir, "iter_026_cycle").exists()


# ----- de-dup of repeated stop messages -------------------------------------


def test_already_stopped_is_idempotent(watcher, tmp_path):
    """A second call on the same run with the sentinel already
    written should NOT re-emit the stop message."""
    progress_dir = tmp_path / "progress"
    _write_eval_json(
        progress_dir, "iter_030_eval_a_vs_b",
        wins_new=100, wins_old=0,
    )
    already: set[str] = set()
    msg1 = watcher._check_status(
        {
            "run_id": "iter_030_eval_a_vs_b",
            "wins_new": 100, "wins_old": 0, "draws": 0,
            "cycle_id": None, "started_at": None,
        },
        threshold=EVAL_GATE_THRESHOLD, z=1.96, min_decisive=30,
        progress_dir=progress_dir, already_stopped=already,
    )
    assert msg1 is not None and "wrote stop sentinel" in msg1
    msg2 = watcher._check_status(
        {
            "run_id": "iter_030_eval_a_vs_b",
            "wins_new": 100, "wins_old": 0, "draws": 0,
            "cycle_id": None, "started_at": None,
        },
        threshold=EVAL_GATE_THRESHOLD, z=1.96, min_decisive=30,
        progress_dir=progress_dir, already_stopped=already,
    )
    assert msg2 is None


# ----- Wilson CI edge cases (direct) ----------------------------------------


def test_wilson_ci_zero_n(watcher):
    p, lo, hi = watcher._wilson_ci(0, 0)
    assert (p, lo, hi) == (0.0, 0.0, 1.0)


def test_z_for_alpha_known_values(watcher):
    assert watcher._z_for_alpha(0.025) == pytest.approx(1.96)
    assert watcher._z_for_alpha(0.01) == pytest.approx(2.326)


def test_z_for_alpha_unknown_falls_back(watcher):
    assert watcher._z_for_alpha(0.0123) == pytest.approx(1.96)


def test_resolve_cycle_id_explicit_wins(watcher):
    """An explicit cycle_id field beats the filename pattern."""
    cid = watcher._resolve_cycle_id(
        "custom_cycle_42", "iter_999_eval_a_vs_b",
    )
    assert cid == "custom_cycle_42"


def test_resolve_cycle_id_filename_pattern(watcher):
    cid = watcher._resolve_cycle_id(None, "iter_042_eval_a_vs_b")
    assert cid == "iter_042_cycle"


def test_resolve_cycle_id_standalone(watcher):
    """A standalone eval (no iter_NNN prefix) has no cycle."""
    assert watcher._resolve_cycle_id(None, "standalone_v16_vs_v13") is None


# ----- main() resolution + error-path coverage ------------------------------


def test_main_db_mode_reads_db_path_from_env(
    watcher, tmp_path, monkeypatch,
):
    """When --db-path isn't passed but $MTG_BOT_RUN_DB_PATH is set,
    main() picks up the env var. Covers the env-fallback branch."""
    db_path = tmp_path / "runs.db"
    with _seeded_db(
        db_path,
        runs=[
            {
                "run_id": "iter_040_eval_a_vs_b",
                "status": "running",
                "started_at": _now() - timedelta(minutes=5),
                "wins_new": 80, "wins_old": 0,
            },
        ],
    ):
        monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", str(db_path))
        progress_dir = tmp_path / "progress"
        # Note: no db_path kwarg → main() falls back to env.
        _run_once(
            watcher, progress_dir=progress_dir, source="db",
        )
    assert sentinel_path(progress_dir, "iter_040_cycle").exists()


def test_main_warns_and_continues_on_db_error(
    watcher, tmp_path, monkeypatch,
):
    """An OSError / sqlite3.Error inside _load_statuses must not
    crash the loop — main() warns and treats the tick as empty."""

    def boom(*_args, **_kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(watcher, "_load_statuses", boom)
    progress_dir = tmp_path / "progress"
    out = _run_once(
        watcher, progress_dir=progress_dir, source="db",
        db_path=tmp_path / "doesnt-matter.db",
    )
    assert "WARNING: failed to load eval state" in out
    # And of course no sentinel was written.
    assert not progress_dir.exists() or not list(
        progress_dir.glob(".STOP_*"),
    )


def test_main_loops_until_once_or_external_stop(
    watcher, tmp_path, monkeypatch,
):
    """Without --once, the loop iterates indefinitely. Patch
    time.sleep so the second tick raises and aborts the loop —
    that exercises the post-sleep continuation path."""

    progress_dir = tmp_path / "progress"
    progress_dir.mkdir()
    calls = {"n": 0}

    def fake_sleep(_secs):
        calls["n"] += 1
        if calls["n"] >= 1:
            raise KeyboardInterrupt

    monkeypatch.setattr(watcher.time, "sleep", fake_sleep)
    buf = io.StringIO()
    # Note: NO --once, so the loop runs until fake_sleep raises.
    with redirect_stdout(buf):
        with pytest.raises(KeyboardInterrupt):
            watcher.main([
                "--progress-dir", str(progress_dir),
                "--source", "jsons",
                "--check-interval-sec", "0.001",
            ])
    assert calls["n"] >= 1
