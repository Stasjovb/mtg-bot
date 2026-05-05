"""Tests for the strength-A/B bench progress tracker.

Mirrors ``test_eval_progress`` / ``test_data_gen_progress``. The
contract:

1. ``begin()`` writes an initial ``running, no pairings`` snapshot.
2. ``start_pairing(...)`` opens a pairing with metadata; the pairing
   shows up in the snapshot immediately.
3. ``record_game(...)`` and ``record_pairing_result(...)`` accumulate
   onto the *current* pairing only.
4. ``finish_pairing(...)`` closes the current pairing with
   ``status="completed"`` (or ``"failed"``) and forces a flush.
5. ``finalize(...)`` writes the terminal run-level snapshot.
6. The Wilson 95% CI + verdict update live as games stream in.
7. Snapshot writes are atomic — concurrent readers never see a
   half-file (mirrors the EvalProgress concurrency test).
8. Crashed games count toward ``n_games_done`` but NOT toward the
   wins / draws / decided columns or the Wilson denominator.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from mtg_bot.training import BenchProgress


def _make(progress_path: Path, **overrides) -> BenchProgress:
    defaults = {
        "progress_path": progress_path,
        "run_id": progress_path.stem,
        "weights_path": "trained_weights/v6/weights.pt",
        "n_games_per_pairing": 4,
        "budgets": [(4, 200)],
        "include_belief": False,
        "belief_m_candidates": 64,
        "nn_device": "cpu",
        "flush_interval_s": 5.0,
    }
    defaults.update(overrides)
    return BenchProgress(**defaults)


def test_begin_writes_initial_snapshot(tmp_path: Path):
    progress = _make(tmp_path / "run.json")
    progress.begin()
    payload = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert payload["kind"] == "bench"
    assert payload["status"] == "running"
    assert payload["run_id"] == "run"
    assert payload["pairings"] == []
    assert payload["n_games_done"] == 0
    assert payload["n_games_total"] == 0
    assert payload["weights_path"] == "trained_weights/v6/weights.pt"
    assert payload["budgets"] == [[4, 200]]
    assert payload["include_belief"] is False
    assert payload["belief_m_candidates"] == 64
    assert payload["nn_device"] == "cpu"
    assert payload["ended_at"] is None
    assert "git_commit" in payload


def test_start_pairing_appears_in_snapshot(tmp_path: Path):
    progress = _make(tmp_path / "run.json")
    progress.begin()
    progress.start_pairing(
        challenger="ISMCTS-uniform",
        defender="PIMC",
        n_games=4,
        samples=4,
        inner_nodes=200,
        total_iterations=800,
    )
    payload = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert len(payload["pairings"]) == 1
    p = payload["pairings"][0]
    assert p["challenger"] == "ISMCTS-uniform"
    assert p["defender"] == "PIMC"
    assert p["n_games"] == 4
    assert p["samples"] == 4
    assert p["inner_nodes"] == 200
    assert p["total_iterations"] == 800
    assert p["status"] == "running"
    assert p["n_games_done"] == 0
    assert p["n_decided"] == 0
    assert p["verdict"] == "pending"
    # Run-level n_games_total now reflects the open pairing.
    assert payload["n_games_total"] == 4


def test_first_start_pairing_triggers_begin(tmp_path: Path):
    """If the driver forgets ``begin()``, the first
    ``start_pairing`` should still produce a valid snapshot."""
    progress = _make(tmp_path / "run.json")
    progress.start_pairing(
        challenger="ISMCTS-uniform", defender="PIMC", n_games=2,
    )
    payload = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert payload["status"] == "running"
    assert len(payload["pairings"]) == 1


def test_record_game_updates_current_pairing(tmp_path: Path):
    """Per-game record_game accumulates on the current pairing
    only, with throttled flushes between."""
    progress = _make(tmp_path / "run.json", flush_interval_s=0.0)
    progress.begin()
    progress.start_pairing(
        challenger="A", defender="B", n_games=4,
    )
    progress.record_game(winner=0)
    progress.record_game(winner=0)
    progress.record_game(winner=1)
    progress.record_game(winner=None)
    payload = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    p = payload["pairings"][0]
    assert p["challenger_wins"] == 2
    assert p["defender_wins"] == 1
    assert p["draws"] == 1
    assert p["n_decided"] == 3
    assert p["n_games_done"] == 4
    # 2/3 challenger wins on 3 decided games -> wilson interval
    # straddles 0.5 -> verdict 'comparable'.
    assert p["win_rate"] == 2 / 3
    assert p["verdict"] in {"comparable", "stronger", "weaker"}


def test_record_game_crashed_excluded_from_wilson(tmp_path: Path):
    """Crashed games count toward n_games_done but stay out of the
    win/draw counters and the Wilson CI denominator."""
    progress = _make(tmp_path / "run.json", flush_interval_s=0.0)
    progress.begin()
    progress.start_pairing(
        challenger="A", defender="B", n_games=4,
    )
    progress.record_game(winner=0)
    progress.record_game(winner=1)
    progress.record_game(winner=None, crashed=True)
    progress.record_game(winner=None, crashed=True)
    payload = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    p = payload["pairings"][0]
    assert p["challenger_wins"] == 1
    assert p["defender_wins"] == 1
    assert p["draws"] == 0
    assert p["crashed"] == 2
    # 4 games seen but only 2 decided, so n_decided=2.
    assert p["n_games_done"] == 4
    assert p["n_decided"] == 2
    # win_rate = 1/2; CI brackets 0.5; verdict 'comparable'.
    assert p["win_rate"] == 0.5
    assert p["verdict"] == "comparable"


def test_record_pairing_result_overwrites_current(tmp_path: Path):
    """Bulk-update the current pairing from totals (the bench script
    uses this since it gets totals from run_match_parallel)."""
    progress = _make(tmp_path / "run.json")
    progress.begin()
    progress.start_pairing(
        challenger="ISMCTS-uniform", defender="PIMC", n_games=4,
    )
    progress.record_pairing_result(
        challenger_wins=3, defender_wins=1, draws=0, crashed=0,
        elapsed_seconds=12.5,
    )
    payload = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    p = payload["pairings"][0]
    assert p["challenger_wins"] == 3
    assert p["defender_wins"] == 1
    assert p["n_decided"] == 4
    assert p["n_games_done"] == 4
    assert p["elapsed_seconds"] == 12.5
    assert p["verdict"] in {"comparable", "stronger"}


def test_finish_pairing_marks_completed(tmp_path: Path):
    progress = _make(tmp_path / "run.json")
    progress.begin()
    progress.start_pairing(
        challenger="A", defender="B", n_games=2,
    )
    progress.record_pairing_result(
        challenger_wins=2, defender_wins=0, draws=0,
    )
    progress.finish_pairing(status="completed")
    payload = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    p = payload["pairings"][0]
    assert p["status"] == "completed"
    assert p["ended_at"] is not None


def test_multiple_pairings(tmp_path: Path):
    """Two sequential pairings — the second is the 'current' one
    after start_pairing; finish + finalize close them all out."""
    progress = _make(
        tmp_path / "run.json",
        n_games_per_pairing=2,
        budgets=[(2, 50), (4, 200)],
    )
    progress.begin()

    progress.start_pairing(
        challenger="ISMCTS-uniform", defender="PIMC", n_games=2,
        samples=2, inner_nodes=50, total_iterations=100,
    )
    progress.record_pairing_result(
        challenger_wins=1, defender_wins=1, draws=0,
    )
    progress.finish_pairing(status="completed")

    progress.start_pairing(
        challenger="ISMCTS-uniform", defender="PIMC", n_games=2,
        samples=4, inner_nodes=200, total_iterations=800,
    )
    progress.record_pairing_result(
        challenger_wins=2, defender_wins=0, draws=0,
    )
    progress.finish_pairing(status="completed")
    progress.finalize(status="completed")

    payload = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert payload["status"] == "completed"
    assert payload["ended_at"] is not None
    assert len(payload["pairings"]) == 2
    assert payload["pairings"][0]["total_iterations"] == 100
    assert payload["pairings"][1]["total_iterations"] == 800
    # n_games_total / n_games_done aggregate across all pairings.
    assert payload["n_games_total"] == 4
    assert payload["n_games_done"] == 4


def test_finalize_with_open_pairing_closes_it(tmp_path: Path):
    """If the bench dies mid-pairing, ``finalize(status='failed')``
    should mark both the run AND the orphan pairing as failed so
    the UI doesn't show a perma-running pairing."""
    progress = _make(tmp_path / "run.json")
    progress.begin()
    progress.start_pairing(
        challenger="A", defender="B", n_games=4,
    )
    progress.record_game(winner=0)
    progress.finalize(status="failed")
    payload = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["pairings"][0]["status"] == "failed"


