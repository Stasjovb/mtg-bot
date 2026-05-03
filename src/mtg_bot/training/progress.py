"""Progress reporting for long-running training runs.

Two consumers today: the NN trainer (epoch-by-epoch loss) and the
self-play data generator (game-by-game throughput). Both write
``<run_id>.json`` files into a shared progress directory; the
``mtg_bot.training_ui`` Flask app reads them. A polling reader sees
a stable file (atomic temp + ``os.replace``).

The data-gen tracker batches its writes — the work it tracks is
1-10s per game, so the in-memory counters update on every game
completion but only flush to disk every ``flush_interval_s``
(default 5s). That keeps disk traffic at ~12 writes/min regardless
of game count, which is what we want for "no perf impact."

Schema discriminator: each payload carries ``kind`` so the UI knows
whether to render an epoch chart (``kind="training"``) or a
games-played card (``kind="data_gen"``).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def git_short_sha() -> Optional[str]:
    """Best-effort current git commit short SHA; ``None`` if not in
    a git repo or git isn't on PATH. Stamped onto progress JSON so a
    viewer can correlate runs to code state."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=3, check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        pass
    return None


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write ``payload`` to ``path`` atomically: serialize to a
    sibling ``.tmp`` file then ``os.replace`` it into place. Replace
    is atomic on both POSIX and Windows, so a polling reader either
    sees the previous version or the new one — never a half-file.

    Windows wrinkle: if a reader currently has the destination file
    open (even just for the duration of a ``read_text`` call),
    ``os.replace`` raises ``PermissionError`` because Windows MOVEFILE
    requires deletable access. The contention window for a 2-second
    polling reader doing one fast read is small (~ms), so a tight
    retry loop reliably wins. If we can't get through after ~1s,
    raise — that's a real bug, not a transient race.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
    delay = 0.005
    for _ in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(delay)
            delay = min(delay * 2, 0.1)
    os.replace(tmp, path)


@dataclass
class DataGenProgress:
    """Tracker for a self-play data-generation run.

    The driver code calls ``record_game(...)`` once per finished game
    and (optionally) ``flush()`` at the end. Internally we keep all
    counters in memory and only touch disk when the elapsed time
    since the last flush exceeds ``flush_interval_s`` (or when the
    caller forces it via ``flush(force=True)``). At 5s intervals
    that's ~12 writes/min regardless of game count — well below the
    cost of one game.

    The first call to ``record_game`` triggers an "initial running"
    snapshot if one hasn't been written yet, so the UI can show the
    run with 0 games done very quickly after it starts. The driver
    may also force an opening snapshot via ``begin()``.

    Stats captured:
      - games done / total, samples accumulated
      - p0 wins / p1 wins / draws (p0 perspective)
      - elapsed_seconds, ETA, games/hr, samples/hr
      - n_workers, command line, git commit, started_at ISO

    All times are computed against ``time.monotonic()`` for the
    elapsed counter and ``datetime.now(timezone.utc)`` for the
    wall-clock ISO string. Both are advisory only — the JSON is
    a snapshot, not a log.
    """

    progress_path: Path
    run_id: str
    n_games_total: int
    n_workers: int
    command: str = ""
    notes: str = ""
    flush_interval_s: float = 5.0

    # Internal state — populated in __post_init__ and update()
    _started_perf: float = field(default=0.0, init=False)
    _started_iso: str = field(default="", init=False)
    _git_commit: Optional[str] = field(default=None, init=False)
    _last_flush_perf: float = field(default=0.0, init=False)
    _games_done: int = field(default=0, init=False)
    _samples: int = field(default=0, init=False)
    _p0_wins: int = field(default=0, init=False)
    _p1_wins: int = field(default=0, init=False)
    _draws: int = field(default=0, init=False)
    _status: str = field(default="running", init=False)
    _begun: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self.progress_path = Path(self.progress_path)
        self._started_perf = time.monotonic()
        self._started_iso = datetime.now(timezone.utc).isoformat(
            timespec="seconds",
        )
        self._git_commit = git_short_sha()
        # Force the first flush to fire on the next record_game (or
        # explicit flush(force=True)).
        self._last_flush_perf = self._started_perf - self.flush_interval_s

    def begin(self) -> None:
        """Write an initial 'running, 0 games done' snapshot. Useful
        so the UI shows the run before the first game finishes —
        important when games are slow (multi-minute) or when we want
        to confirm the writer is alive before any real work starts.
        """
        self._begun = True
        self._flush_now()

    def record_game(
        self,
        *,
        n_samples: int,
        outcome_p0: float,
    ) -> None:
        """Account one finished game. ``outcome_p0`` is the +1 / -1 /
        0 outcome from p0's perspective (the value the trainer learns
        on for viewer 0). Anything > 0.5 → p0 win, < -0.5 → p1 win,
        else draw; the threshold avoids float-equality fragility for
        the +1/0/-1 case."""
        self._games_done += 1
        self._samples += int(n_samples)
        if outcome_p0 > 0.5:
            self._p0_wins += 1
        elif outcome_p0 < -0.5:
            self._p1_wins += 1
        else:
            self._draws += 1
        # Lazy first-snapshot — caller may not have called begin().
        if not self._begun:
            self.begin()
            return
        self._maybe_flush()

    def finalize(self, status: str = "completed") -> None:
        """Emit the final snapshot. Caller passes 'completed' on
        success, 'failed' on exception. The snapshot is forced
        regardless of when the last flush happened, and includes
        ``ended_at`` so consumers know the run is terminal."""
        self._status = status
        self._flush_now(ended=True)

    def _maybe_flush(self) -> None:
        now = time.monotonic()
        if now - self._last_flush_perf >= self.flush_interval_s:
            self._flush_now(_perf_now=now)

    def _flush_now(
        self,
        *,
        ended: bool = False,
        _perf_now: Optional[float] = None,
    ) -> None:
        now = _perf_now if _perf_now is not None else time.monotonic()
        elapsed = max(now - self._started_perf, 0.0)
        done = self._games_done
        total = self.n_games_total
        # Avoid divide-by-zero on the very first snapshot where 0
        # games are done but we still want a sensible JSON.
        avg = (elapsed / done) if done > 0 else 0.0
        remaining = max(total - done, 0)
        eta = avg * remaining if avg > 0 else 0.0
        games_per_hour = (done / elapsed * 3600.0) if elapsed > 0 else 0.0
        samples_per_hour = (
            self._samples / elapsed * 3600.0 if elapsed > 0 else 0.0
        )
        ended_at = (
            datetime.now(timezone.utc).isoformat(timespec="seconds")
            if ended else None
        )
        payload: dict[str, Any] = {
            "run_id": self.run_id,
            "kind": "data_gen",
            "status": self._status,
            "started_at": self._started_iso,
            "ended_at": ended_at,
            "n_games_total": int(total),
            "n_games_done": int(done),
            "n_samples": int(self._samples),
            "n_workers": int(self.n_workers),
            "p0_wins": int(self._p0_wins),
            "p1_wins": int(self._p1_wins),
            "draws": int(self._draws),
            "elapsed_seconds": float(elapsed),
            "estimated_remaining_seconds": float(eta),
            "per_game_seconds_avg": float(avg),
            "games_per_hour": float(games_per_hour),
            "samples_per_hour": float(samples_per_hour),
            "command": self.command,
            "git_commit": self._git_commit,
            "notes": self.notes,
        }
        atomic_write_json(self.progress_path, payload)
        self._last_flush_perf = now
