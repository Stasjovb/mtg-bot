"""Tests for the streaming flat-store build in
``mtg_bot.training.structured_dataset``.

The sibling ``test_structured_dataset.py`` covers the dataset's item /
collate contract. This module covers the *storage* layer added when the
loader was made memory-bounded (2026-09-24):

- the streaming two-pass build produces bit-identical tensors to an
  independent naive reference,
- peak process memory during a multi-file load stays proportional to a
  single source file rather than to the whole pool,
- the flat store is deleted deterministically (the old
  ``TemporaryDirectory(ignore_cleanup_errors=True)`` teardown silently
  failed on Windows and leaked 20-50 GB per training run),
- stale stores from crashed runs are swept at load time,
- the opt-in persistent cache reuses an unchanged pool's store.
"""

from __future__ import annotations

import gc
import json
import os
import pickle
import platform
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import pytest
import torch

from mtg_bot.features import FEATURE_DIM
from mtg_bot.training import structured_dataset
from mtg_bot.training.action_encoding import ACTION_VOCAB_SIZE
from mtg_bot.training.data_gen import save_dataset
from mtg_bot.training.structured_dataset import (
    StructuredDataset,
    load_structured_dataset,
    structured_collate,
)
from mtg_bot.training.structured_model import N_EMB_FIELDS, N_SCALAR_FIELDS


# ---------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------


def _make_struct_arrays(
    n_rows: int,
    *,
    seq_lens: list[int] | None = None,
    max_len: int = 6,
    seed: int = 0,
) -> dict[str, np.ndarray]:
    """File-padded structured-token arrays, matching data_gen's
    contract (valid prefix per row, zeros + mask False after)."""
    if seq_lens is None:
        seq_lens = [max_len] * n_rows
    assert len(seq_lens) == n_rows
    rng = np.random.default_rng(seed)
    token_type = np.zeros((n_rows, max_len), dtype=np.int64)
    token_emb_ids = np.zeros((n_rows, max_len, N_EMB_FIELDS), dtype=np.int64)
    token_scalars = np.zeros(
        (n_rows, max_len, N_SCALAR_FIELDS), dtype=np.float32,
    )
    attention_mask = np.zeros((n_rows, max_len), dtype=np.bool_)
    for i, length in enumerate(seq_lens):
        if length > 0:
            token_type[i, :length] = rng.integers(1, 10, size=length)
            token_emb_ids[i, :length, :] = rng.integers(
                0, 5, size=(length, N_EMB_FIELDS),
            )
            token_scalars[i, :length, :] = rng.standard_normal(
                (length, N_SCALAR_FIELDS)
            )
            attention_mask[i, :length] = True
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
    game_ids: np.ndarray | None = None,
    seed: int = 0,
) -> None:
    rng = np.random.default_rng(seed)
    features = rng.standard_normal((n_rows, FEATURE_DIM)).astype(np.float32)
    outcomes = rng.choice(
        np.array([-1.0, 0.0, 1.0], dtype=np.float32), size=n_rows,
    )
    policy_targets = action_masks = None
    if with_policy:
        policy_targets = np.zeros(
            (n_rows, ACTION_VOCAB_SIZE), dtype=np.float32,
        )
        action_masks = np.zeros((n_rows, ACTION_VOCAB_SIZE), dtype=np.bool_)
        for i in range(n_rows):
            if i % 2 == 0:
                policy_targets[i, 0] = 0.6
                policy_targets[i, 1] = 0.4
                action_masks[i, 0] = True
                action_masks[i, 1] = True
    struct = _make_struct_arrays(
        n_rows, seq_lens=seq_lens, max_len=max_len, seed=seed,
    )
    save_dataset(
        features,
        outcomes,
        path,
        policy_targets=policy_targets,
        action_masks=action_masks,
        game_ids=game_ids,
        structured_token_type=struct["structured_token_type"],
        structured_token_emb_ids=struct["structured_token_emb_ids"],
        structured_token_scalars=struct["structured_token_scalars"],
        structured_attention_mask=struct["structured_attention_mask"],
    )


def _write_multi_file_pool(directory: Path) -> None:
    """Three files exercising every ingest branch: ragged per-row
    lengths, differing per-file ``max_len``, a file with no policy
    supervision, a legacy file with no ``game_ids`` key, a file with
    ``game_ids``, and a zero-length row."""
    directory.mkdir(parents=True, exist_ok=True)
    _make_synthetic_npz(
        directory / "a.npz", 4, seq_lens=[3, 1, 5, 0], max_len=5, seed=1,
    )
    _make_synthetic_npz(
        directory / "b.npz", 3, seq_lens=[2, 2, 7], max_len=7,
        with_policy=False, seed=2,
    )
    _make_synthetic_npz(
        directory / "c.npz", 5, seq_lens=[4, 4, 1, 6, 2], max_len=6,
        game_ids=np.array([0, 0, 1, 1, 2], dtype=np.int64), seed=3,
    )


def _naive_reference_rows(directory: Path) -> list[dict]:
    """Independent, deliberately dumb reference implementation.

    Walks the npz files in the same order ``load_structured_dataset``
    does and unpacks each row with a Python loop over the mask. Shares
    no code with the loader beyond numpy itself, so a regression in the
    streaming flat-store build cannot hide behind a shared helper.
    """
    rows: list[dict] = []
    for file_index, path in enumerate(sorted(directory.glob("*.npz"))):
        with np.load(path) as handle:
            keys = set(handle.files)
            token_type = handle["structured_token_type"]
            emb = handle["structured_token_emb_ids"]
            scalars = handle["structured_token_scalars"]
            mask = handle["structured_attention_mask"]
            outcomes = handle["outcomes"]
            policy = (
                handle["policy_targets"] if "policy_targets" in keys else None
            )
            amask = (
                handle["action_masks"] if "action_masks" in keys else None
            )
            gids = handle["game_ids"] if "game_ids" in keys else None
        for i in range(int(token_type.shape[0])):
            keep = [
                j for j in range(int(token_type.shape[1]))
                if bool(mask[i, j])
            ]
            if policy is None:
                pol = np.zeros(ACTION_VOCAB_SIZE, dtype=np.float32)
                act = np.zeros(ACTION_VOCAB_SIZE, dtype=np.bool_)
            else:
                pol = policy[i].astype(np.float32)
                act = amask[i].astype(np.bool_)
            rows.append({
                "token_type": token_type[i][keep].astype(np.int64),
                "token_emb_ids": emb[i][keep].astype(np.int64),
                "token_scalars": scalars[i][keep].astype(np.float32),
                "outcome": np.float32(outcomes[i]),
                "policy_target": pol,
                "action_mask": act,
                "has_policy": bool(pol.sum() > 0.5),
                "group_id": (
                    file_index * 1_000_000
                    + (int(gids[i]) if gids is not None else 0)
                ),
            })
    return rows


