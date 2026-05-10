"""Tests for ``mtg_bot.cli.runs.backfill``.

The fixture matrix mirrors the brief's Sub-task A:

(a) Clean completed runs — happy path; aggregate JSON with terminal
    status maps cleanly into the DB.
(b) A stale-running run — JSON status is still ``running`` but mtime
    is older than the cutoff, so the heuristic stamps ``status=killed``
    and ``ended_at = file mtime``.
(c) Per-shard JSONs alongside an aggregate — both should land, the
    aggregate as ``shard_label IS NULL`` and the per-shard rows under
    their labels.
(d) A partial run — per-shard JSONs exist but no aggregate JSON; the
    backfill synthesizes a parent ``runs`` row so the per-shard rows
    have somewhere to attach.

Plus the explicit idempotency / kind-mapping / error-path corners.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from mtg_bot.cli.runs import backfill, db as runs_db
from mtg_bot.cli.runs.models import (
    Artifact, ProgressUpdate, Run,
)


def _write_progress_json(
    progress_dir: Path, name: str, payload: dict, *,
    mtime: float | None = None,
) -> Path:
    """Drop a synthetic progress JSON. ``mtime`` lets a test pin a
    file's age so the stale-running heuristic is deterministic."""
    path = progress_dir / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


@pytest.fixture()
def progress_dir(tmp_path: Path) -> Path:
    d = tmp_path / "training_progress"
    d.mkdir()
    return d


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "training_progress" / "runs.db"


# ---- (a) clean completed runs ---------------------------------------------


def test_clean_completed_eval_run_lands_in_db(progress_dir, db_path):
    """A completed eval JSON with all the standard fields backfills
    into a single ``runs`` row + aggregate ``run_progress`` row.
    Counter columns land directly; the rich ``machines`` /
    ``opponent_label`` / ``win_rate`` blob flows into ``extra_json``.
    """
    payload = {
        "run_id": "eval_v9_vs_v8",
        "kind": "eval",
        "status": "completed",
        "started_at": "2026-05-04T10:00:00+00:00",
        "ended_at": "2026-05-04T11:00:00+00:00",
        "git_commit": "abcdef0",
        "n_games_done": 200,
        "n_games_total": 200,
        "elapsed_seconds": 3600.0,
        "wins_new": 110,
        "wins_old": 80,
        "draws": 10,
        "crashed": 0,
        "timed_out": 0,
        "win_rate": 0.55,
        "opponent_label": "v8",
        "machines": [
            {"label": "macbook", "n_games_done": 100, "n_workers": 14},
        ],
    }
    _write_progress_json(progress_dir, "eval_v9_vs_v8.json", payload)

    summary = backfill.backfill_progress_dir(progress_dir, db_path)
    assert summary.runs_inserted == 1
    assert summary.progress_rows_upserted == 1
    assert summary.shard_rows_upserted == 0
    assert summary.errors == []

    conn = runs_db.connect(db_path)
    try:
        run = conn.execute(
            "SELECT * FROM runs WHERE run_id = ?", ("eval_v9_vs_v8",),
        ).fetchone()
        assert run["kind"] == "eval"
        assert run["status"] == "completed"
        assert run["ended_at"] == "2026-05-04T11:00:00+00:00"
        assert run["git_commit"] == "abcdef0"

        progress = conn.execute(
            "SELECT * FROM run_progress WHERE run_id = ? "
            "AND shard_label IS NULL",
            ("eval_v9_vs_v8",),
        ).fetchone()
        assert progress["n_games_done"] == 200
        assert progress["wins_new"] == 110
        assert progress["draws"] == 10
        extra = json.loads(progress["extra_json"])
        # Rich fields flow to extra_json, NOT to the structured columns.
        assert extra["win_rate"] == 0.55
        assert extra["opponent_label"] == "v8"
        assert extra["machines"][0]["label"] == "macbook"
    finally:
        conn.close()


def test_data_gen_kind_maps_to_self_play(progress_dir, db_path):
    """Producer-side JSONs use ``kind="data_gen"`` (UI nomenclature);
    DB enum is ``self_play``. Backfill maps on the way in."""
    _write_progress_json(progress_dir, "iter_001_self_play_v6.json", {
        "run_id": "iter_001_self_play_v6",
        "kind": "data_gen",
        "status": "completed",
        "started_at": "2026-05-04T05:53:36+00:00",
        "ended_at": "2026-05-04T06:07:04+00:00",
        "n_games_done": 500, "n_games_total": 500,
    })
    summary = backfill.backfill_progress_dir(progress_dir, db_path)
    assert summary.runs_inserted == 1

    conn = runs_db.connect(db_path)
    try:
        row = conn.execute(
            "SELECT kind FROM runs WHERE run_id = ?",
            ("iter_001_self_play_v6",),
        ).fetchone()
        assert row["kind"] == "self_play"
    finally:
        conn.close()


