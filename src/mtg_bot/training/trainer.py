"""PyTorch training loop for the value network.

Loads (features, outcomes) from data_gen, fits the existing
``_ValueMLP`` architecture from nn_evaluator.py, saves weights to
disk in the same state_dict format NNEvaluator loads.

Standard supervised regression: MSE loss between network output
and the game-outcome target (-1 / 0 / +1). Adam optimizer. Train/val
split for monitoring overfitting. CUDA when available — a small MLP
on tens of thousands of samples trains in seconds on a 5090.

Phase D scope: train one network from one batch of data. Phase E /
later may add iteration (use trained NN to play next round of data,
retrain, repeat) and policy heads (visit-count distribution targets).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

from mtg_bot.search.nn_evaluator import _ValueMLP


@dataclass
class TrainingHistory:
    """One training-run summary. ``train_losses`` and ``val_losses``
    are per-epoch mean MSE; ``best_val_loss`` is the lowest val
    loss seen (the epoch we'd checkpoint at if we did early
    stopping)."""

    train_losses: list[float] = field(default_factory=list)
    val_losses: list[float] = field(default_factory=list)
    best_val_loss: float = float("inf")
    best_val_epoch: int = -1
    weights_path: Optional[Path] = None


def auto_device() -> str:
    """Return ``"cuda"`` when a CUDA device is available, else
    ``"cpu"``. Convenience for callers that don't care which."""
    return "cuda" if torch.cuda.is_available() else "cpu"


def train_value_network(
    features: np.ndarray,
    outcomes: np.ndarray,
    *,
    weights_out_path: Path,
    epochs: int = 30,
    batch_size: int = 256,
    learning_rate: float = 1e-3,
    val_split: float = 0.1,
    device: Optional[str] = None,
    rng_seed: int = 0,
) -> TrainingHistory:
    """Fit a ``_ValueMLP`` to ``(features, outcomes)`` and write the
    final state_dict to ``weights_out_path``.

    ``features``: ``(N, FEATURE_DIM)`` float32. ``outcomes``: ``(N,)``
    float32 in ``{-1, 0, +1}``.

    The split is deterministic in ``rng_seed`` so re-running with
    the same seed and dataset reproduces the same train/val
    partition (important for tuning loops that compare training
    runs at different hyperparameters).

    Returns a ``TrainingHistory`` with per-epoch losses. The weights
    file written at ``weights_out_path`` always reflects the FINAL
    epoch, not the best-val-loss epoch — early stopping isn't
    implemented yet (Phase E if needed).
    """
    if features.shape[0] != outcomes.shape[0]:
        raise ValueError(
            f"features rows {features.shape[0]} != outcomes len "
            f"{outcomes.shape[0]}"
        )
    if features.shape[0] == 0:
        raise ValueError("cannot train on an empty dataset")
    if not (0.0 <= val_split < 1.0):
        raise ValueError(
            f"val_split must be in [0, 1); got {val_split}"
        )

    device_obj = torch.device(device or auto_device())
    torch.manual_seed(rng_seed)

    # Train/val split. Shuffle indices once, slice deterministically.
    n = features.shape[0]
    rng = np.random.default_rng(rng_seed)
    perm = rng.permutation(n)
    n_val = int(n * val_split)
    val_idx = perm[:n_val]
    train_idx = perm[n_val:]

    x_train = torch.from_numpy(features[train_idx]).float()
    y_train = torch.from_numpy(outcomes[train_idx]).float().unsqueeze(1)
    x_val = torch.from_numpy(features[val_idx]).float()
    y_val = torch.from_numpy(outcomes[val_idx]).float().unsqueeze(1)

    train_loader = DataLoader(
        TensorDataset(x_train, y_train),
        batch_size=batch_size, shuffle=True,
        generator=torch.Generator().manual_seed(rng_seed),
    )

    model = _ValueMLP().to(device_obj)
    optimizer = optim.Adam(model.parameters(), lr=learning_rate)
    loss_fn = nn.MSELoss()

    history = TrainingHistory()

    for epoch in range(epochs):
        # Train.
        model.train()
        train_losses_epoch: list[float] = []
        for batch_x, batch_y in train_loader:
            batch_x = batch_x.to(device_obj)
            batch_y = batch_y.to(device_obj)
            optimizer.zero_grad()
            pred = model(batch_x)
            loss = loss_fn(pred, batch_y)
            loss.backward()
            optimizer.step()
            train_losses_epoch.append(loss.item())
        train_loss = float(np.mean(train_losses_epoch))
        history.train_losses.append(train_loss)

        # Val (skip if no val data).
        if n_val > 0:
            model.eval()
            with torch.no_grad():
                val_pred = model(x_val.to(device_obj))
                val_loss = loss_fn(val_pred, y_val.to(device_obj)).item()
        else:
            val_loss = float("nan")
        history.val_losses.append(val_loss)

        if val_loss < history.best_val_loss:
            history.best_val_loss = val_loss
            history.best_val_epoch = epoch

    # Save final weights. (Move back to CPU so the state_dict is
    # device-agnostic when loaded.)
    model.to("cpu")
    torch.save(model.state_dict(), weights_out_path)
    history.weights_path = weights_out_path
    return history
