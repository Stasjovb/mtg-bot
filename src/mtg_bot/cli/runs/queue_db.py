"""SQLite-backed coordinator state for the v2 REST contract.

Separate file from ``runs.db`` so the two stores can be backed up /
inspected / nuked independently. Default path is
``<progress_dir>/coordinator_state/queue.db`` — colocated with the
existing JSON files.

Tables (see ``docs/DISTRIBUTED_API_v2.md`` and
``docs/DISTRIBUTED_RUN_FLOW.md`` for the contract):

- ``stages``        — one row per ``POST /v2/stage/create``. Holds the
                      full stage spec as JSON plus status + lifecycle
                      timestamps.
- ``queued_games``  — claimable backlog. One row per game per stage;
                      rows get DELETED on claim. (Re-queue on
                      TTL-expiry / DEAD-worker re-INSERTs.)
- ``claims``        — every in-flight or completed claim. Carries
                      ``worker_id``, ``claimed_at``, ``expires_at``,
                      ``reported`` (0/1) and the JSON of the report
                      payload. Acts as the idempotency table.
- ``results``       — final results, one per (stage_id, game_idx).
                      Sourced from the claim's report payload and the
                      filesystem-resident artifact paths.

Pragmas: ``journal_mode=WAL`` for concurrent readers,
``synchronous=FULL`` because a lost claim or report is much worse
than a few ms of latency on the coordinator's write path. The
coordinator is single-master — no cluster-wide replication is needed.

The module is intentionally schema-first and helper-thin: callers
(the v2 endpoint blueprint) compose SQL via small typed functions on
top of a single :func:`connect` factory. Mirrors the
``mtg_bot.cli.runs.db`` style.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional


# Module-level write lock used by REST handlers in ``serve.py`` so
# concurrent POSTs from many workers don't race the single SQLite
# writer. (WAL gives us concurrent *readers* for free; writers still
# serialize.)
WRITE_LOCK = threading.Lock()


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS stages (
    stage_id            TEXT PRIMARY KEY,
    kind                TEXT NOT NULL CHECK(kind IN ('self_play','eval')),
    spec_json           TEXT NOT NULL,
    claim_ttl_seconds   INTEGER NOT NULL,
    status              TEXT NOT NULL CHECK(status IN
                        ('queued','running','drained','complete')),
    started_at          TEXT NOT NULL,
    drained_at          TEXT,
    complete_at         TEXT
);

CREATE TABLE IF NOT EXISTS queued_games (
    stage_id            TEXT NOT NULL REFERENCES stages(stage_id),
    game_idx            INTEGER NOT NULL,
    deck_indices_json   TEXT NOT NULL,
    seed                INTEGER NOT NULL,
    PRIMARY KEY (stage_id, game_idx)
);

CREATE TABLE IF NOT EXISTS claims (
    claim_id            TEXT PRIMARY KEY,
    stage_id            TEXT NOT NULL REFERENCES stages(stage_id),
    game_idx            INTEGER NOT NULL,
    worker_id           TEXT NOT NULL,
    claimed_at          TEXT NOT NULL,
    expires_at          TEXT NOT NULL,
    reported            INTEGER NOT NULL DEFAULT 0,
    report_json         TEXT
);

CREATE TABLE IF NOT EXISTS results (
    stage_id            TEXT NOT NULL REFERENCES stages(stage_id),
    game_idx            INTEGER NOT NULL,
    claim_id            TEXT NOT NULL,
    outcome             TEXT NOT NULL,
    winner              INTEGER,
    n_samples           INTEGER,
    duration_s          REAL,
    shard_label         TEXT,
    wins_new            INTEGER,
    wins_old            INTEGER,
    draws               INTEGER,
    crashed             INTEGER,
    timed_out           INTEGER,
    npz_path            TEXT,
    replay_path         TEXT,
    -- artifact_uri records the original drop-off URI the worker
    -- gave us (e.g. ``s3://mtg-bot-artifacts/...`` or
    -- ``file:///tank/share/...``). When the coord's async fetcher
    -- succeeds, npz_path/replay_path point at the local rehydrated
    -- copies AND artifact_uri remembers the source for a manual
    -- ``mtg_bot db retry-fetch`` if the local copy is later lost.
    -- When the fetcher fails after retries, npz_path/replay_path
    -- stay NULL and the row is marked ``outcome='upload_failed'``
    -- with artifact_uri set so the operator can investigate.
    artifact_uri        TEXT,
    reported_at         TEXT NOT NULL,
    PRIMARY KEY (stage_id, game_idx)
);

CREATE INDEX IF NOT EXISTS idx_claims_stage     ON claims(stage_id);
CREATE INDEX IF NOT EXISTS idx_claims_worker    ON claims(worker_id);
CREATE INDEX IF NOT EXISTS idx_claims_expires   ON claims(expires_at);
CREATE INDEX IF NOT EXISTS idx_queued_stage     ON queued_games(stage_id);
CREATE INDEX IF NOT EXISTS idx_results_stage    ON results(stage_id);
"""


