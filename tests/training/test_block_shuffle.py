"""Tests for :mod:`mtg_bot.training.block_shuffle`.

The contract these pin, in order of how badly a regression would
hurt:

1. **Coverage + uniqueness.** Every epoch, across every worker, emits
   each train row exactly once. A desync between workers' block
   permutations would silently duplicate some rows and drop others —
   training would still "work", just on a corrupted sample.
2. **Row-for-row equality with ``__getitem__``.** Block mode only
   reorders; the tensors are byte-identical to the row-shuffle path.
3. Determinism under a seed, partial last block, non-contiguous
   Subsets, and the degenerate-span guard.
"""

from __future__ import annotations

import numpy as np
import pytest
import torch
from torch.utils.data import DataLoader, Subset

from mtg_bot.training.block_shuffle import (
    DEFAULT_BLOCK_ROWS,
    SPAN_BLOWUP_FACTOR,
    BlockShuffleDataset,
    resolve_shuffle_mode,
    store_nbytes,
    supports_block_shuffle,
    unwrap_subset,
)
from mtg_bot.training.structured_dataset import (
    StructuredDataset, structured_collate,
)


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


def _make_dataset(n_rows: int = 200, action_vocab: int = 7):
    """A small real ``StructuredDataset`` (memmap-backed, like
    production) with per-row-distinguishable contents."""
    rng = np.random.default_rng(1234)
    seq_lens = rng.integers(1, 6, size=n_rows)
    max_len = int(seq_lens.max())
    token_type = np.zeros((n_rows, max_len), dtype=np.int64)
    token_emb = np.zeros((n_rows, max_len, 3), dtype=np.int64)
    token_sca = np.zeros((n_rows, max_len, 3), dtype=np.float32)
    mask = np.zeros((n_rows, max_len), dtype=bool)
    for i, n in enumerate(seq_lens):
        n = int(n)
        mask[i, :n] = True
        # Row-identifying payload so a mis-ordered read is visible.
        token_type[i, :n] = (i % 11) + 1
        token_emb[i, :n, 0] = i
        token_sca[i, :n, 0] = float(i)
    outcomes = ((np.arange(n_rows) % 3) - 1).astype(np.float32)
    policy = np.zeros((n_rows, action_vocab), dtype=np.float32)
    policy[::2, 0] = 1.0  # every other row carries policy supervision
    action_mask = np.zeros((n_rows, action_vocab), dtype=bool)
    action_mask[::2, :2] = True
    return StructuredDataset(
        token_type, token_emb, token_sca, mask,
        outcomes, policy, action_mask,
    )


@pytest.fixture()
def dataset():
    ds = _make_dataset()
    yield ds
    ds.close()


# ---------------------------------------------------------------------
# unwrap_subset / introspection
# ---------------------------------------------------------------------


def test_unwrap_plain_dataset(dataset) -> None:
    base, idx = unwrap_subset(dataset)
    assert base is dataset
    np.testing.assert_array_equal(idx, np.arange(len(dataset)))


def test_unwrap_subset_returns_indices(dataset) -> None:
    sub = Subset(dataset, [5, 3, 9])
    base, idx = unwrap_subset(sub)
    assert base is dataset
    np.testing.assert_array_equal(idx, [5, 3, 9])


def test_unwrap_nested_subset_composes(dataset) -> None:
    sub = Subset(Subset(dataset, [10, 11, 12, 13]), [3, 1])
    base, idx = unwrap_subset(sub)
    assert base is dataset
    np.testing.assert_array_equal(idx, [13, 11])


def test_supports_and_store_nbytes(dataset) -> None:
    assert supports_block_shuffle(dataset)
    assert supports_block_shuffle(Subset(dataset, [1, 2]))
    nbytes = store_nbytes(dataset)
    assert nbytes is not None and nbytes > 0
    # Subset of the same store reports the WHOLE store's size.
    assert store_nbytes(Subset(dataset, [1, 2])) == nbytes


def test_unsupported_dataset_reports_false() -> None:
    class _Plain(torch.utils.data.Dataset):
        def __len__(self) -> int:
            return 3

        def __getitem__(self, i):  # pragma: no cover - never called
            return i

    plain = _Plain()
    assert not supports_block_shuffle(plain)
    assert store_nbytes(plain) is None


# ---------------------------------------------------------------------
# resolve_shuffle_mode
# ---------------------------------------------------------------------


def test_resolve_mode_passthrough(dataset) -> None:
    assert resolve_shuffle_mode("row", dataset) == "row"
    assert resolve_shuffle_mode("block", dataset) == "block"


def test_resolve_mode_rejects_unknown(dataset) -> None:
    with pytest.raises(ValueError, match="shuffle_mode must be one of"):
        resolve_shuffle_mode("blocky", dataset)