def test_cycle_kind_maps_to_iterate(progress_dir, db_path):
    """Same as above for ``kind="cycle"`` (the iterate parent run)."""
    _write_progress_json(progress_dir, "iter_001_cycle.json", {
        "run_id": "iter_001_cycle",
        "kind": "cycle",
        "status": "completed",
        "started_at": "2026-05-04T05:00:00+00:00",
        "ended_at": "2026-05-04T07:00:00+00:00",
        "iter_idx": 1, "n_iterations": 5,
    })
    summary = backfill.backfill_progress_dir(progress_dir, db_path)
    assert summary.runs_inserted == 1

    conn = runs_db.connect(db_path)
    try:
        row = conn.execute(
            "SELECT kind FROM runs WHERE run_id = ?",
            ("iter_001_cycle",),
        ).fetchone()
        assert row["kind"] == "iterate"
    finally:
        conn.close()


def test_unknown_kind_records_error_and_skips(progress_dir, db_path):
    """A JSON whose ``kind`` is missing entirely (or some unrecognized
    string) can't be mapped to the DB enum. We log it as an error
    rather than fabricating a kind."""
    _write_progress_json(progress_dir, "weird.json", {
        "run_id": "weird",
        "status": "completed",
        # no 'kind' field
    })
    summary = backfill.backfill_progress_dir(progress_dir, db_path)
    assert summary.runs_inserted == 0
    assert summary.files_skipped >= 1
    assert any("weird.json" in e for e in summary.errors)


def test_status_stopped_maps_to_killed(progress_dir, db_path):
    """Producer-side JSONs use ``status="stopped"`` for clean
    user-requested stops. The DB enum doesn't carry ``stopped``; we
    map to ``killed`` and stash the original in ``extra_json`` so the
    UI can still display it verbatim."""
    _write_progress_json(progress_dir, "iter_005_cycle.json", {
        "run_id": "iter_005_cycle",
        "kind": "cycle",
        "status": "stopped",
        "started_at": "2026-05-10T00:36:58+00:00",
        "ended_at": "2026-05-10T16:03:45+00:00",
        "notes": "manually marked stopped",
    })
    backfill.backfill_progress_dir(progress_dir, db_path)
    conn = runs_db.connect(db_path)
    try:
        run = conn.execute(
            "SELECT status, ended_at FROM runs WHERE run_id = ?",
            ("iter_005_cycle",),
        ).fetchone()
        assert run["status"] == "killed"
        assert run["ended_at"] == "2026-05-10T16:03:45+00:00"
        progress = conn.execute(
            "SELECT extra_json FROM run_progress "
            "WHERE run_id = ? AND shard_label IS NULL",
            ("iter_005_cycle",),
        ).fetchone()
        extra = json.loads(progress["extra_json"])
        assert extra["original_status"] == "stopped"
    finally:
        conn.close()


# ---- (b) stale-running heuristic ------------------------------------------


def test_stale_running_marked_killed_by_age(progress_dir, db_path):
    """A JSON that says ``status=running`` with NO ``ended_at`` and an
    mtime older than the cutoff gets stamped killed + ended_at = mtime.
    """
    fake_now = 1_750_000_000.0
    seven_hours_ago = fake_now - (7 * 3600)
    _write_progress_json(
        progress_dir, "iter_003_self_play_v18.json",
        {
            "run_id": "iter_003_self_play_v18",
            "kind": "data_gen",
            "status": "running",
            "started_at": "2026-05-09T01:00:00+00:00",
            "n_games_done": 42, "n_games_total": 500,
        },
        mtime=seven_hours_ago,
    )
    summary = backfill.backfill_progress_dir(
        progress_dir, db_path, now=fake_now,
    )
    assert summary.stale_running_marked_terminal == 1

    conn = runs_db.connect(db_path)
    try:
        run = conn.execute(
            "SELECT status, ended_at FROM runs WHERE run_id = ?",
            ("iter_003_self_play_v18",),
        ).fetchone()
        assert run["status"] == "killed"
        # ended_at is the file mtime, projected to ISO.
        assert run["ended_at"] is not None
        progress = conn.execute(
            "SELECT extra_json FROM run_progress "
            "WHERE run_id = ? AND shard_label IS NULL",
            ("iter_003_self_play_v18",),
        ).fetchone()
        extra = json.loads(progress["extra_json"])
        assert extra["original_status"] == "running"
        assert "stale-running heuristic" in extra["backfill_note"]
    finally:
        conn.close()


