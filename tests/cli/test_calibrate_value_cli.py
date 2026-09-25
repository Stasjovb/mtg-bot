"""End-to-end tests for ``mtg_bot calibrate-value``.

The subcommand re-fits a registered version's value temperature on a
held-out split and rewrites ONLY ``metadata.value_calibration``. These
tests drive the real CLI over a tiny synthetic structured dataset:

- a version trained without a calibration gains one, and the fitted
  temperature is what the loader then applies;
- ``--dry-run`` measures and prints but leaves metadata.json byte-
  identical;
- re-running is idempotent (the fit works off the RAW pre-tanh logit,
  so it never compounds);
- the guard rails (unknown version, non-structured architecture,
  degenerate --val-split) exit non-zero instead of half-writing.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from mtg_bot.cli import calibrate_value as cli_calibrate
from mtg_bot.cli import train as cli_train
from mtg_bot.features import FEATURE_DIM
from mtg_bot.training.action_encoding import ACTION_VOCAB_SIZE
from mtg_bot.training.data_gen import save_dataset
from mtg_bot.training.structured_model import (
    N_EMB_FIELDS,
    N_SCALAR_FIELDS_V2,
)


def _write_structured_npz(
    out_path: Path, n_rows: int, *, seq_len: int = 4, seed: int = 0,
) -> Path:
    rng = np.random.default_rng(seed)
    features = rng.standard_normal((n_rows, FEATURE_DIM)).astype(np.float32)
    outcomes = rng.choice(
        np.array([-1.0, 1.0], dtype=np.float32), size=n_rows,
    )
    token_type = rng.integers(0, 5, size=(n_rows, seq_len)).astype(np.int64)
    # 0..2 is in-vocab for EVERY embedding field (the narrowest is
    # CONTROLLER_VOCAB_SIZE = 3); anything wider indexes off the end
    # of the smaller tables.
    token_emb_ids = rng.integers(
        0, 3, size=(n_rows, seq_len, N_EMB_FIELDS),
    ).astype(np.int64)
    token_scalars = rng.standard_normal(
        (n_rows, seq_len, N_SCALAR_FIELDS_V2),
    ).astype(np.float32)
    attention_mask = np.ones((n_rows, seq_len), dtype=np.bool_)
    policy_targets = np.zeros((n_rows, ACTION_VOCAB_SIZE), dtype=np.float32)
    action_masks = np.zeros((n_rows, ACTION_VOCAB_SIZE), dtype=np.bool_)
    policy_targets[:, 0] = 0.6
    policy_targets[:, 1] = 0.4
    action_masks[:, 0] = True
    action_masks[:, 1] = True
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


@pytest.fixture()
def trained(tmp_path: Path, monkeypatch):
    """Train a tiny structured version and hand back the paths."""
    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    monkeypatch.delenv("MTG_BOT_STRUCTURED_CACHE_DIR", raising=False)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    for i in range(3):
        _write_structured_npz(
            data_dir / f"shard_{i:03d}.npz", n_rows=48, seed=i,
        )
    registry_root = tmp_path / "weights"
    cli_train.main([
        "--data-dir", str(data_dir),
        "--registry-root", str(registry_root),
        "--epochs", "1",
        "--batch-size", "8",
        "--val-split", "0.25",
        "--device", "cpu",
        "--progress-path", str(tmp_path / "progress" / "train.json"),
        "--architecture", "structured",
        "--notes", "calibrate-value fixture",
    ])
    return data_dir, registry_root


def _meta(registry_root: Path, version: str = "v1") -> dict:
    return json.loads(
        (registry_root / version / "metadata.json").read_text()
    )


def test_dry_run_reports_without_touching_metadata(
    trained, capsys,
) -> None:
    data_dir, registry_root = trained
    before = (registry_root / "v1" / "metadata.json").read_bytes()
    rc = cli_calibrate.main([
        "--version", "v1",
        "--registry-root", str(registry_root),
        "--data-dir", str(data_dir),
        "--device", "cpu",
        "--dry-run",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "uncalibrated MSE" in out
    assert "calibrated MSE" in out
    assert "metadata.json NOT modified" in out
    assert (registry_root / "v1" / "metadata.json").read_bytes() == before


def test_writes_the_fitted_calibration_and_is_idempotent(
    trained,
) -> None:
    data_dir, registry_root = trained
    args = [
        "--version", "v1",
        "--registry-root", str(registry_root),
        "--data-dir", str(data_dir),
        "--device", "cpu",
    ]
    assert cli_calibrate.main(args) == 0
    meta = _meta(registry_root)
    cal = meta["value_calibration"]
    assert cal["method"] == "logit_temperature"
    assert cal["temperature"] > 0.0
    assert cal["n_rows"] > 0
    assert (
        "holdout_value_metrics_recalibrated" in meta["training_history"]
    )
    # weights.pt is not a calibration artifact and must not move.
    weights_before = (registry_root / "v1" / "weights.pt").read_bytes()

    # Second pass: the fit works off the raw logit, so it lands on the
    # same temperature rather than calibrating the calibration.
    assert cli_calibrate.main(args) == 0
    again = _meta(registry_root)["value_calibration"]
    assert again["temperature"] == pytest.approx(
        cal["temperature"], rel=1e-6,
    )
    assert again["bias"] == pytest.approx(cal["bias"], abs=1e-9)
    assert (
        registry_root / "v1" / "weights.pt"
    ).read_bytes() == weights_before


def test_the_written_temperature_is_what_the_loader_applies(
    trained,
) -> None:
    import torch

    from mtg_bot.search.nn_evaluator import NNEvaluator
    from mtg_bot.training.registry import Registry
    from mtg_bot.training.structured_model import make_dummy_batch

    data_dir, registry_root = trained
    assert cli_calibrate.main([
        "--version", "v1",
        "--registry-root", str(registry_root),
        "--data-dir", str(data_dir),
        "--device", "cpu",
    ]) == 0
    registry = Registry(registry_root)
    metadata = registry.load_metadata("v1")
    temperature = metadata.value_calibration["temperature"]
    bias = metadata.value_calibration["bias"]
    evaluator = NNEvaluator.from_metadata(
        registry.weights_path("v1"), metadata, device="cpu",
    )
    assert evaluator.model.config.value_temperature == temperature
    batch = make_dummy_batch(
        batch_size=2, seq_len=5, config=evaluator.model.config, seed=3,
    )
    evaluator.model.eval()
    with torch.no_grad():
        out = evaluator.model(batch)
    assert torch.allclose(
        out["value"],
        torch.tanh(out["value_logit"] / temperature + bias),
    )


def test_no_bias_pins_the_bias_to_zero(trained) -> None:
    data_dir, registry_root = trained
    assert cli_calibrate.main([
        "--version", "v1",
        "--registry-root", str(registry_root),
        "--data-dir", str(data_dir),
        "--device", "cpu",
        "--no-bias",
    ]) == 0
    assert _meta(registry_root)["value_calibration"]["bias"] == 0.0


def test_json_out_writes_the_payload(trained, tmp_path: Path) -> None:
    data_dir, registry_root = trained
    out = tmp_path / "nested" / "calibration.json"
    assert cli_calibrate.main([
        "--version", "v1",
        "--registry-root", str(registry_root),
        "--data-dir", str(data_dir),
        "--device", "cpu",
        "--json-out", str(out),
        "--dry-run",
    ]) == 0
    payload = json.loads(out.read_text())
    assert payload["version"] == "v1"
    assert payload["value_calibration"]["method"] == "logit_temperature"
    assert payload["holdout_value_metrics"]["n_rows"] > 0


def test_unknown_version_exits_nonzero(trained) -> None:
    data_dir, registry_root = trained
    assert cli_calibrate.main([
        "--version", "v99",
        "--registry-root", str(registry_root),
        "--data-dir", str(data_dir),
    ]) == 2


def test_non_structured_version_is_refused(
    trained, tmp_path: Path,
) -> None:
    data_dir, registry_root = trained
    meta_path = registry_root / "v1" / "metadata.json"
    meta = json.loads(meta_path.read_text())
    meta["architecture"] = "shared"
    meta_path.write_text(json.dumps(meta))
    assert cli_calibrate.main([
        "--version", "v1",
        "--registry-root", str(registry_root),
        "--data-dir", str(data_dir),
    ]) == 2


def test_degenerate_val_split_is_refused(trained) -> None:
    data_dir, registry_root = trained
    assert cli_calibrate.main([
        "--version", "v1",
        "--registry-root", str(registry_root),
        "--data-dir", str(data_dir),
        "--val-split", "0",
    ]) == 2


def test_missing_data_dir_is_refused(trained, tmp_path: Path) -> None:
    _, registry_root = trained
    assert cli_calibrate.main([
        "--version", "v1",
        "--registry-root", str(registry_root),
        "--data-dir", str(tmp_path / "nope"),
    ]) == 2
