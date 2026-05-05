"""Progress reporting for long-running training runs.

Four consumers today: the NN trainer (epoch-by-epoch loss), the
self-play data generator (game-by-game throughput), the
NN-vs-baseline evaluator (game-by-game win rate), and the strength-
A/B benchmark (per-pairing matched-budget head-to-head). All four
write ``<run_id>.json`` files into a shared progress directory; the
``mtg_bot.training_ui`` Flask app reads them. A polling reader sees
a stable file (atomic temp + ``os.replace``).

The game-tracking trackers (data-gen, eval, bench) batch their
writes — the work they track is seconds-to-minutes per game, so the
in-memory counters update on every game completion but only flush
to disk every ``flush_interval_s`` (default 5s). That keeps disk
traffic at ~12 writes/min regardless of game count, which is what
we want for "no perf impact."

Schema discriminator: each payload carries ``kind`` so the UI knows
whether to render an epoch chart (``kind="training"``), a games-
played card (``kind="data_gen"``), a head-to-head win-rate card
(``kind="eval"``), or a multi-pairing A/B card (``kind="bench"``).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence


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
    # Where this run is writing captured replay files (one .json.gz per
    # captured game). Surfaced into the snapshot JSON so the UI can
    # link from this run's card directly to its game list.
    # ``None`` means no replays are being captured for this run.
    replays_dir: Optional[str] = None

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
    _crashed: int = field(default=0, init=False)
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
        n_samples: int = 0,
        outcome_p0: float = 0.0,
        crashed: bool = False,
    ) -> None:
        """Account one finished game. ``outcome_p0`` is the +1 / -1 /
        0 outcome from p0's perspective (the value the trainer learns
        on for viewer 0). Anything > 0.5 → p0 win, < -0.5 → p1 win,
        else draw; the threshold avoids float-equality fragility for
        the +1/0/-1 case.

        Pass ``crashed=True`` for games dropped by the worker-crash /
        per-game-timeout sentinel handler (see
        ``data_gen._play_one_parallel_game``). Crashed games increment
        the ``crashed`` counter instead of polluting wins / draws —
        that keeps the live UI's draws number honest by excluding
        games that never reached a clean conclusion. They DO still
        count toward ``n_games_done`` so the progress bar advances.
        Mirror of the ``EvalProgress.record_game`` shape; same fix as
        feature/drop-crashed-games (962d58b) but for the data-gen
        side. ``n_samples`` and ``outcome_p0`` are ignored when
        crashed=True (caller will pass 0/0.0 anyway since the chunk
        is empty).
        """
        self._games_done += 1
        if crashed:
            self._crashed += 1
        else:
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
            "crashed": int(self._crashed),
            "elapsed_seconds": float(elapsed),
            "estimated_remaining_seconds": float(eta),
            "per_game_seconds_avg": float(avg),
            "games_per_hour": float(games_per_hour),
            "samples_per_hour": float(samples_per_hour),
            "command": self.command,
            "git_commit": self._git_commit,
            "notes": self.notes,
            "replays_dir": self.replays_dir,
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
    # See ``DataGenProgress.replays_dir`` — same contract.
    replays_dir: Optional[str] = None

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
            "replays_dir": self.replays_dir,
        }
        atomic_write_json(self.progress_path, payload)
        self._last_flush_perf = now


@dataclass
class _PairingState:
    """In-memory state for one pairing inside a :class:`BenchProgress`
    run. The bench script plays N pairings (typically PIMC vs ISMCTS
    at one or more matched budgets); each pairing is its own
    head-to-head match with running win counts and a Wilson 95% CI
    derived from those counts.

    Stored as plain ints / floats so ``snapshot()`` can serialize the
    pairing into the per-run JSON without further conversion.
    """

    challenger: str
    defender: str
    n_games: int
    samples: Optional[int] = None
    inner_nodes: Optional[int] = None
    total_iterations: Optional[int] = None
    started_perf: float = 0.0
    started_iso: str = ""
    n_decided: int = 0
    challenger_wins: int = 0
    defender_wins: int = 0
    draws: int = 0
    crashed: int = 0
    n_games_done: int = 0
    elapsed_seconds: float = 0.0
    ci_low: float = 0.0
    ci_high: float = 1.0
    win_rate: float = 0.0
    verdict: str = "pending"
    status: str = "running"
    ended_at: Optional[str] = None
    # Throughput stats — populated post-hoc by bench drivers that
    # know their per-game wall-mean and worker count (e.g.
    # ``bench_per_game_wall.py``). None when the bench doesn't
    # report them, so the UI can choose to hide the column.
    games_per_hour: Optional[float] = None
    sec_per_game_per_worker: Optional[float] = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "challenger": self.challenger,
            "defender": self.defender,
            "n_games": int(self.n_games),
            "samples": self.samples,
            "inner_nodes": self.inner_nodes,
            "total_iterations": self.total_iterations,
            "started_at": self.started_iso,
            "ended_at": self.ended_at,
            "n_games_done": int(self.n_games_done),
            "n_decided": int(self.n_decided),
            "challenger_wins": int(self.challenger_wins),
            "defender_wins": int(self.defender_wins),
            "draws": int(self.draws),
            "crashed": int(self.crashed),
            "elapsed_seconds": float(self.elapsed_seconds),
            "win_rate": float(self.win_rate),
            "ci_low": float(self.ci_low),
            "ci_high": float(self.ci_high),
            "verdict": self.verdict,
            "status": self.status,
            "games_per_hour": (
                float(self.games_per_hour)
                if self.games_per_hour is not None else None
            ),
            "sec_per_game_per_worker": (
                float(self.sec_per_game_per_worker)
                if self.sec_per_game_per_worker is not None else None
            ),
        }


def _wilson_interval(
    successes: int, trials: int, z: float = 1.96,
) -> tuple[float, float]:
    """Wilson 95% interval for a binomial proportion.

    Closed-form, no scipy. Mirrors ``wilson_interval`` in
    ``scripts/bench_ismcts_vs_pimc_strength.py`` — duplicated here so
    ``BenchProgress`` can recompute the CI on every snapshot without
    importing from the script (the script imports from ``mtg_bot``,
    not the other way around).
    """
    import math

    if trials <= 0:
        return 0.0, 1.0
    if successes < 0 or successes > trials:
        # Defensive: caller's bookkeeping is broken; clamp to a sane
        # interval so we don't take down the whole snapshot writer.
        successes = max(0, min(trials, successes))
    n = float(trials)
    p_hat = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p_hat + z2 / (2.0 * n)) / denom
    margin = (
        z * math.sqrt((p_hat * (1.0 - p_hat) + z2 / (4.0 * n)) / n)
        / denom
    )
    return center - margin, center + margin


def _classify_verdict(ci_low: float, ci_high: float) -> str:
    """Map a 95% CI to a verdict against the 50% null.

    'stronger': CI strictly above 0.5.
    'weaker':   CI strictly below 0.5.
    'comparable': CI overlaps 0.5.
    """
    if ci_low > 0.5:
        return "stronger"
    if ci_high < 0.5:
        return "weaker"
    return "comparable"


@dataclass
class BenchProgress:
    """Tracker for a strength-A/B benchmark run (multiple pairings).

    Unlike DataGenProgress / EvalProgress, a bench run is structured
    as a sequence of *pairings* — each pairing is itself a head-to-
    head match (challenger vs defender at some matched budget). The
    UI renders a card with one row per pairing showing live win-rate
    + Wilson CI + verdict, plus run-level metadata (weights path,
    budgets, belief settings, elapsed time).

    Lifecycle::

        bp = BenchProgress(progress_path=..., run_id=..., ...)
        bp.begin()
        for (challenger, defender, n, ...) in pairings:
            bp.start_pairing(challenger, defender, n_games=n, ...)
            for game in match:
                bp.record_game(winner=..., crashed=...)
            bp.finish_pairing(status="completed")
        bp.finalize(status="completed")

    The ``record_game`` and ``finish_pairing`` flows respect the
    same throttled-flush contract as the other trackers — a long
    ``flush_interval_s`` keeps in-flight pairings cheap, and the
    ``finish_pairing`` / ``finalize`` calls force a flush so terminal
    states land on disk immediately.

    Pairings are appended to ``self._pairings`` in ``start_pairing``;
    ``record_game`` / ``finish_pairing`` operate on the latest one
    (``self._current``). The bench script doesn't run pairings in
    parallel, so a single ``_current`` pointer suffices.
    """

    progress_path: Path
    run_id: str
    weights_path: str = ""
    n_games_per_pairing: int = 0
    budgets: Sequence[tuple[int, int]] = field(default_factory=tuple)
    include_belief: bool = False
    belief_m_candidates: Optional[int] = None
    nn_device: Optional[str] = None
    command: str = ""
    notes: str = ""
    flush_interval_s: float = 5.0

    _started_perf: float = field(default=0.0, init=False)
    _started_iso: str = field(default="", init=False)
    _git_commit: Optional[str] = field(default=None, init=False)
    _last_flush_perf: float = field(default=0.0, init=False)
    _pairings: list[_PairingState] = field(default_factory=list, init=False)
    _current: Optional[_PairingState] = field(default=None, init=False)
    _status: str = field(default="running", init=False)
    _begun: bool = field(default=False, init=False)
    _ended_at: Optional[str] = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.progress_path = Path(self.progress_path)
        self._started_perf = time.monotonic()
        self._started_iso = datetime.now(timezone.utc).isoformat(
            timespec="seconds",
        )
        self._git_commit = git_short_sha()
        # Force the first flush to fire on the next event.
        self._last_flush_perf = self._started_perf - self.flush_interval_s

    def begin(self) -> None:
        """Write the initial ``running, no pairings yet`` snapshot.

        Useful so the UI shows the run before the first pairing's
        first game finishes. Bench runs with production budgets can
        take 10+ minutes per pairing, so an early snapshot is the
        difference between "is this thing alive?" and a confident
        progress bar.
        """
        self._begun = True
        self._flush_now()

    def start_pairing(
        self,
        *,
        challenger: str,
        defender: str,
        n_games: int,
        samples: Optional[int] = None,
        inner_nodes: Optional[int] = None,
        total_iterations: Optional[int] = None,
    ) -> None:
        """Open a new pairing. Subsequent ``record_game`` calls land
        on this pairing until ``finish_pairing`` is called."""
        if not self._begun:
            self.begin()
        now = time.monotonic()
        pairing = _PairingState(
            challenger=challenger,
            defender=defender,
            n_games=int(n_games),
            samples=samples,
            inner_nodes=inner_nodes,
            total_iterations=total_iterations,
            started_perf=now,
            started_iso=datetime.now(timezone.utc).isoformat(
                timespec="seconds",
            ),
        )
        self._pairings.append(pairing)
        self._current = pairing
        # Force a flush so the UI shows the new pairing as 'running'
        # before the first game lands — pairings can be tens of
        # minutes apart.
        self._flush_now()

    def record_game(
        self,
        *,
        winner: Optional[int],
        crashed: bool = False,
    ) -> None:
        """Account one finished game on the current pairing.

        ``winner=0`` is a challenger win, ``winner=1`` is a defender
        win, ``winner=None`` is a draw. ``crashed=True`` means the
        worker dropped the game; counts toward ``n_games_done`` but
        not the win/loss/draw columns nor the Wilson CI denominator
        — same contract as :class:`EvalProgress.record_game`.

        Raises ``RuntimeError`` if no pairing is active. The bench
        script always opens a pairing before its games run, so this
        is a programming-error guard rather than a runtime concern.
        """
        if self._current is None:
            raise RuntimeError(
                "BenchProgress.record_game called before "
                "start_pairing"
            )
        cur = self._current
        cur.n_games_done += 1
        if crashed:
            cur.crashed += 1
        elif winner == 0:
            cur.challenger_wins += 1
            cur.n_decided += 1
        elif winner == 1:
            cur.defender_wins += 1
            cur.n_decided += 1
        else:
            cur.draws += 1
        self._recompute_current()
        self._maybe_flush()

    def record_pairing_result(
        self,
        *,
        challenger_wins: int,
        defender_wins: int,
        draws: int,
        crashed: int = 0,
        elapsed_seconds: Optional[float] = None,
    ) -> None:
        """Bulk-update the current pairing from a single batch of
        results. Useful when the bench plays the whole pairing inside
        a single ``run_match_parallel`` call and only sees the totals
        — no per-game record_game stream available.

        Overwrites the in-memory game counts on ``self._current``;
        callers should NOT mix this with ``record_game``. Forces a
        flush so the new totals land on disk immediately.
        """
        if self._current is None:
            raise RuntimeError(
                "BenchProgress.record_pairing_result called before "
                "start_pairing"
            )
        cur = self._current
        cur.challenger_wins = int(challenger_wins)
        cur.defender_wins = int(defender_wins)
        cur.draws = int(draws)
        cur.crashed = int(crashed)
        cur.n_decided = cur.challenger_wins + cur.defender_wins
        cur.n_games_done = (
            cur.n_decided + cur.draws + cur.crashed
        )
        if elapsed_seconds is not None:
            cur.elapsed_seconds = float(elapsed_seconds)
        self._recompute_current(force_elapsed=elapsed_seconds is None)
        self._flush_now()

    def set_throughput_stats(
        self,
        *,
        games_per_hour: Optional[float],
        sec_per_game_per_worker: Optional[float],
    ) -> None:
        """Stamp throughput stats onto the current pairing.

        Bench drivers that know their per-game wall-mean and worker
        count (e.g. ``bench_per_game_wall.py``) call this once after
        all games finish but before ``finish_pairing``. The values
        flow through to the JSON pairings entry so the training UI
        can render a games/hour column for at-a-glance comparison
        across machines.

        Pairings whose drivers don't compute these (the strength
        A/B bench, for example) simply omit the call and the fields
        stay ``None`` in the snapshot.
        """
        if self._current is None:
            raise RuntimeError(
                "BenchProgress.set_throughput_stats called before "
                "start_pairing"
            )
        self._current.games_per_hour = (
            float(games_per_hour) if games_per_hour is not None else None
        )
        self._current.sec_per_game_per_worker = (
            float(sec_per_game_per_worker)
            if sec_per_game_per_worker is not None else None
        )
        self._flush_now()

    def finish_pairing(self, status: str = "completed") -> None:
        """Close the current pairing. ``status`` is "completed" on
        normal exit, "failed" if the pairing bailed out partway."""
        if self._current is None:
            raise RuntimeError(
                "BenchProgress.finish_pairing called before "
                "start_pairing"
            )
        cur = self._current
        cur.status = status
        cur.ended_at = datetime.now(timezone.utc).isoformat(
            timespec="seconds",
        )
        self._recompute_current()
        # Force a flush so the terminal pairing state is visible
        # before the next pairing starts (or the whole run ends).
        self._flush_now()
        self._current = None

    def finalize(self, status: str = "completed") -> None:
        """Emit the final run-level snapshot. Any still-active pairing
        is force-finalized with the same status so the UI doesn't
        leave orphan 'running' rows behind."""
        if self._current is not None:
            # Mirror the run-level status onto the orphan pairing.
            self.finish_pairing(status=status)
        self._status = status
        self._ended_at = datetime.now(timezone.utc).isoformat(
            timespec="seconds",
        )
        self._flush_now(ended=True)

    def _recompute_current(
        self, *, force_elapsed: bool = True,
    ) -> None:
        """Refresh derived stats (elapsed, win_rate, CI, verdict) on
        the current pairing from its in-memory counts.

        ``force_elapsed=False`` skips the elapsed recompute — used
        when the caller (record_pairing_result) already supplied an
        authoritative ``elapsed_seconds``.
        """
        cur = self._current
        if cur is None:
            return  # pragma: no cover - guarded by callers
        if force_elapsed:
            cur.elapsed_seconds = max(
                time.monotonic() - cur.started_perf, 0.0,
            )
        decided = cur.n_decided
        cur.win_rate = (
            cur.challenger_wins / decided if decided > 0 else 0.0
        )
        cur.ci_low, cur.ci_high = _wilson_interval(
            cur.challenger_wins, decided,
        )
        cur.verdict = (
            _classify_verdict(cur.ci_low, cur.ci_high)
            if decided > 0 else "pending"
        )

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
        # Aggregate totals across all pairings — handy for the UI
        # header strip and for log scrapers.
        total_games = sum(p.n_games for p in self._pairings)
        total_done = sum(p.n_games_done for p in self._pairings)
        ended_at = (
            self._ended_at
            if ended and self._ended_at is not None
            else (
                datetime.now(timezone.utc).isoformat(timespec="seconds")
                if ended else None
            )
        )
        payload: dict[str, Any] = {
            "run_id": self.run_id,
            "kind": "bench",
            "status": self._status,
            "started_at": self._started_iso,
            "ended_at": ended_at,
            "weights_path": self.weights_path,
            "n_games_per_pairing": int(self.n_games_per_pairing),
            "n_games_total": int(total_games),
            "n_games_done": int(total_done),
            "budgets": [
                [int(k), int(n)] for (k, n) in self.budgets
            ],
            "include_belief": bool(self.include_belief),
            "belief_m_candidates": self.belief_m_candidates,
            "nn_device": self.nn_device,
            "pairings": [p.to_payload() for p in self._pairings],
            "elapsed_seconds": float(elapsed),
            "command": self.command,
            "git_commit": self._git_commit,
            "notes": self.notes,
        }
        atomic_write_json(self.progress_path, payload)
        self._last_flush_perf = now
