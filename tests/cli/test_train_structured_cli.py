"""End-to-end tests for ``mtg_bot train --architecture structured``.

Verifies the CLI dispatch:

- Reads npz files containing the four structured-token arrays.
- Drives the new ``train_structured_model`` path.
- Registers a new version with ``metadata.architecture='structured'``.
- Errors with a clear message when the npz files don't carry
  structured tokens.
- Plumbs progress JSON, run-lifecycle hooks, and notes flag.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import torch

from mtg_bot.cli import train as cli_train
from mtg_bot.features import FEATURE_DIM
from mtg_bot.training.action_encoding import ACTION_VOCAB_SIZE
from mtg_bot.training.data_gen import save_dataset
from mtg_bot.training.structured_model import (
    N_EMB_FIELDS, N_SCALAR_FIELDS, N_SCALAR_FIELDS_V2,
)


def _write_structured_npz(
    out_path: Path,
    n_rows: int,
    *,
    seq_len: int = 4,
    with_policy: bool = True,
    seed: int = 0,
    scalar_width: int = N_SCALAR_FIELDS_V2,
) -> Path:
    rng = np.random.default_rng(seed)
    features = rng.standard_normal((n_rows, FEATURE_DIM)).astype(np.float32)
    outcomes = rng.choice(
        np.array([-1.0, 0.0, 1.0], dtype=np.float32), size=n_rows,
    )
    token_type = rng.integers(0, 5, size=(n_rows, seq_len)).astype(np.int64)
    token_emb_ids = np.zeros(
        (n_rows, seq_len, N_EMB_FIELDS), dtype=np.int64,
    )
    token_scalars = rng.standard_normal(
        (n_rows, seq_len, scalar_width),
    ).astype(np.float32)
    attention_mask = np.ones((n_rows, seq_len), dtype=np.bool_)
    if with_policy:
        policy_targets = np.zeros(
            (n_rows, ACTION_VOCAB_SIZE), dtype=np.float32,
        )
        action_masks = np.zeros(
            (n_rows, ACTION_VOCAB_SIZE), dtype=np.bool_,
        )
        for i in range(n_rows):
            if i % 2 == 0:
                policy_targets[i, 0] = 0.6
                policy_targets[i, 1] = 0.4
                action_masks[i, 0] = True
                action_masks[i, 1] = True
    else:
        policy_targets = None
        action_masks = None
    save_dataset(
        features, outcomes, out_path,
        policy_targets=policy_targets,
        action_masks=action_masks,
        structured_token_type=token_type,
        structured_token_emb_ids=token_emb_ids,
        structured_token_scalars=token_scalars,
        structured_attention_mask=attention_mask,
    )
    return out_path


def test_train_structured_cli_smoke(tmp_path: Path, monkeypatch) -> None:
    """Happy path. Train two epochs on a 16-row synthetic dataset and
    confirm the registry record carries ``architecture='structured'``
    plus a populated training_history."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_structured_npz(
        data_dir / "shard_001.npz", n_rows=16, seq_len=4, seed=1,
    )

    registry_root = tmp_path / "weights"
    progress_path = tmp_path / "progress" / "train.json"

    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)

    cli_train.main([
        "--data-dir", str(data_dir),
        "--registry-root", str(registry_root),
        "--epochs", "2",
        "--batch-size", "4",
        "--val-split", "0.25",
        "--device", "cpu",
        "--progress-path", str(progress_path),
        "--architecture", "structured",
        "--notes", "Slice C smoke",
    ])

    # The registry should now hold v1 with the structured architecture
    # and a complete training-history block.
    v1_dir = registry_root / "v1"
    assert v1_dir.is_dir(), list(registry_root.iterdir())
    meta = json.loads((v1_dir / "metadata.json").read_text())
    assert meta["architecture"] == "structured"
    assert meta["version"] == "v1"
    assert meta["training_history"]["train_losses"]
    assert len(meta["training_history"]["train_losses"]) == 2
    assert meta["training"]["epochs"] == 2
    assert meta["training"]["data_files"] == ["shard_001.npz"]
    # Progress JSON landed and is completed.
    assert progress_path.is_file()
    blob = json.loads(progress_path.read_text())
    assert blob["status"] == "completed"
    assert blob["architecture"] == "structured"
    # Weight file exists and load_state_dict succeeds.
    weights_path = v1_dir / "weights.pt"
    assert weights_path.is_file()
    state = torch.load(weights_path, map_location="cpu", weights_only=True)
    assert isinstance(state, dict)
    assert any("printing_embed" in k for k in state)


