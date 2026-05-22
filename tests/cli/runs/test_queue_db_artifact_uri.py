"""Tests for the ``results.artifact_uri`` column added in the
coord-async-storage refactor.

Two surfaces:

1. Migration: existing DBs (pre-refactor schema without the
   column) gain the column via ``apply_schema``.
2. ``record_report`` accepts an optional ``artifact_uri`` kwarg
   and persists it on the results row.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from mtg_bot.cli.runs import queue_db


def _legacy_results_schema_only() -> str:
    """The ``results`` table CREATE statement as it was BEFORE this
    refactor -- no ``artifact_uri`` column. The other tables
    (stages / claims / queued_games) are unchanged by the
    refactor, so we let ``queue_db.connect`` build them; only the
    legacy ``results`` table needs the manual create-then-migrate
    dance to prove the column gets added.
    """
    return """
    DROP TABLE IF EXISTS results;
    CREATE TABLE results (
        stage_id TEXT NOT NULL, game_idx INTEGER NOT NULL,
        claim_id TEXT NOT NULL, outcome TEXT NOT NULL,
        winner INTEGER, n_samples INTEGER, duration_s REAL,
        shard_label TEXT, wins_new INTEGER, wins_old INTEGER,
        draws INTEGER, crashed INTEGER, timed_out INTEGER,
        npz_path TEXT, replay_path TEXT, reported_at TEXT NOT NULL,
        PRIMARY KEY (stage_id, game_idx)
    );
    """


def _seed_claim(conn: sqlite3.Connection, *, claim_id: str,
                stage_id: str, game_idx: int) -> None:
    """Insert a minimal (stage, claim) pair so ``record_report``
    can find the claim and write the result row. Matches the real
    queue_db schema (stages.{kind, claim_ttl_seconds, status,
    started_at} are all NOT NULL)."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO stages (stage_id, kind, spec_json, "
        " claim_ttl_seconds, status, started_at) "
        "VALUES (?, 'self_play', '{}', 1200, 'running', ?)",
        (stage_id, now),
    )
    conn.execute(
        "INSERT INTO claims (claim_id, stage_id, game_idx, "
        " worker_id, claimed_at, expires_at) "
        "VALUES (?, ?, ?, 'w1', ?, ?)",
        (claim_id, stage_id, game_idx, now, now),
    )
    conn.commit()


# ---- Migration ----------------------------------------------------------


def test_migration_adds_artifact_uri_to_legacy_results(tmp_path: Path):
    # Use queue_db.connect to land the modern schema (which already
    # has artifact_uri), then DROP + re-CREATE the legacy results
    # table without the column. apply_schema should re-add it via
    # the migration path.
    db = tmp_path / "queue.db"
    conn = queue_db.connect(db)
    conn.executescript(_legacy_results_schema_only())
    conn.commit()
    cols = {row[1] for row in conn.execute("PRAGMA table_info(results)")}
    assert "artifact_uri" not in cols  # pre-condition
    queue_db.apply_schema(conn)
    cols_after = {
        row[1] for row in conn.execute("PRAGMA table_info(results)")
    }
    assert "artifact_uri" in cols_after
    conn.close()


def test_migration_is_idempotent_on_already_migrated_db(tmp_path: Path):
    # Running apply_schema twice on a fresh DB doesn't raise
    # (which would happen if the migration added the column
    # unconditionally without the PRAGMA check).
    db = tmp_path / "queue.db"
    conn = queue_db.connect(db)
    queue_db.apply_schema(conn)  # second call
    queue_db.apply_schema(conn)  # third call for good measure
    cols = {row[1] for row in conn.execute("PRAGMA table_info(results)")}
    assert "artifact_uri" in cols
    conn.close()


# ---- record_report persists artifact_uri --------------------------------


def test_record_report_persists_artifact_uri(tmp_path: Path):
    conn = queue_db.connect(tmp_path / "queue.db")
    _seed_claim(conn, claim_id="c1", stage_id="s1", game_idx=0)
    outcome = queue_db.record_report(
        conn,
        claim_id="c1",
        report_meta={
            "outcome": "completed",
            "winner": 0,
            "n_samples": 42,
            "shard_label": "w1",
        },
        npz_path=str(tmp_path / "s1_w1_c1.npz"),
        replay_path=None,
        artifact_uri="s3://mtg-bot-artifacts-630589799985/s1/w1/c1.npz",
    )
    assert outcome == "accepted"
    row = conn.execute(
        "SELECT artifact_uri FROM results WHERE claim_id = 'c1'",
    ).fetchone()
    assert row[0] == (
        "s3://mtg-bot-artifacts-630589799985/s1/w1/c1.npz"
    )
    conn.close()


def test_record_report_artifact_uri_defaults_to_null(tmp_path: Path):
    # Back-compat: existing callers that don't pass artifact_uri
    # land NULL in the column rather than crashing.
    conn = queue_db.connect(tmp_path / "queue.db")
    _seed_claim(conn, claim_id="c2", stage_id="s2", game_idx=0)
    queue_db.record_report(
        conn,
        claim_id="c2",
        report_meta={"outcome": "completed", "shard_label": "w1"},
        npz_path=None,
        replay_path=None,
    )
    row = conn.execute(
        "SELECT artifact_uri FROM results WHERE claim_id = 'c2'",
    ).fetchone()
    assert row[0] is None
    conn.close()
