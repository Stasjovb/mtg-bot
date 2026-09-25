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

    # Force a failure inside the training step: monkeypatch the
    # optimizer's ``step`` to raise on first call. Patch ``AdamW``
    # specifically — that's what the trainer constructs now (decoupled
    # weight decay), and torch's ``Optimizer._patch_step_function``
    # copies a hooked ``step`` onto the concrete subclass the first
    # time one is instantiated, so patching the ``Adam`` base class
    # stops taking effect once any AdamW has been built in-process.
    from torch.optim import AdamW
    real_step = AdamW.step
    state = {"calls": 0}

    def angry_step(self, *args, **kwargs):  # noqa: ANN001
        state["calls"] += 1
        if state["calls"] >= 1:
            raise RuntimeError("synthetic-failure")
        return real_step(self, *args, **kwargs)

    monkeypatch.setattr(AdamW, "step", angry_step)

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


# ---------------------------------------------------------------------
# DataLoader stall guard.
# ---------------------------------------------------------------------

def _capture_dataloader_kwargs(monkeypatch) -> list[dict]:
    """Patch ``torch.utils.data.DataLoader`` so the trainer's loader
    kwargs are recorded. The returned loader is forced back to
    single-process so the test never actually spawns workers."""
    import torch.utils.data as _tud

    real = _tud.DataLoader
    seen: list[dict] = []

    def _fake(*args, **kwargs):
        seen.append(dict(kwargs))
        forced = dict(kwargs)
        forced["num_workers"] = 0
        forced["persistent_workers"] = False
        forced["timeout"] = 0
        return real(*args, **forced)

    monkeypatch.setattr(_tud, "DataLoader", _fake)
    return seen


def test_structured_trainer_sets_dataloader_timeout_with_workers(
    tmp_path: Path, monkeypatch,
) -> None:
    """``num_workers > 0`` must carry a ``timeout`` — without it a
    wedged worker hangs training forever with no error (2026-09-24).
    Both the train and val loaders get it."""
    seen = _capture_dataloader_kwargs(monkeypatch)
    ds = _make_dataset(16)
    train_structured_model(
        ds, weights_out_path=tmp_path / "w.pt",
        config=StructuredModelConfig(
            emb_dim=16, n_heads=2, n_layers=1, hidden_dim=32,
        ),
        epochs=1, batch_size=4, device="cpu", compile_model=False,
        val_split=0.25, num_workers=2, loader_timeout_sec=42.0,
    )
    assert len(seen) == 2, seen
    assert [k["timeout"] for k in seen] == [42.0, 42.0]


def test_structured_trainer_default_loader_timeout_is_600(
    tmp_path: Path, monkeypatch,
) -> None:
    seen = _capture_dataloader_kwargs(monkeypatch)
    ds = _make_dataset(16)
    train_structured_model(
        ds, weights_out_path=tmp_path / "w.pt",
        config=StructuredModelConfig(
            emb_dim=16, n_heads=2, n_layers=1, hidden_dim=32,
        ),
        epochs=1, batch_size=4, device="cpu", compile_model=False,
        val_split=0.0, num_workers=2,
    )
    assert [k["timeout"] for k in seen] == [600.0]


@pytest.mark.parametrize("timeout", [None, 0])
def test_structured_trainer_timeout_zero_without_workers(
    tmp_path: Path, monkeypatch, timeout,
) -> None:
    """torch's single-process iterator asserts ``timeout == 0``
    (``_SingleProcessDataLoaderIter requires timeout == 0``), so the
    guard must NOT be applied at ``num_workers=0``. Explicitly
    disabling it with workers is honoured too."""
    seen = _capture_dataloader_kwargs(monkeypatch)
    ds = _make_dataset(16)
    train_structured_model(
        ds, weights_out_path=tmp_path / "w.pt",
        config=StructuredModelConfig(
            emb_dim=16, n_heads=2, n_layers=1, hidden_dim=32,
        ),
        epochs=1, batch_size=4, device="cpu", compile_model=False,
        val_split=0.0, num_workers=0, loader_timeout_sec=timeout,
    )
    assert [k["timeout"] for k in seen] == [0]


