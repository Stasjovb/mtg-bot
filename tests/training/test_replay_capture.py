"""Tests for ``mtg_bot.training.replay_capture`` and the
``ReplayCaptureConfig`` integration with data_gen."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mtg_bot.replay import load_replay
from mtg_bot.training import (
    PimcConfig, ReplayCaptureConfig, ReplayRecorder,
    generate_training_data, generate_training_data_parallel,
    heuristic_eval_annotator, random_choice_factory,
)
from tests._test_decks import simple_test_decklists, simple_test_deck_pool


# ---------- ReplayRecorder ---------------------------------------------------


def test_recorder_with_no_annotators_records_raw_snapshots():
    """A bare recorder accumulates serialize_state output unchanged."""
    from mtg_bot.simulate import setup_game
    state = setup_game(
        agents=[__import__("mtg_bot.agents", fromlist=["RandomAgent"])
                .RandomAgent(),
                __import__("mtg_bot.agents", fromlist=["RandomAgent"])
                .RandomAgent()],
        decks=simple_test_decklists(), seed=0,
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
    # Recorded with decision=None (default) → key present, value None.
    assert snap["decision"] is None


def test_recorder_stores_decision_when_provided():
    """Passing ``decision=`` threads through to the snapshot's
    ``decision`` JSON field."""
    from mtg_bot.actions import PassPriority
    from mtg_bot.agents import RandomAgent
    from mtg_bot.simulate import setup_game
    state = setup_game(
        agents=[RandomAgent(), RandomAgent()],
        decks=simple_test_decklists(), seed=0,
    )
    rec = ReplayRecorder()
    rec.record(state, decision=PassPriority())
    snap = rec.snapshots[0]
    assert snap["decision"] == {"kind": "PassPriority"}


def test_heuristic_annotator_attaches_eval_per_snapshot():
    from mtg_bot.simulate import setup_game
    from mtg_bot.agents import RandomAgent
    state = setup_game(
        agents=[RandomAgent(), RandomAgent()],
        decks=simple_test_decklists(), seed=0,
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


# ---------- record_search_annotation -----------------------------------------


def test_record_search_annotation_attaches_to_snapshot():
    """``record_search_annotation`` writes the annotation to an
    already-recorded snapshot's ``search`` key. ``record`` initializes
    the field as None so the annotator hook is purely additive."""
    from mtg_bot.actions import PassPriority
    from mtg_bot.agents import RandomAgent
    from mtg_bot.simulate import setup_game
    state = setup_game(
        agents=[RandomAgent(), RandomAgent()],
        decks=simple_test_decklists(), seed=0,
    )
    rec = ReplayRecorder()
    rec.record(state)              # snapshot 0
    rec.record(state, decision=PassPriority())  # snapshot 1
    # Both initialized with search=None.
    assert rec.snapshots[0]["search"] is None
    assert rec.snapshots[1]["search"] is None
    annotation = {
        "chosen": {"kind": "PassPriority"},
        "candidates": [{
            "action": {"kind": "PassPriority"}, "visits": 5,
            "q": 0.1, "prior": None, "leaf_value": None,
        }],
        "samples": 1, "inner_nodes": 50, "elapsed_ms": 12,
    }
    rec.record_search_annotation(1, annotation)
    assert rec.snapshots[0]["search"] is None
    assert rec.snapshots[1]["search"] == annotation


def test_record_search_annotation_rejects_out_of_range():
    """Out-of-range snapshot indices raise IndexError, not silent
    no-ops (off-by-one bugs in callers should fail loud)."""
    rec = ReplayRecorder()
    # Empty: any index is out of range.
    with pytest.raises(IndexError):
        rec.record_search_annotation(0, {"chosen": None, "candidates": []})
    # Add one snapshot, then test ±1 boundaries.
    rec.snapshots.append({"turn_number": 1})
    with pytest.raises(IndexError):
        rec.record_search_annotation(-1, {"chosen": None, "candidates": []})
    with pytest.raises(IndexError):
        rec.record_search_annotation(1, {"chosen": None, "candidates": []})


def test_build_search_annotation_serializes_actions_and_sorts():
    """``build_search_annotation`` runs each candidate through
    ``decision_to_json``, sorts by visits desc, and surfaces the
    strategy's PIMC ``samples`` + inner MCTS ``budget_factory``
    node count."""
    import random
    from mtg_bot.actions import PassPriority, PlayLand
    from mtg_bot.search import (
        Budget, MCTS, RandomRolloutEvaluator,
    )
    from mtg_bot.search.pimc import PIMC
    from mtg_bot.training import build_search_annotation

    inner_factory = lambda: MCTS(
        evaluator=RandomRolloutEvaluator(rng=random.Random(0)),
        budget_factory=lambda: Budget(max_nodes=137),
        rng=random.Random(0),
    )
    pimc = PIMC(inner_factory=inner_factory, samples=4)
    candidates = [
        {"decision": PlayLand(card_id=5), "visits": 3,
         "q": -0.1, "prior": None, "leaf_value": None},
        {"decision": PassPriority(), "visits": 10,
         "q": 0.42, "prior": 0.5, "leaf_value": 0.3},
    ]
    annotation = build_search_annotation(
        chosen=PassPriority(),
        candidates=candidates,
        strategy=pimc,
        elapsed_ms=99,
    )
    assert annotation["chosen"] == {"kind": "PassPriority"}
    # Sorted by visits desc — PassPriority(10) comes before PlayLand(3).
    assert annotation["candidates"][0]["action"] == {"kind": "PassPriority"}
    assert annotation["candidates"][1]["action"] == {
        "kind": "PlayLand", "card_id": 5,
    }
    assert annotation["candidates"][0]["visits"] == 10
    assert annotation["candidates"][0]["q"] == 0.42
    assert annotation["samples"] == 4
    assert annotation["inner_nodes"] == 137
    assert annotation["elapsed_ms"] == 99


def test_build_search_annotation_handles_raw_mcts():
    """When the strategy is a raw MCTS (no PIMC wrapper), ``samples``
    comes back as 1 (default attr) and ``inner_nodes`` reads from the
    strategy's own budget_factory."""
    import random
    from mtg_bot.actions import PassPriority
    from mtg_bot.search import Budget, MCTS, RandomRolloutEvaluator
    from mtg_bot.training import build_search_annotation

    mcts = MCTS(
        evaluator=RandomRolloutEvaluator(rng=random.Random(0)),
        budget_factory=lambda: Budget(max_nodes=64),
        rng=random.Random(0),
    )
    annotation = build_search_annotation(
        chosen=PassPriority(),
        candidates=[
            {"decision": PassPriority(), "visits": 2,
             "q": 0.0, "prior": None, "leaf_value": None},
        ],
        strategy=mcts,
        elapsed_ms=None,
    )
    # MCTS doesn't carry a ``samples`` attribute; helper falls back to 1.
    assert annotation["samples"] == 1
    assert annotation["inner_nodes"] == 64
    assert annotation["elapsed_ms"] is None


