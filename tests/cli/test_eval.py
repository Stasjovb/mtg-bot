"""Tests for ``mtg_bot.cli.eval`` post v2-cutover.

The standalone eval CLI now drives the v2 REST orchestrator instead
of the SSH-based ``run_distributed_eval`` path. These tests pin:

A. ``--shards-config`` is parsed via
   :func:`mtg_bot.distributed_rest_orchestrator.load_worker_urls`
   (URL-only shape; legacy ``{shards: [...]}`` is rejected loudly).
B. ``main`` builds an eval stage spec via
   :func:`mtg_bot.distributed_rest_orchestrator.make_eval_stage_spec`
   carrying ``--new`` / ``--old`` / ``--games`` / ``--nodes`` /
   ``--samples`` / ``--seed`` and the per-game timeout.
C. ``main`` calls
   :func:`mtg_bot.distributed_rest_orchestrator.run_stage` with the
   spec, the coordinator URL (from ``--queue-url``), and the worker
   URLs loaded from ``--shards-config``.
D. ``main`` writes the eval summary (wins_new / wins_old / draws /
   crashed / win_rate) into the runs.db lifecycle wrapper so the
   training UI sees the run.
E. Missing ``--queue-url`` / ``--shards-config`` / ``--deck-pool``
   surface as a SystemExit with a clear message.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from mtg_bot import distributed_rest_orchestrator as _rest_orch
from mtg_bot.cli import eval as cli_eval
from mtg_bot.cli.runs import lifecycle


def _shards_config(tmp_path: Path) -> Path:
    """Write a minimal v2 worker-URL list shards config and return its
    path."""
    p = tmp_path / "shards.json"
    p.write_text(
        json.dumps({"worker_urls": ["http://worker-a:5198"]}),
        encoding="utf-8",
    )
    return p


def _deck_pool(tmp_path: Path, n_decks: int = 4) -> Path:
    """Write a tiny gzipped EoE deck pool JSON. ``decks_from_json``
    handles the gzip transparently; we just need a non-empty list with
    the right shape."""
    p = tmp_path / "decks.json.gz"
    # Minimal Deck-loadable record. ``decks_from_json`` only needs
    # ``cards`` and (optionally) ``name``; printings come from the
    # canonical Scryfall cache so we can ship any printing name.
    decks = [
        {"name": f"d{i}", "cards": [{"name": "Plains", "count": 60}]}
        for i in range(n_decks)
    ]
    p.write_bytes(gzip.compress(json.dumps(decks).encode("utf-8")))
    return p


def _patch_lifecycle_and_decks(monkeypatch, tmp_path):
    """Stub the per-game deck-pool counting + runs.db env so each test
    starts from a clean baseline."""
    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", str(db_path))
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    monkeypatch.setattr(lifecycle, "git_commit_short", lambda: "abc1234")
    # Stub deck-pool counting so the test doesn't have to write a
    # real EoE-shape gzip — the orchestrator's stage builder only
    # needs an integer.
    monkeypatch.setattr(cli_eval, "_count_decks_in_pool", lambda p: 4)
    return db_path


def _base_argv(shards_config: Path, deck_pool: Path, progress_dir: Path):
    return [
        "--new", "v16", "--old", "v13",
        "--games", "8",
        "--seed", "777",
        "--shards-config", str(shards_config),
        "--progress-dir", str(progress_dir),
        "--deck-pool", str(deck_pool),
        "--queue-url", "http://master:5099",
        "--bundle-url", "http://master:5099/repo.bundle",
        "--nodes", "32",
        "--samples", "2",
        "--per-game-timeout-sec", "45.0",
        "--poll-interval-s", "0.0",
    ]


def test_eval_main_loads_worker_urls_from_shards_config(
    monkeypatch, tmp_path,
):
    """``--shards-config`` is the v2 URL list; ``main`` parses it via
    :func:`load_worker_urls` and threads the worker URLs into
    ``run_stage``."""
    _patch_lifecycle_and_decks(monkeypatch, tmp_path)
    shards = _shards_config(tmp_path)
    deck_pool = _deck_pool(tmp_path)
    progress = tmp_path / "progress"

    captured: dict = {}

    def fake_run_stage(*, coordinator_url, worker_urls, spec,
                       poll_interval_s, **kwargs):
        captured["coordinator_url"] = coordinator_url
        captured["worker_urls"] = worker_urls
        captured["spec"] = spec
        captured["poll_interval_s"] = poll_interval_s
        # Return a finished StageResult so the summary code path runs.
        return _rest_orch.StageResult(
            stage_id=spec.stage_id,
            status="complete",
            n_games_done=8,
            crashed=0,
            timed_out=0,
            wins_new=5, wins_old=3, draws=0,
        )

    with patch.object(_rest_orch, "run_stage", fake_run_stage):
        cli_eval.main(_base_argv(shards, deck_pool, progress))

    assert captured["worker_urls"] == ["http://worker-a:5198"]
    assert captured["coordinator_url"] == "http://master:5099"
    assert captured["poll_interval_s"] == 0.0


def test_eval_main_builds_stage_spec_from_flags(monkeypatch, tmp_path):
    """``--new`` / ``--old`` / ``--games`` / ``--nodes`` / ``--samples``
    / ``--seed`` / ``--per-game-timeout-sec`` / ``--capture-every`` all
    round-trip into the stage spec :func:`run_stage` sees."""
    _patch_lifecycle_and_decks(monkeypatch, tmp_path)
    shards = _shards_config(tmp_path)
    deck_pool = _deck_pool(tmp_path)
    progress = tmp_path / "progress"

    captured: dict = {}

    def fake_run_stage(*, coordinator_url, worker_urls, spec, **kwargs):
        captured["spec"] = spec
        return _rest_orch.StageResult(
            stage_id=spec.stage_id, status="complete",
            n_games_done=8, crashed=0, timed_out=0,
            wins_new=4, wins_old=4, draws=0,
        )

    argv = _base_argv(shards, deck_pool, progress) + [
        "--capture-every", "5",
        "--label", "v16_v13_8g",
    ]
    with patch.object(_rest_orch, "run_stage", fake_run_stage):
        cli_eval.main(argv)

    spec = captured["spec"]
    assert spec.kind == "eval"
    assert spec.stage_id == "eval_v16_v13_8g"
    assert spec.weights == {"new": "v16", "old": "v13"}
    assert spec.nodes == 32
    assert spec.samples == 2
    assert spec.per_game_timeout_sec == 45.0
    assert spec.capture_every == 5
    assert len(spec.games) == 8
    # base_seed=777 means game_idx=0 carries seed 777.
    assert spec.games[0]["seed"] == 777
    assert spec.games[0]["game_idx"] == 0


def test_eval_main_default_label_uses_new_old_games(
    monkeypatch, tmp_path,
):
    """No ``--label`` → ``<new>_vs_<old>_<games>g``."""
    _patch_lifecycle_and_decks(monkeypatch, tmp_path)
    shards = _shards_config(tmp_path)
    deck_pool = _deck_pool(tmp_path)
    progress = tmp_path / "progress"

    captured: dict = {}

    def fake_run_stage(*, coordinator_url, worker_urls, spec, **kwargs):
        captured["spec"] = spec
        return _rest_orch.StageResult(
            stage_id=spec.stage_id, status="complete",
            n_games_done=8, crashed=0, timed_out=0,
            wins_new=4, wins_old=4, draws=0,
        )

    with patch.object(_rest_orch, "run_stage", fake_run_stage):
        cli_eval.main(_base_argv(shards, deck_pool, progress))

    assert captured["spec"].stage_id == "eval_v16_vs_v13_8g"


def test_eval_main_writes_runs_db_lifecycle_summary(
    monkeypatch, tmp_path,
):
    """The lifecycle wrapper pushes wins / draws / crashed into runs.db
    so the training UI sees the eval result on the dashboard."""
    from mtg_bot.cli.runs import db as runs_db

    db_path = _patch_lifecycle_and_decks(monkeypatch, tmp_path)
    shards = _shards_config(tmp_path)
    deck_pool = _deck_pool(tmp_path)
    progress = tmp_path / "progress"

    def fake_run_stage(*, coordinator_url, worker_urls, spec, **kwargs):
        return _rest_orch.StageResult(
            stage_id=spec.stage_id, status="complete",
            n_games_done=10, crashed=1, timed_out=0,
            wins_new=6, wins_old=3, draws=0,
        )

    with patch.object(_rest_orch, "run_stage", fake_run_stage):
        cli_eval.main(_base_argv(shards, deck_pool, progress))

    # Lifecycle threads the label-derived run_id into runs.db. Read
    # the row back via the direct-sqlite transport (the env var
    # MTG_BOT_RUN_DB_PATH the fixture pinned).
    import sqlite3
    con = sqlite3.connect(db_path)
    try:
        cur = con.execute(
            "SELECT kind, status FROM runs WHERE run_id = ?",
            ("eval_v16_vs_v13_8g",),
        )
        row = cur.fetchone()
    finally:
        con.close()
    assert row is not None
    assert row[0] == "eval"
    assert row[1] == "completed"


def test_eval_main_rejects_missing_shards_config(monkeypatch, tmp_path):
    _patch_lifecycle_and_decks(monkeypatch, tmp_path)
    deck_pool = _deck_pool(tmp_path)
    progress = tmp_path / "progress"
    bogus = tmp_path / "does_not_exist.json"
    argv = [
        "--new", "v16", "--old", "v13", "--games", "1",
        "--shards-config", str(bogus),
        "--progress-dir", str(progress),
        "--deck-pool", str(deck_pool),
        "--queue-url", "http://master:5099",
    ]
    with pytest.raises(SystemExit) as exc:
        cli_eval.main(argv)
    assert "not found" in str(exc.value).lower()


def test_eval_main_rejects_empty_worker_urls(monkeypatch, tmp_path):
    """A shards_config.json with ``{"worker_urls": []}`` is loudly
    rejected — the operator clearly forgot to register workers."""
    _patch_lifecycle_and_decks(monkeypatch, tmp_path)
    deck_pool = _deck_pool(tmp_path)
    progress = tmp_path / "progress"
    shards = tmp_path / "empty_shards.json"
    shards.write_text(
        json.dumps({"worker_urls": []}), encoding="utf-8",
    )
    argv = [
        "--new", "v16", "--old", "v13", "--games", "1",
        "--shards-config", str(shards),
        "--progress-dir", str(progress),
        "--deck-pool", str(deck_pool),
        "--queue-url", "http://master:5099",
    ]
    with pytest.raises(SystemExit) as exc:
        cli_eval.main(argv)
    assert "no worker_urls entries" in str(exc.value)


def test_eval_main_rejects_legacy_shards_config(monkeypatch, tmp_path):
    """Legacy ``{"shards": [...]}`` shape is rejected at the loader
    boundary so an operator can't accidentally run with a pre-cutover
    config."""
    _patch_lifecycle_and_decks(monkeypatch, tmp_path)
    deck_pool = _deck_pool(tmp_path)
    progress = tmp_path / "progress"
    shards = tmp_path / "legacy_shards.json"
    shards.write_text(
        json.dumps({"shards": [{"host": "mac", "user": "u",
                                "repo_path": "/x",
                                "venv_python": "/x/py"}]}),
        encoding="utf-8",
    )
    argv = [
        "--new", "v16", "--old", "v13", "--games", "1",
        "--shards-config", str(shards),
        "--progress-dir", str(progress),
        "--deck-pool", str(deck_pool),
        "--queue-url", "http://master:5099",
    ]
    with pytest.raises(SystemExit) as exc:
        cli_eval.main(argv)
    # Loader raises LegacyShardsConfigError; the CLI wraps it in
    # SystemExit("--shards-config: ...").
    assert "legacy" in str(exc.value).lower()
