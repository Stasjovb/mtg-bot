"""Block-shuffled sampling over a memmap-backed
:class:`~mtg_bot.training.structured_dataset.StructuredDataset`.

Why
===

``DataLoader(Subset(dataset, train_idx), shuffle=True)`` draws rows in
a uniformly random order over the whole train split. Every row is a
separate slice into the flat store's memmaps, so every batch is
``batch_size`` independent random reads scattered over the entire
store. That is fine while the store fits in the OS page cache and
catastrophic the moment it doesn't:

    MEASURED 2026-09-25, warm-start run, 6,000 files / ~6.6M rows /
    ~60 GB store on a 64 GB box with ~27 GB free: the four DataLoader
    workers sat in ``__getitem__`` page-faulting. Disk 111% busy,
    ~6,800 reads/s at ~170 MB/s (i.e. ~25 KB per read — essentially
    pure 4 KB-fault random I/O), GPU 10-20%, and epoch 1 was still
    unfinished after 70 minutes (26k steps at batch 256).

Random 4 KB faults cap out at the device's IOPS. Sequential reads of
the same bytes run at the device's bandwidth, which is one to two
orders of magnitude more rows per second.

What
====

:class:`BlockShuffleDataset` is an ``IterableDataset`` wrapper that
keeps the SAME set of rows per epoch and only changes their ORDER:

1. The wrapped index space (a ``Subset``'s indices, or ``range(len)``)
   is **sorted ascending** once at construction so that a contiguous
   run of index positions is also a contiguous run of *storage* rows.
   Sorting changes no row membership — ``grouped_train_val_split``
   hands back a pre-shuffled index array and the shuffle it applied is
   exactly what this class re-derives per epoch anyway.
2. The sorted index space is cut into contiguous **blocks** of
   ``block_rows`` rows (default :data:`DEFAULT_BLOCK_ROWS`).
3. Each epoch the block ORDER is shuffled with an epoch-derived seed
   that every worker computes identically, then sharded
   ``blocks[worker_id::num_workers]`` so each worker owns a disjoint
   set of blocks. Union over workers = every block exactly once =
   every row exactly once (pinned by
   ``tests/training/test_block_shuffle.py``).
4. A worker materializes ``window_blocks`` blocks at a time with
   **one contiguous slice per flat array** (``arr[lo:hi]``) — the
   sequential read this whole module exists for — and then emits that
   window's rows in a shuffled order. Windowing across more than one
   block means consecutive emitted rows come from *different* regions
   of the store, which keeps a batch from being entirely one span of
   one self-play game.

Per-row dicts are built from the in-RAM window, in the same shape and
dtypes :meth:`StructuredDataset.__getitem__` returns, so
:func:`~mtg_bot.training.structured_dataset.structured_collate` and
the model are untouched.

Mixing
======

Block shuffling is NOT a uniform shuffle. Rows in one batch are drawn
from ``window_blocks`` randomly-placed regions of ~``block_rows`` rows
each, rather than from the whole split. At the default 65,536 rows ×
2 blocks that is ~131k candidate rows per batch (vs 6.6M) — plenty of
decorrelation for SGD given that neighbouring rows are *different
decision points of different games* only when the store is itself
built from many interleaved files, which it is (one npz per game,
concatenated in discovery order). The knob exists precisely so a
caller who cares can trade memory for mixing.

Memory
======

A worker holds ``window_blocks`` blocks of raw rows at once:

    bytes ≈ window_blocks × block_rows × (
        avg_seq_len × (2 + 4·N_EMB + 4·N_SCALAR)   # token columns
        + 4·ACTION_VOCAB + 1·ACTION_VOCAB + 5      # policy/mask/etc
    )

At the production shape (~45 tokens/row, 517 actions) that is roughly
270 MB per block, so the default 2-block window costs ~540 MB per
worker. Shrink ``block_rows`` if that is too much; a smaller block
still beats row shuffling as long as it is large relative to a batch.

Degenerate subsets
==================

A block's contiguous read spans ``rows[-1] - rows[0] + 1`` storage
rows, which is larger than the block when the subset has holes (the
val split's rows sit between train rows). At a 10% val split the
over-read is ~11% and is still one sequential read, so it wins.
A *pathological* subset (say 100 rows spread over 6M) would try to
read the whole store for one block, so a block whose span exceeds
:data:`SPAN_BLOWUP_FACTOR` × its row count falls back to per-row reads
for that block and logs it. That is a memory-safety bound, not a
silent correctness fallback: the rows emitted are identical either
way.
"""

