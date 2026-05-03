"""Tests for the data-generation progress tracker.

Mirrors the trainer-side ``test_trainer_progress`` style. The
contract we care about:

1. ``record_game(...)`` correctly accumulates games / samples / wins.
2. ``finalize(...)`` writes a complete snapshot with the right
   ``status`` and an ``ended_at`` timestamp.
3. The throttled writes don't lose state — calling ``record_game``
   under the flush interval still updates in-memory counters and
   the next flush picks them all up.
4. The on-disk file is always atomically replaced, so a tight-poll
   reader on another thread never sees a half-file.
5. ``record_game`` before ``begin`` produces a sensible initial
   snapshot rather than a missing-file race for the first reader.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from mtg_bot.training import DataGenProgress


def _make(progress_path: Path, *, total: int = 10, workers: int = 4,
          interval: float = 5.0) -> DataGenProgress:
    return DataGenProgress(
        progress_path=progress_path,
        run_id=progress_path.stem,
        n_games_total=total,
        n_workers=workers,
        flush_interval_s=interval,
    )


def test_finalize_writes_complete_payload(tmp_path: Path):
    progress = _make(tmp_path / "run.json", total=3, workers=2)
    progress.begin()
    progress.record_game(n_samples=10, outcome_p0=1.0)   # p0 wins
    progress.record_game(n_samples=20, outcome_p0=-1.0)  # p1 wins
    progress.record_game(n_samples=30, outcome_p0=0.0)   # draw
    progress.finalize(status="completed")

    payload = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert payload["kind"] == "data_gen"
    assert payload["status"] == "completed"
    assert payload["run_id"] == "run"
    assert payload["n_games_total"] == 3
    assert payload["n_games_done"] == 3
    assert payload["n_samples"] == 60
    assert payload["n_workers"] == 2
    assert payload["p0_wins"] == 1
    assert payload["p1_wins"] == 1
    assert payload["draws"] == 1
    assert payload["elapsed_seconds"] >= 0.0
    assert payload["estimated_remaining_seconds"] == 0.0
    assert payload["ended_at"] is not None
    assert "git_commit" in payload


def test_record_game_throttles_disk_writes(tmp_path: Path):
    """With a long flush interval, only ``begin`` and ``finalize``
    should touch disk — the in-memory counters keep accumulating.
    Verifies that intermediate ``record_game`` calls don't write."""
    progress = _make(tmp_path / "run.json", total=100, interval=10_000.0)
    progress.begin()
    initial_mtime = (tmp_path / "run.json").stat().st_mtime_ns
    for i in range(50):
        progress.record_game(n_samples=1, outcome_p0=1.0)
    # No flush should have fired (interval is 10s of seconds wallclock).
    assert (tmp_path / "run.json").stat().st_mtime_ns == initial_mtime
    progress.finalize(status="completed")
    final = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert final["n_games_done"] == 50
    assert final["p0_wins"] == 50


def test_first_record_game_triggers_begin(tmp_path: Path):
    """If the driver forgets to call begin(), the first
    record_game() still leaves a parseable file on disk so the UI
    has something to read on its first poll. Counters update first,
    so the implicit-begin snapshot already includes that game."""
    progress = _make(tmp_path / "run.json", total=5)
    progress.record_game(n_samples=7, outcome_p0=1.0)
    payload = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert payload["status"] == "running"
    assert payload["n_games_done"] == 1
    assert payload["n_samples"] == 7
    assert payload["p0_wins"] == 1


def test_finalize_failed_status(tmp_path: Path):
    progress = _make(tmp_path / "run.json", total=10)
    progress.begin()
    progress.record_game(n_samples=5, outcome_p0=1.0)
    progress.finalize(status="failed")
    payload = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["ended_at"] is not None
    assert payload["n_games_done"] == 1


def test_atomic_writes_under_concurrent_reads(tmp_path: Path):
    """A tight-poll reader thread reading the file while the tracker
    flushes should never observe a half-written / unparseable JSON.
    """
    progress = _make(
        tmp_path / "run.json", total=200, interval=0.0,  # flush every record
    )
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
                # Windows MOVEFILE race; next poll wins. Same as the
                # trainer-side atomicity test.
                pass
            time.sleep(0.001)

    t = threading.Thread(target=_reader, daemon=True)
    t.start()
    try:
        for i in range(200):
            progress.record_game(n_samples=1, outcome_p0=1.0 if i % 2 == 0 else -1.0)
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


def test_winrate_thresholds(tmp_path: Path):
    """Outcome float can be exactly +/-1.0 or 0.0 (the integer
    winner-encoded path) but might also be a tiny float due to the
    np.float32 round-trip. The tracker uses 0.5 / -0.5 thresholds,
    not exact equality, so any reasonable value lands in the right
    bucket."""
    progress = _make(tmp_path / "run.json", total=4)
    progress.begin()
    progress.record_game(n_samples=1, outcome_p0=0.99)   # p0 win
    progress.record_game(n_samples=1, outcome_p0=-0.51)  # p1 win
    progress.record_game(n_samples=1, outcome_p0=0.49)   # draw (below threshold)
    progress.record_game(n_samples=1, outcome_p0=-0.49)  # draw
    progress.finalize(status="completed")
    payload = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert payload["p0_wins"] == 1
    assert payload["p1_wins"] == 1
    assert payload["draws"] == 2
