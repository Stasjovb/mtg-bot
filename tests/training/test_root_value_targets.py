"""Dense value targets: the search root value recorded per row.

Covers the whole path a ``root_values`` column travels:

recorder helper -> struct-row stacking -> ``save_dataset`` /
runner npz -> flat store (NaN default, streamed column) ->
DataLoader batch -> trainer target resolution -> train CLI flag.
"""

from __future__ import annotations

import io
import json
import math
from pathlib import Path

import numpy as np
import pytest
import torch

from mtg_bot.cli import train as cli_train
from mtg_bot.features import FEATURE_DIM
from mtg_bot.training import structured_dataset
from mtg_bot.training.action_encoding import ACTION_VOCAB_SIZE
from mtg_bot.training.data_gen import (
    _pad_and_stack_structured_rows,
    _root_value_from_candidates,
    save_dataset,
)
from mtg_bot.training.structured_dataset import (
    load_structured_dataset,
    structured_collate,
)
from mtg_bot.training.structured_model import N_EMB_FIELDS, N_SCALAR_FIELDS
from mtg_bot.training.trainer import (
    _parse_value_target,
    _value_target_tensor,
)
from mtg_bot import worker_daemon_production_runner as prr


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _struct_row(
    length: int, root_value=None, seed: int = 0,
    scalar_width: int = N_SCALAR_FIELDS,
) -> dict:
    rng = np.random.default_rng(seed)
    row = {
        # Small ids: the CLI smoke feeds these through the real
        # StructuredModel, whose embedding tables are sized by the
        # per-field vocab (mirrors tests/cli/test_train_structured_cli).
        "token_type": rng.integers(0, 5, size=length).astype(np.int64),
        "token_emb_ids": np.zeros((length, N_EMB_FIELDS), dtype=np.int64),
        "token_scalars": rng.standard_normal(
            (length, scalar_width),
        ).astype(np.float32),
        "attention_mask": np.ones((length,), dtype=np.bool_),
    }
    if root_value is not None:
        row["root_value"] = np.float32(root_value)
    return row


def _write_npz(
    path: Path, n_rows: int, *, root_values=None, seed: int = 0,
    max_len: int = 5, scalar_width: int = N_SCALAR_FIELDS,
) -> None:
    rng = np.random.default_rng(seed)
    features = rng.standard_normal((n_rows, FEATURE_DIM)).astype(np.float32)
    outcomes = rng.choice(
        np.array([-1.0, 1.0], dtype=np.float32), size=n_rows,
    )
    policy_targets = np.zeros((n_rows, ACTION_VOCAB_SIZE), dtype=np.float32)
    action_masks = np.zeros((n_rows, ACTION_VOCAB_SIZE), dtype=np.bool_)
    policy_targets[:, 0] = 1.0
    action_masks[:, 0] = True
    rows = [
        _struct_row(max_len, seed=seed + i, scalar_width=scalar_width)
        for i in range(n_rows)
    ]
    struct = _pad_and_stack_structured_rows(rows)
    save_dataset(
        features, outcomes, path,
        policy_targets=policy_targets,
        action_masks=action_masks,
        game_ids=np.arange(n_rows, dtype=np.int32) // 2,
        structured_token_type=struct["structured_token_type"],
        structured_token_emb_ids=struct["structured_token_emb_ids"],
        structured_token_scalars=struct["structured_token_scalars"],
        structured_attention_mask=struct["structured_attention_mask"],
        root_values=root_values,
    )


# ---------------------------------------------------------------------------
# recorder helper
# ---------------------------------------------------------------------------


def test_root_value_from_candidates_is_visit_weighted_mean_q():
    cands = [
        {"decision": "a", "visits": 3, "q": 0.5},
        {"decision": "b", "visits": 1, "q": -0.5},
    ]
    assert _root_value_from_candidates(cands) == pytest.approx(0.25)


def test_root_value_from_candidates_skips_unusable_entries():
    cands = [
        {"decision": "forced", "visits": 1, "q": None},
        {"decision": "unvisited", "visits": 0, "q": 0.9},
    ]
    assert _root_value_from_candidates(cands) is None
    assert _root_value_from_candidates([]) is None


# ---------------------------------------------------------------------------
# stacking + save_dataset
# ---------------------------------------------------------------------------