from __future__ import annotations

import logging
from typing import Any, Iterator, Optional, Sequence

import numpy as np
import torch
from torch.utils.data import IterableDataset

_log = logging.getLogger(__name__)


DEFAULT_BLOCK_ROWS = 65_536
"""Rows per contiguous block. At the production row size (~1.4 KB of
token bytes + 2.6 KB of policy/mask bytes per row) one block is a
~270 MB sequential read — big enough to amortize a seek to
irrelevance, small enough that a 2-block window fits comfortably in a
worker."""

DEFAULT_WINDOW_BLOCKS = 2
"""Blocks materialized (and shuffled together) at a time. 1 = strict
per-block shuffling; higher values mix across more of the store at a
proportional memory cost."""

DEFAULT_RAM_FRACTION = 0.5
"""``auto`` flips to block mode once the store exceeds this fraction
of *available* RAM. Below it the page cache can hold the whole store
and row shuffling costs nothing after the first epoch."""

SPAN_BLOWUP_FACTOR = 4
"""A block whose storage span exceeds this multiple of its row count
is read row-by-row instead of as one slice (see module docstring)."""

SHUFFLE_MODES = ("auto", "row", "block")


# ---------------------------------------------------------------------
# Dataset introspection
# ---------------------------------------------------------------------

_FLAT_ATTRS = (
    "_row_offsets",
    "_token_type_flat",
    "_token_emb_ids_flat",
    "_token_scalars_flat",
    "_outcomes",
    "_policy_targets",
    "_action_masks",
    "_has_policy",
)


def unwrap_subset(dataset: Any) -> tuple[Any, np.ndarray]:
    """Return ``(base_dataset, indices)`` for a ``Subset`` or a plain
    dataset.

    ``indices`` is an int64 ndarray of base-dataset row ids, NOT
    sorted (that happens in :class:`BlockShuffleDataset`). A plain
    dataset yields ``arange(len(dataset))``.
    """
    base = getattr(dataset, "dataset", None)
    idx = getattr(dataset, "indices", None)
    if base is not None and idx is not None:
        indices = np.asarray(idx, dtype=np.int64)
        # Nested Subsets (Subset(Subset(ds))) compose by indexing.
        inner_base, inner_idx = unwrap_subset(base)
        if inner_base is not base:
            indices = inner_idx[indices]
            base = inner_base
        return base, indices
    return dataset, np.arange(len(dataset), dtype=np.int64)


def supports_block_shuffle(dataset: Any) -> bool:
    """True when ``dataset`` (or the dataset a ``Subset`` wraps) is a
    flat memmap-backed :class:`StructuredDataset`."""
    base, _ = unwrap_subset(dataset)
    return all(getattr(base, a, None) is not None for a in _FLAT_ATTRS)


def store_nbytes(dataset: Any) -> Optional[int]:
    """Total on-disk byte size of the flat store behind ``dataset``,
    or ``None`` when ``dataset`` isn't flat-store backed.

    Counts the WHOLE store, not just the subset's share — the page
    cache is shared with the val loader and with any other reader, so
    the whole store is what has to fit.
    """
    base, _ = unwrap_subset(dataset)
    total = 0
    for attr in _FLAT_ATTRS:
        arr = getattr(base, attr, None)
        if arr is None:
            return None
        total += int(arr.nbytes)
    return total


