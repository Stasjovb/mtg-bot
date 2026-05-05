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


def test_compile_model_falls_back_when_triton_missing(tmp_path: Path):
    """``compile_model=True`` should never crash a training run —
    it should issue a warning and proceed in eager mode if Triton
    isn't installed (the inductor backend's hard dep, which isn't
    packaged for Windows). Verifies the fallback path produces a
    saved weights file and the same TrainingHistory shape as the
    no-compile path."""
    features, outcomes = _synthetic_dataset(64)
    # We don't assert the warning fires (the test box may have
    # Triton installed if it's Linux). We DO assert the run
    # completes and writes a usable weights file regardless.
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("default")
        history = train_value_network(
            features=features, outcomes=outcomes,
            weights_out_path=tmp_path / "w.pt",
            epochs=2, batch_size=16, device="cpu",
            compile_model=True,
        )
    assert isinstance(history, TrainingHistory)
    assert len(history.train_losses) == 2
    assert (tmp_path / "w.pt").is_file()
    # Loaded state_dict should have plain key names — no
    # ``_orig_mod.`` prefix from torch.compile (we save the
    # underlying module's state_dict, not the wrapper's).
    sd = torch.load(tmp_path / "w.pt", map_location="cpu")
    assert all(not k.startswith("_orig_mod.") for k in sd.keys())


def test_custom_hidden_sizes_roundtrip(tmp_path: Path):
    """Train with a non-default trunk shape, save, reload through
    NNEvaluator at the matching shape, run a forward pass. Catches
    any place the trunk size assumption was hardcoded.

    Uses a deliberately weird shape (not (128,128,64) or any other
    tested default) so a regression that ignores the kwarg and
    falls back to the module-level HIDDEN_SIZES constant trips the
    state_dict shape check at load time.
    """
    features, outcomes = _synthetic_dataset(64)
    custom = (96, 48, 24)  # not equal to any other default in the codebase
    history = train_value_network(
        features=features, outcomes=outcomes,
        weights_out_path=tmp_path / "w.pt",
        epochs=2, batch_size=16, device="cpu",
        hidden_sizes=custom,
    )
    assert isinstance(history, TrainingHistory)

    # Reload through NNEvaluator at the same shape — must succeed.
    ev = NNEvaluator(weights_path=tmp_path / "w.pt", hidden_sizes=custom)
    # Forward pass shape: a 1×FEATURE_DIM input → 1×1 value.
    x = torch.zeros(1, FEATURE_DIM)
    out = ev.model(x)
    assert out.shape == (1, 1)

    # Reloading at the WRONG shape must surface as a clear error.
    import pytest
    with pytest.raises(RuntimeError, match=r"size mismatch|shape"):
        NNEvaluator(weights_path=tmp_path / "w.pt")  # uses default shape