def test_build_search_annotation_serialized_size_under_budget():
    """The capture-storage budget assumes a per-decision search
    annotation serializes to ~1 KB raw / ~300 B gzipped. Verify a
    representative annotation (5 candidates, all numeric fields
    present) lands under that ceiling — guards against an
    accidental shape blow-up that would torpedo the per-iter
    replay-dir size budget."""
    import gzip
    import json as _json
    import random
    from mtg_bot.actions import (
        ActivateAbility, CastSpell, PassPriority, PlayLand,
    )
    from mtg_bot.search import Budget, MCTS, RandomRolloutEvaluator
    from mtg_bot.search.pimc import PIMC
    from mtg_bot.training import build_search_annotation

    pimc = PIMC(
        inner_factory=lambda: MCTS(
            evaluator=RandomRolloutEvaluator(rng=random.Random(0)),
            budget_factory=lambda: Budget(max_nodes=200),
            rng=random.Random(0),
        ),
        samples=8,
    )
    decs = [
        PassPriority(),
        PlayLand(card_id=42),
        CastSpell(card_id=7, kicked=True),
        ActivateAbility(source_id=11, ability_index=0),
        CastSpell(card_id=8),
    ]
    candidates = [
        {"decision": d, "visits": 50 - i * 9,
         "q": 0.123 + i * 0.01,
         "prior": 0.2 - i * 0.04,
         "leaf_value": 0.05 + i * 0.02}
        for i, d in enumerate(decs)
    ]
    annotation = build_search_annotation(
        chosen=PassPriority(), candidates=candidates,
        strategy=pimc, elapsed_ms=42,
    )
    raw = _json.dumps(annotation).encode("utf-8")
    gz = gzip.compress(raw)
    # Spec target: ~1 KB raw, ~300 B gzipped. Generous headroom.
    assert len(raw) < 2048, (
        f"raw annotation too big: {len(raw)} bytes; "
        f"budget assumed ~1 KB"
    )
    assert len(gz) < 600, (
        f"gzipped annotation too big: {len(gz)} bytes; "
        f"budget assumed ~300 B"
    )


