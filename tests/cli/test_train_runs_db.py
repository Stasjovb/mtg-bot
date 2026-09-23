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
    # run_id namespaces the registry version (``v1`` here — empty
    # registry) with a UTC start-timestamp so re-running ``mtg_bot
    # train`` against the same version label doesn't collide on the
    # ``runs.run_id`` UNIQUE constraint. The DB's ``label`` column
    # carries the bare version label for UI grouping.
    assert row["run_id"].startswith("train_v1_")
    assert row["run_id"].endswith("Z")
    assert row["label"] == "v1"
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
    helpers must be no-ops — weights still register and no DB file
    is created. Phase 3 cutover: the per-epoch progress JSON is no
    longer written either (the DB-backed runs registry is the only
    sink); a no-DB run is silent on disk apart from the registered
    weights.
    """
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

    # Weights registered; DB file not created.
    assert (registry_root / "v1" / "weights.pt").is_file()
    assert not (tmp_path / "runs.db").exists()
    # Phase 3: the progress JSON file is no longer written.
    assert not progress_path.exists()


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


def _write_synthetic_policy_npz(
    out_dir: Path, n: int = 64, seed: int = 0,
) -> Path:
    """Drop a synthetic .npz including policy_targets + action_masks
    so the trainer takes the dual-head AlphaZero path. Half the rows
    carry single-slot supervision; the rest are value-only."""
    from mtg_bot.training.action_encoding import ACTION_VOCAB_SIZE

    rng = np.random.default_rng(seed)
    features = rng.standard_normal((n, FEATURE_DIM)).astype(np.float32)
    outcomes = np.tanh(features[:, 0]).astype(np.float32)
    policy_targets = np.zeros((n, ACTION_VOCAB_SIZE), dtype=np.float32)
    action_masks = np.zeros((n, ACTION_VOCAB_SIZE), dtype=np.bool_)
    for i in range(n // 2):
        slot = i % ACTION_VOCAB_SIZE
        policy_targets[i, slot] = 1.0
        action_masks[i, slot] = True
    out = out_dir / "data_policy.npz"
    np.savez(
        out,
        features=features, outcomes=outcomes,
        policy_targets=policy_targets, action_masks=action_masks,
    )
    return out


def test_train_main_dual_head_separate_with_policy_hidden_sizes(
    monkeypatch, tmp_path,
):
    """Dual-head + ``--architecture=separate`` + explicit
    ``--policy-hidden-sizes`` exercises the
    ``policy_hidden_sizes is not None`` branch in the
    train_kwargs assembly."""
    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_synthetic_policy_npz(data_dir, n=64, seed=29)

    cli_train.main(_common_args(
        data_dir=data_dir,
        registry_root=tmp_path / "weights",
        progress_path=tmp_path / "p" / "t.json",
        epochs=1,
        extra=[
            "--architecture", "separate",
            "--hidden-sizes", "64,32",
            "--policy-hidden-sizes", "32,16",
        ],
    ))

    meta = json.loads(
        (tmp_path / "weights" / "v1" / "metadata.json").read_text(
            encoding="utf-8",
        )
    )
    assert meta["architecture"] == "separate"
    assert meta["training"]["policy_hidden_sizes"] == [32, 16]


def test_train_main_dual_head_policy_path(monkeypatch, tmp_path):
    """Hit the dual-head AlphaZero branch: data carries policy
    supervision, so the trainer is dispatched with the policy_targets
    / action_masks kwargs and the post-train summary prints the
    per-head loss components."""
    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_synthetic_policy_npz(data_dir, n=64, seed=11)

    registry_root = tmp_path / "weights"
    progress_path = tmp_path / "progress" / "train.json"

    cli_train.main(_common_args(
        data_dir=data_dir,
        registry_root=registry_root,
        progress_path=progress_path,
        epochs=2,
        extra=["--policy-loss-weight", "3.0"],
    ))

    meta_path = registry_root / "v1" / "metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["with_policy"] is True
    assert meta["training_history"]["final_train_loss"] is not None


@pytest.mark.parametrize("flag,bad_value,expected", [
    ("--one-legal-keep-frac", "0.0", "--one-legal-keep-frac"),
    ("--one-legal-keep-frac", "1.5", "--one-legal-keep-frac"),
    ("--early-stop-patience", "0", "--early-stop-patience"),
    ("--early-stop-patience", "-1", "--early-stop-patience"),
    ("--window-recent", "0", "--window-recent"),
    ("--window-recent", "-1", "--window-recent"),
])
def test_train_main_arg_validation_errors(
    monkeypatch, tmp_path, flag, bad_value, expected,
):
    """argparse.error / sys.exit paths for the standalone numeric
    flag validations."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_synthetic_npz(data_dir, n=64, seed=12)

    progress_path = tmp_path / "progress" / "train.json"
    registry_root = tmp_path / "weights"

    with pytest.raises(SystemExit):
        cli_train.main(_common_args(
            data_dir=data_dir,
            registry_root=registry_root,
            progress_path=progress_path,
            epochs=1,
            extra=[flag, bad_value],
        ))


