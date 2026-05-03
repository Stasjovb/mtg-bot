"""Tests for the eval-match progress tracker.

Mirrors ``test_data_gen_progress``. The contract:

1. ``record_game(winner=..., decisions=...)`` accumulates wins/losses/
   draws and the running decision-count average.
2. ``finalize(...)`` writes a complete snapshot with ``status`` and
   ``ended_at``.
3. Throttled writes don't lose state.
4. The on-disk file is atomically replaced under concurrent reads.
5. ``record_game`` before ``begin`` produces a sensible initial
   snapshot.
6. ``win_rate`` is computed correctly (excludes draws from the
   denominator) and is 0.0 when no decided games exist yet.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from mtg_bot.training import EvalProgress


def _make(progress_path: Path, *, total: int = 10, workers: int = 4,
          interval: float = 5.0,
          opponent_label: str = "heuristic") -> EvalProgress:
    return EvalProgress(
        progress_path=progress_path,
        run_id=progress_path.stem,
        n_games_total=total,
        n_workers=workers,
        opponent_label=opponent_label,
        flush_interval_s=interval,
    )


def test_finalize_writes_complete_payload(tmp_path: Path):
    progress = _make(tmp_path / "run.json", total=4, workers=8,
                     opponent_label="v3")
    progress.begin()
    progress.record_game(winner=0, decisions=300)   # new wins
    progress.record_game(winner=0, decisions=400)   # new wins
    progress.record_game(winner=1, decisions=350)   # opp wins
    progress.record_game(winner=None, decisions=4000)  # draw
    progress.finalize(status="completed")

    payload = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert payload["kind"] == "eval"
    assert payload["status"] == "completed"
    assert payload["run_id"] == "run"
    assert payload["n_games_total"] == 4
    assert payload["n_games_done"] == 4
    assert payload["n_workers"] == 8
    assert payload["opponent_label"] == "v3"
    assert payload["wins_new"] == 2
    assert payload["wins_old"] == 1
    assert payload["draws"] == 1
    # win_rate is over decided games only (excludes draws)
    assert payload["win_rate"] == 2 / 3
    assert payload["avg_decisions"] == (300 + 400 + 350 + 4000) / 4
    assert payload["elapsed_seconds"] >= 0.0
    assert payload["estimated_remaining_seconds"] == 0.0
    assert payload["ended_at"] is not None
    assert "git_commit" in payload


def test_record_game_throttles_disk_writes(tmp_path: Path):
    """With a long flush interval, only ``begin`` and ``finalize``
    should touch disk — the in-memory counters keep accumulating."""
    progress = _make(tmp_path / "run.json", total=100, interval=10_000.0)
    progress.begin()
    initial_mtime = (tmp_path / "run.json").stat().st_mtime_ns
    for _ in range(50):
        progress.record_game(winner=0, decisions=200)
    assert (tmp_path / "run.json").stat().st_mtime_ns == initial_mtime
    progress.finalize(status="completed")
    final = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert final["n_games_done"] == 50
    assert final["wins_new"] == 50


def test_first_record_game_triggers_begin(tmp_path: Path):
    """If the driver forgets to call begin(), the first record_game
    still leaves a parseable file on disk so the UI's first poll
    sees something."""
    progress = _make(tmp_path / "run.json", total=5)
    progress.record_game(winner=0, decisions=300)
    payload = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert payload["status"] == "running"
    assert payload["n_games_done"] == 1
    assert payload["wins_new"] == 1
    assert payload["win_rate"] == 1.0


def test_finalize_failed_status(tmp_path: Path):
    progress = _make(tmp_path / "run.json", total=10)
    progress.begin()
    progress.record_game(winner=1, decisions=100)
    progress.finalize(status="failed")
    payload = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["ended_at"] is not None
    assert payload["n_games_done"] == 1


def test_win_rate_zero_when_only_draws(tmp_path: Path):
    """No decided games => win_rate=0.0 (sentinel; UI renders as 0%)."""
    progress = _make(tmp_path / "run.json", total=3)
    progress.begin()
    for _ in range(3):
        progress.record_game(winner=None, decisions=4000)
    progress.finalize(status="completed")
    payload = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert payload["wins_new"] == 0
    assert payload["wins_old"] == 0
    assert payload["draws"] == 3
    assert payload["win_rate"] == 0.0


def test_atomic_writes_under_concurrent_reads(tmp_path: Path):
    """Same atomicity guarantee as DataGenProgress — flushing every
    record_game while a tight-poll reader is open should never
    surface a half-written JSON."""
    progress = _make(tmp_path / "run.json", total=200, interval=0.0)
    progress.begin()
    stop = threading.Event()
    decode_errors: list[Exception] = []
    parses: list[dict] = []

    def _reader():
        while not stop.is_set():
            try:
                if (tmp_path / "run.json").is_file():
                    parses.append(json.loads(
                        (tmp_path / "run.json").read_text(encoding="utf-8"),
                    ))
            except json.JSONDecodeError as e:
                decode_errors.append(e)
            except (FileNotFoundError, PermissionError):
                pass
            time.sleep(0.001)

    t = threading.Thread(target=_reader, daemon=True)
    t.start()
    try:
        for i in range(200):
            progress.record_game(
                winner=0 if i % 3 == 0 else (1 if i % 3 == 1 else None),
                decisions=300,
            )
        progress.finalize(status="completed")
    finally:
        stop.set()
        t.join(timeout=2)

    assert decode_errors == [], (
        f"reader saw {len(decode_errors)} half-written files; "
        f"first: {decode_errors[0]!r}"
    )
    assert parses, "reader never managed to read the file"
    final = parses[-1]
    assert final["status"] in {"running", "completed"}