# ---------- ReplayCaptureConfig ---------------------------------------------


def test_capture_config_should_capture_respects_modulus():
    cfg = ReplayCaptureConfig(save_dir="x", capture_every=3)
    assert cfg.should_capture(0)
    assert not cfg.should_capture(1)
    assert not cfg.should_capture(2)
    assert cfg.should_capture(3)
    assert cfg.should_capture(6)


def test_capture_config_build_recorder_passes_arch_to_nn_annotator(
    tmp_path: Path,
):
    """ReplayCaptureConfig.build_recorder() must propagate hidden_sizes
    and with_policy to nn_eval_annotator → NNEvaluator. Without that,
    a config tagged with a modern (dual-head, big-trunk) checkpoint
    blows up at load time on a state_dict mismatch — which broke the
    first iterate run with deck_pool + replay capture in production."""
    import torch

    from mtg_bot.search.nn_evaluator import _ValuePolicyMLP

    hidden_sizes = (32, 24, 16)
    weights_path = tmp_path / "tiny_dual_head.pt"
    model = _ValuePolicyMLP(hidden_sizes=hidden_sizes)
    torch.save(model.state_dict(), weights_path)

    cfg = ReplayCaptureConfig(
        save_dir=str(tmp_path),
        nn_weights_path=str(weights_path),
        nn_version_label="tiny",
        nn_hidden_sizes=hidden_sizes,
        nn_with_policy=True,
    )
    # build_recorder() loads the NN — would raise RuntimeError if
    # the architecture kwargs weren't threaded through.
    recorder = cfg.build_recorder()
    # Two annotators: the always-on heuristic plus the NN one.
    assert len(recorder.annotators) == 2