def test_train_main_hidden_sizes_parse_error(monkeypatch, tmp_path):
    """``--hidden-sizes`` with a non-int token bails via sys.exit."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_synthetic_npz(data_dir, n=64, seed=13)

    with pytest.raises(SystemExit):
        cli_train.main(_common_args(
            data_dir=data_dir,
            registry_root=tmp_path / "weights",
            progress_path=tmp_path / "p" / "t.json",
            epochs=1,
            extra=["--hidden-sizes", "1024,not_an_int,512"],
        ))


def test_train_main_hidden_sizes_empty_error(monkeypatch, tmp_path):
    """``--hidden-sizes`` parsing produces an empty tuple (e.g. comma
    only) — must fail loudly."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_synthetic_npz(data_dir, n=64, seed=14)

    with pytest.raises((SystemExit, ValueError)):
        cli_train.main(_common_args(
            data_dir=data_dir,
            registry_root=tmp_path / "weights",
            progress_path=tmp_path / "p" / "t.json",
            epochs=1,
            extra=["--hidden-sizes", ""],
        ))


def test_train_main_policy_hidden_sizes_requires_separate(
    monkeypatch, tmp_path,
):
    """``--policy-hidden-sizes`` only valid with
    ``--architecture=separate``."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_synthetic_npz(data_dir, n=64, seed=15)

    with pytest.raises(SystemExit):
        cli_train.main(_common_args(
            data_dir=data_dir,
            registry_root=tmp_path / "weights",
            progress_path=tmp_path / "p" / "t.json",
            epochs=1,
            extra=["--policy-hidden-sizes", "128,64"],
        ))


def test_train_main_policy_hidden_sizes_parse_error(
    monkeypatch, tmp_path,
):
    """``--policy-hidden-sizes`` with non-int token bails via
    sys.exit when --architecture=separate."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_synthetic_npz(data_dir, n=64, seed=16)

    with pytest.raises(SystemExit):
        cli_train.main(_common_args(
            data_dir=data_dir,
            registry_root=tmp_path / "weights",
            progress_path=tmp_path / "p" / "t.json",
            epochs=1,
            extra=[
                "--architecture", "separate",
                "--policy-hidden-sizes", "abc",
            ],
        ))


def test_train_main_data_dir_missing(monkeypatch, tmp_path):
    """``--data-dir`` that isn't a directory: sys.exit."""
    bogus = tmp_path / "does_not_exist"
    with pytest.raises(SystemExit):
        cli_train.main([
            "--data-dir", str(bogus),
            "--registry-root", str(tmp_path / "w"),
            "--epochs", "1",
            "--device", "cpu",
        ])