def test_record_game_before_start_pairing_raises(tmp_path: Path):
    progress = _make(tmp_path / "run.json")
    progress.begin()
    try:
        progress.record_game(winner=0)
    except RuntimeError as e:
        assert "start_pairing" in str(e)
    else:  # pragma: no cover - test would have already failed
        raise AssertionError("expected RuntimeError")


def test_record_pairing_result_before_start_pairing_raises(
    tmp_path: Path,
):
    progress = _make(tmp_path / "run.json")
    progress.begin()
    try:
        progress.record_pairing_result(
            challenger_wins=1, defender_wins=0, draws=0,
        )
    except RuntimeError as e:
        assert "start_pairing" in str(e)
    else:  # pragma: no cover
        raise AssertionError("expected RuntimeError")


def test_finish_pairing_before_start_raises(tmp_path: Path):
    progress = _make(tmp_path / "run.json")
    progress.begin()
    try:
        progress.finish_pairing()
    except RuntimeError as e:
        assert "start_pairing" in str(e)
    else:  # pragma: no cover
        raise AssertionError("expected RuntimeError")


def test_record_game_throttles_disk_writes(tmp_path: Path):
    """With a long flush_interval_s, only begin/start_pairing/
    finish_pairing/finalize touch disk — record_game accumulates
    in memory."""
    progress = _make(tmp_path / "run.json", flush_interval_s=10_000.0)
    progress.begin()
    progress.start_pairing(challenger="A", defender="B", n_games=50)
    mtime_before_games = (tmp_path / "run.json").stat().st_mtime_ns
    for _ in range(50):
        progress.record_game(winner=0)
    # No flush should have happened — start_pairing was the last.
    assert (
        (tmp_path / "run.json").stat().st_mtime_ns
        == mtime_before_games
    )
    progress.finish_pairing(status="completed")
    progress.finalize(status="completed")
    final = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert final["pairings"][0]["challenger_wins"] == 50
    assert final["pairings"][0]["n_decided"] == 50


