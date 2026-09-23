"""Dataset + collate_fn for ``StructuredModel`` training.

The structured-token npz files written by ``data_gen.save_dataset`` are
padded *per file* to the file's max sequence length. At train time
we don't want to pay for any of that padding: the trainer's
``DataLoader`` calls ``__getitem__`` millions of times per epoch and
the per-row Python overhead dominates GPU compute on a small NN
trunk.

This module flattens every npz's padded tokens into a single packed
"flat" storage indexed by per-row ``row_offsets``:

- ``_token_type_flat``      shape (total_real_tokens,) int64
- ``_token_emb_ids_flat``   shape (total_real_tokens, N_EMB_FIELDS) int64
- ``_token_scalars_flat``   shape (total_real_tokens, N_SCALAR_FIELDS) float32
- ``_row_offsets``          shape (n_total + 1,) int64 — cumulative
                            real-token count; ``_row_offsets[i+1] -
                            _row_offsets[i]`` is row i's sequence
                            length, ``_token_type_flat[start:end]``
                            is row i's real tokens with NO padding.

``__getitem__(idx)`` becomes a single numpy slice + ``torch.from_numpy``
per array — no ``.astype()`` copies, no per-row ``.sum()`` to recompute
the sequence length, no Python-level list indexing.

History note: an earlier eager-concat-with-global-max-padding loader
OOM'd at ~42 GiB on the iter_016 dataset (1701 files, 7M samples).
A first refactor switched to per-file ragged storage (one ndarray per
source npz, padded to that file's local max_len) which fit in memory
but introduced enough Python overhead per ``__getitem__`` —
``np.searchsorted`` to map global idx -> file_idx, list indexing into
the per-file arrays, ``.astype`` casts on every row — that an RTX 5090
ran at <10% utilization waiting on the dataloader. The current flat
storage is BOTH smaller (no per-file padding) AND faster (single
contiguous slice per array).

Public API
==========

- :func:`load_structured_dataset` — discover every ``*.npz`` under a
  directory, flatten each file's real tokens, and return a
  :class:`StructuredDataset` ready for the trainer's ``DataLoader``.
- :class:`StructuredDataset` — wraps the packed-flat storage. The
  legacy single-array constructor (used by tests + direct callers)
  still accepts file-padded inputs and flattens them at construction
  time. The :meth:`from_per_file_arrays` and
  :meth:`from_flat_arrays` classmethods cover the other ingest paths.
- :func:`structured_collate` — pads variable-length per-row tensors
  to the batch's max ``seq_len`` and stacks them into the dict
  :meth:`StructuredModel.forward` expects.

This module deliberately does NOT touch ``trainer.py``'s existing
``train_value_network`` path. The sibling ``train_structured_model``
function (in ``trainer.py``) wires this loader to the new model.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np
import torch
from torch.utils.data import Dataset

from mtg_bot.training.action_encoding import ACTION_VOCAB_SIZE
from mtg_bot.training.data_gen import file_group_ids, load_dataset

_log = logging.getLogger(__name__)


_STRUCT_NPZ_KEYS = (
    "structured_token_type",
    "structured_token_emb_ids",
    "structured_token_scalars",
    "structured_attention_mask",
)
"""Mirror of ``data_gen._STRUCT_NPZ_KEYS`` to avoid the private import."""


class StructuredDataset(Dataset):
    """Variable-length per-row structured-token dataset.

    Each item is a Python dict with keys:

    - ``token_type``      ``LongTensor(seq_len,)``
    - ``token_emb_ids``   ``LongTensor(seq_len, N_EMB_FIELDS)``
    - ``token_scalars``   ``FloatTensor(seq_len, N_SCALAR_FIELDS)``
    - ``attention_mask``  ``BoolTensor(seq_len,)`` — all True
      (padding is dropped at file-load time so the collate_fn only
      sees real tokens; this keeps the per-batch max accurate.)
    - ``outcome``         ``FloatTensor(scalar)`` — in ``{-1, 0, +1}``
    - ``policy_target``   ``FloatTensor(action_vocab_size,)`` — visit
      distribution; all-zero if the row carries no policy supervision.
    - ``action_mask``     ``BoolTensor(action_vocab_size,)`` — True
      for legal slots; all-False if no supervision.
    - ``has_policy``      ``BoolTensor(scalar)`` — True iff
      ``policy_target.sum() > 0.5``.

    The arrays are kept on CPU; the trainer is responsible for moving
    each batch to its target device after collation.

    **Internal storage.** Token arrays are stored "flat" — every
    npz's real-token rows packed into a single contiguous numpy
    array, with per-row slice bounds given by ``_row_offsets``. This
    eliminates BOTH the per-file padding overhead (saves ~50% memory
    vs file-padded layouts) AND the per-row Python overhead in
    ``__getitem__`` (a single ``arr[start:end]`` + ``torch.from_numpy``
    per array, no ``.astype`` copies, no list indexing).
    """

    def __init__(
        self,
        token_type: np.ndarray,
        token_emb_ids: np.ndarray,
        token_scalars: np.ndarray,
        attention_mask: np.ndarray,
        outcomes: np.ndarray,
        policy_targets: np.ndarray,
        action_masks: np.ndarray,
        group_ids: Optional[np.ndarray] = None,
    ) -> None:
        n = token_type.shape[0]
        if (
            token_emb_ids.shape[0] != n
            or token_scalars.shape[0] != n
            or attention_mask.shape[0] != n
            or outcomes.shape[0] != n
            or policy_targets.shape[0] != n
            or action_masks.shape[0] != n
        ):
            raise ValueError(
                "All structured-dataset arrays must share row count; "
                f"got {token_type.shape[0]} / {token_emb_ids.shape[0]} "
                f"/ {token_scalars.shape[0]} / {attention_mask.shape[0]} "
                f"/ {outcomes.shape[0]} / {policy_targets.shape[0]} "
                f"/ {action_masks.shape[0]}"
            )
        # Flatten the file-padded inputs at construction time so the
        # internal storage matches the ``from_flat_arrays`` shape.
        tt_flat, emb_flat, sca_flat, row_offsets = _flatten_file_padded(
            token_type, token_emb_ids, token_scalars, attention_mask,
        )
        self._init_flat(
            token_type_flat=tt_flat,
            token_emb_ids_flat=emb_flat,
            token_scalars_flat=sca_flat,
            row_offsets=row_offsets,
            outcomes=np.asarray(outcomes, dtype=np.float32),
            policy_targets=np.asarray(policy_targets, dtype=np.float32),
            action_masks=np.asarray(action_masks, dtype=np.bool_),
            group_ids=group_ids,
        )

    @classmethod
    def from_per_file_arrays(
        cls,
        *,
        token_type_per_file: list[np.ndarray],
        token_emb_ids_per_file: list[np.ndarray],
        token_scalars_per_file: list[np.ndarray],
        attention_mask_per_file: list[np.ndarray],
        outcomes_per_file: list[np.ndarray],
        policy_targets_per_file: list[np.ndarray],
        action_masks_per_file: list[np.ndarray],
        group_ids_per_file: Optional[list[np.ndarray]] = None,
    ) -> "StructuredDataset":
        """Build from a list of per-file padded arrays. Each list
        entry holds one source npz's arrays at the file's native
        ``max_seq_len`` padding. Files may have different
        ``max_seq_len`` values; rows are flattened to their real
        length at construction time."""
        n_files = len(token_type_per_file)
        if (
            len(token_emb_ids_per_file) != n_files
            or len(token_scalars_per_file) != n_files
            or len(attention_mask_per_file) != n_files
            or len(outcomes_per_file) != n_files
            or len(policy_targets_per_file) != n_files
            or len(action_masks_per_file) != n_files
        ):
            raise ValueError(
                "All per-file lists must share length; got "
                f"{n_files} / {len(token_emb_ids_per_file)} / "
                f"{len(token_scalars_per_file)} / "
                f"{len(attention_mask_per_file)} / "
                f"{len(outcomes_per_file)} / "
                f"{len(policy_targets_per_file)} / "
                f"{len(action_masks_per_file)}"
            )
        for fi in range(n_files):
            n = token_type_per_file[fi].shape[0]
            if (
                token_emb_ids_per_file[fi].shape[0] != n
                or token_scalars_per_file[fi].shape[0] != n
                or attention_mask_per_file[fi].shape[0] != n
                or outcomes_per_file[fi].shape[0] != n
                or policy_targets_per_file[fi].shape[0] != n
                or action_masks_per_file[fi].shape[0] != n
            ):
                raise ValueError(
                    f"Per-file arrays in file index {fi} must share "
                    "row count; got "
                    f"{token_type_per_file[fi].shape[0]} / "
                    f"{token_emb_ids_per_file[fi].shape[0]} / "
                    f"{token_scalars_per_file[fi].shape[0]} / "
                    f"{attention_mask_per_file[fi].shape[0]} / "
                    f"{outcomes_per_file[fi].shape[0]} / "
                    f"{policy_targets_per_file[fi].shape[0]} / "
                    f"{action_masks_per_file[fi].shape[0]}"
                )
        # Flatten each file's tokens, then concatenate the flat
        # arrays + the per-file row arrays.
        tt_parts: list[np.ndarray] = []
        emb_parts: list[np.ndarray] = []
        sca_parts: list[np.ndarray] = []
        row_len_parts: list[np.ndarray] = []
        for fi in range(n_files):
            tt_f, emb_f, sca_f, row_lens_f = _flatten_one_file(
                token_type_per_file[fi],
                token_emb_ids_per_file[fi],
                token_scalars_per_file[fi],
                attention_mask_per_file[fi],
            )
            tt_parts.append(tt_f)
            emb_parts.append(emb_f)
            sca_parts.append(sca_f)
            row_len_parts.append(row_lens_f)
        if tt_parts:
            tt_flat = np.concatenate(tt_parts)
            emb_flat = np.concatenate(emb_parts)
            sca_flat = np.concatenate(sca_parts)
            row_lens_all = np.concatenate(row_len_parts).astype(np.int64)
            outcomes = np.concatenate(outcomes_per_file).astype(np.float32)
            policy_targets = np.concatenate(
                policy_targets_per_file
            ).astype(np.float32)
            action_masks = np.concatenate(
                action_masks_per_file
            ).astype(np.bool_)
        else:
            # Empty input lists: produce a zero-row dataset.
            tt_flat = np.zeros((0,), dtype=np.int64)
            emb_flat = np.zeros((0, 0), dtype=np.int64)
            sca_flat = np.zeros((0, 0), dtype=np.float32)
            row_lens_all = np.zeros((0,), dtype=np.int64)
            outcomes = np.zeros((0,), dtype=np.float32)
            policy_targets = np.zeros(
                (0, ACTION_VOCAB_SIZE), dtype=np.float32,
            )
            action_masks = np.zeros(
                (0, ACTION_VOCAB_SIZE), dtype=np.bool_,
            )
        row_offsets = np.concatenate(
            ([0], np.cumsum(row_lens_all)),
        ).astype(np.int64)
        group_ids: Optional[np.ndarray] = None
        if group_ids_per_file is not None:
            if len(group_ids_per_file) != n_files:
                raise ValueError(
                    f"group_ids_per_file length {len(group_ids_per_file)} "
                    f"!= number of files {n_files}"
                )
            group_ids = (
                np.concatenate(group_ids_per_file).astype(np.int64)
                if group_ids_per_file else np.zeros((0,), dtype=np.int64)
            )
        obj = cls.__new__(cls)
        obj._init_flat(
            token_type_flat=tt_flat,
            token_emb_ids_flat=emb_flat,
            token_scalars_flat=sca_flat,
            row_offsets=row_offsets,
            outcomes=outcomes,
            policy_targets=policy_targets,
            action_masks=action_masks,
            group_ids=group_ids,
        )
        return obj

    @classmethod
    def from_flat_arrays(
        cls,
        *,
        token_type_flat: np.ndarray,
        token_emb_ids_flat: np.ndarray,
        token_scalars_flat: np.ndarray,
        row_offsets: np.ndarray,
        outcomes: np.ndarray,
        policy_targets: np.ndarray,
        action_masks: np.ndarray,
        group_ids: Optional[np.ndarray] = None,
    ) -> "StructuredDataset":
        """Build directly from pre-flattened arrays. The caller is
        responsible for ensuring ``row_offsets`` is monotone
        non-decreasing, starts at 0, and ends at
        ``token_type_flat.shape[0]``.

        ``group_ids`` (optional, ``(n_rows,)`` int) is the per-row
        game group id the trainer uses for a game-level train/val
        split. ``None`` = every row is its own group (no game
        structure known — only appropriate for synthetic data)."""
        n_total = int(row_offsets.shape[0]) - 1
        if n_total < 0:
            raise ValueError("row_offsets must have length >= 1")
        if int(row_offsets[0]) != 0:
            raise ValueError(
                f"row_offsets must start at 0; got {int(row_offsets[0])}"
            )
        if int(row_offsets[-1]) != int(token_type_flat.shape[0]):
            raise ValueError(
                f"row_offsets[-1] must equal token_type_flat.shape[0]; "
                f"got {int(row_offsets[-1])} vs {int(token_type_flat.shape[0])}"
            )
        if (
            token_emb_ids_flat.shape[0] != token_type_flat.shape[0]
            or token_scalars_flat.shape[0] != token_type_flat.shape[0]
        ):
            raise ValueError(
                "Flat token arrays must share first dimension; got "
                f"{token_type_flat.shape[0]} / "
                f"{token_emb_ids_flat.shape[0]} / "
                f"{token_scalars_flat.shape[0]}"
            )
        if (
            outcomes.shape[0] != n_total
            or policy_targets.shape[0] != n_total
            or action_masks.shape[0] != n_total
        ):
            raise ValueError(
                f"Per-row arrays must share row count {n_total}; got "
                f"{outcomes.shape[0]} / {policy_targets.shape[0]} / "
                f"{action_masks.shape[0]}"
            )
        if group_ids is not None and np.asarray(group_ids).shape[0] != n_total:
            raise ValueError(
                f"group_ids rows {np.asarray(group_ids).shape[0]} != "
                f"row count {n_total}"
            )
        obj = cls.__new__(cls)
        obj._init_flat(
            token_type_flat=token_type_flat,
            token_emb_ids_flat=token_emb_ids_flat,
            token_scalars_flat=token_scalars_flat,
            row_offsets=row_offsets,
            outcomes=outcomes,
            policy_targets=policy_targets,
            action_masks=action_masks,
            group_ids=group_ids,
        )
        return obj

    def _init_flat(
        self,
        *,
        token_type_flat: np.ndarray,
        token_emb_ids_flat: np.ndarray,
        token_scalars_flat: np.ndarray,
        row_offsets: np.ndarray,
        outcomes: np.ndarray,
        policy_targets: np.ndarray,
        action_masks: np.ndarray,
        group_ids: Optional[np.ndarray] = None,
    ) -> None:
        # **Memmap-backed storage.** Write each flat array to a
        # ``.npy`` file in a temp directory, then ``mmap_mode='r'``
        # reopens them so the dataset object itself holds only file
        # paths + tiny header bytes. This is the storage layout that
        # works with DataLoader workers on Windows: pickling the
        # dataset to a worker sends just the directory path; the
        # worker re-opens the memmaps and the OS page cache shares
        # the data across all readers. (``torch.Tensor.share_memory_()``
        # was tried first but doesn't shrink the raw pickle —
        # see commit history.)
        #
        # Memory ceiling: tracks only what's actively page-cached,
        # not the full 30 GiB flat storage. The 7M-sample dataset
        # works with ``num_workers=4`` because each worker mmaps the
        # same files (no per-worker copy in the pipe).
        # Pre-compute has_policy once so each ``__getitem__`` avoids
        # a per-row ``.sum()`` over the 517-wide policy vector.
        has_policy = (
            np.ascontiguousarray(policy_targets, dtype=np.float32).sum(
                axis=1
            )
            > 0.5
        ).astype(np.bool_)

        # Owned temp directory: cleaned up automatically when the
        # ``StructuredDataset`` (in the parent process) is garbage-
        # collected. ``__setstate__`` (in DataLoader workers) does
        # NOT own the directory — workers just re-open the memmaps.
        # ``ignore_cleanup_errors=True`` is required on Windows
        # because numpy memmap file handles are released lazily on
        # GC; a stray PermissionError at temp-dir teardown is a
        # cleanup nuisance, not a real failure (the OS reclaims the
        # files on process exit even if cleanup fails).
        self._tempdir: Optional[tempfile.TemporaryDirectory] = (
            tempfile.TemporaryDirectory(
                prefix="mtg_bot_structured_dataset_",
                ignore_cleanup_errors=True,
            )
        )
        memmap_dir = Path(self._tempdir.name)
        # Save each array as a separate ``.npy`` file. ``.npy`` is
        # the simplest format that supports ``mmap_mode='r'`` — it
        # writes a small header followed by the contiguous data
        # block.
        np.save(
            memmap_dir / "token_type_flat.npy",
            np.ascontiguousarray(token_type_flat, dtype=np.int64),
        )
        np.save(
            memmap_dir / "token_emb_ids_flat.npy",
            np.ascontiguousarray(token_emb_ids_flat, dtype=np.int64),
        )
        np.save(
            memmap_dir / "token_scalars_flat.npy",
            np.ascontiguousarray(token_scalars_flat, dtype=np.float32),
        )
        np.save(
            memmap_dir / "row_offsets.npy",
            np.ascontiguousarray(row_offsets, dtype=np.int64),
        )
        np.save(
            memmap_dir / "outcomes.npy",
            np.ascontiguousarray(outcomes, dtype=np.float32),
        )
        np.save(
            memmap_dir / "policy_targets.npy",
            np.ascontiguousarray(policy_targets, dtype=np.float32),
        )
        np.save(
            memmap_dir / "action_masks.npy",
            np.ascontiguousarray(action_masks, dtype=np.bool_),
        )
        np.save(
            memmap_dir / "has_policy.npy",
            has_policy,
        )
        # Per-row game group id for the trainer's game-level split.
        # Default (no game structure known) = one group per row.
        n_rows_total = int(row_offsets.shape[0]) - 1
        if group_ids is None:
            group_ids_arr = np.arange(n_rows_total, dtype=np.int64)
        else:
            group_ids_arr = np.ascontiguousarray(group_ids, dtype=np.int64)
            if group_ids_arr.shape[0] != n_rows_total:
                raise ValueError(
                    f"group_ids rows {group_ids_arr.shape[0]} != "
                    f"row count {n_rows_total}"
                )
        np.save(memmap_dir / "group_ids.npy", group_ids_arr)
        self._memmap_dir = str(memmap_dir)
        self._open_memmaps()

    @property
    def group_ids(self) -> np.ndarray:
        """``(len(self),)`` int64 per-row game group ids. Rows that
        share a value came from the same self-play game and must land
        on the same side of the train/val split (see
        ``trainer.grouped_train_val_split``)."""
        return np.asarray(self._group_ids)

    def _open_memmaps(self) -> None:
        """Open the on-disk ``.npy`` files as read-only memmaps.

        Called from ``_init_flat`` in the parent process and from
        ``__setstate__`` in each DataLoader worker. Each call opens
        new file handles in the calling process; the underlying file
        pages are shared via the OS page cache.
        """
        d = Path(self._memmap_dir)
        self._token_type_flat = np.load(
            d / "token_type_flat.npy", mmap_mode="r",
        )
        self._token_emb_ids_flat = np.load(
            d / "token_emb_ids_flat.npy", mmap_mode="r",
        )
        self._token_scalars_flat = np.load(
            d / "token_scalars_flat.npy", mmap_mode="r",
        )
        self._row_offsets = np.load(
            d / "row_offsets.npy", mmap_mode="r",
        )
        self._outcomes = np.load(
            d / "outcomes.npy", mmap_mode="r",
        )
        self._policy_targets = np.load(
            d / "policy_targets.npy", mmap_mode="r",
        )
        self._action_masks = np.load(
            d / "action_masks.npy", mmap_mode="r",
        )
        self._has_policy = np.load(
            d / "has_policy.npy", mmap_mode="r",
        )
        self._group_ids = np.load(
            d / "group_ids.npy", mmap_mode="r",
        )
        self._n_total = int(self._row_offsets.shape[0]) - 1

    def __getstate__(self) -> dict:
        # Pickle a minimal state — just the memmap directory path
        # and the row count. The actual data is on disk; workers
        # re-open the memmaps in ``__setstate__``.
        return {
            "_memmap_dir": self._memmap_dir,
            "_n_total": self._n_total,
        }

    def __setstate__(self, state: dict) -> None:
        self._memmap_dir = state["_memmap_dir"]
        # Workers do NOT own the temp directory — only the parent
        # process cleans it up. Setting ``_tempdir`` to None makes
        # this explicit and prevents ``__del__`` from trying to
        # remove files still in use by other processes.
        self._tempdir = None
        self._open_memmaps()
        # ``_n_total`` is also restored by ``_open_memmaps`` (from
        # row_offsets.shape), but assigning from state is a touch
        # cheaper and pins the contract.
        self._n_total = int(state["_n_total"])

    def __len__(self) -> int:
        return self._n_total

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        if idx < 0 or idx >= self._n_total:
            raise IndexError(
                f"index {idx} out of range for dataset of length "
                f"{self._n_total}"
            )
        start = int(self._row_offsets[idx])
        end = int(self._row_offsets[idx + 1])
        seq_len = end - start
        # ``np.array(memmap_slice)`` materializes a writable copy of
        # the slice in the worker process — small (one row's worth
        # of tokens, ~50 entries on average). ``torch.from_numpy``
        # then wraps that copy as a tensor with zero further copy.
        # We can't pass a memmap directly to ``torch.from_numpy``
        # because that would produce a tensor pointing into a
        # read-only mapping, which collate_fn's ``in-place`` writes
        # would fail on.
        tt = torch.from_numpy(np.array(self._token_type_flat[start:end]))
        emb = torch.from_numpy(np.array(self._token_emb_ids_flat[start:end]))
        sca = torch.from_numpy(np.array(self._token_scalars_flat[start:end]))
        am = torch.ones(seq_len, dtype=torch.bool)
        outcome = torch.tensor(
            float(self._outcomes[idx]), dtype=torch.float32,
        )
        policy_target = torch.from_numpy(
            np.array(self._policy_targets[idx]),
        )
        action_mask = torch.from_numpy(
            np.array(self._action_masks[idx]),
        )
        has_policy = torch.tensor(
            bool(self._has_policy[idx]), dtype=torch.bool,
        )
        return {
            "token_type": tt,
            "token_emb_ids": emb,
            "token_scalars": sca,
            "attention_mask": am,
            "outcome": outcome,
            "policy_target": policy_target,
            "action_mask": action_mask,
            "has_policy": has_policy,
        }


def _flatten_one_file(
    token_type: np.ndarray,
    token_emb_ids: np.ndarray,
    token_scalars: np.ndarray,
    attention_mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Flatten one file's padded token arrays into packed real-token
    arrays + a row-length vector.

    Inputs are file-padded:
    - ``token_type`` shape ``(n_rows, file_max_len)``
    - ``token_emb_ids`` shape ``(n_rows, file_max_len, emb_width)``
    - ``token_scalars`` shape ``(n_rows, file_max_len, scalar_width)``
    - ``attention_mask`` shape ``(n_rows, file_max_len)`` (bool)

    Outputs are packed:
    - ``token_type_flat`` shape ``(total_real,)``
    - ``token_emb_ids_flat`` shape ``(total_real, emb_width)``
    - ``token_scalars_flat`` shape ``(total_real, scalar_width)``
    - ``row_lengths`` shape ``(n_rows,)``

    Uses numpy boolean-indexing (``arr[mask]``) for the gather, which
    is the vectorized way to extract real tokens from a 2-D padded
    layout. C-order memory layout guarantees the output rows appear
    in row-major (i.e., file-row) order.
    """
    if attention_mask.dtype != np.bool_:
        attention_mask = attention_mask.astype(np.bool_)
    # ``token_type[mask]`` produces a 1-D array of real tokens in
    # row-major order (numpy boolean-indexing on a 2-D array).
    tt_flat = token_type[attention_mask]
    # For the 3-D arrays, numpy broadcasts the mask across the last
    # axis: ``emb_ids[mask]`` returns shape ``(total_real, emb_width)``.
    emb_flat = token_emb_ids[attention_mask]
    sca_flat = token_scalars[attention_mask]
    # Per-row real length = mask sum along axis 1.
    row_lengths = attention_mask.sum(axis=1).astype(np.int64)
    return tt_flat, emb_flat, sca_flat, row_lengths


