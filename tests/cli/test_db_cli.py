"""Tests for the ``mtg_bot db`` CLI dispatcher.

The ``backup`` and ``dump`` actions delegate to
:mod:`mtg_bot.cli.runs.backup`, which has its own coverage in
``tests/cli/runs/test_backup.py``. The tests here pin:

- The ``query`` action's SELECT-only guard (the operator-facing
  escape hatch).
- The dispatcher routing (each action lands in the right helper).
- Output formatting (``--format json`` vs ``--format tsv``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mtg_bot.cli import db as cli_db
from mtg_bot.cli.runs import db as runs_db
from mtg_bot.cli.runs.models import Event, ProgressUpdate, Run


def _seed_db(db_path: Path) -> None:
    conn = runs_db.connect(db_path)
    try:
        runs_db.insert_run(
            conn,
            Run(
                run_id="r1", kind="eval", status="running",
                started_at="2026-05-06T12:00:00+00:00",
                git_commit="abc1234", config_json="{}",
                label="lbl",
            ),
        )
        runs_db.insert_run(
            conn,
            Run(
                run_id="r2", kind="bench", status="running",
                started_at="2026-05-06T12:01:00+00:00",
                git_commit="abc1234", config_json="{}",
            ),
        )
        runs_db.upsert_progress(
            conn,
            ProgressUpdate(run_id="r1", n_games_done=10),
        )
        runs_db.insert_event(
            conn, Event(run_id="r1", event_type="started"),
        )
    finally:
        conn.close()


# ---- is_safe_select / run_query --------------------------------------------


@pytest.mark.parametrize("sql", [
    "SELECT * FROM runs",
    "select run_id from runs where status = 'running'",
    "  SELECT 1",
    "SELECT * FROM runs;",  # trailing semi OK
])
def test_is_safe_select_accepts_pure_selects(sql):
    assert cli_db.is_safe_select(sql) is True


@pytest.mark.parametrize("sql", [
    "DELETE FROM runs",
    "UPDATE runs SET status='killed'",
    "INSERT INTO runs VALUES (...)",
    "DROP TABLE runs",
    "PRAGMA journal_mode=DELETE",
    "ALTER TABLE runs ADD COLUMN c TEXT",
    "VACUUM",
    # Multi-statement: SELECT followed by something else.
    "SELECT 1; DELETE FROM runs",
])
def test_is_safe_select_rejects_writes(sql):
    assert cli_db.is_safe_select(sql) is False


def test_is_safe_select_rejects_non_select_first(monkeypatch):
    assert cli_db.is_safe_select("WITH foo AS (SELECT 1) SELECT 1") is False


def test_run_query_returns_rows(tmp_path: Path):
    db_path = tmp_path / "runs.db"
    _seed_db(db_path)
    rows = cli_db.run_query(
        db_path, "SELECT run_id, kind FROM runs ORDER BY run_id",
    )
    assert rows == [
        {"run_id": "r1", "kind": "eval"},
        {"run_id": "r2", "kind": "bench"},
    ]


def test_run_query_rejects_writes(tmp_path: Path):
    db_path = tmp_path / "runs.db"
    _seed_db(db_path)
    with pytest.raises(ValueError, match="non-SELECT"):
        cli_db.run_query(db_path, "DELETE FROM runs")


def test_run_query_missing_db_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        cli_db.run_query(tmp_path / "nope.db", "SELECT 1")


# ---- main() dispatch -------------------------------------------------------


def test_main_backup_writes_file(tmp_path: Path, capsys):
    db_path = tmp_path / "runs.db"
    _seed_db(db_path)
    out = tmp_path / "snap.db"
    cli_db.main([
        "backup", "--db", str(db_path), "--out", str(out),
    ])
    assert out.is_file()
    captured = capsys.readouterr().out
    assert "backup ok" in captured
    # Verify the snapshot has the same row count.
    conn = runs_db.connect(out)
    try:
        n = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    finally:
        conn.close()
    assert n == 2


def test_main_backup_default_out_path(tmp_path: Path, capsys, monkeypatch):
    """Without --out, the destination should land under the default
    backup dir with a UTC timestamp suffix. We patch the cwd-based
    default to live under tmp_path so the test doesn't pollute the
    real training_progress dir."""
    db_path = tmp_path / "runs.db"
    _seed_db(db_path)
    backups_dir = tmp_path / "backups"
    monkeypatch.setattr(cli_db, "_DEFAULT_BACKUP_DIR", backups_dir)
    cli_db.main(["backup", "--db", str(db_path)])
    files = sorted(backups_dir.glob("runs.db.*.bak"))
    assert len(files) == 1


def test_main_dump_pretty_prints(tmp_path: Path, capsys):
    db_path = tmp_path / "runs.db"
    _seed_db(db_path)
    cli_db.main([
        "dump", "--db", str(db_path), "--run-id", "r1",
    ])
    out = capsys.readouterr().out
    body = json.loads(out)
    assert body["run"]["run_id"] == "r1"
    assert body["run"]["label"] == "lbl"
    assert len(body["progress"]) == 1
    assert len(body["events"]) == 1


def test_main_query_json(tmp_path: Path, capsys):
    db_path = tmp_path / "runs.db"
    _seed_db(db_path)
    cli_db.main([
        "query", "--db", str(db_path),
        "SELECT run_id, kind FROM runs ORDER BY run_id",
    ])
    rows = json.loads(capsys.readouterr().out)
    assert rows == [
        {"run_id": "r1", "kind": "eval"},
        {"run_id": "r2", "kind": "bench"},
    ]


def test_main_query_tsv(tmp_path: Path, capsys):
    db_path = tmp_path / "runs.db"
    _seed_db(db_path)
    cli_db.main([
        "query", "--db", str(db_path), "--format", "tsv",
        "SELECT run_id, kind FROM runs ORDER BY run_id",
    ])
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "run_id\tkind"
    assert out[1] == "r1\teval"
    assert out[2] == "r2\tbench"


def test_main_query_tsv_empty_result_no_header(tmp_path: Path, capsys):
    db_path = tmp_path / "runs.db"
    _seed_db(db_path)
    cli_db.main([
        "query", "--db", str(db_path), "--format", "tsv",
        "SELECT run_id FROM runs WHERE run_id = 'no-such'",
    ])
    out = capsys.readouterr().out
    assert out == ""


def test_main_query_rejects_write(tmp_path: Path):
    db_path = tmp_path / "runs.db"
    _seed_db(db_path)
    with pytest.raises(ValueError):
        cli_db.main([
            "query", "--db", str(db_path),
            "DELETE FROM runs",
        ])


def test_main_no_action_errors(capsys):
    """``mtg_bot db`` with no sub-action should error via argparse."""
    with pytest.raises(SystemExit):
        cli_db.main([])


# ---- registered with the top-level dispatcher ------------------------------


def test_top_level_dispatcher_includes_db():
    """The top-level ``mtg_bot`` dispatcher must include the new ``db``
    subcommand. Pin so a future restructure doesn't drop it."""
    from mtg_bot import cli as cli_pkg
    assert "db" in cli_pkg._SUBCOMMANDS
    assert cli_pkg._SUBCOMMANDS["db"] == "mtg_bot.cli.db"
    assert "db" in cli_pkg._DESCRIPTIONS


