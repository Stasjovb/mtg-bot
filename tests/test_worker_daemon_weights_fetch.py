"""Tests for the atomic, inter-process-safe weights-cache fetch.

This module exists to close the TOCTOU race that crashed the AWS
c7i.8xlarge economics bench at ``--n-workers 30`` (72/100 games
crashed instantly at game start — ``torch.load`` of a 0-byte /
partially-written ``weights.pt`` — while 28 ran normally; the bimodal
"instant-crash or fully-normal" signature of a subprocess-pool
startup race).

Coverage:

- ``_atomic_write_bytes``: a concurrent reader never sees a partial
  file (the core invariant); temp file is cleaned up.
- ``_InterProcessLock``: mutual exclusion, timeout, stale reclaim,
  released-mid-wait, context manager.
- ``fetch_weights_atomic``: warm-cache fast path (no GET, no lock),
  cold fetch (two GETs), non-200 raises, 0-byte legacy file is
  re-fetched, and the **concurrent cold-cache regression** — N
  threads racing a slow fetch all observe a byte-complete file
  (fails on revert to the pre-fix ``is_file()`` guard).
- ``fetch_weights_if_missing`` delegation still satisfies the
  existing claim-loop contract.
"""

from __future__ import annotations

import threading
import multiprocessing as mp
import sys
import time
import zlib
from pathlib import Path

import pytest

from mtg_bot import worker_daemon_weights_fetch as wf
from mtg_bot import worker_daemon_claim_loop as cl


# ---------------------------------------------------------------------------
# Process-based race regression (module-level so it pickles for spawn).
#
# This is the strongest guard: TRUE multi-process parallelism (no GIL),
# the exact shape that crashed the AWS c7i.8xlarge bench. A
# network-stretched http_get widens the window; each process then
# CRC-checks the published file several times (modelling per-game
# torch.load reloads). Pre-fix this produced 0-byte / partial reads.
# ---------------------------------------------------------------------------

# ~2.6 MB — the real v6 weights.pt size. The torn-write window scales
# with payload size; the proven local repro
# (scripts/scout_weights_fetch_race.py) needed this size to trip the
# pre-fix is_file() guard 75/150 times across trials. A smaller blob
# writes too fast to reliably catch a reader mid-write even on POSIX.
_RACE_PAYLOAD = (b"".join(bytes([i % 256]) for i in range(65_536))) * 40
_RACE_TRAILER = zlib.crc32(_RACE_PAYLOAD).to_bytes(4, "big")
_RACE_BLOB = _RACE_PAYLOAD + _RACE_TRAILER


def _race_worker(args):
    idx, cache_root, barrier, get_counter, counter_lock = args

    def counting_http_get(url, *, timeout=30.0):
        # Count every real network fetch across all processes via a
        # Manager-proxied shared counter (picklable through pool.map).
        # Models the multi-MB Tailscale pull: the GET takes real wall
        # time, so N processes overlap inside the fetch window
        # (maximising the pre-fix race).
        with counter_lock:
            get_counter.value += 1
        if url.endswith("/metadata"):
            time.sleep(0.05)
            return 200, b'{"a":1}', {}
        time.sleep(0.25)
        return 200, _RACE_BLOB, {}

    try:
        barrier.wait(timeout=30)
    except Exception:
        pass
    try:
        out = wf.fetch_weights_atomic(
            coordinator_url="http://fake",
            version="v6",
            weights_dir=Path(cache_root) / "v6",
            http_get=counting_http_get,
            http_timeout_s=30.0,
        )
        wp = out / "weights.pt"
        for _ in range(4):  # per-game torch.load reloads
            raw = wp.read_bytes()
            if len(raw) < 4:
                return idx, f"FAIL truncated {len(raw)}b"
            if zlib.crc32(raw[:-4]).to_bytes(4, "big") != raw[-4:]:
                return idx, f"FAIL CRC {len(raw)}b"
        return idx, "OK"
    except Exception as exc:  # noqa: BLE001
        return idx, f"FAIL {type(exc).__name__}: {exc}"


@pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "The torn-write race is POSIX-semantics (open(wb) truncates "
        "immediately, no opportunistic lock). Windows file sharing "
        "masks it; the atomicity invariant is covered cross-platform "
        "by test_naive_writer_is_torn_but_atomic_writer_is_not. This "
        "process-based test is the on-Linux (CI / AWS-shape) guard."
    ),
)
def test_concurrent_processes_cold_cache_lock_collapses_and_no_torn(
    tmp_path,
):
    """REGRESSION (process-based, fails on revert to the is_file
    guard). 30 fork processes hit a cold shared cache simultaneously
    through a slow fetch — the exact AWS c7i.8xlarge --n-workers 30
    shape.

    Two invariants, both broken pre-fix:

    1. **Lock-collapse (deterministic).** The per-version
       inter-process lock serializes the fetch: the first process
       downloads, peers block then return the published cache. So
       across all 30 processes there are **exactly 2 GETs** (weights
       + metadata). The pre-fix code had no lock — all 30 processes
       independently fetch → ~60 GETs. This assertion fails hard on
       revert.
    2. **No torn reads.** Every process ends with a byte-complete,
       CRC-valid weights.pt (pre-fix: bimodal instant-crash from a
       0-byte / partial torch.load on the processes that lost the
       race).
    """
    procs = 30
    # ``fork`` on Linux == the AWS worker daemon's mp context and the
    # shape the proven local repro used. (This whole test is
    # win32-skipped above, so fork is always available here.)
    ctx = mp.get_context("fork")
    mgr = ctx.Manager()
    barrier = mgr.Barrier(procs)
    get_counter = mgr.Value("i", 0)
    counter_lock = mgr.Lock()
    cache_root = str(tmp_path / "cache")
    with ctx.Pool(procs) as pool:
        results = pool.map(
            _race_worker,
            [
                (i, cache_root, barrier, get_counter, counter_lock)
                for i in range(procs)
            ],
            chunksize=1,
        )
    bad = [r for r in results if r[1] != "OK"]
    assert len(results) == procs
    assert not bad, f"{len(bad)}/{procs} processes saw a torn file: {bad[:6]}"
    # The lock must collapse 30 concurrent cold fetches into exactly
    # one fetch pair. Pre-fix (no lock): ~2*procs GETs.
    assert get_counter.value == 2, (
        f"expected exactly 2 GETs (per-version lock should collapse "
        f"the {procs}-way cold race), got {get_counter.value} — the "
        f"inter-process lock is not serializing the fetch."
    )


# ---------------------------------------------------------------------------
# _atomic_write_bytes
# ---------------------------------------------------------------------------


def test_atomic_write_publishes_full_file(tmp_path):
    target = tmp_path / "weights.pt"
    wf._atomic_write_bytes(target, b"\x00" * 4096)
    assert target.read_bytes() == b"\x00" * 4096
    # No temp residue.
    assert list(tmp_path.glob(".weights.pt.*.tmp")) == []


def _naive_write_bytes(target: Path, data: bytes, _chunk_pause):
    """The PRE-FIX writer: open the final path directly and write in
    chunks (models a network-streamed body landing incrementally).
    A reader can catch this mid-write. Used only to prove the test
    harness genuinely detects the torn-file class the fix removes.
    """
    import time as _t

    with open(target, "wb") as fh:
        half = len(data) // 2
        fh.write(data[:half])
        fh.flush()
        _chunk_pause()  # the observable partial-file window
        fh.write(data[half:])


def test_naive_writer_is_torn_but_atomic_writer_is_not(tmp_path):
    """Sentinel + invariant: a reader spinning while a writer works
    MUST catch a partial file with the naive (pre-fix) writer, and
    MUST NEVER catch one with ``_atomic_write_bytes``. The first half
    proves the harness has teeth (guards against a vacuous pass); the
    second half is the actual regression guard for the fix.
    """
    full = b"A" * 800_000

    def run(writer_fn, fname):
        target = tmp_path / fname
        stop = threading.Event()
        seen_partial: list[int] = []
        pause = threading.Event()

        def reader():
            while not stop.is_set():
                try:
                    data = target.read_bytes()
                except OSError:
                    continue
                if data and data != full:
                    seen_partial.append(len(data))

        def chunk_pause():
            # Hold the half-written window open long enough for the
            # reader to observe it deterministically.
            time.sleep(0.05)

        r = threading.Thread(target=reader, daemon=True)
        r.start()
        for _ in range(8):
            if writer_fn is _naive_write_bytes:
                writer_fn(target, full, chunk_pause)
            else:
                writer_fn(target, full)
        stop.set()
        r.join(timeout=5)
        return seen_partial

    naive_partials = run(_naive_write_bytes, "naive.pt")
    atomic_partials = run(wf._atomic_write_bytes, "atomic.pt")

    assert naive_partials, (
        "harness sanity FAILED: the naive pre-fix writer should be "
        "observably torn — if this is empty the test cannot guard "
        "the fix (vacuous pass)."
    )
    assert atomic_partials == [], (
        f"REGRESSION: _atomic_write_bytes left {len(atomic_partials)} "
        f"observable partial files {atomic_partials[:5]} — the "
        f"os.replace publish is not atomic."
    )


