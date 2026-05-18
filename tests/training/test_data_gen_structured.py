"""Tests for the structured-token writer integration in
``mtg_bot.training.data_gen``.

Covers:

- Backward compatibility: with the flag OFF the npz contents are
  bit-identical (no extra keys) to the legacy path.
- Round-trip: with the flag ON the four new arrays land in the npz
  with consistent rows and load back cleanly.
- End-to-end smoke: a tiny 2-game self-play with the flag ON writes
  a valid npz that load_dataset reads without crashing.
"""

from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import pytest

from mtg_bot.features import FEATURE_DIM
from mtg_bot.training import (
    generate_training_data, load_dataset, random_choice_factory, save_dataset,
)
from mtg_bot.training.action_encoding import ACTION_VOCAB_SIZE
from mtg_bot.training.data_gen import (
    _STRUCT_NPZ_KEYS,
    _empty_structured_row,
    _pad_and_stack_structured_rows,
)
from mtg_bot.training.state_tokenizer import tokenize_state
from mtg_bot.training.structured_model import N_EMB_FIELDS, N_SCALAR_FIELDS

from tests._test_decks import simple_test_deck_pool


# ---------------------------------------------------------------------
# Pad-and-stack helper
# ---------------------------------------------------------------------


def test_pad_and_stack_with_empty_input_returns_empty_arrays() -> None:
    # The trailing token-field dim must match the populated path
    # (N_EMB_FIELDS / N_SCALAR_FIELDS) so empty timeout/crash chunks
    # can be stacked alongside real ones in the dataset loader.
    # Old behavior returned (0,0,0) which broadcast-failed against
    # (n, max_len, N_EMB_FIELDS) at train time — the iter_004
    # workaround was to quarantine the empties before training.
    out = _pad_and_stack_structured_rows([])
    assert out["structured_token_type"].shape == (0, 0)
    assert out["structured_token_emb_ids"].shape == (0, 0, N_EMB_FIELDS)
    assert out["structured_token_scalars"].shape == (0, 0, N_SCALAR_FIELDS)
    assert out["structured_attention_mask"].shape == (0, 0)


def test_pad_and_stack_pads_to_max_len_and_zeros_padding() -> None:
    """Rows with different seq_lens get right-padded to the max
    length; padding slots get zeros and attention_mask=False."""
    short = {
        "token_type": np.asarray([1, 2], dtype=np.int64),
        "token_emb_ids": np.asarray(
            [[5, 0, 0, 0, 0, 0, 0], [6, 0, 0, 0, 0, 0, 0]], dtype=np.int64,
        ),
        "token_scalars": np.zeros((2, N_SCALAR_FIELDS), dtype=np.float32),
        "attention_mask": np.ones((2,), dtype=np.bool_),
    }
    longer = {
        "token_type": np.asarray([3, 4, 5, 6], dtype=np.int64),
        "token_emb_ids": np.zeros((4, N_EMB_FIELDS), dtype=np.int64),
        "token_scalars": np.ones((4, N_SCALAR_FIELDS), dtype=np.float32),
        "attention_mask": np.ones((4,), dtype=np.bool_),
    }
    out = _pad_and_stack_structured_rows([short, longer])
    # max_len=4.
    assert out["structured_token_type"].shape == (2, 4)
    # Short row's last two slots are padded to 0 with mask=False.
    assert out["structured_token_type"][0].tolist() == [1, 2, 0, 0]
    assert out["structured_attention_mask"][0].tolist() == [
        True, True, False, False,
    ]
    # Longer row stays True throughout.
    assert all(out["structured_attention_mask"][1].tolist())


def test_pad_and_stack_with_only_empty_rows() -> None:
    """All-empty rows should still produce well-shaped arrays."""
    out = _pad_and_stack_structured_rows(
        [_empty_structured_row(), _empty_structured_row()],
    )
    assert out["structured_token_type"].shape == (2, 0)
    assert out["structured_attention_mask"].shape == (2, 0)


def test_empty_structured_row_returns_well_shaped_dict() -> None:
    row = _empty_structured_row()
    assert row["token_type"].shape == (0,)
    assert row["token_emb_ids"].shape == (0, N_EMB_FIELDS)
    assert row["token_scalars"].shape == (0, N_SCALAR_FIELDS)
    assert row["attention_mask"].shape == (0,)


# ---------------------------------------------------------------------
# Backwards compat: flag OFF leaves the npz layout untouched
# ---------------------------------------------------------------------


def test_generate_data_default_omits_structured_arrays() -> None:
    """With the flag at its default (False), the return tuple is the
    same legacy shape callers had before this feature landed."""
    features, outcomes = generate_training_data(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=1, base_seed=0, deck_pool=simple_test_deck_pool(),
    )
    assert features.dtype == np.float32
    assert features.shape[1] == FEATURE_DIM
    assert outcomes.shape == (features.shape[0],)


