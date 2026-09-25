"""Measure row-shuffle vs block-shuffle I/O on a synthetic flat store.

Three measurements, from most to least machine-dependent:

1. **Access-trace analysis (deterministic, machine-independent).**
   Replay one epoch's exact read requests against the store's byte
   layout and count:

   - ``requests`` — contiguous 4 KB-page runs the epoch issues. This
     is the number of separate seeks a cold cache would pay.
   - ``mean run KB`` — how much each of those requests transfers.
     Random 4 KB faults cap out at the device's IOPS; long runs run
     at its bandwidth.
   - ``LRU-miss bytes`` — bytes the epoch pulls from disk under a
     simulated LRU page cache sized at ``--cache-frac`` of the store.
     This is the number the real box could not be made to produce
     (you cannot shrink the Windows page cache without admin), so it
     is simulated exactly instead of approximated.

2. **Wall-clock epoch** through a real ``DataLoader`` at
   ``--workers`` worker processes, with per-worker ``read_bytes`` /
   ``read_count`` sampled from ``psutil`` before the workers are shut
   down. On a box whose page cache holds the whole synthetic store
   this measures the CPU/pipeline cost, not the disk — which is
   exactly what (3) wants.

3. **Per-batch CPU cost** of ``__getitem__`` + ``structured_collate``
   with no model and no workers.

Usage::

    PYTHONPATH=src python scripts/bench_block_shuffle_io.py \\
        --rows 262144 --batch-size 256 --workers 2

Writes a JSON summary to ``--json-out`` when given.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from collections import OrderedDict
from pathlib import Path

import numpy as np

_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mtg_bot.training.block_shuffle import BlockShuffleDataset  # noqa: E402
from mtg_bot.training.structured_dataset import (  # noqa: E402
    StructuredDataset, structured_collate,
)
from mtg_bot.training.structured_model import (  # noqa: E402
    N_EMB_FIELDS, N_SCALAR_FIELDS_V2,
)

PAGE = 4096
ACTION_VOCAB = 517
NPY_HEADER = 128  # every .npy this module writes has a 128-byte header


# ---------------------------------------------------------------------
# Synthetic store
# ---------------------------------------------------------------------


def build_store(directory: Path, n_rows: int, avg_seq: int) -> None:
    """Write a flat store with the production per-row byte profile
    (~9.1 KB/row: 45 tokens × 146 B + 2.6 KB of policy/mask/scalars)."""
    directory.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(0)
    seq = rng.integers(
        max(1, avg_seq - 12), avg_seq + 13, size=n_rows,
    ).astype(np.int64)
    row_offsets = np.zeros(n_rows + 1, dtype=np.int64)
    np.cumsum(seq, out=row_offsets[1:])
    n_tok = int(row_offsets[-1])

    def _alloc(name, dtype, shape):
        return np.lib.format.open_memmap(
            directory / name, mode="w+", dtype=dtype, shape=shape,
        )

    np.save(directory / "row_offsets.npy", row_offsets)
    tt = _alloc("token_type_flat.npy", np.int16, (n_tok,))
    emb = _alloc("token_emb_ids_flat.npy", np.int32, (n_tok, N_EMB_FIELDS))
    sca = _alloc(
        "token_scalars_flat.npy", np.float32, (n_tok, N_SCALAR_FIELDS_V2),
    )
    # Fill in chunks so peak RSS stays small.
    chunk = 1_000_000
    for lo in range(0, n_tok, chunk):
        hi = min(lo + chunk, n_tok)
        tt[lo:hi] = rng.integers(0, 12, size=hi - lo).astype(np.int16)
        emb[lo:hi] = rng.integers(
            0, 100, size=(hi - lo, N_EMB_FIELDS),
        ).astype(np.int32)
        sca[lo:hi] = rng.standard_normal(
            (hi - lo, N_SCALAR_FIELDS_V2),
        ).astype(np.float32)
    for arr in (tt, emb, sca):
        arr.flush()
        del arr
    np.save(
        directory / "outcomes.npy",
        rng.choice(np.float32([-1, 0, 1]), size=n_rows),
    )
    pol = _alloc("policy_targets.npy", np.float32, (n_rows, ACTION_VOCAB))
    msk = _alloc("action_masks.npy", np.bool_, (n_rows, ACTION_VOCAB))
    for lo in range(0, n_rows, 50_000):
        hi = min(lo + 50_000, n_rows)
        pol[lo:hi, 0] = 1.0
        msk[lo:hi, :3] = True
    for arr in (pol, msk):
        arr.flush()
        del arr
    np.save(directory / "has_policy.npy", np.ones(n_rows, dtype=np.bool_))
    np.save(
        directory / "group_ids.npy",
        (np.arange(n_rows) // 40).astype(np.int64),
    )


def store_bytes(directory: Path) -> int:
    return sum(f.stat().st_size for f in directory.glob("*.npy"))


def purge_page_cache(directory: Path) -> bool:
    """Evict every store file from the Windows file cache.

    Opening a file with ``FILE_FLAG_NO_BUFFERING | FILE_FLAG_WRITE_THROUGH``
    makes the cache manager purge that file's cached section. Verified
    on this box: a 1.27 GB sequential read goes 2,525 MB/s warm ->
    1,192 MB/s straight after the purge -> 2,590 MB/s warm again.

    This is what makes a genuinely COLD epoch measurable without
    admin rights and without evicting the rest of the system's cache
    (which would be rude to anything else running).
    """
    if sys.platform != "win32":
        print("  (cold mode is win32-only; running warm)", flush=True)
        return False
    import ctypes
    import ctypes.wintypes as wt

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wt.HANDLE
    k32.CreateFileW.argtypes = [
        wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p,
        wt.DWORD, wt.DWORD, wt.HANDLE,
    ]
    ok = True
    for f in sorted(directory.glob("*.npy")):
        h = k32.CreateFileW(
            str(f), 0x80000000 | 0x40000000, 1 | 2, None, 3,
            0x20000000 | 0x80000000, None,
        )
        if h == wt.HANDLE(-1).value:
            ok = False
            continue
        k32.CloseHandle(h)
    return ok


# ---------------------------------------------------------------------
# 1. Access-trace analysis
# ---------------------------------------------------------------------


class _Layout:
    """Byte offsets of each array, laid end to end in one virtual
    address space so a single page-id space covers the whole store."""

    def __init__(self, ds: StructuredDataset) -> None:
        self.row_offsets = np.asarray(ds._row_offsets)
        self.arrays = []
        base = 0
        for name, arr, per in (
            ("token_type", ds._token_type_flat, 2),
            ("token_emb", ds._token_emb_ids_flat, 4 * N_EMB_FIELDS),
            ("token_sca", ds._token_scalars_flat, 4 * N_SCALAR_FIELDS_V2),
        ):
            self.arrays.append(("tok", name, base + NPY_HEADER, per))
            base += arr.nbytes + NPY_HEADER
        for name, arr, per in (
            ("policy", ds._policy_targets, 4 * ACTION_VOCAB),
            ("action_mask", ds._action_masks, ACTION_VOCAB),
            ("outcomes", ds._outcomes, 4),
            ("has_policy", ds._has_policy, 1),
        ):
            self.arrays.append(("row", name, base + NPY_HEADER, per))
            base += arr.nbytes + NPY_HEADER
        self.total = base

    def row_page_spans(self, lo: int, hi: int) -> list[tuple[int, int]]:
        """Inclusive ``(first_page, last_page)`` per array for storage
        rows ``[lo, hi)``."""
        t0 = int(self.row_offsets[lo])
        t1 = int(self.row_offsets[hi])
        out = []
        for kind, _name, base, per in self.arrays:
            if kind == "tok":
                b0, b1 = base + t0 * per, base + t1 * per
            else:
                b0, b1 = base + lo * per, base + hi * per
            out.append((b0 // PAGE, (b1 - 1) // PAGE))
        return out


def _runs_from_spans(spans: list[tuple[int, int]]) -> tuple[int, int]:
    """``(n_contiguous_runs, n_pages)`` for a set of page spans that
    may overlap/abut."""
    if not spans:
        return 0, 0
    spans = sorted(spans)
    runs = 0
    pages = 0
    cur_lo, cur_hi = spans[0]
    for lo, hi in spans[1:]:
        if lo <= cur_hi + 1:
            cur_hi = max(cur_hi, hi)
        else:
            runs += 1
            pages += cur_hi - cur_lo + 1
            cur_lo, cur_hi = lo, hi
    runs += 1
    pages += cur_hi - cur_lo + 1
    return runs, pages


def _lru_misses(page_iter, capacity_pages: int) -> int:
    """Pages read from disk under an LRU cache of ``capacity_pages``."""
    cache: OrderedDict[int, None] = OrderedDict()
    misses = 0
    for p in page_iter:
        if p in cache:
            cache.move_to_end(p)
            continue
        misses += 1
        cache[p] = None
        if len(cache) > capacity_pages:
            cache.popitem(last=False)
    return misses


def analyse(
    ds: StructuredDataset,
    *,
    batch_size: int,
    block_rows: int,
    cache_frac: float,
    seed: int = 0,
) -> dict:
    layout = _Layout(ds)
    n = len(ds)
    capacity = max(1, int(cache_frac * layout.total / PAGE))

    # --- row shuffle: one read per row, grouped per batch ----------
    order = np.random.default_rng(seed).permutation(n)
    row_requests = 0
    row_pages_touched = 0

    def _row_pages():
        for b0 in range(0, n, batch_size):
            spans = []
            for r in order[b0:b0 + batch_size]:
                spans.extend(layout.row_page_spans(int(r), int(r) + 1))
            runs, pages = _runs_from_spans(spans)
            yield spans, runs, pages

    row_trace: list[int] = []
    for spans, runs, pages in _row_pages():
        row_requests += runs
        row_pages_touched += pages
        for lo, hi in spans:
            row_trace.extend(range(lo, hi + 1))
    row_misses = _lru_misses(row_trace, capacity)
    del row_trace

    # --- block shuffle: one read per array per block ---------------
    bs = BlockShuffleDataset(ds, block_rows=block_rows, seed=seed)
    blk_requests = 0
    blk_pages_touched = 0
    blk_trace: list[int] = []
    for b in range(bs.n_blocks):
        lo, hi = bs.block_bounds(b)
        spans = layout.row_page_spans(
            int(bs.indices[lo]), int(bs.indices[hi - 1]) + 1,
        )
        runs, pages = _runs_from_spans(spans)
        blk_requests += runs
        blk_pages_touched += pages
        for p_lo, p_hi in spans:
            blk_trace.extend(range(p_lo, p_hi + 1))
    blk_misses = _lru_misses(blk_trace, capacity)
    del blk_trace

    return {
        "store_bytes": layout.total,
        "cache_frac": cache_frac,
        "cache_bytes": capacity * PAGE,
        "row": {
            "requests": row_requests,
            "pages": row_pages_touched,
            "mean_run_kb": row_pages_touched * PAGE / row_requests / 1024,
            "lru_miss_bytes": row_misses * PAGE,
        },
        "block": {
            "requests": blk_requests,
            "pages": blk_pages_touched,
            "mean_run_kb": blk_pages_touched * PAGE / blk_requests / 1024,
            "lru_miss_bytes": blk_misses * PAGE,
        },
    }


# ---------------------------------------------------------------------
# 2. Wall-clock epoch through a real DataLoader
# ---------------------------------------------------------------------


def _io_of_children(parent_pid: int) -> dict:
    try:
        import psutil
    except ImportError:
        return {}
    out = {"read_bytes": 0, "read_count": 0}
    try:
        for child in psutil.Process(parent_pid).children(recursive=True):
            try:
                io = child.io_counters()
            except Exception:  # noqa: BLE001
                continue
            out["read_bytes"] += io.read_bytes
            out["read_count"] += io.read_count
    except Exception:  # noqa: BLE001
        pass
    return out


def wall_epoch(
    memmap_dir: Path,
    mode: str,
    *,
    batch_size: int,
    block_rows: int,
    workers: int,
    cold: bool = False,
) -> dict:
    from torch.utils.data import DataLoader

    from mtg_bot.training.structured_dataset import (
        shutdown_dataloader_workers,
    )

    if cold:
        purge_page_cache(memmap_dir)
    ds = StructuredDataset.from_memmap_dir(memmap_dir)
    try:
        if mode == "block":
            loader = DataLoader(
                BlockShuffleDataset(ds, block_rows=block_rows, seed=0),
                batch_size=batch_size, shuffle=False,
                collate_fn=structured_collate, num_workers=workers,
                persistent_workers=workers > 0,
            )
        else:
            loader = DataLoader(
                ds, batch_size=batch_size, shuffle=True,
                collate_fn=structured_collate, num_workers=workers,
                persistent_workers=workers > 0,
            )
        rows = 0
        batches = 0
        t0 = time.perf_counter()
        for batch in loader:
            rows += int(batch["token_type"].shape[0])
            batches += 1
        elapsed = time.perf_counter() - t0
        io = _io_of_children(os.getpid())
        shutdown_dataloader_workers(loader)
        del loader
        return {
            "mode": mode, "cold": bool(cold),
            "seconds": elapsed, "rows": rows,
            "batches": batches, "rows_per_sec": rows / elapsed,
            "worker_read_bytes": io.get("read_bytes"),
            "worker_read_count": io.get("read_count"),
        }
    finally:
        ds.close()


# ---------------------------------------------------------------------
# 3. Per-batch CPU cost of __getitem__ + collate
# ---------------------------------------------------------------------


def cpu_cost(
    memmap_dir: Path,
    mode: str,
    *,
    batch_size: int,
    block_rows: int,
    max_batches: int,
) -> dict:
    ds = StructuredDataset.from_memmap_dir(memmap_dir)
    try:
        n = len(ds)
        if mode == "block":
            src = iter(BlockShuffleDataset(
                ds, block_rows=block_rows, seed=0,
            ))

            def _next_batch():
                items = []
                for _ in range(batch_size):
                    try:
                        items.append(next(src))
                    except StopIteration:
                        break
                return items
        else:
            order = np.random.default_rng(0).permutation(n)
            pos = {"i": 0}

            def _next_batch():
                i = pos["i"]
                idx = order[i:i + batch_size]
                pos["i"] = i + batch_size
                return [ds[int(r)] for r in idx]

        # Warm-up batch (page-cache + import costs) is discarded.
        _next_batch()
        times = []
        rows = 0
        for _ in range(max_batches):
            t0 = time.perf_counter()
            items = _next_batch()
            if not items:
                break
            batch = structured_collate(items)
            times.append(time.perf_counter() - t0)
            rows += int(batch["token_type"].shape[0])
        arr = np.array(times)
        return {
            "mode": mode,
            "batches": int(arr.size),
            "ms_per_batch_mean": float(arr.mean() * 1e3),
            "ms_per_batch_p50": float(np.percentile(arr, 50) * 1e3),
            "ms_per_batch_p90": float(np.percentile(arr, 90) * 1e3),
            "us_per_row": float(arr.sum() / rows * 1e6),
        }
    finally:
        ds.close()


# ---------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rows", type=int, default=262_144)
    ap.add_argument("--avg-seq", type=int, default=45)
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--block-rows", type=int, default=65_536)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--cache-frac", type=float, default=0.25)
    ap.add_argument(
        "--cold", action="store_true",
        help=(
            "Purge the store from the OS file cache before each wall "
            "epoch so the numbers reflect real disk I/O (win32 only)."
        ),
    )
    ap.add_argument("--cpu-batches", type=int, default=120)
    ap.add_argument("--store-dir", default=None)
    ap.add_argument("--keep-store", action="store_true")
    ap.add_argument("--json-out", default=None)
    ap.add_argument(
        "--skip", default="", help="comma-separated: trace,wall,cpu",
    )
    args = ap.parse_args(argv)
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}

    import tempfile

    store = Path(
        args.store_dir
        or Path(tempfile.gettempdir()) / "mtg_bot_block_shuffle_bench"
    )
    fresh = not (store / "row_offsets.npy").is_file()
    if fresh:
        print(f"building synthetic store at {store} ...", flush=True)
        t0 = time.perf_counter()
        build_store(store, args.rows, args.avg_seq)
        print(f"  built in {time.perf_counter() - t0:.1f}s", flush=True)
    nbytes = store_bytes(store)
    print(f"store: {nbytes / 1024 ** 3:.2f} GB", flush=True)

    out: dict = {
        "store_dir": str(store),
        "store_gb": nbytes / 1024 ** 3,
        "rows": args.rows,
        "batch_size": args.batch_size,
        "block_rows": args.block_rows,
        "workers": args.workers,
    }
    try:
        if "trace" not in skip:
            ds = StructuredDataset.from_memmap_dir(store)
            try:
                print("access-trace analysis ...", flush=True)
                out["trace"] = analyse(
                    ds, batch_size=args.batch_size,
                    block_rows=args.block_rows,
                    cache_frac=args.cache_frac,
                )
            finally:
                ds.close()
            t = out["trace"]
            for mode in ("row", "block"):
                m = t[mode]
                print(
                    f"  {mode:5s}  requests={m['requests']:>10,}  "
                    f"mean_run={m['mean_run_kb']:>9.1f} KB  "
                    f"lru_miss={m['lru_miss_bytes'] / 1024 ** 3:>7.2f} GB",
                    flush=True,
                )
        if "wall" not in skip:
            out["wall"] = []
            for mode in ("row", "block"):
                print(
                    f"wall epoch [{mode}]"
                    f"{' cold' if args.cold else ' warm'} ...", flush=True,
                )
                r = wall_epoch(
                    store, mode, batch_size=args.batch_size,
                    block_rows=args.block_rows, workers=args.workers,
                    cold=args.cold,
                )
                out["wall"].append(r)
                print(
                    f"  {mode:5s}  {r['seconds']:.1f}s  "
                    f"{r['rows_per_sec']:,.0f} rows/s  "
                    f"worker_read="
                    f"{(r['worker_read_bytes'] or 0) / 1024 ** 2:.0f} MB",
                    flush=True,
                )
        if "cpu" not in skip:
            out["cpu"] = []
            for mode in ("row", "block"):
                r = cpu_cost(
                    store, mode, batch_size=args.batch_size,
                    block_rows=args.block_rows,
                    max_batches=args.cpu_batches,
                )
                out["cpu"].append(r)
                print(
                    f"  cpu {mode:5s}  {r['ms_per_batch_mean']:.2f} "
                    f"ms/batch (p50 {r['ms_per_batch_p50']:.2f}, "
                    f"p90 {r['ms_per_batch_p90']:.2f})  "
                    f"{r['us_per_row']:.1f} us/row",
                    flush=True,
                )
    finally:
        if not args.keep_store and fresh:
            shutil.rmtree(store, ignore_errors=True)

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(out, indent=2), encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