def resolve_shuffle_mode(
    mode: str,
    dataset: Any,
    *,
    ram_fraction: float = DEFAULT_RAM_FRACTION,
) -> str:
    """Resolve ``"auto"`` to ``"row"`` or ``"block"``.

    ``auto`` picks ``block`` when the flat store is larger than
    ``ram_fraction`` × available RAM (``psutil``), i.e. exactly when
    random per-row access stops being served from the page cache.
    Without ``psutil`` installed there is no way to know, so a
    flat-store dataset gets ``block`` unconditionally — block mode is
    never *worse* for I/O, it only costs the window's RAM and some
    shuffle entropy.

    ``row`` / ``block`` are returned as-is; ``block`` on a dataset
    that has no flat store raises rather than silently degrading.
    """
    if mode not in SHUFFLE_MODES:
        raise ValueError(
            f"shuffle_mode must be one of {SHUFFLE_MODES}; got {mode!r}"
        )
    if mode == "row":
        return "row"
    if mode == "block":
        if not supports_block_shuffle(dataset):
            raise ValueError(
                "shuffle_mode='block' requires a memmap-backed "
                "StructuredDataset (or a Subset of one); got "
                f"{type(unwrap_subset(dataset)[0]).__name__}. Pass "
                "shuffle_mode='row' for other dataset types."
            )
        return "block"
    # auto
    nbytes = store_nbytes(dataset)
    if nbytes is None:
        return "row"
    try:
        import psutil
    except ImportError:  # pragma: no cover - psutil is a hard dep here
        _log.info(
            "shuffle_mode=auto: psutil unavailable, defaulting to "
            "block shuffling (%.1f GB store)", nbytes / 1024 ** 3,
        )
        return "block"
    available = int(psutil.virtual_memory().available)
    budget = ram_fraction * available
    chosen = "block" if nbytes > budget else "row"
    _log.info(
        "shuffle_mode=auto -> %s (store %.2f GB vs %.0f%% of %.2f GB "
        "available RAM = %.2f GB budget)",
        chosen, nbytes / 1024 ** 3, 100 * ram_fraction,
        available / 1024 ** 3, budget / 1024 ** 3,
    )
    return chosen


# ---------------------------------------------------------------------
# One materialized window of rows
# ---------------------------------------------------------------------


class _RowBlock:
    """One contiguous storage span read into RAM.

    ``rows`` is a sorted ascending array of base-dataset row ids. The
    constructor issues ONE slice per flat array covering
    ``[rows[0], rows[-1] + 1)``; :meth:`item` then serves any row in
    that span with no further disk access.
    """

    __slots__ = (
        "_lo", "_offsets", "_tt", "_emb", "_sca",
        "_outcomes", "_policy", "_mask", "_has_policy",
        "_dataset", "nbytes", "span", "n_rows",
    )

    def __init__(self, dataset: Any, rows: np.ndarray) -> None:
        lo = int(rows[0])
        hi = int(rows[-1]) + 1
        self._lo = lo
        self.n_rows = int(rows.shape[0])
        self.span = hi - lo
        if self.span > max(SPAN_BLOWUP_FACTOR * self.n_rows, 1):
            # Degenerate subset — a single slice would pull in orders
            # of magnitude more rows than the block needs. Serve the
            # block from the dataset row-by-row instead. Identical
            # rows, just without the sequential-read win.
            _log.warning(
                "block_shuffle: block of %d rows spans %d storage "
                "rows (>%dx); reading row-by-row instead of as one "
                "slice.", self.n_rows, self.span, SPAN_BLOWUP_FACTOR,
            )
            self._dataset = dataset
            self._offsets = None
            self.nbytes = 0
            return
        self._dataset = None
        # --- the sequential reads --------------------------------
        # ``np.array(...)`` and NOT ``np.asarray(...)``: a memmap is
        # an ndarray subclass, so ``asarray`` hands back the mapped
        # VIEW untouched and not one byte is read. The whole point is
        # to fault the block in as one sequential pass, so the copy
        # has to be forced. (Measured cold on an NVMe under load:
        # ~570 MB/s for this sequential materialization vs ~15 MB/s
        # for the same bytes reached by per-row random faults.)
        row_off = np.array(dataset._row_offsets[lo:hi + 1])
        t0 = int(row_off[0])
        t1 = int(row_off[-1])
        self._offsets = (row_off - t0).astype(np.int64, copy=False)
        self._tt = np.array(dataset._token_type_flat[t0:t1])
        self._emb = np.array(dataset._token_emb_ids_flat[t0:t1])
        self._sca = np.array(dataset._token_scalars_flat[t0:t1])
        self._outcomes = np.array(dataset._outcomes[lo:hi])
        self._policy = np.array(dataset._policy_targets[lo:hi])
        self._mask = np.array(dataset._action_masks[lo:hi])
        self._has_policy = np.array(dataset._has_policy[lo:hi])
        self.nbytes = int(
            self._tt.nbytes + self._emb.nbytes + self._sca.nbytes
            + self._outcomes.nbytes + self._policy.nbytes
            + self._mask.nbytes + self._has_policy.nbytes
        )

    def item(self, idx: int) -> dict[str, torch.Tensor]:
        """Return row ``idx`` (a base-dataset row id inside this
        block's span) in :meth:`StructuredDataset.__getitem__`'s exact
        shape and dtypes."""
        if self._offsets is None:  # degenerate-span fallback
            return self._dataset[int(idx)]
        j = int(idx) - self._lo
        start = int(self._offsets[j])
        end = int(self._offsets[j + 1])
        return {
            "token_type": torch.from_numpy(
                self._tt[start:end].astype(np.int64)
            ),
            "token_emb_ids": torch.from_numpy(
                self._emb[start:end].astype(np.int64)
            ),
            "token_scalars": torch.from_numpy(
                np.array(self._sca[start:end])
            ),
            "attention_mask": torch.ones(end - start, dtype=torch.bool),
            "outcome": torch.tensor(
                float(self._outcomes[j]), dtype=torch.float32,
            ),
            "policy_target": torch.from_numpy(
                np.array(self._policy[j])
            ),
            "action_mask": torch.from_numpy(np.array(self._mask[j])),
            "has_policy": torch.tensor(
                bool(self._has_policy[j]), dtype=torch.bool,
            ),
        }


