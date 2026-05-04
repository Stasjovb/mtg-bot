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

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class HangProgress:
    """Mutable progress sentinel shared between the inner game thread
    and the timeout handler.

    Fields are deliberately small + shallow-copy-safe — we want the
    snapshot serializable into the hang-dump JSON without any active-
    record gymnastics.
    """

    started_at: float = field(default_factory=time.perf_counter)
    decisions_completed: int = 0
    last_active_player: Optional[int] = None
    last_decision_repr: str = ""
    last_update_at: float = field(default_factory=time.perf_counter)
    last_n_legal: int = 0

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
        self.last_update_at = time.perf_counter()

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
