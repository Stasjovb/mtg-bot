"""Tests for ``mtg_bot.search.nn_evaluator.NNEvaluator``.

Phase C scaffolding: no training in this PR, so these tests cover
the *infrastructure* (architecture, save/load, integration with the
search stack) rather than play strength. Phase D adds tests that
actually train and assert "trained NN beats heuristic in self-play."
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import torch

from mtg_bot.agents import RandomAgent
from mtg_bot.features import FEATURE_DIM
from mtg_bot.search import (
    Budget, MCTS, MtgGameStateAdapter, NNEvaluator,
)
from mtg_bot.search.nn_evaluator import HIDDEN_SIZES, _ValueMLP
from mtg_bot.simulate import setup_game


def _adapter(seed: int = 42) -> MtgGameStateAdapter:
    state = setup_game(
        [RandomAgent(), RandomAgent()], ["G", "R"], seed=seed,
    )
    return MtgGameStateAdapter(state)


# ---------- architecture ----------------------------------------------------


def test_value_mlp_input_output_shape():
    net = _ValueMLP()
    batch = torch.zeros(4, FEATURE_DIM)
    out = net(batch)
    assert out.shape == (4, 1)


def test_value_mlp_output_is_in_unit_interval():
    """Tanh on the last layer must keep outputs in [-1, 1] regardless
    of input magnitude. Smoke this with extreme inputs to confirm."""
    net = _ValueMLP()
    extreme = torch.full((8, FEATURE_DIM), 1e6)
    out = net(extreme)
    assert torch.all(out >= -1.0)
    assert torch.all(out <= 1.0)


def test_value_mlp_parameter_count_is_reasonable():
    """Sanity check on architecture size — bumping past the upper
    bound unintentionally would mean we lost track of
    ``HIDDEN_SIZES``."""
    net = _ValueMLP()
    total = sum(p.numel() for p in net.parameters())
    # Current 51→512→512→256→1 is ~420k params. The pre-2026-05-02
    # default 51→128→128→64→1 was ~25k. Cap at 2M as a sanity
    # ceiling — a value-only net beyond that starts overfitting at
    # our data scale.
    assert 1_000 <= total <= 2_000_000, (
        f"network has {total} params; expected 1k–2M for the "
        f"default HIDDEN_SIZES={HIDDEN_SIZES}"
    )


# ---------- NNEvaluator: random init ----------------------------------------


def test_nn_evaluator_default_init_returns_random_value_in_range():
    """Untrained network should still return a finite value in
    [-1, 1] for any input — tanh on the output guarantees the
    range, weight init guarantees finiteness."""
    evaluator = NNEvaluator()
    adapter = _adapter()
    value = evaluator.evaluate(adapter, player_id=0)
    assert isinstance(value, float)
    assert np.isfinite(value)
    assert -1.0 <= value <= 1.0


def test_nn_evaluator_inference_is_deterministic():
    """Same network, same state, same player → same value across
    repeated calls. (Trivially true since model.eval() + no dropout,
    but worth pinning.)"""
    evaluator = NNEvaluator()
    adapter = _adapter()
    a = evaluator.evaluate(adapter, player_id=0)
    b = evaluator.evaluate(adapter, player_id=0)
    assert a == b


def test_nn_evaluator_different_states_can_give_different_values():
    """Sanity: swapping the viewer or moving to a different state
    should be able to produce different values (random network, but
    inputs differ)."""
    evaluator = NNEvaluator()
    a = _adapter(seed=42)
    b = _adapter(seed=99)
    val_a = evaluator.evaluate(a, player_id=0)
    val_b = evaluator.evaluate(b, player_id=0)
    # Random network — usually different, but not guaranteed. A loose
    # check: at least one of (different state, different viewer) gives
    # a different value.
    val_a_p1 = evaluator.evaluate(a, player_id=1)
    assert val_a != val_b or val_a != val_a_p1, (
        "evaluator collapsed all inputs to the same value — likely a "
        "feature-extraction or forward-pass bug"
    )


# ---------- terminal short-circuit ------------------------------------------


def test_nn_evaluator_returns_plus_one_for_winning_terminal():
    """The Evaluator base class short-circuits terminal states to
    ±1 / 0 without consulting _evaluate_nonterminal. NNEvaluator
    inherits that for free; verify it works."""
    adapter = _adapter()
    # Force a terminal where P0 won.
    adapter.engine_state.players[1].has_lost = True
    adapter.engine_state.winner_id = 0
    assert adapter.is_terminal()
    evaluator = NNEvaluator()
    assert evaluator.evaluate(adapter, player_id=0) == 1.0
    assert evaluator.evaluate(adapter, player_id=1) == -1.0


# ---------- save / load -----------------------------------------------------


def test_nn_evaluator_save_and_load_round_trip(tmp_path: Path):
    """Save weights, load into a fresh evaluator, check that both
    evaluate to the same value on the same state."""
    a = NNEvaluator()
    weights_path = tmp_path / "weights.pt"
    a.save(weights_path)
    assert weights_path.exists()

    b = NNEvaluator(weights_path=weights_path)

    adapter = _adapter()
    val_a = a.evaluate(adapter, player_id=0)
    val_b = b.evaluate(adapter, player_id=0)
    assert val_a == val_b


def test_loaded_weights_differ_from_random_init(tmp_path: Path):
    """Two NNEvaluators with no weights given are random-initialized
    with different weights (assuming default torch RNG state moves
    forward between constructors). Loading from a saved file should
    reproduce the saved weights, not give yet another random init."""
    saver = NNEvaluator()
    weights_path = tmp_path / "saved.pt"
    saver.save(weights_path)

    fresh_random = NNEvaluator()
    loaded = NNEvaluator(weights_path=weights_path)

    adapter = _adapter()
    saver_val = saver.evaluate(adapter, player_id=0)
    fresh_val = fresh_random.evaluate(adapter, player_id=0)
    loaded_val = loaded.evaluate(adapter, player_id=0)

    # Loaded matches saver.
    assert loaded_val == saver_val
    # Fresh-random typically differs from saver (if torch's global
    # RNG state advanced between constructions).
    # We assert that loaded is NOT equal to fresh_random — which would
    # be the case if "load" was silently a no-op.
    assert loaded_val != fresh_val or saver_val == fresh_val, (
        "loaded value matches a fresh random init — "
        "weights may not have actually loaded"
    )


# ---------- integration with MCTS -------------------------------------------


def test_nn_evaluator_drives_mcts_without_crashing():
    """Drop NNEvaluator into MCTS and confirm it can return a legal
    decision against the real engine. Smoke test — untrained net, so
    decision quality is meaningless. Just verifies the wiring."""
    adapter = _adapter()
    evaluator = NNEvaluator()
    mcts = MCTS(
        evaluator=evaluator,
        budget_factory=lambda: Budget(max_nodes=8),
        rng=__import__("random").Random(0),
    )
    legal = adapter.legal_decisions()
    decision = mcts.choose(adapter, adapter.active_player())
    assert decision in legal
