"""PyTorch training loop for the value (and optional policy) network.

Loads (features, outcomes [, policy_targets, action_masks]) from
data_gen, fits ``_ValueMLP`` (value-only) or ``_ValuePolicyMLP``
(dual-head) from nn_evaluator.py, saves weights to disk in the
state_dict format NNEvaluator loads.

Loss:

- Value-only mode: MSE between value head output and the game-
  outcome target (-1 / 0 / +1).
- AlphaZero mode: same value-MSE PLUS cross-entropy between the
  policy head's masked log-softmax and the per-row visit
  distribution. Policy loss only contributes for rows where the
  visit distribution carries actual supervision (sum > 0.5);
  rows from baseline strategies or data-doubled non-active-viewer
  views go through value-only.

Mode selection is automatic: pass ``policy_targets`` +
``action_masks`` arrays to ``train_value_network`` for AlphaZero
training; omit them for value-only. Function name kept (rather than
renamed to ``train_actor_critic``) so the existing CLI / tests /
imports keep working — the AlphaZero supervision is opt-in.

Adam optimizer. Train/val split for monitoring overfitting. CUDA
when available; CPU pin to a single thread because OMP/MKL barrier
sync dominates on tiny matmuls (revisit when we scale past ~100k
params).
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
import torch.nn.functional as F
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

from mtg_bot.search.nn_evaluator import _ValueMLP, _ValuePolicyMLP


@dataclass
class TrainingHistory:
    """One training-run summary.

    ``train_losses`` / ``val_losses`` are per-epoch mean TOTAL loss
    (value MSE + λ·policy CE in AlphaZero mode; value MSE alone in
    value-only mode).

    The two ``*_value_*`` and ``*_policy_*`` lists carry the
    per-component per-epoch averages so the trainer can report each
    head's progress separately. In value-only mode the policy
    components are NaN (no policy head to track).

    ``best_val_loss`` is the lowest TOTAL val loss seen — the epoch
    we'd checkpoint at if we did early stopping.
    """

    train_losses: list[float] = field(default_factory=list)
    val_losses: list[float] = field(default_factory=list)
    train_value_losses: list[float] = field(default_factory=list)
    val_value_losses: list[float] = field(default_factory=list)
    train_policy_losses: list[float] = field(default_factory=list)
    val_policy_losses: list[float] = field(default_factory=list)
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
    policy_targets: Optional[np.ndarray] = None,
    action_masks: Optional[np.ndarray] = None,
    policy_loss_weight: float = 1.0,
) -> TrainingHistory:
    """Fit a value (or value+policy) network to the supplied
    training data and write the final state_dict to
    ``weights_out_path``.

    ``features``: ``(N, FEATURE_DIM)`` float32. ``outcomes``: ``(N,)``
    float32 in ``{-1, 0, +1}``.

    AlphaZero mode (opt-in): pass both ``policy_targets`` (``(N,
    ACTION_VOCAB_SIZE)`` float32 — per-row normalized visit
    distribution from MCTS, all-zero rows = no policy supervision)
    and ``action_masks`` (``(N, ACTION_VOCAB_SIZE)`` bool — legal-
    slot mask per row, all-False for rows without supervision).
    With both provided, we instantiate ``_ValuePolicyMLP`` instead
    of ``_ValueMLP``, the loss becomes
    ``MSE(v, z) + policy_loss_weight · masked_CE(p_pred, π_target)``,
    and the policy CE only sums over rows whose policy_target sum
    is > 0.5 (other rows contribute zero to the policy loss).

    Value-only mode (default): both ``policy_targets`` and
    ``action_masks`` omitted. Trains ``_ValueMLP`` on MSE, exact
    pre-A2.3 behavior. The existing CLI / tests don't change.

    The split is deterministic in ``rng_seed`` so re-running with
    the same seed and dataset reproduces the same train/val
    partition (important for tuning loops that compare training
    runs at different hyperparameters).

    If ``progress_path`` is given, a JSON status file is written
    after each epoch (and once at startup) so an external viewer
    can poll it. Writes are atomic via ``os.replace`` — a polling
    reader never sees a half-written file. ``run_id`` is the stable
    identifier baked into that file; it defaults to the file stem.

    Returns a ``TrainingHistory`` with per-epoch losses (total +
    value + policy components separately). The weights file
    written at ``weights_out_path`` always reflects the FINAL
    epoch, not the best-val-loss epoch — early stopping isn't
    implemented yet.
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
    if (policy_targets is None) != (action_masks is None):
        raise ValueError(
            "policy_targets and action_masks must be provided "
            "together (or both omitted for value-only training)"
        )
    with_policy = policy_targets is not None
    if with_policy:
        if policy_targets.shape[0] != features.shape[0]:
            raise ValueError(
                f"policy_targets rows {policy_targets.shape[0]} != "
                f"features rows {features.shape[0]}"
            )
        if action_masks.shape != policy_targets.shape:
            raise ValueError(
                f"action_masks shape {action_masks.shape} != "
                f"policy_targets shape {policy_targets.shape}"
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

    if with_policy:
        # Pack policy targets, action masks, and a per-row "has
        # supervision" flag into the dataloader alongside features
        # and outcomes. The flag (computed once here) is the cheap
        # gate that lets the inner loop skip the policy loss for
        # rows where MCTS didn't provide visits.
        p_train = torch.from_numpy(policy_targets[train_idx]).float()
        m_train = torch.from_numpy(
            action_masks[train_idx],
        ).bool()
        has_pol_train = torch.from_numpy(
            (policy_targets[train_idx].sum(axis=-1) > 0.5),
        ).float().unsqueeze(1)
        p_val = torch.from_numpy(policy_targets[val_idx]).float()
        m_val = torch.from_numpy(action_masks[val_idx]).bool()
        has_pol_val = torch.from_numpy(
            (policy_targets[val_idx].sum(axis=-1) > 0.5),
        ).float().unsqueeze(1)
        train_loader = DataLoader(
            TensorDataset(
                x_train, y_train, p_train, m_train, has_pol_train,
            ),
            batch_size=batch_size, shuffle=True,
            generator=torch.Generator().manual_seed(rng_seed),
        )
        model = _ValuePolicyMLP().to(device_obj)
    else:
        train_loader = DataLoader(
            TensorDataset(x_train, y_train),
            batch_size=batch_size, shuffle=True,
            generator=torch.Generator().manual_seed(rng_seed),
        )
        model = _ValueMLP().to(device_obj)

    optimizer = optim.Adam(model.parameters(), lr=learning_rate)
    mse = nn.MSELoss()

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

    def _policy_loss(
        policy_logits: torch.Tensor,
        target_dist: torch.Tensor,
        action_mask: torch.Tensor,
        has_supervision: torch.Tensor,
    ) -> torch.Tensor:
        """Masked cross-entropy averaged over rows that have policy
        supervision. Rows with all-zero target / all-False mask
        contribute zero — the ``has_supervision`` gate scales them
        to 0 and they never reach the denominator.

        Implementation note: we use ``-1e9`` (not ``-inf``) for
        masked slots. log_softmax of an all-``-inf`` row is NaN
        (softmax denominator is 0, log of 0 is undefined), and
        ``NaN * 0`` is still NaN — would propagate through the
        gate. ``-1e9`` is finite enough to keep softmax stable
        (e^-1e9 ≈ 0 in float32 anyway) and finite enough that
        log_softmax of an all-``-1e9`` row is uniform-then-finite
        rather than NaN. The unsupervised-row contribution then
        cleanly multiplies to 0.
        """
        masked_logits = policy_logits.masked_fill(~action_mask, -1e9)
        log_probs = F.log_softmax(masked_logits, dim=-1)
        per_row_ce = -(target_dist * log_probs).sum(dim=-1)
        weighted = per_row_ce * has_supervision.squeeze(-1)
        denom = has_supervision.sum().clamp(min=1.0)
        return weighted.sum() / denom

    try:
        for epoch in range(epochs):
            # Train.
            model.train()
            train_total: list[float] = []
            train_value: list[float] = []
            train_policy: list[float] = []
            for batch in train_loader:
                if with_policy:
                    bx, by, bp, bm, bhas = (
                        t.to(device_obj) for t in batch
                    )
                else:
                    bx, by = (t.to(device_obj) for t in batch)
                optimizer.zero_grad()
                if with_policy:
                    v_pred, p_logits = model(bx)
                    v_loss = mse(v_pred, by)
                    p_loss = _policy_loss(p_logits, bp, bm, bhas)
                    total = v_loss + policy_loss_weight * p_loss
                    train_value.append(v_loss.item())
                    train_policy.append(p_loss.item())
                else:
                    pred = model(bx)
                    total = mse(pred, by)
                    train_value.append(total.item())
                    train_policy.append(float("nan"))
                total.backward()
                optimizer.step()
                train_total.append(total.item())
            history.train_losses.append(float(np.mean(train_total)))
            history.train_value_losses.append(
                float(np.mean(train_value))
            )
            history.train_policy_losses.append(
                float(np.nanmean(train_policy))
                if any(not np.isnan(x) for x in train_policy)
                else float("nan")
            )

            # Val (skip if no val data).
            if n_val > 0:
                model.eval()
                with torch.no_grad():
                    if with_policy:
                        v_pred_val, p_logits_val = model(
                            x_val.to(device_obj),
                        )
                        v_loss_val = mse(
                            v_pred_val, y_val.to(device_obj),
                        ).item()
                        p_loss_val = _policy_loss(
                            p_logits_val,
                            p_val.to(device_obj),
                            m_val.to(device_obj),
                            has_pol_val.to(device_obj),
                        ).item()
                        val_loss = (
                            v_loss_val
                            + policy_loss_weight * p_loss_val
                        )
                        history.val_value_losses.append(v_loss_val)
                        history.val_policy_losses.append(p_loss_val)
                    else:
                        val_pred = model(x_val.to(device_obj))
                        val_loss = mse(
                            val_pred, y_val.to(device_obj),
                        ).item()
                        history.val_value_losses.append(val_loss)
                        history.val_policy_losses.append(
                            float("nan")
                        )
            else:
                val_loss = float("nan")
                history.val_value_losses.append(float("nan"))
                history.val_policy_losses.append(float("nan"))
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