def now_iso() -> str:
    """ISO-8601 UTC second precision; matches ``runs.db``'s format."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    """WAL + FULL fsync + foreign keys. ``synchronous=FULL`` is stricter
    than ``runs.db`` (which uses NORMAL) — the coordinator's claim/
    report path is the durability boundary for the whole cluster, so
    we trade a bit of throughput for "the write you saw the 200 for
    survives an immediate power loss."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")


def apply_schema(conn: sqlite3.Connection) -> None:
    """Idempotent schema apply. Safe on a fresh or existing DB."""
    conn.executescript(SCHEMA_SQL)
    _migrate_add_artifact_uri(conn)
    conn.commit()


def _migrate_add_artifact_uri(conn: sqlite3.Connection) -> None:
    """Add the ``results.artifact_uri`` column to pre-existing DBs.

    SQLite's ``CREATE TABLE IF NOT EXISTS`` does not back-fill new
    columns on already-existing tables — only fresh DBs pick the
    column up from the CREATE statement. We probe ``PRAGMA
    table_info`` and ``ALTER TABLE`` if absent. Idempotent: a fresh
    DB already has the column (from SCHEMA_SQL) and the probe is a
    no-op.
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(results)")}
    if "artifact_uri" not in cols:
        conn.execute("ALTER TABLE results ADD COLUMN artifact_uri TEXT")


def connect(db_path: Path) -> sqlite3.Connection:
    """Open ``db_path`` (creating its parent dir if missing), apply
    pragmas + schema, return the connection. Caller closes."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(db_path),
        isolation_level=None,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn)
    apply_schema(conn)
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Wrap a block in BEGIN IMMEDIATE / COMMIT. Rolls back on
    exception. ``BEGIN IMMEDIATE`` grabs the writer lock right away,
    so concurrent transactions on this conn serialize cleanly."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


# ---- stages ----------------------------------------------------------------