def test_resolve_block_on_unsupported_dataset_raises() -> None:
    class _Plain(torch.utils.data.Dataset):
        def __len__(self) -> int:
            return 3

        def __getitem__(self, i):  # pragma: no cover
            return i

    with pytest.raises(ValueError, match="requires a memmap-backed"):
        resolve_shuffle_mode("block", _Plain())


def test_resolve_auto_small_store_is_row(dataset) -> None:
    """A tiny store fits the page cache many times over — auto must
    leave the uniform row shuffle alone."""
    assert resolve_shuffle_mode("auto", dataset) == "row"


def test_resolve_auto_flips_to_block_when_store_exceeds_budget(
    dataset,
) -> None:
    """Same store, an absurdly small RAM fraction: auto flips."""
    assert resolve_shuffle_mode(
        "auto", dataset, ram_fraction=1e-12,
    ) == "block"


def test_resolve_auto_on_unsupported_dataset_is_row() -> None:
    class _Plain(torch.utils.data.Dataset):
        def __len__(self) -> int:
            return 3

        def __getitem__(self, i):  # pragma: no cover
            return i

    assert resolve_shuffle_mode("auto", _Plain()) == "row"


def test_resolve_auto_without_psutil_defaults_to_block(
    dataset, monkeypatch,
) -> None:
    """No psutil = no way to size the page cache. Block mode is never
    worse for I/O, so that's the safe default."""
    import builtins

    real_import = builtins.__import__

    def _no_psutil(name, *args, **kwargs):
        if name == "psutil":
            raise ImportError("no psutil")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_psutil)
    assert resolve_shuffle_mode("auto", dataset) == "block"


# ---------------------------------------------------------------------
# Construction + validation
# ---------------------------------------------------------------------


def test_rejects_bad_block_rows(dataset) -> None:
    with pytest.raises(ValueError, match="block_rows must be >= 1"):
        BlockShuffleDataset(dataset, block_rows=0)


def test_rejects_bad_window_blocks(dataset) -> None:
    with pytest.raises(ValueError, match="window_blocks must be >= 1"):
        BlockShuffleDataset(dataset, window_blocks=0)


def test_rejects_unsupported_dataset() -> None:
    class _Plain(torch.utils.data.Dataset):
        def __len__(self) -> int:
            return 3

        def __getitem__(self, i):  # pragma: no cover
            return i

    with pytest.raises(ValueError, match="requires a memmap-backed"):
        BlockShuffleDataset(_Plain())


def test_indices_are_sorted(dataset) -> None:
    sub = Subset(dataset, [9, 1, 5, 3])
    bs = BlockShuffleDataset(sub)
    np.testing.assert_array_equal(bs.indices, [1, 3, 5, 9])
    assert len(bs) == 4


def test_default_block_rows_constant() -> None:
    assert DEFAULT_BLOCK_ROWS == 65_536


# ---------------------------------------------------------------------
# Coverage + uniqueness (the load-bearing invariant)
# ---------------------------------------------------------------------


@pytest.mark.parametrize("num_workers", [1, 2, 3, 4, 7])
def test_every_row_exactly_once_across_workers(
    dataset, num_workers,
) -> None:
    bs = BlockShuffleDataset(dataset, block_rows=17, window_blocks=2)
    emitted: list[int] = []
    for w in range(num_workers):
        emitted.extend(
            bs.row_order((3, 0), worker_id=w, num_workers=num_workers)
            .tolist()
        )
    assert sorted(emitted) == list(range(len(dataset)))


@pytest.mark.parametrize("epoch", [0, 1, 2, 5])
def test_coverage_holds_every_epoch(dataset, epoch) -> None:
    bs = BlockShuffleDataset(dataset, block_rows=13, window_blocks=3)
    emitted: list[int] = []
    for w in range(3):
        emitted.extend(
            bs.row_order((epoch, 0), worker_id=w, num_workers=3).tolist()
        )
    assert sorted(emitted) == list(range(len(dataset)))


def test_workers_get_disjoint_blocks(dataset) -> None:
    bs = BlockShuffleDataset(dataset, block_rows=17)
    per_worker = [
        set(bs.row_order((0, 0), worker_id=w, num_workers=4).tolist())
        for w in range(4)
    ]
    for a in range(4):
        for b in range(a + 1, 4):
            assert not (per_worker[a] & per_worker[b])


def test_more_workers_than_blocks_is_safe(dataset) -> None:
    """8 workers, 2 blocks: six workers emit nothing and the two that
    do still cover everything exactly once."""
    bs = BlockShuffleDataset(dataset, block_rows=100)
    assert bs.n_blocks == 2
    emitted: list[int] = []
    empties = 0
    for w in range(8):
        rows = bs.row_order((0, 0), worker_id=w, num_workers=8).tolist()
        empties += not rows
        emitted.extend(rows)
    assert empties == 6
    assert sorted(emitted) == list(range(len(dataset)))


