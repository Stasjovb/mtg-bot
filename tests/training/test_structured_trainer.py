"""Tests for ``train_structured_model`` in
``mtg_bot.training.trainer``.

Contract checks on small synthetic structured-token datasets:
losses drop, weights save to disk, progress JSON lands, callbacks
fire, validation tracks, error paths surface.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np
import pytest
import torch

from mtg_bot.training.action_encoding import ACTION_VOCAB_SIZE
from mtg_bot.training.structured_dataset import StructuredDataset
from mtg_bot.training.structured_model import (
    DEFAULT_N_PRINTINGS, N_EMB_FIELDS, N_SCALAR_FIELDS_V2, StructuredModelConfig,
)
from mtg_bot.training.trainer import (
    TrainingHistory, train_structured_model,
)


def _make_dataset(
    n_rows: int = 16,
    *,
    seq_len: int = 4,
    with_policy_mask: Optional[list[bool]] = None,
    seed: int = 0,
) -> StructuredDataset:
    """Make a deterministic small dataset for trainer smoke tests.

    Half the rows get policy supervision (visit on slots 0/1, both
    legal), the rest are value-only. Outcomes are -1/0/+1.
    """
    if with_policy_mask is None:
        with_policy_mask = [(i % 2 == 0) for i in range(n_rows)]
    rng = np.random.default_rng(seed)
    # Token type id 0..11 (N_TOKEN_TYPES=12). All emb-field ids set to
    # 0 (NA) to stay inside every sub-vocab — narrower than necessary
    # but bulletproof for unit-test inputs.
    token_type = rng.integers(0, 5, size=(n_rows, seq_len)).astype(np.int64)
    token_emb_ids = np.zeros(
        (n_rows, seq_len, N_EMB_FIELDS), dtype=np.int64,
    )
    token_scalars = rng.standard_normal(
        (n_rows, seq_len, N_SCALAR_FIELDS_V2),
    ).astype(np.float32)
    attention_mask = np.ones((n_rows, seq_len), dtype=np.bool_)
    outcomes = rng.choice(
        np.array([-1.0, 0.0, 1.0], dtype=np.float32), size=n_rows,
    )
    policy_targets = np.zeros((n_rows, ACTION_VOCAB_SIZE), dtype=np.float32)
    action_masks = np.zeros((n_rows, ACTION_VOCAB_SIZE), dtype=np.bool_)
    for i, has in enumerate(with_policy_mask):
        if has:
            policy_targets[i, 0] = 0.7
            policy_targets[i, 1] = 0.3
            action_masks[i, 0] = True
            action_masks[i, 1] = True
    return StructuredDataset(
        token_type=token_type,
        token_emb_ids=token_emb_ids,
        token_scalars=token_scalars,
        attention_mask=attention_mask,
        outcomes=outcomes,
        policy_targets=policy_targets,
        action_masks=action_masks,
    )


def _tiny_cfg() -> StructuredModelConfig:
    """A minimal config for fast unit tests."""
    return StructuredModelConfig(
        emb_dim=16,
        n_heads=2,
        n_layers=1,
        hidden_dim=32,
        n_printings=DEFAULT_N_PRINTINGS,
    )


def test_train_structured_model_saves_weights_and_history(
    tmp_path: Path,
) -> None:
    ds = _make_dataset(n_rows=16, seq_len=4)
    weights = tmp_path / "w.pt"
    history = train_structured_model(
        ds,
        weights_out_path=weights,
        config=_tiny_cfg(),
        epochs=3,
        batch_size=4,
        learning_rate=1e-2,
        val_split=0.25,
        device="cpu",
        rng_seed=0,
    )
    assert isinstance(history, TrainingHistory)
    assert weights.is_file()
    assert len(history.train_losses) == 3
    assert len(history.val_losses) == 3
    # Per-component loss series are populated.
    assert len(history.train_value_losses) == 3
    assert len(history.train_policy_losses) == 3
    # Total loss should be finite throughout.
    for x in history.train_losses + history.val_losses:
        assert x == x and abs(x) < 100.0  # not NaN; not exploded


def test_train_structured_model_loss_reduces(tmp_path: Path) -> None:
    """Loss reduces on a learnable signal: outcome = sign(first
    token-type id). With 4-token sequences and a fixed mapping, the
    transformer should fit comfortably in a handful of epochs."""
    rng = np.random.default_rng(42)
    n = 64
    seq_len = 4
    token_type = np.zeros((n, seq_len), dtype=np.int64)
    token_emb_ids = np.zeros((n, seq_len, N_EMB_FIELDS), dtype=np.int64)
    token_scalars = np.zeros(
        (n, seq_len, N_SCALAR_FIELDS_V2), dtype=np.float32,
    )
    attention_mask = np.ones((n, seq_len), dtype=np.bool_)
    # Pin the first token-type to {1,2}; map 1->+1, 2->-1.
    token_type[:, 0] = rng.choice([1, 2], size=n)
    outcomes = np.where(
        token_type[:, 0] == 1, 1.0, -1.0,
    ).astype(np.float32)
    policy_targets = np.zeros((n, ACTION_VOCAB_SIZE), dtype=np.float32)
    action_masks = np.zeros((n, ACTION_VOCAB_SIZE), dtype=np.bool_)
    ds = StructuredDataset(
        token_type=token_type,
        token_emb_ids=token_emb_ids,
        token_scalars=token_scalars,
        attention_mask=attention_mask,
        outcomes=outcomes,
        policy_targets=policy_targets,
        action_masks=action_masks,
    )
    history = train_structured_model(
        ds,
        weights_out_path=tmp_path / "w.pt",
        config=_tiny_cfg(),
        epochs=10,
        batch_size=16,
        learning_rate=5e-2,
        val_split=0.25,
        device="cpu",
        rng_seed=0,
    )
    # Final train loss should be visibly below initial.
    assert history.train_losses[-1] < history.train_losses[0]


def test_train_structured_model_progress_json_and_callback(
    tmp_path: Path,
) -> None:
    ds = _make_dataset(n_rows=8, seq_len=3)
    progress_path = tmp_path / "progress.json"
    calls: list[dict] = []
    history = train_structured_model(
        ds,
        weights_out_path=tmp_path / "w.pt",
        config=_tiny_cfg(),
        epochs=2,
        batch_size=4,
        learning_rate=1e-2,
        val_split=0.25,
        device="cpu",
        rng_seed=0,
        progress_path=progress_path,
        run_id="vTest",
        notes="hello",
        epoch_callback=lambda payload: calls.append(payload),
    )
    assert progress_path.is_file()
    blob = json.loads(progress_path.read_text())
    assert blob["status"] == "completed"
    assert blob["architecture"] == "structured"
    assert blob["run_id"] == "vTest"
    assert blob["notes"] == "hello"
    # Two epochs ⇒ two callback invocations.
    assert len(calls) == 2
    assert calls[0]["epoch"] == 1
    assert calls[-1]["epoch"] == 2


def test_train_structured_model_callback_exceptions_swallowed(
    tmp_path: Path,
) -> None:
    ds = _make_dataset(n_rows=8, seq_len=3)

    def boom(_payload: dict) -> None:
        raise RuntimeError("synthetic")

    # Should not raise — the trainer catches callback errors.
    train_structured_model(
        ds,
        weights_out_path=tmp_path / "w.pt",
        config=_tiny_cfg(),
        epochs=1,
        batch_size=4,
        learning_rate=1e-2,
        val_split=0.25,
        device="cpu",
        epoch_callback=boom,
    )


def test_train_structured_model_zero_val_split_runs(tmp_path: Path) -> None:
    """val_split=0 → no validation loader; val series come back NaN."""
    ds = _make_dataset(n_rows=8, seq_len=3)
    history = train_structured_model(
        ds,
        weights_out_path=tmp_path / "w.pt",
        config=_tiny_cfg(),
        epochs=2,
        batch_size=4,
        learning_rate=1e-2,
        val_split=0.0,
        device="cpu",
    )
    # All val losses are NaN — len matches train.
    assert len(history.val_losses) == 2
    for v in history.val_losses:
        assert np.isnan(v)


def test_train_structured_model_rejects_empty_dataset(tmp_path: Path) -> None:
    ds = StructuredDataset(
        token_type=np.zeros((0, 0), dtype=np.int64),
        token_emb_ids=np.zeros((0, 0, N_EMB_FIELDS), dtype=np.int64),
        token_scalars=np.zeros(
            (0, 0, N_SCALAR_FIELDS_V2), dtype=np.float32,
        ),
        attention_mask=np.zeros((0, 0), dtype=np.bool_),
        outcomes=np.zeros((0,), dtype=np.float32),
        policy_targets=np.zeros(
            (0, ACTION_VOCAB_SIZE), dtype=np.float32,
        ),
        action_masks=np.zeros(
            (0, ACTION_VOCAB_SIZE), dtype=np.bool_,
        ),
    )
    with pytest.raises(ValueError, match="empty dataset"):
        train_structured_model(
            ds,
            weights_out_path=tmp_path / "w.pt",
            epochs=1,
        )


def test_train_structured_model_rejects_invalid_val_split(
    tmp_path: Path,
) -> None:
    ds = _make_dataset(n_rows=4, seq_len=3)
    with pytest.raises(ValueError, match="val_split"):
        train_structured_model(
            ds,
            weights_out_path=tmp_path / "w.pt",
            epochs=1,
            val_split=1.5,
        )


def test_train_structured_model_rejects_non_positive_patience(
    tmp_path: Path,
) -> None:
    ds = _make_dataset(n_rows=8, seq_len=3)
    for bad in (0, -3):
        with pytest.raises(ValueError, match="early_stop_patience"):
            train_structured_model(
                ds,
                weights_out_path=tmp_path / "w.pt",
                config=_tiny_cfg(),
                epochs=2,
                batch_size=4,
                val_split=0.25,
                device="cpu",
                early_stop_patience=bad,
            )


def test_train_structured_model_early_stop_disabled_runs_all_epochs(
    tmp_path: Path,
) -> None:
    # Back-compat: ``early_stop_patience=None`` (the trainer-function
    # default) runs the full --epochs budget. Catches a regression where
    # adding the early-stop branch would short-circuit a None-disabled
    # run.
    ds = _make_dataset(n_rows=16, seq_len=4)
    history = train_structured_model(
        ds,
        weights_out_path=tmp_path / "w.pt",
        config=_tiny_cfg(),
        epochs=5,
        batch_size=4,
        learning_rate=1e-2,
        val_split=0.25,
        device="cpu",
        rng_seed=0,
        early_stop_patience=None,
    )
    assert len(history.train_losses) == 5


def test_train_structured_model_early_stop_fires_on_plateau(
    tmp_path: Path,
) -> None:
    # The structured-trainer mirror of
    # ``test_early_stop_fires_when_val_loss_plateaus``. With a small
    # synthetic dataset whose val loss plateaus within a few epochs,
    # ``early_stop_patience=2`` MUST stop training before the full
    # --epochs budget (50). This is the lever the D3 ablation
    # (docs/SCALING_DIAGNOSTICS.md) requires; without an early-stop
    # break the structured-CLI flag was a dead flag.
    ds = _make_dataset(n_rows=16, seq_len=4, seed=0)
    history = train_structured_model(
        ds,
        weights_out_path=tmp_path / "w.pt",
        config=_tiny_cfg(),
        epochs=50,
        batch_size=4,
        learning_rate=1e-2,
        val_split=0.25,
        device="cpu",
        rng_seed=0,
        early_stop_patience=2,
    )
    # Tiny network on a tiny dataset hits best val within ~1-3 epochs,
    # then plateaus; patience=2 should fire well before 50.
    assert len(history.train_losses) < 50, (
        f"early-stop did not fire; ran all {len(history.train_losses)} epochs"
    )
    # The trained history is contiguous and val data is populated.
    assert len(history.val_losses) == len(history.train_losses)
    assert history.best_val_epoch >= 0


def test_train_structured_model_emits_failed_on_exception(
    tmp_path: Path, monkeypatch,
) -> None:
    """A crash during training writes ``status='failed'`` to the
    progress JSON before re-raising."""
    ds = _make_dataset(n_rows=4, seq_len=3)
    progress_path = tmp_path / "progress.json"

    # Force a failure inside the forward pass by zeroing model weights
    # — simpler: monkeypatch ``Adam.step`` to raise on first call.
    from torch.optim import Adam
    real_step = Adam.step
    state = {"calls": 0}

    def angry_step(self, *args, **kwargs):  # noqa: ANN001
        state["calls"] += 1
        if state["calls"] >= 1:
            raise RuntimeError("synthetic-failure")
        return real_step(self, *args, **kwargs)

    monkeypatch.setattr(Adam, "step", angry_step)

    with pytest.raises(RuntimeError, match="synthetic-failure"):
        train_structured_model(
            ds,
            weights_out_path=tmp_path / "w.pt",
            config=_tiny_cfg(),
            epochs=1,
            batch_size=4,
            val_split=0.25,
            device="cpu",
            progress_path=progress_path,
        )
    assert progress_path.is_file()
    blob = json.loads(progress_path.read_text())
    assert blob["status"] == "failed"


def test_train_structured_model_default_device_auto(
    tmp_path: Path, monkeypatch,
) -> None:
    """When ``device=None``, the trainer calls ``auto_device``."""
    ds = _make_dataset(n_rows=4, seq_len=3)
    monkeypatch.setattr(
        "mtg_bot.training.trainer.auto_device", lambda: "cpu",
    )
    history = train_structured_model(
        ds,
        weights_out_path=tmp_path / "w.pt",
        config=_tiny_cfg(),
        epochs=1,
        batch_size=4,
    )
    assert len(history.train_losses) == 1


# ---------------------------------------------------------------------
# Scalar schema: the trainer refuses a dataset / config width mismatch
# ---------------------------------------------------------------------


def test_dataset_exposes_scalar_width() -> None:
    ds = _make_dataset(n_rows=4, seq_len=3)
    assert ds.scalar_width == N_SCALAR_FIELDS_V2


def test_train_structured_model_rejects_scalar_width_mismatch(
    tmp_path: Path,
) -> None:
    """A v2-wide dataset trained under a schema-1 config (or vice
    versa) must fail loudly before any batch is touched, naming both
    widths and the fix."""
    import pytest
    ds = _make_dataset(n_rows=8, seq_len=4)  # v2-wide rows
    cfg_v1 = StructuredModelConfig(
        emb_dim=16, n_heads=2, n_layers=1, hidden_dim=32,
        n_printings=DEFAULT_N_PRINTINGS, scalar_schema_version=1,
    )
    with pytest.raises(ValueError, match="scalar schema mismatch") as exc:
        train_structured_model(
            ds, weights_out_path=tmp_path / "w.pt", config=cfg_v1,
            epochs=1, batch_size=4, device="cpu", compile_model=False,
        )
    msg = str(exc.value)
    assert str(N_SCALAR_FIELDS_V2) in msg and "3" in msg
    assert "--scalar-schema-version" in msg
    assert not (tmp_path / "w.pt").exists()


def test_train_structured_model_accepts_matching_v1_width(
    tmp_path: Path,
) -> None:
    """Schema-1 data + schema-1 config trains (old-layout data is
    still trainable when the config opts into schema 1)."""
    rng = np.random.default_rng(0)
    n, seq_len = 8, 4
    ds = StructuredDataset(
        token_type=rng.integers(0, 5, size=(n, seq_len)).astype(np.int64),
        token_emb_ids=np.zeros((n, seq_len, N_EMB_FIELDS), dtype=np.int64),
        token_scalars=rng.standard_normal((n, seq_len, 3)).astype(np.float32),
        attention_mask=np.ones((n, seq_len), dtype=np.bool_),
        outcomes=np.zeros(n, dtype=np.float32),
        policy_targets=np.zeros((n, ACTION_VOCAB_SIZE), dtype=np.float32),
        action_masks=np.zeros((n, ACTION_VOCAB_SIZE), dtype=np.bool_),
    )
    assert ds.scalar_width == 3
    cfg_v1 = StructuredModelConfig(
        emb_dim=16, n_heads=2, n_layers=1, hidden_dim=32,
        n_printings=DEFAULT_N_PRINTINGS, scalar_schema_version=1,
    )
    history = train_structured_model(
        ds, weights_out_path=tmp_path / "w1.pt", config=cfg_v1,
        epochs=1, batch_size=4, device="cpu", compile_model=False,
        val_split=0.0,
    )
    assert len(history.train_losses) == 1
    assert (tmp_path / "w1.pt").exists()
