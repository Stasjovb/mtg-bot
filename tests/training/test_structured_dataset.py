"""Tests for ``mtg_bot.training.structured_dataset``.

Covers:

- ``StructuredDataset.__getitem__`` trimming to real-length tokens.
- ``structured_collate`` per-batch padding to the batch max + correct
  attention masks.
- ``load_structured_dataset`` glob behavior, ``max_files`` recency
  filter, error paths (empty dir, npz missing structured arrays).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import pytest
import torch

from mtg_bot.features import FEATURE_DIM
from mtg_bot.training.action_encoding import ACTION_VOCAB_SIZE
from mtg_bot.training.data_gen import save_dataset
from mtg_bot.training.structured_dataset import (
    StructuredDataset,
    load_structured_dataset,
    structured_collate,
)
from mtg_bot.training.structured_model import (
    N_EMB_FIELDS, N_SCALAR_FIELDS,
)


def _make_struct_arrays(
    n_rows: int,
    *,
    seq_lens: list[int] | None = None,
    max_len: int = 6,
    seed: int = 0,
) -> dict[str, np.ndarray]:
    """Build a deterministic set of file-padded structured-token
    arrays for ``n_rows`` rows. ``seq_lens[i]`` is the true valid
    prefix length for row ``i``; missing positions get zeros + mask
    False (matching the data_gen padding contract)."""
    if seq_lens is None:
        seq_lens = [max_len] * n_rows
    assert len(seq_lens) == n_rows
    rng = np.random.default_rng(seed)
    token_type = np.zeros((n_rows, max_len), dtype=np.int64)
    token_emb_ids = np.zeros(
        (n_rows, max_len, N_EMB_FIELDS), dtype=np.int64,
    )
    token_scalars = np.zeros(
        (n_rows, max_len, N_SCALAR_FIELDS), dtype=np.float32,
    )
    attention_mask = np.zeros((n_rows, max_len), dtype=np.bool_)
    for i, L in enumerate(seq_lens):
        if L > 0:
            token_type[i, :L] = rng.integers(1, 10, size=L)
            token_emb_ids[i, :L, :] = rng.integers(
                0, 5, size=(L, N_EMB_FIELDS),
            )
            token_scalars[i, :L, :] = rng.standard_normal(
                (L, N_SCALAR_FIELDS)
            )
            attention_mask[i, :L] = True
    return {
        "structured_token_type": token_type,
        "structured_token_emb_ids": token_emb_ids,
        "structured_token_scalars": token_scalars,
        "structured_attention_mask": attention_mask,
    }


def _make_synthetic_npz(
    path: Path,
    n_rows: int,
    *,
    seq_lens: list[int] | None = None,
    max_len: int = 6,
    with_policy: bool = True,
    seed: int = 0,
) -> None:
    rng = np.random.default_rng(seed)
    features = rng.standard_normal((n_rows, FEATURE_DIM)).astype(np.float32)
    outcomes = rng.choice(
        np.array([-1.0, 0.0, 1.0], dtype=np.float32), size=n_rows,
    )
    if with_policy:
        policy_targets = np.zeros(
            (n_rows, ACTION_VOCAB_SIZE), dtype=np.float32,
        )
        action_masks = np.zeros(
            (n_rows, ACTION_VOCAB_SIZE), dtype=np.bool_,
        )
        # Give half the rows real supervision.
        for i in range(n_rows):
            if i % 2 == 0:
                policy_targets[i, 0] = 0.6
                policy_targets[i, 1] = 0.4
                action_masks[i, 0] = True
                action_masks[i, 1] = True
    else:
        policy_targets = None
        action_masks = None
    struct = _make_struct_arrays(
        n_rows, seq_lens=seq_lens, max_len=max_len, seed=seed,
    )
    save_dataset(
        features,
        outcomes,
        path,
        policy_targets=policy_targets,
        action_masks=action_masks,
        structured_token_type=struct["structured_token_type"],
        structured_token_emb_ids=struct["structured_token_emb_ids"],
        structured_token_scalars=struct["structured_token_scalars"],
        structured_attention_mask=struct["structured_attention_mask"],
    )


# ---------------------------------------------------------------------
# StructuredDataset
# ---------------------------------------------------------------------


def test_structured_dataset_len_and_item_shapes() -> None:
    seq_lens = [4, 2, 5]
    struct = _make_struct_arrays(3, seq_lens=seq_lens, max_len=5)
    outcomes = np.array([1.0, -1.0, 0.0], dtype=np.float32)
    policy_targets = np.zeros((3, ACTION_VOCAB_SIZE), dtype=np.float32)
    policy_targets[0, 0] = 1.0  # row 0 supervised
    action_masks = np.zeros((3, ACTION_VOCAB_SIZE), dtype=np.bool_)
    action_masks[0, 0] = True
    ds = StructuredDataset(
        token_type=struct["structured_token_type"],
        token_emb_ids=struct["structured_token_emb_ids"],
        token_scalars=struct["structured_token_scalars"],
        attention_mask=struct["structured_attention_mask"],
        outcomes=outcomes,
        policy_targets=policy_targets,
        action_masks=action_masks,
    )
    assert len(ds) == 3
    # Each row is trimmed to its true length.
    for i, L in enumerate(seq_lens):
        item = ds[i]
        assert item["token_type"].shape == (L,)
        assert item["token_emb_ids"].shape == (L, N_EMB_FIELDS)
        assert item["token_scalars"].shape == (L, N_SCALAR_FIELDS)
        assert item["attention_mask"].shape == (L,)
        assert item["attention_mask"].all()  # all real after trim
        assert item["outcome"].dtype == torch.float32
        assert item["policy_target"].shape == (ACTION_VOCAB_SIZE,)
        assert item["action_mask"].shape == (ACTION_VOCAB_SIZE,)
    # has_policy reflects sum > 0.5.
    assert bool(ds[0]["has_policy"].item()) is True
    assert bool(ds[1]["has_policy"].item()) is False


def test_structured_dataset_row_count_mismatch_raises() -> None:
    struct = _make_struct_arrays(3, max_len=4)
    with pytest.raises(ValueError, match="share row count"):
        StructuredDataset(
            token_type=struct["structured_token_type"],
            token_emb_ids=struct["structured_token_emb_ids"],
            token_scalars=struct["structured_token_scalars"],
            attention_mask=struct["structured_attention_mask"],
            outcomes=np.zeros((2,), dtype=np.float32),  # mismatch
            policy_targets=np.zeros(
                (3, ACTION_VOCAB_SIZE), dtype=np.float32,
            ),
            action_masks=np.zeros(
                (3, ACTION_VOCAB_SIZE), dtype=np.bool_,
            ),
        )


# ---------------------------------------------------------------------
# structured_collate
# ---------------------------------------------------------------------


def test_structured_collate_pads_to_batch_max() -> None:
    seq_lens = [3, 5, 2]
    struct = _make_struct_arrays(3, seq_lens=seq_lens, max_len=5)
    outcomes = np.array([1.0, -1.0, 0.0], dtype=np.float32)
    policy = np.zeros((3, ACTION_VOCAB_SIZE), dtype=np.float32)
    amask = np.zeros((3, ACTION_VOCAB_SIZE), dtype=np.bool_)
    ds = StructuredDataset(
        token_type=struct["structured_token_type"],
        token_emb_ids=struct["structured_token_emb_ids"],
        token_scalars=struct["structured_token_scalars"],
        attention_mask=struct["structured_attention_mask"],
        outcomes=outcomes,
        policy_targets=policy,
        action_masks=amask,
    )
    batch = structured_collate([ds[i] for i in range(3)])
    assert batch["token_type"].shape == (3, 5)
    assert batch["token_emb_ids"].shape == (3, 5, N_EMB_FIELDS)
    assert batch["token_scalars"].shape == (3, 5, N_SCALAR_FIELDS)
    assert batch["attention_mask"].shape == (3, 5)
    # Row 0 (seq_len=3) has 3 True then 2 False.
    assert batch["attention_mask"][0].tolist() == [True, True, True, False, False]
    assert batch["attention_mask"][1].tolist() == [True] * 5
    assert batch["attention_mask"][2].tolist() == [True, True, False, False, False]
    # Outcome / policy / mask preserved.
    assert batch["outcome"].shape == (3,)
    assert batch["policy_target"].shape == (3, ACTION_VOCAB_SIZE)
    assert batch["action_mask"].shape == (3, ACTION_VOCAB_SIZE)
    assert batch["has_policy"].shape == (3,)


def test_structured_collate_empty_batch_raises() -> None:
    with pytest.raises(ValueError, match="empty batch"):
        structured_collate([])


def test_structured_collate_handles_zero_seq_len_rows() -> None:
    """All-zero-length rows promote max_len to 1 so the model never
    sees a zero-key attention call."""
    seq_lens = [0, 0]
    struct = _make_struct_arrays(2, seq_lens=seq_lens, max_len=3)
    ds = StructuredDataset(
        token_type=struct["structured_token_type"],
        token_emb_ids=struct["structured_token_emb_ids"],
        token_scalars=struct["structured_token_scalars"],
        attention_mask=struct["structured_attention_mask"],
        outcomes=np.zeros((2,), dtype=np.float32),
        policy_targets=np.zeros(
            (2, ACTION_VOCAB_SIZE), dtype=np.float32,
        ),
        action_masks=np.zeros(
            (2, ACTION_VOCAB_SIZE), dtype=np.bool_,
        ),
    )
    batch = structured_collate([ds[0], ds[1]])
    assert batch["token_type"].shape == (2, 1)
    assert batch["attention_mask"].tolist() == [[False], [False]]


# ---------------------------------------------------------------------
# load_structured_dataset
# ---------------------------------------------------------------------


def test_load_structured_dataset_concatenates_across_files(
    tmp_path: Path,
) -> None:
    _make_synthetic_npz(tmp_path / "a.npz", n_rows=4, seq_lens=[3, 4, 2, 4], max_len=4, seed=1)
    _make_synthetic_npz(tmp_path / "b.npz", n_rows=3, seq_lens=[1, 2, 3], max_len=5, seed=2)
    ds = load_structured_dataset(tmp_path)
    assert len(ds) == 7
    # global max seq_len = 5 ; row from a.npz that had file-max=4
    # should still trim to its real length on __getitem__.
    sample_a = ds[0]  # row 0 from a.npz had seq_len=3
    assert sample_a["token_type"].shape == (3,)
    sample_b = ds[6]  # row 2 from b.npz had seq_len=3
    assert sample_b["token_type"].shape == (3,)


def test_load_structured_dataset_empty_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_structured_dataset(tmp_path)


def test_load_structured_dataset_missing_struct_raises(tmp_path: Path) -> None:
    """An npz that has features+outcomes but no structured-token
    arrays raises rather than silently returning zero structured
    data — the structured trainer requires the flag-on output."""
    n = 4
    rng = np.random.default_rng(0)
    features = rng.standard_normal((n, FEATURE_DIM)).astype(np.float32)
    outcomes = np.zeros((n,), dtype=np.float32)
    save_dataset(features, outcomes, tmp_path / "legacy.npz")
    with pytest.raises(ValueError, match="missing structured-token"):
        load_structured_dataset(tmp_path)


def test_load_structured_dataset_max_files_picks_most_recent(
    tmp_path: Path,
) -> None:
    old_path = tmp_path / "old.npz"
    _make_synthetic_npz(old_path, n_rows=3, seed=1)
    # Backdate ``old.npz`` so the recency filter can prefer the other file.
    old_time = time.time() - 10_000
    os.utime(old_path, (old_time, old_time))
    new_path = tmp_path / "new.npz"
    _make_synthetic_npz(new_path, n_rows=5, seed=2)
    ds = load_structured_dataset(tmp_path, max_files=1)
    assert len(ds) == 5  # only ``new.npz``'s rows


def test_load_structured_dataset_max_files_invalid(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="max_files must be positive"):
        load_structured_dataset(tmp_path, max_files=0)


# ---------------------------------------------------------------------
# from_per_file_arrays + per-file ragged storage
# ---------------------------------------------------------------------


def test_from_per_file_arrays_packs_into_flat_storage() -> None:
    """Files with different per-file ``max_len`` get flattened into
    one packed real-token array indexed by ``row_offsets``. The
    earlier eager-allocation implementation OOM'd at ~42 GiB on
    production data because every row was padded to the global max;
    a per-file ragged interim layout fit in memory but still paid
    Python overhead per ``__getitem__``. Packed-flat storage
    eliminates BOTH issues: no padding bytes, no per-row lookup."""
    # File 0: 3 rows, per-file max_len=4.
    s0 = _make_struct_arrays(3, seq_lens=[3, 4, 2], max_len=4, seed=1)
    # File 1: 2 rows, per-file max_len=8 (much larger, exercises the
    # historic OOM case).
    s1 = _make_struct_arrays(2, seq_lens=[5, 7], max_len=8, seed=2)
    outcomes_pf = [
        np.array([1.0, 0.0, -1.0], dtype=np.float32),
        np.array([1.0, -1.0], dtype=np.float32),
    ]
    pol_pf = [
        np.zeros((3, ACTION_VOCAB_SIZE), dtype=np.float32),
        np.zeros((2, ACTION_VOCAB_SIZE), dtype=np.float32),
    ]
    am_pf = [
        np.zeros((3, ACTION_VOCAB_SIZE), dtype=np.bool_),
        np.zeros((2, ACTION_VOCAB_SIZE), dtype=np.bool_),
    ]
    ds = StructuredDataset.from_per_file_arrays(
        token_type_per_file=[s0["structured_token_type"], s1["structured_token_type"]],
        token_emb_ids_per_file=[
            s0["structured_token_emb_ids"], s1["structured_token_emb_ids"],
        ],
        token_scalars_per_file=[
            s0["structured_token_scalars"], s1["structured_token_scalars"],
        ],
        attention_mask_per_file=[
            s0["structured_attention_mask"], s1["structured_attention_mask"],
        ],
        outcomes_per_file=outcomes_pf,
        policy_targets_per_file=pol_pf,
        action_masks_per_file=am_pf,
    )
    assert len(ds) == 5
    # Internal storage is packed: token_type_flat shape = (sum of real
    # row lengths,). For our inputs that's 3 + 4 + 2 + 5 + 7 = 21.
    total_real = 3 + 4 + 2 + 5 + 7
    assert ds._token_type_flat.shape == (total_real,)
    assert ds._row_offsets.tolist() == [0, 3, 7, 9, 14, 21]
    # __getitem__ trims rows down to their true length.
    assert ds[0]["token_type"].shape == (3,)
    assert ds[1]["token_type"].shape == (4,)
    assert ds[2]["token_type"].shape == (2,)
    assert ds[3]["token_type"].shape == (5,)
    assert ds[4]["token_type"].shape == (7,)
    # The outcomes line up across the file boundary.
    assert ds[0]["outcome"].item() == 1.0
    assert ds[3]["outcome"].item() == 1.0  # file 1 row 0
    assert ds[4]["outcome"].item() == -1.0  # file 1 row 1


def test_from_per_file_arrays_mismatched_file_count_raises() -> None:
    s = _make_struct_arrays(2, max_len=3)
    with pytest.raises(ValueError, match="per-file lists must share length"):
        StructuredDataset.from_per_file_arrays(
            token_type_per_file=[s["structured_token_type"]],
            token_emb_ids_per_file=[
                s["structured_token_emb_ids"],
                s["structured_token_emb_ids"],
            ],  # length mismatch
            token_scalars_per_file=[s["structured_token_scalars"]],
            attention_mask_per_file=[s["structured_attention_mask"]],
            outcomes_per_file=[np.zeros((2,), dtype=np.float32)],
            policy_targets_per_file=[
                np.zeros((2, ACTION_VOCAB_SIZE), dtype=np.float32)
            ],
            action_masks_per_file=[
                np.zeros((2, ACTION_VOCAB_SIZE), dtype=np.bool_)
            ],
        )


def test_from_per_file_arrays_per_file_row_count_mismatch_raises() -> None:
    s = _make_struct_arrays(3, max_len=4)
    with pytest.raises(ValueError, match="file index 0 must share row count"):
        StructuredDataset.from_per_file_arrays(
            token_type_per_file=[s["structured_token_type"]],
            token_emb_ids_per_file=[s["structured_token_emb_ids"]],
            token_scalars_per_file=[s["structured_token_scalars"]],
            attention_mask_per_file=[s["structured_attention_mask"]],
            # Outcomes has 2 rows but the others have 3 -> mismatch.
            outcomes_per_file=[np.zeros((2,), dtype=np.float32)],
            policy_targets_per_file=[
                np.zeros((3, ACTION_VOCAB_SIZE), dtype=np.float32)
            ],
            action_masks_per_file=[
                np.zeros((3, ACTION_VOCAB_SIZE), dtype=np.bool_)
            ],
        )


def test_zero_row_file_in_middle_does_not_shift_indexing() -> None:
    """A file with zero rows in the middle of the per-file list
    mustn't shift the global-index mapping for subsequent files."""
    s_real = _make_struct_arrays(3, seq_lens=[2, 3, 1], max_len=3, seed=0)
    # Empty arrays at file 1 (zero rows) at the same per-file max_len.
    empty_tt = np.zeros((0, 3), dtype=np.int64)
    empty_emb = np.zeros((0, 3, N_EMB_FIELDS), dtype=np.int64)
    empty_sca = np.zeros((0, 3, N_SCALAR_FIELDS), dtype=np.float32)
    empty_mask = np.zeros((0, 3), dtype=np.bool_)
    empty_outcome = np.zeros((0,), dtype=np.float32)
    empty_pol = np.zeros((0, ACTION_VOCAB_SIZE), dtype=np.float32)
    empty_am = np.zeros((0, ACTION_VOCAB_SIZE), dtype=np.bool_)
    ds = StructuredDataset.from_per_file_arrays(
        token_type_per_file=[s_real["structured_token_type"], empty_tt],
        token_emb_ids_per_file=[
            s_real["structured_token_emb_ids"], empty_emb,
        ],
        token_scalars_per_file=[
            s_real["structured_token_scalars"], empty_sca,
        ],
        attention_mask_per_file=[
            s_real["structured_attention_mask"], empty_mask,
        ],
        outcomes_per_file=[
            np.array([1.0, -1.0, 0.0], dtype=np.float32),
            empty_outcome,
        ],
        policy_targets_per_file=[
            np.zeros((3, ACTION_VOCAB_SIZE), dtype=np.float32),
            empty_pol,
        ],
        action_masks_per_file=[
            np.zeros((3, ACTION_VOCAB_SIZE), dtype=np.bool_),
            empty_am,
        ],
    )
    assert len(ds) == 3
    # Per-row seq_len from packed storage: seq_lens=[2, 3, 1] from file 0,
    # nothing from the empty file 1.
    assert ds[0]["token_type"].shape == (2,)
    assert ds[1]["token_type"].shape == (3,)
    assert ds[2]["token_type"].shape == (1,)
    # row_offsets walk: 0 -> 2 -> 5 -> 6. Total real tokens = 6.
    assert ds._row_offsets.tolist() == [0, 2, 5, 6]
    assert ds._token_type_flat.shape == (6,)
    # Outcomes line up — file 1 is empty so file 0's rows fully cover
    # the global index range.
    assert ds[0]["outcome"].item() == 1.0
    assert ds[1]["outcome"].item() == -1.0
    assert ds[2]["outcome"].item() == 0.0