def test_pending_verdict_until_first_decided_game(tmp_path: Path):
    """Verdict stays at 'pending' as long as n_decided is 0 — the
    Wilson CI on (0, 0) is (0.0, 1.0), which would otherwise classify
    as 'comparable' and mislead the operator."""
    progress = _make(tmp_path / "run.json", flush_interval_s=0.0)
    progress.begin()
    progress.start_pairing(challenger="A", defender="B", n_games=4)
    payload = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert payload["pairings"][0]["verdict"] == "pending"
    progress.record_game(winner=None)  # draw, still no decided games
    payload = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert payload["pairings"][0]["verdict"] == "pending"


def test_verdict_classifies_strong_signal(tmp_path: Path):
    """20 wins / 0 losses => CI lower bound ≫ 0.5 => 'stronger'."""
    progress = _make(tmp_path / "run.json", flush_interval_s=0.0)
    progress.begin()
    progress.start_pairing(challenger="A", defender="B", n_games=20)
    for _ in range(20):
        progress.record_game(winner=0)
    payload = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    p = payload["pairings"][0]
    assert p["challenger_wins"] == 20
    assert p["defender_wins"] == 0
    assert p["verdict"] == "stronger"
    assert p["ci_low"] > 0.5


def test_atomic_writes_under_concurrent_reads(tmp_path: Path):
    """Same atomicity guarantee as the other trackers — flushing on
    every record_game while a tight-poll reader is open should never
    surface a half-written JSON."""
    progress = _make(tmp_path / "run.json", flush_interval_s=0.0)
    progress.begin()
    progress.start_pairing(challenger="A", defender="B", n_games=200)
    stop = threading.Event()
    decode_errors: list[Exception] = []
    parses: list[dict] = []

    def _reader() -> None:
        while not stop.is_set():
            try:
                if (tmp_path / "run.json").is_file():
                    parses.append(json.loads(
                        (tmp_path / "run.json").read_text(
                            encoding="utf-8",
                        ),
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
                winner=0 if i % 3 == 0 else (
                    1 if i % 3 == 1 else None
                ),
            )
        progress.finish_pairing(status="completed")
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


def test_record_pairing_result_clamps_negative_wins(tmp_path: Path):
    """Defensive: a buggy caller passing a negative win count must
    not blow up the snapshot writer. Wilson interval clamps the
    counts and proceeds."""
    progress = _make(tmp_path / "run.json")
    progress.begin()
    progress.start_pairing(challenger="A", defender="B", n_games=4)
    # Overwriting with the Wilson-helper-friendly clamp path —
    # n_decided becomes -1 + 1 = 0; we just want no crash.
    progress.record_pairing_result(
        challenger_wins=-1, defender_wins=1, draws=0,
    )
    payload = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    p = payload["pairings"][0]
    # ci_low/ci_high stay finite even with the negative input.
    assert 0.0 <= p["ci_low"] <= 1.0
    assert 0.0 <= p["ci_high"] <= 1.0


def test_wilson_helper_clamps_out_of_range_inputs():
    """``_wilson_interval`` defensively clamps successes outside the
    [0, trials] window rather than raising. Mirrors the ValueError
    path of the script-level helper, but inside the snapshot writer
    we never want a bad count to take down the whole flush.
    """
    from mtg_bot.training.progress import _wilson_interval

    # successes < 0 — clamp up to 0.
    low, high = _wilson_interval(-1, 10)
    assert 0.0 <= low <= high <= 1.0
    # successes > trials — clamp down to trials.
    low, high = _wilson_interval(11, 10)
    assert 0.0 <= low <= high <= 1.0


def test_classify_verdict_weaker_branch():
    """``_classify_verdict`` hits its 'weaker' branch when the upper
    CI bound is strictly below 0.5 — covered here since the
    BenchProgress lifecycle tests don't naturally hit a 100%-loss
    pairing."""
    from mtg_bot.training.progress import _classify_verdict

    assert _classify_verdict(0.05, 0.45) == "weaker"


def test_throughput_stats_default_none(tmp_path: Path):
    """Pairings that never call ``set_throughput_stats`` keep both
    throughput fields at ``None`` in the JSON. The strength A/B
    bench falls in this bucket — the UI should be able to detect
    'no throughput data' and hide the column."""
    progress = _make(tmp_path / "run.json")
    progress.begin()
    progress.start_pairing(challenger="A", defender="B", n_games=2)
    progress.record_pairing_result(
        challenger_wins=1, defender_wins=1, draws=0,
    )
    progress.finish_pairing(status="completed")
    progress.finalize(status="completed")
    payload = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    p = payload["pairings"][0]
    assert "games_per_hour" in p
    assert "sec_per_game_per_worker" in p
    assert p["games_per_hour"] is None
    assert p["sec_per_game_per_worker"] is None


def test_set_throughput_stats_lands_in_json(tmp_path: Path):
    """``set_throughput_stats`` stamps the two numbers onto the
    current pairing and forces a flush so the UI sees them
    immediately. Mirrors the bench_per_game_wall.py end-of-run
    call site."""
    progress = _make(tmp_path / "run.json")
    progress.begin()
    progress.start_pairing(challenger="A", defender="B", n_games=4)
    progress.record_pairing_result(
        challenger_wins=2, defender_wins=2, draws=0,
    )
    # Synthetic throughput: 24 workers, 60s mean per game →
    # 3600 / 60 * 24 = 1440 games/hour.
    progress.set_throughput_stats(
        games_per_hour=1440.0,
        sec_per_game_per_worker=60.0,
    )
    payload = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    p = payload["pairings"][0]
    assert p["games_per_hour"] == 1440.0
    assert p["sec_per_game_per_worker"] == 60.0
    # Survives finalize roundtrip too.
    progress.finish_pairing(status="completed")
    progress.finalize(status="completed")
    payload = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    p = payload["pairings"][0]
    assert p["games_per_hour"] == 1440.0
    assert p["sec_per_game_per_worker"] == 60.0


def test_set_throughput_stats_accepts_none(tmp_path: Path):
    """Drivers that compute one stat but not the other (or want to
    reset) can pass ``None``; the field stores ``None`` in the JSON
    rather than crashing on float-cast."""
    progress = _make(tmp_path / "run.json")
    progress.begin()
    progress.start_pairing(challenger="A", defender="B", n_games=2)
    progress.set_throughput_stats(
        games_per_hour=None, sec_per_game_per_worker=None,
    )
    payload = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    p = payload["pairings"][0]
    assert p["games_per_hour"] is None
    assert p["sec_per_game_per_worker"] is None


def test_set_throughput_stats_before_start_raises(tmp_path: Path):
    progress = _make(tmp_path / "run.json")
    progress.begin()
    try:
        progress.set_throughput_stats(
            games_per_hour=100.0, sec_per_game_per_worker=10.0,
        )
    except RuntimeError as e:
        assert "start_pairing" in str(e)
    else:  # pragma: no cover
        raise AssertionError("expected RuntimeError")
