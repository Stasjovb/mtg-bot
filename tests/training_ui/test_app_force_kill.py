"""Tests for the ``POST /api/runs/<run_id>/force_kill`` endpoint.

Force-kill is the destructive sibling of the clean ``/stop`` button.
``/stop`` writes a sentinel and trusts a live producer to drain;
``/force_kill`` writes the terminal status directly to ``runs.db``
for ZOMBIE runs whose master has died.

These tests pin:

* Force-kill on a ``running`` row flips it to ``killed`` with an
  ``ended_at`` timestamp, drops the straggler-insurance sentinel,
  stamps ``original_status="force_killed"`` on the aggregate
  ``run_progress`` row's ``extra_json``, and surfaces ``forced=true``
  in the response.
* Force-kill on a terminal row (``completed`` / ``failed`` / ``killed``)
  is a no-op: ``forced=false``, the DB and sentinel are NOT touched.
* Force-kill on an unknown ``run_id`` returns 404.
* Force-kill on a child run with a JSON-side ``cycle_id`` targets the
  cycle (matches the ``/stop`` endpoint's cycle-aware behavior). The
  child run's DB row is untouched on the immediate write; child stages
  inherit terminal status on the next backfill pass.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from mtg_bot.cli.runs import backfill as runs_backfill
from mtg_bot.training_ui.app import create_app


class _DBSyncClient:
    """Test-only wrapper: backfills ``progress_dir/*.json`` into the DB
    before every request. Phase 3 removed the request-time backfill
    from the UI; this preserves the old "write JSON, request, observe
    in DB" convenience for the existing force-kill tests."""

    def __init__(self, flask_client, progress_dir: Path):
        self._client = flask_client
        self._progress_dir = progress_dir

    def _refresh(self) -> None:
        try:
            runs_backfill.backfill_progress_dir(
                self._progress_dir, self._progress_dir / "runs.db",
                stale_after_hours=24.0 * 365,
            )
        except Exception:  # noqa: BLE001
            pass

    def __getattr__(self, name):
        attr = getattr(self._client, name)
        if name in ("get", "post", "put", "patch", "delete", "head"):
            def _wrapped(*args, **kwargs):
                self._refresh()
                return attr(*args, **kwargs)
            return _wrapped
        return attr


def _write_run(progress_dir: Path, run_id: str, **fields) -> Path:
    """Drop a synthetic run JSON in ``progress_dir`` with sensible
    defaults; ``fields`` overrides individual keys.

    Tests use this with the ``_DBSyncClient`` wrapper which folds
    JSON files into the colocated runs.db before each request, so
    by the time the force_kill endpoint runs, the row exists in the
    DB with the JSON's ``status``.
    """
    payload = {
        "run_id": run_id,
        "kind": "training",
        "started_at": "2026-05-02T12:00:00+00:00",
        "total_epochs": 30,
        "current_epoch": 15,
        "elapsed_seconds": 60.0,
        "per_epoch_seconds_avg": 2.0,
        "estimated_remaining_seconds": 30.0,
        "train_losses": [0.5, 0.4, 0.3],
        "val_losses": [0.55, 0.45, 0.35],
        "status": "running",
        "git_commit": "abcdef0",
        "notes": "",
    }
    payload.update(fields)
    path = progress_dir / f"{run_id}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.fixture()
def client(tmp_path: Path):
    progress_dir = tmp_path / "training_progress"
    progress_dir.mkdir()
    app = create_app(progress_dir)
    app.config["TESTING"] = True
    return _DBSyncClient(app.test_client(), progress_dir), progress_dir


def _read_db_row(progress_dir: Path, run_id: str) -> dict | None:
    """Read the raw ``runs`` row from the DB. Bypasses the UI's
    JSON-side ``original_status`` shadowing so we can assert on the
    canonical DB status."""
    db_path = progress_dir / "runs.db"
    if not db_path.is_file():
        return None
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,),
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def _read_progress_extra(
    progress_dir: Path, run_id: str,
) -> dict | None:
    """Read the aggregate ``run_progress`` row's ``extra_json``
    decoded as a dict. ``None`` if no row or the column is null."""
    db_path = progress_dir / "runs.db"
    if not db_path.is_file():
        return None
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT extra_json FROM run_progress
            WHERE run_id = ? AND shard_label IS NULL
            """,
            (run_id,),
        ).fetchone()
        if row is None or row["extra_json"] is None:
            return None
        try:
            return json.loads(row["extra_json"])
        except (json.JSONDecodeError, TypeError):
            return None
    finally:
        conn.close()


def test_force_kill_flips_running_row_to_killed(client):
    """The happy path: a stuck ``running`` row in the DB transitions to
    ``killed`` with an ``ended_at`` timestamp, the sentinel file is
    written for insurance, the aggregate ``run_progress`` row's
    ``extra_json`` gains an ``original_status="force_killed"`` marker
    that the UI uses to label the row, and the response carries
    ``forced=true`` with the previous status."""
    c, progress_dir = client
    _write_run(progress_dir, "iter_zombie", status="running")
    res = c.post(
        "/api/runs/iter_zombie/force_kill",
        json={"reason": "zombie-cleanup"},
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    assert body["run_id"] == "iter_zombie"
    assert body["stopped_target"] == "iter_zombie"
    assert body["is_cycle_stop"] is False
    assert body["forced"] is True
    assert body["previous_status"] == "running"
    assert body["sentinel_path"]

    # DB row is now terminal with an ended_at set.
    db_row = _read_db_row(progress_dir, "iter_zombie")
    assert db_row is not None
    assert db_row["status"] == "killed"
    assert db_row["ended_at"] is not None

    # Aggregate progress row carries the force_killed marker.
    extra = _read_progress_extra(progress_dir, "iter_zombie")
    assert extra is not None
    assert extra["original_status"] == "force_killed"

    # Insurance sentinel landed on disk.
    sentinel = progress_dir / ".STOP_iter_zombie"
    assert sentinel.is_file()
    sentinel_body = json.loads(sentinel.read_text(encoding="utf-8"))
    assert sentinel_body["reason"] == "zombie-cleanup"


def test_force_kill_surfaces_as_force_killed_in_api_runs(client):
    """End-to-end: after a force-kill, the next ``/api/runs`` poll
    returns the row with ``status="force_killed"`` (the UI label) and
    not ``killed`` (the raw DB enum). This is what the front-end uses
    to render the distinct badge."""
    c, progress_dir = client
    _write_run(progress_dir, "iter_zombie", status="running")
    c.post("/api/runs/iter_zombie/force_kill")
    listing = c.get("/api/runs").get_json()["runs"]
    by_id = {r["run_id"]: r for r in listing}
    assert by_id["iter_zombie"]["status"] == "force_killed"


def test_force_kill_idempotent_on_completed_row(client):
    """A completed row is already terminal; force-kill must be a no-op
    that returns ``forced=false`` with the existing status, does NOT
    touch the DB row, and does NOT drop a sentinel."""
    c, progress_dir = client
    _write_run(
        progress_dir, "iter_done",
        status="completed",
        ended_at="2026-05-02T12:30:00+00:00",
    )
    # Snapshot the row BEFORE the force-kill so we can prove it didn't
    # mutate. The backfill runs on the first request; trigger it.
    c.get("/api/runs")
    before = _read_db_row(progress_dir, "iter_done")
    assert before is not None
    assert before["status"] == "completed"

    res = c.post("/api/runs/iter_done/force_kill")
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    assert body["forced"] is False
    assert body["previous_status"] == "completed"
    assert body["sentinel_path"] is None

    # DB row unchanged.
    after = _read_db_row(progress_dir, "iter_done")
    assert after == before

    # No sentinel landed.
    assert not (progress_dir / ".STOP_iter_done").is_file()


def test_force_kill_idempotent_on_killed_row(client):
    """Same as the completed case but for an already-killed row, which
    is the more common no-op (a previous force_kill, or the backfill's
    stale-running heuristic). Pin the no-op semantics here too."""
    c, progress_dir = client
    _write_run(
        progress_dir, "iter_already_killed",
        status="killed",
        ended_at="2026-05-02T12:30:00+00:00",
    )
    res = c.post("/api/runs/iter_already_killed/force_kill")
    assert res.status_code == 200
    body = res.get_json()
    assert body["forced"] is False
    assert body["previous_status"] == "killed"


def test_force_kill_404_for_unknown_run(client):
    c, _ = client
    res = c.post("/api/runs/no-such-run/force_kill")
    assert res.status_code == 404


def test_force_kill_targets_cycle_when_child_has_cycle_id(client):
    """A child run carrying a ``cycle_id`` back-pointer redirects the
    force-kill to the cycle, so the whole iter aborts rather than just
    the in-flight stage. Mirrors the ``/stop`` endpoint's behavior.
    Child stages inherit terminal status on the next backfill pass —
    this test only checks the cycle row.
    """
    c, progress_dir = client
    # Write the cycle row first; the child references it.
    _write_run(
        progress_dir, "iter_cycle_007",
        kind="iterate",
        status="running",
    )
    _write_run(
        progress_dir, "iter_cycle_007_eval_v9_vs_v8",
        kind="eval",
        status="running",
        cycle_id="iter_cycle_007",
    )
    res = c.post(
        "/api/runs/iter_cycle_007_eval_v9_vs_v8/force_kill",
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["forced"] is True
    assert body["stopped_target"] == "iter_cycle_007"
    assert body["is_cycle_stop"] is True

    # Cycle row is now killed; the child remains running in the DB
    # (the next backfill / progress-write will finalize it).
    cycle_row = _read_db_row(progress_dir, "iter_cycle_007")
    assert cycle_row is not None
    assert cycle_row["status"] == "killed"

    # Sentinel landed on the cycle, NOT the child.
    assert (progress_dir / ".STOP_iter_cycle_007").is_file()
    assert not (
        progress_dir / ".STOP_iter_cycle_007_eval_v9_vs_v8"
    ).is_file()

    # The cycle's aggregate progress row gains the force_killed marker.
    extra = _read_progress_extra(progress_dir, "iter_cycle_007")
    assert extra is not None
    assert extra["original_status"] == "force_killed"


def test_force_kill_handles_empty_body(client):
    """The UI may POST without a body — endpoint must not 400 on empty
    body / missing JSON content-type. Mirrors the /stop endpoint's
    contract."""
    c, progress_dir = client
    _write_run(progress_dir, "iter_zombie", status="running")
    res = c.post("/api/runs/iter_zombie/force_kill")
    assert res.status_code == 200
    body = res.get_json()
    assert body["forced"] is True


def test_index_html_contains_force_kill_button_scaffolding(client):
    """Force-kill button + modal markup and JS are rendered into the
    page so the front-end can wire them without an extra fetch.
    Mirrors the existing ``test_index_html_contains_stop_button_scaffolding``
    pin for the clean Stop variant.
    """
    c, _ = client
    body = c.get("/").get_data(as_text=True)
    # CSS class for the new button + the destructive-confirm pill.
    assert 'class="force-kill-btn"' in body
    assert ".btn-confirm-force-kill" in body
    # Modal markup.
    assert 'id="force-kill-modal"' in body
    assert 'id="force-kill-modal-confirm"' in body
    # JS entry point.
    assert "showForceKillModal" in body
    # Distinct badge styling for force_killed status.
    assert ".badge.force_killed" in body


def test_force_kill_creates_aggregate_progress_row_when_absent(
    tmp_path: Path,
):
    """If the DB has a ``runs`` row but no aggregate ``run_progress``
    row yet (legitimate state during the brief window between
    ``insert_run`` and the first ``upsert_progress``), force-kill must
    INSERT a fresh row carrying only the ``original_status`` marker.
    The UI uses that row to surface the ``force_killed`` label.
    """
    progress_dir = tmp_path / "training_progress"
    progress_dir.mkdir()
    # Hand-write a runs row + skip the progress row entirely.
    from mtg_bot.cli.runs import db as runs_db_mod
    from mtg_bot.cli.runs.models import Run
    db_path = progress_dir / "runs.db"
    conn = runs_db_mod.connect(db_path)
    try:
        runs_db_mod.insert_run(conn, Run(
            run_id="iter_no_progress",
            kind="training",
            status="running",
            started_at="2026-05-02T12:00:00+00:00",
            ended_at=None,
            git_commit="abcdef0",
            config_json="{}",
            parent_run_id=None,
            label=None,
            notes=None,
        ))
    finally:
        conn.close()

    app = create_app(progress_dir)
    app.config["TESTING"] = True
    c = app.test_client()
    res = c.post("/api/runs/iter_no_progress/force_kill")
    assert res.status_code == 200
    body = res.get_json()
    assert body["forced"] is True

    # Aggregate row exists post-force-kill with the marker.
    extra = _read_progress_extra(progress_dir, "iter_no_progress")
    assert extra is not None
    assert extra["original_status"] == "force_killed"


def _write_db_only_run(
    progress_dir: Path, run_id: str, status: str = "running",
    extra_json: str | None = None,
) -> None:
    """Seed a runs.db row WITHOUT writing a matching JSON file. This
    bypasses the request-time backfill (which would re-upsert progress
    from the JSON and clobber any extra_json we plant) so the test can
    pin the force-kill endpoint's tolerance for malformed extra_json
    columns the producer might have written before our codec hardened.
    """
    from mtg_bot.cli.runs import db as runs_db_mod
    from mtg_bot.cli.runs.models import (
        ProgressUpdate as _ProgressUpdate, Run as _Run,
    )
    db_path = progress_dir / "runs.db"
    conn = runs_db_mod.connect(db_path)
    try:
        runs_db_mod.insert_run(conn, _Run(
            run_id=run_id, kind="training", status=status,
            started_at="2026-05-02T12:00:00+00:00", ended_at=None,
            git_commit="abcdef0", config_json="{}",
            parent_run_id=None, label=None, notes=None,
        ))
        runs_db_mod.upsert_progress(conn, _ProgressUpdate(
            run_id=run_id, shard_label=None,
            n_games_done=None, n_games_total=None,
            elapsed_seconds=None, crashed=None, timed_out=None,
            wins_new=None, wins_old=None, draws=None,
            extra_json=extra_json,
        ))
    finally:
        conn.close()


def test_force_kill_tolerates_malformed_extra_json(tmp_path: Path):
    """A producer that wrote garbage into ``extra_json`` must not
    crash force-kill. We swallow the decode error and replace the
    column with a clean dict carrying just the ``original_status``
    marker. DB-only seed (no JSON file) so the request-time backfill
    can't restore the broken value before we assert.
    """
    progress_dir = tmp_path / "training_progress"
    progress_dir.mkdir()
    _write_db_only_run(
        progress_dir, "iter_garbage",
        status="running", extra_json="{not json",
    )
    app = create_app(progress_dir)
    app.config["TESTING"] = True
    c = app.test_client()
    res = c.post("/api/runs/iter_garbage/force_kill")
    assert res.status_code == 200
    assert res.get_json()["forced"] is True
    extra = _read_progress_extra(progress_dir, "iter_garbage")
    assert extra == {"original_status": "force_killed"}


def test_force_kill_tolerates_non_dict_extra_json(tmp_path: Path):
    """A JSON-decodable but non-dict ``extra_json`` (legacy producer
    that wrote a bare array) is treated as if the field were empty —
    force-kill replaces it with a clean dict carrying the marker.
    Pins the parallel ``isinstance(extra, dict)`` branch.
    """
    progress_dir = tmp_path / "training_progress"
    progress_dir.mkdir()
    _write_db_only_run(
        progress_dir, "iter_array_extra",
        status="running", extra_json="[1, 2, 3]",
    )
    app = create_app(progress_dir)
    app.config["TESTING"] = True
    c = app.test_client()
    c.post("/api/runs/iter_array_extra/force_kill")
    extra = _read_progress_extra(progress_dir, "iter_array_extra")
    assert extra == {"original_status": "force_killed"}


def test_force_kill_preserves_existing_extra_json_keys(client):
    """Force-kill merges ``original_status`` into the existing
    ``extra_json``; it must NOT clobber sibling keys the backfill or
    the producer already wrote (e.g. ``machines``, ``train_losses``,
    ``replays_dir``)."""
    c, progress_dir = client
    _write_run(
        progress_dir, "iter_zombie",
        kind="data_gen",
        status="running",
        machines=[{"label": "host", "n_games_done": 1, "n_workers": 4}],
        replays_dir="/tmp/replays/iter_zombie",
    )
    # Force the backfill so ``extra_json`` is populated before we
    # mutate it.
    c.get("/api/runs")
    c.post("/api/runs/iter_zombie/force_kill")
    extra = _read_progress_extra(progress_dir, "iter_zombie")
    assert extra is not None
    assert extra["original_status"] == "force_killed"
    # Sibling keys survive.
    assert extra.get("replays_dir") == "/tmp/replays/iter_zombie"
    assert extra.get("machines")[0]["label"] == "host"
