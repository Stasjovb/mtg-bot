"""SQLite backing store for run records.

One DB file per master, default path
``training_progress/runs.db`` — colocated with the JSON files the UI
already polls. The file is created on first connect; the schema apply
is ``CREATE TABLE IF NOT EXISTS`` so re-running against an existing DB
is idempotent (additive migrations are the only kind we ship in
Phase 1).

Pragmas:

- ``journal_mode=WAL`` — concurrent readers without blocking writers.
  WAL files (``runs.db-wal`` + ``runs.db-shm``) sit alongside the DB
  and survive crashes; ``PRAGMA wal_checkpoint`` (or just an idle
  period) folds them back into the main file.
- ``synchronous=NORMAL`` — flush at txn commit but not on every
  page-write. Trades a tiny crash-recovery exposure (you might lose
  the last commit if the OS power-cycles) for substantially better
  write throughput on the spinning-rust path.
- ``foreign_keys=ON`` — enforce the ``parent_run_id`` /
  ``run_progress.run_id`` / ``run_events.run_id`` references. Off by
  default in SQLite; we want it on so a typo in ``run_id`` fails
  loudly instead of silently writing orphan rows.

The single-writer/multi-reader model is enforced by the REST layer
(serve.py) using a thread lock around all write endpoints. In-process
callers using :mod:`mtg_bot.cli.runs.client`'s direct-SQLite path get
a fresh ``Connection`` per call, which is fine because Python's GIL +
the SQLite library's own internal lock serialize the actual file
writes.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from mtg_bot.cli.runs.models import (
    Artifact, Event, KINDS, ProgressUpdate, Run, STATUSES,
)


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id                TEXT PRIMARY KEY,
    kind                  TEXT NOT NULL CHECK(kind IN
                          ('iterate','self_play','eval','bench','capture','training')),
    status                TEXT NOT NULL CHECK(status IN
                          ('running','completed','failed','killed')),
    started_at            TEXT NOT NULL,
    ended_at              TEXT,
    git_commit            TEXT NOT NULL,
    config_json           TEXT NOT NULL,
    parent_run_id         TEXT REFERENCES runs(run_id),
    label                 TEXT,
    notes                 TEXT,
    pid                   INTEGER,
    host                  TEXT,
    training_history_json TEXT,
    last_progress_at      TEXT,
    stop_requested        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS run_progress (
    run_id          TEXT NOT NULL REFERENCES runs(run_id),
    shard_label     TEXT,
    n_games_done    INTEGER,
    n_games_total   INTEGER,
    elapsed_seconds REAL,
    crashed         INTEGER,
    timed_out       INTEGER,
    wins_new        INTEGER,
    wins_old        INTEGER,
    draws           INTEGER,
    extra_json      TEXT,
    updated_at      TEXT NOT NULL,
    PRIMARY KEY (run_id, shard_label)
);

CREATE TABLE IF NOT EXISTS run_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT NOT NULL REFERENCES runs(run_id),
    shard_label  TEXT,
    event_type   TEXT NOT NULL,
    timestamp    TEXT NOT NULL,
    payload_json TEXT
);

CREATE TABLE IF NOT EXISTS run_artifacts (
    run_id        TEXT NOT NULL REFERENCES runs(run_id),
    artifact_type TEXT NOT NULL,
    path          TEXT NOT NULL,
    bytes         INTEGER,
    created_at    TEXT NOT NULL,
    PRIMARY KEY (run_id, artifact_type, path)
);

CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_kind   ON runs(kind);
CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs(started_at);
CREATE INDEX IF NOT EXISTS idx_events_run ON run_events(run_id, timestamp);
"""


def now_iso() -> str:
    """ISO-8601 UTC second precision; same shape the JSON writers use."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    """Set the WAL + foreign-key pragmas. Called on every fresh
    connection — pragmas don't always persist across connections in
    SQLite (``foreign_keys`` is per-connection; ``journal_mode`` IS
    DB-level and persists)."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")


def _existing_columns(
    conn: sqlite3.Connection, table: str,
) -> set[str]:
    """Names of columns currently in ``table``.

    Used by :func:`_apply_runs_column_migrations` to decide whether
    each additive column already exists. ``PRAGMA table_info(<t>)``
    is read-only and safe to call inside an outer transaction.
    """
    return {
        row["name"] for row in conn.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    }