def _flatten_file_padded(
    token_type: np.ndarray,
    token_emb_ids: np.ndarray,
    token_scalars: np.ndarray,
    attention_mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Single-file flatten helper that also computes ``row_offsets``.

    Returned tuple is
    ``(token_type_flat, token_emb_ids_flat, token_scalars_flat,
    row_offsets)`` — same shapes as the dataset's internal storage.
    """
    tt_flat, emb_flat, sca_flat, row_lengths = _flatten_one_file(
        token_type, token_emb_ids, token_scalars, attention_mask,
    )
    row_offsets = np.concatenate(
        ([0], np.cumsum(row_lengths)),
    ).astype(np.int64)
    return tt_flat, emb_flat, sca_flat, row_offsets


def structured_collate(
    items: list[dict[str, torch.Tensor]],
) -> dict[str, torch.Tensor]:
    """Pad variable-length per-row tensors to the batch's max
    ``seq_len`` and stack into the dict :meth:`StructuredModel.forward`
    expects.

    The shape contract on the returned dict:

    - ``token_type``      ``LongTensor(B, max_len)``
    - ``token_emb_ids``   ``LongTensor(B, max_len, N_EMB_FIELDS)``
    - ``token_scalars``   ``FloatTensor(B, max_len, N_SCALAR_FIELDS)``
    - ``attention_mask``  ``BoolTensor(B, max_len)``
    - ``outcome``         ``FloatTensor(B,)``
    - ``policy_target``   ``FloatTensor(B, action_vocab_size)``
    - ``action_mask``     ``BoolTensor(B, action_vocab_size)``
    - ``has_policy``      ``BoolTensor(B,)``

    Empty rows (seq_len=0) are tolerated: the row's mask comes back
    all-False. ``StructuredModel`` guards against fully-padded rows
    inside ``forward`` because attention with no valid keys raises NaN
    on some PyTorch versions; the data path filters those rows before
    we get here (rows with no decisions don't produce a sample), so
    the smoke check is "no row in production has seq_len=0" rather
    than a runtime guard inside the collate.
    """
    if not items:
        raise ValueError("structured_collate received an empty batch")
    batch_size = len(items)
    seq_lens = [int(it["token_type"].shape[0]) for it in items]
    max_len = max(seq_lens) if seq_lens else 0
    if max_len == 0:
        max_len = 1
    emb_width = items[0]["token_emb_ids"].shape[-1]
    scalar_width = items[0]["token_scalars"].shape[-1]
    action_vocab = items[0]["policy_target"].shape[-1]

    token_type = torch.zeros((batch_size, max_len), dtype=torch.int64)
    token_emb_ids = torch.zeros(
        (batch_size, max_len, emb_width), dtype=torch.int64,
    )
    token_scalars = torch.zeros(
        (batch_size, max_len, scalar_width), dtype=torch.float32,
    )
    attention_mask = torch.zeros((batch_size, max_len), dtype=torch.bool)
    outcome = torch.zeros((batch_size,), dtype=torch.float32)
    policy_target = torch.zeros(
        (batch_size, action_vocab), dtype=torch.float32,
    )
    action_mask = torch.zeros(
        (batch_size, action_vocab), dtype=torch.bool,
    )
    has_policy = torch.zeros((batch_size,), dtype=torch.bool)
    for i, it in enumerate(items):
        n = int(it["token_type"].shape[0])
        if n > 0:
            token_type[i, :n] = it["token_type"]
            token_emb_ids[i, :n, :] = it["token_emb_ids"]
            token_scalars[i, :n, :] = it["token_scalars"]
            attention_mask[i, :n] = True
        outcome[i] = it["outcome"]
        policy_target[i] = it["policy_target"]
        action_mask[i] = it["action_mask"]
        has_policy[i] = it["has_policy"]
    return {
        "token_type": token_type,
        "token_emb_ids": token_emb_ids,
        "token_scalars": token_scalars,
        "attention_mask": attention_mask,
        "outcome": outcome,
        "policy_target": policy_target,
        "action_mask": action_mask,
        "has_policy": has_policy,
    }


def load_structured_dataset(
    directory: Path,
    *,
    max_files: Optional[int] = None,
) -> StructuredDataset:
    """Load every ``*.npz`` in ``directory`` that contains the four
    structured-token arrays. Files missing those arrays raise.

    ``max_files`` (default ``None`` = all) caps to the N most recent
    files by mtime. Same semantics as
    :func:`data_gen.load_all_datasets`.

    Each file's padded tokens are flattened into a packed real-token
    layout at load time — the returned dataset's ``__getitem__`` is a
    single contiguous slice per array, no per-row ``.astype`` copies,
    no ``np.searchsorted`` lookup, no per-row ``mask.sum()``
    recomputation. See module docstring for the storage layout and
    the history note on why this matters.
    """
    if max_files is not None and max_files <= 0:
        raise ValueError(
            f"max_files must be positive or None; got {max_files}"
        )
    all_paths = list(directory.glob("*.npz"))
    if max_files is not None and all_paths:
        all_paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        kept = all_paths[:max_files]
        paths = sorted(kept)
    else:
        paths = sorted(all_paths)
    if not paths:
        raise FileNotFoundError(
            f"No .npz files in {directory}"
        )
    # Accumulate one file at a time. The per-file padded arrays go
    # out of scope after _flatten_one_file extracts their real
    # tokens, so peak memory tracks (current file's padded + sum of
    # flat parts already emitted) rather than (all files' padded
    # + flat output).
    tt_parts: list[np.ndarray] = []
    emb_parts: list[np.ndarray] = []
    sca_parts: list[np.ndarray] = []
    row_len_parts: list[np.ndarray] = []
    outcomes_parts: list[np.ndarray] = []
    policy_parts: list[np.ndarray] = []
    am_parts: list[np.ndarray] = []
    group_parts: list[np.ndarray] = []
    for file_index, path in enumerate(paths):
        (
            features, outcomes, policy_targets, action_masks,
            tt, emb_ids, scalars, mask, game_ids,
        ) = load_dataset(
            path, with_policy=True, with_structured=True,
            with_game_ids=True,
        )
        if (
            tt is None or emb_ids is None
            or scalars is None or mask is None
        ):
            raise ValueError(
                f"{path}: missing structured-token arrays. The "
                f"structured trainer requires data_gen to be run "
                f"with structured_tokens=True."
            )
        n_rows = int(tt.shape[0])
        # Synthesize per-file policy / action arrays when the file
        # carries no policy supervision so old value-only data falls
        # back to all-zero policy_targets + action_masks (same
        # behavior as the legacy global-array zero-fill).
        if policy_targets is None:
            policy_targets = np.zeros(
                (n_rows, ACTION_VOCAB_SIZE), dtype=np.float32,
            )
        if action_masks is None:
            action_masks = np.zeros(
                (n_rows, ACTION_VOCAB_SIZE), dtype=np.bool_,
            )
        tt_f, emb_f, sca_f, rows_f = _flatten_one_file(
            tt, emb_ids, scalars, mask,
        )
        tt_parts.append(tt_f)
        emb_parts.append(emb_f)
        sca_parts.append(sca_f)
        row_len_parts.append(rows_f)
        outcomes_parts.append(outcomes)
        policy_parts.append(policy_targets)
        am_parts.append(action_masks)
        # Game-level group ids: ``file_index * 1e6 + game_id`` when
        # the file carries ``game_ids``; whole file as one group for
        # legacy files (logged at INFO inside ``file_group_ids``).
        group_parts.append(
            file_group_ids(game_ids, n_rows, file_index, path=path)
        )
    tt_flat = np.concatenate(tt_parts)
    emb_flat = np.concatenate(emb_parts)
    sca_flat = np.concatenate(sca_parts)
    row_lengths_all = np.concatenate(row_len_parts).astype(np.int64)
    row_offsets = np.concatenate(
        ([0], np.cumsum(row_lengths_all)),
    ).astype(np.int64)
    outcomes_all = np.concatenate(outcomes_parts).astype(np.float32)
    policy_all = np.concatenate(policy_parts).astype(np.float32)
    am_all = np.concatenate(am_parts).astype(np.bool_)
    group_all = np.concatenate(group_parts).astype(np.int64)
    _log.info(
        "structured dataset: %d rows across %d files in %d game groups",
        int(group_all.shape[0]), len(paths),
        int(np.unique(group_all).shape[0]),
    )
    return StructuredDataset.from_flat_arrays(
        token_type_flat=tt_flat,
        token_emb_ids_flat=emb_flat,
        token_scalars_flat=sca_flat,
        row_offsets=row_offsets,
        outcomes=outcomes_all,
        policy_targets=policy_all,
        action_masks=am_all,
        group_ids=group_all,
    )


__all__ = [
    "StructuredDataset",
    "load_structured_dataset",
    "structured_collate",
]