# ---------------------------------------------------------------------
# Streaming build parity
# ---------------------------------------------------------------------


def test_streaming_load_matches_naive_reference(tmp_path: Path) -> None:
    _write_multi_file_pool(tmp_path)
    expected = _naive_reference_rows(tmp_path)
    dataset = load_structured_dataset(tmp_path)
    try:
        assert len(dataset) == len(expected)
        for i, ref in enumerate(expected):
            item = dataset[i]
            np.testing.assert_array_equal(
                item["token_type"].numpy(), ref["token_type"],
            )
            np.testing.assert_array_equal(
                item["token_emb_ids"].numpy(), ref["token_emb_ids"],
            )
            np.testing.assert_array_equal(
                item["token_scalars"].numpy(), ref["token_scalars"],
            )
            assert item["attention_mask"].shape[0] == len(ref["token_type"])
            assert bool(item["attention_mask"].all())
            assert float(item["outcome"]) == float(ref["outcome"])
            np.testing.assert_array_equal(
                item["policy_target"].numpy(), ref["policy_target"],
            )
            np.testing.assert_array_equal(
                item["action_mask"].numpy(), ref["action_mask"],
            )
            assert bool(item["has_policy"]) is ref["has_policy"]
        np.testing.assert_array_equal(
            dataset.group_ids,
            np.array([r["group_id"] for r in expected], dtype=np.int64),
        )
        batch = structured_collate([dataset[i] for i in range(len(dataset))])
        max_len = max(len(r["token_type"]) for r in expected)
        assert batch["token_type"].shape == (len(expected), max_len)
        assert batch["token_emb_ids"].shape[-1] == N_EMB_FIELDS
        assert batch["token_scalars"].shape[-1] == N_SCALAR_FIELDS
    finally:
        dataset.close()


def test_streaming_load_matches_reference_under_max_files(
    tmp_path: Path,
) -> None:
    """``max_files`` picks by mtime; the store is still built in
    sorted-path order because ``file_index`` drives the group ids."""
    _write_multi_file_pool(tmp_path)
    now = time.time()
    os.utime(tmp_path / "a.npz", (now - 300, now - 300))
    os.utime(tmp_path / "b.npz", (now - 200, now - 200))
    os.utime(tmp_path / "c.npz", (now - 100, now - 100))
    dataset = load_structured_dataset(tmp_path, max_files=2)
    try:
        (tmp_path / "a.npz").unlink()
        expected = _naive_reference_rows(tmp_path)
        assert len(dataset) == len(expected)
        for i, ref in enumerate(expected):
            np.testing.assert_array_equal(
                dataset[i]["token_type"].numpy(), ref["token_type"],
            )
        np.testing.assert_array_equal(
            dataset.group_ids,
            np.array([r["group_id"] for r in expected], dtype=np.int64),
        )
    finally:
        dataset.close()


@pytest.mark.parametrize("chunk_bytes", [1, 17, 64, 4096])
def test_chunked_decode_matches_naive_reference(
    monkeypatch, tmp_path: Path, chunk_bytes: int,
) -> None:
    """Row-chunked inflation must be invariant to the chunk size —
    including chunks smaller than a single row (clamped to 1 row) and
    chunks that split a file mid-array."""
    _write_multi_file_pool(tmp_path)
    expected = _naive_reference_rows(tmp_path)
    monkeypatch.setattr(structured_dataset, "CHUNK_BYTES", chunk_bytes)
    dataset = load_structured_dataset(tmp_path)
    try:
        assert len(dataset) == len(expected)
        for i, ref in enumerate(expected):
            item = dataset[i]
            np.testing.assert_array_equal(
                item["token_type"].numpy(), ref["token_type"],
            )
            np.testing.assert_array_equal(
                item["token_emb_ids"].numpy(), ref["token_emb_ids"],
            )
            np.testing.assert_array_equal(
                item["token_scalars"].numpy(), ref["token_scalars"],
            )
            np.testing.assert_array_equal(
                item["policy_target"].numpy(), ref["policy_target"],
            )
            np.testing.assert_array_equal(
                item["action_mask"].numpy(), ref["action_mask"],
            )
            assert float(item["outcome"]) == float(ref["outcome"])
            assert bool(item["has_policy"]) is ref["has_policy"]
        np.testing.assert_array_equal(
            dataset.group_ids,
            np.array([r["group_id"] for r in expected], dtype=np.int64),
        )
    finally:
        dataset.close()


def test_iter_member_rows_truncated_member_raises(tmp_path: Path) -> None:
    """A truncated / corrupt npz member must fail loudly rather than
    silently short-filling the store."""
    import io
    import zipfile as _zipfile

    path = tmp_path / "trunc.npz"
    payload = io.BytesIO()
    np.lib.format.write_array(payload, np.arange(64, dtype=np.int64))
    raw = payload.getvalue()
    with _zipfile.ZipFile(path, "w") as zf:
        zf.writestr("arr.npy", raw[: len(raw) - 32])
    with _zipfile.ZipFile(path) as zf:
        with pytest.raises(ValueError, match="unexpected EOF"):
            list(structured_dataset._iter_member_rows(zf, "arr.npy"))


def test_scan_and_plan_agree_with_the_written_store(tmp_path: Path) -> None:
    _write_multi_file_pool(tmp_path)
    paths = sorted(tmp_path.glob("*.npz"))
    scans = [structured_dataset._scan_structured_npz(p) for p in paths]
    plan = structured_dataset._plan_store(scans)
    dataset = load_structured_dataset(tmp_path)
    try:
        assert plan.n_rows == len(dataset)
        assert plan.emb_width == N_EMB_FIELDS
        assert plan.scalar_width == N_SCALAR_FIELDS
        assert plan.policy_width == ACTION_VOCAB_SIZE
        # Pre-allocated token count == the real (unpadded) token total.
        assert plan.n_tokens == sum(
            int(dataset[i]["token_type"].shape[0]) for i in range(len(dataset))
        )
        np.testing.assert_array_equal(
            np.asarray(dataset._row_offsets), plan.row_offsets,
        )
    finally:
        dataset.close()


def test_plan_rejects_mismatched_emb_width(tmp_path: Path) -> None:
    _make_synthetic_npz(tmp_path / "a.npz", 2, seq_lens=[2, 2], max_len=2)
    struct = _make_struct_arrays(2, seq_lens=[2, 2], max_len=2, seed=5)
    struct["structured_token_emb_ids"] = np.zeros(
        (2, 2, N_EMB_FIELDS + 1), dtype=np.int64,
    )
    save_dataset(
        np.zeros((2, FEATURE_DIM), dtype=np.float32),
        np.zeros(2, dtype=np.float32),
        tmp_path / "b.npz",
        structured_token_type=struct["structured_token_type"],
        structured_token_emb_ids=struct["structured_token_emb_ids"],
        structured_token_scalars=struct["structured_token_scalars"],
        structured_attention_mask=struct["structured_attention_mask"],
    )
    with pytest.raises(ValueError, match="token_emb_ids width mismatch"):
        load_structured_dataset(tmp_path)