def test_single_process_dataloader_rejects_nonzero_timeout() -> None:
    """Pins the torch behaviour the guard exists for: a non-zero
    timeout with 0 workers blows up at ITERATION time (not
    construction), which is why the trainer gates on num_workers."""
    from torch.utils.data import DataLoader

    loader = DataLoader(
        [torch.zeros(1) for _ in range(4)], batch_size=2,
        num_workers=0, timeout=600,
    )
    with pytest.raises(AssertionError, match="timeout == 0"):
        list(loader)


# ---------------------------------------------------------------------
# Regularisation: weight decay, restore-best, held-out value metrics.
# ---------------------------------------------------------------------


def test_weight_decay_reaches_adamw(tmp_path: Path, monkeypatch) -> None:
    """``weight_decay`` must land on a real AdamW (decoupled L2), not
    on the plain Adam the trainer used to build."""
    import torch.optim as _optim

    seen: list[dict] = []
    real = _optim.AdamW

    def spy(params, **kwargs):
        seen.append(dict(kwargs))
        return real(params, **kwargs)

    monkeypatch.setattr(_optim, "AdamW", spy)
    train_structured_model(
        _make_dataset(n_rows=8, seq_len=3),
        weights_out_path=tmp_path / "w.pt",
        config=_tiny_cfg(), epochs=1, batch_size=4, device="cpu",
        weight_decay=3e-4,
    )
    assert seen and seen[0]["weight_decay"] == 3e-4


def test_weight_decay_defaults_to_zero_for_direct_callers(
    tmp_path: Path, monkeypatch,
) -> None:
    """AdamW at weight_decay=0 is numerically Adam, so existing
    callers that never pass the knob see no behaviour change."""
    import torch.optim as _optim

    seen: list[dict] = []
    real = _optim.AdamW

    def spy(params, **kwargs):
        seen.append(dict(kwargs))
        return real(params, **kwargs)

    monkeypatch.setattr(_optim, "AdamW", spy)
    train_structured_model(
        _make_dataset(n_rows=8, seq_len=3),
        weights_out_path=tmp_path / "w.pt",
        config=_tiny_cfg(), epochs=1, batch_size=4, device="cpu",
    )
    assert seen[0]["weight_decay"] == 0.0


def test_negative_weight_decay_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="weight_decay must be >= 0"):
        train_structured_model(
            _make_dataset(n_rows=4, seq_len=3),
            weights_out_path=tmp_path / "w.pt",
            config=_tiny_cfg(), epochs=1, batch_size=4, device="cpu",
            weight_decay=-1e-4,
        )


def _diverging_run(tmp_path: Path, *, restore_best: bool, name: str):
    """Train with an absurd LR so val loss is best at an EARLY epoch
    and strictly worse afterwards — the situation restore-best exists
    for. Deterministic: the trainer seeds torch from ``rng_seed`` and
    the dataset is fixed."""
    return train_structured_model(
        _make_dataset(n_rows=16, seq_len=4),
        weights_out_path=tmp_path / name,
        config=_tiny_cfg(),
        epochs=4, batch_size=4, learning_rate=5.0,
        val_split=0.25, device="cpu", rng_seed=0,
        restore_best=restore_best,
    )


def test_restore_best_saves_best_epoch_not_final_epoch(
    tmp_path: Path,
) -> None:
    """The bug this closes: early stopping tracked ``best_val_epoch``
    and then saved the FINAL epoch's weights anyway."""
    h_last = _diverging_run(
        tmp_path, restore_best=False, name="last.pt",
    )
    h_best = _diverging_run(
        tmp_path, restore_best=True, name="best.pt",
    )
    # Same seed + same data => identical trajectory, so the ONLY
    # difference between the two files is which epoch got saved.
    assert h_last.val_losses == h_best.val_losses
    assert h_best.best_val_epoch < len(h_best.train_losses) - 1, (
        "test setup: best epoch must not be the last epoch"
    )
    assert h_best.restored_best_epoch == h_best.best_val_epoch
    assert h_last.restored_best_epoch is None

    last = torch.load(tmp_path / "last.pt", weights_only=True)
    best = torch.load(tmp_path / "best.pt", weights_only=True)
    assert any(
        not torch.equal(last[k], best[k]) for k in last
    ), "restore-best saved the same weights as keep-last"