def test_pad_and_stack_carries_root_values_with_nan_default():
    rows = [
        _struct_row(3, root_value=0.25),
        _struct_row(2),                 # no root value recorded
        _struct_row(0, root_value=-1.0),  # zero-token sentinel still keeps it
    ]
    out = _pad_and_stack_structured_rows(rows)
    rv = out["root_values"]
    assert rv.dtype == np.float32 and rv.shape == (3,)
    assert rv[0] == pytest.approx(0.25)
    assert math.isnan(rv[1])
    assert rv[2] == pytest.approx(-1.0)


def test_pad_and_stack_empty_has_zero_length_root_values():
    out = _pad_and_stack_structured_rows([])
    assert out["root_values"].shape == (0,)
    assert out["root_values"].dtype == np.float32


def test_save_dataset_writes_root_values_and_validates_shape(tmp_path):
    path = tmp_path / "with.npz"
    rv = np.array([0.1, np.nan, -0.3, 0.7], dtype=np.float32)
    _write_npz(path, 4, root_values=rv)
    with np.load(path) as z:
        assert "root_values" in z.files
        got = z["root_values"]
    assert got.dtype == np.float32
    np.testing.assert_array_equal(np.isnan(got), np.isnan(rv))
    assert got[0] == pytest.approx(0.1)
    with pytest.raises(ValueError, match="root_values shape"):
        _write_npz(tmp_path / "bad.npz", 4, root_values=rv[:3])


# ---------------------------------------------------------------------------
# flat store
# ---------------------------------------------------------------------------


def test_store_streams_root_values_and_defaults_missing_files_to_nan(
    tmp_path,
):
    rv = np.array([0.5, -0.25, np.nan, 1.0], dtype=np.float32)
    _write_npz(tmp_path / "a_with.npz", 4, root_values=rv, seed=1)
    _write_npz(tmp_path / "b_without.npz", 3, seed=2)  # legacy shard
    ds = load_structured_dataset(tmp_path)
    try:
        assert "root_values.npy" in structured_dataset.FLAT_STORE_DTYPES
        assert len(ds) == 7
        got = np.array([float(ds[i]["root_value"]) for i in range(len(ds))])
        # File order is deterministic (sorted); rows 0-3 come from
        # a_with.npz, 4-6 from the legacy shard.
        assert got[0] == pytest.approx(0.5)
        assert got[1] == pytest.approx(-0.25)
        assert math.isnan(got[2])
        assert got[3] == pytest.approx(1.0)
        assert all(math.isnan(x) for x in got[4:])
        batch = structured_collate([ds[i] for i in range(len(ds))])
        assert batch["root_value"].dtype == torch.float32
        assert batch["root_value"].shape == (7,)
        assert torch.isnan(batch["root_value"][4:]).all()
        assert float(batch["root_value"][0]) == pytest.approx(0.5)
    finally:
        ds.close()


def test_store_rejects_root_values_row_count_mismatch(tmp_path):
    """A shard whose ``root_values`` length disagrees with its token
    rows is corrupt; fail the load rather than mis-align targets."""
    _write_npz(tmp_path / "ok.npz", 3, seed=3)
    with np.load(tmp_path / "ok.npz") as z:
        arrays = {k: z[k] for k in z.files}
    arrays["root_values"] = np.zeros((2,), dtype=np.float32)
    np.savez_compressed(tmp_path / "ok.npz", **arrays)
    with pytest.raises(ValueError, match="root_values rows"):
        ds = load_structured_dataset(tmp_path)
        ds.close()


def test_in_memory_store_defaults_root_values_to_nan():
    """The from-arrays constructor writes the column too (the memmap
    opener reads every file in ``_ARRAY_FILES``)."""
    rows = [_struct_row(2, seed=7), _struct_row(3, seed=8)]
    struct = _pad_and_stack_structured_rows(rows)
    ds = structured_dataset.StructuredDataset(
        struct["structured_token_type"],
        struct["structured_token_emb_ids"],
        struct["structured_token_scalars"],
        struct["structured_attention_mask"],
        np.array([1.0, -1.0], dtype=np.float32),
        policy_targets=np.zeros((2, ACTION_VOCAB_SIZE), dtype=np.float32),
        action_masks=np.zeros((2, ACTION_VOCAB_SIZE), dtype=np.bool_),
    )
    try:
        assert math.isnan(float(ds[0]["root_value"]))
        assert math.isnan(float(ds[1]["root_value"]))
    finally:
        ds.close()


# ---------------------------------------------------------------------------
# worker runner npz
# ---------------------------------------------------------------------------