def insert_stage(
    conn: sqlite3.Connection,
    *,
    stage_id: str,
    kind: str,
    spec_json: str,
    claim_ttl_seconds: int,
    games: list[dict[str, Any]],
) -> None:
    """Persist a fresh stage + its queued games in one transaction.

    ``games`` is the list of ``{game_idx, deck_indices, seed}`` dicts
    from the orchestrator's POST body.

    Empty stages (``games == []``) are inserted and IMMEDIATELY
    transitioned to ``complete`` via :func:`_maybe_auto_close_stage` —
    a stage with zero work is "naturally drained" the instant it's
    created, so the orchestrator's polling loop sees ``complete`` on
    the very next ``GET /v2/stage/<id>``. (Empty stages are a
    degenerate but legal corner of the contract — see the doc note
    on ``POST /v2/stage/create``.)
    """
    started_at = now_iso()
    with transaction(conn):
        conn.execute(
            "INSERT INTO stages "
            "(stage_id, kind, spec_json, claim_ttl_seconds, status, started_at) "
            "VALUES (?, ?, ?, ?, 'running', ?)",
            (stage_id, kind, spec_json, claim_ttl_seconds, started_at),
        )
        conn.executemany(
            "INSERT INTO queued_games "
            "(stage_id, game_idx, deck_indices_json, seed) "
            "VALUES (?, ?, ?, ?)",
            [
                (
                    stage_id,
                    int(g["game_idx"]),
                    json.dumps(list(g["deck_indices"])),
                    int(g["seed"]),
                )
                for g in games
            ],
        )
    # n_games_total == 0 is auto-complete on creation; the check is
    # cheap for the populated case (one COUNT(*) on an empty results
    # table) so we run it unconditionally.
    _maybe_auto_close_stage(conn, stage_id)


def get_stage(
    conn: sqlite3.Connection, stage_id: str,
) -> Optional[sqlite3.Row]:
    """Return the ``stages`` row for ``stage_id`` or None if missing."""
    return conn.execute(
        "SELECT * FROM stages WHERE stage_id = ?",
        (stage_id,),
    ).fetchone()


def mark_drained(conn: sqlite3.Connection, stage_id: str) -> bool:
    """Flip the stage's status to ``drained`` and set ``drained_at``.

    Idempotent on a stage that's already ``drained`` or ``complete``
    (no change, returns True). Returns False if the stage doesn't
    exist. Also DELETEs all remaining ``queued_games`` rows for the
    stage — once drained, new claims should never see them.
    """
    drained_at = now_iso()
    with transaction(conn):
        row = conn.execute(
            "SELECT status FROM stages WHERE stage_id = ?",
            (stage_id,),
        ).fetchone()
        if row is None:
            return False
        if row["status"] in ("drained", "complete"):
            return True
        conn.execute(
            "UPDATE stages SET status='drained', drained_at=? "
            "WHERE stage_id = ?",
            (drained_at, stage_id),
        )
        conn.execute(
            "DELETE FROM queued_games WHERE stage_id = ?",
            (stage_id,),
        )
    _maybe_auto_close_stage(conn, stage_id)
    return True