def test_train_main_empty_data_dir(monkeypatch, tmp_path):
    """Empty data dir (no .npz files) exits."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with pytest.raises(SystemExit):
        cli_train.main([
            "--data-dir", str(data_dir),
            "--registry-root", str(tmp_path / "w"),
            "--epochs", "1",
            "--device", "cpu",
        ])


def test_train_main_window_recent_caps_loaded_files(
    monkeypatch, tmp_path,
):
    """``--window-recent`` < len(*.npz): the older files get dropped
    from the loaded subset; metadata's data_files reflects only the
    most-recent N."""
    import time as _time
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    # Three files; touch each so they have distinct mtimes.
    for i, seed in enumerate([21, 22, 23]):
        rng = np.random.default_rng(seed)
        features = rng.standard_normal((32, FEATURE_DIM)).astype(np.float32)
        outcomes = np.tanh(features[:, 0]).astype(np.float32)
        path = data_dir / f"data{i}.npz"
        np.savez(path, features=features, outcomes=outcomes)
        _time.sleep(0.01)

    cli_train.main(_common_args(
        data_dir=data_dir,
        registry_root=tmp_path / "weights",
        progress_path=tmp_path / "p" / "t.json",
        epochs=1,
        extra=["--window-recent", "2"],
    ))

    meta = json.loads(
        (tmp_path / "weights" / "v1" / "metadata.json").read_text(
            encoding="utf-8",
        )
    )
    assert len(meta["training"]["data_files"]) == 2
    assert meta["training"]["window_recent"] == 2


def test_train_main_one_legal_downsample_branch(monkeypatch, tmp_path):
    """``--one-legal-keep-frac < 1.0`` triggers the downsample branch
    and logs a kept-N / total-N line."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_synthetic_policy_npz(data_dir, n=128, seed=24)

    cli_train.main(_common_args(
        data_dir=data_dir,
        registry_root=tmp_path / "weights",
        progress_path=tmp_path / "p" / "t.json",
        epochs=1,
        extra=["--one-legal-keep-frac", "0.5"],
    ))

    meta = json.loads(
        (tmp_path / "weights" / "v1" / "metadata.json").read_text(
            encoding="utf-8",
        )
    )
    assert meta["training"]["one_legal_keep_frac"] == 0.5


