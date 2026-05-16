"""Atomic, inter-process-safe weights-cache fetch.

Why this module exists
-----------------------

The v2 worker daemon runs games in a
:class:`concurrent.futures.ProcessPoolExecutor` of ``--n-workers``
spawn subprocesses (see
:mod:`mtg_bot.worker_daemon_production_runner`). On the **first**
claim each subprocess processes, it lazily downloads the stage's
weights into a shared on-disk cache
(``<weights_root>/<version>/weights.pt`` + ``metadata.json``) via
``fetch_weights_if_missing``.

The original implementation guarded the download with
``weights_path.is_file()``. That is a textbook TOCTOU race once N
subprocesses on the *same box* hit a cold cache simultaneously:

* ``Path.is_file()`` returns ``True`` the instant
  ``open(path, "wb")`` *creates* the file — **before any bytes are
  written or flushed**. A peer subprocess that observes the
  half-created file skips the fetch and immediately ``torch.load``s
  a 0-byte / partially-written checkpoint.
* ``open(path, "wb")`` *truncates* the file to zero immediately on
  POSIX (no opportunistic lock like Windows), so a second writer can
  truncate the file out from under a peer that is mid-load.

Either way ``torch.load`` raises instantly
(``RuntimeError: PytorchStreamReader failed reading zip archive`` /
``EOFError`` / ``UnpicklingError``) — caught by the production
runner's ``except Exception: log.exception(... game %d crashed ...)``
and reported as an ``outcome="crashed"`` game with ~0.01s duration.

This produces the exact field signature observed on the AWS
c7i.8xlarge economics bench (``--n-workers 30``): **bimodal**
"instant-crash at game start OR fully-normal" — the subprocesses
that lost the race crash every game until the writer finishes, the
rest run normally. ``--n-workers 14`` boxes had a small enough
concurrent-first-claim window that they never tripped it.

The fix
-------

1. **Atomic publish.** Download to a unique per-process temp file in
   the destination directory, then ``os.replace`` it into the final
   path. ``os.replace`` is atomic on POSIX *and* Windows, so a
   reader at the final path *always* sees either no file or a
   byte-complete one — never a partial.

2. **Inter-process lock per version.** A lockfile
   (``<version>.fetch.lock``) serializes the fetch across every
   subprocess on the box. Peers that arrive while one process is
   downloading block on the lock, then re-check and return the
   already-published cache instead of redundantly re-downloading the
   same multi-MB blob.

3. **Completeness re-check inside the lock.** The fast path (both
   files already present) stays lock-free for the common warm-cache
   case; the lock is only taken on a cache miss.

The lock is process-level (``filelock``-style spin on an
exclusively-created lock file) — intentionally dependency-free
(stdlib only) so the worker daemon's minimal bootstrap venv needs
nothing extra.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from pathlib import Path
from typing import Callable, Optional


log = logging.getLogger(__name__)


# How long a peer waits for the lock holder to finish the download
# before giving up. Sized well above a realistic multi-MB Tailscale
# pull (the WEIGHTS_HTTP_TIMEOUT_S in the claim loop is 120s; allow
# headroom for two GETs + disk write).
DEFAULT_LOCK_TIMEOUT_S = 300.0
# Poll interval while spinning on the lock.
_LOCK_POLL_S = 0.1
# A lock file older than this is treated as stale (holder crashed
# mid-fetch) and forcibly reclaimed. Must exceed the longest plausible
# legitimate hold (download + write).
_LOCK_STALE_S = 360.0


class _InterProcessLock:
    """Minimal cross-platform advisory lock backed by exclusive file
    creation (``O_CREAT | O_EXCL``), which is atomic on every OS/FS we
    target. Not reentrant. Released on context exit.

    Stale-lock reclaim: if the lock file exists and is older than
    ``stale_s`` the holder is presumed dead (crashed mid-fetch) and
    the lock file is removed so progress can continue. This keeps a
    crashed subprocess from wedging the whole pool forever.
    """

    def __init__(
        self,
        lock_path: Path,
        *,
        timeout_s: float = DEFAULT_LOCK_TIMEOUT_S,
        poll_s: float = _LOCK_POLL_S,
        stale_s: float = _LOCK_STALE_S,
    ) -> None:
        self._lock_path = Path(lock_path)
        self._timeout_s = timeout_s
        self._poll_s = poll_s
        self._stale_s = stale_s
        self._acquired = False

    def acquire(self) -> None:
        deadline = time.monotonic() + self._timeout_s
        while True:
            try:
                fd = os.open(
                    self._lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                with os.fdopen(fd, "w") as fh:
                    fh.write(f"{os.getpid()} {time.time()}")
                self._acquired = True
                return
            except (FileExistsError, PermissionError):
                # FileExistsError: another holder has the lock.
                # PermissionError: Windows raises this (WinError 5)
                # instead of FileExistsError when the lock file is in
                # a transient delete-pending state — a peer is
                # release()-ing it concurrently. Both mean "couldn't
                # take it this instant": reclaim if stale, else wait
                # and retry. Treating PermissionError as fatal here
                # would spuriously crash a worker the moment two
                # subprocesses contend the lock on Windows.
                if self._reclaim_if_stale():
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"timed out after {self._timeout_s}s waiting "
                        f"for weights-fetch lock {self._lock_path}"
                    )
                time.sleep(self._poll_s)

    def _reclaim_if_stale(self) -> bool:
        try:
            age = time.time() - self._lock_path.stat().st_mtime
        except OSError:
            # Lock vanished between FileExistsError and stat() —
            # it was just released; retry the acquire immediately.
            return True
        if age > self._stale_s:
            log.warning(
                "[weights_fetch] reclaiming stale lock %s (age %.0fs "
                "> %.0fs); previous holder presumed dead",
                self._lock_path, age, self._stale_s,
            )
            try:
                os.unlink(self._lock_path)
            except OSError:
                pass
            return True
        return False

    def release(self) -> None:
        if not self._acquired:
            return
        try:
            os.unlink(self._lock_path)
        except OSError:
            pass
        self._acquired = False

    def __enter__(self) -> "_InterProcessLock":
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()


# Windows ``os.replace`` fails with PermissionError (WinError 5/32)
# when another handle has the *destination* file open — there is no
# POSIX-style atomic-replace-over-open-file. A peer subprocess doing
# ``torch.load(weights.pt)`` holds that handle for a few ms. We retry
# the replace briefly; the reader's load completes and releases the
# handle well within this window. (No-op on POSIX, where the replace
# over an open file just succeeds.)
_REPLACE_RETRY_S: tuple[float, ...] = (0.02, 0.05, 0.1, 0.2, 0.5, 1.0)


def _atomic_write_bytes(target: Path, data: bytes) -> None:
    """Write ``data`` to ``target`` atomically: stage in a unique
    sibling temp file then ``os.replace`` into place.

    ``os.replace`` is an atomic rename on POSIX and Windows, so a
    concurrent reader at ``target`` sees either the old contents (or
    no file) or the fully-written new contents — never a partial.
    The temp file is in the same directory so the rename stays on one
    filesystem (cross-device rename is not atomic).

    Windows quirk: ``os.replace`` raises ``PermissionError`` if a peer
    holds the destination open (no atomic-replace-over-open-handle).
    We retry with short backoff; if a peer meanwhile published an
    identical-length file we treat it as done (the cache is correct
    either way — every writer writes the same coordinator blob).
    """
    tmp = target.with_name(
        f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        last_exc: Optional[OSError] = None
        for delay in (0.0,) + _REPLACE_RETRY_S:
            if delay:
                time.sleep(delay)
            try:
                os.replace(tmp, target)
                return
            except PermissionError as exc:
                last_exc = exc
                # A peer may have already published the same blob
                # while we were blocked on its open handle. If the
                # destination is now byte-complete we're done.
                try:
                    if (
                        target.is_file()
                        and target.stat().st_size == len(data)
                    ):
                        return
                except OSError:
                    pass
                continue
        if last_exc is not None:
            raise last_exc
    finally:
        # Clean up the temp file if the replace didn't consume it
        # (e.g. write failed, or a peer won the publish). Best-effort.
        try:
            if tmp.exists():
                os.unlink(tmp)
        except OSError:
            pass


def _cache_complete(weights_path: Path, metadata_path: Path) -> bool:
    """Both artifacts present AND non-empty. The non-empty check is a
    cheap defense against any legacy 0-byte file a pre-fix daemon may
    have left in a shared cache dir.
    """
    try:
        return (
            weights_path.is_file()
            and metadata_path.is_file()
            and weights_path.stat().st_size > 0
            and metadata_path.stat().st_size > 0
        )
    except OSError:
        return False


def fetch_weights_atomic(
    coordinator_url: str,
    version: str,
    weights_dir: Path,
    *,
    http_get: Callable[..., tuple[int, bytes, dict[str, str]]],
    http_timeout_s: float,
    lock_timeout_s: float = DEFAULT_LOCK_TIMEOUT_S,
) -> Path:
    """Atomically + inter-process-safely populate ``weights_dir`` with
    ``weights.pt`` and ``metadata.json``. Returns ``weights_dir``.

    ``weights_dir`` is the *version* dir (``<root>/<version>``); the
    caller resolves it.

    Fast path (warm cache) is lock-free. On a cache miss the per-
    version lock serializes the download across all box-local
    subprocesses; the first writer publishes atomically and peers
    return the published cache without re-downloading.
    """
    weights_dir = Path(weights_dir)
    weights_path = weights_dir / "weights.pt"
    metadata_path = weights_dir / "metadata.json"

    # Lock-free fast path: warm, complete cache.
    if _cache_complete(weights_path, metadata_path):
        return weights_dir

    weights_dir.mkdir(parents=True, exist_ok=True)
    lock_path = weights_dir / f".{version}.fetch.lock"
    base = coordinator_url.rstrip("/")

    with _InterProcessLock(lock_path, timeout_s=lock_timeout_s):
        # Re-check under the lock: a peer may have published while we
        # waited. This is the branch that turns N redundant cold
        # fetches into exactly one.
        if _cache_complete(weights_path, metadata_path):
            return weights_dir

        def _present(p: Path) -> bool:
            try:
                return p.is_file() and p.stat().st_size > 0
            except OSError:
                return False

        if not _present(weights_path):
            status, body, _ = http_get(
                f"{base}/v2/weights/{version}",
                timeout=http_timeout_s,
            )
            if status != 200:
                raise RuntimeError(
                    f"GET /v2/weights/{version} failed: status={status}"
                )
            _atomic_write_bytes(weights_path, body)

        if not _present(metadata_path):
            status, body, _ = http_get(
                f"{base}/v2/weights/{version}/metadata",
                timeout=http_timeout_s,
            )
            if status != 200:
                raise RuntimeError(
                    f"GET /v2/weights/{version}/metadata failed: "
                    f"status={status}"
                )
            _atomic_write_bytes(metadata_path, body)

    return weights_dir