def test_recent_running_left_alone(progress_dir, db_path):
    """A JSON that's still genuinely fresh (mtime within cutoff)
    should NOT trigger the stale heuristic — the producer might
    actually still be alive."""
    fake_now = 1_750_000_000.0
    one_hour_ago = fake_now - 3600
    _write_progress_json(
        progress_dir, "active_run.json",
        {
            "run_id": "active_run",
            "kind": "eval",
            "status": "running",
            "started_at": "2026-05-09T15:00:00+00:00",
        },
        mtime=one_hour_ago,
    )
    summary = backfill.backfill_progress_dir(
        progress_dir, db_path, now=fake_now,
    )
    assert summary.stale_running_marked_terminal == 0

    conn = runs_db.connect(db_path)
    try:
        run = conn.execute(
            "SELECT status FROM runs WHERE run_id = ?", ("active_run",),
        ).fetchone()
        assert run["status"] == "running"
    finally:
        conn.close()


def test_stop_sentinel_promotes_to_killed(progress_dir, db_path):
    """If a ``.STOP_<run_id>`` sentinel sits next to a fresh running
    JSON, the producer never finalized after the user clicked stop —
    treat the run as terminal even though mtime is recent."""
    fake_now = 1_750_000_000.0
    one_hour_ago = fake_now - 3600
    _write_progress_json(
        progress_dir, "stuck_run.json",
        {
            "run_id": "stuck_run",
            "kind": "eval",
            "status": "running",
            "started_at": "2026-05-09T15:00:00+00:00",
        },
        mtime=one_hour_ago,
    )
    (progress_dir / ".STOP_stuck_run").write_text("test", encoding="utf-8")

    summary = backfill.backfill_progress_dir(
        progress_dir, db_path, now=fake_now,
    )
    assert summary.stale_running_marked_terminal == 1

    conn = runs_db.connect(db_path)
    try:
        run = conn.execute(
            "SELECT status FROM runs WHERE run_id = ?", ("stuck_run",),
        ).fetchone()
        assert run["status"] == "killed"
    finally:
        conn.close()


def test_running_with_ended_at_promotes_to_killed(progress_dir, db_path):
    """A weird JSON that has ``status=running`` AND ``ended_at`` set
    is producer-side-buggy. Trust the wall-clock end time, promote to
    killed, and stash the inconsistency note."""
    _write_progress_json(progress_dir, "buggy.json", {
        "run_id": "buggy",
        "kind": "eval",
        "status": "running",
        "started_at": "2026-05-09T15:00:00+00:00",
        "ended_at": "2026-05-09T16:00:00+00:00",
    })
    backfill.backfill_progress_dir(progress_dir, db_path)
    conn = runs_db.connect(db_path)
    try:
        run = conn.execute(
            "SELECT status, ended_at FROM runs WHERE run_id = ?",
            ("buggy",),
        ).fetchone()
        assert run["status"] == "killed"
        assert run["ended_at"] == "2026-05-09T16:00:00+00:00"
        progress = conn.execute(
            "SELECT extra_json FROM run_progress "
            "WHERE run_id = ? AND shard_label IS NULL",
            ("buggy",),
        ).fetchone()
        extra = json.loads(progress["extra_json"])
        assert "promoted to killed" in extra["backfill_note"]
    finally:
        conn.close()


# ---- (c) per-shard JSONs alongside an aggregate ---------------------------