def test_restore_best_is_a_noop_without_val_data(
    tmp_path: Path,
) -> None:
    """``val_split=0`` leaves no best epoch to restore; the final
    epoch's weights are kept and nothing pretends otherwise."""
    history = train_structured_model(
        _make_dataset(n_rows=8, seq_len=3),
        weights_out_path=tmp_path / "w.pt",
        config=_tiny_cfg(), epochs=2, batch_size=4, device="cpu",
        val_split=0.0, restore_best=True,
    )
    assert history.best_val_epoch == -1
    assert history.restored_best_epoch is None
    assert (tmp_path / "w.pt").is_file()


def test_holdout_value_metrics_populated(tmp_path: Path) -> None:
    history = train_structured_model(
        _make_dataset(n_rows=16, seq_len=4),
        weights_out_path=tmp_path / "w.pt",
        config=_tiny_cfg(), epochs=1, batch_size=4, device="cpu",
        val_split=0.25, rng_seed=0,
    )
    m = history.holdout_value_metrics
    assert m is not None
    assert m.n_rows == 4
    assert m.value_mse == m.value_mse  # finite, not NaN
    assert m.constant_zero_mse >= 0.0
    # JSON-safe for metadata.json / the progress card.
    json.dumps(m.as_dict())


def test_holdout_value_metrics_empty_without_val_split(
    tmp_path: Path,
) -> None:
    history = train_structured_model(
        _make_dataset(n_rows=8, seq_len=3),
        weights_out_path=tmp_path / "w.pt",
        config=_tiny_cfg(), epochs=1, batch_size=4, device="cpu",
        val_split=0.0,
    )
    m = history.holdout_value_metrics
    assert m is not None and m.n_rows == 0


def test_holdout_metrics_land_in_progress_json(tmp_path: Path) -> None:
    progress_path = tmp_path / "progress.json"
    train_structured_model(
        _make_dataset(n_rows=16, seq_len=4),
        weights_out_path=tmp_path / "w.pt",
        config=_tiny_cfg(), epochs=1, batch_size=4, device="cpu",
        val_split=0.25, progress_path=progress_path,
    )
    blob = json.loads(progress_path.read_text())
    assert blob["status"] == "completed"
    assert blob["holdout_value_metrics"]["n_rows"] == 4
    assert "value_mse" in blob["holdout_value_metrics"]


def test_holdout_life_diff_baseline_uses_global_token(
    tmp_path: Path,
) -> None:
    """With schema v2 scalars the trivial life-differential baseline
    correlation is reported; it is read off the GLOBAL token."""
    from mtg_bot.training.structured_model import (
        SCALAR_FIELD_OPP_LIFE, SCALAR_FIELD_VIEWER_LIFE,
        TOKEN_TYPE_GLOBAL,
    )

    # Every row's first token is the GLOBAL token, carrying a life
    # differential that tracks the outcome exactly.
    n_rows, seq_len, width = 16, 3, N_SCALAR_FIELDS_V2
    outcomes = np.array(
        [1.0 if i % 2 else -1.0 for i in range(n_rows)],
        dtype=np.float32,
    )
    token_type = np.full((n_rows, seq_len), 2, dtype=np.int64)
    token_type[:, 0] = TOKEN_TYPE_GLOBAL
    scalars = np.zeros((n_rows, seq_len, width), dtype=np.float32)
    scalars[:, 0, SCALAR_FIELD_VIEWER_LIFE] = 20.0 + 5.0 * outcomes
    scalars[:, 0, SCALAR_FIELD_OPP_LIFE] = 20.0
    ds = StructuredDataset(
        token_type=token_type,
        token_emb_ids=np.zeros(
            (n_rows, seq_len, N_EMB_FIELDS), dtype=np.int64,
        ),
        token_scalars=scalars,
        attention_mask=np.ones((n_rows, seq_len), dtype=np.bool_),
        outcomes=outcomes,
        policy_targets=np.zeros(
            (n_rows, ACTION_VOCAB_SIZE), dtype=np.float32,
        ),
        action_masks=np.zeros(
            (n_rows, ACTION_VOCAB_SIZE), dtype=np.bool_,
        ),
    )
    history = train_structured_model(
        ds,
        weights_out_path=tmp_path / "w.pt",
        config=_tiny_cfg(), epochs=1, batch_size=4, device="cpu",
        val_split=0.5, rng_seed=0,
    )
    m = history.holdout_value_metrics
    assert m.baseline_life_diff_corr is not None
    assert m.baseline_life_diff_corr > 0.99