def test_atomic_write_retries_replace_on_permission_error(
    tmp_path, monkeypatch
):
    """Windows: ``os.replace`` raises PermissionError while a peer
    holds the destination open. The writer must retry and eventually
    succeed once the handle is released.
    """
    target = tmp_path / "weights.pt"
    state = {"n": 0}
    real_replace = wf.os.replace

    def flaky_replace(src, dst):
        state["n"] += 1
        if state["n"] < 3:
            raise PermissionError(5, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(wf.os, "replace", flaky_replace)
    monkeypatch.setattr(wf, "_REPLACE_RETRY_S", (0.0, 0.0, 0.0, 0.0))
    wf._atomic_write_bytes(target, b"payload")
    monkeypatch.undo()
    assert target.read_bytes() == b"payload"
    assert state["n"] == 3


def test_atomic_write_permission_error_peer_published_is_success(
    tmp_path, monkeypatch
):
    """If ``os.replace`` keeps failing with PermissionError but a peer
    meanwhile published a byte-complete identical-length file, the
    writer treats it as done rather than raising.
    """
    target = tmp_path / "weights.pt"

    def always_denied(src, dst):
        # Simulate a peer having published the same blob.
        if not target.exists():
            target.write_bytes(b"PEER-BLOB")
        raise PermissionError(32, "in use")

    monkeypatch.setattr(wf.os, "replace", always_denied)
    monkeypatch.setattr(wf, "_REPLACE_RETRY_S", (0.0, 0.0))
    wf._atomic_write_bytes(target, b"MY-BLOB!!")  # same length (9)
    monkeypatch.undo()
    assert target.read_bytes() == b"PEER-BLOB"


def test_atomic_write_permission_error_exhausts_and_raises(
    tmp_path, monkeypatch
):
    """If the replace never succeeds and no peer publishes, the
    PermissionError surfaces after retries are exhausted."""
    target = tmp_path / "weights.pt"

    def always_denied(src, dst):
        raise PermissionError(5, "locked forever")

    monkeypatch.setattr(wf.os, "replace", always_denied)
    monkeypatch.setattr(wf, "_REPLACE_RETRY_S", (0.0, 0.0))
    with pytest.raises(PermissionError):
        wf._atomic_write_bytes(target, b"data")
    monkeypatch.undo()
    assert list(tmp_path.glob(".weights.pt.*.tmp")) == []


def test_atomic_write_cleans_temp_on_write_failure(tmp_path, monkeypatch):
    target = tmp_path / "weights.pt"

    class Boom(IOError):
        pass

    real_open = open

    def exploding_open(path, mode="r", *a, **k):
        if str(path).endswith(".tmp") and "w" in mode:
            fh = real_open(path, mode, *a, **k)
            orig_write = fh.write

            def bad_write(_data):
                raise Boom("disk full")

            fh.write = bad_write  # type: ignore[assignment]
            return fh
        return real_open(path, mode, *a, **k)

    monkeypatch.setattr("builtins.open", exploding_open)
    with pytest.raises(Boom):
        wf._atomic_write_bytes(target, b"data")
    monkeypatch.undo()
    assert not target.exists()
    assert list(tmp_path.glob(".weights.pt.*.tmp")) == []


# ---------------------------------------------------------------------------
# _InterProcessLock
# ---------------------------------------------------------------------------


def test_lock_is_mutually_exclusive(tmp_path):
    lp = tmp_path / "x.lock"
    order: list[str] = []
    held = threading.Event()

    def first():
        with wf._InterProcessLock(lp):
            held.set()
            order.append("first-in")
            time.sleep(0.2)
            order.append("first-out")

    def second():
        held.wait()
        with wf._InterProcessLock(lp, poll_s=0.01):
            order.append("second-in")

    t1 = threading.Thread(target=first)
    t2 = threading.Thread(target=second)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert order == ["first-in", "first-out", "second-in"]


def test_lock_times_out_when_held(tmp_path):
    lp = tmp_path / "y.lock"
    with wf._InterProcessLock(lp):
        other = wf._InterProcessLock(lp, timeout_s=0.15, poll_s=0.01)
        with pytest.raises(TimeoutError, match="weights-fetch lock"):
            other.acquire()


def test_lock_reclaims_stale(tmp_path):
    lp = tmp_path / "z.lock"
    # Simulate a crashed holder: a lock file with an old mtime.
    lp.write_text("99999 0")
    import os

    old = time.time() - 10_000
    os.utime(lp, (old, old))
    # stale_s small enough that the existing file is stale.
    with wf._InterProcessLock(lp, stale_s=1.0, poll_s=0.01):
        assert lp.exists()  # we now hold a fresh one
    assert not lp.exists()


def test_lock_acquire_treats_permission_error_like_contention(
    tmp_path, monkeypatch
):
    """Windows raises PermissionError (not FileExistsError) when the
    lock file is in a transient delete-pending state under contention.
    The acquire loop must retry, not crash, and eventually succeed.
    """
    lp = tmp_path / "p.lock"
    real_open = wf.os.open
    calls = {"n": 0}

    def flaky_open(path, flags, *a, **k):
        if str(path) == str(lp) and (flags & wf.os.O_EXCL):
            calls["n"] += 1
            if calls["n"] < 4:
                raise PermissionError(5, "Access is denied")
        return real_open(path, flags, *a, **k)

    monkeypatch.setattr(wf.os, "open", flaky_open)
    lk = wf._InterProcessLock(lp, poll_s=0.0)
    lk.acquire()
    monkeypatch.undo()
    assert lk._acquired
    assert calls["n"] == 4
    lk.release()


def test_lock_release_swallows_unlink_oserror(tmp_path, monkeypatch):
    """release()'s os.unlink may race a peer / AV scanner; an OSError
    there must not propagate (lines 164-165)."""
    lp = tmp_path / "ro.lock"
    lk = wf._InterProcessLock(lp)
    lk.acquire()

    def boom_unlink(_p):
        raise OSError("device busy")

    monkeypatch.setattr(wf.os, "unlink", boom_unlink)
    lk.release()  # must not raise
    monkeypatch.undo()
    assert not lk._acquired


def test_replace_retry_actually_sleeps(tmp_path, monkeypatch):
    """The retry backoff path's ``time.sleep(delay)`` (line 223) is
    exercised when the first replace fails and a non-zero delay
    follows."""
    target = tmp_path / "weights.pt"
    slept: list[float] = []
    monkeypatch.setattr(wf.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(wf, "_REPLACE_RETRY_S", (0.01, 0.02))
    real_replace = wf.os.replace
    n = {"i": 0}

    def flaky(src, dst):
        n["i"] += 1
        if n["i"] == 1:
            raise PermissionError(5, "denied once")
        return real_replace(src, dst)

    monkeypatch.setattr(wf.os, "replace", flaky)
    wf._atomic_write_bytes(target, b"ok")
    monkeypatch.undo()
    assert target.read_bytes() == b"ok"
    assert slept and slept[0] == 0.01  # the first backoff delay slept


def test_atomic_write_finally_unlink_oserror_swallowed(
    tmp_path, monkeypatch
):
    """The finally-block temp cleanup (lines 249-250) must swallow an
    OSError from os.unlink."""
    target = tmp_path / "weights.pt"
    real_unlink = wf.os.unlink

    def boom_unlink(p):
        if str(p).endswith(".tmp"):
            raise OSError("locked by scanner")
        return real_unlink(p)

    # Force the replace to fail so the temp file survives into the
    # finally cleanup, then make that cleanup's unlink raise.
    monkeypatch.setattr(wf, "_REPLACE_RETRY_S", ())
    monkeypatch.setattr(
        wf.os, "replace",
        lambda *a: (_ for _ in ()).throw(PermissionError(5, "x")),
    )
    monkeypatch.setattr(wf.os, "unlink", boom_unlink)
    with pytest.raises(PermissionError):
        wf._atomic_write_bytes(target, b"data")
    monkeypatch.undo()  # no secondary OSError leaked


def test_cache_complete_returns_false_on_oserror(monkeypatch, tmp_path):
    """_cache_complete's stat() may raise (lines 265-266); it must
    degrade to "incomplete" (treat as miss) rather than crash."""
    wp = tmp_path / "weights.pt"
    mp_ = tmp_path / "metadata.json"
    wp.write_bytes(b"x")
    mp_.write_bytes(b"{}")

    def boom_stat(self, *a, **k):
        raise OSError("io error")

    monkeypatch.setattr(Path, "stat", boom_stat)
    assert wf._cache_complete(wp, mp_) is False
    monkeypatch.undo()


def test_present_helper_oserror_treated_as_absent(tmp_path, monkeypatch):
    """The under-lock ``_present`` helper (lines 311-312): a stat()
    OSError means "not present", so the fetch proceeds rather than
    crashing."""
    vdir = tmp_path / "v6"
    http = _http(weights=b"WW", metadata=b"{}")

    real_stat = Path.stat
    state = {"raised": False}

    def flaky_stat(self, *a, **k):
        # Raise exactly once, for the weights.pt presence check
        # inside the lock, then behave normally.
        if self.name == "weights.pt" and not state["raised"]:
            state["raised"] = True
            raise OSError("transient")
        return real_stat(self, *a, **k)

    monkeypatch.setattr(Path, "stat", flaky_stat)
    out = wf.fetch_weights_atomic(
        "http://c", "v6", vdir, http_get=http, http_timeout_s=5,
    )
    monkeypatch.undo()
    assert (out / "weights.pt").read_bytes() == b"WW"
    assert state["raised"]


def test_lock_release_is_idempotent_and_handles_missing(tmp_path):
    lp = tmp_path / "i.lock"
    lk = wf._InterProcessLock(lp)
    lk.release()  # never acquired -> no-op
    lk.acquire()
    lp.unlink()  # vanish underneath us
    lk.release()  # must not raise
    lk.release()  # idempotent


def test_lock_acquire_retries_when_lock_vanishes(tmp_path, monkeypatch):
    """A FileExistsError followed by the lock disappearing (peer
    released it) must lead to a successful acquire on retry — the
    ``_reclaim_if_stale`` returns True branch when ``stat`` raises.
    """
    lp = tmp_path / "v.lock"
    lp.write_text("1 0")

    lk = wf._InterProcessLock(lp, poll_s=0.01)
    real_stat = Path.stat
    calls = {"n": 0}

    def flaky_stat(self, *a, **k):
        if self == lp:
            calls["n"] += 1
            # First stat: pretend the lock vanished -> reclaim retry.
            lp.unlink(missing_ok=True)
            raise OSError("gone")
        return real_stat(self, *a, **k)

    monkeypatch.setattr(Path, "stat", flaky_stat, raising=True)
    lk.acquire()
    monkeypatch.undo()
    assert lk._acquired
    lk.release()
    assert calls["n"] >= 1


# ---------------------------------------------------------------------------
# fetch_weights_atomic
# ---------------------------------------------------------------------------


def _http(weights=b"WEIGHTS", metadata=b'{"a":1}', status=200, delay=0.0):
    calls: list[str] = []

    def http_get(url, *, timeout=30.0):
        calls.append(url)
        if delay:
            time.sleep(delay)
        body = metadata if url.endswith("/metadata") else weights
        return status, body, {}

    http_get.calls = calls  # type: ignore[attr-defined]
    return http_get


def test_warm_cache_is_lock_free_and_no_get(tmp_path):
    vdir = tmp_path / "v6"
    vdir.mkdir(parents=True)
    (vdir / "weights.pt").write_bytes(b"x")
    (vdir / "metadata.json").write_bytes(b"{}")
    http = _http()
    out = wf.fetch_weights_atomic(
        "http://c", "v6", vdir, http_get=http, http_timeout_s=5,
    )
    assert out == vdir
    assert http.calls == []
    # No lock file created on the fast path.
    assert not (vdir / ".v6.fetch.lock").exists()


def test_cold_fetch_does_two_gets_and_publishes(tmp_path):
    vdir = tmp_path / "v6"
    http = _http(weights=b"W" * 1000, metadata=b'{"arch":"x"}')
    out = wf.fetch_weights_atomic(
        "http://c", "v6", vdir, http_get=http, http_timeout_s=5,
    )
    assert (out / "weights.pt").read_bytes() == b"W" * 1000
    assert (out / "metadata.json").read_bytes() == b'{"arch":"x"}'
    assert len(http.calls) == 2
    # Lock file released after publish.
    assert not (vdir / ".v6.fetch.lock").exists()


def test_cold_fetch_non_200_raises(tmp_path):
    vdir = tmp_path / "vMISS"
    http = _http(status=404)
    with pytest.raises(RuntimeError, match="GET /v2/weights/vMISS"):
        wf.fetch_weights_atomic(
            "http://c", "vMISS", vdir, http_get=http, http_timeout_s=5,
        )


def test_metadata_non_200_raises(tmp_path):
    vdir = tmp_path / "vM"

    def http_get(url, *, timeout=30.0):
        if url.endswith("/metadata"):
            return 500, b"", {}
        return 200, b"W", {}

    with pytest.raises(RuntimeError, match="/metadata failed"):
        wf.fetch_weights_atomic(
            "http://c", "vM", vdir, http_get=http_get, http_timeout_s=5,
        )


def test_zero_byte_legacy_weights_is_refetched(tmp_path):
    """A pre-fix daemon may have left a 0-byte weights.pt in a shared
    cache. ``_cache_complete`` must treat it as a miss and re-fetch.
    """
    vdir = tmp_path / "v6"
    vdir.mkdir(parents=True)
    (vdir / "weights.pt").write_bytes(b"")  # 0 bytes — the bug residue
    (vdir / "metadata.json").write_bytes(b"{}")
    http = _http(weights=b"REAL-WEIGHTS")
    out = wf.fetch_weights_atomic(
        "http://c", "v6", vdir, http_get=http, http_timeout_s=5,
    )
    assert (out / "weights.pt").read_bytes() == b"REAL-WEIGHTS"
    assert any("/v2/weights/v6" in u for u in http.calls)


def test_concurrent_cold_fetch_all_readers_see_complete_file(tmp_path):
    """REGRESSION (fails on revert to the ``is_file()`` guard).

    N threads hit a cold cache simultaneously through a *slow* fetch
    (modelling the multi-MB Tailscale pull). With the pre-fix guard a
    racing thread observes the half-created file, skips the fetch and
    reads a 0/partial ``weights.pt``. With the atomic + locked fetch
    every thread must end up with a byte-complete file and exactly
    one network fetch happens (the lock collapses the redundant
    cold fetches).
    """
    vdir = tmp_path / "v6"
    full = b"Z" * 500_000
    n = 16
    barrier = threading.Barrier(n)
    results: list[tuple[int, str]] = []
    res_lock = threading.Lock()
    get_count = {"n": 0}

    def http_get(url, *, timeout=30.0):
        with res_lock:
            get_count["n"] += 1
        time.sleep(0.15)  # network-stretched window
        body = b'{"a":1}' if url.endswith("/metadata") else full
        return 200, body, {}

    def worker(i: int):
        barrier.wait()
        try:
            out = wf.fetch_weights_atomic(
                "http://c", "v6", vdir,
                http_get=http_get, http_timeout_s=10,
            )
            # Model the per-game torch.load: read the shared file
            # several times while peers may still be active.
            for _ in range(3):
                data = (out / "weights.pt").read_bytes()
                if data != full:
                    with res_lock:
                        results.append((i, f"PARTIAL len={len(data)}"))
                    return
            with res_lock:
                results.append((i, "OK"))
        except Exception as exc:  # noqa: BLE001
            with res_lock:
                results.append((i, f"RAISED {type(exc).__name__}: {exc}"))

    threads = [threading.Thread(target=worker, args=(i,))
               for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert len(results) == n
    bad = [r for r in results if r[1] != "OK"]
    assert not bad, f"non-OK outcomes: {bad}"
    # The per-version lock collapses N cold fetches into one fetch
    # pair (2 GETs: weights + metadata).
    assert get_count["n"] == 2, (
        f"expected exactly 2 GETs (lock should collapse the race), "
        f"got {get_count['n']}"
    )


# ---------------------------------------------------------------------------
# fetch_weights_if_missing delegation
# ---------------------------------------------------------------------------


def test_claim_loop_delegates_and_returns_version_dir(tmp_path):
    http = _http(weights=b"W", metadata=b"{}")
    out = cl.fetch_weights_if_missing(
        coordinator_url="http://fake:5099",
        version="vD",
        weights_root=tmp_path,
        http_get=http,
    )
    assert out == tmp_path / "vD"
    assert (out / "weights.pt").read_bytes() == b"W"
    # Post-merge fetch_weights_if_missing runs the coherency algorithm
    # + reuses _InterProcessLock directly (no longer delegates to
    # fetch_weights_atomic). Invariant: exactly ONE weights-blob GET.
    assert len([c for c in http.calls if not c.endswith("/metadata")]) == 1
