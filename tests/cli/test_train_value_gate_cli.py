"""CLI-level tests for the held-out value-quality gate.

``mtg_bot train --architecture structured`` must refuse to register a
value head that scores no better than the constant-0 predictor on the
game-level held-out split. These drive the real CLI over a tiny
synthetic dataset built to FAIL the gate (random labels, multiple
games so the split is non-empty), and over the same data with the
gate relaxed to confirm the only thing standing between the run and a
registered version is the gate itself.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from mtg_bot.cli import train as cli_train
from mtg_bot.features import FEATURE_DIM
from mtg_bot.training.action_encoding import ACTION_VOCAB_SIZE
from mtg_bot.training.data_gen import save_dataset
from mtg_bot.training.structured_model import (
    N_EMB_FIELDS,
    N_SCALAR_FIELDS_V2,
    SCALAR_FIELD_OPP_LIFE,
    SCALAR_FIELD_VIEWER_LIFE,
    TOKEN_TYPE_GLOBAL,
)


def _write_memorisable_npz(
    out_path: Path,
    *,
    n_games: int = 8,
    rows_per_game: int = 8,
    seq_len: int = 4,
    seed: int = 0,
) -> Path:
    """A dataset engineered so the value head CANNOT generalise.

    Each game gets a distinct printing id on every token (the "game
    identity" the real model memorises through ``printing_embed``) and
    a RANDOM outcome that no feature predicts. A model with enough
    capacity fits the training games perfectly and is a coin flip on
    held-out games — the exact failure the gate exists to catch.

    ``game_ids`` are written so the loader builds real game-level
    groups and the held-out split is non-empty.
    """
    rng = np.random.default_rng(seed)
    n_rows = n_games * rows_per_game
    game_ids = np.repeat(np.arange(n_games), rows_per_game).astype(np.int32)
    game_outcome = rng.choice(np.array([-1.0, 1.0], dtype=np.float32),
                              size=n_games)
    outcomes = game_outcome[game_ids]

    token_type = np.full((n_rows, seq_len), 2, dtype=np.int64)
    token_type[:, 0] = TOKEN_TYPE_GLOBAL
    token_emb_ids = np.zeros(
        (n_rows, seq_len, N_EMB_FIELDS), dtype=np.int64,
    )
    # Printing id == game identity: perfectly memorisable, perfectly
    # useless out of sample.
    token_emb_ids[:, :, 0] = (game_ids[:, None] + 1)
    token_scalars = np.zeros(
        (n_rows, seq_len, N_SCALAR_FIELDS_V2), dtype=np.float32,
    )
    token_scalars[:, 0, SCALAR_FIELD_VIEWER_LIFE] = 20.0
    token_scalars[:, 0, SCALAR_FIELD_OPP_LIFE] = 20.0
    attention_mask = np.ones((n_rows, seq_len), dtype=np.bool_)
    save_dataset(
        rng.standard_normal((n_rows, FEATURE_DIM)).astype(np.float32),
        outcomes,
        out_path,
        policy_targets=np.zeros(
            (n_rows, ACTION_VOCAB_SIZE), dtype=np.float32,
        ),
        action_masks=np.zeros(
            (n_rows, ACTION_VOCAB_SIZE), dtype=np.bool_,
        ),
        structured_token_type=token_type,
        structured_token_emb_ids=token_emb_ids,
        structured_token_scalars=token_scalars,
        structured_attention_mask=attention_mask,
        game_ids=game_ids,
    )
    return out_path


def _argv(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "--architecture", "structured",
        "--data-dir", str(tmp_path / "data"),
        "--registry-root", str(tmp_path / "registry"),
        "--epochs", "8", "--batch-size", "8", "--val-split", "0.25",
        "--lr", "0.05",
        "--device", "cpu",
        "--emb-dim", "16", "--n-heads", "2", "--n-layers", "1",
        "--hidden-dim", "32", "--action-history-n", "4",
        "--progress-path", str(tmp_path / "progress" / "train.json"),
        *extra,
    ]


@pytest.fixture
def memorisable(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    (tmp_path / "data").mkdir()
    _write_memorisable_npz(tmp_path / "data" / "shard_001.npz")
    return tmp_path


def test_gate_rejects_and_registers_nothing(
    memorisable: Path, capsys,
) -> None:
    """The headline behaviour: an unlearnable target produces NO
    promotable version and a non-zero exit."""
    with pytest.raises(SystemExit) as exc:
        cli_train.main(_argv(memorisable))
    assert exc.value.code == cli_train._GATE_REJECT_EXIT_CODE

    # Nothing registered — the registry root is empty (or absent).
    registry_root = memorisable / "registry"
    assert not any(
        p.is_dir() and p.name.startswith("v")
        for p in (registry_root.iterdir() if registry_root.is_dir() else [])
    )

    err = capsys.readouterr().err
    assert "TRAINING REJECTED" in err
    assert "held-out value MSE" in err
    assert "--min-holdout-value-quality" in err
    # Multi-line, actionable.
    assert len(err.strip().splitlines()) > 10


def test_gate_rejection_writes_metrics_into_progress_json(
    memorisable: Path,
) -> None:
    with pytest.raises(SystemExit):
        cli_train.main(_argv(memorisable))
    blob = json.loads(
        (memorisable / "progress" / "train.json").read_text()
    )
    metrics = blob["holdout_value_metrics"]
    assert metrics["n_rows"] > 0
    assert metrics["value_mse"] >= 1.0
    assert blob["value_gate"]["passed"] is False
    assert blob["value_gate"]["evaluated"] is True
    assert "does not generalise" in blob["value_gate"]["reason"]


def test_gate_disabled_registers_and_still_reports_metrics(
    memorisable: Path,
) -> None:
    """``--min-holdout-value-quality 0`` disables the gate. The same
    data registers a version, and the metrics are recorded anyway so
    the memorisation is still visible in metadata.json."""
    cli_train.main(
        _argv(memorisable, "--min-holdout-value-quality", "0")
    )
    meta = json.loads(
        (memorisable / "registry" / "v1" / "metadata.json").read_text()
    )
    hist = meta["training_history"]
    assert hist["holdout_value_metrics"]["n_rows"] > 0
    assert hist["value_gate"]["passed"] is True
    assert hist["value_gate"]["evaluated"] is False
    assert "DISABLED" in hist["value_gate"]["reason"]


def test_regularisation_knobs_recorded_in_metadata(
    memorisable: Path,
) -> None:
    cli_train.main(_argv(
        memorisable,
        "--min-holdout-value-quality", "0",
        "--dropout", "0.25",
        "--weight-decay", "5e-4",
    ))
    meta = json.loads(
        (memorisable / "registry" / "v1" / "metadata.json").read_text()
    )
    training = meta["training"]
    assert training["dropout"] == 0.25
    assert training["weight_decay"] == 5e-4
    assert training["restore_best"] is True
    assert training["min_holdout_value_quality"] == 0.0
    assert training["structured_config"]["dropout"] == 0.25


def test_defaults_are_dropout_point_one_and_wd_1e_4(
    memorisable: Path,
) -> None:
    cli_train.main(
        _argv(memorisable, "--min-holdout-value-quality", "0")
    )
    training = json.loads(
        (memorisable / "registry" / "v1" / "metadata.json").read_text()
    )["training"]
    assert training["dropout"] == cli_train.DEFAULT_STRUCTURED_DROPOUT
    assert training["dropout"] == 0.1
    assert (
        training["weight_decay"]
        == cli_train.DEFAULT_STRUCTURED_WEIGHT_DECAY == 1e-4
    )


def test_keep_last_epoch_flag_disables_restore_best(
    memorisable: Path,
) -> None:
    cli_train.main(_argv(
        memorisable, "--min-holdout-value-quality", "0",
        "--keep-last-epoch",
    ))
    training = json.loads(
        (memorisable / "registry" / "v1" / "metadata.json").read_text()
    )["training"]
    assert training["restore_best"] is False
    assert training["restored_best_epoch"] is None


def test_restore_best_records_the_saved_epoch(memorisable: Path) -> None:
    cli_train.main(
        _argv(memorisable, "--min-holdout-value-quality", "0")
    )
    meta = json.loads(
        (memorisable / "registry" / "v1" / "metadata.json").read_text()
    )
    hist = meta["training_history"]
    assert meta["training"]["restore_best"] is True
    # With a val split there is always a best epoch to restore.
    assert hist["restored_best_epoch"] == hist["best_val_epoch"]
    assert hist["restored_best_epoch"] >= 0


def test_life_diff_baseline_reported_for_schema_v2(
    memorisable: Path,
) -> None:
    """Schema v2 carries life on the global token, so the trivial
    baseline correlation is computed (here the life diff is constant,
    so the correlation is undefined -> None, reported as such rather
    than faked)."""
    cli_train.main(
        _argv(memorisable, "--min-holdout-value-quality", "0")
    )
    metrics = json.loads(
        (memorisable / "registry" / "v1" / "metadata.json").read_text()
    )["training_history"]["holdout_value_metrics"]
    assert "baseline_life_diff_corr" in metrics


def test_flat_architecture_refuses_structured_only_knobs(
    tmp_path: Path, capsys,
) -> None:
    """A regularisation flag that would be silently ignored on the
    flat-feature path is an error, not a no-op."""
    with pytest.raises(SystemExit):
        cli_train.main([
            "--data-dir", str(tmp_path),
            "--architecture", "shared",
            "--dropout", "0.1",
        ])
    assert "only apply to --architecture structured" in (
        capsys.readouterr().err
    )


def test_dropout_out_of_range_rejected(memorisable: Path, capsys) -> None:
    with pytest.raises(SystemExit):
        cli_train.main(_argv(memorisable, "--dropout", "1.0"))
    assert "--dropout must be in [0.0, 1.0)" in capsys.readouterr().err
