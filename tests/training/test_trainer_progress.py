"""Tests for the per-epoch progress JSON emission in
``train_value_network``.

Two interesting things to verify:

1. The contract: when ``progress_path=...`` is set, the file exists
   afterwards with the documented fields, the right epoch counts,
   and ``status="completed"``.
2. Atomicity: while training is running, a concurrent reader on
   another thread can read the file at any instant without ever
   seeing a half-written / unparseable JSON document. The trainer
   uses ``os.replace`` for this.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from mtg_bot.features import FEATURE_DIM
from mtg_bot.training import train_value_network


def _synthetic_dataset(n: int, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    features = rng.standard_normal((n, FEATURE_DIM)).astype(np.float32)
    outcomes = np.tanh(features[:, 0]).astype(np.float32)
    return features, outcomes


def test_progress_file_completed_after_training(tmp_path: Path):
    """Happy path. After a 5-epoch run, the JSON has all the
    fields the UI needs and status='completed'."""
    features, outcomes = _synthetic_dataset(64)
    progress = tmp_path / "v_test.json"

    train_value_network(
        features=features, outcomes=outcomes,
        weights_out_path=tmp_path / "w.pt",
        epochs=5, batch_size=16, device="cpu",
        progress_path=progress, run_id="v_test",
        notes="unit test",
    )

    assert progress.is_file()
    payload = json.loads(progress.read_text(encoding="utf-8"))
    assert payload["run_id"] == "v_test"
    assert payload["status"] == "completed"
    assert payload["total_epochs"] == 5
    assert payload["current_epoch"] == 5
    assert len(payload["train_losses"]) == 5
    assert len(payload["val_losses"]) == 5
    # ETA is 0 once we're done; elapsed and avg are positive.
    assert payload["elapsed_seconds"] > 0.0
    assert payload["per_epoch_seconds_avg"] > 0.0
    assert payload["estimated_remaining_seconds"] == 0.0
    assert payload["notes"] == "unit test"
    # ISO 8601 ish — at minimum has the date prefix.
    assert payload["started_at"].count("-") >= 2
    # git_commit may be None outside a repo; just check key exists.
    assert "git_commit" in payload
    # policy_loss_weight is recorded on the progress JSON so the UI
    # can show the actual scalar baked into the total-loss combination
    # (``total = value + policy_loss_weight × policy``). Default 1.0
    # when the caller doesn't pass one.
    assert payload["policy_loss_weight"] == 1.0


def test_progress_records_non_default_policy_loss_weight(tmp_path: Path):
    """When the trainer is invoked with ``policy_loss_weight != 1.0``,
    the progress JSON must echo the actual scalar so the UI can show
    the formula ``total = value + W × policy`` and the user can
    reconcile what they see on the card.

    AlphaZero mode requires both ``policy_targets`` and ``action_masks``
    to be present for ``policy_loss_weight`` to actually affect the
    combined loss math; we wire them in here too. The recorded value
    is independent of any of that — it is just the scalar threaded
    into the payload — but pinning the realistic call shape catches
    a future refactor that accidentally drops the kwarg from the
    progress writer.
    """
    # Local import to avoid a top-level cycle if action_encoding ever
    # picks up additional dependencies; mirrors the helper in
    # test_trainer.py.
    from mtg_bot.training.action_encoding import ACTION_VOCAB_SIZE

    rng = np.random.default_rng(0)
    n = 32
    features = rng.standard_normal((n, FEATURE_DIM)).astype(np.float32)
    outcomes = np.tanh(features[:, 0]).astype(np.float32)
    policy_targets = np.zeros((n, ACTION_VOCAB_SIZE), dtype=np.float32)
    action_masks = np.zeros((n, ACTION_VOCAB_SIZE), dtype=np.bool_)
    for i in range(n):
        slot = i % ACTION_VOCAB_SIZE
        policy_targets[i, slot] = 1.0
        action_masks[i, slot] = True

    progress = tmp_path / "v_weighted.json"
    train_value_network(
        features=features, outcomes=outcomes,
        policy_targets=policy_targets, action_masks=action_masks,
        weights_out_path=tmp_path / "w.pt",
        epochs=2, batch_size=8, device="cpu",
        progress_path=progress, run_id="v_weighted",
        policy_loss_weight=5.0,
    )
    payload = json.loads(progress.read_text(encoding="utf-8"))
    assert payload["policy_loss_weight"] == 5.0


def test_progress_run_id_defaults_to_filename_stem(tmp_path: Path):
    features, outcomes = _synthetic_dataset(32)
    progress = tmp_path / "v42.json"

    train_value_network(
        features=features, outcomes=outcomes,
        weights_out_path=tmp_path / "w.pt",
        epochs=2, batch_size=8, device="cpu",
        progress_path=progress,
    )

    payload = json.loads(progress.read_text(encoding="utf-8"))
    assert payload["run_id"] == "v42"


def test_progress_writes_are_atomic_under_concurrent_reads(
    tmp_path: Path,
):
    """Spin up a reader thread that polls the progress file while
    training runs. The reader records every successful parse — if
    the trainer were doing a non-atomic write, we'd eventually catch
    a JSONDecodeError. We require the reader to land at least one
    read showing status='running' (proving it really did read mid-
    training, not just the final completed state).
    """
    features, outcomes = _synthetic_dataset(128)
    progress = tmp_path / "v_atomic.json"

    stop = threading.Event()
    parses: list[dict] = []
    decode_errors: list[Exception] = []

    def _reader():
        while not stop.is_set():
            try:
                if progress.is_file():
                    parses.append(json.loads(
                        progress.read_text(encoding="utf-8")
                    ))
            except json.JSONDecodeError as e:
                decode_errors.append(e)
            except (FileNotFoundError, PermissionError):
                # FileNotFoundError: window between is_file() and
                # read_text — file got replaced. PermissionError:
                # the writer's MOVEFILE happened while we held the
                # read handle. Both are normal Windows behavior; the
                # next poll iteration succeeds. Either way we never
                # see a half-written file, which is the contract
                # this test is verifying.
                pass
            time.sleep(0.001)  # tight poll

    t = threading.Thread(target=_reader, daemon=True)
    t.start()
    try:
        train_value_network(
            features=features, outcomes=outcomes,
            weights_out_path=tmp_path / "w.pt",
            epochs=10, batch_size=16, device="cpu",
            progress_path=progress, run_id="v_atomic",
        )
    finally:
        stop.set()
        t.join(timeout=2)

    assert decode_errors == [], (
        f"reader saw {len(decode_errors)} half-written files; "
        f"first: {decode_errors[0]!r}"
    )
    assert parses, "reader never managed to read the file"
    statuses = {p.get("status") for p in parses}
    # We should have seen at least one 'running' snapshot during
    # the loop (the initial pre-epoch emit, if nothing else).
    assert "running" in statuses, (
        f"reader only ever saw statuses {statuses}; expected to "
        f"observe 'running' mid-training"
    )


def test_progress_failed_status_on_exception(tmp_path: Path):
    """If the training loop blows up, we emit status='failed'
    before re-raising. Use a deliberately-bad val_split to force
    an early ValueError before the loop starts; that exception
    still triggers the progress emit since we wired the try/except
    around the loop. So instead, force a failure mid-loop by
    passing data that NaNs out the loss... actually the simplest
    way is to monkey-patch torch.optim.Adam.step to raise."""
    features, outcomes = _synthetic_dataset(32)
    progress = tmp_path / "v_fail.json"

    import torch.optim
    original_step = torch.optim.Adam.step
    call_count = {"n": 0}

    def _bad_step(self, *a, **kw):
        call_count["n"] += 1
        if call_count["n"] >= 2:
            raise RuntimeError("synthetic blow-up")
        return original_step(self, *a, **kw)

    torch.optim.Adam.step = _bad_step
    try:
        with pytest.raises(RuntimeError, match="synthetic blow-up"):
            train_value_network(
                features=features, outcomes=outcomes,
                weights_out_path=tmp_path / "w.pt",
                epochs=5, batch_size=8, device="cpu",
                progress_path=progress, run_id="v_fail",
            )
    finally:
        torch.optim.Adam.step = original_step

    assert progress.is_file()
    payload = json.loads(progress.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["run_id"] == "v_fail"


def test_epoch_callback_fires_once_per_epoch_with_per_epoch_metrics(
    tmp_path: Path,
):
    """``epoch_callback`` is the hook cli/train uses to push runs-DB
    updates alongside the trainer's own JSON writes. Verify it fires
    once per epoch with all the per-epoch loss components."""
    features, outcomes = _synthetic_dataset(64)
    calls: list[dict] = []

    train_value_network(
        features=features, outcomes=outcomes,
        weights_out_path=tmp_path / "w.pt",
        epochs=3, batch_size=16, device="cpu",
        progress_path=tmp_path / "p.json",
        epoch_callback=calls.append,
    )

    assert len(calls) == 3
    # Each call must carry the per-epoch shape the cli/train wiring
    # depends on; pin the keys explicitly.
    required = {
        "epoch", "total_epochs", "elapsed_seconds",
        "train_loss", "val_loss",
        "train_value_loss", "val_value_loss",
        "train_policy_loss", "val_policy_loss",
        "status",
    }
    for i, payload in enumerate(calls):
        assert required <= set(payload.keys())
        assert payload["epoch"] == i + 1
        assert payload["total_epochs"] == 3
        assert payload["status"] == "running"
        # Losses must be numeric (NaN in policy-only fields is fine).
        assert isinstance(payload["train_loss"], float)


def test_epoch_callback_exception_does_not_kill_training(tmp_path: Path):
    """A flaky telemetry sink (e.g. the runs DB server is down) must
    not break a healthy training run. The callback may raise; the
    trainer eats the exception and keeps going."""
    features, outcomes = _synthetic_dataset(32)

    def bad_cb(_payload):
        raise RuntimeError("telemetry sink down")

    history = train_value_network(
        features=features, outcomes=outcomes,
        weights_out_path=tmp_path / "w.pt",
        epochs=2, batch_size=8, device="cpu",
        epoch_callback=bad_cb,
    )
    # Training still completes — losses recorded for both epochs.
    assert len(history.train_losses) == 2


def test_progress_path_none_writes_nothing(tmp_path: Path):
    """No progress_path → no file written. Verifies the default
    path in train_nn.py callers stays additive — old callers that
    don't pass the kwarg behave exactly as before."""
    features, outcomes = _synthetic_dataset(32)
    train_value_network(
        features=features, outcomes=outcomes,
        weights_out_path=tmp_path / "w.pt",
        epochs=2, batch_size=8, device="cpu",
    )
    # No JSON files should exist under tmp_path.
    json_files = list(tmp_path.glob("*.json"))
    assert json_files == []