def test_runner_encode_npz_bytes_includes_root_values():
    n = 2
    features = np.zeros((n, FEATURE_DIM), dtype=np.float32)
    outcomes = np.array([1.0, -1.0], dtype=np.float32)
    policy = np.zeros((n, ACTION_VOCAB_SIZE), dtype=np.float32)
    masks = np.zeros((n, ACTION_VOCAB_SIZE), dtype=np.bool_)
    struct_rows = [
        _struct_row(3, root_value=0.4, seed=1),
        _struct_row(3, root_value=-0.4, seed=2),
    ]
    game_ids = np.zeros((n,), dtype=np.int32)
    chunk = (
        features, outcomes, policy, masks, 0, "completed",
        struct_rows, game_ids,
    )
    blob = prr._encode_npz_bytes(chunk, write_structured_tokens=True)
    with np.load(io.BytesIO(blob)) as z:
        assert "root_values" in z.files
        np.testing.assert_allclose(
            z["root_values"], np.array([0.4, -0.4], dtype=np.float32),
        )


# ---------------------------------------------------------------------------
# trainer target resolution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spec,expected", [
    ("outcome", ("outcome", 0.0)),
    ("root", ("root", 1.0)),
    ("ROOT", ("root", 1.0)),
    ("blend:0.3", ("blend", 0.3)),
])
def test_parse_value_target_accepts_documented_forms(spec, expected):
    mode, w = _parse_value_target(spec)
    assert mode == expected[0]
    assert w == pytest.approx(expected[1])


@pytest.mark.parametrize("spec", ["blend:1.5", "blend:x", "search"])
def test_parse_value_target_rejects_garbage(spec):
    with pytest.raises(ValueError):
        _parse_value_target(spec)


def test_value_target_tensor_root_falls_back_to_outcome_on_nan():
    batch = {
        "outcome": torch.tensor([1.0, -1.0, 1.0]),
        "root_value": torch.tensor([0.2, float("nan"), -0.6]),
    }
    root = _value_target_tensor(batch, "root", 1.0)
    assert torch.allclose(root, torch.tensor([0.2, -1.0, -0.6]))
    blend = _value_target_tensor(batch, "blend", 0.5)
    assert torch.allclose(blend, torch.tensor([0.6, -1.0, 0.2]))
    assert torch.equal(
        _value_target_tensor(batch, "outcome", 0.0), batch["outcome"],
    )


def test_value_target_tensor_without_root_column_is_outcome():
    batch = {"outcome": torch.tensor([1.0, -1.0])}
    assert torch.equal(
        _value_target_tensor(batch, "root", 1.0), batch["outcome"],
    )


# ---------------------------------------------------------------------------
# train CLI
# ---------------------------------------------------------------------------


def test_train_cli_value_target_root_trains_and_records_metadata(
    tmp_path, monkeypatch,
):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    rng = np.random.default_rng(0)
    rv = rng.uniform(-1, 1, size=16).astype(np.float32)
    rv[3] = np.nan
    # The CLI's default scalar schema is v2; write rows at its width.
    from mtg_bot.training.structured_model import scalar_width_for_schema
    _write_npz(
        data_dir / "shard_001.npz", 16, root_values=rv, seed=5,
        scalar_width=scalar_width_for_schema(2),
    )
    registry_root = tmp_path / "weights"
    progress_path = tmp_path / "progress" / "train.json"
    monkeypatch.delenv("MTG_BOT_RUN_DB_PATH", raising=False)
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    cli_train.main([
        "--data-dir", str(data_dir),
        "--registry-root", str(registry_root),
        "--epochs", "1",
        "--batch-size", "4",
        "--val-split", "0.25",
        "--device", "cpu",
        "--progress-path", str(progress_path),
        "--architecture", "structured",
        "--value-target", "blend:0.5",
        "--min-holdout-value-quality", "1e9",
        "--notes", "root-value smoke",
    ])
    meta = json.loads((registry_root / "v1" / "metadata.json").read_text())
    assert meta["training"]["value_target"] == "blend:0.5"
    assert meta["training_history"]["train_losses"]


def test_train_cli_value_target_is_structured_only(tmp_path, capsys):
    """The flat-feature trainer has no root-value path; passing the
    flag there is refused loudly (same policy as --dropout)."""
    with pytest.raises(SystemExit):
        cli_train.main([
            "--data-dir", str(tmp_path),
            "--registry-root", str(tmp_path / "w"),
            "--value-target", "root",
        ])
    assert "--value-target" in capsys.readouterr().err
