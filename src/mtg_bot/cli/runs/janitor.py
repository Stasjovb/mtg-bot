"""Periodic janitor for stale ``running`` rows in ``runs.db``.

Producers register a run with ``status='running'`` at start and call
``finish_run`` at end. If a producer dies between those two — kill -9,
power loss, kernel OOM, hung ProcessPoolExecutor that never returned
— the row stays at ``running`` forever, and the UI keeps rendering it
as if the work is in flight.

Pre-Phase-3 the UI's per-request backfill carried a "stale-running
heuristic" that turned any JSON file with ``status="running"`` and an
mtime older than 6h into ``status="killed"``. With the backfill
gone (UI now reads the DB directly), nothing was demoting stale rows;
they'd accumulate forever. The janitor restores that responsibility.

Mechanics
---------
The janitor wakes every ``interval_seconds`` and runs:

.. code-block:: sql

    UPDATE runs
    SET status = 'killed',
        ended_at = <now-iso>,
        notes = COALESCE(notes || ' | ', '')
              || 'janitor: stale running (last_progress_at < ' || ? || ')'
    WHERE status = 'running'
      AND COALESCE(last_progress_at, started_at) < ?

``last_progress_at`` is the freshest signal — every ``push_progress``
call stamps it inside the same transaction as the per-row insert (see
``upsert_progress`` in ``mtg_bot.cli.runs.db``). When it's NULL
(producer registered but never pushed progress — a very early death
or a kind that genuinely doesn't push progress, e.g. a 30-second
bench), we fall back to ``started_at`` so a real death doesn't
escape the heuristic.

The default stale threshold is 6 hours — well beyond any single
producer stage's expected wall time (longest is the eval phase at
~2000 games × 30s = ~17h on the cluster, but eval pushes progress
roughly every minute via per-shard flushes, so its
``last_progress_at`` advances continuously). A run that's actually
still working but hasn't pushed in 6 hours is broken in some other
way and should be flagged anyway.

The janitor is best-effort — exceptions are logged once per tick
and swallowed so a bad DB state can't kill the serve process. Idempotent
because the WHERE clause excludes rows that are already terminal.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Optional

from mtg_bot.cli.runs import db as runs_db


DEFAULT_INTERVAL_SECONDS = 5 * 60       # 5 minutes
DEFAULT_STALE_AFTER_HOURS = 6.0         # 6 hours


def run_once(
    db_path: Path,
    *,
    stale_after_hours: float = DEFAULT_STALE_AFTER_HOURS,
    now_iso_fn=runs_db.now_iso,
) -> int:
    """Run a single janitor sweep against ``db_path``. Returns the
    number of rows that got demoted to ``status='killed'``.

    Best-effort: if the DB file is missing or unreadable, returns 0
    rather than raising — the caller (a daemon timer in
    ``run_forever``) shouldn't crash on a transient failure.

    Threshold semantics: a row is stale if
    ``COALESCE(last_progress_at, started_at)`` is older than
    ``stale_after_hours`` ago. Pure ``last_progress_at`` would let
    a producer that died BEFORE its first push_progress live forever
    (the column is NULL); the COALESCE fallback to ``started_at``
    plugs that gap.

    Uses SQLite's ``datetime('now', '-Nh')`` literal so the comparison
    happens server-side (no Python-side timestamp math). The
    threshold-as-fractional-hours is rounded to seconds in the SQL —
    sub-second precision is meaningless for this heuristic anyway.
    """
    db_path = Path(db_path)
    if not db_path.is_file():
        return 0
    try:
        conn = runs_db.connect(db_path)
    except Exception:  # noqa: BLE001
        return 0
    try:
        # SQLite parses ``datetime('now', '-Nh')`` server-side. We use
        # seconds rather than hours so fractional stale thresholds (e.g.
        # 0.1h in tests) work correctly.
        stale_seconds = int(stale_after_hours * 3600.0)
        offset_clause = f"-{stale_seconds} seconds"
        ended = now_iso_fn()
        with runs_db.transaction(conn):
            # ``datetime()`` normalizes both sides of the comparison:
            # producers stamp ISO 8601 with a ``T`` separator and a
            # ``+00:00`` UTC offset (``datetime.now(timezone.utc)
            # .isoformat(timespec='seconds')``); SQLite's
            # ``datetime('now')`` emits ``YYYY-MM-DD HH:MM:SS`` with a
            # space and no offset. A naive lexical compare fails
            # (``'T'`` > ``' '`` ASCII-wise). Wrapping both sides in
            # ``datetime()`` parses each to the canonical
            # space-separated UTC shape so the comparison works.
            cur = conn.execute(
                """
                UPDATE runs
                SET status = 'killed',
                    ended_at = ?,
                    notes = CASE
                        WHEN notes IS NULL OR notes = ''
                        THEN ?
                        ELSE notes || ' | ' || ?
                    END
                WHERE status = 'running'
                  AND datetime(COALESCE(last_progress_at, started_at))
                      < datetime('now', ?)
                """,
                (
                    ended,
                    f"janitor: stale running ({stale_after_hours:g}h)",
                    f"janitor: stale running ({stale_after_hours:g}h)",
                    offset_clause,
                ),
            )
            return cur.rowcount or 0
    finally:
        conn.close()


class JanitorThread:
    """Daemon thread that ticks the janitor every
    ``interval_seconds``. Started by ``mtg_bot serve`` when the
    run-DB endpoints are enabled; stopped on process exit (daemon
    bit handles cleanup).

    Errors per tick are caught + printed to stderr (one line) so a
    transient DB issue can't crash the serve process. The thread
    itself keeps ticking after errors.
    """

    def __init__(
        self,
        db_path: Path,
        *,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
        stale_after_hours: float = DEFAULT_STALE_AFTER_HOURS,
    ) -> None:
        self._db_path = Path(db_path)
        self._interval_seconds = float(interval_seconds)
        self._stale_after_hours = float(stale_after_hours)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_marked: int = 0

    @property
    def last_marked(self) -> int:
        """How many rows the last sweep demoted. Tests use this as
        a side-channel signal; nothing in production reads it."""
        return self._last_marked

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name=f"runs-db-janitor[{self._db_path.name}]",
            daemon=True,
        )
        self._thread.start()

    def stop(self, *, timeout: Optional[float] = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _loop(self) -> None:
        # First sweep fires immediately; subsequent sweeps wait the
        # full interval. This means a freshly-started server clears
        # stale rows within seconds rather than waiting N minutes.
        first = True
        while True:
            if not first and self._stop_event.wait(self._interval_seconds):
                return
            first = False
            try:
                marked = run_once(
                    self._db_path,
                    stale_after_hours=self._stale_after_hours,
                )
                self._last_marked = marked
                if marked > 0:
                    print(
                        f"[runs.janitor] marked {marked} stale "
                        f"running rows as killed",
                        file=sys.stderr,
                    )
            except Exception as exc:  # noqa: BLE001
                # Best-effort: log once and keep going. The next tick
                # will retry; the run-DB endpoints don't depend on the
                # janitor for correctness.
                print(
                    f"[runs.janitor] WARNING: sweep failed: "
                    f"{type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )


__all__ = [
    "DEFAULT_INTERVAL_SECONDS",
    "DEFAULT_STALE_AFTER_HOURS",
    "JanitorThread",
    "run_once",
]