def _maybe_auto_close_stage(
    conn: sqlite3.Connection, stage_id: str,
) -> None:
    """Auto-transition the stage to ``complete`` if the work is done.

    Two ways a stage can be "done":

    1. **Natural drain** (status == ``running``): every ``game_idx``
       in the spec has a row in ``results`` AND no claims are still
       in-flight (unreported but not yet TTL-expired). This is the
       primary auto-close path; it fires the moment the last
       in-flight game's result lands in ``/v2/report_result``.
    2. **Explicit close** (status == ``drained``): the orchestrator
       already called ``/v2/stage/<id>/close``, which DELETEs the
       residual queued games. Once the in-flight claims drain to 0,
       the stage transitions to ``complete`` regardless of whether
       ``n_done`` reached ``n_total`` — the dropped queued work was
       intentionally abandoned. (This preserves the pre-auto-close
       behavior of :func:`mark_drained` + the eval-watcher
       early-stop path.)

    "Done" in the natural-drain accounting is purely table-driven —
    abandoned tombstones (``reported=1`` with
    ``report_json={"abandoned":true}``) do NOT contribute to
    ``n_done``. They mark *claims* that were re-queued; the game
    itself was either re-claimed and successfully reported by
    another worker (in which case there IS a results row) or is
    still queued / in-flight (no results row yet, and the stage
    isn't done). Counting per-results-row makes this precise:
    "every ``game_idx`` has at least one result row." Matches the
    :func:`stage_counters` ``n_games_done`` semantic, so auto-close
    fires at exactly the moment the stage view would already show
    "all done."

    Called after every operation that could move a stage toward
    done: :func:`insert_stage` (handles the degenerate
    ``n_games_total == 0`` case), :func:`mark_drained` (path #2
    above; the existing explicit-close path), and
    :func:`record_report` (path #1; the natural-drain path that
    this module's auto-close exists for).

    Idempotent — if status is already ``complete`` (or no such
    stage), returns without touching the row. Safe to call from
    inside or outside an outer transaction; the UPDATE runs as its
    own auto-commit statement.
    """
    row = conn.execute(
        "SELECT status, spec_json FROM stages WHERE stage_id = ?",
        (stage_id,),
    ).fetchone()
    if row is None or row["status"] == "complete":
        return
    in_flight = conn.execute(
        "SELECT COUNT(*) AS c FROM claims "
        "WHERE stage_id = ? AND reported = 0",
        (stage_id,),
    ).fetchone()["c"]
    if in_flight > 0:
        return
    if row["status"] == "drained":
        # Explicit-close path: queued work was intentionally
        # abandoned by ``mark_drained``; once in-flight clears, the
        # stage is done regardless of ``n_done`` vs ``n_total``.
        pass
    else:
        # Natural-drain path: only flip when EVERY game has a result.
        # Total games come from the persisted spec (cheaper than a
        # COUNT over queued+claimed+done, and matches the
        # stage_counters ``n_games_total`` semantic).
        spec = json.loads(row["spec_json"])
        n_total = len(spec.get("games", []))
        n_done = conn.execute(
            "SELECT COUNT(*) AS c FROM results WHERE stage_id = ?",
            (stage_id,),
        ).fetchone()["c"]
        if n_done < n_total:
            return
    conn.execute(
        "UPDATE stages SET status='complete', complete_at=? "
        "WHERE stage_id = ?",
        (now_iso(), stage_id),
    )


# Back-compat alias for the narrow "only-flip-when-drained" name used
# pre-stage-auto-close. New code should call ``_maybe_auto_close_stage``
# directly; this thunk exists so any in-flight import paths keep
# resolving during the transition.
_maybe_mark_complete = _maybe_auto_close_stage


# ---- claims ----------------------------------------------------------------


