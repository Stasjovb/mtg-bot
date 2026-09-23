"""Game-level train/val split (feature/lf-training).

Rows from one self-play game are near-duplicates of each other; a
row-level split puts some of every game in val and turns val loss
into a memorisation score. These tests lock in:

- ``grouped_train_val_split`` never lets a group straddle the split.
- ``save_dataset`` / ``load_dataset`` round-trip ``game_ids``; files
  written before the key existed load with ``None``.
- ``load_all_datasets(include_group_ids=True)`` and
  ``load_structured_dataset`` derive per-file group ids: one group
  per game when ``game_ids`` is present, the whole file as one group
  for legacy NPZs (logged at INFO).
- Both trainers split by group (spied), and legacy files without
  ``game_ids`` still train.
- data_gen emits ``game_ids`` (``with_game_ids=True``) unique per game.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pytest

from mtg_bot.features import FEATURE_DIM
from mtg_bot.training import (
    generate_training_data, load_all_datasets, load_dataset,
    random_choice_factory, save_dataset,
)
from mtg_bot.training.action_encoding import ACTION_VOCAB_SIZE
from mtg_bot.training.data_gen import file_group_ids
from mtg_bot.training.structured_dataset import (
    StructuredDataset, load_structured_dataset,
)
from mtg_bot.training.structured_model import (
    N_EMB_FIELDS, N_SCALAR_FIELDS,
)
from mtg_bot.training import trainer as trainer_mod
from mtg_bot.training.trainer import (
    grouped_train_val_split, train_structured_model, train_value_network,
)
from tests._test_decks import simple_test_deck_pool
from tests.training.test_structured_trainer import _tiny_cfg


# ---------- grouped_train_val_split ----------------------------------------


def _assert_partition_by_group(group_ids, train_idx, val_idx):
    n = group_ids.shape[0]
    both = np.concatenate([train_idx, val_idx])
    assert sorted(both.tolist()) == list(range(n)), "not a partition"
    train_groups = set(group_ids[train_idx].tolist())
    val_groups = set(group_ids[val_idx].tolist())
    assert not (train_groups & val_groups), (
        f"groups straddle the split: {train_groups & val_groups}"
    )


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_grouped_split_no_group_straddles(seed):
    rng = np.random.default_rng(seed)
    # 200 rows spread unevenly over 20 groups, shuffled row order.
    group_ids = rng.integers(0, 20, size=200)
    train_idx, val_idx = grouped_train_val_split(
        group_ids, 0.25, np.random.default_rng(seed + 100),
    )
    _assert_partition_by_group(group_ids, train_idx, val_idx)
    n_groups = np.unique(group_ids).shape[0]
    assert np.unique(group_ids[val_idx]).shape[0] == int(n_groups * 0.25)


def test_grouped_split_val_zero_is_all_train():
    group_ids = np.repeat(np.arange(5), 4)
    train_idx, val_idx = grouped_train_val_split(
        group_ids, 0.0, np.random.default_rng(0),
    )
    assert val_idx.shape[0] == 0
    assert sorted(train_idx.tolist()) == list(range(20))


def test_grouped_split_single_group_has_empty_val(caplog):
    group_ids = np.zeros(12, dtype=np.int64)
    with caplog.at_level(logging.WARNING, logger="mtg_bot.training.trainer"):
        train_idx, val_idx = grouped_train_val_split(
            group_ids, 0.5, np.random.default_rng(0),
        )
    assert val_idx.shape[0] == 0
    assert train_idx.shape[0] == 12
    assert any("only ONE group" in r.getMessage() for r in caplog.records)


def test_grouped_split_rounds_up_to_one_val_group():
    """3 groups at val_split=0.1 rounds to 0 groups; we bump to 1 so
    early-stopping keeps a signal (legacy one-group-per-file NPZs)."""
    group_ids = np.repeat(np.array([10, 20, 30]), 7)
    train_idx, val_idx = grouped_train_val_split(
        group_ids, 0.1, np.random.default_rng(0),
    )
    _assert_partition_by_group(group_ids, train_idx, val_idx)
    assert val_idx.shape[0] == 7
    assert np.unique(group_ids[val_idx]).shape[0] == 1


def test_grouped_split_deterministic_in_rng():
    group_ids = np.random.default_rng(3).integers(0, 30, size=300)
    a = grouped_train_val_split(group_ids, 0.2, np.random.default_rng(7))
    b = grouped_train_val_split(group_ids, 0.2, np.random.default_rng(7))
    c = grouped_train_val_split(group_ids, 0.2, np.random.default_rng(8))
    assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])
    assert not (np.array_equal(a[0], c[0]) and np.array_equal(a[1], c[1]))


# ---------- save / load ------------------------------------------------------


def _flat_arrays(n_rows: int, seed: int = 0):
    rng = np.random.default_rng(seed)
    features = rng.standard_normal((n_rows, FEATURE_DIM)).astype(np.float32)
    outcomes = rng.choice(
        np.array([-1.0, 1.0], dtype=np.float32), size=n_rows,
    )
    policy = np.zeros((n_rows, ACTION_VOCAB_SIZE), dtype=np.float32)
    masks = np.zeros((n_rows, ACTION_VOCAB_SIZE), dtype=np.bool_)
    policy[:, 0] = 0.6
    policy[:, 1] = 0.4
    masks[:, :2] = True
    return features, outcomes, policy, masks


def test_save_load_round_trips_game_ids(tmp_path: Path):
    f, o, p, m = _flat_arrays(6)
    gids = np.array([0, 0, 1, 1, 1, 2], dtype=np.int32)
    save_dataset(
        f, o, tmp_path / "a.npz", policy_targets=p, action_masks=m,
        game_ids=gids,
    )
    with np.load(tmp_path / "a.npz") as data:
        assert "game_ids" in data.files
        assert data["game_ids"].dtype == np.int32
    out = load_dataset(tmp_path / "a.npz", with_policy=True, with_game_ids=True)
    assert len(out) == 5
    assert np.array_equal(out[4], gids)
    # Default shape unchanged for existing callers.
    assert len(load_dataset(tmp_path / "a.npz", with_policy=True)) == 4
    assert len(load_dataset(tmp_path / "a.npz")) == 2


def test_save_dataset_rejects_mismatched_game_ids(tmp_path: Path):
    f, o, p, m = _flat_arrays(4)
    with pytest.raises(ValueError, match="game_ids"):
        save_dataset(
            f, o, tmp_path / "a.npz", policy_targets=p, action_masks=m,
            game_ids=np.array([0, 1], dtype=np.int32),
        )


def test_load_dataset_legacy_file_reports_none_game_ids(tmp_path: Path):
    f, o, p, m = _flat_arrays(4)
    save_dataset(f, o, tmp_path / "old.npz", policy_targets=p, action_masks=m)
    out = load_dataset(
        tmp_path / "old.npz", with_policy=True, with_structured=True,
        with_game_ids=True,
    )
    assert len(out) == 9
    assert out[8] is None


def test_file_group_ids_modes(caplog):
    with caplog.at_level(logging.INFO, logger="mtg_bot.training.data_gen"):
        new = file_group_ids(np.array([0, 0, 3]), 3, file_index=2)
        old = file_group_ids(None, 4, file_index=1)
    assert new.tolist() == [2_000_000, 2_000_000, 2_000_003]
    assert old.tolist() == [1_000_000] * 4
    msgs = [r.getMessage() for r in caplog.records]
    assert any("game_ids present" in m for m in msgs)
    assert any("no game_ids key" in m for m in msgs)
    with pytest.raises(ValueError, match="rows"):
        file_group_ids(np.array([0, 1]), 3, file_index=0)


def test_load_all_datasets_group_ids_new_and_legacy_files(tmp_path: Path):
    f, o, p, m = _flat_arrays(5)
    gids = np.array([0, 0, 1, 1, 2], dtype=np.int32)
    save_dataset(
        f, o, tmp_path / "a.npz", policy_targets=p, action_masks=m,
        game_ids=gids,
    )
    f2, o2, p2, m2 = _flat_arrays(3, seed=1)
    save_dataset(f2, o2, tmp_path / "b.npz", policy_targets=p2, action_masks=m2)
    out = load_all_datasets(tmp_path, include_policy=True, include_group_ids=True)
    assert len(out) == 5
    group_ids = out[4]
    assert group_ids.dtype == np.int64
    assert group_ids.tolist() == [0, 0, 1, 1, 2] + [1_000_000] * 3
    # Value-only variant also carries the tail.
    out2 = load_all_datasets(tmp_path, include_group_ids=True)
    assert len(out2) == 3 and np.array_equal(out2[2], group_ids)
    # Existing shapes unchanged when the flag is off.
    assert len(load_all_datasets(tmp_path, include_policy=True)) == 4
    assert len(load_all_datasets(tmp_path)) == 2


# ---------- legacy trainer ---------------------------------------------------


def _spy_split(monkeypatch):
    calls: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    real = trainer_mod.grouped_train_val_split

    def spy(group_ids, val_split, rng):
        train_idx, val_idx = real(group_ids, val_split, rng)
        calls.append((np.asarray(group_ids).copy(), train_idx, val_idx))
        return train_idx, val_idx

    monkeypatch.setattr(trainer_mod, "grouped_train_val_split", spy)
    return calls


def test_train_value_network_splits_by_game_group(tmp_path: Path, monkeypatch):
    calls = _spy_split(monkeypatch)
    f, o, p, m = _flat_arrays(40)
    group_ids = np.repeat(np.arange(8), 5)  # 8 games x 5 rows
    train_value_network(
        f, o, weights_out_path=tmp_path / "w.pt", epochs=1, batch_size=8,
        val_split=0.25, device="cpu", policy_targets=p, action_masks=m,
        group_ids=group_ids,
    )
    assert len(calls) == 1
    gids, train_idx, val_idx = calls[0]
    _assert_partition_by_group(gids, train_idx, val_idx)
    assert np.unique(gids[val_idx]).shape[0] == 2
    assert val_idx.shape[0] == 10


def test_train_value_network_rejects_wrong_length_group_ids(tmp_path: Path):
    f, o, _, _ = _flat_arrays(10)
    with pytest.raises(ValueError, match="group_ids"):
        train_value_network(
            f, o, weights_out_path=tmp_path / "w.pt", epochs=1,
            device="cpu", group_ids=np.arange(3),
        )


def test_train_value_network_without_group_ids_warns_and_row_splits(
    tmp_path: Path, monkeypatch, caplog,
):
    calls = _spy_split(monkeypatch)
    f, o, _, _ = _flat_arrays(20)
    with caplog.at_level(logging.WARNING, logger="mtg_bot.training.trainer"):
        train_value_network(
            f, o, weights_out_path=tmp_path / "w.pt", epochs=1,
            batch_size=8, val_split=0.1, device="cpu",
        )
    assert any("no group_ids" in r.getMessage() for r in caplog.records)
    gids, train_idx, val_idx = calls[0]
    assert gids.tolist() == list(range(20))
    assert val_idx.shape[0] == 2  # same count the old row split produced


def test_legacy_npz_without_game_ids_trains_with_file_groups(
    tmp_path: Path, monkeypatch,
):
    """Three pre-game_ids NPZs → three file-level groups; the trainer
    holds out exactly one whole file as val (0.1 rounds up to 1)."""
    calls = _spy_split(monkeypatch)
    for i, n in enumerate((6, 9, 12)):
        f, o, p, m = _flat_arrays(n, seed=i)
        save_dataset(
            f, o, tmp_path / f"legacy_{i}.npz",
            policy_targets=p, action_masks=m,
        )
    f, o, p, m, group_ids = load_all_datasets(
        tmp_path, include_policy=True, include_group_ids=True,
    )
    assert np.unique(group_ids).shape[0] == 3
    history = train_value_network(
        f, o, weights_out_path=tmp_path / "w.pt", epochs=2, batch_size=8,
        val_split=0.1, device="cpu", policy_targets=p, action_masks=m,
        group_ids=group_ids,
    )
    assert len(history.val_losses) == 2
    assert all(not np.isnan(v) for v in history.val_losses)
    gids, train_idx, val_idx = calls[0]
    _assert_partition_by_group(gids, train_idx, val_idx)
    assert np.unique(gids[val_idx]).shape[0] == 1
    assert val_idx.shape[0] in (6, 9, 12)


# ---------- structured dataset + trainer ------------------------------------


def _struct_arrays(n_rows: int, seq_len: int = 4, seed: int = 0):
    rng = np.random.default_rng(seed)
    token_type = rng.integers(0, 5, size=(n_rows, seq_len)).astype(np.int64)
    token_emb_ids = np.zeros((n_rows, seq_len, N_EMB_FIELDS), dtype=np.int64)
    token_scalars = rng.standard_normal(
        (n_rows, seq_len, N_SCALAR_FIELDS),
    ).astype(np.float32)
    attention_mask = np.ones((n_rows, seq_len), dtype=np.bool_)
    return token_type, token_emb_ids, token_scalars, attention_mask


def _write_structured_npz(path: Path, n_rows: int, game_ids, seed: int = 0):
    f, o, p, m = _flat_arrays(n_rows, seed=seed)
    tt, emb, sca, am = _struct_arrays(n_rows, seed=seed)
    save_dataset(
        f, o, path, policy_targets=p, action_masks=m,
        structured_token_type=tt, structured_token_emb_ids=emb,
        structured_token_scalars=sca, structured_attention_mask=am,
        game_ids=game_ids,
    )


def test_structured_dataset_default_group_ids_is_per_row():
    tt, emb, sca, am = _struct_arrays(6)
    f, o, p, m = _flat_arrays(6)
    ds = StructuredDataset(
        token_type=tt, token_emb_ids=emb, token_scalars=sca,
        attention_mask=am, outcomes=o, policy_targets=p, action_masks=m,
    )
    assert ds.group_ids.tolist() == list(range(6))
    ds2 = StructuredDataset(
        token_type=tt, token_emb_ids=emb, token_scalars=sca,
        attention_mask=am, outcomes=o, policy_targets=p, action_masks=m,
        group_ids=np.array([1, 1, 2, 2, 3, 3]),
    )
    assert ds2.group_ids.tolist() == [1, 1, 2, 2, 3, 3]


def test_structured_dataset_group_ids_survive_pickle_round_trip():
    import pickle
    tt, emb, sca, am = _struct_arrays(4)
    f, o, p, m = _flat_arrays(4)
    ds = StructuredDataset(
        token_type=tt, token_emb_ids=emb, token_scalars=sca,
        attention_mask=am, outcomes=o, policy_targets=p, action_masks=m,
        group_ids=np.array([7, 7, 8, 8]),
    )
    clone = pickle.loads(pickle.dumps(ds))
    assert clone.group_ids.tolist() == [7, 7, 8, 8]


def test_load_structured_dataset_group_ids_new_and_legacy(
    tmp_path: Path, caplog,
):
    _write_structured_npz(
        tmp_path / "a.npz", 5, np.array([0, 0, 1, 1, 2], dtype=np.int32),
    )
    _write_structured_npz(tmp_path / "b.npz", 3, None, seed=1)
    with caplog.at_level(logging.INFO):
        ds = load_structured_dataset(tmp_path)
    assert len(ds) == 8
    assert ds.group_ids.tolist() == [0, 0, 1, 1, 2] + [1_000_000] * 3
    msgs = [r.getMessage() for r in caplog.records]
    assert any("game_ids present" in m and "a.npz" in m for m in msgs)
    assert any("no game_ids key" in m and "b.npz" in m for m in msgs)
    assert any("4 game groups" in m for m in msgs)


def test_train_structured_model_splits_by_group(tmp_path: Path, monkeypatch):
    calls = _spy_split(monkeypatch)
    n_rows = 24
    tt, emb, sca, am = _struct_arrays(n_rows)
    f, o, p, m = _flat_arrays(n_rows)
    group_ids = np.repeat(np.arange(6), 4)
    ds = StructuredDataset(
        token_type=tt, token_emb_ids=emb, token_scalars=sca,
        attention_mask=am, outcomes=o, policy_targets=p, action_masks=m,
        group_ids=group_ids,
    )
    history = train_structured_model(
        ds, weights_out_path=tmp_path / "w.pt", config=_tiny_cfg(),
        epochs=1, batch_size=8, val_split=0.34, device="cpu",
        compile_model=False, autocast_dtype=False,
    )
    assert len(history.val_losses) == 1
    gids, train_idx, val_idx = calls[0]
    _assert_partition_by_group(gids, train_idx, val_idx)
    assert np.unique(gids[val_idx]).shape[0] == 2
    assert val_idx.shape[0] == 8


def test_train_structured_model_legacy_files_train(tmp_path: Path):
    """Legacy structured NPZs (no game_ids) load as one group per
    file and still train end-to-end with a held-out file."""
    for i in range(3):
        _write_structured_npz(tmp_path / f"legacy_{i}.npz", 8, None, seed=i)
    ds = load_structured_dataset(tmp_path)
    assert np.unique(ds.group_ids).shape[0] == 3
    history = train_structured_model(
        ds, weights_out_path=tmp_path / "w.pt", config=_tiny_cfg(),
        epochs=1, batch_size=8, val_split=0.1, device="cpu",
        compile_model=False, autocast_dtype=False,
    )
    assert len(history.val_losses) == 1
    assert not np.isnan(history.val_losses[0])


# ---------- data_gen emits game_ids -----------------------------------------


def test_generate_training_data_with_game_ids_unique_per_game(tmp_path: Path):
    out = generate_training_data(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=3, base_seed=5, deck_pool=simple_test_deck_pool(),
        with_policy=True, with_game_ids=True,
    )
    assert len(out) == 5
    features, outcomes, policy, masks, game_ids = out
    assert game_ids.dtype == np.int32
    assert game_ids.shape == (features.shape[0],)
    assert set(np.unique(game_ids).tolist()) <= {0, 1, 2}
    # Rows are concatenated per game in game order: ids are
    # non-decreasing, and every game that produced rows is present.
    assert np.all(np.diff(game_ids) >= 0)
    # Round-trip through save/load keeps the per-row ids.
    save_dataset(
        features, outcomes, tmp_path / "g.npz",
        policy_targets=policy, action_masks=masks, game_ids=game_ids,
    )
    loaded = load_dataset(tmp_path / "g.npz", with_game_ids=True)
    assert np.array_equal(loaded[2], game_ids)
    # Without the flag the classic 4-tuple is unchanged.
    out4 = generate_training_data(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=3, base_seed=5, deck_pool=simple_test_deck_pool(),
        with_policy=True,
    )
    assert len(out4) == 4
    assert np.array_equal(out4[0], features)