def test_per_shard_jsons_become_per_shard_progress_rows(
    progress_dir, db_path,
):
    """Aggregate JSON + N per-shard JSONs all land. The aggregate
    populates the ``shard_label IS NULL`` row; each per-shard JSON
    populates its own row keyed by label."""
    _write_progress_json(progress_dir, "iter_001_eval_v18_vs_v17.json", {
        "run_id": "iter_001_eval_v18_vs_v17",
        "kind": "eval",
        "status": "completed",
        "started_at": "2026-05-04T10:00:00+00:00",
        "ended_at": "2026-05-04T11:00:00+00:00",
        "n_games_done": 200, "n_games_total": 200,
        "wins_new": 110, "wins_old": 80, "draws": 10,
    })
    _write_progress_json(
        progress_dir, "iter_001_eval_v18_vs_v17_shard_local.json", {
            "run_id": "iter_001_eval_v18_vs_v17_shard_local",
            "kind": "eval",
            "status": "completed",
            "started_at": "2026-05-04T10:00:00+00:00",
            "ended_at": "2026-05-04T11:00:00+00:00",
            "n_games_done": 100, "n_games_total": 100,
            "wins_new": 55,
        },
    )
    _write_progress_json(
        progress_dir,
        "iter_001_eval_v18_vs_v17_shard_greggs-macbook-pro.json",
        {
            "run_id": (
                "iter_001_eval_v18_vs_v17_shard_greggs-macbook-pro"
            ),
            "kind": "eval",
            "status": "completed",
            "started_at": "2026-05-04T10:00:00+00:00",
            "ended_at": "2026-05-04T11:00:00+00:00",
            "n_games_done": 100, "n_games_total": 100,
            "wins_new": 55,
        },
    )

    summary = backfill.backfill_progress_dir(progress_dir, db_path)
    assert summary.runs_inserted == 1
    assert summary.progress_rows_upserted == 1
    assert summary.shard_rows_upserted == 2

    conn = runs_db.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT shard_label, n_games_done FROM run_progress "
            "WHERE run_id = ? "
            "ORDER BY shard_label IS NULL DESC, shard_label",
            ("iter_001_eval_v18_vs_v17",),
        ).fetchall()
        labels = [r["shard_label"] for r in rows]
        assert labels == [
            None, "greggs-macbook-pro", "local",
        ]
        # Aggregate carries the rolled-up counter; per-shard each
        # carry their slice.
        assert rows[0]["n_games_done"] == 200
        assert rows[1]["n_games_done"] == 100
        assert rows[2]["n_games_done"] == 100
        # Per-shard JSONs are also registered as artifacts.
        arts = conn.execute(
            "SELECT artifact_type, COUNT(*) AS n FROM run_artifacts "
            "WHERE run_id = ? GROUP BY artifact_type",
            ("iter_001_eval_v18_vs_v17",),
        ).fetchall()
        types = {r["artifact_type"]: r["n"] for r in arts}
        assert types == {"progress_json": 1, "shard_progress_json": 2}
    finally:
        conn.close()


# ---- (d) per-shard JSONs without an aggregate -----------------------------


def test_orphan_shard_synthesizes_parent_runs_row(progress_dir, db_path):
    """Self-play sometimes leaves per-shard JSONs without a rolled-up
    aggregate (the aggregator never fired). The backfill synthesizes
    a minimal parent ``runs`` row so the per-shard rows have somewhere
    to attach via the FK."""
    _write_progress_json(
        progress_dir,
        "orphaned_self_play_shard_local.json", {
            "run_id": "orphaned_self_play_shard_local",
            "kind": "data_gen",
            "status": "failed",
            "started_at": "2026-05-04T10:00:00+00:00",
            "n_games_done": 5, "n_games_total": 100,
        },
    )
    summary = backfill.backfill_progress_dir(progress_dir, db_path)
    assert summary.runs_inserted == 1  # the synthesized parent
    assert summary.shard_rows_upserted == 1

    conn = runs_db.connect(db_path)
    try:
        run = conn.execute(
            "SELECT status, kind, notes FROM runs WHERE run_id = ?",
            ("orphaned_self_play",),
        ).fetchone()
        assert run is not None
        # The synthesized parent gets killed status (we don't know
        # for sure it completed — best-effort terminal).
        assert run["status"] == "killed"
        assert run["kind"] == "self_play"
        assert "synthesized parent" in run["notes"]

        shard = conn.execute(
            "SELECT shard_label, n_games_done FROM run_progress "
            "WHERE run_id = ?",
            ("orphaned_self_play",),
        ).fetchone()
        assert shard["shard_label"] == "local"
        assert shard["n_games_done"] == 5
    finally:
        conn.close()


# ---- idempotency ----------------------------------------------------------