def test_nn_eval_annotator_annotates_running_and_terminal_states(
    tmp_path: Path,
):
    """nn_eval_annotator's inner ``annotate`` returns ``nn_eval`` with
    p0/p1 floats + version on a running state, and the terminal value
    fast-path on a finished state. Pins both branches."""
    import torch

    from mtg_bot.search.nn_evaluator import _ValuePolicyMLP
    from mtg_bot.simulate import setup_game
    from mtg_bot.training.replay_capture import nn_eval_annotator

    hidden_sizes = (16, 16)
    weights_path = tmp_path / "tiny.pt"
    torch.save(
        _ValuePolicyMLP(hidden_sizes=hidden_sizes).state_dict(),
        weights_path,
    )
    annotate = nn_eval_annotator(
        weights_path,
        version_label="tiny",
        hidden_sizes=hidden_sizes,
        with_policy=True,
    )

    # Build a real running engine state via setup_game so the
    # evaluator gets a well-formed input. RandomAgent isn't needed —
    # the annotator only inspects state, never asks for decisions.
    from mtg_bot.agents import RandomAgent
    state = setup_game(
        agents=[RandomAgent(), RandomAgent()],
        decks=simple_test_decklists(),
        seed=0,
    )
    out = annotate(state)
    assert "nn_eval" in out
    assert out["nn_eval"]["version"] == "tiny"
    assert isinstance(out["nn_eval"]["p0"], float)
    assert isinstance(out["nn_eval"]["p1"], float)

    # Terminal-state branch: hand-set the engine to "p0 wins" and
    # confirm the annotator reads off the engine state directly
    # (skipping the NN forward).
    state.winner_id = 0
    state.is_draw = False
    out_terminal = annotate(state)
    assert out_terminal["nn_eval"]["p0"] == 1.0
    assert out_terminal["nn_eval"]["p1"] == -1.0
    assert out_terminal["nn_eval"]["version"] == "tiny"


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
        n_games=2, base_seed=42, replay_config=cfg, deck_pool=simple_test_deck_pool(),
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
        n_games=4, base_seed=0, replay_config=cfg, deck_pool=simple_test_deck_pool(),
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
        n_games=2, base_seed=0, deck_pool=simple_test_deck_pool(),
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
        n_games=3, base_seed=7, n_workers=2, replay_config=cfg, deck_pool=simple_test_deck_pool(),
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
        n_games=2, base_seed=99, replay_config=seq_cfg, deck_pool=simple_test_deck_pool(),
    )
    generate_training_data_parallel(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=2, base_seed=99, n_workers=2, replay_config=par_cfg, deck_pool=simple_test_deck_pool(),
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


# ---------- decision capture (Phase 6 prereq) -------------------------------


def test_v2_replay_round_trips_decisions(tmp_path: Path):
    """Build a recorder, hand it several representative decisions,
    save the replay, load it back. Each snapshot's ``decision``
    deserializes to the same Decision instance."""
    from mtg_bot.actions import (
        ActivateAbility, CastSpell, DeclareAttackers, PassPriority, PlayLand,
    )
    from mtg_bot.agents import RandomAgent
    from mtg_bot.replay import REPLAY_FORMAT_VERSION, save_replay
    from mtg_bot.search.combat_decisions import AttackerDecision, BlockerDecision
    from mtg_bot.search.resolution_decisions import ResolutionTargetDecision
    from mtg_bot.simulate import setup_game
    from mtg_bot.training.replay_decisions import decision_from_json

    state = setup_game(
        agents=[RandomAgent(), RandomAgent()],
        decks=simple_test_decklists(), seed=0,
    )
    rec = ReplayRecorder()
    expected = [
        None,  # initial pre-game state
        PassPriority(),
        PlayLand(card_id=42),
        CastSpell(card_id=7, kicked=True),
        ActivateAbility(source_id=11, ability_index=0),
        DeclareAttackers(attacker_ids=frozenset({3, 5})),
        AttackerDecision(attacker_id=3, attack=True),
        BlockerDecision(blocker_id=8, attacker_id=None),
        ResolutionTargetDecision(target=("creature", 7)),
    ]
    for d in expected:
        rec.record(state, decision=d)
    replay = rec.to_replay(metadata={"game_idx": 1})
    assert replay.format_version == REPLAY_FORMAT_VERSION

    path = tmp_path / "v2.json.gz"
    save_replay(replay, path)
    loaded = load_replay(path)
    assert len(loaded.snapshots) == len(expected)
    for snap, original in zip(loaded.snapshots, expected):
        if original is None:
            assert snap["decision"] is None
        else:
            assert decision_from_json(snap["decision"]) == original


def test_end_to_end_pimc_replay_capture_attaches_search_annotations(
    tmp_path: Path,
):
    """Run a sequential data_gen with PIMC on both sides and replay
    capture enabled — at least one captured snapshot should carry a
    populated ``search`` annotation with non-empty candidates."""
    from mtg_bot.training import PimcConfig
    config = PimcConfig(samples=1, inner_nodes=4)
    factory = lambda seed, _c=config: _c.build(seed)
    save_dir = tmp_path / "replays"
    cfg = ReplayCaptureConfig(save_dir=str(save_dir), capture_every=1)
    generate_training_data(
        p0_factory=factory, p1_factory=factory,
        n_games=1, base_seed=0, replay_config=cfg,
        deck_pool=simple_test_deck_pool(),
    )
    files = sorted(save_dir.glob("*.json.gz"))
    assert len(files) == 1
    replay = load_replay(files[0])
    assert replay.format_version == 3
    annotated = [
        s for s in replay.snapshots if s.get("search") is not None
    ]
    assert annotated, "expected at least one search-annotated snapshot"
    # First annotated snapshot should have a chosen action and at
    # least one candidate.
    sample = annotated[0]["search"]
    assert sample["chosen"] is not None
    assert isinstance(sample["candidates"], list)
    assert len(sample["candidates"]) >= 1
    # Per-candidate fields are present (None or numeric — type is
    # the contract).
    c0 = sample["candidates"][0]
    assert "action" in c0
    assert isinstance(c0["visits"], int)
    assert "q" in c0 and "prior" in c0 and "leaf_value" in c0
    # PIMC-of-MCTS budget threaded through.
    assert sample["samples"] == 1
    assert sample["inner_nodes"] == 4


def test_end_to_end_replay_capture_writes_v3_with_search_field(
    tmp_path: Path,
):
    """Run a sequential data_gen with replay capture enabled and
    verify the resulting replay files are v3 and every snapshot
    carries a ``search`` field (None for the snapshots that
    couldn't be annotated — random play has no search tree, so
    the field stays None for the random-strategy game). Pins the
    ``record`` → ``search=None`` initialization so v3 schema is
    honored end-to-end."""
    save_dir = tmp_path / "replays"
    cfg = ReplayCaptureConfig(save_dir=str(save_dir), capture_every=1)
    generate_training_data(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=1, base_seed=42, replay_config=cfg,
        deck_pool=simple_test_deck_pool(),
    )
    files = sorted(save_dir.glob("*.json.gz"))
    assert len(files) == 1
    replay = load_replay(files[0])
    # v3 snapshots all have a ``search`` key.
    assert replay.format_version == 3
    assert all("search" in s for s in replay.snapshots)
    # Random play has no search tree → every search field stays None.
    assert all(s["search"] is None for s in replay.snapshots)


def test_end_to_end_replay_capture_records_decisions(tmp_path: Path):
    """Run two games with replay capture enabled. Every snapshot
    after the first carries a non-None decision that round-trips
    through ``decision_from_json``."""
    from mtg_bot.training.replay_decisions import decision_from_json

    save_dir = tmp_path / "replays"
    cfg = ReplayCaptureConfig(save_dir=str(save_dir), capture_every=1)
    generate_training_data(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=2, base_seed=42, replay_config=cfg, deck_pool=simple_test_deck_pool(),
    )
    files = sorted(save_dir.glob("*.json.gz"))
    assert len(files) == 2
    saw_a_real_game = False
    for f in files:
        replay = load_replay(f)
        assert len(replay.snapshots) >= 1
        # First snapshot is the pre-game initial state — no decision.
        assert replay.snapshots[0]["decision"] is None
        # Every subsequent snapshot must carry an action that decodes.
        for snap in replay.snapshots[1:]:
            saw_a_real_game = True
            assert snap["decision"] is not None
            decoded = decision_from_json(snap["decision"])
            # Sanity: encoding is bijective end-to-end.
            from mtg_bot.training.replay_decisions import decision_to_json
            assert decision_to_json(decoded) == snap["decision"]
    # At least one game advanced past turn 0; otherwise this test
    # would silently pass with zero decisions checked.
    assert saw_a_real_game
