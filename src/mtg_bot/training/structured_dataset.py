"""Dataset + collate_fn for ``StructuredModel`` training.

The structured-token npz files written by ``data_gen.save_dataset`` are
already padded *per file* to the file's max sequence length. Stacking
many files for training leaves the per-row variable-length information
intact in the ``structured_attention_mask`` array; this module reads
the file-padded arrays, then re-pads each *batch* to that batch's max
sequence length on the fly. Per-batch padding (rather than global
padding to the dataset max) keeps wasted padding bounded — the seq_len
distribution in EoE self-play is 15..86 with median ~53, so a
20%-sample batch sees ~63 padded slots on average instead of the worst-
case 86.

Public API
==========

- :func:`load_structured_dataset` — discover and concatenate every
  ``*.npz`` under a directory, returning a ``StructuredDataset`` that
  the trainer's :class:`torch.utils.data.DataLoader` can iterate.
- :class:`StructuredDataset` — wraps the concatenated arrays. Each
  ``__getitem__`` returns a dict of per-row tensors trimmed to the
  row's real length (via the attention mask), plus the row's
  ``outcome`` / ``policy_target`` / ``action_mask`` supervision.
- :func:`structured_collate` — pads variable-length per-row sequences
  to the batch max and stacks them into the dict shape that
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
        self._token_type = token_type
        self._token_emb_ids = token_emb_ids
        self._token_scalars = token_scalars
        self._attention_mask = attention_mask
        self._outcomes = outcomes
        self._policy_targets = policy_targets
        self._action_masks = action_masks

    def __len__(self) -> int:
        return int(self._token_type.shape[0])

    def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
        # Slice down to the actual valid sequence length for this row
        # so the collate_fn's per-batch max is computed against real
        # tokens — file-level padding is dropped here.
        mask = self._attention_mask[idx]
        # ``mask`` is a 1-D bool array. The valid prefix is contiguous
        # (the data writer right-pads), so ``mask.sum()`` is the row's
        # true length.
        seq_len = int(mask.sum())
        tt = torch.from_numpy(
            self._token_type[idx, :seq_len].astype(np.int64)
        )
        emb = torch.from_numpy(
            self._token_emb_ids[idx, :seq_len].astype(np.int64)
        )
        sca = torch.from_numpy(
            self._token_scalars[idx, :seq_len].astype(np.float32)
        )
        # Real-token-only mask: all True post-slice.
        am = torch.ones(seq_len, dtype=torch.bool)
        outcome = torch.tensor(
            float(self._outcomes[idx]), dtype=torch.float32,
        )
        policy_target = torch.from_numpy(
            self._policy_targets[idx].astype(np.float32)
        )
        action_mask = torch.from_numpy(self._action_masks[idx].astype(np.bool_))
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
    """Load every ``*.npz`` in ``directory`` that contains the
    four structured-token arrays. Files missing those arrays raise.

    ``max_files`` (default ``None`` = all) caps to the N most recent
    files by mtime. Same semantics as
    :func:`data_gen.load_all_datasets`.

    Each file's per-row sequences may be padded to *that file's* max
    seq_len. To concatenate files of different max_seq_len, we pad
    each file's arrays out to the GLOBAL max_seq_len so the resulting
    arrays are aligned. The dataset's ``__getitem__`` re-slices each
    row to its real length via ``attention_mask.sum()``, so the
    inflated padding here costs only memory at load time — not at
    train time.
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
    # Pull every file, complaining loudly about ones missing the
    # structured-token block — the trainer can't operate on those, so
    # silent skipping would mask data-pipeline bugs.
    per_file: list[
        tuple[
            np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray,
            Optional[np.ndarray], Optional[np.ndarray],
        ]
    ] = []
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
        per_file.append((tt, emb_ids, scalars, mask, outcomes,
                         policy_targets, action_masks))
    # Determine global max seq_len across all files.
    max_len = max(int(t[0].shape[1]) for t in per_file) if per_file else 0
    emb_width = per_file[0][1].shape[-1]
    scalar_width = per_file[0][2].shape[-1]
    n_total = sum(int(t[0].shape[0]) for t in per_file)
    # Allocate the concatenated arrays.
    token_type_all = np.zeros((n_total, max_len), dtype=np.int64)
    token_emb_ids_all = np.zeros(
        (n_total, max_len, emb_width), dtype=np.int64,
    )
    token_scalars_all = np.zeros(
        (n_total, max_len, scalar_width), dtype=np.float32,
    )
    attention_mask_all = np.zeros((n_total, max_len), dtype=np.bool_)
    outcomes_all = np.zeros((n_total,), dtype=np.float32)
    policy_targets_all = np.zeros(
        (n_total, ACTION_VOCAB_SIZE), dtype=np.float32,
    )
    action_masks_all = np.zeros(
        (n_total, ACTION_VOCAB_SIZE), dtype=np.bool_,
    )
    row = 0
    for (
        tt, emb_ids, scalars, mask, outcomes,
        policy_targets, action_masks,
    ) in per_file:
        n = int(tt.shape[0])
        L = int(tt.shape[1])
        token_type_all[row:row + n, :L] = tt
        token_emb_ids_all[row:row + n, :L, :] = emb_ids
        token_scalars_all[row:row + n, :L, :] = scalars
        attention_mask_all[row:row + n, :L] = mask
        outcomes_all[row:row + n] = outcomes
        if policy_targets is not None:
            policy_targets_all[row:row + n] = policy_targets
        if action_masks is not None:
            action_masks_all[row:row + n] = action_masks
        row += n
    return StructuredDataset(
        token_type=token_type_all,
        token_emb_ids=token_emb_ids_all,
        token_scalars=token_scalars_all,
        attention_mask=attention_mask_all,
        outcomes=outcomes_all,
        policy_targets=policy_targets_all,
        action_masks=action_masks_all,
    )


__all__ = [
    "StructuredDataset",
    "load_structured_dataset",
    "structured_collate",
]