def test_source_file_rewritten_between_passes_raises(
    monkeypatch, tmp_path: Path,
) -> None:
    """The sizing pass pre-allocates from the attention masks; if a file
    is rewritten before the read pass the store would be silently
    misaligned. Fail loudly instead."""
    _write_multi_file_pool(tmp_path)
    real_scan = structured_dataset._scan_structured_npz

    def _lying_scan(path: Path):
        scan = real_scan(path)
        if path.name == "b.npz":
            scan.row_lengths = scan.row_lengths + 1
            scan.n_tokens = int(scan.row_lengths.sum())
        return scan

    monkeypatch.setattr(
        structured_dataset, "_scan_structured_npz", _lying_scan,
    )
    with pytest.raises(ValueError, match="changed between the sizing pass"):
        load_structured_dataset(tmp_path)


def test_failed_build_removes_the_partial_store(
    monkeypatch, tmp_path: Path,
) -> None:
    _write_multi_file_pool(tmp_path)
    before = set(structured_dataset._OWNED_DIRS)

    def _explode(*args, **kwargs):
        raise RuntimeError("decode exploded")

    monkeypatch.setattr(
        structured_dataset, "_stream_file_into_store", _explode,
    )
    with pytest.raises(RuntimeError, match="decode exploded"):
        load_structured_dataset(tmp_path)
    assert set(structured_dataset._OWNED_DIRS) == before


def _write_raw_npz(path: Path, **arrays) -> None:
    np.savez_compressed(path, **arrays)


def _struct_kwargs(n_rows: int, max_len: int, *, mask_rows: int | None = None):
    if mask_rows is None:
        mask_rows = n_rows
    return {
        "structured_token_type": np.zeros((n_rows, max_len), dtype=np.int64),
        "structured_token_emb_ids": np.zeros(
            (n_rows, max_len, N_EMB_FIELDS), dtype=np.int64,
        ),
        "structured_token_scalars": np.zeros(
            (n_rows, max_len, N_SCALAR_FIELDS), dtype=np.float32,
        ),
        "structured_attention_mask": np.ones(
            (mask_rows, max_len), dtype=np.bool_,
        ),
    }


def test_scan_rejects_mask_row_count_mismatch(tmp_path: Path) -> None:
    kwargs = _struct_kwargs(3, 4, mask_rows=2)
    _write_raw_npz(
        tmp_path / "bad.npz",
        features=np.zeros((3, FEATURE_DIM), dtype=np.float32),
        outcomes=np.zeros(3, dtype=np.float32),
        **kwargs,
    )
    with pytest.raises(ValueError, match="structured_attention_mask rows"):
        load_structured_dataset(tmp_path)


def test_scan_rejects_token_array_row_count_mismatch(tmp_path: Path) -> None:
    kwargs = _struct_kwargs(3, 4)
    kwargs["structured_token_emb_ids"] = np.zeros(
        (2, 4, N_EMB_FIELDS), dtype=np.int64,
    )
    _write_raw_npz(
        tmp_path / "bad.npz",
        features=np.zeros((3, FEATURE_DIM), dtype=np.float32),
        outcomes=np.zeros(3, dtype=np.float32),
        **kwargs,
    )
    with pytest.raises(ValueError, match="disagree on row count"):
        load_structured_dataset(tmp_path)


def test_stream_rejects_outcomes_row_count_mismatch(tmp_path: Path) -> None:
    kwargs = _struct_kwargs(3, 4)
    _write_raw_npz(
        tmp_path / "bad.npz",
        features=np.zeros((3, FEATURE_DIM), dtype=np.float32),
        outcomes=np.zeros(2, dtype=np.float32),
        **kwargs,
    )
    with pytest.raises(ValueError, match="outcomes rows"):
        load_structured_dataset(tmp_path)


def test_pool_with_no_real_tokens_anywhere_loads(tmp_path: Path) -> None:
    """Every row masked out: no file can pin the schema width, so the
    plan falls back to the first file's declared widths."""
    for name in ("a.npz", "b.npz"):
        kwargs = _struct_kwargs(2, 3)
        kwargs["structured_attention_mask"] = np.zeros((2, 3), dtype=np.bool_)
        _write_raw_npz(
            tmp_path / name,
            features=np.zeros((2, FEATURE_DIM), dtype=np.float32),
            outcomes=np.zeros(2, dtype=np.float32),
            **kwargs,
        )
    dataset = load_structured_dataset(tmp_path)
    try:
        assert len(dataset) == 4
        assert dataset.scalar_width == N_SCALAR_FIELDS
        assert int(dataset[0]["token_type"].shape[0]) == 0
        assert not bool(dataset[0]["has_policy"])
    finally:
        dataset.close()


def test_plan_rejects_policy_width_mismatch(tmp_path: Path) -> None:
    for name, width in (("a.npz", 4), ("b.npz", 5)):
        _write_raw_npz(
            tmp_path / name,
            features=np.zeros((2, FEATURE_DIM), dtype=np.float32),
            outcomes=np.zeros(2, dtype=np.float32),
            policy_targets=np.zeros((2, width), dtype=np.float32),
            action_masks=np.zeros((2, width), dtype=np.bool_),
            **_struct_kwargs(2, 3),
        )
    with pytest.raises(ValueError, match="policy_targets width mismatch"):
        load_structured_dataset(tmp_path)


def test_plan_rejects_odd_policy_width_mixed_with_value_only(
    tmp_path: Path,
) -> None:
    """A value-only file gets zero-filled at ACTION_VOCAB_SIZE; if the
    files that DO carry policy use another width there is no single
    correct store width."""
    _write_raw_npz(
        tmp_path / "a.npz",
        features=np.zeros((2, FEATURE_DIM), dtype=np.float32),
        outcomes=np.zeros(2, dtype=np.float32),
        policy_targets=np.zeros((2, 4), dtype=np.float32),
        action_masks=np.zeros((2, 4), dtype=np.bool_),
        **_struct_kwargs(2, 3),
    )
    _write_raw_npz(
        tmp_path / "b.npz",
        features=np.zeros((2, FEATURE_DIM), dtype=np.float32),
        outcomes=np.zeros(2, dtype=np.float32),
        **_struct_kwargs(2, 3),
    )
    with pytest.raises(ValueError, match="does not match ACTION_VOCAB_SIZE"):
        load_structured_dataset(tmp_path)