def test_train_structured_cli_writes_both_metadata_layouts(
    tmp_path: Path, monkeypatch,
) -> None:
    """iter_019 BUG #2 trainer-side regression: the structured trainer's
    metadata writer emits BOTH the nested ``structured_config`` dict
    AND the flat ``structured_*`` keys for the six tunable dims.
    Belt-and-braces companion to the loader-side compat shim — a
    metadata file from this trainer round-trips through any historical
    loader version (including pre-iter_019 loaders that only read the
    flat keys)."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_structured_npz(
        data_dir / "shard_001.npz", n_rows=16, seq_len=4, seed=1,
    )

    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)

    registry_root = tmp_path / "weights"
    cli_train.main([
        "--data-dir", str(data_dir),
        "--registry-root", str(registry_root),
        "--epochs", "1",
        "--batch-size", "4",
        "--val-split", "0.25",
        "--device", "cpu",
        "--architecture", "structured",
        # Non-default dims so the test would fail loud if the writer
        # silently used StructuredModelConfig defaults instead of the
        # CLI-supplied values.
        "--emb-dim", "16",
        "--n-heads", "2",
        "--n-layers", "2",
        "--hidden-dim", "32",
        "--action-history-n", "4",
    ])

    meta = json.loads((registry_root / "v1" / "metadata.json").read_text())
    training = meta["training"]
    # Nested layout (preserved — the loader's primary path before the
    # compat shim and still acceptable post-fix).
    assert training["structured_config"]["emb_dim"] == 16
    assert training["structured_config"]["n_heads"] == 2
    assert training["structured_config"]["n_layers"] == 2
    assert training["structured_config"]["hidden_dim"] == 32
    assert training["structured_config"]["action_history_n"] == 4
    # Flat layout (new — added so pre-iter_019 loaders still work).
    assert training["structured_emb_dim"] == 16
    assert training["structured_n_heads"] == 2
    assert training["structured_n_layers"] == 2
    assert training["structured_hidden_dim"] == 32
    assert training["structured_action_history_n"] == 4
    # n_printings isn't a CLI knob — verify both layouts carry the same
    # value (whatever StructuredModelConfig defaulted to).
    assert (
        training["structured_n_printings"]
        == training["structured_config"]["n_printings"]
    )


def test_train_structured_cli_passes_compile_flag(
    tmp_path: Path, monkeypatch,
) -> None:
    """``mtg_bot train --architecture structured`` MUST forward the
    ``--compile`` flag value into ``train_structured_model``.

    Regression test for the iter_002 train crash: ``_main_structured``
    constructed the train kwargs without ``compile_model=``, so the
    trainer's internal ``compile_model: Optional[bool] = None`` default
    kicked in and tried to torch.compile on CUDA — which crashes on
    Windows-cu128 (Triton not packaged) at the first forward pass,
    AFTER the try/except around ``torch.compile()`` itself.
    """
    captured = {}
    real_train = cli_train.train_structured_model

    def spy(*args, **kwargs):
        captured["compile_model"] = kwargs.get(
            "compile_model", "<not-passed>",
        )
        # Force compile_model=False so the test doesn't try to compile
        # for real; we only care that the flag was forwarded.
        kwargs["compile_model"] = False
        return real_train(*args, **kwargs)

    monkeypatch.setattr(cli_train, "train_structured_model", spy)
    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_structured_npz(
        data_dir / "shard_001.npz", n_rows=16, seq_len=4, seed=1,
    )

    # Without --compile, compile_model defaults to False (action="store_true").
    cli_train.main([
        "--data-dir", str(data_dir),
        "--registry-root", str(tmp_path / "weights"),
        "--epochs", "1",
        "--batch-size", "4",
        "--val-split", "0.25",
        "--device", "cpu",
        "--architecture", "structured",
    ])
    assert captured["compile_model"] is False, (
        f"expected compile_model=False (--compile not passed), "
        f"got {captured['compile_model']!r}"
    )


def test_train_structured_cli_missing_structured_arrays(
    tmp_path: Path, monkeypatch,
) -> None:
    """An npz with features+outcomes only fails loudly when
    --architecture structured is requested."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    # Save a legacy npz with no structured arrays.
    rng = np.random.default_rng(0)
    features = rng.standard_normal((8, FEATURE_DIM)).astype(np.float32)
    outcomes = np.zeros((8,), dtype=np.float32)
    save_dataset(features, outcomes, data_dir / "legacy.npz")

    registry_root = tmp_path / "weights"
    progress_path = tmp_path / "progress" / "train.json"

    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)

    with pytest.raises(SystemExit) as exc:
        cli_train.main([
            "--data-dir", str(data_dir),
            "--registry-root", str(registry_root),
            "--epochs", "1",
            "--batch-size", "4",
            "--val-split", "0.25",
            "--device", "cpu",
            "--progress-path", str(progress_path),
            "--architecture", "structured",
        ])
    msg = str(exc.value)
    assert "structured" in msg
    assert "structured_tokens=True" in msg