def test_rerun_is_idempotent_terminal_unchanged(progress_dir, db_path):
    """Running the backfill twice against the same source dir yields
    the same DB. Specifically: a completed run stays completed even
    if the JSON's status drifts."""
    _write_progress_json(progress_dir, "done.json", {
        "run_id": "done", "kind": "eval", "status": "completed",
        "started_at": "2026-05-04T10:00:00+00:00",
        "ended_at": "2026-05-04T11:00:00+00:00",
    })
    backfill.backfill_progress_dir(progress_dir, db_path)
    # Mutate the on-disk JSON to simulate a stale rewrite.
    _write_progress_json(progress_dir, "done.json", {
        "run_id": "done", "kind": "eval", "status": "running",
        "started_at": "2026-05-04T10:00:00+00:00",
    })
    summary = backfill.backfill_progress_dir(progress_dir, db_path)
    assert summary.runs_inserted == 0
    assert summary.runs_skipped_terminal == 1

    conn = runs_db.connect(db_path)
    try:
        run = conn.execute(
            "SELECT status, ended_at FROM runs WHERE run_id = ?",
            ("done",),
        ).fetchone()
        # Authoritative DB row preserved despite stale JSON.
        assert run["status"] == "completed"
        assert run["ended_at"] == "2026-05-04T11:00:00+00:00"
    finally:
        conn.close()


def test_rerun_advances_running_to_terminal(progress_dir, db_path):
    """When the existing DB row is non-terminal, a re-run that finds
    the JSON now shows a terminal status DOES advance the row."""
    fake_now = 1_750_000_000.0
    _write_progress_json(
        progress_dir, "in_flight.json",
        {
            "run_id": "in_flight", "kind": "eval", "status": "running",
            "started_at": "2026-05-09T15:00:00+00:00",
        },
        mtime=fake_now - 60,  # fresh
    )
    backfill.backfill_progress_dir(
        progress_dir, db_path, now=fake_now,
    )
    # Producer has now finalized — JSON updated terminal.
    _write_progress_json(progress_dir, "in_flight.json", {
        "run_id": "in_flight", "kind": "eval", "status": "completed",
        "started_at": "2026-05-09T15:00:00+00:00",
        "ended_at": "2026-05-09T16:00:00+00:00",
        "wins_new": 50, "wins_old": 40, "draws": 0,
    })
    summary = backfill.backfill_progress_dir(progress_dir, db_path)
    assert summary.runs_updated == 1

    conn = runs_db.connect(db_path)
    try:
        run = conn.execute(
            "SELECT status, ended_at FROM runs WHERE run_id = ?",
            ("in_flight",),
        ).fetchone()
        assert run["status"] == "completed"
        assert run["ended_at"] == "2026-05-09T16:00:00+00:00"
    finally:
        conn.close()


# ---- exclusion / robustness ----------------------------------------------


def test_excludes_events_jsonl_and_result_json(progress_dir, db_path):
    """Per-shard event-log files (``*_events.jsonl``) and shard result
    files (``*_result.json``) are NOT run records. They must be
    skipped silently."""
    (progress_dir / "x_shard_local_events.jsonl").write_text(
        '{"timestamp": "2026-05-04T10:00:00+00:00"}\n', encoding="utf-8",
    )
    (progress_dir / "x_shard_local_result.json").write_text(
        json.dumps({"some": "result"}), encoding="utf-8",
    )
    summary = backfill.backfill_progress_dir(progress_dir, db_path)
    assert summary.runs_inserted == 0
    assert summary.files_skipped >= 1


def test_skips_unparseable_json(progress_dir, db_path):
    """A truncated / corrupt JSON file shouldn't take the whole
    backfill down; we count it under ``files_unparseable`` and move
    on."""
    (progress_dir / "broken.json").write_text(
        "{this is not valid json", encoding="utf-8",
    )
    _write_progress_json(progress_dir, "good.json", {
        "run_id": "good", "kind": "eval", "status": "completed",
        "started_at": "2026-05-04T10:00:00+00:00",
        "ended_at": "2026-05-04T11:00:00+00:00",
    })
    summary = backfill.backfill_progress_dir(progress_dir, db_path)
    assert summary.runs_inserted == 1
    assert summary.files_unparseable == 1


def test_skips_bom_prefixed_json_via_utf8_sig(progress_dir, db_path):
    """Some legacy producer JSONs were written with a UTF-8 BOM. The
    reader uses ``utf-8-sig`` so the BOM doesn't bork ``json.load``.
    """
    payload = json.dumps({
        "run_id": "bom_run", "kind": "eval", "status": "completed",
        "started_at": "2026-05-04T10:00:00+00:00",
        "ended_at": "2026-05-04T11:00:00+00:00",
    })
    # Write with explicit BOM prefix.
    (progress_dir / "bom_run.json").write_bytes(
        b"\xef\xbb\xbf" + payload.encode("utf-8"),
    )
    summary = backfill.backfill_progress_dir(progress_dir, db_path)
    assert summary.runs_inserted == 1