def test_non_bool_attention_mask_is_coerced(tmp_path: Path) -> None:
    """Older writers stored the mask as uint8; both passes must treat
    it as boolean."""
    kwargs = _struct_kwargs(2, 3)
    kwargs["structured_token_type"] = np.arange(6, dtype=np.int64).reshape(2, 3)
    mask = np.zeros((2, 3), dtype=np.uint8)
    mask[0, :2] = 1
    mask[1, :1] = 1
    kwargs["structured_attention_mask"] = mask
    _write_raw_npz(
        tmp_path / "u8.npz",
        features=np.zeros((2, FEATURE_DIM), dtype=np.float32),
        outcomes=np.zeros(2, dtype=np.float32),
        **kwargs,
    )
    dataset = load_structured_dataset(tmp_path)
    try:
        np.testing.assert_array_equal(
            dataset[0]["token_type"].numpy(), np.array([0, 1]),
        )
        np.testing.assert_array_equal(
            dataset[1]["token_type"].numpy(), np.array([3]),
        )
    finally:
        dataset.close()


def test_npy_v2_headers_are_readable(tmp_path: Path) -> None:
    """``.npy`` format 2.0 (header > 64 KB) needs its own header
    reader in both the sizing and the streaming path."""
    import io
    import zipfile as _zipfile

    arr = np.arange(24, dtype=np.int64).reshape(6, 4)
    buf = io.BytesIO()
    np.lib.format.write_array(buf, arr, version=(2, 0))
    path = tmp_path / "v2.npz"
    with _zipfile.ZipFile(path, "w") as zf:
        zf.writestr("arr.npy", buf.getvalue())
    with _zipfile.ZipFile(path) as zf:
        shape, dtype = structured_dataset._read_member_header(zf, "arr.npy")
        assert shape == (6, 4)
        assert dtype == np.dtype(np.int64)
        chunks = list(
            structured_dataset._iter_member_rows(zf, "arr.npy", chunk_bytes=64)
        )
    rebuilt = np.concatenate([c for _offset, c in chunks])
    np.testing.assert_array_equal(rebuilt, arr)
    assert [offset for offset, _c in chunks] == [0, 2, 4]


def test_cache_publish_race_prefers_the_winner(
    monkeypatch, tmp_path: Path,
) -> None:
    """Two processes can build the same signature concurrently. The
    loser's rename fails; it must adopt the published store and delete
    its own build dir."""
    pool = tmp_path / "pool"
    cache = tmp_path / "cache"
    _write_multi_file_pool(pool)
    winner = load_structured_dataset(pool, cache_dir=cache)
    published = Path(winner._memmap_dir)
    winner.close()

    real_is_complete = structured_dataset._store_is_complete
    calls = {"n": 0}

    def _miss_first(directory, signature):
        calls["n"] += 1
        if calls["n"] == 1:
            return False  # force a rebuild even though the store exists
        return real_is_complete(directory, signature)

    monkeypatch.setattr(structured_dataset, "_store_is_complete", _miss_first)
    loser = load_structured_dataset(pool, cache_dir=cache)
    try:
        assert Path(loser._memmap_dir) == published
        assert [p for p in cache.iterdir() if p.is_dir()] == [published]
    finally:
        loser.close()


# ---------------------------------------------------------------------
# Peak-memory bound
# ---------------------------------------------------------------------


def _process_memory_bytes(proc) -> int:
    """Private (commit-charged) memory where the platform exposes it.

    Windows' ``rss`` is the working set, which *includes* file-backed
    memmap pages — exactly the pages this design deliberately pushes to
    disk — so measuring rss there would punish the fix. ``private`` is
    the Windows PrivateUsage counter; elsewhere fall back to rss.
    """
    info = proc.memory_info()
    return int(getattr(info, "private", info.rss))


class _PeakMemorySampler(threading.Thread):
    def __init__(self, proc, interval: float = 0.002) -> None:
        super().__init__(daemon=True)
        self._proc = proc
        self._interval = interval
        self._stop = threading.Event()
        self.peak = 0

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                self.peak = max(self.peak, _process_memory_bytes(self._proc))
            except Exception:  # noqa: BLE001  # pragma: no cover
                return
            time.sleep(self._interval)

    def stop(self) -> int:
        self._stop.set()
        self.join(timeout=2.0)
        return self.peak


@pytest.mark.slow
def test_peak_memory_is_bounded_by_one_file_not_the_pool(
    tmp_path: Path,
) -> None:
    """Load ~200k rows spread over 40 files and assert peak private
    memory stays near one file's footprint.

    Arithmetic: 40 files x 5,000 rows x max_len 16 tokens. One file's
    decoded arrays are ~6 MB (int64 types + 7 emb ids + 3 scalars +
    mask). The whole flat store is ~130 MB. The pre-change loader held
    every file's packed arrays in RAM, concatenated them (another full
    copy) and then wrote a third copy out, so its peak was >=400 MB on
    this input. The streaming build should stay under ~100 MB; the
    bound below is 220 MB, which passes comfortably for the streaming
    build and fails for any eager rebuild.
    """
    psutil = pytest.importorskip("psutil")
    n_files, rows_per_file, max_len = 40, 5_000, 16
    rng = np.random.default_rng(0)
    seq_lens = rng.integers(1, max_len + 1, size=rows_per_file)
    policy_width = 8  # keep the fixture's disk footprint sane
    for f in range(n_files):
        token_type = np.zeros((rows_per_file, max_len), dtype=np.int64)
        emb = np.zeros((rows_per_file, max_len, N_EMB_FIELDS), dtype=np.int64)
        scalars = np.zeros(
            (rows_per_file, max_len, N_SCALAR_FIELDS), dtype=np.float32,
        )
        mask = np.zeros((rows_per_file, max_len), dtype=np.bool_)
        for i, length in enumerate(seq_lens):
            token_type[i, :length] = (i % 9) + 1
            emb[i, :length, :] = (i % 5)
            scalars[i, :length, :] = np.float32(i % 7)
            mask[i, :length] = True
        np.savez_compressed(
            tmp_path / f"m_{f:03d}.npz",
            features=np.zeros((rows_per_file, FEATURE_DIM), dtype=np.float32),
            outcomes=np.zeros(rows_per_file, dtype=np.float32),
            policy_targets=np.zeros(
                (rows_per_file, policy_width), dtype=np.float32,
            ),
            action_masks=np.zeros(
                (rows_per_file, policy_width), dtype=np.bool_,
            ),
            game_ids=np.arange(rows_per_file, dtype=np.int64) // 100,
            structured_token_type=token_type,
            structured_token_emb_ids=emb,
            structured_token_scalars=scalars,
            structured_attention_mask=mask,
        )
    del token_type, emb, scalars, mask
    gc.collect()

    proc = psutil.Process()
    baseline = _process_memory_bytes(proc)
    sampler = _PeakMemorySampler(proc)
    sampler.start()
    dataset = load_structured_dataset(tmp_path)
    peak = sampler.stop()
    try:
        assert len(dataset) == n_files * rows_per_file
        growth = max(0, peak - baseline)
        per_file_bytes = rows_per_file * max_len * (8 + 8 * N_EMB_FIELDS + 4 * N_SCALAR_FIELDS + 1)
        bound = 220 * 1024 * 1024
        assert growth < bound, (
            f"peak private-memory growth {growth / 1e6:.0f} MB exceeded "
            f"{bound / 1e6:.0f} MB for {n_files} files "
            f"({per_file_bytes / 1e6:.1f} MB decoded per file) — the "
            f"loader is no longer streaming"
        )
    finally:
        dataset.close()