def test_getitem_out_of_range_raises() -> None:
    s = _make_struct_arrays(2, max_len=3)
    ds = StructuredDataset(
        token_type=s["structured_token_type"],
        token_emb_ids=s["structured_token_emb_ids"],
        token_scalars=s["structured_token_scalars"],
        attention_mask=s["structured_attention_mask"],
        outcomes=np.zeros((2,), dtype=np.float32),
        policy_targets=np.zeros((2, ACTION_VOCAB_SIZE), dtype=np.float32),
        action_masks=np.zeros((2, ACTION_VOCAB_SIZE), dtype=np.bool_),
    )
    with pytest.raises(IndexError, match="index 2 out of range"):
        ds[2]
    with pytest.raises(IndexError, match="index -1 out of range"):
        ds[-1]


def test_load_structured_dataset_files_with_different_max_lens(
    tmp_path: Path,
) -> None:
    """End-to-end: files with VERY different per-file max_seq_len are
    loaded into a single packed real-token array. The crashing
    production scenario was 1700 files where 99% had max_len ~70 and
    a few had max_len 115; the global allocation inflated padding by
    1.6x. This test pins that the new path packs real tokens only —
    no padding bytes, no per-file padded storage."""
    _make_synthetic_npz(
        tmp_path / "a.npz", n_rows=3, seq_lens=[2, 3, 1],
        max_len=3, seed=1,
    )
    _make_synthetic_npz(
        tmp_path / "b.npz", n_rows=2, seq_lens=[5, 7],
        max_len=10, seed=2,
    )
    ds = load_structured_dataset(tmp_path)
    assert len(ds) == 5
    # Internal storage is one packed array of shape (total_real,);
    # total_real = 2 + 3 + 1 + 5 + 7 = 18 (NO padding bytes).
    total_real = 2 + 3 + 1 + 5 + 7
    assert ds._token_type_flat.shape == (total_real,)
    assert ds._row_offsets.tolist() == [0, 2, 5, 6, 11, 18]
    # __getitem__ slices produce correct row shapes.
    assert ds[0]["token_type"].shape == (2,)
    assert ds[3]["token_type"].shape == (5,)
    assert ds[4]["token_type"].shape == (7,)