def test_skips_non_dict_json(progress_dir, db_path):
    """A JSON that parses to a list (or scalar) rather than a dict
    isn't a run record — skip silently rather than crash."""
    (progress_dir / "list.json").write_text("[1, 2, 3]", encoding="utf-8")
    summary = backfill.backfill_progress_dir(progress_dir, db_path)
    assert summary.runs_inserted == 0
    assert summary.files_unparseable == 1


def test_missing_progress_dir_returns_error_summary(tmp_path):
    """Pointing the backfill at a non-existent directory returns a
    summary with an error message — not a crash."""
    db_path = tmp_path / "runs.db"
    summary = backfill.backfill_progress_dir(
        tmp_path / "no_such_dir", db_path,
    )
    assert summary.runs_inserted == 0
    assert any("does not exist" in e for e in summary.errors)


def test_empty_progress_dir_yields_empty_summary(progress_dir, db_path):
    """An empty dir is fine — the backfill creates the DB schema
    and reports zeros."""
    summary = backfill.backfill_progress_dir(progress_dir, db_path)
    assert summary.runs_inserted == 0
    assert summary.errors == []
    assert db_path.is_file()  # schema applied


def test_iter_progress_json_files_filters_excluded(progress_dir):
    """Helper used by the docs / ad-hoc tooling to list which files
    the backfill considers."""
    (progress_dir / "a.json").write_text("{}", encoding="utf-8")
    (progress_dir / "b_events.jsonl").write_text("\n", encoding="utf-8")
    (progress_dir / "c_result.json").write_text("{}", encoding="utf-8")
    files = [p.name for p in backfill.iter_progress_json_files(progress_dir)]
    assert files == ["a.json"]


def test_iter_progress_json_files_handles_missing_dir(tmp_path):
    files = list(
        backfill.iter_progress_json_files(tmp_path / "no_such_dir"),
    )
    assert files == []


# ---- summary rendering / dataclass ----------------------------------------


def test_summary_render_includes_all_counters():
    s = backfill.BackfillSummary(
        runs_inserted=2,
        runs_updated=1,
        runs_skipped_terminal=3,
        progress_rows_upserted=4,
        shard_rows_upserted=5,
        artifacts_registered=6,
        stale_running_marked_terminal=7,
        files_skipped=8,
        files_unparseable=9,
        errors=["something went wrong"],
    )
    rendered = s.render()
    assert "runs inserted               : 2" in rendered
    assert "stale-running -> terminal   : 7" in rendered
    assert "something went wrong" in rendered


def test_summary_as_dict_round_trips():
    s = backfill.BackfillSummary(runs_inserted=5)
    d = s.as_dict()
    assert d["runs_inserted"] == 5
    assert d["errors"] == []


# ---- terminal-skip preserves DB-side richer rows --------------------------


def test_terminal_skip_does_not_overwrite_progress(progress_dir, db_path):
    """If the DB already has a richer run_progress row (because the
    dual-write producer pushed it before the JSON-side history was
    backfilled), the backfill must not clobber it."""
    # Pre-seed a "real" terminal record with rich progress.
    conn = runs_db.connect(db_path)
    try:
        runs_db.insert_run(
            conn,
            Run(
                run_id="hot", kind="eval", status="completed",
                started_at="2026-05-04T10:00:00+00:00",
                ended_at="2026-05-04T11:00:00+00:00",
                git_commit="livecommit", config_json="{}",
            ),
        )
        runs_db.upsert_progress(
            conn,
            ProgressUpdate(
                run_id="hot", n_games_done=200, n_games_total=200,
                wins_new=120, wins_old=70, draws=10,
                extra_json=json.dumps({"win_rate": 0.6}),
            ),
        )
    finally:
        conn.close()

    # Now drop a stale JSON next to it.
    _write_progress_json(progress_dir, "hot.json", {
        "run_id": "hot", "kind": "eval", "status": "running",
        "started_at": "2026-05-04T10:00:00+00:00",
        # No counters at all — would clobber if we let it through.
    })
    summary = backfill.backfill_progress_dir(progress_dir, db_path)
    assert summary.runs_skipped_terminal == 1

    conn = runs_db.connect(db_path)
    try:
        progress = conn.execute(
            "SELECT n_games_done, wins_new, extra_json FROM run_progress "
            "WHERE run_id = ? AND shard_label IS NULL",
            ("hot",),
        ).fetchone()
        assert progress["n_games_done"] == 200
        assert progress["wins_new"] == 120
    finally:
        conn.close()