def test_holdout_life_diff_baseline_skipped_for_schema_v1(
    tmp_path: Path,
) -> None:
    """Schema v1 rows carry no life fields — the baseline is reported
    as None rather than silently zero."""
    cfg_v1 = StructuredModelConfig(
        emb_dim=16, n_heads=2, n_layers=1, hidden_dim=32,
        scalar_schema_version=1,
    )
    n_rows, seq_len = 8, 3
    rng = np.random.default_rng(1)
    ds = StructuredDataset(
        token_type=np.ones((n_rows, seq_len), dtype=np.int64),
        token_emb_ids=np.zeros(
            (n_rows, seq_len, N_EMB_FIELDS), dtype=np.int64,
        ),
        # Schema-v1 rows are 3 scalars wide (no life fields at all).
        token_scalars=rng.standard_normal(
            (n_rows, seq_len, 3),
        ).astype(np.float32),
        attention_mask=np.ones((n_rows, seq_len), dtype=np.bool_),
        outcomes=rng.choice(
            np.array([-1.0, 1.0], dtype=np.float32), size=n_rows,
        ),
        policy_targets=np.zeros(
            (n_rows, ACTION_VOCAB_SIZE), dtype=np.float32,
        ),
        action_masks=np.zeros(
            (n_rows, ACTION_VOCAB_SIZE), dtype=np.bool_,
        ),
    )
    history = train_structured_model(
        ds,
        weights_out_path=tmp_path / "w.pt",
        config=cfg_v1, epochs=1, batch_size=4, device="cpu",
        val_split=0.25, rng_seed=0,
    )
    m = history.holdout_value_metrics
    assert m.n_rows > 0
    assert m.baseline_life_diff_corr is None


def test_global_life_diff_handles_rows_without_global_token() -> None:
    from mtg_bot.training.trainer import _global_life_diff

    token_type = torch.tensor([[1, 2], [2, 2]])
    scalars = torch.zeros((2, 2, 4), dtype=torch.float32)
    scalars[0, 0, 2] = 18.0   # viewer life on the global token
    scalars[0, 0, 3] = 11.0   # opponent life
    mask = torch.ones((2, 2), dtype=torch.bool)
    out = _global_life_diff(
        token_type, scalars, mask,
        global_type=1, viewer_idx=2, opp_idx=3,
    )
    assert out.tolist() == [7.0, 0.0]


def test_global_life_diff_ignores_padded_global_tokens() -> None:
    """A padded position that happens to carry the global type id must
    not be read — padding is uninitialised, not data."""
    from mtg_bot.training.trainer import _global_life_diff

    token_type = torch.tensor([[2, 1]])
    scalars = torch.zeros((1, 2, 4), dtype=torch.float32)
    scalars[0, 1, 2] = 99.0
    mask = torch.tensor([[True, False]])
    out = _global_life_diff(
        token_type, scalars, mask,
        global_type=1, viewer_idx=2, opp_idx=3,
    )
    assert out.tolist() == [0.0]


# ---------------------------------------------------------------------
# shuffle_mode wiring (see mtg_bot.training.block_shuffle)
# ---------------------------------------------------------------------


