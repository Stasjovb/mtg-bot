"""Progress sentinel for in-flight games — read by the hang-dump
handler when a per-game timeout fires.

Background: every per-game timeout dumps a faulthandler traceback,
which tells you WHICH FUNCTION the worker thread happened to be in
at the moment the timeout fired. That's a one-frame snapshot — it
doesn't tell you whether the game was

  (a) actually stuck on one decision (a real engine pathology), or
  (b) just slow-but-progressing under a heavily-loaded multiprocessing
      pool (real-world cause: the per-game wallclock budget is too
      tight relative to the standalone game-length distribution and
      MKL/CPU contention scales nonlinearly with worker count).

Empirically (2026-05-04 audit) every dumped "hang" so far has been
case (b): standalone the same (base_seed, game_idx) completes in
1-3 minutes with NO single decision exceeding 4 seconds, but in a
24-worker pool the same game gets squeezed past the 5-min cap.

This module adds a tiny shared sentinel updated by the inner game
loop after every apply(). When the timeout fires, the dump-handler
reads it and writes the per-game progress (decisions completed,
last decision repr, time of last update) into the hang-dump JSON.
That's enough to diagnose case (a) vs (b) at-a-glance the next time
a hang shows up: if ``decisions_completed`` is ~0-5 and the time-since-
last-update is large, it's a real engine hang; if ``decisions_completed``
is in the hundreds and the last update was recent, it's just a slow
game and the user should either raise the budget or reduce the worker
count.

Concurrency: the writer is the inner-game thread (run via
``run_with_timeout``); the reader is the parent thread that fires
the dump after ``TimeoutError``. There's no shared lock — the writes
are simple field assignments (atomic in CPython for a single
attribute) and the reader takes whatever it sees. A torn read is
fine: we'd rather show "decisions_completed=N-1, last_decision=Nth"
than block the worker on a lock.
"""

from __future__ import annotations

import json as _json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class HangProgress:
    """Mutable progress sentinel shared between the inner game thread
    and the timeout handler.

    Fields are deliberately small + shallow-copy-safe — we want the
    snapshot serializable into the hang-dump JSON without any active-
    record gymnastics.

    Heartbeat emission (decisions-zero diagnosis 2026-05-10): when
    ``heartbeat_path`` is set, ``record`` appends a one-line JSON
    heartbeat to that file every ``heartbeat_every_n_decisions``
    decisions **AND** at least ``heartbeat_min_seconds`` after the last
    heartbeat (sparser-of-the-two semantics). This gives the parent
    controller a way to see how far an in-flight game progressed before
    a per-game timeout fired — answering "did the game wedge in its
    first decision, or grind through hundreds of decisions and just
    blow the wall budget?". Disabled by default (``heartbeat_path=None``)
    so existing callers pay nothing.
    """

    started_at: float = field(default_factory=time.perf_counter)
    decisions_completed: int = 0
    last_active_player: Optional[int] = None
    last_decision_repr: str = ""
    last_update_at: float = field(default_factory=time.perf_counter)
    last_n_legal: int = 0

    # Heartbeat config — opt-in via ``heartbeat_path``. Bookkeeping
    # fields track the last emitted heartbeat so the throttle is
    # decision-AND-time-gated.
    heartbeat_path: Optional[Path] = None
    heartbeat_every_n_decisions: int = 50
    heartbeat_min_seconds: float = 5.0
    _last_heartbeat_decisions: int = field(default=0, init=False, repr=False)
    _last_heartbeat_at: float = field(
        default_factory=time.perf_counter, init=False, repr=False,
    )

    def record(
        self,
        active: Optional[int],
        decision: object,
        n_legal: int,
    ) -> None:
        """Called by the inner game loop AFTER each adapter.apply().
        Cost: a few attribute assignments + a repr() call truncated to
        160 chars. Negligible vs decision wallclock (typical 100ms-3s)
        and the worker is already in this hot loop's overhead so no
        new allocations on the steady-state path."""
        self.decisions_completed += 1
        self.last_active_player = active
        # Truncate repr to keep dumps small + avoid surprising ``repr``
        # dispatch on rare object types. 160 chars is enough for any
        # realistic Decision dataclass.
        try:
            r = repr(decision)
        except Exception:  # noqa: BLE001 - intentional broad catch
            r = "<unrepr-able>"
        self.last_decision_repr = r[:160]
        self.last_n_legal = n_legal
        now = time.perf_counter()
        self.last_update_at = now
        # Heartbeat throttle: only emit when BOTH "N decisions since
        # last emit" AND "K seconds since last emit" have elapsed.
        # User spec called for "the sparser of N=50 / K=5s" — sparser
        # rate ⇔ longer interval ⇔ AND of the two thresholds.
        if self.heartbeat_path is not None:
            decisions_since = (
                self.decisions_completed - self._last_heartbeat_decisions
            )
            seconds_since = now - self._last_heartbeat_at
            if (
                decisions_since >= self.heartbeat_every_n_decisions
                and seconds_since >= self.heartbeat_min_seconds
            ):
                self._emit_heartbeat(now, reason="periodic")
                self._last_heartbeat_decisions = self.decisions_completed
                self._last_heartbeat_at = now

    def emit_final_heartbeat(self, reason: str) -> None:
        """Force a heartbeat write irrespective of throttle gates.
        Called by the timeout / hang-dump path so the on-disk record
        always reflects the *final* decision count when a game ends.
        No-op when ``heartbeat_path`` is unset."""
        if self.heartbeat_path is None:
            return
        self._emit_heartbeat(time.perf_counter(), reason=reason)

    def _emit_heartbeat(self, now: float, reason: str) -> None:
        """Write one JSONL line to ``heartbeat_path``. Best-effort —
        any I/O exception is swallowed (a diagnostic side-channel must
        never break the game loop). The line schema mirrors the main
        EventLog so the controller can splice these straight in."""
        assert self.heartbeat_path is not None
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": "game_heartbeat",
            "reason": reason,
            "decisions_completed": self.decisions_completed,
            "last_active_player": self.last_active_player,
            "last_decision_repr": self.last_decision_repr,
            "last_n_legal": self.last_n_legal,
            "seconds_since_started": round(now - self.started_at, 3),
        }
        try:
            self.heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
            with self.heartbeat_path.open("a", encoding="utf-8") as f:
                f.write(_json.dumps(payload, default=str) + "\n")
        except OSError:
            # Diagnostic side-channel — never propagate I/O errors.
            pass

    def snapshot(self) -> dict:
        """Read-side: produce a JSON-serializable summary for the
        hang dump. Computes derived `seconds_since_last_update` and
        `total_elapsed_sec` so the post-mortem reader doesn't need
        timestamps from elsewhere."""
        now = time.perf_counter()
        return {
            "decisions_completed": self.decisions_completed,
            "last_active_player": self.last_active_player,
            "last_decision_repr": self.last_decision_repr,
            "last_n_legal": self.last_n_legal,
            "seconds_since_last_update": round(
                now - self.last_update_at, 3,
            ),
            "total_elapsed_sec": round(now - self.started_at, 3),
        }
