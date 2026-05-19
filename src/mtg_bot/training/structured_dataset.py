"""Dataset + collate_fn for ``StructuredModel`` training.

The structured-token npz files written by ``data_gen.save_dataset`` are
already padded *per file* to the file's max sequence length. This
module wraps each file's arrays at their native (per-file) padding —
``__getitem__`` slices each row down to its true length via the
attention mask, and ``structured_collate`` then pads each batch to the
batch's max sequence length.

Per-batch padding (rather than global padding to the dataset max) keeps
wasted padding bounded — the seq_len distribution in EoE self-play is
15..86 with median ~53, so a 20%-sample batch sees ~63 padded slots on
average instead of the worst-case 86.

History note: an earlier implementation eagerly concatenated every
file's arrays into a single contiguous numpy array padded to the
GLOBAL max_seq_len at load time. That allocation is
``O(n_total * GLOBAL_max_len * emb_width * 8 bytes)`` for the int64
``token_emb_ids`` slab alone; with ~7M accumulated samples (eight
iterate cycles' worth) this OOM'd at ~42 GiB on a 64 GiB box because
the global max_len inflated padding ~1.6x over the per-file max.
Keeping each file's array at its native per-file padding eliminates
that inflation entirely.

Public API
==========

- :func:`load_structured_dataset` — discover and wrap every ``*.npz``
  under a directory into a :class:`StructuredDataset` whose internal
  storage is ragged across files.
- :class:`StructuredDataset` — wraps either a single concat'd array
  set (the back-compat positional constructor, used by tests and
  direct callers) or a list of per-file array sets built by
  :meth:`StructuredDataset.from_per_file_arrays` for the
  memory-efficient path.
- :func:`structured_collate` — pads variable-length per-row tensors
  to the batch's max ``seq_len`` and stacks them into the dict
  :meth:`StructuredModel.forward` expects.

This module deliberately does NOT touch ``trainer.py``'s existing
``train_value_network`` path. The sibling ``train_structured_model``
function (in ``trainer.py``) wires this loader to the new model.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import torch
from torch.utils.data import Dataset

from mtg_bot.training.action_encoding import ACTION_VOCAB_SIZE
from mtg_bot.training.data_gen import load_dataset


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
      (padding is dropped at __getitem__ time so the collate_fn only
      sees real tokens; this keeps the per-batch max accurate.)
    - ``outcome``         ``FloatTensor(scalar)`` — in ``{-1, 0, +1}``
    - ``policy_target``   ``FloatTensor(action_vocab_size,)`` — visit
      distribution; all-zero if the row carries no policy supervision.
    - ``action_mask``     ``BoolTensor(action_vocab_size,)`` — True
      for legal slots; all-False if no supervision.
    - ``has_policy``      ``BoolTensor(scalar)`` — True iff
      ``policy_target.sum() > 0.5``.

    The arrays are kept on CPU; the trainer is responsible for moving
    each batch to its target device after collation. Per-row slicing
    via the attention mask happens at ``__getitem__`` time so the
    collate's per-batch max is the tightest possible bound.

    **Internal storage.** The dataset holds a *list of per-file
    arrays* — one entry per source npz file — so files with very
    different max sequence lengths don't pay the global-max padding
    tax. The legacy positional constructor (which takes seven single
    arrays) stores its arrays as a one-file list; the
    :meth:`from_per_file_arrays` classmethod accepts pre-split lists
    directly. ``__getitem__`` binary-searches the cumulative row-count
    offsets to map a global index to (file_idx, local_row_idx).
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
        self._init_per_file(
            [token_type], [token_emb_ids], [token_scalars],
            [attention_mask], [outcomes], [policy_targets], [action_masks],
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
    ) -> "StructuredDataset":
        """Build a dataset over a list of per-file arrays without
        global-max re-padding. Each list entry holds one source file's
        arrays at the file's native ``max_seq_len`` padding; files may
        have different ``max_seq_len`` values. Rows are sliced down to
        their real length at ``__getitem__`` time."""
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
        obj = cls.__new__(cls)
        obj._init_per_file(
            token_type_per_file,
            token_emb_ids_per_file,
            token_scalars_per_file,
            attention_mask_per_file,
            outcomes_per_file,
            policy_targets_per_file,
            action_masks_per_file,
        )
        return obj

    def _init_per_file(
        self,
        token_type_per_file: list[np.ndarray],
        token_emb_ids_per_file: list[np.ndarray],
        token_scalars_per_file: list[np.ndarray],
        attention_mask_per_file: list[np.ndarray],
        outcomes_per_file: list[np.ndarray],
        policy_targets_per_file: list[np.ndarray],
        action_masks_per_file: list[np.ndarray],
    ) -> None:
        self._token_type = token_type_per_file
        self._token_emb_ids = token_emb_ids_per_file
        self._token_scalars = token_scalars_per_file
        self._attention_mask = attention_mask_per_file
        self._outcomes = outcomes_per_file
        self._policy_targets = policy_targets_per_file
        self._action_masks = action_masks_per_file
        # ``_file_offsets[i]`` = cumulative row count BEFORE file i;
        # ``_file_offsets[-1]`` = total row count.
        # ``__getitem__`` uses
        # ``np.searchsorted(_file_offsets, idx, side='right') - 1`` to
        # map a global row index to its file index. ``side='right'``
        # naturally walks past zero-row files (whose offsets equal the
        # previous file's offset), so no extra empty-file handling is
        # needed.
        row_counts = [int(a.shape[0]) for a in token_type_per_file]
        self._file_offsets = np.concatenate(
            ([0], np.cumsum(row_counts)),
        ).astype(np.int64)
        self._n_total = int(self._file_offsets[-1])

    def __len__(self) -> int:
        return self._n_total

    def _locate(self, idx: int) -> tuple[int, int]:
        """Map a global row index to ``(file_idx, local_row_idx)``."""
        if idx < 0 or idx >= self._n_total:
            raise IndexError(
                f"index {idx} out of range for dataset of length "
                f"{self._n_total}"
            )
        file_idx = int(
            np.searchsorted(self._file_offsets, idx, side="right") - 1
        )
        local_idx = idx - int(self._file_offsets[file_idx])
        return file_idx, local_idx

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        # Slice down to the actual valid sequence length for this row
        # so the collate_fn's per-batch max is computed against real
        # tokens — file-level padding is dropped here.
        file_idx, local = self._locate(idx)
        mask = self._attention_mask[file_idx][local]
        # ``mask`` is a 1-D bool array. The valid prefix is contiguous
        # (the data writer right-pads), so ``mask.sum()`` is the row's
        # true length.
        seq_len = int(mask.sum())
        tt = torch.from_numpy(
            self._token_type[file_idx][local, :seq_len].astype(np.int64)
        )
        emb = torch.from_numpy(
            self._token_emb_ids[file_idx][local, :seq_len, :].astype(np.int64)
        )
        sca = torch.from_numpy(
            self._token_scalars[file_idx][local, :seq_len, :].astype(np.float32)
        )
        # Real-token-only mask: all True post-slice.
        am = torch.ones(seq_len, dtype=torch.bool)
        outcome = torch.tensor(
            float(self._outcomes[file_idx][local]), dtype=torch.float32,
        )
        policy_target = torch.from_numpy(
            self._policy_targets[file_idx][local].astype(np.float32)
        )
        action_mask = torch.from_numpy(
            self._action_masks[file_idx][local].astype(np.bool_)
        )
        has_policy = torch.tensor(
            bool(policy_target.sum().item() > 0.5), dtype=torch.bool,
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
    # Bump max_len up to 1 even when every row has zero real tokens so
    # the model sees at least one slot (its [CLS] gets prepended on top
    # anyway, but the empty-key edge case is still cheaper to avoid).
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

    The returned dataset stores each file's arrays at the file's
    native per-file ``max_seq_len`` — no global-max re-padding, no
    giant single concatenated allocation. ``__getitem__`` re-slices
    each row to its real length via ``attention_mask.sum()`` (same
    contract as before).
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
    token_type_pf: list[np.ndarray] = []
    token_emb_ids_pf: list[np.ndarray] = []
    token_scalars_pf: list[np.ndarray] = []
    attention_mask_pf: list[np.ndarray] = []
    outcomes_pf: list[np.ndarray] = []
    policy_targets_pf: list[np.ndarray] = []
    action_masks_pf: list[np.ndarray] = []
    # Pull every file, complaining loudly about ones missing the
    # structured-token block — the trainer can't operate on those, so
    # silent skipping would mask data-pipeline bugs.
    for path in paths:
        (
            features, outcomes, policy_targets, action_masks,
            tt, emb_ids, scalars, mask,
        ) = load_dataset(path, with_policy=True, with_structured=True)
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
        # carries no policy supervision so the dataset's per-file
        # shape contract stays uniform. Old value-only data falls
        # back to all-zero policy_targets + action_masks, identical
        # to the legacy global-array zero-fill semantics.
        if policy_targets is None:
            policy_targets = np.zeros(
                (n_rows, ACTION_VOCAB_SIZE), dtype=np.float32,
            )
        if action_masks is None:
            action_masks = np.zeros(
                (n_rows, ACTION_VOCAB_SIZE), dtype=np.bool_,
            )
        token_type_pf.append(tt)
        token_emb_ids_pf.append(emb_ids)
        token_scalars_pf.append(scalars)
        attention_mask_pf.append(mask)
        outcomes_pf.append(outcomes)
        policy_targets_pf.append(policy_targets)
        action_masks_pf.append(action_masks)
    return StructuredDataset.from_per_file_arrays(
        token_type_per_file=token_type_pf,
        token_emb_ids_per_file=token_emb_ids_pf,
        token_scalars_per_file=token_scalars_pf,
        attention_mask_per_file=attention_mask_pf,
        outcomes_per_file=outcomes_pf,
        policy_targets_per_file=policy_targets_pf,
        action_masks_per_file=action_masks_pf,
    )


__all__ = [
    "StructuredDataset",
    "load_structured_dataset",
    "structured_collate",
]
