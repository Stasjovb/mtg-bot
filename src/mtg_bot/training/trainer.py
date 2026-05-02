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

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

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


def _git_short_sha() -> Optional[str]:
    """Best-effort current git commit short SHA; ``None`` if not in
    a git repo or git isn't on PATH. Stamped onto the progress JSON
    so a viewer can correlate runs to code state."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=3, check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        pass
    return None


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write ``payload`` to ``path`` atomically: serialize to a
    sibling ``.tmp`` file then ``os.replace`` it into place. Replace
    is atomic on both POSIX and Windows, so a polling reader either
    sees the previous version or the new one — never a half-file.

    Windows wrinkle: if a reader currently has the destination file
    open (even just for the duration of a ``read_text`` call),
    ``os.replace`` raises ``PermissionError`` because Windows MOVEFILE
    requires deletable access. The contention window for a 2-second
    polling reader doing one fast read is small (~ms), so a tight
    retry loop reliably wins. If we can't get through after ~1s,
    raise — that's a real bug, not a transient race.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
    delay = 0.005
    for _ in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(delay)
            delay = min(delay * 2, 0.1)
    # One last try; let the exception propagate if it still fails.
    os.replace(tmp, path)


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
    progress_path: Optional[Path] = None,
    run_id: Optional[str] = None,
    notes: str = "",
) -> TrainingHistory:
    """Fit a ``_ValueMLP`` to ``(features, outcomes)`` and write the
    final state_dict to ``weights_out_path``.

    ``features``: ``(N, FEATURE_DIM)`` float32. ``outcomes``: ``(N,)``
    float32 in ``{-1, 0, +1}``.

    The split is deterministic in ``rng_seed`` so re-running with
    the same seed and dataset reproduces the same train/val
    partition (important for tuning loops that compare training
    runs at different hyperparameters).

    If ``progress_path`` is given, a JSON status file is written
    after each epoch (and once at startup) so an external viewer
    can poll it. Writes are atomic via ``os.replace`` — a polling
    reader never sees a half-written file. ``run_id`` is the stable
    identifier baked into that file; it defaults to the file stem.

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

    # Pin to a single torch thread on CPU. With our small batches
    # (256 rows × FEATURE_DIM=51 floats) and small model (~25k
    # params), per-batch OMP/MKL barrier sync across the host's
    # cores costs more than it saves — empirically observed an
    # ~85× slowdown going from 1 thread to 32 threads on a 32-core
    # box (248s/epoch → 2.93s/epoch). Once the model scales up to
    # ~100k+ parameters the matmul work per batch grows enough
    # that multi-threading wins; revisit this pin then.
    # GPU training is unaffected (set_num_threads governs CPU only).
    if device is None:
        device = auto_device()
    if device == "cpu":
        torch.set_num_threads(1)
    device_obj = torch.device(device)
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

    # Progress emission. Snapshot a few values up front so the writer
    # never has to recompute or worry about dataclass mutation
    # mid-write.
    progress_enabled = progress_path is not None
    started_at_iso = ""
    started_perf = 0.0
    git_commit: Optional[str] = None
    if progress_enabled:
        progress_path = Path(progress_path)
        if run_id is None:
            run_id = progress_path.stem
        started_at_iso = datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )
        started_perf = time.perf_counter()
        git_commit = _git_short_sha()

    def _emit(status: str, current_epoch: int) -> None:
        if not progress_enabled:
            return
        elapsed = time.perf_counter() - started_perf
        done = max(current_epoch, 0)
        avg = (elapsed / done) if done > 0 else 0.0
        remaining_epochs = max(epochs - done, 0)
        eta = avg * remaining_epochs if avg > 0 else 0.0
        payload = {
            "run_id": run_id,
            "started_at": started_at_iso,
            "total_epochs": int(epochs),
            "current_epoch": int(done),
            "elapsed_seconds": float(elapsed),
            "per_epoch_seconds_avg": float(avg),
            "estimated_remaining_seconds": float(eta),
            "train_losses": list(history.train_losses),
            "val_losses": list(history.val_losses),
            "status": status,
            "git_commit": git_commit,
            "notes": notes,
        }
        _atomic_write_json(progress_path, payload)

    # Initial "running" snapshot so the UI shows the run immediately,
    # before the first epoch finishes (epochs can be ~30s each at
    # 420k params on CPU).
    _emit("running", current_epoch=0)

    try:
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
                    val_loss = loss_fn(
                        val_pred, y_val.to(device_obj),
                    ).item()
            else:
                val_loss = float("nan")
            history.val_losses.append(val_loss)

            if val_loss < history.best_val_loss:
                history.best_val_loss = val_loss
                history.best_val_epoch = epoch

            _emit("running", current_epoch=epoch + 1)
    except BaseException:
        # Mark the run failed before re-raising so a watcher knows
        # not to keep polling. BaseException so even KeyboardInterrupt
        # leaves a useful tombstone.
        try:
            _emit("failed", current_epoch=len(history.train_losses))
        except Exception:
            # Don't mask the original error with a logging error.
            pass
        raise

    # Save final weights. (Move back to CPU so the state_dict is
    # device-agnostic when loaded.)
    model.to("cpu")
    torch.save(model.state_dict(), weights_out_path)
    history.weights_path = weights_out_path

    _emit("completed", current_epoch=epochs)

    return history