# ---------------------------------------------------------------------
# Deterministic cleanup
# ---------------------------------------------------------------------


def test_flat_store_dir_removed_when_dataset_is_deleted(
    tmp_path: Path,
) -> None:
    _write_multi_file_pool(tmp_path)
    dataset = load_structured_dataset(tmp_path)
    store = Path(dataset._memmap_dir)
    assert store.is_dir()
    assert str(store) in structured_dataset._OWNED_DIRS
    del dataset
    gc.collect()
    assert not store.exists(), (
        "flat store leaked; on Windows this is 20-50 GB per training run"
    )
    assert str(store) not in structured_dataset._OWNED_DIRS


def test_close_is_idempotent(tmp_path: Path) -> None:
    _write_multi_file_pool(tmp_path)
    dataset = load_structured_dataset(tmp_path)
    store = Path(dataset._memmap_dir)
    dataset.close()
    assert not store.exists()
    dataset.close()
    assert not store.exists()


def test_group_ids_survives_close(tmp_path: Path) -> None:
    """The trainer holds ``group_ids`` for the whole run; it must be a
    detached copy, not a view that pins the mapping open."""
    _write_multi_file_pool(tmp_path)
    dataset = load_structured_dataset(tmp_path)
    groups = dataset.group_ids
    store = Path(dataset._memmap_dir)
    dataset.close()
    assert not store.exists()
    assert groups.shape[0] == 12
    assert int(groups[0]) == 0


def test_unpickled_worker_copy_does_not_delete_the_store(
    tmp_path: Path,
) -> None:
    """DataLoader workers re-open the memmaps but never own the dir."""
    _write_multi_file_pool(tmp_path)
    dataset = load_structured_dataset(tmp_path)
    store = Path(dataset._memmap_dir)
    worker = pickle.loads(pickle.dumps(dataset))
    assert worker._owned_dir is None
    np.testing.assert_array_equal(
        worker[0]["token_type"].numpy(), dataset[0]["token_type"].numpy(),
    )
    del worker
    gc.collect()
    assert store.is_dir(), "a worker copy must not delete the parent's store"
    dataset.close()
    assert not store.exists()


def test_legacy_in_ram_constructor_also_cleans_up() -> None:
    struct = _make_struct_arrays(3, seq_lens=[2, 3, 1], max_len=3)
    dataset = StructuredDataset(
        struct["structured_token_type"],
        struct["structured_token_emb_ids"],
        struct["structured_token_scalars"],
        struct["structured_attention_mask"],
        np.zeros(3, dtype=np.float32),
        np.zeros((3, ACTION_VOCAB_SIZE), dtype=np.float32),
        np.zeros((3, ACTION_VOCAB_SIZE), dtype=np.bool_),
    )
    store = Path(dataset._memmap_dir)
    assert store.is_dir()
    dataset.close()
    assert not store.exists()


def test_shutdown_dataloader_workers_is_safe(tmp_path: Path) -> None:
    structured_dataset.shutdown_dataloader_workers(object())

    class _FakeLoader:
        def __init__(self) -> None:
            self.calls = 0
            self._iterator = self

        def _shutdown_workers(self) -> None:
            self.calls += 1

    fake = _FakeLoader()
    structured_dataset.shutdown_dataloader_workers(fake)
    assert fake.calls == 1
    assert fake._iterator is None
    structured_dataset.shutdown_dataloader_workers(fake)
    assert fake.calls == 1


def test_dataloader_workers_release_the_store(tmp_path: Path) -> None:
    """End-to-end: real worker processes map the store, and after the
    trainer's shutdown hook the parent can still delete it."""
    from torch.utils.data import DataLoader

    _write_multi_file_pool(tmp_path)
    dataset = load_structured_dataset(tmp_path)
    store = Path(dataset._memmap_dir)
    loader = DataLoader(
        dataset,
        batch_size=2,
        collate_fn=structured_collate,
        num_workers=1,
        persistent_workers=True,
    )
    seen = sum(int(batch["token_type"].shape[0]) for batch in loader)
    assert seen == len(dataset)
    structured_dataset.shutdown_dataloader_workers(loader)
    del loader
    dataset.close()
    assert not store.exists()


# ---------------------------------------------------------------------
# Stale-store sweep
# ---------------------------------------------------------------------


def test_sweep_removes_only_old_foreign_dirs(tmp_path: Path) -> None:
    prefix = structured_dataset.MEMMAP_DIR_PREFIX
    stale = tmp_path / f"{prefix}stale"
    fresh = tmp_path / f"{prefix}fresh"
    mine = tmp_path / f"{prefix}mine"
    unrelated = tmp_path / "some_other_tempdir"
    for directory in (stale, fresh, mine, unrelated):
        directory.mkdir()
        (directory / "token_type_flat.npy").write_bytes(b"x")
    old = time.time() - 48 * 3600
    os.utime(stale, (old, old))
    os.utime(mine, (old, old))
    os.utime(unrelated, (old, old))
    structured_dataset._OWNED_DIRS.add(str(mine))
    try:
        removed = structured_dataset.sweep_stale_memmap_dirs(
            max_age_hours=24, root=tmp_path,
        )
    finally:
        structured_dataset._OWNED_DIRS.discard(str(mine))
    assert removed == 1
    assert not stale.exists()
    assert fresh.is_dir()
    assert mine.is_dir(), "a store this process owns must never be swept"
    assert unrelated.is_dir()


def test_load_sweeps_stale_dirs(monkeypatch, tmp_path: Path) -> None:
    prefix = structured_dataset.MEMMAP_DIR_PREFIX
    fake_temp = tmp_path / "temproot"
    fake_temp.mkdir()
    stale = fake_temp / f"{prefix}stale"
    stale.mkdir()
    old = time.time() - 48 * 3600
    os.utime(stale, (old, old))
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(fake_temp))
    pool = tmp_path / "pool"
    _write_multi_file_pool(pool)
    dataset = load_structured_dataset(pool)
    assert not stale.exists()
    dataset.close()