def test_train_structured_cli_missing_data_dir_exits(
    tmp_path: Path, monkeypatch,
) -> None:
    missing = tmp_path / "nope"
    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    with pytest.raises(SystemExit) as exc:
        cli_train.main([
            "--data-dir", str(missing),
            "--registry-root", str(tmp_path / "weights"),
            "--epochs", "1",
            "--device", "cpu",
            "--architecture", "structured",
        ])
    assert "is not a directory" in str(exc.value)


def test_train_structured_cli_empty_data_dir(
    tmp_path: Path, monkeypatch,
) -> None:
    """Empty data dir surfaces a clear FileNotFoundError-class
    message via the CLI."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    with pytest.raises(SystemExit) as exc:
        cli_train.main([
            "--data-dir", str(data_dir),
            "--registry-root", str(tmp_path / "weights"),
            "--epochs", "1",
            "--device", "cpu",
            "--architecture", "structured",
        ])
    assert "No .npz files" in str(exc.value)


def test_train_structured_cli_validates_early_stop_patience(
    tmp_path: Path, monkeypatch,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_structured_npz(data_dir / "a.npz", n_rows=8, seed=0)
    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    with pytest.raises(SystemExit):
        cli_train.main([
            "--data-dir", str(data_dir),
            "--registry-root", str(tmp_path / "weights"),
            "--epochs", "1",
            "--device", "cpu",
            "--architecture", "structured",
            "--early-stop-patience", "0",
        ])


def test_train_structured_cli_default_early_stop_patience_is_3(
    tmp_path: Path, monkeypatch,
) -> None:
    # Regression: when --early-stop-patience is omitted, the CLI must
    # forward patience=3 into the trainer (D3 ablation finding — v5 was
    # undertrained at patience=None / 5 epochs; docs/SCALING_DIAGNOSTICS.md).
    captured = {}
    real_train = cli_train.train_structured_model

    def spy(*args, **kwargs):
        captured["early_stop_patience"] = kwargs.get(
            "early_stop_patience", "<not-passed>",
        )
        return real_train(*args, **kwargs)

    monkeypatch.setattr(cli_train, "train_structured_model", spy)
    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_structured_npz(
        data_dir / "shard_001.npz", n_rows=16, seq_len=4, seed=1,
    )

    cli_train.main([
        "--data-dir", str(data_dir),
        "--registry-root", str(tmp_path / "weights"),
        "--epochs", "1",
        "--batch-size", "4",
        "--val-split", "0.25",
        "--device", "cpu",
        "--architecture", "structured",
    ])
    assert captured["early_stop_patience"] == 3, (
        f"expected default --early-stop-patience=3 "
        f"(D3 ablation finding), got {captured['early_stop_patience']!r}"
    )


def test_train_structured_cli_validates_window_recent(
    tmp_path: Path, monkeypatch,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_structured_npz(data_dir / "a.npz", n_rows=4, seed=0)
    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    with pytest.raises(SystemExit):
        cli_train.main([
            "--data-dir", str(data_dir),
            "--registry-root", str(tmp_path / "weights"),
            "--epochs", "1",
            "--device", "cpu",
            "--architecture", "structured",
            "--window-recent", "-1",
        ])


def test_train_structured_cli_window_recent_files_picks_latest(
    tmp_path: Path, monkeypatch,
) -> None:
    """--window-recent-files filters to the N most recent npz files.

    (This is the pre-2026-09-24 ``--window-recent`` behaviour; that
    flag now windows by ITERATION — see
    ``tests/cli/test_train_window_recent.py``. These fixture files
    carry no ``iter_NNN`` label, so the iteration window would keep
    them all.)
    """
    import os
    import time
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    old = data_dir / "old.npz"
    _write_structured_npz(old, n_rows=4, seed=1)
    old_t = time.time() - 10_000
    os.utime(old, (old_t, old_t))
    new = data_dir / "new.npz"
    _write_structured_npz(new, n_rows=4, seed=2)

    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    registry_root = tmp_path / "weights"
    progress_path = tmp_path / "p" / "train.json"
    cli_train.main([
        "--data-dir", str(data_dir),
        "--registry-root", str(registry_root),
        "--epochs", "1",
        "--batch-size", "4",
        "--val-split", "0.25",
        "--device", "cpu",
        "--progress-path", str(progress_path),
        "--architecture", "structured",
        "--window-recent-files", "1",
    ])
    meta = json.loads(
        (registry_root / "v1" / "metadata.json").read_text()
    )
    # Only ``new.npz`` should have been loaded.
    assert meta["training"]["data_files"] == ["new.npz"]


def test_train_structured_cli_default_progress_path(
    tmp_path: Path, monkeypatch,
) -> None:
    """When no --progress-path is given, the default lands under
    training_progress/train_<version>_<stamp>.json (under the cwd we
    ``chdir`` into). The timestamp salt keeps consecutive standalone
    trains of the same version label from sharing a filename — see
    the sibling ``test_train_main_default_progress_path_branch``
    docstring for context.
    """
    import re as _re

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_structured_npz(data_dir / "a.npz", n_rows=8, seed=0)
    registry_root = tmp_path / "weights"
    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    cli_train.main([
        "--data-dir", str(data_dir),
        "--registry-root", str(registry_root),
        "--epochs", "1",
        "--batch-size", "4",
        "--val-split", "0.25",
        "--device", "cpu",
        "--architecture", "structured",
    ])
    # No bare ``v1.json`` — the default is salt-stamped.
    assert not (tmp_path / "training_progress" / "v1.json").exists()
    matches = [
        p for p in (tmp_path / "training_progress").iterdir()
        if _re.match(r"train_v1_\d{8}T\d{6}Z\.json", p.name)
    ]
    assert len(matches) == 1, list(
        (tmp_path / "training_progress").iterdir()
    )
    blob = json.loads(matches[0].read_text())
    assert blob["architecture"] == "structured"


def test_train_structured_cli_progress_dir_moves_default_progress_path(
    tmp_path: Path, monkeypatch,
) -> None:
    """``--progress-dir`` (forwarded by iterate, which the unified
    launcher forwards from the launch TOML) relocates the DEFAULT
    progress JSON. Before this was threaded, an s2-lineage train
    printed ``# Progress JSON: training_progress\\
    s2_iter_005_train_v6.json`` while the rest of the cycle's
    artifacts lived under ``training_progress_s2/``.
    """
    import re as _re

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_structured_npz(data_dir / "a.npz", n_rows=8, seed=0)
    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    cli_train.main([
        "--data-dir", str(data_dir),
        "--registry-root", str(tmp_path / "weights"),
        "--epochs", "1",
        "--batch-size", "4",
        "--val-split", "0.25",
        "--device", "cpu",
        "--architecture", "structured",
        "--progress-dir", "training_progress_s2",
    ])
    assert not (tmp_path / "training_progress").exists()
    matches = [
        p for p in (tmp_path / "training_progress_s2").iterdir()
        if _re.match(r"train_v1_\d{8}T\d{6}Z\.json", p.name)
    ]
    assert len(matches) == 1, list(
        (tmp_path / "training_progress_s2").iterdir()
    )


def test_train_structured_cli_threads_loader_timeout(
    tmp_path: Path, monkeypatch,
) -> None:
    """``--loader-timeout-sec`` reaches ``train_structured_model``.

    The DataLoaders run with ``num_workers>0`` +
    ``persistent_workers`` and no timeout, so a wedged worker hung
    training forever (2026-09-24).
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_structured_npz(data_dir / "a.npz", n_rows=8, seed=0)
    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)

    captured: dict = {}
    real = cli_train.train_structured_model

    def _capture(*args, **kwargs):
        captured.update(kwargs)
        kwargs.pop("loader_timeout_sec", None)
        return real(*args, **kwargs)

    monkeypatch.setattr(cli_train, "train_structured_model", _capture)
    cli_train.main([
        "--data-dir", str(data_dir),
        "--registry-root", str(tmp_path / "weights"),
        "--epochs", "1",
        "--batch-size", "4",
        "--val-split", "0.25",
        "--device", "cpu",
        "--architecture", "structured",
        "--progress-path", str(tmp_path / "p" / "t.json"),
        "--loader-timeout-sec", "123",
    ])
    assert captured["loader_timeout_sec"] == 123.0