def claim_next_game(
    conn: sqlite3.Connection,
    *,
    stage_id: str,
    worker_id: str,
    now_unix: float,
) -> Optional[dict[str, Any]]:
    """Atomically pop one queued game for ``stage_id`` and record a
    claim. Returns ``{claim_id, game_idx, deck_indices, seed,
    expires_at}`` on success, or ``None`` if the stage is drained /
    complete / empty.

    Caller is responsible for first checking whether the stage exists
    (returns ``None`` here too, which the caller can't distinguish
    from "empty queue").
    """
    with transaction(conn):
        stage = conn.execute(
            "SELECT status, claim_ttl_seconds FROM stages "
            "WHERE stage_id = ?",
            (stage_id,),
        ).fetchone()
        if stage is None:
            return None
        if stage["status"] in ("drained", "complete"):
            return None
        row = conn.execute(
            "SELECT game_idx, deck_indices_json, seed "
            "FROM queued_games WHERE stage_id = ? "
            "ORDER BY game_idx ASC LIMIT 1",
            (stage_id,),
        ).fetchone()
        if row is None:
            return None
        game_idx = int(row["game_idx"])
        deck_indices = json.loads(row["deck_indices_json"])
        seed = int(row["seed"])
        ttl = int(stage["claim_ttl_seconds"])
        expires_unix = now_unix + ttl
        expires_iso = datetime.fromtimestamp(
            expires_unix, tz=timezone.utc,
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        claimed_iso = datetime.fromtimestamp(
            now_unix, tz=timezone.utc,
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        claim_id = f"{stage_id}:{game_idx:06d}"
        conn.execute(
            "DELETE FROM queued_games WHERE stage_id = ? AND game_idx = ?",
            (stage_id, game_idx),
        )
        # Idempotency on the claim_id PRIMARY KEY: if a previous
        # claim with the same id was reported and the game was re-
        # queued via TTL-expiry, we generate a *new* claim_id with
        # an attempt suffix. Detect the collision by SELECT first.
        existing = conn.execute(
            "SELECT 1 FROM claims WHERE claim_id = ?",
            (claim_id,),
        ).fetchone()
        if existing is not None:
            # Re-claim after re-queue: append a unique suffix using
            # the current unix timestamp (sub-second resolution is
            # fine for this — re-claims for the same game_idx are
            # rare and serialized through WRITE_LOCK anyway).
            claim_id = f"{stage_id}:{game_idx:06d}:{int(now_unix * 1000)}"
        conn.execute(
            "INSERT INTO claims "
            "(claim_id, stage_id, game_idx, worker_id, claimed_at, "
            " expires_at, reported) "
            "VALUES (?, ?, ?, ?, ?, ?, 0)",
            (
                claim_id, stage_id, game_idx, worker_id,
                claimed_iso, expires_iso,
            ),
        )
        return {
            "claim_id": claim_id,
            "game_idx": game_idx,
            "deck_indices": deck_indices,
            "seed": seed,
            "expires_at": expires_iso,
        }


def get_claim(
    conn: sqlite3.Connection, claim_id: str,
) -> Optional[sqlite3.Row]:
    """Return the ``claims`` row for ``claim_id`` or None."""
    return conn.execute(
        "SELECT * FROM claims WHERE claim_id = ?",
        (claim_id,),
    ).fetchone()


def list_claims_for_worker(
    conn: sqlite3.Connection, worker_id: str,
) -> list[sqlite3.Row]:
    """Return all unreported claims currently held by ``worker_id``."""
    return list(conn.execute(
        "SELECT * FROM claims WHERE worker_id = ? AND reported = 0",
        (worker_id,),
    ).fetchall())


def record_report(
    conn: sqlite3.Connection,
    *,
    claim_id: str,
    report_meta: dict[str, Any],
    npz_path: Optional[str],
    replay_path: Optional[str],
    artifact_uri: Optional[str] = None,
) -> str:
    """Mark ``claim_id`` reported and write the matching ``results``
    row. Returns one of:

    - ``"accepted"`` — fresh on-time report, results row created.
    - ``"duplicate"`` — claim was already reported; on-time duplicate
      (silent 200 in the REST layer).
    - ``"conflict"`` — claim no longer exists in the table, or it was
      already reported by a re-delivered claim_id — late duplicate
      (409 in the REST layer).
    - ``"unknown"`` — no such claim_id in the table.

    The caller's REST handler maps these to HTTP status codes.
    """
    reported_at = now_iso()
    with transaction(conn):
        claim = conn.execute(
            "SELECT * FROM claims WHERE claim_id = ?",
            (claim_id,),
        ).fetchone()
        if claim is None:
            return "unknown"
        stage_id = claim["stage_id"]
        game_idx = int(claim["game_idx"])
        if claim["reported"] == 1:
            # Distinguish two sub-cases:
            #  (a) abandoned tombstone left by requeue_claim — the
            #      worker that's reporting now is a zombie whose work
            #      was reassigned. Return "conflict" so the REST
            #      layer 409s.
            #  (b) genuine on-time duplicate retry — silent 200.
            report_json = claim["report_json"]
            if report_json:
                try:
                    parsed = json.loads(report_json)
                    if isinstance(parsed, dict) and parsed.get("abandoned"):
                        return "conflict"
                except json.JSONDecodeError:
                    pass
            return "duplicate"
        # Has another claim for the same (stage_id, game_idx) already
        # written a result? That's the "re-delivered, finished
        # elsewhere, late report" case → 409.
        existing_result = conn.execute(
            "SELECT 1 FROM results WHERE stage_id = ? AND game_idx = ?",
            (stage_id, game_idx),
        ).fetchone()
        if existing_result is not None:
            return "conflict"
        outcome = report_meta.get("outcome", "completed")
        crashed = 1 if outcome == "crashed" else 0
        timed_out = 1 if outcome == "timed_out" else 0
        winner = report_meta.get("winner")
        n_samples = report_meta.get("n_samples")
        duration_s = report_meta.get("duration_s")
        shard_label = report_meta.get("shard_label")
        wins_new = report_meta.get("wins_new")
        wins_old = report_meta.get("wins_old")
        draws = report_meta.get("draws")
        conn.execute(
            "INSERT INTO results "
            "(stage_id, game_idx, claim_id, outcome, winner, n_samples, "
            " duration_s, shard_label, wins_new, wins_old, draws, "
            " crashed, timed_out, npz_path, replay_path, artifact_uri, "
            " reported_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                stage_id, game_idx, claim_id, outcome, winner, n_samples,
                duration_s, shard_label, wins_new, wins_old, draws,
                crashed, timed_out, npz_path, replay_path, artifact_uri,
                reported_at,
            ),
        )
        conn.execute(
            "UPDATE claims SET reported = 1, report_json = ? "
            "WHERE claim_id = ?",
            (json.dumps(report_meta), claim_id),
        )
    # Auto-close fires the moment the last in-flight game reports,
    # whether or not the orchestrator ever called /v2/stage/<id>/close.
    # The check is fast (two COUNT(*)s on stage-indexed tables) and
    # idempotent, so we run it after every result write.
    _maybe_auto_close_stage(conn, stage_id)
    return "accepted"


def requeue_claim(
    conn: sqlite3.Connection,
    claim_id: str,
) -> bool:
    """Mark a claim as "abandoned" and put its game back in the queue.

    Used by:
    - the startup TTL-expiry sweep (``requeue_expired_claims``);
    - the HeartbeatPoller's DEAD-worker handler.

    The old claim row stays in the table (with ``reported`` left at
    ``0`` and an extra ``report_json`` value of ``{"abandoned":
    true}``) so the late-duplicate detection in :func:`record_report`
    can tell "this claim_id existed but was re-delivered to someone
    else" from "this claim_id was never issued" (404). The next call
    to :func:`claim_next_game` for the same ``game_idx`` picks the
    game up under a *new* claim_id (the collision check in that
    function appends a ms-timestamp suffix on the second issuance).

    Idempotent: a claim that's already reported is NOT re-queued.
    Returns True when the game went back to the queue, False when
    nothing happened (already reported / unknown claim).
    """
    with transaction(conn):
        claim = conn.execute(
            "SELECT * FROM claims WHERE claim_id = ?",
            (claim_id,),
        ).fetchone()
        if claim is None:
            return False
        if claim["reported"] == 1:
            return False
        stage_id = claim["stage_id"]
        game_idx = int(claim["game_idx"])
        # Look up the original deck_indices + seed from the spec.
        # (We don't store them per-claim; cheaper to re-derive from
        # the stage spec than to denormalize.)
        stage = conn.execute(
            "SELECT spec_json, status FROM stages WHERE stage_id = ?",
            (stage_id,),
        ).fetchone()
        if stage is None:
            return False
        # Don't re-queue if stage is drained — the orchestrator told
        # us to abandon residual work. Mark the claim abandoned in
        # place; do NOT delete (so a late report still 409s rather
        # than 404s).
        if stage["status"] in ("drained", "complete"):
            conn.execute(
                "UPDATE claims SET report_json = ? WHERE claim_id = ?",
                (json.dumps({"abandoned": True}), claim_id),
            )
            return False
        spec = json.loads(stage["spec_json"])
        games = spec.get("games", [])
        match = None
        for g in games:
            if int(g["game_idx"]) == game_idx:
                match = g
                break
        if match is None:
            return False
        # Tombstone the old claim row so late reports under the same
        # claim_id can be detected as conflicts (vs the 404 path,
        # which is "this id was never issued"). We mark reported=1
        # with a synthetic report_json so the on-claim duplicate
        # check fires before the (stage_id, game_idx) results check.
        conn.execute(
            "UPDATE claims SET reported = 1, report_json = ? "
            "WHERE claim_id = ?",
            (json.dumps({"abandoned": True}), claim_id),
        )
        # Insert back into queued_games. Use INSERT OR IGNORE in case
        # of a race with another requeue path.
        conn.execute(
            "INSERT OR IGNORE INTO queued_games "
            "(stage_id, game_idx, deck_indices_json, seed) "
            "VALUES (?, ?, ?, ?)",
            (
                stage_id, game_idx,
                json.dumps(list(match["deck_indices"])),
                int(match["seed"]),
            ),
        )
    return True


def requeue_expired_claims(
    conn: sqlite3.Connection,
    now_unix: Optional[float] = None,
) -> int:
    """Scan ``claims`` for unreported rows with ``expires_at < now``
    and re-queue them. Returns the count re-queued.

    Called on coordinator startup (recovery path) — see
    ``docs/DISTRIBUTED_RUN_FLOW.md`` "Coordinator crashes mid-stage."
    """
    now_unix = now_unix if now_unix is not None else time.time()
    now_iso_str = datetime.fromtimestamp(
        now_unix, tz=timezone.utc,
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    expired = list(conn.execute(
        "SELECT claim_id FROM claims "
        "WHERE reported = 0 AND expires_at < ?",
        (now_iso_str,),
    ).fetchall())
    count = 0
    for row in expired:
        if requeue_claim(conn, row["claim_id"]):
            count += 1
    return count


# ---- aggregate counters ----------------------------------------------------


def stage_counters(
    conn: sqlite3.Connection, stage_id: str,
) -> Optional[dict[str, Any]]:
    """Build the response shape for ``GET /v2/stage/<stage_id>``.

    Returns ``None`` if the stage doesn't exist.
    """
    stage = conn.execute(
        "SELECT * FROM stages WHERE stage_id = ?",
        (stage_id,),
    ).fetchone()
    if stage is None:
        return None
    spec = json.loads(stage["spec_json"])
    n_total = len(spec.get("games", []))
    n_queued = conn.execute(
        "SELECT COUNT(*) AS c FROM queued_games WHERE stage_id = ?",
        (stage_id,),
    ).fetchone()["c"]
    n_in_flight = conn.execute(
        "SELECT COUNT(*) AS c FROM claims "
        "WHERE stage_id = ? AND reported = 0",
        (stage_id,),
    ).fetchone()["c"]
    agg = conn.execute(
        "SELECT COUNT(*) AS n_done, "
        "       SUM(COALESCE(wins_new, 0))    AS wins_new, "
        "       SUM(COALESCE(wins_old, 0))    AS wins_old, "
        "       SUM(COALESCE(draws, 0))       AS draws, "
        "       SUM(crashed)                  AS crashed, "
        "       SUM(timed_out)                AS timed_out, "
        "       SUM(COALESCE(n_samples, 0))   AS n_samples, "
        "       SUM(COALESCE(duration_s, 0))  AS total_duration_s "
        "FROM results WHERE stage_id = ?",
        (stage_id,),
    ).fetchone()
    n_done = int(agg["n_done"] or 0)
    if stage["kind"] == "eval":
        wins_new = int(agg["wins_new"] or 0)
        wins_old = int(agg["wins_old"] or 0)
    else:
        wins_new = None
        wins_old = None

    # ---- Per-worker breakdown -------------------------------------------
    # Two sources to merge:
    #   1. ``results.shard_label``: workers that have reported at least one
    #      finished game (carries n_samples + duration + crashed/timed_out).
    #   2. ``claims.worker_id``: workers that have claimed but not yet
    #      reported any game (surfaces machines warming up before their
    #      first report lands so the UI shows them immediately).
    per_shard_done = conn.execute(
        "SELECT shard_label,                                              "
        "       COUNT(*)                            AS n_games_done,      "
        "       SUM(COALESCE(n_samples, 0))         AS n_samples,         "
        "       SUM(COALESCE(wins_new, 0))          AS wins_new,          "
        "       SUM(COALESCE(wins_old, 0))          AS wins_old,          "
        "       SUM(COALESCE(draws, 0))             AS draws,             "
        "       SUM(crashed)                        AS crashed,           "
        "       SUM(timed_out)                      AS timed_out,         "
        "       SUM(COALESCE(duration_s, 0))        AS total_duration_s   "
        "FROM results WHERE stage_id = ? AND shard_label IS NOT NULL      "
        "GROUP BY shard_label",
        (stage_id,),
    ).fetchall()
    per_shard_inflight = conn.execute(
        "SELECT worker_id AS shard_label, COUNT(*) AS n_in_flight "
        "FROM claims "
        "WHERE stage_id = ? AND reported = 0 "
        "GROUP BY worker_id",
        (stage_id,),
    ).fetchall()
    machines: dict[str, dict[str, Any]] = {}
    for r in per_shard_done:
        label = r["shard_label"]
        machines[label] = {
            "label": label,
            "n_games_done": int(r["n_games_done"] or 0),
            "n_samples": int(r["n_samples"] or 0),
            "n_in_flight": 0,
            "wins_new": int(r["wins_new"] or 0) if stage["kind"] == "eval" else None,
            "wins_old": int(r["wins_old"] or 0) if stage["kind"] == "eval" else None,
            "draws": int(r["draws"] or 0),
            "crashed": int(r["crashed"] or 0),
            "timed_out": int(r["timed_out"] or 0),
            "total_duration_s": float(r["total_duration_s"] or 0.0),
        }
    for r in per_shard_inflight:
        label = r["shard_label"]
        if label not in machines:
            machines[label] = {
                "label": label,
                "n_games_done": 0,
                "n_samples": 0,
                "n_in_flight": 0,
                "wins_new": 0 if stage["kind"] == "eval" else None,
                "wins_old": 0 if stage["kind"] == "eval" else None,
                "draws": 0,
                "crashed": 0,
                "timed_out": 0,
                "total_duration_s": 0.0,
            }
        machines[label]["n_in_flight"] = int(r["n_in_flight"] or 0)
    # Deterministic order so consumers (UI cards, run-DB rows) see a
    # stable shape across polls.
    machines_list = sorted(machines.values(), key=lambda m: m["label"])

    return {
        "stage_id": stage["stage_id"],
        "kind": stage["kind"],
        "status": stage["status"],
        "n_games_total": n_total,
        "n_games_queued": int(n_queued),
        "n_games_in_flight": int(n_in_flight),
        "n_games_done": n_done,
        "n_samples": int(agg["n_samples"] or 0),
        "total_duration_s": float(agg["total_duration_s"] or 0.0),
        "wins_new": wins_new,
        "wins_old": wins_old,
        "draws": int(agg["draws"] or 0),
        "crashed": int(agg["crashed"] or 0),
        "timed_out": int(agg["timed_out"] or 0),
        "started_at": stage["started_at"],
        "drained_at": stage["drained_at"],
        "complete_at": stage["complete_at"],
        "machines": machines_list,
        # Count of distinct machines with any activity (reported OR
        # in-flight) — this is the "Workers" stat on the UI card.
        "n_workers": len(machines_list),
    }


def queue_depths(conn: sqlite3.Connection) -> dict[str, int]:
    """Return ``{stage_id: n_queued_games}`` for all stages with
    non-zero queued counts. Used by ``GET /v2/healthz``."""
    rows = conn.execute(
        "SELECT stage_id, COUNT(*) AS c FROM queued_games "
        "GROUP BY stage_id"
    ).fetchall()
    return {r["stage_id"]: int(r["c"]) for r in rows}