def test_load_respects_sweep_opt_out(monkeypatch, tmp_path: Path) -> None:
    prefix = structured_dataset.MEMMAP_DIR_PREFIX
    fake_temp = tmp_path / "temproot"
    fake_temp.mkdir()
    stale = fake_temp / f"{prefix}stale"
    stale.mkdir()
    old = time.time() - 48 * 3600
    os.utime(stale, (old, old))
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(fake_temp))
    pool = tmp_path / "pool"
    _write_multi_file_pool(pool)
    dataset = load_structured_dataset(pool, sweep_stale=False)
    assert stale.is_dir()
    dataset.close()

    monkeypatch.setenv(structured_dataset.SWEEP_ENV, "0")
    assert structured_dataset._sweep_enabled() is False
    dataset = load_structured_dataset(pool)
    assert stale.is_dir()
    dataset.close()
    monkeypatch.setenv(structured_dataset.SWEEP_ENV, "1")
    assert structured_dataset._sweep_enabled() is True


def test_sweep_hours_env_override(monkeypatch, tmp_path: Path) -> None:
    directory = tmp_path / f"{structured_dataset.MEMMAP_DIR_PREFIX}x"
    directory.mkdir()
    old = time.time() - 2 * 3600
    os.utime(directory, (old, old))
    monkeypatch.setenv(structured_dataset.SWEEP_HOURS_ENV, "1")
    assert structured_dataset.sweep_stale_memmap_dirs(root=tmp_path) == 1
    assert not directory.exists()


def test_sweep_hours_env_garbage_falls_back_to_default(
    monkeypatch, tmp_path: Path,
) -> None:
    directory = tmp_path / f"{structured_dataset.MEMMAP_DIR_PREFIX}y"
    directory.mkdir()
    young = time.time() - 0.25 * structured_dataset.DEFAULT_SWEEP_HOURS * 3600
    os.utime(directory, (young, young))
    monkeypatch.setenv(structured_dataset.SWEEP_HOURS_ENV, "not-a-number")
    # Garbage falls back to DEFAULT_SWEEP_HOURS, so a dir a quarter of
    # that age survives.
    assert structured_dataset.sweep_stale_memmap_dirs(root=tmp_path) == 0
    assert directory.is_dir()
    old = time.time() - 4 * structured_dataset.DEFAULT_SWEEP_HOURS * 3600
    os.utime(directory, (old, old))
    assert structured_dataset.sweep_stale_memmap_dirs(root=tmp_path) == 1


def test_sweep_missing_root_is_noop(tmp_path: Path) -> None:
    assert structured_dataset.sweep_stale_memmap_dirs(
        root=tmp_path / "nope",
    ) == 0


# ---------------------------------------------------------------------
# Persistent cache
# ---------------------------------------------------------------------


def test_persistent_cache_reuses_store_and_invalidates_on_change(
    tmp_path: Path,
) -> None:
    pool = tmp_path / "pool"
    cache = tmp_path / "cache"
    _write_multi_file_pool(pool)
    first = load_structured_dataset(pool, cache_dir=cache)
    store = Path(first._memmap_dir)
    assert store.parent == cache
    assert (store / "manifest.json").is_file()
    assert first._owned_dir is None, "cached stores are caller-owned"
    rows = [first[i]["token_type"].numpy().copy() for i in range(len(first))]
    first.close()
    assert store.is_dir(), "close() must not delete a cached store"

    second = load_structured_dataset(pool, cache_dir=cache)
    assert Path(second._memmap_dir) == store
    for i, expected in enumerate(rows):
        np.testing.assert_array_equal(second[i]["token_type"].numpy(), expected)
    second.close()

    _make_synthetic_npz(pool / "d.npz", 2, seq_lens=[1, 2], max_len=2, seed=9)
    third = load_structured_dataset(pool, cache_dir=cache)
    assert Path(third._memmap_dir) != store
    assert len(third) == len(rows) + 2
    third.close()
    assert len([p for p in cache.iterdir() if p.is_dir()]) == 2


def test_persistent_cache_via_env(monkeypatch, tmp_path: Path) -> None:
    pool = tmp_path / "pool"
    cache = tmp_path / "envcache"
    _write_multi_file_pool(pool)
    monkeypatch.setenv(structured_dataset.CACHE_DIR_ENV, str(cache))
    dataset = load_structured_dataset(pool)
    assert Path(dataset._memmap_dir).parent == cache
    dataset.close()


def test_persistent_cache_rejects_stale_or_corrupt_manifest(
    tmp_path: Path,
) -> None:
    pool = tmp_path / "pool"
    cache = tmp_path / "cache"
    _write_multi_file_pool(pool)
    dataset = load_structured_dataset(pool, cache_dir=cache)
    store = Path(dataset._memmap_dir)
    dataset.close()
    manifest = store / "manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    signature = payload["signature"]
    assert structured_dataset._store_is_complete(store, signature)
    assert not structured_dataset._store_is_complete(store, "other-signature")
    payload["version"] = structured_dataset.FLAT_STORE_VERSION + 1
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    assert not structured_dataset._store_is_complete(store, signature)
    manifest.write_text("{not json", encoding="utf-8")
    assert not structured_dataset._store_is_complete(store, signature)
    manifest.unlink()
    assert not structured_dataset._store_is_complete(store, signature)


def test_store_signature_tracks_mtime_and_size(tmp_path: Path) -> None:
    pool = tmp_path / "pool"
    _write_multi_file_pool(pool)
    paths = sorted(pool.glob("*.npz"))
    sig = structured_dataset._store_signature(paths)
    assert sig == structured_dataset._store_signature(paths)
    future = time.time() + 120
    os.utime(paths[0], (future, future))
    assert structured_dataset._store_signature(paths) != sig


# ---------------------------------------------------------------------
# Narrowed on-disk dtypes (flat-store layout v2)
# ---------------------------------------------------------------------


def _store_dtypes(directory: Path) -> dict[str, np.dtype]:
    """Read every store array's dtype straight off its ``.npy``
    header — no dataset object in between."""
    out: dict[str, np.dtype] = {}
    for path in sorted(directory.glob("*.npy")):
        with open(path, "rb") as fp:
            version = np.lib.format.read_magic(fp)
            reader = (
                np.lib.format.read_array_header_1_0 if version == (1, 0)
                else np.lib.format.read_array_header_2_0
            )
            _shape, _fortran, dtype = reader(fp)
        out[path.name] = dtype
    return out


