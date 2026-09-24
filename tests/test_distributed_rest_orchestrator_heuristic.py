"""v2 stage-spec coverage for heuristic (warm-start corpus) self-play.

Companion to ``test_distributed_rest_orchestrator.py``; kept separate
so the historical NN-path assertions there stay untouched.
"""

from __future__ import annotations

from typing import Any

import pytest

from mtg_bot import distributed_rest_orchestrator as orch


def _heuristic_spec(**overrides):
    kwargs: dict[str, Any] = dict(
        stage_id="s2_iter_011_self_play_heuristic",
        n_games=10,
        base_seed=11_000_000,
        deck_pool_size=5000,
        weights_version="v1",
        nodes=100,
        samples=2,
        per_game_timeout_sec=900.0,
        evaluator="heuristic",
        action_encoding_version="canonical_v2",
        structured_tokens=True,
        structured_scalar_schema_version=2,
    )
    kwargs.update(overrides)
    return orch.make_self_play_stage_spec(**kwargs)


def test_self_play_stage_spec_defaults_to_nn_evaluator():
    """Existing call sites keep the historical shape: evaluator="nn",
    real weights, and no corpus-format overrides on the wire."""
    spec = orch.make_self_play_stage_spec(
        stage_id="iter_009_self_play_v6",
        n_games=4, base_seed=0, deck_pool_size=50,
        weights_version="v6", nodes=200, samples=4,
        per_game_timeout_sec=600.0,
    )
    assert spec.evaluator == "nn"
    assert spec.weights == {"p0": "v6", "p1": "v6"}
    assert spec.action_encoding_version is None
    assert spec.structured_tokens is None
    assert spec.structured_scalar_schema_version is None


def test_heuristic_stage_spec_empties_weights_for_old_worker_failure():
    """The old-worker interlock.

    A worker that predates the ``evaluator`` field does
    ``weights.get("p0") or weights.get("new")`` and raises when that
    is falsy -- so it crashes loudly on every claim instead of quietly
    playing the stage with the NN, which is the exact corpus this
    feature exists to avoid.
    """
    spec = _heuristic_spec()
    assert spec.evaluator == "heuristic"
    assert not (spec.weights.get("p0") or spec.weights.get("new"))
    assert not spec.weights.get("p1")


def test_heuristic_stage_spec_carries_corpus_format_fields():
    """No weights version means no metadata.json on the worker, so
    the action encoding + token schema must travel on the spec."""
    spec = _heuristic_spec()
    d = spec.to_dict()
    assert d["evaluator"] == "heuristic"
    assert d["action_encoding_version"] == "canonical_v2"
    assert d["structured_tokens"] is True
    assert d["structured_scalar_schema_version"] == 2
    assert len(spec.games) == 10
    # Same per-game shape as an NN stage -- deck pairing and seeds are
    # evaluator-independent.
    g0 = spec.games[0]
    assert set(g0) >= {"game_idx", "deck_indices", "seed"}


def test_heuristic_stage_spec_requires_action_encoding_version():
    with pytest.raises(ValueError, match="action_encoding_version"):
        _heuristic_spec(action_encoding_version=None)


def test_heuristic_stage_spec_keeps_exploration_knobs():
    """Move temperature (and the carried Dirichlet knobs) are
    search-level settings, not NN-only settings."""
    spec = _heuristic_spec(
        root_dirichlet_alpha=0.5, root_dirichlet_eps=0.3,
        move_temperature=1.0, temperature_cutoff=30,
    )
    assert spec.root_dirichlet_alpha == 0.5
    assert spec.root_dirichlet_eps == 0.3
    assert spec.move_temperature == 1.0
    assert spec.temperature_cutoff == 30


def test_self_play_stage_spec_rejects_unknown_evaluator():
    with pytest.raises(ValueError, match="unknown self-play evaluator"):
        _heuristic_spec(evaluator="random")


def test_eval_stage_spec_is_always_nn():
    spec = orch.make_eval_stage_spec(
        stage_id="eval_v6_vs_v5", n_games=4, base_seed=0,
        deck_pool_size=50, new_version="v6", old_version="v5",
        nodes=200, samples=4, per_game_timeout_sec=600.0,
    )
    assert spec.evaluator == "nn"
    assert spec.to_dict()["evaluator"] == "nn"