def test_train_structured_model_block_shuffle_runs(
    tmp_path: Path,
) -> None:
    """``shuffle_mode='block'`` trains end-to-end and produces the
    same history shape as the row-shuffle path."""
    ds = _make_dataset(n_rows=24, seq_len=4)
    weights = tmp_path / "w_block.pt"
    history = train_structured_model(
        ds,
        weights_out_path=weights,
        config=_tiny_cfg(),
        epochs=1,
        batch_size=4,
        learning_rate=1e-2,
        val_split=0.25,
        device="cpu",
        rng_seed=0,
        shuffle_mode="block",
        shuffle_block_rows=8,
    )
    assert isinstance(history, TrainingHistory)
    assert weights.is_file()
    assert len(history.train_losses) == 1
    assert history.train_losses[0] == history.train_losses[0]  # not NaN
    assert history.holdout_value_metrics is not None


def test_block_shuffle_visits_every_train_row_once_per_epoch(
    tmp_path: Path,
) -> None:
    """The load-bearing equivalence: block mode changes ORDER, not the
    row set. Counted through the real trainer by spying on the collate
    the DataLoader calls."""
    from mtg_bot.training import structured_dataset as sd_mod

    ds = _make_dataset(n_rows=24, seq_len=4)
    real_collate = sd_mod.structured_collate
    sizes: dict[str, list[int]] = {"row": [], "block": []}

    def _make_spy(mode: str):
        def _spy(items):
            sizes[mode].append(len(items))
            return real_collate(items)
        return _spy

    for mode in ("row", "block"):
        sd_mod.structured_collate = _make_spy(mode)
        try:
            train_structured_model(
                ds,
                weights_out_path=tmp_path / f"w_{mode}.pt",
                config=_tiny_cfg(),
                epochs=1,
                batch_size=4,
                learning_rate=1e-2,
                val_split=0.0,
                device="cpu",
                rng_seed=0,
                shuffle_mode=mode,
                shuffle_block_rows=7,
            )
        finally:
            sd_mod.structured_collate = real_collate
    # val_split=0 -> every row is a train row in both modes, and the
    # holdout re-score adds no batches (no val loader).
    assert sum(sizes["row"]) == 24
    assert sum(sizes["block"]) == 24


def test_train_structured_model_rejects_bad_shuffle_mode(
    tmp_path: Path,
) -> None:
    ds = _make_dataset(n_rows=8, seq_len=4)
    with pytest.raises(ValueError, match="shuffle_mode must be one of"):
        train_structured_model(
            ds,
            weights_out_path=tmp_path / "w.pt",
            config=_tiny_cfg(),
            epochs=1,
            batch_size=4,
            device="cpu",
            shuffle_mode="sideways",
        )


def test_train_structured_model_rejects_bad_block_rows(
    tmp_path: Path,
) -> None:
    ds = _make_dataset(n_rows=8, seq_len=4)
    with pytest.raises(ValueError, match="shuffle_block_rows must be"):
        train_structured_model(
            ds,
            weights_out_path=tmp_path / "w.pt",
            config=_tiny_cfg(),
            epochs=1,
            batch_size=4,
            device="cpu",
            shuffle_block_rows=0,
        )


def test_block_mode_sorts_the_val_split(tmp_path: Path) -> None:
    """Block mode also fixes the val loader's access pattern:
    ``grouped_train_val_split`` returns a PERMUTATION and the val
    loader reads it back with shuffle=False, so the eval pass was
    seeking every epoch too."""
    import torch.utils.data as tud

    made: list[list[int]] = []
    real_subset = tud.Subset

    class _RecordingSubset(real_subset):
        def __init__(self, dataset, indices):
            made.append(list(indices))
            super().__init__(dataset, indices)

    ds = _make_dataset(n_rows=40, seq_len=4)
    tud.Subset = _RecordingSubset
    try:
        train_structured_model(
            ds,
            weights_out_path=tmp_path / "w.pt",
            config=_tiny_cfg(),
            epochs=1,
            batch_size=4,
            device="cpu",
            val_split=0.25,
            rng_seed=3,
            shuffle_mode="block",
            shuffle_block_rows=8,
        )
    finally:
        tud.Subset = real_subset
    # Two Subsets are built: train then val. Block mode sorts val.
    assert len(made) == 2
    train_indices, val_indices = made
    assert len(val_indices) > 1
    assert val_indices == sorted(val_indices)
    # Together they still cover every row exactly once.
    assert sorted(train_indices + val_indices) == list(range(40))