def test_save_dataset_without_structured_writes_no_extra_keys(
    tmp_path: Path,
) -> None:
    features = np.zeros((3, FEATURE_DIM), dtype=np.float32)
    outcomes = np.zeros((3,), dtype=np.float32)
    out_path = tmp_path / "value_only.npz"
    save_dataset(features, outcomes, out_path)
    with np.load(out_path) as data:
        assert set(data.files) == {"features", "outcomes"}


def test_load_dataset_legacy_file_returns_none_for_structured(
    tmp_path: Path,
) -> None:
    features = np.zeros((2, FEATURE_DIM), dtype=np.float32)
    outcomes = np.zeros((2,), dtype=np.float32)
    out_path = tmp_path / "value_only.npz"
    save_dataset(features, outcomes, out_path)
    (
        f, o, p, m, st, se, ss, sm,
    ) = load_dataset(out_path, with_structured=True)
    assert f.shape == (2, FEATURE_DIM)
    assert p is None and m is None
    assert st is None and se is None
    assert ss is None and sm is None


# ---------------------------------------------------------------------
# save_dataset structured array validation
# ---------------------------------------------------------------------


def test_save_dataset_rejects_partial_structured_arrays(
    tmp_path: Path,
) -> None:
    """All four structured arrays must be provided together or none
    of them."""
    features = np.zeros((1, FEATURE_DIM), dtype=np.float32)
    outcomes = np.zeros((1,), dtype=np.float32)
    only_one = np.zeros((1, 3), dtype=np.int64)
    with pytest.raises(ValueError, match="must be provided together"):
        save_dataset(
            features, outcomes, tmp_path / "bad.npz",
            structured_token_type=only_one,
        )


def test_save_dataset_rejects_mismatched_structured_rows(
    tmp_path: Path,
) -> None:
    """Structured arrays must share row count with features."""
    features = np.zeros((2, FEATURE_DIM), dtype=np.float32)
    outcomes = np.zeros((2,), dtype=np.float32)
    seq = 3
    # All four structured arrays — but with 1 row, not 2.
    st = np.zeros((1, seq), dtype=np.int64)
    se = np.zeros((1, seq, N_EMB_FIELDS), dtype=np.int64)
    ss = np.zeros((1, seq, N_SCALAR_FIELDS), dtype=np.float32)
    sm = np.zeros((1, seq), dtype=np.bool_)
    with pytest.raises(ValueError, match="rows"):
        save_dataset(
            features, outcomes, tmp_path / "bad.npz",
            structured_token_type=st,
            structured_token_emb_ids=se,
            structured_token_scalars=ss,
            structured_attention_mask=sm,
        )


def test_save_and_load_structured_round_trip(tmp_path: Path) -> None:
    """All four structured arrays survive a save → load cycle."""
    features = np.zeros((2, FEATURE_DIM), dtype=np.float32)
    outcomes = np.zeros((2,), dtype=np.float32)
    seq = 4
    st = np.arange(2 * seq, dtype=np.int64).reshape(2, seq)
    se = np.arange(2 * seq * N_EMB_FIELDS, dtype=np.int64).reshape(
        2, seq, N_EMB_FIELDS,
    )
    ss = np.zeros((2, seq, N_SCALAR_FIELDS), dtype=np.float32)
    sm = np.ones((2, seq), dtype=np.bool_)
    out_path = tmp_path / "with_struct.npz"
    save_dataset(
        features, outcomes, out_path,
        structured_token_type=st,
        structured_token_emb_ids=se,
        structured_token_scalars=ss,
        structured_attention_mask=sm,
    )
    with np.load(out_path) as data:
        for key in _STRUCT_NPZ_KEYS:
            assert key in data.files
        np.testing.assert_array_equal(data["structured_token_type"], st)
        np.testing.assert_array_equal(
            data["structured_token_emb_ids"], se,
        )
        np.testing.assert_array_equal(
            data["structured_attention_mask"], sm,
        )


# ---------------------------------------------------------------------
# End-to-end: flag ON populates the four arrays
# ---------------------------------------------------------------------