def test_train_structured_cli_loader_timeout_default_is_600(
    tmp_path: Path, monkeypatch,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_structured_npz(data_dir / "a.npz", n_rows=8, seed=0)
    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)

    captured: dict = {}
    real = cli_train.train_structured_model

    def _capture(*args, **kwargs):
        captured.update(kwargs)
        kwargs.pop("loader_timeout_sec", None)
        return real(*args, **kwargs)

    monkeypatch.setattr(cli_train, "train_structured_model", _capture)
    cli_train.main([
        "--data-dir", str(data_dir),
        "--registry-root", str(tmp_path / "weights"),
        "--epochs", "1",
        "--batch-size", "4",
        "--val-split", "0.25",
        "--device", "cpu",
        "--architecture", "structured",
        "--progress-path", str(tmp_path / "p" / "t.json"),
    ])
    assert captured["loader_timeout_sec"] == 600.0


def test_train_structured_cli_rejects_negative_loader_timeout(
    tmp_path: Path, monkeypatch,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_structured_npz(data_dir / "a.npz", n_rows=4, seed=0)
    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    with pytest.raises(SystemExit):
        cli_train.main([
            "--data-dir", str(data_dir),
            "--registry-root", str(tmp_path / "weights"),
            "--epochs", "1",
            "--device", "cpu",
            "--architecture", "structured",
            "--loader-timeout-sec", "-1",
        ])


def test_train_structured_cli_runs_db_records_run(
    tmp_path: Path, monkeypatch,
) -> None:
    """When ``MTG_BOT_RUN_DB_PATH`` is set, the run lifecycle writes
    a ``runs`` row + per-epoch progress + final artifact."""
    from mtg_bot.cli.runs import db as runs_db, lifecycle

    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", str(db_path))
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    monkeypatch.setattr(lifecycle, "git_commit_short", lambda: "deadbee")

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _write_structured_npz(data_dir / "a.npz", n_rows=8, seed=0)
    registry_root = tmp_path / "weights"
    progress_path = tmp_path / "p" / "train.json"
    cli_train.main([
        "--data-dir", str(data_dir),
        "--registry-root", str(registry_root),
        "--epochs", "2",
        "--batch-size", "4",
        "--val-split", "0.25",
        "--device", "cpu",
        "--progress-path", str(progress_path),
        "--architecture", "structured",
        "--notes", "db smoke",
    ])
    conn = runs_db.connect(db_path)
    try:
        rows = list(conn.execute("SELECT * FROM runs"))
        events = list(conn.execute("SELECT * FROM run_events"))
        artifacts = list(conn.execute("SELECT * FROM run_artifacts"))
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0]["kind"] == "training"
    assert rows[0]["status"] == "completed"
    # Two epochs ⇒ two epoch_completed events.
    epoch_events = [e for e in events if e["event_type"] == "epoch_completed"]
    assert len(epoch_events) == 2
    # Weights artifact registered.
    weights_artifacts = [
        a for a in artifacts if a["artifact_type"] == "weights"
    ]
    assert len(weights_artifacts) == 1