# ---------------------------------------------------------------------
# Scalar schema widths across files
# ---------------------------------------------------------------------


def test_scalar_width_property_reports_row_width() -> None:
    s = _make_struct_arrays(n_rows=3, max_len=4, seed=0)
    ds = StructuredDataset(
        token_type=s["structured_token_type"],
        token_emb_ids=s["structured_token_emb_ids"],
        token_scalars=s["structured_token_scalars"],
        attention_mask=s["structured_attention_mask"],
        outcomes=np.zeros(3, dtype=np.float32),
        policy_targets=np.zeros((3, ACTION_VOCAB_SIZE), dtype=np.float32),
        action_masks=np.zeros((3, ACTION_VOCAB_SIZE), dtype=np.bool_),
    )
    assert ds.scalar_width == N_SCALAR_FIELDS


def test_load_structured_dataset_rejects_mixed_scalar_widths(
    tmp_path: Path,
) -> None:
    """Two npz files generated under different scalar schemas must
    fail loudly (naming the file) instead of a bare numpy concat
    error."""
    from mtg_bot.training.structured_model import N_SCALAR_FIELDS_V2
    s3 = _make_struct_arrays(n_rows=2, max_len=3, seed=1)
    s29 = _make_struct_arrays(n_rows=2, max_len=3, seed=2)
    s29["structured_token_scalars"] = np.zeros(
        (2, 3, N_SCALAR_FIELDS_V2), dtype=np.float32,
    )
    for name, s in (("a_v1.npz", s3), ("b_v2.npz", s29)):
        save_dataset(
            np.zeros((2, FEATURE_DIM), dtype=np.float32),
            np.zeros(2, dtype=np.float32),
            tmp_path / name,
            structured_token_type=s["structured_token_type"],
            structured_token_emb_ids=s["structured_token_emb_ids"],
            structured_token_scalars=s["structured_token_scalars"],
            structured_attention_mask=s["structured_attention_mask"],
        )
    with pytest.raises(ValueError, match="scalar schema mismatch") as exc:
        load_structured_dataset(tmp_path)
    assert "b_v2.npz" in str(exc.value)


