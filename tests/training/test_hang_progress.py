"""Tests for ``mtg_bot.training._hang_progress.HangProgress``.

The progress sentinel is shared between the inner-game thread and the
parent timeout handler. We test:

  - ``record`` updates fields and bumps ``decisions_completed``.
  - ``snapshot`` returns a JSON-serializable dict with the derived
    ``seconds_since_last_update`` and ``total_elapsed_sec`` fields.
  - ``record`` truncates oversized decision repr's to keep dumps small.
  - ``record`` never raises when ``repr()`` of the decision throws.
  - Integration: a TimeoutError raised inside the data-gen / self-play
    timeout handler dumps a hang JSON containing ``progress`` populated
    from the sentinel.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from mtg_bot.training._hang_progress import HangProgress


def test_record_updates_fields_and_bumps_decisions():
    p = HangProgress()
    assert p.decisions_completed == 0
    assert p.last_active_player is None

    p.record(active=0, decision="PassPriority()", n_legal=2)
    assert p.decisions_completed == 1
    assert p.last_active_player == 0
    assert p.last_decision_repr == "'PassPriority()'"  # repr of a str
    assert p.last_n_legal == 2

    p.record(active=1, decision=42, n_legal=5)
    assert p.decisions_completed == 2
    assert p.last_active_player == 1
    assert p.last_decision_repr == "42"
    assert p.last_n_legal == 5


def test_snapshot_returns_serializable_dict_with_derived_fields():
    p = HangProgress()
    p.record(active=0, decision="X", n_legal=3)
    snap = p.snapshot()
    # Must be json-serializable (dump_hang_diagnostics jsons it).
    json.dumps(snap)
    assert snap["decisions_completed"] == 1
    assert snap["last_active_player"] == 0
    assert snap["last_decision_repr"] == "'X'"
    assert snap["last_n_legal"] == 3
    assert snap["seconds_since_last_update"] >= 0.0
    assert snap["total_elapsed_sec"] >= 0.0


def test_record_truncates_long_repr():
    p = HangProgress()
    huge = "a" * 1000
    p.record(active=0, decision=huge, n_legal=1)
    # repr adds the surrounding quotes; we cap at 160 chars total.
    assert len(p.last_decision_repr) == 160


def test_record_swallows_repr_exceptions():
    class _Exploding:
        def __repr__(self):  # pragma: no cover - tested via record
            raise RuntimeError("boom")

    p = HangProgress()
    # Must not raise.
    p.record(active=0, decision=_Exploding(), n_legal=0)
    assert p.last_decision_repr == "<unrepr-able>"
    assert p.decisions_completed == 1


def test_snapshot_seconds_since_last_update_grows():
    p = HangProgress()
    p.record(active=0, decision="X", n_legal=1)
    snap1 = p.snapshot()
    time.sleep(0.05)
    snap2 = p.snapshot()
    # Allow tiny clock noise; snap2 should be later than snap1.
    assert snap2["seconds_since_last_update"] >= snap1[
        "seconds_since_last_update"
    ]


# -----------------------------------------------------------------
# Integration: confirm the timeout handler dumps include the
# ``progress`` field. We monkey-patch ``run_with_timeout`` to (a) call
# the inner function for a few decisions then raise TimeoutError, so we
# can verify the sentinel was actually updated, and (b) avoid spinning
# up a full game.
# -----------------------------------------------------------------


def _drive_progress(progress: HangProgress, n: int) -> None:
    """Call ``progress.record`` ``n`` times to simulate decisions before
    a hang fires."""
    for i in range(n):
        progress.record(active=i % 2, decision=f"D{i}", n_legal=3)


def test_data_gen_timeout_dump_contains_progress(
    tmp_path: Path, monkeypatch,
):
    from mtg_bot.training import _timeout
    from mtg_bot.training import random_choice_factory
    from mtg_bot.training.data_gen import _generate_one_game_data
    from tests._test_decks import simple_test_deck_pool

    # ``run_with_timeout(func, args, timeout)`` — drive the progress
    # sentinel that's been threaded into ``args`` for a few iterations,
    # then raise. Progress is identified by isinstance check rather
    # than positional index because the diagnostic-deep-capture feature
    # added trailing ``tree_depth`` / ``tree_top_k`` ints after the
    # progress slot — index lookup is brittle to that.
    def fake_run_with_timeout(func, args, timeout_sec):
        progress = next(a for a in args if isinstance(a, HangProgress))
        _drive_progress(progress, 7)
        raise TimeoutError("simulated hang at decision 7")

    monkeypatch.setattr(
        _timeout, "run_with_timeout", fake_run_with_timeout,
    )

    dump_dir = tmp_path / "hangs"
    with pytest.raises(TimeoutError):
        _generate_one_game_data(
            game_idx=11,
            p0_factory=random_choice_factory,
            p1_factory=random_choice_factory,
            base_seed=99,
            decision_cap=4000,
            sample_every=1,
            per_game_timeout_sec=300.0,
            hang_dump_dir=str(dump_dir),
            deck_pool=simple_test_deck_pool(),
        )
    files = sorted(dump_dir.iterdir())
    assert len(files) == 2
    meta = next(f for f in files if f.suffix == ".json")
    payload = json.loads(meta.read_text(encoding="utf-8"))
    assert "progress" in payload
    assert payload["progress"]["decisions_completed"] == 7
    assert payload["progress"]["last_decision_repr"] == "'D6'"
    assert payload["progress"]["last_active_player"] == 0  # 6 % 2 == 0


def test_self_play_timeout_dump_contains_progress(
    tmp_path: Path, monkeypatch,
):
    from mtg_bot.training import _timeout
    from mtg_bot.training import random_choice_factory
    from mtg_bot.training.self_play import _play_one_match_game
    from tests._test_decks import simple_test_deck_pool

    def fake_run_with_timeout(func, args, timeout_sec):
        # Locate the progress sentinel by isinstance — the args tuple
        # gained trailing tree_depth / tree_top_k ints with the
        # diagnostic-deep-capture feature, so positional indexing is
        # brittle.
        progress = next(a for a in args if isinstance(a, HangProgress))
        _drive_progress(progress, 4)
        raise TimeoutError("simulated hang at decision 4")

    monkeypatch.setattr(
        _timeout, "run_with_timeout", fake_run_with_timeout,
    )

    dump_dir = tmp_path / "hangs"
    with pytest.raises(TimeoutError):
        _play_one_match_game(
            game_idx=2,
            p0_factory=random_choice_factory,
            p1_factory=random_choice_factory,
            base_seed=42,
            decision_cap=4000,
            per_game_timeout_sec=300.0,
            hang_dump_dir=str(dump_dir),
            deck_pool=simple_test_deck_pool(),
        )
    files = sorted(dump_dir.iterdir())
    assert len(files) == 2
    meta = next(f for f in files if f.suffix == ".json")
    payload = json.loads(meta.read_text(encoding="utf-8"))
    assert "progress" in payload
    assert payload["progress"]["decisions_completed"] == 4
    assert payload["progress"]["last_decision_repr"] == "'D3'"


def test_heartbeat_disabled_by_default(tmp_path: Path):
    """No ``heartbeat_path`` → no file is created, even after many
    record() calls. Existing callers (sequential ``run_match``, unit
    tests that don't opt in) pay zero overhead and leave no side-
    effects on disk."""
    p = HangProgress()
    for i in range(200):
        p.record(active=i % 2, decision=f"D{i}", n_legal=3)
    # No path → no file written anywhere.
    assert list(tmp_path.iterdir()) == []


def test_heartbeat_respects_both_decisions_and_seconds_throttle(
    tmp_path: Path,
):
    """The user asked for "every 50 decisions or every 5 seconds,
    whichever is sparser" — sparser = longer gap = the AND of the
    two thresholds. Drive 150 decisions without any sleep: the
    decisions threshold is satisfied 3x but the 5-second threshold
    isn't, so no heartbeat is emitted."""
    hb_path = tmp_path / "hb.jsonl"
    p = HangProgress(
        heartbeat_path=hb_path,
        heartbeat_every_n_decisions=50,
        heartbeat_min_seconds=5.0,
    )
    for i in range(150):
        p.record(active=i % 2, decision=f"D{i}", n_legal=3)
    # Decisions met 50/100/150, but no real time passed → no emit.
    assert not hb_path.exists() or hb_path.read_text() == ""


def test_heartbeat_emits_when_both_thresholds_met(tmp_path: Path):
    """Tunable thresholds let the test exercise the emit path without
    actually sleeping for 5 seconds. With min_seconds=0.0, every
    Nth-decision call should emit."""
    hb_path = tmp_path / "hb.jsonl"
    p = HangProgress(
        heartbeat_path=hb_path,
        heartbeat_every_n_decisions=10,
        heartbeat_min_seconds=0.0,
    )
    for i in range(35):
        p.record(active=i % 2, decision=f"D{i}", n_legal=3)
    # 10, 20, 30 → three heartbeats.
    lines = hb_path.read_text().strip().splitlines()
    assert len(lines) == 3
    payloads = [json.loads(line) for line in lines]
    assert payloads[0]["decisions_completed"] == 10
    assert payloads[1]["decisions_completed"] == 20
    assert payloads[2]["decisions_completed"] == 30
    for pl in payloads:
        assert pl["event"] == "game_heartbeat"
        assert pl["reason"] == "periodic"
        assert "ts" in pl
        assert "last_decision_repr" in pl


def test_emit_final_heartbeat_writes_irrespective_of_throttle(
    tmp_path: Path,
):
    """The timeout path needs a guaranteed write even if only 7
    decisions have happened and no periodic emit was due. The
    final heartbeat marks the moment the timeout fired so post-hoc
    triage can see exactly how far the game got."""
    hb_path = tmp_path / "hb.jsonl"
    p = HangProgress(
        heartbeat_path=hb_path,
        heartbeat_every_n_decisions=50,  # way more than 7
        heartbeat_min_seconds=5.0,
    )
    for i in range(7):
        p.record(active=i % 2, decision=f"D{i}", n_legal=3)
    assert not hb_path.exists()  # throttle blocked periodic emit
    p.emit_final_heartbeat(reason="timed_out")
    payloads = [
        json.loads(line) for line in hb_path.read_text().splitlines()
    ]
    assert len(payloads) == 1
    assert payloads[0]["reason"] == "timed_out"
    assert payloads[0]["decisions_completed"] == 7


def test_emit_final_heartbeat_no_op_without_path(tmp_path: Path):
    """Final-flush helper is a safe no-op when the path is unset —
    callers can invoke unconditionally without an existence check."""
    p = HangProgress()
    p.record(active=0, decision="X", n_legal=1)
    p.emit_final_heartbeat(reason="timed_out")  # must not raise
    # And nothing on disk.
    assert list(tmp_path.iterdir()) == []


def test_heartbeat_io_errors_dont_break_record(monkeypatch):
    """Diagnostic side-channel must never propagate I/O errors — if
    the heartbeat file is on a full disk or its directory has been
    deleted out from under us, the game loop must continue. We force
    the failure by pointing at a path whose parent is a regular file
    (so mkdir() will raise OSError)."""
    import tempfile
    with tempfile.NamedTemporaryFile() as fp:
        # Path under a regular file → mkdir() raises NotADirectoryError.
        bad_path = Path(fp.name) / "subdir" / "hb.jsonl"
        p = HangProgress(
            heartbeat_path=bad_path,
            heartbeat_every_n_decisions=1,
            heartbeat_min_seconds=0.0,
        )
        # Must not raise.
        p.record(active=0, decision="X", n_legal=1)
        # And the regular fields still get updated.
        assert p.decisions_completed == 1


def test_hang_dump_progress_classifies_real_vs_slow():
    """The whole point of the progress sentinel: a triage reader can
    classify a hang dump as
      (a) `decisions_completed` near 0 + large
          `seconds_since_last_update` -> real engine pathology, or
      (b) `decisions_completed` in the hundreds + recent
          `seconds_since_last_update` -> slow but progressing.
    This test pins the snapshot semantics so future readers can rely
    on them.
    """
    # Case (a): few decisions, long stall.
    stuck = HangProgress()
    stuck.record(active=0, decision="STUCK", n_legal=2)
    # Force the last_update_at backwards to simulate a long stall
    # without sleeping in the test.
    stuck.last_update_at -= 250.0
    snap_a = stuck.snapshot()
    assert snap_a["decisions_completed"] == 1
    assert snap_a["seconds_since_last_update"] >= 250.0

    # Case (b): many decisions, recent update.
    busy = HangProgress()
    for i in range(600):
        busy.record(active=i % 2, decision=f"D{i}", n_legal=3)
    snap_b = busy.snapshot()
    assert snap_b["decisions_completed"] == 600
    assert snap_b["seconds_since_last_update"] < 1.0