# Additive column migrations on the ``runs`` table. Each entry is
# ``(column_name, column_ddl)``. ``column_ddl`` is the part that
# follows ``ALTER TABLE runs ADD COLUMN`` — so it includes the type
# and any constant ``DEFAULT``.
#
# SQLite restriction: ``ALTER TABLE ... ADD COLUMN`` cannot add a
# ``NOT NULL`` column without a constant ``DEFAULT`` (existing rows
# need a value). For ``stop_requested`` we want NOT NULL semantics on
# fresh tables (the CREATE TABLE in SCHEMA_SQL has ``NOT NULL DEFAULT
# 0``), but on a pre-existing DB the ALTER path lands the column with
# the same DEFAULT 0 — every old row gets 0 implicitly, and every new
# INSERT either provides a value or falls back to 0. Functionally
# equivalent for callers; the only diff is the column's metadata
# ``notnull`` flag (1 vs 0). We don't rely on that flag anywhere.
_RUNS_ADDITIVE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("pid", "INTEGER"),
    ("host", "TEXT"),
    ("training_history_json", "TEXT"),
    ("last_progress_at", "TEXT"),
    ("stop_requested", "INTEGER NOT NULL DEFAULT 0"),
)


def _apply_runs_column_migrations(conn: sqlite3.Connection) -> None:
    """Idempotently add any missing additive columns to ``runs``.

    Guards each ``ALTER TABLE`` with a ``PRAGMA table_info`` lookup
    so re-running this function on an already-migrated DB is a
    no-op. Existing rows are unaffected: every additive column is
    nullable (or has a constant DEFAULT), so the ALTER produces no
    table rewrite and no row-data churn.
    """
    existing = _existing_columns(conn, "runs")
    for name, ddl in _RUNS_ADDITIVE_COLUMNS:
        if name in existing:
            continue
        conn.execute(f"ALTER TABLE runs ADD COLUMN {name} {ddl}")


def apply_schema(conn: sqlite3.Connection) -> None:
    """Idempotent schema apply. Safe to call on a fresh DB or an
    existing one — every table/index is ``IF NOT EXISTS``, and any
    additive column migrations on the ``runs`` table are guarded by
    a ``PRAGMA table_info`` lookup."""
    conn.executescript(SCHEMA_SQL)
    _apply_runs_column_migrations(conn)
    conn.commit()


def connect(db_path: Path) -> sqlite3.Connection:
    """Open ``db_path`` (creating it if missing), apply pragmas, apply
    schema, return the connection. Caller closes.

    ``isolation_level=None`` puts us in autocommit; we wrap explicit
    multi-statement work in BEGIN ... COMMIT via the
    :func:`transaction` context manager below. That model plays better
    with WAL than the implicit-transaction default.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(db_path),
        isolation_level=None,  # autocommit; explicit BEGIN via transaction()
        check_same_thread=False,  # serve.py uses a write-lock, OK to share
    )
    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn)
    apply_schema(conn)
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Wrap a write batch in BEGIN/COMMIT (or ROLLBACK on exception).

    SQLite begins an implicit deferred transaction on the first write
    in autocommit-ish mode, but explicit BEGIN IMMEDIATE makes the
    semantics obvious AND grabs the write-lock up front so two
    concurrent writers don't both think they're going to succeed and
    then race at COMMIT.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


# ---- low-level upserts -----------------------------------------------------


def insert_run(conn: sqlite3.Connection, run: Run) -> None:
    """Insert a new run row. Raises :class:`sqlite3.IntegrityError` if
    ``run_id`` already exists, ``kind`` / ``status`` is out of the
    allowed set, or ``parent_run_id`` references a non-existent row.
    """
    if run.kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}; got {run.kind!r}")
    if run.status not in STATUSES:
        raise ValueError(
            f"status must be one of {STATUSES}; got {run.status!r}"
        )
    with transaction(conn):
        conn.execute(
            """
            INSERT INTO runs(
                run_id, kind, status, started_at, ended_at,
                git_commit, config_json, parent_run_id, label, notes,
                pid, host, training_history_json, last_progress_at,
                stop_requested
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.run_id, run.kind, run.status, run.started_at,
                run.ended_at, run.git_commit, run.config_json,
                run.parent_run_id, run.label, run.notes,
                run.pid, run.host, run.training_history_json,
                run.last_progress_at,
                1 if run.stop_requested else 0,
            ),
        )