# ---- backfill action -------------------------------------------------------


def test_main_backfill_runs_against_progress_dir(
    tmp_path: Path, capsys,
):
    """``mtg_bot db backfill`` walks the source dir and upserts every
    JSON record into the destination DB."""
    progress_dir = tmp_path / "training_progress"
    progress_dir.mkdir()
    (progress_dir / "v1.json").write_text(
        json.dumps({
            "run_id": "v1", "kind": "training", "status": "completed",
            "started_at": "2026-05-04T10:00:00+00:00",
            "ended_at": "2026-05-04T11:00:00+00:00",
        }),
        encoding="utf-8",
    )
    db_path = tmp_path / "runs.db"
    cli_db.main([
        "backfill", "--db", str(db_path), "--source", str(progress_dir),
    ])
    out = capsys.readouterr().out
    assert "runs inserted" in out
    assert "1" in out
    # Verify the row landed.
    conn = runs_db.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT run_id FROM runs",
        ).fetchall()
        assert [r["run_id"] for r in rows] == ["v1"]
    finally:
        conn.close()


def test_main_backfill_respects_stale_after_hours_flag(
    tmp_path: Path, capsys,
):
    """``--stale-after-hours`` flows through to the backfill helper.
    Pass an absurdly high cutoff so a fresh-mtime running JSON doesn't
    get marked stale."""
    progress_dir = tmp_path / "training_progress"
    progress_dir.mkdir()
    (progress_dir / "still_running.json").write_text(
        json.dumps({
            "run_id": "still_running", "kind": "eval",
            "status": "running",
            "started_at": "2026-05-09T15:00:00+00:00",
        }),
        encoding="utf-8",
    )
    db_path = tmp_path / "runs.db"
    cli_db.main([
        "backfill", "--db", str(db_path),
        "--source", str(progress_dir),
        "--stale-after-hours", "1000",
    ])
    conn = runs_db.connect(db_path)
    try:
        run = conn.execute(
            "SELECT status FROM runs WHERE run_id = ?",
            ("still_running",),
        ).fetchone()
        # Cutoff is so high the heuristic doesn't trigger; row stays
        # ``running``.
        assert run["status"] == "running"
    finally:
        conn.close()