def test_artifact_size_handles_oserror(monkeypatch, progress_dir, db_path):
    """A racy ``stat()`` (file deleted between scan + size) shouldn't
    take the backfill down — we just register the artifact with
    bytes=None."""
    _write_progress_json(progress_dir, "racy.json", {
        "run_id": "racy", "kind": "eval", "status": "completed",
        "started_at": "2026-05-04T10:00:00+00:00",
        "ended_at": "2026-05-04T11:00:00+00:00",
    })

    real_stat = Path.stat
    calls = {"n": 0}

    def flaky_stat(self, *a, **kw):
        # First call from the scan + first call from the heuristic
        # path go through; the next call (artifact registration) blows
        # up. The exact call ordering depends on internal walk order,
        # so we approximate "after a few calls".
        calls["n"] += 1
        if calls["n"] >= 4 and self.name == "racy.json":
            raise OSError("boom")
        return real_stat(self, *a, **kw)

    monkeypatch.setattr(Path, "stat", flaky_stat)
    summary = backfill.backfill_progress_dir(progress_dir, db_path)
    # Still succeeds.
    assert summary.runs_inserted == 1


def test_run_id_defaults_to_filename_stem_when_missing(
    progress_dir, db_path,
):
    """Some early one-off JSONs (e.g. ``baseline.json``) don't carry
    a ``run_id`` field. We default to the filename stem."""
    _write_progress_json(progress_dir, "baseline.json", {
        "kind": "data_gen",
        "status": "completed",
        "started_at": "2026-05-03T04:47:16+00:00",
        "ended_at": "2026-05-03T04:49:09+00:00",
        "n_games_done": 50, "n_games_total": 50,
    })
    summary = backfill.backfill_progress_dir(progress_dir, db_path)
    assert summary.runs_inserted == 1

    conn = runs_db.connect(db_path)
    try:
        run = conn.execute(
            "SELECT run_id FROM runs",
        ).fetchone()
        assert run["run_id"] == "baseline"
    finally:
        conn.close()


def test_orphan_shard_only_synthesizes_parent_once(progress_dir, db_path):
    """Two per-shard JSONs sharing one orphan parent should result in
    a single synthesized parent row (not two), with both shard rows
    attaching."""
    for label in ("local", "macbook"):
        _write_progress_json(
            progress_dir,
            f"twin_orphan_shard_{label}.json", {
                "run_id": f"twin_orphan_shard_{label}",
                "kind": "data_gen",
                "status": "completed",
                "started_at": "2026-05-04T10:00:00+00:00",
            },
        )
    summary = backfill.backfill_progress_dir(progress_dir, db_path)
    assert summary.runs_inserted == 1
    assert summary.shard_rows_upserted == 2

    conn = runs_db.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT shard_label FROM run_progress WHERE run_id = ? "
            "ORDER BY shard_label",
            ("twin_orphan",),
        ).fetchall()
        assert [r["shard_label"] for r in rows] == ["local", "macbook"]
    finally:
        conn.close()


def test_cycle_id_threads_through_as_parent_run_id(progress_dir, db_path):
    """``iterate.py`` writes ``cycle_id`` into child stage JSONs; the
    DB schema's matching column is ``parent_run_id``. Backfill threads
    the value across so the click-through ``cycle_id`` lookup the UI
    needs still works."""
    _write_progress_json(progress_dir, "iter_001_cycle.json", {
        "run_id": "iter_001_cycle", "kind": "cycle",
        "status": "completed",
        "started_at": "2026-05-04T05:00:00+00:00",
        "ended_at": "2026-05-04T07:00:00+00:00",
    })
    _write_progress_json(progress_dir, "iter_001_self_play_v6.json", {
        "run_id": "iter_001_self_play_v6", "kind": "data_gen",
        "status": "completed",
        "started_at": "2026-05-04T05:30:00+00:00",
        "ended_at": "2026-05-04T06:00:00+00:00",
        "cycle_id": "iter_001_cycle",
    })
    backfill.backfill_progress_dir(progress_dir, db_path)

    conn = runs_db.connect(db_path)
    try:
        run = conn.execute(
            "SELECT parent_run_id FROM runs WHERE run_id = ?",
            ("iter_001_self_play_v6",),
        ).fetchone()
        assert run["parent_run_id"] == "iter_001_cycle"
    finally:
        conn.close()