def upsert_progress(
    conn: sqlite3.Connection, update: ProgressUpdate,
) -> None:
    """UPSERT a row in ``run_progress`` keyed by
    ``(run_id, shard_label)``. ``shard_label IS NULL`` matches the
    aggregate row.

    SQLite gotcha: ``ON CONFLICT (run_id, shard_label)`` does NOT
    match a row whose shard_label is NULL — NULLs are treated as
    distinct in unique-index comparisons regardless of SQLite version
    (PEP 670-style "IS NOT DISTINCT FROM" semantics never reached
    SQLite). So inserting an aggregate row with shard_label=NULL
    twice would create two rows. Fix: do explicit DELETE-then-INSERT
    inside the same transaction when shard_label is NULL, and use
    real ON CONFLICT for the per-shard (non-NULL) path. Both branches
    are atomic via the surrounding ``transaction(conn)``.
    """
    updated_at = update.updated_at or now_iso()
    with transaction(conn):
        # Stamp runs.last_progress_at on every push, in the same
        # transaction as the run_progress row write. This makes the
        # "most-recent progress" timestamp readable directly off the
        # runs row — janitor / force-kill code doesn't have to JOIN
        # against run_progress. Update is a no-op if no such run
        # exists (a slightly odd state — push_progress for an
        # unknown run — but we don't want to error here; the
        # existing FK constraint on run_progress.run_id will catch
        # it on the INSERT below).
        conn.execute(
            "UPDATE runs SET last_progress_at = ? WHERE run_id = ?",
            (updated_at, update.run_id),
        )
        if update.shard_label is None:
            conn.execute(
                "DELETE FROM run_progress WHERE run_id = ? "
                "AND shard_label IS NULL",
                (update.run_id,),
            )
            conn.execute(
                """
                INSERT INTO run_progress(
                    run_id, shard_label, n_games_done, n_games_total,
                    elapsed_seconds, crashed, timed_out,
                    wins_new, wins_old, draws, extra_json, updated_at
                ) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    update.run_id,
                    update.n_games_done, update.n_games_total,
                    update.elapsed_seconds,
                    update.crashed, update.timed_out,
                    update.wins_new, update.wins_old, update.draws,
                    update.extra_json, updated_at,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO run_progress(
                    run_id, shard_label, n_games_done, n_games_total,
                    elapsed_seconds, crashed, timed_out,
                    wins_new, wins_old, draws, extra_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, shard_label) DO UPDATE SET
                    n_games_done    = excluded.n_games_done,
                    n_games_total   = excluded.n_games_total,
                    elapsed_seconds = excluded.elapsed_seconds,
                    crashed         = excluded.crashed,
                    timed_out       = excluded.timed_out,
                    wins_new        = excluded.wins_new,
                    wins_old        = excluded.wins_old,
                    draws           = excluded.draws,
                    extra_json      = excluded.extra_json,
                    updated_at      = excluded.updated_at
                """,
                (
                    update.run_id, update.shard_label,
                    update.n_games_done, update.n_games_total,
                    update.elapsed_seconds,
                    update.crashed, update.timed_out,
                    update.wins_new, update.wins_old, update.draws,
                    update.extra_json, updated_at,
                ),
            )