# ---------------------------------------------------------------------
# The wrapper
# ---------------------------------------------------------------------


class BlockShuffleDataset(IterableDataset):
    """Block-shuffled ``IterableDataset`` view of a flat-store
    dataset (or a ``Subset`` of one). See the module docstring.

    Use it exactly like the ``Subset`` it replaces, minus
    ``shuffle=True`` (illegal on an ``IterableDataset``; this class
    IS the shuffle)::

        loader = DataLoader(
            BlockShuffleDataset(Subset(ds, train_idx), seed=0),
            batch_size=256, shuffle=False, num_workers=4,
            persistent_workers=True, collate_fn=structured_collate,
        )

    Epochs
    ------
    Reshuffling needs a per-epoch nonce every worker agrees on (if
    two workers disagree, their block shards overlap and the epoch
    both duplicates and drops rows). Two independent sources are
    mixed, each of which is constant across workers within an epoch:

    - a per-instance counter bumped once per ``__iter__``, which is
      the live one under ``persistent_workers=True`` (the same worker
      objects are re-iterated each epoch), and
    - torch's per-iterator ``base_seed``, recovered from
      ``get_worker_info().seed - get_worker_info().id``, which is the
      live one under ``persistent_workers=False`` (fresh workers are
      pickled from an un-iterated parent every epoch, so their
      counters would all read 0).

    ``num_workers=0`` uses the counter alone. :meth:`set_epoch` pins
    the counter explicitly (tests, resumable runs).
    """

    def __init__(
        self,
        dataset: Any,
        *,
        block_rows: int = DEFAULT_BLOCK_ROWS,
        window_blocks: int = DEFAULT_WINDOW_BLOCKS,
        seed: int = 0,
    ) -> None:
        if block_rows < 1:
            raise ValueError(f"block_rows must be >= 1; got {block_rows}")
        if window_blocks < 1:
            raise ValueError(
                f"window_blocks must be >= 1; got {window_blocks}"
            )
        base, indices = unwrap_subset(dataset)
        if not supports_block_shuffle(base):
            raise ValueError(
                "BlockShuffleDataset requires a memmap-backed "
                "StructuredDataset (or a Subset of one); got "
                f"{type(base).__name__}"
            )
        self.dataset = base
        # Sorted so a run of positions is a run of storage rows. The
        # row SET is unchanged, which is the whole compatibility
        # contract with the Subset this replaces.
        self.indices = np.sort(np.asarray(indices, dtype=np.int64))
        self.block_rows = int(block_rows)
        self.window_blocks = int(window_blocks)
        self.seed = int(seed)
        self._epoch_counter = 0

    # -- plumbing -------------------------------------------------

    def __len__(self) -> int:
        return int(self.indices.shape[0])

    @property
    def n_blocks(self) -> int:
        n = len(self)
        return (n + self.block_rows - 1) // self.block_rows if n else 0

    def set_epoch(self, epoch: int) -> None:
        """Pin the next ``__iter__``'s epoch counter."""
        self._epoch_counter = int(epoch)

    def block_bounds(self, block_id: int) -> tuple[int, int]:
        """``[start, stop)`` positions into :attr:`indices` for a
        block. The last block is short when ``len(self)`` is not a
        multiple of ``block_rows``."""
        start = block_id * self.block_rows
        stop = min(start + self.block_rows, len(self))
        return start, stop

    # -- ordering -------------------------------------------------

    @staticmethod
    def _worker_context() -> tuple[int, int, Optional[int]]:
        """``(worker_id, num_workers, base_seed)``."""
        info = torch.utils.data.get_worker_info()
        if info is None:
            return 0, 1, None
        return int(info.id), int(info.num_workers), int(info.seed) - int(info.id)

    def epoch_block_order(self, epoch_key: Sequence[int]) -> np.ndarray:
        """Shuffled block ids for an epoch. Identical for every worker
        given the same ``epoch_key``, which is what makes the shards
        disjoint AND exhaustive."""
        rng = np.random.default_rng([self.seed, *epoch_key])
        return rng.permutation(self.n_blocks)

    def windows(
        self,
        epoch_key: Sequence[int],
        worker_id: int = 0,
        num_workers: int = 1,
    ) -> list[tuple[list[np.ndarray], list[tuple[int, int]]]]:
        """Plan one worker's epoch.

        Returns a list of windows; each window is
        ``(block_row_arrays, emit_pairs)`` where ``emit_pairs`` is the
        shuffled ``(block_position, offset_in_block)`` emission order.
        Pure planning — touches no store bytes — so tests can assert
        coverage/uniqueness/determinism without any I/O.
        """
        order = self.epoch_block_order(epoch_key)
        mine = order[worker_id::num_workers]
        out: list[tuple[list[np.ndarray], list[tuple[int, int]]]] = []
        for w_i in range(0, len(mine), self.window_blocks):
            block_ids = mine[w_i:w_i + self.window_blocks]
            blocks = []
            pairs: list[tuple[int, int]] = []
            for b_pos, b_id in enumerate(block_ids):
                start, stop = self.block_bounds(int(b_id))
                rows = self.indices[start:stop]
                if rows.shape[0] == 0:
                    continue
                blocks.append(rows)
                pairs.extend(
                    (len(blocks) - 1, j) for j in range(rows.shape[0])
                )
            if not blocks:
                continue
            rng = np.random.default_rng(
                [self.seed, *epoch_key, worker_id, w_i, 0x5B10CC],
            )
            perm = rng.permutation(len(pairs))
            out.append((blocks, [pairs[int(p)] for p in perm]))
        return out

    def row_order(
        self,
        epoch_key: Sequence[int] = (0,),
        worker_id: int = 0,
        num_workers: int = 1,
    ) -> np.ndarray:
        """The base-dataset row ids one worker emits, in order. The
        test-facing view of :meth:`windows`."""
        out: list[int] = []
        for blocks, pairs in self.windows(
            epoch_key, worker_id, num_workers,
        ):
            out.extend(int(blocks[b][j]) for b, j in pairs)
        return np.asarray(out, dtype=np.int64)

    # -- iteration ------------------------------------------------

    def __iter__(self) -> Iterator[dict[str, torch.Tensor]]:
        worker_id, num_workers, base_seed = self._worker_context()
        epoch = self._epoch_counter
        self._epoch_counter += 1
        epoch_key = (epoch, abs(base_seed) if base_seed is not None else 0)
        for blocks, pairs in self.windows(
            epoch_key, worker_id, num_workers,
        ):
            materialized = [_RowBlock(self.dataset, r) for r in blocks]
            for b_pos, j in pairs:
                yield materialized[b_pos].item(int(blocks[b_pos][j]))
            # Drop the window before reading the next one so peak RSS
            # is one window, not the whole epoch.
            del materialized

    # -- pickling -------------------------------------------------
    #
    # The default ndarray pickle already beats what it replaces: a
    # ``Subset`` ships a Python LIST of row ids (6.6M ints ≈ 250 MB of
    # pickle per worker); ``self.indices`` is a 53 MB int64 buffer.