def test_store_arrays_use_the_narrowed_dtypes(tmp_path: Path) -> None:
    """Every column's on-disk dtype is the documented one: the token
    id columns are int16 / int32, not int64."""
    _write_multi_file_pool(tmp_path)
    dataset = load_structured_dataset(tmp_path)
    try:
        dtypes = _store_dtypes(Path(dataset._memmap_dir))
        assert dtypes == structured_dataset.FLAT_STORE_DTYPES
        assert dtypes["token_type_flat.npy"] == np.dtype(np.int16)
        assert dtypes["token_emb_ids_flat.npy"] == np.dtype(np.int32)
        assert dtypes["token_scalars_flat.npy"] == np.dtype(np.float32)
        # The memmaps the dataset holds agree with the files.
        assert dataset._token_type_flat.dtype == np.int16
        assert dataset._token_emb_ids_flat.dtype == np.int32
    finally:
        dataset.close()


def test_in_ram_constructor_also_narrows() -> None:
    """The legacy single-array constructor writes the same layout."""
    arrays = _make_struct_arrays(4, seq_lens=[1, 2, 3, 4], max_len=4, seed=5)
    dataset = StructuredDataset(
        arrays["structured_token_type"],
        arrays["structured_token_emb_ids"],
        arrays["structured_token_scalars"],
        arrays["structured_attention_mask"],
        np.zeros((4,), dtype=np.float32),
        np.zeros((4, ACTION_VOCAB_SIZE), dtype=np.float32),
        np.zeros((4, ACTION_VOCAB_SIZE), dtype=np.bool_),
    )
    try:
        assert _store_dtypes(Path(dataset._memmap_dir)) == (
            structured_dataset.FLAT_STORE_DTYPES
        )
        assert dataset[0]["token_type"].dtype == torch.int64
        assert dataset[0]["token_emb_ids"].dtype == torch.int64
    finally:
        dataset.close()


def test_narrow_store_yields_tensors_identical_to_the_int64_store(
    tmp_path: Path, monkeypatch,
) -> None:
    """Round trip: every yielded tensor — and every collated batch —
    is dtype- and value-identical to what the pre-v2 all-int64 store
    produced for the same pool."""
    _write_multi_file_pool(tmp_path)
    narrow = load_structured_dataset(tmp_path)
    try:
        with monkeypatch.context() as mp:
            # Widening the dtype constants rebuilds the v1 layout
            # through the exact same code path.
            mp.setattr(structured_dataset, "TOKEN_TYPE_DTYPE", np.int64)
            mp.setattr(structured_dataset, "TOKEN_EMB_IDS_DTYPE", np.int64)
            reference = load_structured_dataset(tmp_path)
            try:
                ref_dtypes = _store_dtypes(Path(reference._memmap_dir))
                assert ref_dtypes["token_type_flat.npy"] == np.dtype(np.int64)
                assert ref_dtypes["token_emb_ids_flat.npy"] == np.dtype(
                    np.int64
                )
                assert len(narrow) == len(reference)
                for i in range(len(reference)):
                    got, want = narrow[i], reference[i]
                    assert got.keys() == want.keys()
                    for key in want:
                        assert got[key].dtype == want[key].dtype, key
                        assert torch.equal(got[key], want[key]), key
                    assert got["token_type"].dtype == torch.int64
                    assert got["token_emb_ids"].dtype == torch.int64
                batch_got = structured_collate(
                    [narrow[i] for i in range(len(narrow))]
                )
                batch_want = structured_collate(
                    [reference[i] for i in range(len(reference))]
                )
                for key in batch_want:
                    assert batch_got[key].dtype == batch_want[key].dtype, key
                    assert torch.equal(batch_got[key], batch_want[key]), key
                assert batch_got["token_type"].dtype == torch.int64
                assert batch_got["token_emb_ids"].dtype == torch.int64
            finally:
                reference.close()
    finally:
        narrow.close()


@pytest.mark.parametrize(
    "key, value, column",
    [
        ("structured_token_type", 40_000, "token_type_flat"),
        ("structured_token_emb_ids", 2 ** 31, "token_emb_ids_flat"),
    ],
)
def test_value_too_wide_for_the_store_dtype_fails_loudly(
    tmp_path: Path, key: str, value: int, column: str,
) -> None:
    """A vocab that outgrew the stored dtype must raise, naming the
    column, the value and the file — numpy truncates silently."""
    _make_synthetic_npz(tmp_path / "a.npz", 3, max_len=4, seed=1)
    with np.load(tmp_path / "a.npz") as handle:
        arrays = {k: handle[k] for k in handle.files}
    bumped = arrays[key].astype(np.int64)
    if bumped.ndim == 2:
        bumped[0, 0] = value
    else:
        bumped[0, 0, 0] = value
    arrays[key] = bumped
    _write_raw_npz(tmp_path / "a.npz", **arrays)

    owned_before = set(structured_dataset._OWNED_DIRS)
    with pytest.raises(ValueError) as excinfo:
        load_structured_dataset(tmp_path)
    message = str(excinfo.value)
    assert column in message
    assert str(value) in message
    assert "a.npz" in message
    # The half-written store is removed by the failure path.
    assert set(structured_dataset._OWNED_DIRS) == owned_before


def test_in_ram_constructor_rejects_out_of_range_ids() -> None:
    arrays = _make_struct_arrays(2, seq_lens=[2, 2], max_len=2, seed=2)
    arrays["structured_token_emb_ids"][0, 0, 0] = 2 ** 33
    with pytest.raises(ValueError, match="token_emb_ids_flat"):
        StructuredDataset(
            arrays["structured_token_type"],
            arrays["structured_token_emb_ids"],
            arrays["structured_token_scalars"],
            arrays["structured_attention_mask"],
            np.zeros((2,), dtype=np.float32),
            np.zeros((2, ACTION_VOCAB_SIZE), dtype=np.float32),
            np.zeros((2, ACTION_VOCAB_SIZE), dtype=np.bool_),
        )


# ---------------------------------------------------------------------
# Owner marker + killed-run reclamation
# ---------------------------------------------------------------------


def _spawned_and_exited_pid() -> int:
    """A pid that is definitely not running any more: spawn a trivial
    process, wait for it, return its (now free) pid."""
    popen = subprocess.Popen([sys.executable, "-c", "pass"])
    popen.wait()
    return popen.pid


def _write_marker(directory: Path, pid: int) -> None:
    (directory / structured_dataset._OWNER_NAME).write_text(
        json.dumps(
            {"pid": pid, "host": platform.node(), "created_at": time.time()}
        ),
        encoding="utf-8",
    )


def test_pid_is_running_self_and_exited_child() -> None:
    assert structured_dataset._pid_is_running(os.getpid())
    assert not structured_dataset._pid_is_running(_spawned_and_exited_pid())
    assert not structured_dataset._pid_is_running(0)