def insert_event(conn: sqlite3.Connection, event: Event) -> None:
    """Append a row to ``run_events``. Always inserts; events are not
    upserted (the ``id`` column is autoincrement)."""
    timestamp = event.timestamp or now_iso()
    with transaction(conn):
        conn.execute(
            """
            INSERT INTO run_events(
                run_id, shard_label, event_type, timestamp, payload_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                event.run_id, event.shard_label,
                event.event_type, timestamp, event.payload_json,
            ),
        )


def upsert_artifact(
    conn: sqlite3.Connection, artifact: Artifact,
) -> None:
    """UPSERT into ``run_artifacts`` keyed by
    ``(run_id, artifact_type, path)``. Re-registering the same
    artifact path is a no-op except for the ``bytes`` + ``created_at``
    columns being refreshed.
    """
    created_at = artifact.created_at or now_iso()
    with transaction(conn):
        conn.execute(
            """
            INSERT INTO run_artifacts(
                run_id, artifact_type, path, bytes, created_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(run_id, artifact_type, path) DO UPDATE SET
                bytes = excluded.bytes,
                created_at = excluded.created_at
            """,
            (
                artifact.run_id, artifact.artifact_type, artifact.path,
                artifact.bytes, created_at,
            ),
        )


def finish_run(
    conn: sqlite3.Connection,
    run_id: str,
    status: str,
    *,
    notes: Optional[str] = None,
    ended_at: Optional[str] = None,
) -> None:
    """Mark a run terminal. ``status`` must be one of completed /
    failed / killed (never 'running' — that's the start state)."""
    if status not in STATUSES or status == "running":
        raise ValueError(
            f"finish_run status must be one of completed/failed/killed; "
            f"got {status!r}"
        )
    ended = ended_at or now_iso()
    with transaction(conn):
        if notes is not None:
            conn.execute(
                """
                UPDATE runs
                SET status = ?, ended_at = ?, notes = ?
                WHERE run_id = ?
                """,
                (status, ended, notes, run_id),
            )
        else:
            conn.execute(
                """
                UPDATE runs
                SET status = ?, ended_at = ?
                WHERE run_id = ?
                """,
                (status, ended, run_id),
            )


def set_stop_requested(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    value: bool = True,
) -> None:
    """Flip the soft ``stop_requested`` flag on ``run_id``.

    The flag is set by the UI's Force-Kill endpoint (or by detecting
    a ``.STOP_<run_id>`` sentinel) and polled by producers so they
    can drain cleanly. Default value is ``True`` — the common case
    is "request a stop"; callers that want to clear the flag (e.g.
    after a producer acknowledges) pass ``value=False`` explicitly.

    Idempotent: flipping a flag that's already in the target state
    is a no-op UPDATE that touches one row's column. No error if
    the row doesn't exist (zero rows updated) — the producer code
    will simply not find the run and stop itself for an unrelated
    reason.
    """
    with transaction(conn):
        conn.execute(
            "UPDATE runs SET stop_requested = ? WHERE run_id = ?",
            (1 if value else 0, run_id),
        )


# ---- read helpers ----------------------------------------------------------


def get_run(
    conn: sqlite3.Connection, run_id: str,
) -> Optional[dict[str, Any]]:
    """Return the run row + its progress rows + last 100 events.
    ``None`` if no such run."""
    row = conn.execute(
        "SELECT * FROM runs WHERE run_id = ?", (run_id,),
    ).fetchone()
    if row is None:
        return None
    progress = [
        dict(r) for r in conn.execute(
            """
            SELECT * FROM run_progress WHERE run_id = ?
            ORDER BY shard_label IS NULL DESC, shard_label
            """,
            (run_id,),
        ).fetchall()
    ]
    events = [
        dict(r) for r in conn.execute(
            """
            SELECT * FROM run_events WHERE run_id = ?
            ORDER BY id DESC LIMIT 100
            """,
            (run_id,),
        ).fetchall()
    ]
    artifacts = [
        dict(r) for r in conn.execute(
            "SELECT * FROM run_artifacts WHERE run_id = ?",
            (run_id,),
        ).fetchall()
    ]
    return {
        "run": dict(row),
        "progress": progress,
        "events": events,
        "artifacts": artifacts,
    }


def list_runs(
    conn: sqlite3.Connection,
    *,
    status: Optional[str] = None,
    kind: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Filtered list of run rows. Newest first by ``started_at``."""
    where: list[str] = []
    params: list[Any] = []
    if status is not None:
        where.append("status = ?")
        params.append(status)
    if kind is not None:
        where.append("kind = ?")
        params.append(kind)
    if since is not None:
        where.append("started_at >= ?")
        params.append(since)
    sql = "SELECT * FROM runs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY started_at DESC LIMIT ?"
    params.append(int(limit))
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


# ---- module-level write lock ----------------------------------------------

# Single in-process write lock. The REST endpoints serialize through
# this; in-process callers share it too so a master that's hosting
# the REST server AND running iterate locally can't deadlock or
# corrupt at the boundary. SQLite's own lock would catch most cases,
# but a Python-side lock makes the contract explicit.
WRITE_LOCK = threading.Lock()


__all__ = [
    "Artifact",
    "Event",
    "ProgressUpdate",
    "Run",
    "SCHEMA_SQL",
    "WRITE_LOCK",
    "apply_schema",
    "connect",
    "finish_run",
    "get_run",
    "insert_event",
    "insert_run",
    "list_runs",
    "now_iso",
    "set_stop_requested",
    "transaction",
    "upsert_artifact",
    "upsert_progress",
]
