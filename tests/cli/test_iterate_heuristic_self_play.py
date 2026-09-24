"""``mtg_bot iterate --self-play-evaluator heuristic`` wiring.

Pins the three seams the warm-start corpus path depends on:

A. ``_self_play`` (local pool) builds the heuristic PIMC config
   instead of ``NNPimcConfig`` and never reads the weights file,
   while still emitting the same npz columns.
B. ``_self_play_distributed`` puts ``evaluator`` + the three
   corpus-format fields on the v2 stage spec.
C. The CLI surface: ``--self-play-evaluator`` (default nn, choices
   validated) and ``--corpus-only``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from mtg_bot.cli import iterate as iz
from mtg_bot.training import PimcConfig
from mtg_bot.training.action_encoding import ACTION_VOCAB_SIZE


def _empty_data_gen_result() -> tuple:
    return (
        np.zeros((0, 51), dtype=np.float32),
        np.zeros((0,), dtype=np.float32),
        np.zeros((0, ACTION_VOCAB_SIZE), dtype=np.float32),
        np.zeros((0, ACTION_VOCAB_SIZE), dtype=np.bool_),
    )


def _spy_data_gen(captured: dict[str, Any]):
    def _run(*args: Any, **kwargs: Any):
        captured.update(kwargs)
        out = _empty_data_gen_result()
        if kwargs.get("structured_tokens"):
            out = out + (
                np.zeros((0, 1), dtype=np.int64),
                np.zeros((0, 1, 7), dtype=np.int64),
                np.zeros((0, 1, 29), dtype=np.float32),
                np.zeros((0, 1), dtype=np.bool_),
            )
        if kwargs.get("with_game_ids"):
            out = out + (np.zeros((0,), dtype=np.int32),)
        return out

    return _run


# ---------------------------------------------------------------------------
# A. local pool path
# ---------------------------------------------------------------------------


def test_self_play_heuristic_builds_pimc_not_nn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    from mtg_bot.search.heuristic_evaluator import MtgHeuristicEvaluator
    from mtg_bot.search.pimc import PIMC

    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        iz, "generate_training_data_parallel", _spy_data_gen(captured),
    )
    monkeypatch.setattr(iz, "save_dataset", lambda *a, **kw: None)

    def _explode(*a, **kw):  # pragma: no cover
        raise AssertionError("heuristic self-play must not build an NN")

    monkeypatch.setattr(iz, "NNPimcConfig", _explode)

    iz._self_play(
        # Deliberately a path that does not exist: the heuristic path
        # must never read it.
        weights_path=tmp_path / "nope" / "weights.pt",
        n_games=1, samples=2, nodes=100, seed=0, n_workers=1,
        output=tmp_path / "out.npz",
        deck_pool=[],
        action_encoding_version="canonical_v2",
        evaluator="heuristic",
    )

    p0 = captured["p0_factory"]
    assert captured["p0_factory"] == captured["p1_factory"], (
        "self-play means both seats share the agent"
    )
    strategy = p0(0)
    assert isinstance(strategy, PIMC)
    assert isinstance(
        strategy.inner_factory().evaluator, MtgHeuristicEvaluator,
    )
    assert strategy.samples == 2
    # Corpus format is unchanged from the NN path.
    assert captured["action_encoding_version"] == "canonical_v2"
    assert captured["with_policy"] is True
    assert captured["with_game_ids"] is True


def test_self_play_heuristic_keeps_structured_and_temperature_knobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        iz, "generate_training_data_parallel", _spy_data_gen(captured),
    )
    monkeypatch.setattr(iz, "save_dataset", lambda *a, **kw: None)

    iz._self_play(
        weights_path=tmp_path / "weights.pt",
        n_games=1, samples=2, nodes=100, seed=0, n_workers=1,
        output=tmp_path / "out.npz",
        deck_pool=[],
        evaluator="heuristic",
        write_structured_tokens=True,
        structured_scalar_schema_version=2,
        move_temperature=1.0,
        temperature_cutoff=30,
    )
    assert captured["structured_tokens"] is True
    assert captured["structured_scalar_schema_version"] == 2
    assert captured["move_temperature"] == 1.0
    assert captured["temperature_cutoff"] == 30


def test_self_play_heuristic_carries_dirichlet_onto_the_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        iz, "generate_training_data_parallel", _spy_data_gen(captured),
    )
    monkeypatch.setattr(iz, "save_dataset", lambda *a, **kw: None)

    iz._self_play(
        weights_path=tmp_path / "weights.pt",
        n_games=1, samples=2, nodes=100, seed=0, n_workers=1,
        output=tmp_path / "out.npz", deck_pool=[],
        evaluator="heuristic",
        root_dirichlet_alpha=0.5, root_dirichlet_eps=0.3,
    )
    inner = captured["p0_factory"](0).inner_factory()
    assert inner.root_dirichlet_alpha == 0.5
    assert inner.root_dirichlet_eps == 0.3


def test_self_play_rejects_unknown_evaluator(tmp_path: Path):
    with pytest.raises(ValueError, match="unknown self-play evaluator"):
        iz._self_play(
            weights_path=tmp_path / "weights.pt",
            n_games=1, samples=1, nodes=1, seed=0, n_workers=1,
            output=tmp_path / "out.npz", deck_pool=[],
            evaluator="random",
        )


def test_self_play_defaults_to_nn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """Omitting the kwarg reproduces the historical NN path."""
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        iz, "generate_training_data_parallel", _spy_data_gen(captured),
    )
    monkeypatch.setattr(iz, "save_dataset", lambda *a, **kw: None)

    iz._self_play(
        weights_path=tmp_path / "weights.pt",
        n_games=1, samples=1, nodes=1, seed=0, n_workers=1,
        output=tmp_path / "out.npz", deck_pool=[],
    )
    factory = captured["p0_factory"]
    assert not isinstance(getattr(factory, "__self__", None), PimcConfig)
    assert isinstance(factory.__self__, iz.NNPimcConfig)


# ---------------------------------------------------------------------------
# B. distributed path
# ---------------------------------------------------------------------------


class _StubStageResult:
    upload_failed = 0
    n_games_done = 4


def test_self_play_distributed_puts_evaluator_on_the_stage_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, Any] = {}

    def _fake_run_stage(*, spec, **kwargs):
        captured["spec"] = spec
        return _StubStageResult()

    monkeypatch.setattr(iz._rest_orch, "run_stage", _fake_run_stage)
    monkeypatch.setattr(
        iz._rest_orch, "make_runs_db_progress_writer",
        lambda *a, **kw: (lambda payload: None),
    )
    monkeypatch.setattr(
        iz, "_aggregate_self_play_npzs", lambda **kw: (1234, 500),
    )

    n_samples, n_policy, _elapsed = iz._self_play_distributed(
        worker_urls=["http://w1:5198"],
        coordinator_url="http://coord:5099",
        nn_version_label="v1",
        samples=2, nodes=100, seed=7,
        per_game_timeout_sec=900.0,
        capture_every=0,
        total_games=4,
        deck_pool_size=50,
        run_id_prefix="s2_iter_011_self_play_heuristic",
        iterate_data_dir=tmp_path,
        evaluator="heuristic",
        action_encoding_version="canonical_v2",
        structured_tokens=True,
        structured_scalar_schema_version=2,
        move_temperature=1.0,
        temperature_cutoff=30,
    )

    assert (n_samples, n_policy) == (1234, 500)
    spec = captured["spec"]
    assert spec.evaluator == "heuristic"
    assert spec.action_encoding_version == "canonical_v2"
    assert spec.structured_tokens is True
    assert spec.structured_scalar_schema_version == 2
    assert not (spec.weights.get("p0") or spec.weights.get("new"))
    assert spec.move_temperature == 1.0


def test_self_play_distributed_defaults_to_nn_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, Any] = {}

    def _fake_run_stage(*, spec, **kwargs):
        captured["spec"] = spec
        return _StubStageResult()

    monkeypatch.setattr(iz._rest_orch, "run_stage", _fake_run_stage)
    monkeypatch.setattr(
        iz._rest_orch, "make_runs_db_progress_writer",
        lambda *a, **kw: (lambda payload: None),
    )
    monkeypatch.setattr(
        iz, "_aggregate_self_play_npzs", lambda **kw: (1, 1),
    )

    iz._self_play_distributed(
        worker_urls=["http://w1:5198"],
        coordinator_url="http://coord:5099",
        nn_version_label="v6",
        samples=4, nodes=200, seed=0,
        per_game_timeout_sec=600.0,
        capture_every=0,
        total_games=4,
        deck_pool_size=50,
        run_id_prefix="iter_009_self_play_v6",
        iterate_data_dir=tmp_path,
    )
    spec = captured["spec"]
    assert spec.evaluator == "nn"
    assert spec.weights == {"p0": "v6", "p1": "v6"}


# ---------------------------------------------------------------------------
# C. CLI surface
# ---------------------------------------------------------------------------


def test_cli_exposes_self_play_evaluator_and_corpus_only():
    """``main`` is a long orchestration body; rather than run it, we
    assert the flags exist on the parser it builds by scanning the
    module source for the argparse registrations and then checking
    the documented defaults via a direct argparse rebuild."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--self-play-evaluator",
        choices=list(iz._SELF_PLAY_EVALUATORS), default="nn",
    )
    parser.add_argument("--corpus-only", action="store_true")

    args = parser.parse_args([])
    assert args.self_play_evaluator == "nn"
    assert args.corpus_only is False

    args = parser.parse_args(
        ["--self-play-evaluator", "heuristic", "--corpus-only"],
    )
    assert args.self_play_evaluator == "heuristic"
    assert args.corpus_only is True

    with pytest.raises(SystemExit):
        parser.parse_args(["--self-play-evaluator", "random"])


def test_iterate_module_registers_the_flags():
    """Guard against the flags being dropped from ``main``'s parser
    (the rebuild above only checks the choices/defaults contract)."""
    import inspect

    src = inspect.getsource(iz.main)
    assert '"--self-play-evaluator"' in src
    assert '"--corpus-only"' in src
    assert "_SELF_PLAY_EVALUATORS" in src


def test_self_play_config_dict_records_evaluator_provenance():
    import argparse

    args = argparse.Namespace(
        games_per_iteration=10, samples=2, nodes=100,
        deck_pool=Path("pool.json.gz"),
        root_dirichlet_alpha=0.5, root_dirichlet_eps=0.25,
        move_temperature=1.0, temperature_cutoff=30,
        self_play_evaluator="heuristic", corpus_only=True,
    )
    cfg = iz._self_play_config_dict(
        args=args, best_version="v1", cycle_seed=5, distributed=True,
    )
    assert cfg["self_play_evaluator"] == "heuristic"
    assert cfg["corpus_only"] is True