# ---------------------------------------------------------------------
# --scalar-schema-version
# ---------------------------------------------------------------------


def _run_train_cli(tmp_path: Path, monkeypatch, argv_extra: list[str]):
    """Run ``mtg_bot train --architecture structured`` on the npz files
    in ``tmp_path/data`` into ``tmp_path/registry``; returns the
    registry."""
    from mtg_bot.training.registry import Registry
    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    registry_root = tmp_path / "registry"
    cli_train.main([
        "--architecture", "structured",
        "--data-dir", str(tmp_path / "data"),
        "--registry-root", str(registry_root),
        "--epochs", "1", "--batch-size", "4", "--val-split", "0.25",
        "--device", "cpu",
        "--emb-dim", "16", "--n-heads", "2", "--n-layers", "1",
        "--hidden-dim", "32", "--action-history-n", "4",
        "--progress-path", str(tmp_path / "progress" / "train.json"),
        *argv_extra,
    ])
    return Registry(registry_root)


def test_train_cli_default_writes_scalar_schema_v2(
    tmp_path: Path, monkeypatch,
) -> None:
    (tmp_path / "data").mkdir()
    _write_structured_npz(tmp_path / "data" / "d.npz", n_rows=8)
    registry = _run_train_cli(tmp_path, monkeypatch, [])
    meta = registry.load_metadata("v1")
    assert meta.scalar_schema_version == 2
    assert meta.training["structured_config"]["scalar_schema_version"] == 2
    assert meta.training["structured_scalar_schema_version"] == 2
    # The saved weights have the v2-wide projection.
    import torch
    sd = torch.load(registry.weights_path("v1"), weights_only=True)
    assert sd["scalar_proj.weight"].shape[1] == N_SCALAR_FIELDS_V2