def test_coverage_with_non_contiguous_subset(dataset) -> None:
    """A Subset with holes (what ``grouped_train_val_split`` hands
    back) still emits exactly its own rows."""
    rng = np.random.default_rng(7)
    train_idx = rng.permutation(len(dataset))[:137]
    bs = BlockShuffleDataset(
        Subset(dataset, train_idx.tolist()), block_rows=20,
    )
    emitted: list[int] = []
    for w in range(3):
        emitted.extend(
            bs.row_order((0, 0), worker_id=w, num_workers=3).tolist()
        )
    assert sorted(emitted) == sorted(train_idx.tolist())


def test_rows_per_epoch_match_the_subset_it_replaces(dataset) -> None:
    sub = Subset(dataset, list(range(0, len(dataset), 2)))
    bs = BlockShuffleDataset(sub, block_rows=9)
    assert len(bs) == len(sub)
    assert len(bs.row_order((0, 0))) == len(sub)


# ---------------------------------------------------------------------
# Block boundaries
# ---------------------------------------------------------------------


def test_last_partial_block(dataset) -> None:
    """200 rows / 30-row blocks = 6 full + one 20-row tail."""
    bs = BlockShuffleDataset(dataset, block_rows=30)
    assert bs.n_blocks == 7
    assert bs.block_bounds(6) == (180, 200)
    assert sorted(bs.row_order((0, 0)).tolist()) == list(range(200))


def test_exact_multiple_has_no_partial_block(dataset) -> None:
    bs = BlockShuffleDataset(dataset, block_rows=50)
    assert bs.n_blocks == 4
    assert bs.block_bounds(3) == (150, 200)


def test_block_larger_than_dataset(dataset) -> None:
    bs = BlockShuffleDataset(dataset, block_rows=10_000)
    assert bs.n_blocks == 1
    assert sorted(bs.row_order((0, 0)).tolist()) == list(range(200))


def test_empty_subset_emits_nothing(dataset) -> None:
    bs = BlockShuffleDataset(Subset(dataset, []), block_rows=8)
    assert bs.n_blocks == 0
    assert len(bs) == 0
    assert list(iter(bs)) == []


# ---------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------


def test_same_seed_same_order(dataset) -> None:
    a = BlockShuffleDataset(dataset, block_rows=17, seed=42)
    b = BlockShuffleDataset(dataset, block_rows=17, seed=42)
    np.testing.assert_array_equal(
        a.row_order((2, 0), 1, 3), b.row_order((2, 0), 1, 3),
    )


def test_different_seed_different_order(dataset) -> None:
    a = BlockShuffleDataset(dataset, block_rows=17, seed=1)
    b = BlockShuffleDataset(dataset, block_rows=17, seed=2)
    assert not np.array_equal(a.row_order((0, 0)), b.row_order((0, 0)))


def test_different_epoch_different_order(dataset) -> None:
    bs = BlockShuffleDataset(dataset, block_rows=17, seed=0)
    assert not np.array_equal(
        bs.row_order((0, 0)), bs.row_order((1, 0)),
    )


def test_base_seed_component_changes_order(dataset) -> None:
    """The second epoch-key element is torch's per-iterator base
    seed — the reshuffle source when persistent_workers=False."""
    bs = BlockShuffleDataset(dataset, block_rows=17, seed=0)
    assert not np.array_equal(
        bs.row_order((0, 0)), bs.row_order((0, 99)),
    )


def test_iter_advances_the_epoch_counter(dataset) -> None:
    bs = BlockShuffleDataset(dataset, block_rows=17)
    first = [int(it["token_emb_ids"][0, 0]) for it in bs]
    second = [int(it["token_emb_ids"][0, 0]) for it in bs]
    assert sorted(first) == sorted(second) == list(range(200))
    assert first != second, "epoch 2 must reshuffle"


def test_set_epoch_pins_the_order(dataset) -> None:
    bs = BlockShuffleDataset(dataset, block_rows=17)
    bs.set_epoch(4)
    a = [int(it["token_emb_ids"][0, 0]) for it in bs]
    bs.set_epoch(4)
    b = [int(it["token_emb_ids"][0, 0]) for it in bs]
    assert a == b


# ---------------------------------------------------------------------
# Row payloads are identical to __getitem__
# ---------------------------------------------------------------------


def test_items_match_getitem_exactly(dataset) -> None:
    bs = BlockShuffleDataset(dataset, block_rows=13, window_blocks=2)
    seen = 0
    for item in bs:
        row = int(item["token_emb_ids"][0, 0])
        ref = dataset[row]
        assert set(item) == set(ref)
        for key in ref:
            assert item[key].dtype == ref[key].dtype, key
            assert torch.equal(item[key], ref[key]), key
        seen += 1
    assert seen == len(dataset)