def test_training_reduces_loss_on_synthetic_data(tmp_path: Path):
    """Train for a few epochs on a tractable synthetic problem;
    final train loss should be lower than first-epoch loss. Catches
    bugs where backward pass is wrong, optimizer isn't stepping,
    etc.

    Uses 30 epochs at lr=1e-3 — enough updates for the production
    HIDDEN_SIZES network (420k params at the 2026-05-02 sizing) to
    show meaningful loss decrease without overshooting. The
    assertion is "loss went down at all", not "converged" — keeps
    the test fast in CI."""
    features, outcomes = _synthetic_dataset(256)
    history = train_value_network(
        features=features, outcomes=outcomes,
        weights_out_path=tmp_path / "w.pt",
        epochs=30, batch_size=32, learning_rate=1e-3,
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


# ---------- A4-wiring: AlphaZero mode (dual-head training) ------------------


def _synthetic_alphazero_dataset(
    n: int, seed: int = 0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Synthetic AlphaZero-shape data: random features, value
    target depends on first feature, policy target is one-hot on
    a slot picked from the second feature, action mask covers
    a small legal subset. Half the rows have policy supervision
    (sum=1) and half are value-only (sum=0) so the trainer's
    per-row gate gets exercised."""
    from mtg_bot.training.action_encoding import ACTION_VOCAB_SIZE
    rng = np.random.default_rng(seed)
    features = rng.standard_normal((n, FEATURE_DIM)).astype(np.float32)
    outcomes = np.tanh(features[:, 0]).astype(np.float32)
    policy_targets = np.zeros((n, ACTION_VOCAB_SIZE), dtype=np.float32)
    action_masks = np.zeros((n, ACTION_VOCAB_SIZE), dtype=np.bool_)
    for i in range(n):
        if i % 2 == 0:
            slot = int(features[i, 1] * 50) % ACTION_VOCAB_SIZE
            policy_targets[i, slot] = 1.0
            for j in range(slot, slot + 10):
                action_masks[i, j % ACTION_VOCAB_SIZE] = True
    return features, outcomes, policy_targets, action_masks


def test_alphazero_mode_runs_and_returns_dual_losses(tmp_path: Path):
    """``policy_targets`` + ``action_masks`` provided → trainer
    builds ``_ValuePolicyMLP``, returns history with both value and
    policy loss components per epoch."""
    f, o, p, m = _synthetic_alphazero_dataset(64)
    history = train_value_network(
        features=f, outcomes=o,
        policy_targets=p, action_masks=m,
        weights_out_path=tmp_path / "az.pt",
        epochs=3, batch_size=16, device="cpu",
    )
    assert len(history.train_value_losses) == 3
    assert len(history.train_policy_losses) == 3
    assert len(history.val_value_losses) == 3
    assert len(history.val_policy_losses) == 3
    assert all(not np.isnan(v) for v in history.train_value_losses)
    assert all(not np.isnan(v) for v in history.train_policy_losses)


def test_alphazero_mode_loads_into_dual_head_evaluator(tmp_path: Path):
    """Saved weights round-trip into ``NNEvaluator(with_policy=True)``
    cleanly. The state_dict shape must match ``_ValuePolicyMLP``."""
    from mtg_bot.search import NNEvaluator
    f, o, p, m = _synthetic_alphazero_dataset(64)
    out = tmp_path / "az.pt"
    train_value_network(
        features=f, outcomes=o,
        policy_targets=p, action_masks=m,
        weights_out_path=out,
        epochs=2, batch_size=16, device="cpu",
    )
    evaluator = NNEvaluator(weights_path=out, with_policy=True)
    x = torch.from_numpy(f[:1])
    with torch.no_grad():
        v, _p_logits = evaluator.model(x)
    assert v.shape == (1, 1)
    assert -1.0 <= float(v) <= 1.0


def test_alphazero_rejects_lonely_policy_arg(tmp_path: Path):
    """Passing only one of (policy_targets, action_masks) raises."""
    from mtg_bot.training.action_encoding import ACTION_VOCAB_SIZE
    f, o = _synthetic_dataset(32)
    p = np.zeros((32, ACTION_VOCAB_SIZE), dtype=np.float32)
    with pytest.raises(ValueError, match="must be provided together"):
        train_value_network(
            features=f, outcomes=o,
            policy_targets=p,
            weights_out_path=tmp_path / "x.pt",
            epochs=1, device="cpu",
        )


def test_alphazero_rows_with_no_supervision_dont_break_training(
    tmp_path: Path,
):
    """All rows are value-only (policy_target sum = 0). Trainer
    runs without errors; policy loss term is zero per batch
    (gate normalizes by max(supervision_count, 1) → loss 0)."""
    from mtg_bot.training.action_encoding import ACTION_VOCAB_SIZE
    f, o = _synthetic_dataset(64)
    p = np.zeros((64, ACTION_VOCAB_SIZE), dtype=np.float32)
    m = np.zeros((64, ACTION_VOCAB_SIZE), dtype=np.bool_)
    history = train_value_network(
        features=f, outcomes=o,
        policy_targets=p, action_masks=m,
        weights_out_path=tmp_path / "x.pt",
        epochs=2, batch_size=16, device="cpu",
    )
    assert all(v == 0.0 for v in history.train_policy_losses)


def test_alphazero_target_on_illegal_slot_does_not_explode_loss(
    tmp_path: Path,
):
    """One row carrying ``policy_target`` mass on an
    ``action_mask=False`` slot must not produce a ~1e9 per-row CE
    that dominates the batch average via the trainer's
    ``masked_fill(~mask, -1e9)``. Defensive: the loss zeros target
    mass on illegal slots before computing CE.

    Reproduction: 46 such rows in the historical iterate_data pool
    drove iter_002's training to train_policy_loss ~7000 and a flat
    val_policy_loss ~14336 across 7 epochs (gradient was dominated
    by ``-1e9`` slots, killing learning).
    """
    from mtg_bot.training.action_encoding import ACTION_VOCAB_SIZE
    f, o, p, m = _synthetic_alphazero_dataset(64)
    # Pick a supervised row (even index per the synthetic builder)
    # and place 30% of its target mass on a slot the mask marks
    # illegal. Renormalize the rest down to keep sum=1.0 (matches
    # how production data is shaped — sums to 1 with mass leaking
    # onto illegal slots).
    bad_row = 2
    legal_slots = np.where(m[bad_row])[0]
    illegal_slots = np.where(~m[bad_row])[0]
    assert len(illegal_slots) > 0
    p[bad_row, :] = 0.0
    p[bad_row, legal_slots[0]] = 0.7
    p[bad_row, illegal_slots[0]] = 0.3  # the offending slot

    history = train_value_network(
        features=f, outcomes=o,
        policy_targets=p, action_masks=m,
        weights_out_path=tmp_path / "x.pt",
        epochs=2, batch_size=16, device="cpu",
    )
    # Without the fix: per-row CE on the bad row ≈ 1e9 * 0.3 = 3e8.
    # That single row drives the batch average past 1e6.
    # With the fix: loss is bounded by log(ACTION_VOCAB_SIZE) ≈ 6.3
    # (uniform over the legal slots).
    for v in history.train_policy_losses:
        assert v < 100.0, f"loss exploded: {v}"
        assert np.isfinite(v), f"loss not finite: {v}"
    for v in history.val_policy_losses:
        assert v < 100.0, f"val loss exploded: {v}"
        assert np.isfinite(v), f"val loss not finite: {v}"


def test_alphazero_policy_loss_weight_scales_combined_loss(
    tmp_path: Path,
):
    """Bumping ``policy_loss_weight`` from 1.0 to a larger value
    must visibly reweight the combined loss. Smoke-pin: at weight 5.0
    the policy term contributes ~5x more to ``total_loss`` than at
    weight 1.0 on the same data, so the train_total at epoch 1 must
    be measurably larger when the weight is higher.

    Defends the iter_002 v13 finding: with weight=1.0 the policy
    head plateaus because value loss dominates the gradient ~3:1.
    Weight=5.0 puts policy in the lead. This test pins the knob's
    end-to-end effect (CLI default → train_value_network kwarg →
    combined-loss math).
    """
    f, o, p, m = _synthetic_alphazero_dataset(64)

    h_default = train_value_network(
        features=f, outcomes=o,
        policy_targets=p, action_masks=m,
        weights_out_path=tmp_path / "az_default.pt",
        epochs=1, batch_size=16, device="cpu",
    )
    h_boosted = train_value_network(
        features=f, outcomes=o,
        policy_targets=p, action_masks=m,
        weights_out_path=tmp_path / "az_boosted.pt",
        epochs=1, batch_size=16, device="cpu",
        policy_loss_weight=5.0,
    )
    # train_value and train_policy are unaffected by the weight (they
    # are the raw per-component losses); the COMBINED train_loss
    # incorporates weight * policy_loss. Same data + same epochs +
    # cpu = the per-component values track but the combined diverges.
    assert (
        h_boosted.train_losses[0] > h_default.train_losses[0]
    ), (
        f"weight=5.0 should produce larger combined loss "
        f"(was {h_boosted.train_losses[0]}) than weight=1.0 "
        f"(was {h_default.train_losses[0]})"
    )