def test_train_cli_schema_v1_flag_trains_on_legacy_width(
    tmp_path: Path, monkeypatch,
) -> None:
    (tmp_path / "data").mkdir()
    _write_structured_npz(
        tmp_path / "data" / "d.npz", n_rows=8, scalar_width=N_SCALAR_FIELDS,
    )
    registry = _run_train_cli(
        tmp_path, monkeypatch, ["--scalar-schema-version", "1"],
    )
    meta = registry.load_metadata("v1")
    assert meta.scalar_schema_version == 1
    import torch
    sd = torch.load(registry.weights_path("v1"), weights_only=True)
    assert sd["scalar_proj.weight"].shape[1] == N_SCALAR_FIELDS


def test_train_cli_refuses_scalar_width_mismatch(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    """v2-wide data + ``--scalar-schema-version 1`` exits via
    parser.error with a message naming both widths."""
    (tmp_path / "data").mkdir()
    _write_structured_npz(tmp_path / "data" / "d.npz", n_rows=8)
    with pytest.raises(SystemExit) as exc:
        _run_train_cli(tmp_path, monkeypatch, ["--scalar-schema-version", "1"])
    assert exc.value.code != 0
    err = capsys.readouterr().err
    assert "scalar schema mismatch" in err
    assert str(N_SCALAR_FIELDS_V2) in err


def test_train_cli_rejects_unknown_scalar_schema(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    (tmp_path / "data").mkdir()
    _write_structured_npz(tmp_path / "data" / "d.npz", n_rows=8)
    with pytest.raises(SystemExit):
        _run_train_cli(tmp_path, monkeypatch, ["--scalar-schema-version", "9"])
    assert "scalar_schema_version" in capsys.readouterr().err