def test_window_of_one_block_also_covers(dataset) -> None:
    bs = BlockShuffleDataset(dataset, block_rows=13, window_blocks=1)
    rows = [int(it["token_emb_ids"][0, 0]) for it in bs]
    assert sorted(rows) == list(range(len(dataset)))


def test_degenerate_span_falls_back_to_row_reads(dataset, caplog) -> None:
    """A subset whose rows are spread far apart must not try to slurp
    the whole span into RAM — but must still emit the same rows."""
    sparse = list(range(0, len(dataset), 50))  # 4 rows spanning 151
    bs = BlockShuffleDataset(Subset(dataset, sparse), block_rows=4)
    with caplog.at_level("WARNING"):
        rows = [int(it["token_emb_ids"][0, 0]) for it in bs]
    assert sorted(rows) == sparse
    assert any("row-by-row" in r.message for r in caplog.records)
    assert SPAN_BLOWUP_FACTOR == 4


def test_one_slice_per_array_per_block(dataset, monkeypatch) -> None:
    """The point of the whole module: a block costs ONE slice per
    flat array, not one per row."""
    calls: list[tuple[int, int]] = []

    class _Counting:
        def __init__(self, arr):
            self._arr = arr

        def __getitem__(self, key):
            if isinstance(key, slice):
                calls.append((key.start, key.stop))
            return self._arr[key]

        def __getattr__(self, name):
            return getattr(self._arr, name)

    monkeypatch.setattr(
        dataset, "_token_scalars_flat",
        _Counting(dataset._token_scalars_flat), raising=True,
    )
    bs = BlockShuffleDataset(dataset, block_rows=100, window_blocks=1)
    list(bs)
    # 200 rows / 100-row blocks = 2 blocks = 2 slices, not 200.
    assert len(calls) == 2, calls


# ---------------------------------------------------------------------
# DataLoader integration
# ---------------------------------------------------------------------


def test_dataloader_single_process_covers_epoch(dataset) -> None:
    loader = DataLoader(
        BlockShuffleDataset(dataset, block_rows=17, window_blocks=2),
        batch_size=8, shuffle=False, collate_fn=structured_collate,
        num_workers=0,
    )
    rows: list[int] = []
    n_batches = 0
    for batch in loader:
        n_batches += 1
        rows.extend(batch["token_emb_ids"][:, 0, 0].tolist())
    assert sorted(rows) == list(range(len(dataset)))
    assert n_batches == 25


def test_dataloader_batch_shapes_match_collate_contract(dataset) -> None:
    loader = DataLoader(
        BlockShuffleDataset(dataset, block_rows=64),
        batch_size=16, shuffle=False, collate_fn=structured_collate,
    )
    batch = next(iter(loader))
    assert batch["token_type"].dtype == torch.int64
    assert batch["token_emb_ids"].shape[0] == 16
    assert batch["token_scalars"].shape[0] == 16
    assert batch["attention_mask"].dtype == torch.bool
    assert batch["outcome"].shape == (16,)
    assert batch["has_policy"].dtype == torch.bool


def test_dataloader_two_epochs_reshuffle_same_rows(dataset) -> None:
    loader = DataLoader(
        BlockShuffleDataset(dataset, block_rows=17),
        batch_size=8, shuffle=False, collate_fn=structured_collate,
    )

    def _epoch() -> list[int]:
        out: list[int] = []
        for batch in loader:
            out.extend(batch["token_emb_ids"][:, 0, 0].tolist())
        return out

    first, second = _epoch(), _epoch()
    assert sorted(first) == sorted(second) == list(range(len(dataset)))
    assert first != second


def test_block_materializes_instead_of_holding_memmap_views() -> None:
    """The regression that made the whole feature a no-op: a memmap
    is an ndarray subclass, so ``np.asarray(memmap[lo:hi])`` returns
    the mapped VIEW and reads nothing. Every block array must be a
    real in-RAM copy, or the rows still fault in one at a time and
    block mode buys exactly zero I/O.

    Measured cold on this box: sequential materialization of a
    1.27 GB array ran at 570 MB/s; the same bytes reached by per-row
    random faults ran at ~15 MB/s.
    """
    from mtg_bot.training.block_shuffle import _RowBlock

    ds = _make_dataset()
    try:
        block = _RowBlock(ds, np.arange(0, 64, dtype=np.int64))
        for name in ("_tt", "_emb", "_sca", "_outcomes",
                     "_policy", "_mask", "_has_policy"):
            arr = getattr(block, name)
            assert not isinstance(arr, np.memmap), (
                f"{name} is still a memmap view -- no bytes were read"
            )
            assert arr.base is None or not isinstance(
                arr.base, np.memmap
            ), f"{name} is a view onto a memmap"
        assert block.nbytes > 0
    finally:
        ds.close()
