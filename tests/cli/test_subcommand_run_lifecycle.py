"""End-to-end test that ``mtg_bot eval``'s ``main()`` body
correctly issues the start_run -> push_eval_summary -> finish_run
trio against the SQLite run DB.

Post v2-cutover the body drives the REST orchestrator
(``run_stage`` against the coordinator + worker daemons) instead of
the SSH-based ``run_distributed_eval``. The lifecycle contract under
test is the same — start_run, then push counters via
``push_eval_summary``, then finish_run('completed' / 'failed' /
'killed') based on how main() exits. These tests stub
``_rest_orch.run_stage`` so the heavy distributed-runtime work is
not exercised; the observable is the rows that land in runs.db.
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from mtg_bot import distributed_rest_orchestrator as _rest_orch
from mtg_bot.cli import eval as cli_eval
from mtg_bot.cli.runs import db as runs_db, lifecycle


def _v2_shards_config(tmp_path: Path) -> Path:
    p = tmp_path / "shards.json"
    p.write_text(
        json.dumps({"worker_urls": ["http://worker-a:5198"]}),
        encoding="utf-8",
    )
    return p


def _common_setup(monkeypatch, tmp_path):
    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", str(db_path))
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    monkeypatch.setattr(lifecycle, "git_commit_short", lambda: "abc1234")
    # Skip the real deck-pool load — the orchestrator only needs the
    # size to populate per-game ``deck_indices``.
    monkeypatch.setattr(cli_eval, "_count_decks_in_pool", lambda p: 4)
    return db_path


def _base_argv(shards: Path, deck_pool: Path, progress_dir: Path,
               *, games: int = 622, seed: int = 42,
               nodes: int = 200, samples: int = 4) -> list[str]:
    return [
        "--new", "v16", "--old", "v13",
        "--games", str(games),
        "--shards-config", str(shards),
        "--progress-dir", str(progress_dir),
        "--deck-pool", str(deck_pool),
        "--queue-url", "http://master:5099",
        "--bundle-url", "http://master:5099/repo.bundle",
        "--seed", str(seed),
        "--nodes", str(nodes),
        "--samples", str(samples),
        "--poll-interval-s", "0.0",
    ]


def test_eval_main_round_trips_start_summary_finish(
    monkeypatch, tmp_path,
):
    db_path = _common_setup(monkeypatch, tmp_path)
    progress_dir = tmp_path / "training_progress"
    deck_pool = tmp_path / "decks.json.gz"
    deck_pool.write_bytes(b"")
    shards = _v2_shards_config(tmp_path)

    captured: dict = {}

    def fake_run_stage(*, coordinator_url, worker_urls, spec,
                       poll_interval_s, **kwargs):
        captured["coordinator_url"] = coordinator_url
        captured["spec"] = spec
        # Touch a progress JSON so the lifecycle artifact registration
        # sees a real file.
        progress_json = progress_dir / f"{spec.stage_id}.json"
        progress_json.parent.mkdir(parents=True, exist_ok=True)
        progress_json.write_text("{}", encoding="utf-8")
        return _rest_orch.StageResult(
            stage_id=spec.stage_id, status="complete",
            n_games_done=620, crashed=2, timed_out=0,
            wins_new=320, wins_old=290, draws=10,
        )

    with patch.object(_rest_orch, "run_stage", fake_run_stage):
        cli_eval.main(_base_argv(shards, deck_pool, progress_dir))

    assert captured["coordinator_url"] == "http://master:5099"
    assert captured["spec"].stage_id == "eval_v16_vs_v13_622g"

    # Verify DB rows landed.
    conn = runs_db.connect(db_path)
    try:
        run_rows = list(conn.execute("SELECT * FROM runs"))
        progress_rows = list(conn.execute("SELECT * FROM run_progress"))
        artifact_rows = list(conn.execute("SELECT * FROM run_artifacts"))
    finally:
        conn.close()

    assert len(run_rows) == 1
    run_id = run_rows[0]["run_id"]
    assert run_id == "eval_v16_vs_v13_622g"
    assert run_rows[0]["status"] == "completed"
    assert run_rows[0]["kind"] == "eval"
    assert run_rows[0]["git_commit"] == "abc1234"
    config = json.loads(run_rows[0]["config_json"])
    assert config["new"] == "v16"
    assert config["old"] == "v13"
    assert config["games"] == 622

    assert len(progress_rows) == 1
    p = progress_rows[0]
    assert p["wins_new"] == 320
    assert p["wins_old"] == 290
    assert p["draws"] == 10
    assert p["crashed"] == 2
    assert p["n_games_total"] == 622
    extra = json.loads(p["extra_json"])
    assert extra["win_rate"] == pytest.approx(320 / 610)

    # Progress JSON registered as an artifact.
    assert len(artifact_rows) == 1
    assert artifact_rows[0]["artifact_type"] == "progress_json"


def test_eval_main_marks_failed_on_exception(monkeypatch, tmp_path):
    """If ``run_stage`` raises, the lifecycle CM catches → finish_run
    with status=failed → re-raises."""
    db_path = _common_setup(monkeypatch, tmp_path)
    progress_dir = tmp_path / "training_progress"
    deck_pool = tmp_path / "decks.json.gz"
    deck_pool.write_bytes(b"")
    shards = _v2_shards_config(tmp_path)

    def boom(*a, **kw):
        raise RuntimeError("stage crashed")

    with patch.object(_rest_orch, "run_stage", boom):
        with pytest.raises(RuntimeError, match="stage crashed"):
            cli_eval.main(_base_argv(shards, deck_pool, progress_dir,
                                     games=10))

    conn = runs_db.connect(db_path)
    try:
        rows = list(conn.execute("SELECT status, notes FROM runs"))
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0]["status"] == "failed"
    assert "RuntimeError" in (rows[0]["notes"] or "")
    assert "stage crashed" in (rows[0]["notes"] or "")


def test_eval_main_marks_killed_on_sigint(monkeypatch, tmp_path):
    """KeyboardInterrupt mid-run lands in the DB as status=killed."""
    db_path = _common_setup(monkeypatch, tmp_path)
    progress_dir = tmp_path / "training_progress"
    deck_pool = tmp_path / "decks.json.gz"
    deck_pool.write_bytes(b"")
    shards = _v2_shards_config(tmp_path)

    def interrupted(*a, **kw):
        raise KeyboardInterrupt()

    with patch.object(_rest_orch, "run_stage", interrupted):
        with pytest.raises(KeyboardInterrupt):
            cli_eval.main(_base_argv(shards, deck_pool, progress_dir,
                                     games=10))

    conn = runs_db.connect(db_path)
    try:
        rows = list(conn.execute("SELECT status FROM runs"))
    finally:
        conn.close()
    assert rows[0]["status"] == "killed"
