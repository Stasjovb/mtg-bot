"""Loud failure when a self-play stage yields no usable data.

2026-09-23: 500 distributed self-play games ran, the coordinator's
stage view reported ``n_games_done=500`` with ~1M ``n_samples``, and
zero ``.npz`` files reached ``iterate_data_s2/``. ``mtg_bot iterate``
then died on ``ZeroDivisionError`` at the ``n_policy / n_samples``
print -- a stack trace that names neither the cause nor the fix.

Root cause: both worker daemons ran the test-only
``--artifact-storage-uri null://`` default, so the coordinator's
report job could not fetch the artifact and wrote
``outcome='upload_failed'`` rows -- but the stage aggregate still
counted the game and its n_samples, so nothing upstream noticed.

This file pins the two halves of the fix:
- ``queue_db.stage_counters`` surfaces ``upload_failed`` per machine
  and in total (and ``StageResult`` carries it through).
- ``iterate.self_play_yield_error`` turns both "0 samples" and
  "upload_failed > 0" into one actionable message.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mtg_bot import distributed_rest_orchestrator as _rest_orch
from mtg_bot.cli import iterate as cli_iterate
from mtg_bot.cli.runs import queue_db


# ---------------------------------------------------------------------------
# The pure check
# ---------------------------------------------------------------------------


def test_healthy_stage_returns_none():
    assert cli_iterate.self_play_yield_error(
        stage_id="iter_021_self_play_v5",
        data_dir=Path("iterate_data_s2"),
        n_samples=1_000_000,
        upload_failed=0,
        n_games_done=500,
    ) is None


def test_zero_samples_names_the_stage_data_dir_and_both_causes():
    msg = cli_iterate.self_play_yield_error(
        stage_id="iter_021_self_play_v5",
        data_dir=Path("iterate_data_s2"),
        n_samples=0,
        n_games_done=500,
    )
    assert msg is not None
    assert "iter_021_self_play_v5" in msg
    assert "--data-dir" in msg
    assert "iterate_data_s2" in msg
    # Cause 1: worker dropping artifacts.
    assert "null://" in msg
    assert "--artifact-storage-uri" in msg
    # Cause 2: coordinator writing them somewhere else.
    assert "--iterate-data-dir" in msg
    assert "n_games_done=500" in msg


def test_upload_failed_is_a_hard_error_even_with_samples():
    """The insidious case: SOME games landed, so ``n_samples`` is
    non-zero and the old code would happily train on a partial
    dataset."""
    msg = cli_iterate.self_play_yield_error(
        stage_id="iter_021_self_play_v5",
        data_dir=Path("iterate_data_s2"),
        n_samples=4200,
        upload_failed=37,
        n_games_done=500,
    )
    assert msg is not None
    assert "37 upload_failed" in msg
    assert "null://" in msg
    assert "--iterate-data-dir" in msg


def test_message_omits_stage_view_line_when_games_done_unknown():
    msg = cli_iterate.self_play_yield_error(
        stage_id="s", data_dir=Path("d"), n_samples=0,
    )
    assert msg is not None
    assert "n_games_done" not in msg


def test_zero_samples_wins_over_upload_failed_in_the_headline():
    msg = cli_iterate.self_play_yield_error(
        stage_id="s", data_dir=Path("d"), n_samples=0, upload_failed=9,
    )
    assert "produced 0 training samples" in msg


# ---------------------------------------------------------------------------
# queue_db surfaces the upload_failed count
# ---------------------------------------------------------------------------


def _stage_with_results(tmp_path: Path, outcomes: list[tuple[str, str]]):
    """Build a queue.db with one self_play stage and one result row
    per ``(shard_label, outcome)`` pair. Returns the connection."""
    conn = queue_db.connect(tmp_path / "queue.db")
    games = [
        {"game_idx": i, "deck_indices": [i, i + 1], "seed": 1000 + i}
        for i in range(len(outcomes))
    ]
    queue_db.insert_stage(
        conn,
        stage_id="st1",
        kind="self_play",
        spec_json='{"games": %s}' % (
            str([{"game_idx": g["game_idx"]} for g in games]).replace("'", '"')
        ),
        claim_ttl_seconds=600,
        games=games,
    )
    for i, (shard, outcome) in enumerate(outcomes):
        claim = queue_db.claim_next_game(
            conn, stage_id="st1", worker_id=shard, now_unix=0.0,
        )
        assert claim is not None
        queue_db.record_report(
            conn,
            claim_id=claim["claim_id"],
            report_meta={
                "claim_id": claim["claim_id"],
                "outcome": outcome,
                "shard_label": shard,
                "n_samples": 0 if outcome == "upload_failed" else 100,
                "duration_s": 1.0,
            },
            npz_path=None if outcome == "upload_failed" else f"/x/{i}.npz",
            replay_path=None,
            artifact_uri="null:///dropped" if outcome == "upload_failed"
            else "file:///x",
        )
    return conn


def test_stage_counters_reports_zero_upload_failed_on_a_clean_stage(tmp_path):
    conn = _stage_with_results(
        tmp_path, [("mac", "completed"), ("master", "completed")],
    )
    counters = queue_db.stage_counters(conn, "st1")
    assert counters["upload_failed"] == 0
    assert all(m["upload_failed"] == 0 for m in counters["machines"])


def test_stage_counters_counts_upload_failed_total_and_per_machine(tmp_path):
    conn = _stage_with_results(tmp_path, [
        ("mac", "upload_failed"),
        ("mac", "upload_failed"),
        ("master", "completed"),
        ("master", "upload_failed"),
    ])
    counters = queue_db.stage_counters(conn, "st1")
    assert counters["upload_failed"] == 3
    # The game still counts as done -- that's precisely why this was
    # invisible before.
    assert counters["n_games_done"] == 4
    per_machine = {m["label"]: m["upload_failed"] for m in counters["machines"]}
    assert per_machine == {"mac": 2, "master": 1}


def test_in_flight_only_machine_row_has_upload_failed_zero(tmp_path):
    """A worker that has claimed but not yet reported shows up via
    the claims join; its row must carry the new key too."""
    conn = queue_db.connect(tmp_path / "queue.db")
    queue_db.insert_stage(
        conn, stage_id="st1", kind="self_play",
        spec_json='{"games": [{"game_idx": 0}]}',
        claim_ttl_seconds=600,
        games=[{"game_idx": 0, "deck_indices": [1, 2], "seed": 7}],
    )
    queue_db.claim_next_game(
        conn, stage_id="st1", worker_id="mac", now_unix=0.0,
    )
    counters = queue_db.stage_counters(conn, "st1")
    assert counters["machines"][0]["upload_failed"] == 0


# ---------------------------------------------------------------------------
# StageResult carries it to the orchestrator
# ---------------------------------------------------------------------------


def test_stage_result_defaults_upload_failed_to_zero():
    """A pre-upgrade coordinator's stage view has no ``upload_failed``
    key; the orchestrator must not blow up or invent failures."""
    res = _rest_orch.StageResult(
        stage_id="s", status="complete", n_games_done=1,
        crashed=0, timed_out=0,
    )
    assert res.upload_failed == 0
    assert res.n_samples == 0


def test_poll_stage_threads_upload_failed_through(monkeypatch):
    payload = {
        "stage_id": "s", "status": "complete", "n_games_done": 500,
        "crashed": 0, "timed_out": 0, "draws": 0,
        "n_samples": 1_000_000, "upload_failed": 500,
    }

    import json as _json

    def fake_get(url, **kwargs):
        return 200, _json.dumps(payload).encode("utf-8")

    res = _rest_orch.poll_stage(
        coordinator_url="http://coord:5099",
        stage_id="s",
        poll_interval_s=0.0,
        http_get=fake_get,
        sleep=lambda _s: None,
    )
    assert res.upload_failed == 500
    assert res.n_samples == 1_000_000


def test_the_2026_09_23_shape_is_caught():
    """End-to-end on the counters: 500 games 'done', ~1M samples
    claimed by the aggregate, but every artifact dropped -> 0 npz
    files on disk. The check must fire."""
    msg = cli_iterate.self_play_yield_error(
        stage_id="iter_021_self_play_v5",
        data_dir=Path("iterate_data_s2"),
        n_samples=0,          # what the npz glob actually finds
        upload_failed=500,    # what the coordinator recorded
        n_games_done=500,     # what the stage view proudly reported
    )
    assert msg is not None
    assert "Refusing to train" in msg


def test_pure_function_does_not_exit(monkeypatch):
    """It returns a string; the CALLERS exit. Keeps it unit-testable
    and keeps the exit policy in one place."""
    def boom(*_a, **_k):  # pragma: no cover - must never run
        raise AssertionError("self_play_yield_error called sys.exit")

    monkeypatch.setattr(cli_iterate.sys, "exit", boom)
    assert cli_iterate.self_play_yield_error(
        stage_id="s", data_dir=Path("d"), n_samples=0,
    ) is not None


@pytest.mark.parametrize("n_samples,upload_failed", [(0, 0), (5, 1), (0, 3)])
def test_all_bad_combinations_produce_a_message(n_samples, upload_failed):
    assert cli_iterate.self_play_yield_error(
        stage_id="s", data_dir=Path("d"),
        n_samples=n_samples, upload_failed=upload_failed,
    ) is not None