def test_owned_store_carries_an_owner_marker(tmp_path: Path) -> None:
    _write_multi_file_pool(tmp_path)
    dataset = load_structured_dataset(tmp_path)
    try:
        marker = structured_dataset._read_owner_marker(
            Path(dataset._memmap_dir)
        )
        assert marker is not None
        assert marker["pid"] == os.getpid()
        assert marker["host"] == platform.node()
        assert structured_dataset._store_owner_is_live(
            Path(dataset._memmap_dir)
        ) is True
    finally:
        dataset.close()


def test_sweep_keeps_a_live_owner_store_however_old(tmp_path: Path) -> None:
    """A multi-hour training run's store must survive the sweep even
    though its mtime is ancient — the pid, not the age, is the signal."""
    prefix = structured_dataset.MEMMAP_DIR_PREFIX
    live = tmp_path / f"{prefix}live"
    live.mkdir()
    _write_marker(live, os.getpid())
    old = time.time() - 48 * 3600
    os.utime(live, (old, old))
    removed = structured_dataset.sweep_stale_memmap_dirs(
        max_age_hours=1, root=tmp_path,
    )
    assert removed == 0
    assert live.is_dir()


def test_sweep_removes_a_dead_owner_store_immediately(
    tmp_path: Path,
) -> None:
    """A killed run's store is reclaimed on the next load, not after
    the age threshold — a single leaked store is tens of GB."""
    prefix = structured_dataset.MEMMAP_DIR_PREFIX
    orphan = tmp_path / f"{prefix}orphan"
    orphan.mkdir()
    (orphan / "token_type_flat.npy").write_bytes(b"x")
    _write_marker(orphan, _spawned_and_exited_pid())
    # Fresh: mtime is now, so the age threshold alone would keep it.
    removed = structured_dataset.sweep_stale_memmap_dirs(
        max_age_hours=12, root=tmp_path,
    )
    assert removed == 1
    assert not orphan.exists()


def test_sweep_falls_back_to_age_without_a_usable_marker(
    tmp_path: Path,
) -> None:
    prefix = structured_dataset.MEMMAP_DIR_PREFIX
    foreign = tmp_path / f"{prefix}foreign_host"
    corrupt = tmp_path / f"{prefix}corrupt_marker"
    for directory in (foreign, corrupt):
        directory.mkdir()
    (foreign / structured_dataset._OWNER_NAME).write_text(
        json.dumps({"pid": 1, "host": "some-other-box"}), encoding="utf-8",
    )
    (corrupt / structured_dataset._OWNER_NAME).write_text(
        "{truncated", encoding="utf-8",
    )
    removed = structured_dataset.sweep_stale_memmap_dirs(
        max_age_hours=12, root=tmp_path,
    )
    assert removed == 0, "young + unidentifiable must be left alone"
    old = time.time() - 48 * 3600
    os.utime(foreign, (old, old))
    os.utime(corrupt, (old, old))
    removed = structured_dataset.sweep_stale_memmap_dirs(
        max_age_hours=12, root=tmp_path,
    )
    assert removed == 2


def test_default_sweep_age_is_short_now_that_stores_are_huge() -> None:
    assert structured_dataset.DEFAULT_SWEEP_HOURS <= 2.0


def test_abandoned_cache_build_dirs_are_reclaimed(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    dead = cache / ".building-deadsig-1234"
    live = cache / ".building-livesig-5678"
    published = cache / "abcdef"
    for directory in (dead, live, published):
        directory.mkdir()
    _write_marker(dead, _spawned_and_exited_pid())
    _write_marker(live, os.getpid())
    assert structured_dataset.sweep_abandoned_build_dirs(cache) == 1
    assert not dead.exists()
    assert live.is_dir(), "a live build must not be swept"
    assert published.is_dir(), "a published store is not a build dir"


_LEAK_CHILD = """
import sys
from pathlib import Path
sys.path.insert(0, {src!r})
from mtg_bot.training.structured_dataset import load_structured_dataset
ds = load_structured_dataset(Path({pool!r}))
print(ds._memmap_dir)
sys.stdout.flush()
{tail}
"""


def _run_child(tmp_root: Path, pool: Path, tail: str):
    env = dict(os.environ)
    env.update(
        TMP=str(tmp_root), TEMP=str(tmp_root), TMPDIR=str(tmp_root),
        MTG_BOT_STRUCTURED_SWEEP="0",
    )
    src = str(Path(structured_dataset.__file__).parents[3])
    code = _LEAK_CHILD.format(src=src, pool=str(pool), tail=tail)
    return subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True,
    )


@pytest.mark.slow
def test_normal_child_exit_removes_the_store_without_close(
    tmp_path: Path,
) -> None:
    """``atexit`` covers the ordinary exit path: a script that never
    calls ``close()`` still leaves nothing behind."""
    pool = tmp_path / "pool"
    _write_multi_file_pool(pool)
    tmp_root = tmp_path / "temproot"
    tmp_root.mkdir()
    proc = _run_child(tmp_root, pool, "")
    assert proc.returncode == 0, proc.stderr
    leftovers = list(
        tmp_root.glob(structured_dataset.MEMMAP_DIR_PREFIX + "*")
    )
    assert leftovers == [], f"atexit did not reclaim {leftovers}"


@pytest.mark.slow
def test_os_exit_leak_is_reclaimed_by_the_next_sweep(
    tmp_path: Path,
) -> None:
    """``os._exit`` (and a hard kill) skips ``atexit``, so the store
    IS leaked — the sweep must then reclaim it on owner death, without
    waiting out the age threshold."""
    pool = tmp_path / "pool"
    _write_multi_file_pool(pool)
    tmp_root = tmp_path / "temproot"
    tmp_root.mkdir()
    proc = _run_child(tmp_root, pool, "import os; os._exit(0)")
    assert proc.returncode == 0, proc.stderr
    leaked = list(tmp_root.glob(structured_dataset.MEMMAP_DIR_PREFIX + "*"))
    assert len(leaked) == 1, "expected the documented os._exit leak"
    assert structured_dataset._store_owner_is_live(leaked[0]) is False
    removed = structured_dataset.sweep_stale_memmap_dirs(
        max_age_hours=12, root=tmp_root,
    )
    assert removed == 1
    assert not leaked[0].exists()


def test_layout_version_bump_invalidates_v1_caches(tmp_path: Path) -> None:
    """The narrowed layout is v2, and the version is part of the
    persistent-cache key, so a v1 store can never be reused."""
    assert structured_dataset.FLAT_STORE_VERSION >= 2
    _write_multi_file_pool(tmp_path)
    paths = sorted(tmp_path.glob("*.npz"))
    sig_now = structured_dataset._store_signature(paths)
    saved = structured_dataset.FLAT_STORE_VERSION
    try:
        structured_dataset.FLAT_STORE_VERSION = 1
        assert structured_dataset._store_signature(paths) != sig_now
    finally:
        structured_dataset.FLAT_STORE_VERSION = saved
