"""Tests for ``mtg_bot.training.replay_capture`` and the
``ReplayCaptureConfig`` integration with data_gen."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from mtg_bot.replay import load_replay
from mtg_bot.training import (
    PimcConfig, ReplayCaptureConfig, ReplayRecorder,
    generate_training_data, generate_training_data_parallel,
    heuristic_eval_annotator, random_choice_factory,
)


# ---------- ReplayRecorder ---------------------------------------------------


def test_recorder_with_no_annotators_records_raw_snapshots():
    """A bare recorder accumulates serialize_state output unchanged."""
    from mtg_bot.simulate import setup_game
    state = setup_game(
        agents=[__import__("mtg_bot.agents", fromlist=["RandomAgent"])
                .RandomAgent(),
                __import__("mtg_bot.agents", fromlist=["RandomAgent"])
                .RandomAgent()],
        colors=["G", "R"], seed=0,
    )
    rec = ReplayRecorder()
    rec.record(state)
    assert len(rec.snapshots) == 1
    snap = rec.snapshots[0]
    # Should have the standard serialize_state keys.
    assert "turn_number" in snap
    assert "players" in snap
    # No annotator → no eval keys.
    assert "heuristic_eval" not in snap
    assert "nn_eval" not in snap


def test_heuristic_annotator_attaches_eval_per_snapshot():
    from mtg_bot.simulate import setup_game
    from mtg_bot.agents import RandomAgent
    state = setup_game(
        agents=[RandomAgent(), RandomAgent()],
        colors=["G", "R"], seed=0,
    )
    rec = ReplayRecorder(annotators=[heuristic_eval_annotator()])
    rec.record(state)
    snap = rec.snapshots[0]
    assert "heuristic_eval" in snap
    h = snap["heuristic_eval"]
    assert "p0" in h and "p1" in h
    assert -1.0 <= h["p0"] <= 1.0
    assert -1.0 <= h["p1"] <= 1.0


def test_to_replay_packages_metadata_and_snapshots():
    rec = ReplayRecorder()
    # Fake a snapshot directly for unit-test simplicity.
    rec.snapshots.append({"turn_number": 1, "step": "upkeep"})
    replay = rec.to_replay(metadata={"game_idx": 7, "winner": 0})
    assert replay.metadata == {"game_idx": 7, "winner": 0}
    assert replay.snapshots == [{"turn_number": 1, "step": "upkeep"}]


# ---------- ReplayCaptureConfig ---------------------------------------------


def test_capture_config_should_capture_respects_modulus():
    cfg = ReplayCaptureConfig(save_dir="x", capture_every=3)
    assert cfg.should_capture(0)
    assert not cfg.should_capture(1)
    assert not cfg.should_capture(2)
    assert cfg.should_capture(3)
    assert cfg.should_capture(6)


def test_capture_config_replay_path_is_deterministic_in_inputs(tmp_path: Path):
    cfg = ReplayCaptureConfig(
        save_dir=str(tmp_path), capture_every=1, filename_prefix="exp1",
    )
    p = cfg.replay_path(base_seed=42, game_idx=3)
    assert p.parent == tmp_path
    assert "exp1" in p.name
    assert "seed42" in p.name
    assert "idx0003" in p.name
    assert p.suffixes == [".json", ".gz"]


# ---------- end-to-end with sequential data_gen -----------------------------


def test_generate_training_data_writes_replays_when_configured(tmp_path: Path):
    """Run the sequential data gen with replay capture enabled;
    verify .json.gz files appear and can be loaded."""
    save_dir = tmp_path / "replays"
    cfg = ReplayCaptureConfig(save_dir=str(save_dir), capture_every=1)
    features, outcomes = generate_training_data(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=2, base_seed=42, replay_config=cfg,
    )
    # Training data still produced as before.
    assert features.shape[0] == outcomes.shape[0]
    # One replay file per game.
    files = sorted(save_dir.glob("*.json.gz"))
    assert len(files) == 2
    # Each file is a valid Replay.
    for f in files:
        replay = load_replay(f)
        assert len(replay.snapshots) > 0
        # Each snapshot has heuristic_eval (default annotator).
        assert all("heuristic_eval" in s for s in replay.snapshots)
        # Metadata captured.
        assert "winner" in replay.metadata
        assert "n_decisions" in replay.metadata
        assert replay.metadata["base_seed"] == 42


def test_generate_training_data_capture_every_thins_files(tmp_path: Path):
    """With capture_every=2, only games at idx 0, 2 produce files."""
    save_dir = tmp_path / "replays"
    cfg = ReplayCaptureConfig(save_dir=str(save_dir), capture_every=2)
    generate_training_data(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=4, base_seed=0, replay_config=cfg,
    )
    files = sorted(save_dir.glob("*.json.gz"))
    # Games 0 and 2 captured.
    assert len(files) == 2
    names = [f.name for f in files]
    assert any("idx0000" in n for n in names)
    assert any("idx0002" in n for n in names)


def test_generate_training_data_no_replay_config_writes_no_files(tmp_path: Path):
    """When replay_config is None (default), no files appear even if
    we were to inspect a directory after the run."""
    save_dir = tmp_path / "replays"
    save_dir.mkdir()
    generate_training_data(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=2, base_seed=0,
    )
    assert list(save_dir.glob("*.json.gz")) == []


# ---------- parallel data_gen with replay capture ---------------------------


def test_generate_training_data_parallel_writes_replays(tmp_path: Path):
    """Workers each save their own game's replay file. Same per-game
    output as sequential because per-game seeds are deterministic."""
    save_dir = tmp_path / "replays"
    cfg = ReplayCaptureConfig(save_dir=str(save_dir), capture_every=1)
    features, _ = generate_training_data_parallel(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=3, base_seed=7, n_workers=2, replay_config=cfg,
    )
    assert features.shape[0] > 0
    files = sorted(save_dir.glob("*.json.gz"))
    assert len(files) == 3


def test_parallel_replay_files_match_sequential(tmp_path: Path):
    """Stronger determinism check: replay files written by the
    parallel path should match those written by the sequential path
    for the same base_seed (per-game payload identical, file names
    identical)."""
    seq_dir = tmp_path / "seq"
    par_dir = tmp_path / "par"
    seq_cfg = ReplayCaptureConfig(save_dir=str(seq_dir), capture_every=1)
    par_cfg = ReplayCaptureConfig(save_dir=str(par_dir), capture_every=1)
    generate_training_data(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=2, base_seed=99, replay_config=seq_cfg,
    )
    generate_training_data_parallel(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=2, base_seed=99, n_workers=2, replay_config=par_cfg,
    )
    seq_files = sorted(p.name for p in seq_dir.glob("*.json.gz"))
    par_files = sorted(p.name for p in par_dir.glob("*.json.gz"))
    assert seq_files == par_files
    # And the file CONTENTS should be identical (per-game replays
    # are deterministic in seed).
    for name in seq_files:
        seq_replay = load_replay(seq_dir / name)
        par_replay = load_replay(par_dir / name)
        assert seq_replay.snapshots == par_replay.snapshots
        # Metadata may differ in `captured_at` (timestamp), so compare
        # the deterministic fields specifically.
        for key in ("game_idx", "base_seed", "engine_seed", "winner",
                    "n_decisions", "annotated_with_nn_version"):
            assert seq_replay.metadata[key] == par_replay.metadata[key]