def test_train_main_explicit_progress_path_override(
    monkeypatch, tmp_path,
):
    """An explicit ``--progress-path`` exercises the path-string
    construction branch and creates any missing parent dirs. Phase 3
    cutover: the JSON file itself is no longer written, but the parent
    directory is still created so the path string survives as a
    registered ``progress_json`` artifact pointer.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_synthetic_npz(data_dir, n=64, seed=25)

    nested = tmp_path / "deeply" / "nested" / "p.json"
    assert not nested.parent.exists()
    cli_train.main(_common_args(
        data_dir=data_dir,
        registry_root=tmp_path / "weights",
        progress_path=nested,
        epochs=1,
    ))
    # Parent dirs created so artifact registration sees a well-formed
    # path; file itself is not written.
    assert nested.parent.is_dir()
    assert not nested.exists()


def test_train_main_progress_path_disabled_branch(monkeypatch, tmp_path):
    """The helper at cli/train.py supports a sentinel empty-string
    ``--progress-path`` that disables JSON emission. argparse's
    ``type=Path`` coerces an empty argv token to ``Path('.')``, so
    we exercise the branch by stubbing ``parse_args`` to surface a
    ``Path('')`` namespace value — this mirrors how a direct
    caller (e.g. iterate.py threading an explicit empty Path) hits
    the same code path."""
    import argparse as _ap

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_synthetic_npz(data_dir, n=64, seed=26)

    real_parse = _ap.ArgumentParser.parse_args

    def parse_with_empty_path(self, argv=None):
        ns = real_parse(self, argv)
        # Stub progress_path to a Path-typed value whose str() is
        # the empty string — that's the sentinel the elif branch
        # checks for.
        class _EmptyPath:
            def __str__(self):
                return ""
        ns.progress_path = _EmptyPath()
        return ns

    monkeypatch.setattr(
        _ap.ArgumentParser, "parse_args", parse_with_empty_path,
    )

    cli_train.main([
        "--data-dir", str(data_dir),
        "--registry-root", str(tmp_path / "weights"),
        "--epochs", "1",
        "--batch-size", "16",
        "--device", "cpu",
        "--progress-path", "anything",
    ])
    # The training_progress/ directory should not be created since
    # progress_path landed in the disabled branch.
    assert not (tmp_path / "training_progress").exists()


def test_train_main_default_progress_path_branch(monkeypatch, tmp_path):
    """Without ``--progress-path``, the default ``training_progress/
    train_<version>_<stamp>.json`` path is computed under cwd. Phase 3
    cutover: the JSON file is no longer written, but the parent
    directory ``training_progress/`` is still created (idempotent
    mkdir) so the artifact path-string registration sees a
    well-formed path.

    Salting the default with the start timestamp lands each
    standalone invocation in its own filename so consecutive trains
    of the same version label don't clobber each other's per-epoch
    JSON — the run_id-collision sibling fix.
    """
    import re as _re

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_synthetic_npz(data_dir, n=64, seed=27)

    cwd = tmp_path / "runcwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    cli_train.main([
        "--data-dir", str(data_dir),
        "--registry-root", str(tmp_path / "weights"),
        "--epochs", "1",
        "--batch-size", "16",
        "--device", "cpu",
    ])
    progress_dir = cwd / "training_progress"
    # Parent dir created; file itself not written (Phase 3).
    assert progress_dir.is_dir()
    # No bare ``v1.json`` should appear — the default is now
    # ``train_v1_<stamp>.json``. (And no actual JSON file lands.)
    assert not (progress_dir / "v1.json").exists()
    # The matching artifact row in runs.db (no DB configured here, so
    # we just sanity-check the run_id format via the directory listing
    # if anything ever lands).
    for entry in progress_dir.iterdir():
        assert _re.match(r"train_v1_\d{8}T\d{6}Z\.json", entry.name)


def test_train_main_weights_stat_oserror_swallowed(
    monkeypatch, tmp_path,
):
    """If ``weights_path.stat()`` fails (e.g. transient filesystem
    error between registration and our stat call), the artifact
    push still lands with bytes=None rather than crashing the
    run. We force the failure by stubbing
    ``Registry.weights_path`` to return a non-existent path AFTER
    registration so the stat() call fails."""
    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", str(db_path))
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    monkeypatch.setattr(lifecycle, "git_commit_short", lambda: "abc")

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_synthetic_npz(data_dir, n=64, seed=28)

    from mtg_bot.training.registry import Registry as _Reg

    real_weights_path = _Reg.weights_path
    call_count = {"n": 0}

    def patched_weights_path(self, version):
        call_count["n"] += 1
        path = real_weights_path(self, version)
        # The 1st call from train.py's artifact-register block:
        # redirect to a non-existent path so the inline stat()
        # raises FileNotFoundError -> the OSError-fallback branch
        # writes bytes=None to the artifact row.
        if call_count["n"] == 1:
            return tmp_path / "nope" / "missing.pt"
        return path

    monkeypatch.setattr(_Reg, "weights_path", patched_weights_path)

    cli_train.main(_common_args(
        data_dir=data_dir,
        registry_root=tmp_path / "weights",
        progress_path=tmp_path / "p" / "t.json",
        epochs=1,
    ))

    conn = runs_db.connect(db_path)
    try:
        arts = list(conn.execute(
            "SELECT artifact_type, bytes FROM run_artifacts "
            "WHERE artifact_type='weights'"
        ))
    finally:
        conn.close()
    assert len(arts) == 1
    assert arts[0]["bytes"] is None


def test_train_main_legacy_git_commit_helper_returns_string_or_none(
    monkeypatch,
):
    """The legacy ``_git_commit`` helper (kept for the metadata's
    ``git_commit`` field — the lifecycle's own git probe is
    separate) returns either a short SHA or None; the helper must
    not raise even with git missing."""
    # Real call — exercises the happy path. In a CI without git it
    # would hit the except path.
    result = cli_train._git_commit()
    assert result is None or isinstance(result, str)


def test_train_main_legacy_git_commit_helper_handles_missing_git(
    monkeypatch,
):
    """When ``git`` isn't on PATH, ``_git_commit`` returns None
    instead of raising — pins the except-branch behavior."""
    def fake_run(*a, **kw):
        raise FileNotFoundError("no git binary")
    monkeypatch.setattr(cli_train.subprocess, "run", fake_run)
    assert cli_train._git_commit() is None


def test_train_main_legacy_git_commit_helper_nonzero_returncode(
    monkeypatch,
):
    """If ``git`` exits non-zero (e.g. not a git checkout), the
    helper returns None."""
    class FakeResult:
        returncode = 128
        stdout = ""

    monkeypatch.setattr(
        cli_train.subprocess, "run",
        lambda *a, **kw: FakeResult(),
    )
    assert cli_train._git_commit() is None


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
    # Lineage-prefixed cycle ids (``iterate --run-label-prefix s2_``)
    # must still resolve — a leading \b would not match there because
    # ``_`` is a word character.
    assert (
        cli_train._parent_run_id_from_notes("s2_iter_001_cycle: train")
        == "s2_iter_001_cycle"
    )
    assert (
        cli_train._parent_run_id_from_notes("foo s2_iter_042_cycle bar")
        == "s2_iter_042_cycle"
    )
    # Still anchored at a token start — a run-together word doesn't
    # spuriously match.
    assert cli_train._parent_run_id_from_notes("xiter_001_cycle") is None
