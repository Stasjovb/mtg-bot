"""End-to-end test that ``mtg_bot train``'s ``main()`` body
correctly wires the runs-DB lifecycle alongside the existing
JSON progress writes.

The trainer's epoch loop already has its own unit coverage in
``tests/training/test_trainer_progress.py``; this test pins the
cli-layer wiring:

- ``start_run`` fires with ``kind="training"`` and the peeked
  version label as ``run_id``.
- Once per epoch, ``push_progress`` lands a row with
  ``n_games_done=current_epoch`` + extra_json carrying the
  per-epoch losses, AND ``push_event`` appends an
  ``epoch_completed`` event with the same loss components.
- After training, a final ``push_progress`` carries the full
  ``training_history`` blob in ``extra_json["training_history"]``.
- The weights file is registered as an artifact.
- ``finish_run`` lands with ``status="completed"``.
- Failure paths still mark the run as ``failed``/``killed``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from mtg_bot.cli import train as cli_train
from mtg_bot.cli.runs import db as runs_db, lifecycle
from mtg_bot.features import FEATURE_DIM


def _write_synthetic_npz(out_dir: Path, n: int = 64, seed: int = 0) -> Path:
    """Drop a small synthetic .npz the way ``load_all_datasets``
    expects to find it: features + outcomes only (value-only mode,
    so the trainer takes the simpler value-MSE path)."""
    rng = np.random.default_rng(seed)
    features = rng.standard_normal((n, FEATURE_DIM)).astype(np.float32)
    outcomes = np.tanh(features[:, 0]).astype(np.float32)
    out = out_dir / "data.npz"
    np.savez(out, features=features, outcomes=outcomes)
    return out


def _common_args(
    *, data_dir: Path, registry_root: Path,
    progress_path: Path, epochs: int = 3,
    extra: list[str] | None = None,
) -> list[str]:
    args = [
        "--data-dir", str(data_dir),
        "--registry-root", str(registry_root),
        "--epochs", str(epochs),
        "--batch-size", "16",
        "--val-split", "0.25",
        "--device", "cpu",
        "--progress-path", str(progress_path),
    ]
    if extra:
        args.extend(extra)
    return args


def test_train_main_round_trips_start_progress_finish(
    monkeypatch, tmp_path,
):
    """Happy path. After a 3-epoch run, the DB has:
    - one ``runs`` row with kind=training / status=completed
    - one ``run_progress`` row (upsert keyed on (run_id, None))
      with extra_json["training_history"] populated
    - 3 ``run_events`` of type ``epoch_completed``
    - two ``run_artifacts``: the progress JSON + the weights file
    """
    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", str(db_path))
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    monkeypatch.setattr(lifecycle, "git_commit_short", lambda: "abc1234")

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_synthetic_npz(data_dir, n=64, seed=0)

    registry_root = tmp_path / "weights"
    progress_path = tmp_path / "progress" / "train.json"

    cli_train.main(_common_args(
        data_dir=data_dir,
        registry_root=registry_root,
        progress_path=progress_path,
        epochs=3,
        extra=["--notes", "unit test"],
    ))

    # Inspect the DB.
    conn = runs_db.connect(db_path)
    try:
        run_rows = list(conn.execute("SELECT * FROM runs"))
        progress_rows = list(conn.execute(
            "SELECT * FROM run_progress ORDER BY updated_at"
        ))
        event_rows = list(conn.execute(
            "SELECT * FROM run_events ORDER BY id"
        ))
        artifact_rows = list(conn.execute(
            "SELECT * FROM run_artifacts"
        ))
    finally:
        conn.close()

    # One run row, kind=training, completed, with git_commit pinned.
    assert len(run_rows) == 1
    row = run_rows[0]
    assert row["kind"] == "training"
    assert row["status"] == "completed"
    assert row["git_commit"] == "abc1234"
    # run_id should be the peeked version (v1 — empty registry).
    assert row["run_id"] == "v1"
    cfg = json.loads(row["config_json"])
    assert cfg["kind"] == "training"
    assert cfg["epochs"] == 3
    assert cfg["device"] == "cpu"

    # Aggregate progress row carries the final training_history blob.
    # Upsert means a single row — the per-epoch pushes overwrite, and
    # the final post-train push lands the training_history blob.
    assert len(progress_rows) == 1
    final = progress_rows[0]
    assert final["n_games_done"] == 3
    assert final["n_games_total"] == 3
    extra = json.loads(final["extra_json"])
    assert "training_history" in extra
    history = extra["training_history"]
    for key in (
        "train_losses", "val_losses",
        "train_value_losses", "val_value_losses",
        "train_policy_losses", "val_policy_losses",
        "best_val_loss", "best_val_epoch",
        "final_train_loss", "final_val_loss",
        "epochs_trained",
    ):
        assert key in history, f"missing training_history key: {key}"
    assert len(history["train_losses"]) == 3
    assert history["epochs_trained"] == 3
    assert extra["registered_version"] == "v1"

    # One epoch_completed event per epoch, carrying the loss
    # components from the trainer history.
    epoch_events = [e for e in event_rows if e["event_type"] == "epoch_completed"]
    assert len(epoch_events) == 3
    for i, ev in enumerate(epoch_events):
        payload = json.loads(ev["payload_json"])
        assert payload["epoch"] == i + 1
        for key in (
            "train_loss", "val_loss",
            "train_value_loss", "val_value_loss",
            "train_policy_loss", "val_policy_loss",
        ):
            assert key in payload

    # Two artifacts: the progress JSON (registered by lifecycle) and
    # the weights file (registered after training).
    arts_by_type = {a["artifact_type"]: a for a in artifact_rows}
    assert "progress_json" in arts_by_type
    assert "weights" in arts_by_type
    assert arts_by_type["weights"]["path"].endswith("weights.pt")
    assert arts_by_type["weights"]["bytes"] is not None
    assert arts_by_type["weights"]["bytes"] > 0


def test_train_main_lifecycle_no_op_when_db_unset(
    monkeypatch, tmp_path,
):
    """Without ``MTG_BOT_RUN_DB_PATH`` (and no URL), the lifecycle
    helpers must be no-ops — the existing JSON + registry write
    paths still complete and no DB file is created."""
    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_synthetic_npz(data_dir, n=64, seed=1)

    registry_root = tmp_path / "weights"
    progress_path = tmp_path / "progress" / "train.json"

    cli_train.main(_common_args(
        data_dir=data_dir,
        registry_root=registry_root,
        progress_path=progress_path,
        epochs=2,
    ))

    # Progress JSON written, weights registered — but no DB file.
    assert progress_path.is_file()
    assert (registry_root / "v1" / "weights.pt").is_file()
    assert not (tmp_path / "runs.db").exists()


def test_train_main_marks_failed_on_exception(monkeypatch, tmp_path):
    """If ``train_value_network`` raises mid-training, the lifecycle
    CM must mark the run ``status=failed`` and re-raise."""
    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", str(db_path))
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    monkeypatch.setattr(lifecycle, "git_commit_short", lambda: "abc")

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_synthetic_npz(data_dir, n=64, seed=2)

    registry_root = tmp_path / "weights"
    progress_path = tmp_path / "progress" / "train.json"

    def boom(*a, **kw):
        raise RuntimeError("synthetic trainer crash")

    with patch.object(cli_train, "train_value_network", boom):
        with pytest.raises(RuntimeError, match="synthetic trainer crash"):
            cli_train.main(_common_args(
                data_dir=data_dir,
                registry_root=registry_root,
                progress_path=progress_path,
                epochs=2,
            ))

    conn = runs_db.connect(db_path)
    try:
        rows = list(conn.execute("SELECT status, notes FROM runs"))
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0]["status"] == "failed"
    assert "RuntimeError" in (rows[0]["notes"] or "")


def test_train_main_marks_killed_on_sigint(monkeypatch, tmp_path):
    """``KeyboardInterrupt`` mid-train lands as ``status=killed``."""
    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", str(db_path))
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    monkeypatch.setattr(lifecycle, "git_commit_short", lambda: "abc")

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_synthetic_npz(data_dir, n=64, seed=3)

    registry_root = tmp_path / "weights"
    progress_path = tmp_path / "progress" / "train.json"

    def interrupted(*a, **kw):
        raise KeyboardInterrupt()

    with patch.object(cli_train, "train_value_network", interrupted):
        with pytest.raises(KeyboardInterrupt):
            cli_train.main(_common_args(
                data_dir=data_dir,
                registry_root=registry_root,
                progress_path=progress_path,
                epochs=2,
            ))

    conn = runs_db.connect(db_path)
    try:
        rows = list(conn.execute("SELECT status FROM runs"))
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0]["status"] == "killed"


def test_train_main_parses_parent_run_id_from_notes(
    monkeypatch, tmp_path,
):
    """When ``--notes`` carries an ``iter_NNN_cycle`` token (as
    iterate would inject in Phase 2), the start_run picks it up as
    parent_run_id so the iterate row in the UI can fan out into
    its training children."""
    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", str(db_path))
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    monkeypatch.setattr(lifecycle, "git_commit_short", lambda: "abc")

    # Seed the parent cycle row first so the foreign-key constraint
    # is satisfied. Real production runs land the cycle row from
    # iterate.py before spawning the train subprocess.
    conn = runs_db.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO runs (run_id, kind, status, started_at, "
            "git_commit, config_json) VALUES (?, ?, ?, ?, ?, ?)",
            ("iter_007_cycle", "iterate", "running",
             "2026-05-11T00:00:00+00:00", "abc", "{}"),
        )
        conn.commit()
    finally:
        conn.close()

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_synthetic_npz(data_dir, n=64, seed=4)

    registry_root = tmp_path / "weights"
    progress_path = tmp_path / "progress" / "train.json"

    cli_train.main(_common_args(
        data_dir=data_dir,
        registry_root=registry_root,
        progress_path=progress_path,
        epochs=1,
        extra=["--notes", "iter_007_cycle: training stage"],
    ))

    conn = runs_db.connect(db_path)
    try:
        rows = list(conn.execute(
            "SELECT run_id, parent_run_id FROM runs WHERE kind='training'"
        ))
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0]["parent_run_id"] == "iter_007_cycle"


def test_train_main_with_epochs_zero_registers_cleanly(
    monkeypatch, tmp_path,
):
    """``--epochs 0`` is a smoke-test mode: just register a fresh
    version with no actual training. Previously this crashed with
    ``IndexError: list index out of range`` because the post-train
    summary blindly indexed ``history.train_losses[-1]``. Now it
    must complete cleanly with epochs_trained=0 in metadata.
    """
    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_synthetic_npz(data_dir, n=64, seed=9)

    registry_root = tmp_path / "weights"
    progress_path = tmp_path / "progress" / "train.json"

    # The interesting bit: epochs=0 must complete without an
    # IndexError. If the bug regresses, this raises.
    cli_train.main(_common_args(
        data_dir=data_dir,
        registry_root=registry_root,
        progress_path=progress_path,
        epochs=0,
    ))

    # Weights file + metadata still landed in the registry.
    weights = registry_root / "v1" / "weights.pt"
    metadata = registry_root / "v1" / "metadata.json"
    assert weights.is_file()
    assert metadata.is_file()
    meta = json.loads(metadata.read_text(encoding="utf-8"))
    assert meta["training"]["epochs_trained"] == 0
    # final_*_loss fields must be present but None (not blindly
    # indexed into empty lists).
    assert meta["training_history"]["final_train_loss"] is None
    assert meta["training_history"]["final_val_loss"] is None
    assert meta["training_history"]["train_losses"] == []


def test_train_main_with_epochs_zero_lands_db_rows(
    monkeypatch, tmp_path,
):
    """``--epochs 0`` with DB configured: start_run + finish_run
    both land (status=completed). No per-epoch events fire because
    the trainer's epoch loop never executes. The final aggregate
    progress row carries epochs_trained=0."""
    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", str(db_path))
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    monkeypatch.setattr(lifecycle, "git_commit_short", lambda: "abc")

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_synthetic_npz(data_dir, n=64, seed=10)

    registry_root = tmp_path / "weights"
    progress_path = tmp_path / "progress" / "train.json"

    cli_train.main(_common_args(
        data_dir=data_dir,
        registry_root=registry_root,
        progress_path=progress_path,
        epochs=0,
    ))

    conn = runs_db.connect(db_path)
    try:
        run_rows = list(conn.execute("SELECT * FROM runs"))
        event_rows = list(conn.execute(
            "SELECT event_type FROM run_events"
        ))
        progress_rows = list(conn.execute("SELECT * FROM run_progress"))
    finally:
        conn.close()

    assert len(run_rows) == 1
    assert run_rows[0]["status"] == "completed"
    assert run_rows[0]["kind"] == "training"
    # No epoch_completed events with epochs=0.
    assert [r["event_type"] for r in event_rows].count(
        "epoch_completed"
    ) == 0
    # The post-train aggregate progress row landed with
    # training_history showing epochs_trained=0.
    assert len(progress_rows) == 1
    extra = json.loads(progress_rows[0]["extra_json"])
    assert extra["training_history"]["epochs_trained"] == 0
    assert extra["training_history"]["train_losses"] == []


def test_parent_run_id_from_notes_helper():
    """Direct unit test for the helper — covers the regex paths."""
    assert cli_train._parent_run_id_from_notes("") is None
    assert cli_train._parent_run_id_from_notes("no iter token here") is None
    assert (
        cli_train._parent_run_id_from_notes("iter_001_cycle: train stage")
        == "iter_001_cycle"
    )
    assert (
        cli_train._parent_run_id_from_notes("foo iter_042_cycle bar")
        == "iter_042_cycle"
    )
    # No match if just the prefix without _cycle.
    assert cli_train._parent_run_id_from_notes("iter_001") is None