def test_generate_with_structured_tokens_returns_eight_tuple() -> None:
    out = generate_training_data(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=1, base_seed=11, deck_pool=simple_test_deck_pool(),
        structured_tokens=True,
    )
    assert len(out) == 8
    (
        features, outcomes, policy_targets, action_masks,
        struct_token_type, struct_emb_ids, struct_scalars, struct_mask,
    ) = out
    n = features.shape[0]
    # Every row gets a structured token entry.
    assert struct_token_type.shape[0] == n
    assert struct_emb_ids.shape[0] == n
    assert struct_scalars.shape[0] == n
    assert struct_mask.shape[0] == n
    # Per-row max_seq_len is consistent across the four arrays.
    max_len = struct_token_type.shape[1]
    assert struct_emb_ids.shape[1] == max_len
    assert struct_scalars.shape[1] == max_len
    assert struct_mask.shape[1] == max_len
    # Field widths match the model contract.
    assert struct_emb_ids.shape[2] == N_EMB_FIELDS
    assert struct_scalars.shape[2] == N_SCALAR_FIELDS
    # dtypes match what the model expects.
    assert struct_token_type.dtype == np.int64
    assert struct_emb_ids.dtype == np.int64
    assert struct_scalars.dtype == np.float32
    assert struct_mask.dtype == np.bool_


def test_generate_with_structured_tokens_aligns_legacy_arrays() -> None:
    """The structured arrays' row count must match the legacy
    features / outcomes / policy arrays so downstream code can
    iterate them together."""
    (
        features, outcomes, policy_targets, action_masks,
        struct_token_type, _, _, _,
    ) = generate_training_data(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=2, base_seed=22, deck_pool=simple_test_deck_pool(),
        structured_tokens=True,
    )
    assert struct_token_type.shape[0] == features.shape[0]
    assert struct_token_type.shape[0] == outcomes.shape[0]
    assert struct_token_type.shape[0] == policy_targets.shape[0]
    assert struct_token_type.shape[0] == action_masks.shape[0]


def test_generate_with_structured_tokens_zero_games_is_empty() -> None:
    out = generate_training_data(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=0, base_seed=0, deck_pool=simple_test_deck_pool(),
        structured_tokens=True,
    )
    assert len(out) == 8
    # Every array has 0 rows.
    for arr in out:
        assert arr.shape[0] == 0


def test_generate_with_structured_tokens_npz_smoke(
    tmp_path: Path,
) -> None:
    """End-to-end: tiny self-play with structured_tokens=True writes
    an npz that contains all four arrays and load_dataset reads them
    back."""
    out = generate_training_data(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=2, base_seed=33, deck_pool=simple_test_deck_pool(),
        structured_tokens=True,
    )
    (
        features, outcomes, policy_targets, action_masks,
        struct_token_type, struct_emb_ids, struct_scalars, struct_mask,
    ) = out
    npz_path = tmp_path / "structured.npz"
    save_dataset(
        features, outcomes, npz_path,
        policy_targets=policy_targets, action_masks=action_masks,
        structured_token_type=struct_token_type,
        structured_token_emb_ids=struct_emb_ids,
        structured_token_scalars=struct_scalars,
        structured_attention_mask=struct_mask,
    )
    # Re-load.
    (
        f, o, p, m, st, se, ss, sm,
    ) = load_dataset(npz_path, with_structured=True)
    np.testing.assert_array_equal(f, features)
    np.testing.assert_array_equal(o, outcomes)
    np.testing.assert_array_equal(p, policy_targets)
    np.testing.assert_array_equal(m, action_masks)
    np.testing.assert_array_equal(st, struct_token_type)
    np.testing.assert_array_equal(se, struct_emb_ids)
    np.testing.assert_array_equal(ss, struct_scalars)
    np.testing.assert_array_equal(sm, struct_mask)


def test_structured_tokens_action_history_grows_over_decisions() -> None:
    """The action-history feed accumulates as the game progresses —
    sample points after enough decisions should carry non-empty
    action tokens. Spot check: with a 2-game run, at least some rows
    have action_event tokens (token_type=11)."""
    from mtg_bot.training.structured_model import TOKEN_TYPE_ACTION_EVENT
    (
        features, outcomes, policy_targets, action_masks,
        struct_token_type, _, _, struct_mask,
    ) = generate_training_data(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=2, base_seed=44, deck_pool=simple_test_deck_pool(),
        structured_tokens=True,
    )
    # Count action-event tokens across all valid (mask=True) slots.
    valid = struct_mask
    n_action_tokens = int(
        ((struct_token_type == TOKEN_TYPE_ACTION_EVENT) & valid).sum()
    )
    assert n_action_tokens > 0


def test_structured_attention_mask_matches_real_tokens_only() -> None:
    """For every row, attention_mask=True exactly at slots where
    token_type was set to a real token type. Padded slots get
    token_type=0 (which collides with the CLS token-type id but the
    tokenizer doesn't emit CLS — TOKEN_TYPE_GLOBAL=1 is the actual
    first real slot, so 0 + mask=False unambiguously identifies
    padding)."""
    out = generate_training_data(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=1, base_seed=55, deck_pool=simple_test_deck_pool(),
        structured_tokens=True,
    )
    struct_token_type, struct_mask = out[4], out[7]
    # Where mask=False, token_type must be the zero/padding value.
    padded = ~struct_mask
    assert (struct_token_type[padded] == 0).all()
