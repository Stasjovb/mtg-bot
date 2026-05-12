"""Tests for the additive ``runs`` columns landed in
``feature/runs-db-schema-additions``: ``pid``, ``host``,
``training_history_json``, ``last_progress_at``, ``stop_requested``.

Covers:

- Fresh-DB bootstrap: every new column is present after the first
  ``connect`` call.
- Idempotency: re-running ``apply_schema`` on a DB that already has
  the columns does not error and does not blow away existing rows.
- The "old DB needs migration" path: build a DB with the pre-addition
  schema (CREATE TABLE without the new columns + seed a row), then
  call ``apply_schema`` and confirm the columns are added and the
  seeded row survives (and gets sensible defaults).
- ``insert_run`` round-trips every new column.
- ``upsert_progress`` stamps ``runs.last_progress_at`` in the same
  transaction.
- ``set_stop_requested`` flips the flag and is idempotent.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from mtg_bot.cli.runs import db as runs_db
from mtg_bot.cli.runs.models import ProgressUpdate, Run


def _fresh_db(tmp_path: Path) -> Path:
    return tmp_path / "runs.db"


def _make_run(run_id: str = "r1", **overrides) -> Run:
    base = dict(
        run_id=run_id,
        kind="eval",
        status="running",
        started_at="2026-05-11T12:00:00+00:00",
        git_commit="abc1234",
        config_json=json.dumps({"games": 10}),
    )
    base.update(overrides)
    return Run(**base)


# ---- fresh-DB bootstrap ----------------------------------------------------


def test_fresh_db_has_new_columns(tmp_path):
    """A brand-new DB should have every additive column on ``runs``."""
    conn = runs_db.connect(_fresh_db(tmp_path))
    try:
        cols = {
            r["name"] for r in conn.execute("PRAGMA table_info(runs)")
        }
        assert {
            "pid",
            "host",
            "training_history_json",
            "last_progress_at",
            "stop_requested",
        } <= cols
    finally:
        conn.close()


def test_stop_requested_default_is_zero(tmp_path):
    """Brand-new rows that don't pass ``stop_requested`` should land
    with the DEFAULT 0 — the column is NOT NULL on a fresh CREATE."""
    db_path = _fresh_db(tmp_path)
    conn = runs_db.connect(db_path)
    try:
        runs_db.insert_run(conn, _make_run("r1"))
        row = conn.execute(
            "SELECT stop_requested FROM runs WHERE run_id = 'r1'"
        ).fetchone()
        assert row["stop_requested"] == 0
    finally:
        conn.close()


# ---- migration idempotency -------------------------------------------------


def test_apply_schema_twice_is_idempotent(tmp_path):
    """Re-running apply_schema on an already-current DB is a no-op:
    no error, no duplicate column, no row loss."""
    db_path = _fresh_db(tmp_path)
    conn = runs_db.connect(db_path)
    try:
        runs_db.insert_run(conn, _make_run("r1"))
        runs_db.apply_schema(conn)
        runs_db.apply_schema(conn)
        # Row still here.
        cnt = conn.execute(
            "SELECT COUNT(*) AS c FROM runs"
        ).fetchone()["c"]
        assert cnt == 1
        # No duplicate columns.
        names = [
            r["name"] for r in conn.execute("PRAGMA table_info(runs)")
        ]
        assert len(names) == len(set(names))
    finally:
        conn.close()


# ---- pre-addition schema migration -----------------------------------------


# The pre-addition CREATE TABLE — exactly the shape ``main`` had
# before this slice. Used to build a "legacy" DB and prove the
# ALTER-TABLE migration adds the missing columns without losing rows.
_PRE_ADDITION_RUNS_DDL = """
CREATE TABLE runs (
    run_id        TEXT PRIMARY KEY,
    kind          TEXT NOT NULL CHECK(kind IN
                  ('iterate','self_play','eval','bench','capture','training')),
    status        TEXT NOT NULL CHECK(status IN
                  ('running','completed','failed','killed')),
    started_at    TEXT NOT NULL,
    ended_at      TEXT,
    git_commit    TEXT NOT NULL,
    config_json   TEXT NOT NULL,
    parent_run_id TEXT REFERENCES runs(run_id),
    label         TEXT,
    notes         TEXT
);
"""


def _build_legacy_db(db_path: Path) -> None:
    """Build a runs.db with the pre-addition ``runs`` schema (just
    the columns that existed before this slice). Companion tables
    use the modern schema since they're unaffected by this slice."""
    raw = sqlite3.connect(str(db_path))
    raw.row_factory = sqlite3.Row
    raw.executescript(_PRE_ADDITION_RUNS_DDL)
    # Seed a row so we can prove migration preserves data.
    raw.execute(
        """
        INSERT INTO runs(
            run_id, kind, status, started_at, git_commit,
            config_json, label, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "legacy1", "eval", "running",
            "2026-05-10T12:00:00+00:00", "deadbee",
            '{"games": 1}', "old-eval", "from before the migration",
        ),
    )
    raw.commit()
    raw.close()


def test_migration_adds_new_columns_to_legacy_db(tmp_path):
    """The classic upgrade path: an existing DB built with the
    pre-addition schema gets the new columns on the first ``connect``
    after the upgrade. The seeded row survives and shows NULL /
    default values for the new columns."""
    db_path = _fresh_db(tmp_path)
    _build_legacy_db(db_path)

    # Before migration: legacy column set only.
    raw = sqlite3.connect(str(db_path))
    cols_before = {r[1] for r in raw.execute("PRAGMA table_info(runs)")}
    raw.close()
    assert "pid" not in cols_before
    assert "stop_requested" not in cols_before

    # Connect via the package — triggers apply_schema +
    # _apply_runs_column_migrations.
    conn = runs_db.connect(db_path)
    try:
        cols_after = {
            r["name"] for r in conn.execute("PRAGMA table_info(runs)")
        }
        assert {
            "pid", "host", "training_history_json",
            "last_progress_at", "stop_requested",
        } <= cols_after

        # Existing row preserved.
        row = conn.execute(
            "SELECT * FROM runs WHERE run_id = 'legacy1'"
        ).fetchone()
        assert row is not None
        assert row["label"] == "old-eval"
        assert row["notes"] == "from before the migration"
        # New columns: NULL (or 0 default for stop_requested).
        assert row["pid"] is None
        assert row["host"] is None
        assert row["training_history_json"] is None
        assert row["last_progress_at"] is None
        # ALTER TABLE ADD COLUMN ... DEFAULT 0 lands rows at 0.
        assert row["stop_requested"] == 0
    finally:
        conn.close()


def test_migration_is_idempotent_on_legacy_db(tmp_path):
    """Calling apply_schema multiple times after the legacy DB has
    been upgraded should be a no-op (no duplicate ALTER errors)."""
    db_path = _fresh_db(tmp_path)
    _build_legacy_db(db_path)

    conn = runs_db.connect(db_path)
    try:
        # Call apply_schema several more times — should never error.
        runs_db.apply_schema(conn)
        runs_db.apply_schema(conn)
        runs_db.apply_schema(conn)
        # The legacy row is still there.
        cnt = conn.execute(
            "SELECT COUNT(*) AS c FROM runs"
        ).fetchone()["c"]
        assert cnt == 1
    finally:
        conn.close()


# ---- insert_run round-trips the new columns --------------------------------


def test_insert_run_round_trips_pid_host(tmp_path):
    db_path = _fresh_db(tmp_path)
    conn = runs_db.connect(db_path)
    try:
        runs_db.insert_run(
            conn,
            _make_run("r1", pid=12345, host="desktop-j05412i"),
        )
        rec = runs_db.get_run(conn, "r1")
        assert rec["run"]["pid"] == 12345
        assert rec["run"]["host"] == "desktop-j05412i"
    finally:
        conn.close()


def test_insert_run_round_trips_training_history_json(tmp_path):
    db_path = _fresh_db(tmp_path)
    conn = runs_db.connect(db_path)
    try:
        history = json.dumps({
            "train_losses": [1.0, 0.5, 0.25],
            "val_losses": [1.1, 0.6, 0.3],
        })
        runs_db.insert_run(
            conn,
            _make_run("r1", training_history_json=history),
        )
        rec = runs_db.get_run(conn, "r1")
        assert json.loads(rec["run"]["training_history_json"]) == {
            "train_losses": [1.0, 0.5, 0.25],
            "val_losses": [1.1, 0.6, 0.3],
        }
    finally:
        conn.close()


def test_insert_run_round_trips_stop_requested_true(tmp_path):
    """Passing ``stop_requested=True`` explicitly stores it as 1."""
    db_path = _fresh_db(tmp_path)
    conn = runs_db.connect(db_path)
    try:
        runs_db.insert_run(
            conn,
            _make_run("r1", stop_requested=True),
        )
        rec = runs_db.get_run(conn, "r1")
        assert rec["run"]["stop_requested"] == 1
    finally:
        conn.close()


# ---- last_progress_at auto-stamping ----------------------------------------


def test_upsert_progress_stamps_last_progress_at(tmp_path):
    """Every ``upsert_progress`` call should update
    ``runs.last_progress_at`` to the same timestamp used for the
    ``run_progress`` row."""
    db_path = _fresh_db(tmp_path)
    conn = runs_db.connect(db_path)
    try:
        runs_db.insert_run(conn, _make_run("r1"))
        # Before any progress push, last_progress_at is NULL.
        rec = runs_db.get_run(conn, "r1")
        assert rec["run"]["last_progress_at"] is None

        # Stamp via an explicit updated_at to make the assertion exact.
        runs_db.upsert_progress(
            conn,
            ProgressUpdate(
                run_id="r1", n_games_done=1,
                updated_at="2026-05-11T12:34:56+00:00",
            ),
        )
        rec = runs_db.get_run(conn, "r1")
        assert rec["run"]["last_progress_at"] == "2026-05-11T12:34:56+00:00"

        # A later push moves the timestamp forward.
        runs_db.upsert_progress(
            conn,
            ProgressUpdate(
                run_id="r1", n_games_done=2,
                updated_at="2026-05-11T13:00:00+00:00",
            ),
        )
        rec = runs_db.get_run(conn, "r1")
        assert rec["run"]["last_progress_at"] == "2026-05-11T13:00:00+00:00"
    finally:
        conn.close()


def test_upsert_progress_per_shard_also_stamps_last_progress_at(tmp_path):
    """The per-shard branch (non-NULL shard_label) must stamp
    ``runs.last_progress_at`` too — both branches go through the
    same `runs UPDATE`."""
    db_path = _fresh_db(tmp_path)
    conn = runs_db.connect(db_path)
    try:
        runs_db.insert_run(conn, _make_run("r1"))
        runs_db.upsert_progress(
            conn,
            ProgressUpdate(
                run_id="r1", shard_label="desktop",
                n_games_done=7,
                updated_at="2026-05-11T14:00:00+00:00",
            ),
        )
        rec = runs_db.get_run(conn, "r1")
        assert rec["run"]["last_progress_at"] == "2026-05-11T14:00:00+00:00"
    finally:
        conn.close()


def test_upsert_progress_auto_now_when_no_updated_at(tmp_path):
    """When the caller doesn't pass ``updated_at``, the db layer
    fills it in via ``now_iso()`` — and the same value lands in
    ``runs.last_progress_at``."""
    db_path = _fresh_db(tmp_path)
    conn = runs_db.connect(db_path)
    try:
        runs_db.insert_run(conn, _make_run("r1"))
        runs_db.upsert_progress(
            conn,
            ProgressUpdate(run_id="r1", n_games_done=3),
        )
        rec = runs_db.get_run(conn, "r1")
        # The same timestamp is shared by both row writes within the
        # transaction.
        progress_ts = rec["progress"][0]["updated_at"]
        assert rec["run"]["last_progress_at"] == progress_ts
        # Sanity: ISO-shaped.
        assert "T" in progress_ts
    finally:
        conn.close()


# ---- set_stop_requested ----------------------------------------------------


def test_set_stop_requested_flips_to_true(tmp_path):
    db_path = _fresh_db(tmp_path)
    conn = runs_db.connect(db_path)
    try:
        runs_db.insert_run(conn, _make_run("r1"))
        rec = runs_db.get_run(conn, "r1")
        assert rec["run"]["stop_requested"] == 0

        runs_db.set_stop_requested(conn, "r1")
        rec = runs_db.get_run(conn, "r1")
        assert rec["run"]["stop_requested"] == 1
    finally:
        conn.close()


def test_set_stop_requested_can_clear(tmp_path):
    """``value=False`` clears the flag (useful for producer ACK)."""
    db_path = _fresh_db(tmp_path)
    conn = runs_db.connect(db_path)
    try:
        runs_db.insert_run(conn, _make_run("r1", stop_requested=True))
        rec = runs_db.get_run(conn, "r1")
        assert rec["run"]["stop_requested"] == 1

        runs_db.set_stop_requested(conn, "r1", value=False)
        rec = runs_db.get_run(conn, "r1")
        assert rec["run"]["stop_requested"] == 0
    finally:
        conn.close()


def test_set_stop_requested_idempotent(tmp_path):
    """Calling set_stop_requested twice with the same value is a no-op
    after the first call — no errors, flag stays where it was."""
    db_path = _fresh_db(tmp_path)
    conn = runs_db.connect(db_path)
    try:
        runs_db.insert_run(conn, _make_run("r1"))
        runs_db.set_stop_requested(conn, "r1", value=True)
        runs_db.set_stop_requested(conn, "r1", value=True)
        rec = runs_db.get_run(conn, "r1")
        assert rec["run"]["stop_requested"] == 1
    finally:
        conn.close()


def test_set_stop_requested_on_missing_run_silent(tmp_path):
    """Setting the flag on a non-existent run_id is a silent no-op
    (zero rows updated) — no exception."""
    db_path = _fresh_db(tmp_path)
    conn = runs_db.connect(db_path)
    try:
        # Should not raise.
        runs_db.set_stop_requested(conn, "no-such-run")
    finally:
        conn.close()
