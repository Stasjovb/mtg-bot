"""Progress reporting for long-running training runs.

Three consumers today: the NN trainer (epoch-by-epoch loss), the
self-play data generator (game-by-game throughput), and the
NN-vs-baseline evaluator (game-by-game win rate). All three write
``<run_id>.json`` files into a shared progress directory; the
``mtg_bot.training_ui`` Flask app reads them. A polling reader sees
a stable file (atomic temp + ``os.replace``).

The game-tracking trackers (data-gen, eval) batch their writes — the
work they track is seconds-to-minutes per game, so the in-memory
counters update on every game completion but only flush to disk
every ``flush_interval_s`` (default 5s). That keeps disk traffic at
~12 writes/min regardless of game count, which is what we want for
"no perf impact."

Schema discriminator: each payload carries ``kind`` so the UI knows
whether to render an epoch chart (``kind="training"``), a games-
played card (``kind="data_gen"``), or a head-to-head win-rate card
(``kind="eval"``).
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


@dataclass
class EvalProgress:
    """Tracker for an NN-vs-opponent head-to-head evaluation match.

    Mirrors :class:`DataGenProgress`'s shape — same begin / record_game
    / finalize lifecycle, same ``flush_interval_s`` batching — but
    tracks win counts from the new model's perspective rather than
    sample counts. The new model is conventionally seat 0; the
    opponent (baseline heuristic, or an older registered version) is
    seat 1.

    ``record_game`` takes ``winner`` (0, 1, or None for draw / decision-
    cap timeout) and the per-game decision count for the running
    average. Pass ``crashed=True`` for games where a worker raised an
    engine-level exception and was dropped — those increment a
    dedicated ``crashed`` counter instead of polluting the
    wins/draws columns (see ``run_match_parallel`` for the producer
    side). Aggregated stats published to the snapshot JSON:

    - ``wins_new`` / ``wins_old`` / ``draws``
    - ``crashed``         — games dropped due to worker-side engine
      exceptions; kept out of wins_new/wins_old/draws/win_rate so
      a 1/1000 corruption bug doesn't pollute the head-to-head
      number. Total games seen is still ``n_games_done`` =
      wins_new + wins_old + draws + crashed.
    - ``win_rate``        — wins_new / decided games (excludes draws
      and crashes)
    - ``avg_decisions``   — running mean of per-game decision counts
    - ``elapsed_seconds`` / ``estimated_remaining_seconds`` /
      ``per_game_seconds_avg`` / ``games_per_hour`` (same as data_gen)
    - ``opponent_label``  — free-form description so the UI can
      render "v4 vs heuristic" or "v5 vs v4" without re-deriving it
    """

    progress_path: Path
    run_id: str
    n_games_total: int
    n_workers: int
    opponent_label: str = "heuristic"
    command: str = ""
    notes: str = ""
    flush_interval_s: float = 5.0

    _started_perf: float = field(default=0.0, init=False)
    _started_iso: str = field(default="", init=False)
    _git_commit: Optional[str] = field(default=None, init=False)
    _last_flush_perf: float = field(default=0.0, init=False)
    _games_done: int = field(default=0, init=False)
    _wins_new: int = field(default=0, init=False)
    _wins_old: int = field(default=0, init=False)
    _draws: int = field(default=0, init=False)
    _crashed: int = field(default=0, init=False)
    _total_decisions: int = field(default=0, init=False)
    _status: str = field(default="running", init=False)
    _begun: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self.progress_path = Path(self.progress_path)
        self._started_perf = time.monotonic()
        self._started_iso = datetime.now(timezone.utc).isoformat(
            timespec="seconds",
        )
        self._git_commit = git_short_sha()
        self._last_flush_perf = self._started_perf - self.flush_interval_s

    def begin(self) -> None:
        """Write an initial 'running, 0 games done' snapshot. Useful
        because PUCT eval games can be multi-minute affairs and we
        want the run visible in the UI before the first finishes."""
        self._begun = True
        self._flush_now()

    def record_game(
        self,
        *,
        winner: Optional[int],
        decisions: int = 0,
        crashed: bool = False,
    ) -> None:
        """Account one finished game. ``winner=0`` is a new-model
        win, ``winner=1`` an opponent win, ``winner=None`` a draw
        (decision-cap timeout or genuine repetition). ``decisions``
        is folded into the running average.

        Pass ``crashed=True`` for games dropped by the eval pool's
        worker-crash handler (see ``self_play.run_match_parallel``).
        Crashed games increment ``crashed`` instead of any of
        wins_new / wins_old / draws — that keeps win_rate (and the
        UI's head-to-head number) honest by excluding games that
        never reached a clean conclusion. They DO still count
        toward ``n_games_done`` so the progress bar advances.
        Default ``False`` preserves the existing call-site contract.
        """
        self._games_done += 1
        self._total_decisions += int(decisions)
        if crashed:
            self._crashed += 1
        elif winner == 0:
            self._wins_new += 1
        elif winner == 1:
            self._wins_old += 1
        else:
            self._draws += 1
        if not self._begun:
            self.begin()
            return
        self._maybe_flush()

    def finalize(self, status: str = "completed") -> None:
        """Emit the final snapshot. ``status`` is 'completed' on
        normal exit, 'failed' if the eval bailed out partway."""
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
        avg = (elapsed / done) if done > 0 else 0.0
        remaining = max(total - done, 0)
        eta = avg * remaining if avg > 0 else 0.0
        games_per_hour = (done / elapsed * 3600.0) if elapsed > 0 else 0.0
        decided = self._wins_new + self._wins_old
        win_rate = (self._wins_new / decided) if decided > 0 else 0.0
        avg_decisions = (
            self._total_decisions / done if done > 0 else 0.0
        )
        ended_at = (
            datetime.now(timezone.utc).isoformat(timespec="seconds")
            if ended else None
        )
        payload: dict[str, Any] = {
            "run_id": self.run_id,
            "kind": "eval",
            "status": self._status,
            "started_at": self._started_iso,
            "ended_at": ended_at,
            "n_games_total": int(total),
            "n_games_done": int(done),
            "n_workers": int(self.n_workers),
            "opponent_label": self.opponent_label,
            "wins_new": int(self._wins_new),
            "wins_old": int(self._wins_old),
            "draws": int(self._draws),
            "crashed": int(self._crashed),
            "win_rate": float(win_rate),
            "avg_decisions": float(avg_decisions),
            "elapsed_seconds": float(elapsed),
            "estimated_remaining_seconds": float(eta),
            "per_game_seconds_avg": float(avg),
            "games_per_hour": float(games_per_hour),
            "command": self.command,
            "git_commit": self._git_commit,
            "notes": self.notes,
        }
        atomic_write_json(self.progress_path, payload)
        self._last_flush_perf = now