def test_aggregate_exception_caught_and_logged(
    monkeypatch, progress_dir, db_path,
):
    """A failure inside ``_backfill_one_aggregate`` must not abort the
    whole walk — the error is caught, logged in ``summary.errors``,
    and the next file proceeds."""
    _write_progress_json(progress_dir, "good.json", {
        "run_id": "good", "kind": "eval", "status": "completed",
        "started_at": "2026-05-04T10:00:00+00:00",
        "ended_at": "2026-05-04T11:00:00+00:00",
    })
    _write_progress_json(progress_dir, "boom.json", {
        "run_id": "boom", "kind": "eval", "status": "completed",
        "started_at": "2026-05-04T10:00:00+00:00",
        "ended_at": "2026-05-04T11:00:00+00:00",
    })
    real_upsert_progress = backfill._upsert_progress_row

    def flaky(conn, run_id, **kw):
        if run_id == "boom":
            raise RuntimeError("forced upsert failure")
        return real_upsert_progress(conn, run_id, **kw)

    monkeypatch.setattr(backfill, "_upsert_progress_row", flaky)
    summary = backfill.backfill_progress_dir(progress_dir, db_path)
    # The good run still landed; the boom run is in errors.
    assert summary.runs_inserted == 2
    assert any("boom.json" in e for e in summary.errors)


def test_shard_exception_caught_and_logged(
    monkeypatch, progress_dir, db_path,
):
    """Same as above for the per-shard branch of the loop."""
    # Aggregate parent so the shard isn't an orphan.
    _write_progress_json(progress_dir, "p.json", {
        "run_id": "p", "kind": "data_gen", "status": "completed",
        "started_at": "2026-05-04T10:00:00+00:00",
        "ended_at": "2026-05-04T11:00:00+00:00",
    })
    _write_progress_json(progress_dir, "p_shard_x.json", {
        "run_id": "p_shard_x", "kind": "data_gen", "status": "completed",
        "started_at": "2026-05-04T10:00:00+00:00",
        "ended_at": "2026-05-04T11:00:00+00:00",
    })
    real_upsert = backfill._upsert_progress_row

    def flaky(conn, run_id, *, shard_label=None, **kw):
        if shard_label == "x":
            raise RuntimeError("forced shard failure")
        return real_upsert(conn, run_id, shard_label=shard_label, **kw)

    monkeypatch.setattr(backfill, "_upsert_progress_row", flaky)
    summary = backfill.backfill_progress_dir(progress_dir, db_path)
    assert any("p_shard_x.json" in e for e in summary.errors)


def test_progress_dir_path_treated_as_file_returns_error(tmp_path):
    """When the source path exists but is a regular file (not a dir),
    the backfill returns an error rather than crashing in glob."""
    db_path = tmp_path / "runs.db"
    not_a_dir = tmp_path / "actually_a_file"
    not_a_dir.write_text("hi", encoding="utf-8")
    summary = backfill.backfill_progress_dir(not_a_dir, db_path)
    assert any("does not exist" in e for e in summary.errors)


def test_underscore_prefix_keys_filtered_from_extra(progress_dir, db_path):
    """The UI loader stamps internal markers (``_filename``,
    ``_source``) onto JSON payloads. Those shouldn't pollute the DB's
    ``extra_json``."""
    _write_progress_json(progress_dir, "marked.json", {
        "run_id": "marked", "kind": "eval", "status": "completed",
        "started_at": "2026-05-04T10:00:00+00:00",
        "ended_at": "2026-05-04T11:00:00+00:00",
        "_filename": "marked.json",
        "_source": "json",
        "win_rate": 0.5,
    })
    backfill.backfill_progress_dir(progress_dir, db_path)
    conn = runs_db.connect(db_path)
    try:
        progress = conn.execute(
            "SELECT extra_json FROM run_progress "
            "WHERE run_id = ? AND shard_label IS NULL",
            ("marked",),
        ).fetchone()
        extra = json.loads(progress["extra_json"])
        assert "_filename" not in extra
        assert "_source" not in extra
        assert extra["win_rate"] == 0.5
    finally:
        conn.close()
