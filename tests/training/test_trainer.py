"""Tests for ``mtg_bot.training.trainer``.

The training loop is straightforward PyTorch — these tests verify
the contract (shapes, save/load, determinism, basic learning) on
small synthetic datasets so they run in single-digit seconds. We
don't verify "trains a network that beats the heuristic" here;
that's an end-to-end smoke better done outside the test suite.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import torch

from mtg_bot.features import FEATURE_DIM
from mtg_bot.search import NNEvaluator
from mtg_bot.training import (
    TrainingHistory, auto_device, train_value_network,
)


def _synthetic_dataset(n: int, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Cheap synthetic data: random features and a target that
    depends on the first feature only. The MLP should be able to
    fit this trivially, which is enough for the "training reduces
    loss" assertion."""
    rng = np.random.default_rng(seed)
    features = rng.standard_normal((n, FEATURE_DIM)).astype(np.float32)
    # target = tanh(first_feature) → in [-1, 1] like real outcomes
    outcomes = np.tanh(features[:, 0]).astype(np.float32)
    return features, outcomes


# ---------- contract checks --------------------------------------------------


def test_auto_device_returns_cuda_or_cpu():
    d = auto_device()
    assert d in ("cuda", "cpu")


def test_returns_training_history_with_per_epoch_losses(tmp_path: Path):
    features, outcomes = _synthetic_dataset(64)
    history = train_value_network(
        features=features, outcomes=outcomes,
        weights_out_path=tmp_path / "w.pt",
        epochs=3, batch_size=16, device="cpu",
    )
    assert isinstance(history, TrainingHistory)
    assert len(history.train_losses) == 3
    assert len(history.val_losses) == 3
    assert history.weights_path == tmp_path / "w.pt"


def test_writes_weights_file(tmp_path: Path):
    features, outcomes = _synthetic_dataset(32)
    out = tmp_path / "weights.pt"
    train_value_network(
        features=features, outcomes=outcomes,
        weights_out_path=out, epochs=1, batch_size=8, device="cpu",
    )
    assert out.exists()


# ---------- learning ---------------------------------------------------------


def test_training_reduces_loss_on_synthetic_data(tmp_path: Path):
    """Train for a few epochs on a tractable synthetic problem;
    final train loss should be lower than first-epoch loss. Catches
    bugs where backward pass is wrong, optimizer isn't stepping,
    etc."""
    features, outcomes = _synthetic_dataset(256)
    history = train_value_network(
        features=features, outcomes=outcomes,
        weights_out_path=tmp_path / "w.pt",
        epochs=10, batch_size=32, learning_rate=1e-2,
        device="cpu", rng_seed=0,
    )
    assert history.train_losses[-1] < history.train_losses[0], (
        f"loss didn't drop: {history.train_losses}"
    )


def test_trained_weights_load_into_nn_evaluator(tmp_path: Path):
    """After training, NNEvaluator should be able to load the
    weights and produce finite predictions — the file format the
    trainer writes must match the format NNEvaluator expects."""
    features, outcomes = _synthetic_dataset(64)
    out = tmp_path / "trained.pt"
    train_value_network(
        features=features, outcomes=outcomes,
        weights_out_path=out, epochs=2, batch_size=16, device="cpu",
    )
    evaluator = NNEvaluator(weights_path=out)
    # Predict on one sample (use raw feature as a fake "engine state"
    # via a torch tensor through the model directly).
    x = torch.from_numpy(features[:1])
    with torch.no_grad():
        value = evaluator.model(x).item()
    assert -1.0 <= value <= 1.0
    assert np.isfinite(value)


# ---------- determinism ------------------------------------------------------


def test_training_is_deterministic_in_seed(tmp_path: Path):
    """Same seed + same data → same final loss. Weight init,
    train/val split, and batch shuffling all need to honor the
    seed."""
    features, outcomes = _synthetic_dataset(128, seed=1)

    h1 = train_value_network(
        features=features, outcomes=outcomes,
        weights_out_path=tmp_path / "w1.pt",
        epochs=3, batch_size=16, device="cpu", rng_seed=42,
    )
    h2 = train_value_network(
        features=features, outcomes=outcomes,
        weights_out_path=tmp_path / "w2.pt",
        epochs=3, batch_size=16, device="cpu", rng_seed=42,
    )
    assert h1.train_losses == h2.train_losses
    assert h1.val_losses == h2.val_losses


# ---------- input validation -------------------------------------------------


def test_rejects_mismatched_features_outcomes(tmp_path: Path):
    bad_f = np.zeros((5, FEATURE_DIM), dtype=np.float32)
    bad_o = np.zeros((4,), dtype=np.float32)
    with pytest.raises(ValueError, match="rows"):
        train_value_network(
            features=bad_f, outcomes=bad_o,
            weights_out_path=tmp_path / "x.pt",
        )


def test_rejects_empty_dataset(tmp_path: Path):
    f = np.zeros((0, FEATURE_DIM), dtype=np.float32)
    o = np.zeros((0,), dtype=np.float32)
    with pytest.raises(ValueError, match="empty"):
        train_value_network(
            features=f, outcomes=o,
            weights_out_path=tmp_path / "x.pt",
        )


def test_rejects_invalid_val_split(tmp_path: Path):
    f, o = _synthetic_dataset(8)
    with pytest.raises(ValueError, match="val_split"):
        train_value_network(
            features=f, outcomes=o,
            weights_out_path=tmp_path / "x.pt", val_split=1.0,
        )
    with pytest.raises(ValueError, match="val_split"):
        train_value_network(
            features=f, outcomes=o,
            weights_out_path=tmp_path / "x.pt", val_split=-0.1,
        )


def test_zero_val_split_skips_validation(tmp_path: Path):
    """val_split=0.0 → no val data; val losses are NaN per epoch
    but training still runs to completion."""
    f, o = _synthetic_dataset(32)
    history = train_value_network(
        features=f, outcomes=o,
        weights_out_path=tmp_path / "x.pt",
        epochs=2, batch_size=8, val_split=0.0, device="cpu",
    )
    for v in history.val_losses:
        assert np.isnan(v)