def test_load_structured_dataset_tolerates_zero_row_file_of_other_width(
    tmp_path: Path,
) -> None:
    """Crash / timeout npzs carry zero rows with a placeholder scalar
    width; they must not poison a load of real v2 files."""
    from mtg_bot.training.structured_model import N_SCALAR_FIELDS_V2
    real = _make_struct_arrays(n_rows=2, max_len=3, seed=3)
    real["structured_token_scalars"] = np.ones(
        (2, 3, N_SCALAR_FIELDS_V2), dtype=np.float32,
    )
    save_dataset(
        np.zeros((2, FEATURE_DIM), dtype=np.float32),
        np.zeros(2, dtype=np.float32),
        tmp_path / "real.npz",
        structured_token_type=real["structured_token_type"],
        structured_token_emb_ids=real["structured_token_emb_ids"],
        structured_token_scalars=real["structured_token_scalars"],
        structured_attention_mask=real["structured_attention_mask"],
    )
    save_dataset(
        np.zeros((0, FEATURE_DIM), dtype=np.float32),
        np.zeros(0, dtype=np.float32),
        tmp_path / "empty.npz",
        structured_token_type=np.zeros((0, 0), dtype=np.int64),
        structured_token_emb_ids=np.zeros((0, 0, N_EMB_FIELDS), dtype=np.int64),
        structured_token_scalars=np.zeros((0, 0, 3), dtype=np.float32),
        structured_attention_mask=np.zeros((0, 0), dtype=np.bool_),
    )
    ds = load_structured_dataset(tmp_path)
    assert len(ds) == 2
    assert ds.scalar_width == N_SCALAR_FIELDS_V2
