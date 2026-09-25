"""Claim/play/report loop for the v2 worker daemon.

Separated from :mod:`mtg_bot.worker_daemon` so the HTTP I/O + the
multiprocessing-pool plumbing don't crowd the Flask handler module.

The actual per-game work — running the PIMC search, accumulating the
training samples, writing the npz — is encapsulated behind a small
``GameRunner`` protocol so tests can swap a stub runner that returns
synthetic results in microseconds. The production runner (kept in this
module for now; lifted from ``cli/shard.py``'s body) is exercised in
the integration test only.

HTTP transport: stdlib ``urllib.request``. The coordinator's v2
endpoints accept plain JSON. Result reporting now uses the
"drop-off + small JSON ping" protocol — the worker drops the npz /
replay blobs into shared storage via :mod:`mtg_bot.worker_daemon_storage`
and POSTs only the URIs + sizes back to ``/v2/report_result``. The
old multipart-POST protocol saturated the coord's single-threaded
WSGI handler under cluster scale (see ``project_mtg_bot_coord_wsgi``
memory); this offloads the file I/O off the coord's request thread.

Backoff schedule on 5xx: 1s / 3s / 10s, then ERROR. Constant
``RETRY_BACKOFF_S`` is exposed for tests.

worker_id resolution: prefer ``~/.mtg_bot_worker_id`` file; if absent,
default to ``socket.gethostname()``. Documented in :func:`resolve_worker_id`.
"""

from __future__ import annotations

import abc
import concurrent.futures
import hashlib
import json
import logging
import os
import shutil
import socket
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from mtg_bot.worker_daemon_storage import ArtifactUploader, NullUploader


log = logging.getLogger(__name__)


# Retry/backoff constants. Tests monkeypatch these to keep wall time
# tiny without paying for real network sleeps.
RETRY_BACKOFF_S: tuple[float, ...] = (1.0, 3.0, 10.0)
DEFAULT_HTTP_TIMEOUT_S = 30.0
# Bounded-drain timeout. When the stage drains (claim returns 204) or
# ``/v2/stop`` fires, ``ClaimLoopRunner.run`` joins its worker threads
# with this timeout. If any thread is wedged in
# ``pool.submit().result()`` (subprocess game hung) the daemon still
# transitions to IDLE so the next stage can start; the hung thread
# stays alive as a daemon thread and dies with the daemon process.
# Without a bounded join, a single hung subprocess wedges the entire
# daemon in STOPPING forever — repro'd on the 2026-05-15 smoke where
# master+mac needed external ``Stop-ScheduledTask`` to recover.
DEFAULT_DRAIN_JOIN_TIMEOUT_S = 60.0
WEIGHTS_HTTP_TIMEOUT_S = 120.0
# How many CONSECUTIVE per-game crashes one claim-loop thread tolerates
# before it gives up and pushes the daemon into ERROR. A single hard
# subprocess death (the documented CPython-3.13 interpreter-corruption
# class that produces ``BrokenProcessPool``) is recoverable: we report
# the claim crashed, rebuild the pool and keep claiming. A *run* of
# them means something structural is wrong (bad weights, OOM, corrupt
# deck pool) and burning through the whole queue reporting "crashed"
# would be worse than parking. Twice on 2026-09-25 (cycles 8 + 9,
# ~1 death per 1,200-1,500 games) a single BrokenProcessPool escaped
# ``run_once`` and parked the daemon for the rest of the stage.
DEFAULT_MAX_CONSECUTIVE_CRASHES = 5
# Cap on the traceback text shipped to the coordinator in the crashed
# report's ``meta``. The full text is logged locally; the wire copy is
# only there so an operator reading runs.db can classify the failure.
MAX_REPORTED_TRACEBACK_CHARS = 4000


# ---------------------------------------------------------------------------
# worker_id resolution
# ---------------------------------------------------------------------------


def _worker_id_file() -> Path:
    """Return the path to the on-disk ``worker_id`` cache.

    Lives under the user's home dir so it survives venv re-creation
    and worktree churn. Operators override per-machine via
    ``MTG_BOT_WORKER_ID_FILE``.
    """
    override = os.environ.get("MTG_BOT_WORKER_ID_FILE")
    if override:
        return Path(override)
    return Path.home() / ".mtg_bot_worker_id"


def resolve_worker_id() -> str:
    """Return the worker_id for ``/v2/claim`` calls.

    Resolution order:

    1. ``MTG_BOT_WORKER_ID`` env var (test/CI override).
    2. Contents of ``~/.mtg_bot_worker_id`` (the cached per-machine ID).
    3. ``socket.gethostname()`` (fallback — also matches the legacy
       ``shard_label`` convention from ``cli/shard.py``).

    No automatic writes to the cache file — operators populate it
    explicitly when they want a stable ID that's different from the
    hostname (e.g. running two daemons on the same box).
    """
    env_val = os.environ.get("MTG_BOT_WORKER_ID")
    if env_val:
        return env_val
    path = _worker_id_file()
    try:
        if path.is_file():
            content = path.read_text(encoding="utf-8").strip()
            if content:
                return content
    except OSError:
        pass
    try:
        return socket.gethostname() or "unknown"
    except OSError:
        return "unknown"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _http_get(url: str, *, timeout: float = DEFAULT_HTTP_TIMEOUT_S) -> tuple[int, bytes, dict[str, str]]:
    """Issue a GET. Returns (status, body, headers). Network errors
    surface as :class:`urllib.error.URLError`.

    HTTP error responses (4xx/5xx) come back as the response object's
    status without raising, so callers can branch on it.
    """
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as e:
        body = b""
        try:
            body = e.read() or b""
        except Exception:
            pass
        return e.code, body, dict(e.headers or {})


def _http_post_json(
    url: str, payload: dict, *, timeout: float = DEFAULT_HTTP_TIMEOUT_S,
) -> tuple[int, bytes, dict[str, str]]:
    """POST a JSON body. Same response convention as :func:`_http_get`."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as e:
        body = b""
        try:
            body = e.read() or b""
        except Exception:
            pass
        return e.code, body, dict(e.headers or {})


# ---------------------------------------------------------------------------
# Weights cache
# ---------------------------------------------------------------------------


# Sidecar that records the fingerprint of the (metadata.json,
# weights.pt) PAIR that is currently cached for a version. Its
# presence is the "this version dir is coherent" signal — a version
# dir without it (or with a stale one) is treated as poisoned and
# re-fetched atomically.
CACHE_FINGERPRINT_FILE = ".cache_fingerprint.json"


class PoisonedWeightsCacheError(RuntimeError):
    """The cached ``(metadata.json, weights.pt)`` pair for a version is
    incoherent — the metadata describes one architecture but the
    ``weights.pt`` state_dict is for a different one.

    Raised LOUDLY (with the offending version + both sides' identities)
    instead of letting ``NNEvaluator.__init__ -> load_state_dict`` blow
    up with an opaque torch state_dict stack trace that crashes every
    game at evaluator init. This is the true cluster "stale node"
    failure mode: a ``v6/metadata.json`` from the old MLP era (no
    ``architecture`` field) paired with a ``v6/weights.pt`` that is the
    structured/transformer checkpoint.
    """


def _weights_dir(weights_root: Path, version: str) -> Path:
    return Path(weights_root) / version


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_fingerprint(version_dir: Path) -> Optional[dict[str, Any]]:
    """Return the cached pair fingerprint sidecar, or ``None`` if it is
    absent / unreadable / malformed (all of which mean "treat the cache
    as un-trustworthy and re-fetch")."""
    fp_path = version_dir / CACHE_FINGERPRINT_FILE
    if not fp_path.is_file():
        return None
    try:
        with fp_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        return data
    except (OSError, ValueError):
        return None


def _is_cache_coherent(
    version_dir: Path, server_metadata_sha: str
) -> bool:
    """A cached version dir is coherent iff:

    1. both ``metadata.json`` and ``weights.pt`` exist, AND
    2. a fingerprint sidecar exists recording the SHA of the pair that
       was atomically written, AND
    3. the sidecar's ``metadata_sha256`` equals the SHA the coordinator
       is serving NOW (so a re-trained checkpoint — which changes
       ``metadata.json``, e.g. its ``git_commit`` — forces a re-fetch),
       AND
    4. the on-disk ``metadata.json`` / ``weights.pt`` still hash to the
       fingerprint's recorded values (so a half-written or tampered
       file is caught even if the metadata SHA happens to match).

    Any failure means "poisoned / stale — re-fetch the pair".
    """
    meta_path = version_dir / "metadata.json"
    weights_path = version_dir / "weights.pt"
    if not (meta_path.is_file() and weights_path.is_file()):
        return False
    fp = _read_fingerprint(version_dir)
    if fp is None:
        return False
    if fp.get("metadata_sha256") != server_metadata_sha:
        return False
    try:
        disk_meta_sha = _sha256(meta_path.read_bytes())
        disk_weights_sha = _sha256(weights_path.read_bytes())
    except OSError:
        return False
    return (
        fp.get("metadata_sha256") == disk_meta_sha
        and fp.get("weights_sha256") == disk_weights_sha
    )


def _os_replace_retry(src: Path, dst: Path, *, attempts: int = 5) -> None:
    """``os.replace`` with a bounded retry on Windows ``PermissionError``.

    On Windows a directory/file rename can transiently fail with
    ``PermissionError`` (winerror 5 / 32) when another handle is open
    (e.g. a peer subprocess mid ``torch.load``, or AV scanning the
    freshly written ``weights.pt``). The rename itself stays atomic —
    we just retry the whole atomic op a few times with a short backoff
    rather than fall back to a non-atomic copy. Mirrors the trainer's
    documented Windows ``os.replace`` retry loop.
    """
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(0.2 * (i + 1))


def _atomic_write_pair(
    weights_root: Path,
    version: str,
    metadata_bytes: bytes,
    weights_bytes: bytes,
) -> Path:
    """Write the ``(metadata.json, weights.pt)`` pair + its fingerprint
    sidecar as ONE atomic unit.

    Strategy: stage all three files into a sibling temp dir under the
    same ``weights_root`` (so the final move is a same-filesystem
    rename, which is atomic), then ``os.replace`` the staged dir into
    the version-dir slot. A reader can therefore only ever see either
    the OLD complete pair or the NEW complete pair — never a
    half-updated mix (old metadata + new weights), which is exactly the
    poisoning the daemon used to crash on.
    """
    weights_root = Path(weights_root)
    weights_root.mkdir(parents=True, exist_ok=True)
    target_dir = _weights_dir(weights_root, version)

    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{version}.staging.", dir=str(weights_root)
        )
    )
    try:
        (staging / "metadata.json").write_bytes(metadata_bytes)
        (staging / "weights.pt").write_bytes(weights_bytes)
        fingerprint = {
            "metadata_sha256": _sha256(metadata_bytes),
            "weights_sha256": _sha256(weights_bytes),
            "version": version,
            "written_at": time.time(),
        }
        (staging / CACHE_FINGERPRINT_FILE).write_text(
            json.dumps(fingerprint, indent=2), encoding="utf-8"
        )
        # Replace the slot atomically. ``os.replace`` onto an existing
        # directory fails on every OS, so swap the old dir out first.
        if target_dir.exists():
            trash = Path(
                tempfile.mkdtemp(
                    prefix=f".{version}.trash.", dir=str(weights_root)
                )
            )
            trash_inner = trash / "old"
            _os_replace_retry(target_dir, trash_inner)
            try:
                _os_replace_retry(staging, target_dir)
            finally:
                shutil.rmtree(trash, ignore_errors=True)
        else:
            _os_replace_retry(staging, target_dir)
        staging = None  # consumed by os.replace; don't rmtree it
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
    return target_dir


def fetch_weights_if_missing(
    coordinator_url: str,
    version: str,
    weights_root: Path,
    *,
    http_get: Callable[..., tuple[int, bytes, dict[str, str]]] = _http_get,
    verify_coherent: bool = True,
) -> Path:
    """Ensure a COHERENT ``<weights_root>/<version>/{metadata.json,
    weights.pt}`` pair exists locally, fetching from
    ``<coordinator_url>/v2/weights/<version>`` (+ ``/metadata``) when
    the cache is missing OR poisoned. Returns the version dir.

    Coherency model (the core of the fix for the cluster "stale node"
    100%-crash): the two files for a version label can become
    MISMATCHED when one is re-fetched without the other. Observed on a
    real node: ``v6/metadata.json`` from the old MLP era (no
    ``architecture`` field) paired with ``v6/weights.pt`` that is the
    structured checkpoint -> the daemon builds the wrong model class ->
    ``load_state_dict`` raises and every game crashes at evaluator
    init. Fix: the metadata sidecar is the cheap, always-current
    source of truth -- we ALWAYS fetch ``/metadata`` first, hash it,
    and compare against a fingerprint sidecar written when the pair
    was last published; on miss / fingerprint-absent / server-SHA-
    changed / on-disk-drift we re-fetch BOTH and publish via a temp
    dir + atomic rename so a reader never sees a half-updated pair.

    ``verify_coherent`` (default True) also runs the defensive load-
    time check :func:`assert_metadata_weights_coherent` so a structural
    disagreement that slipped through (or a coordinator serving a
    poisoned pair) fails LOUDLY with
    :class:`PoisonedWeightsCacheError`, not an opaque torch state_dict
    trace inside ``NNEvaluator``.

    Concurrency: the cold-fetch path is serialized by a per-version
    inter-process lock
    (:class:`mtg_bot.worker_daemon_weights_fetch._InterProcessLock`),
    so the N ``--n-workers`` subprocesses that hit a cold cache on
    their first claim collapse into exactly ONE fetch -- closing the
    TOCTOU torn-read that crashed 72/100 games at game start on the
    c7i.8xlarge (``--n-workers 30``) bench, while the atomic
    ``_atomic_write_pair`` publish keeps the pair coherent. The lock
    file lives in ``weights_root`` (NOT the version dir, which
    ``_atomic_write_pair`` swaps wholesale).
    """
    from mtg_bot.worker_daemon_weights_fetch import _InterProcessLock

    weights_root = Path(weights_root)
    weights_root.mkdir(parents=True, exist_ok=True)
    target_dir = _weights_dir(weights_root, version)
    base = coordinator_url.rstrip("/")

    def _server_meta_and_coherent() -> "tuple[bytes, bool]":
        status, metadata_bytes, _ = http_get(
            f"{base}/v2/weights/{version}/metadata",
            timeout=WEIGHTS_HTTP_TIMEOUT_S,
        )
        if status != 200:
            raise RuntimeError(
                f"GET /v2/weights/{version}/metadata failed: "
                f"status={status}"
            )
        return metadata_bytes, _is_cache_coherent(
            target_dir, _sha256(metadata_bytes)
        )

    # Lock-free fast path: pair already coherent w.r.t. live metadata.
    _metadata_bytes, coherent = _server_meta_and_coherent()
    if coherent:
        if verify_coherent:
            assert_metadata_weights_coherent(target_dir)
        return target_dir

    # Cold / poisoned: serialize concurrent cold fetches across the
    # box-local subprocess pool; first writer publishes the coherent
    # pair atomically, peers re-check under the lock and return it.
    lock_path = weights_root / f".{version}.fetch.lock"
    with _InterProcessLock(lock_path):
        metadata_bytes, coherent = _server_meta_and_coherent()
        if not coherent:
            status, weights_bytes, _ = http_get(
                f"{base}/v2/weights/{version}",
                timeout=WEIGHTS_HTTP_TIMEOUT_S,
            )
            if status != 200:
                raise RuntimeError(
                    f"GET /v2/weights/{version} failed: status={status}"
                )
            target_dir = _atomic_write_pair(
                weights_root, version, metadata_bytes, weights_bytes
            )
    if verify_coherent:
        assert_metadata_weights_coherent(target_dir)
    return target_dir


# ---------------------------------------------------------------------------
# Defensive load-time coherency check (defense-in-depth)
# ---------------------------------------------------------------------------


# state_dict key fragments that uniquely identify the structured
# transformer checkpoint (``StructuredModel``). None of these appear in
# the flat-feature MLP dual-head models (``_ValuePolicyMLP`` /
# ``_ValuePolicyMLPSeparate``), whose trunk keys look like
# ``trunk.0.weight``. We don't import torch here (the claim-loop module
# is deliberately torch-free); ``weights.pt`` is a zip whose member
# names embed the state_dict keys, so a cheap substring scan over the
# raw bytes is enough to tell the two architectures apart without
# materializing tensors.
_STRUCTURED_STATE_DICT_MARKERS: tuple[bytes, ...] = (
    b"cls_token",
    b"printing_embed",
    b"trunk.layers.0.self_attn",
)
_MLP_STATE_DICT_MARKERS: tuple[bytes, ...] = (
    b"trunk.0.weight",
)


def _weights_pt_looks_structured(weights_path: Path) -> Optional[bool]:
    """Best-effort architecture sniff of a ``weights.pt`` zip.

    Returns ``True`` if it carries structured-model markers, ``False``
    if it carries flat-MLP markers, ``None`` if indeterminate (an
    unreadable / tiny / synthetic test blob — callers treat ``None`` as
    "can't tell, don't block").
    """
    try:
        raw = weights_path.read_bytes()
    except OSError:
        return None
    if any(m in raw for m in _STRUCTURED_STATE_DICT_MARKERS):
        return True
    if any(m in raw for m in _MLP_STATE_DICT_MARKERS):
        return False
    return None


def assert_metadata_weights_coherent(version_dir: Path) -> None:
    """Raise :class:`PoisonedWeightsCacheError` if the cached
    ``metadata.json`` and ``weights.pt`` disagree about the model
    architecture, BEFORE the opaque torch ``load_state_dict`` does.

    The disagreement we catch is exactly the production failure: the
    metadata says (or back-compat-defaults to) the flat-feature MLP
    dual-head model, but ``weights.pt`` is the structured/transformer
    checkpoint (or vice versa). The MLP path is what the loader builds
    when ``architecture`` is absent, so an OLD metadata.json next to a
    NEW structured weights.pt is the poisoned case.

    Indeterminate inputs (synthetic test blobs, missing files) are NOT
    flagged — this is a targeted defense against the known poisoning,
    not a general weight validator. The structural fix
    (atomic coherent caching) is primary; this is defense-in-depth so a
    poisoned pair — even one a misconfigured coordinator serves — fails
    with a clear diagnostic instead of a 100%-crash.
    """
    version_dir = Path(version_dir)
    meta_path = version_dir / "metadata.json"
    weights_path = version_dir / "weights.pt"
    if not (meta_path.is_file() and weights_path.is_file()):
        return

    try:
        with meta_path.open("r", encoding="utf-8") as f:
            metadata = json.load(f)
        if not isinstance(metadata, dict):
            metadata = {}
    except (OSError, ValueError):
        # Unreadable metadata is its own failure mode handled
        # elsewhere; don't double-report here.
        return

    training = metadata.get("training") if isinstance(
        metadata.get("training"), dict
    ) else {}
    declared_arch = metadata.get("architecture") or training.get(
        "architecture"
    )
    # The loader back-compat-defaults a MISSING architecture to the
    # flat-MLP dual-head path (``_ValuePolicyMLP``) — that's precisely
    # what builds the wrong class for a structured weights.pt.
    effective_arch = declared_arch or "shared"

    weights_is_structured = _weights_pt_looks_structured(weights_path)
    if weights_is_structured is None:
        return  # can't tell — don't block (synthetic test blob etc.)

    metadata_is_structured = effective_arch == "structured"
    if weights_is_structured == metadata_is_structured:
        return  # coherent

    weights_desc = (
        "structured/transformer checkpoint"
        if weights_is_structured
        else "flat-feature MLP checkpoint"
    )
    meta_desc = (
        "structured"
        if metadata_is_structured
        else f"{effective_arch!r} (flat-feature MLP)"
        + ("" if declared_arch else " [architecture field ABSENT]")
    )
    raise PoisonedWeightsCacheError(
        f"poisoned weights cache for {version_dir.name!r}: "
        f"metadata says architecture={meta_desc} but weights.pt is a "
        f"{weights_desc}. The cached (metadata.json, weights.pt) pair "
        f"is incoherent — delete {version_dir} and let the daemon "
        f"re-fetch a coherent pair, or fix the coordinator's served "
        f"pair for this version."
    )


# ---------------------------------------------------------------------------
# Game runner protocol
# ---------------------------------------------------------------------------


@dataclass
class GameResult:
    """Per-game result the runner returns to the claim loop.

    Maps 1:1 onto the ``/v2/report_result`` ``meta`` JSON the
    coordinator expects, plus the optional npz / replay bytes.
    """

    outcome: str  # "completed" | "timed_out" | "crashed"
    winner: Optional[int] = None  # 0/1 in self-play
    n_samples: int = 0
    duration_s: float = 0.0
    wins_new: Optional[int] = None  # eval only
    wins_old: Optional[int] = None  # eval only
    draws: Optional[int] = None  # eval only
    npz_bytes: Optional[bytes] = None
    replay_bytes: Optional[bytes] = None
    # Failure detail for ``outcome == "crashed"`` reports. Surfaces on
    # the wire as ``meta["traceback"]`` so the coordinator's
    # ``claims.report_json`` records WHY a game died (a bare
    # ``crashed`` row is indistinguishable between "pool died" and
    # "the game body threw").
    error_traceback: Optional[str] = None


class GameRunner(abc.ABC):
    """Protocol the claim loop drives. Concrete implementations live
    near the production self-play / eval machinery; tests pass a
    callable-backed stub instead."""

    @abc.abstractmethod
    def setup(
        self,
        coordinator_url: str,
        weights_root: Path,
        stage_kind: str,
        n_workers: int,
    ) -> None:
        ...

    @abc.abstractmethod
    def play_one_game(self, claim: dict, shard_label: str) -> GameResult:
        ...

    @abc.abstractmethod
    def teardown(self) -> None:
        ...

    # -- optional pool-recovery surface -------------------------------
    #
    # Concrete (NOT abstract) so every existing runner / test stub
    # keeps working unchanged. Runners that own a
    # :class:`concurrent.futures.ProcessPoolExecutor` override these so
    # the claim loop can rebuild a pool that a hard subprocess death
    # left permanently broken.

    def pool_generation(self) -> int:
        """Monotonic id of the runner's current process pool.

        ``0`` for runners that own no pool. The claim loop reads this
        BEFORE dispatching a game and hands it back to
        :meth:`reset_pool`, so N threads that all trip over the same
        dead pool collapse into a single rebuild.
        """
        return 0

    def reset_pool(self, generation: Optional[int] = None) -> int:
        """Rebuild the process pool; return the (possibly unchanged)
        generation.

        ``generation`` is the value :meth:`pool_generation` returned
        before the failing game. When it no longer matches the live
        generation a peer thread already rebuilt after the same
        failure and this call is a no-op. A return value equal to the
        caller's ``generation`` means "nothing was rebuilt".
        """
        return 0


class CallableGameRunner(GameRunner):
    """Adapter that wraps a plain ``Callable[[claim, shard_label], GameResult]``.

    Production code can pass a closure that owns the NN evaluator + SHM
    server. Tests pass a closure that synthesizes a result without
    touching torch.
    """

    def __init__(
        self,
        play_one: Callable[[dict, str], GameResult],
        setup_fn: Optional[Callable[[str, Path, str, int], None]] = None,
        teardown_fn: Optional[Callable[[], None]] = None,
        reset_pool_fn: Optional[Callable[[Optional[int]], int]] = None,
        pool_generation_fn: Optional[Callable[[], int]] = None,
    ):
        self._play_one = play_one
        self._setup = setup_fn
        self._teardown = teardown_fn
        self._reset_pool = reset_pool_fn
        self._pool_generation = pool_generation_fn

    def setup(self, coordinator_url, weights_root, stage_kind, n_workers):
        if self._setup is not None:
            self._setup(coordinator_url, weights_root, stage_kind, n_workers)

    def play_one_game(self, claim, shard_label):
        return self._play_one(claim, shard_label)

    def teardown(self):
        if self._teardown is not None:
            self._teardown()

    def pool_generation(self) -> int:
        if self._pool_generation is None:
            return 0
        return int(self._pool_generation())

    def reset_pool(self, generation: Optional[int] = None) -> int:
        if self._reset_pool is None:
            return 0 if generation is None else int(generation)
        return int(self._reset_pool(generation))


# ---------------------------------------------------------------------------
# Claim loop
# ---------------------------------------------------------------------------


@dataclass
class ClaimLoopConfig:
    coordinator_url: str
    stage_id: str
    kind: str  # "self_play" | "eval"
    n_workers: int
    worker_id: str
    weights_root: Path
    shard_label: str
    # Optional deck pool path. Phase 2c production runner uses this
    # to load the deck pool once at setup time. ``None`` falls back to
    # the system-wide default (currently
    # ``data/17lands/eoe_decks.json.gz`` under the daemon's cwd).
    # Plumbed through here rather than on the wire claim payload so
    # the deck pool doesn't have to round-trip through every /v2/claim
    # response — workers and coordinator already share the file at
    # deploy time, this is just naming.
    deck_pool_path: Optional[str] = None
    # Worker-owned NN-eval device selector from the daemon's
    # ``--nn-device`` flag, same plumbing class as ``deck_pool_path`` /
    # ``n_workers`` (per-machine operational config baked into the
    # native service file, NOT part of the orchestrator's /v2/start_*
    # body). ``None`` (== ``--nn-device cpu``) is the historical
    # CPU-only path and is byte-identical to the pre-flag behavior.
    # ``"auto"`` / ``"cuda"`` are carried verbatim into the production
    # runner and resolved per-worker inside ``NNPimcConfig.build()``;
    # the daemon parent / claim-loop thread never touches the CUDA
    # driver, so the subprocess pool's per-worker context init stays
    # Windows-spawn / Linux-fork-safe.
    nn_device: Optional[str] = None
    # Retry/backoff. Tests slam this to zero.
    retry_backoff_s: tuple[float, ...] = field(
        default_factory=lambda: RETRY_BACKOFF_S
    )
    # Bounded-drain timeout — see ``DEFAULT_DRAIN_JOIN_TIMEOUT_S``.
    # Tests can shorten this to keep wall time tiny when simulating
    # hung threads.
    drain_join_timeout_s: float = DEFAULT_DRAIN_JOIN_TIMEOUT_S
    # Consecutive per-thread game crashes tolerated before the daemon
    # parks in ERROR. See ``DEFAULT_MAX_CONSECUTIVE_CRASHES``. Tests
    # set this to 1 to exercise the escalation path in one game.
    max_consecutive_crashes: int = DEFAULT_MAX_CONSECUTIVE_CRASHES
    # HTTP transport hooks. Overridable for testing.
    http_get: Callable[..., tuple[int, bytes, dict[str, str]]] = field(
        default=_http_get
    )
    http_post_json: Callable[..., tuple[int, bytes, dict[str, str]]] = field(
        default=_http_post_json
    )
    # Drop-off-protocol artifact uploader. Workers no longer multipart-
    # POST .npz bytes to the coord; they upload to shared storage via
    # this uploader and POST only the URI back. Production wires
    # ``uploader_from_uri(--artifact-storage-uri)`` (s3:// or file://);
    # tests default to ``NullUploader`` so the wire shape works without
    # standing up real storage. See
    # :mod:`mtg_bot.worker_daemon_storage` + ``project_mtg_bot_coord_wsgi``
    # memory for the why.
    artifact_uploader: ArtifactUploader = field(
        default_factory=NullUploader
    )


class ClaimLoopRunner:
    """Owns the claim/play/report loop for one stage.

    Run as a single background thread on the worker daemon. The
    multiprocessing pool that fans out the per-game work lives inside
    the supplied :class:`GameRunner` (production) or runs single-
    threaded in the supplied callable (tests). The runner itself just
    orchestrates the per-claim wire calls.
    """

    def __init__(
        self,
        cfg: ClaimLoopConfig,
        state_callbacks: "StateCallbacks",
        runner: GameRunner,
    ):
        self.cfg = cfg
        self.state = state_callbacks
        self.runner = runner
        # Pool-rebuild reporting dedup. All N claim threads trip over
        # the same dead pool and all N call ``reset_pool``; only one
        # of them actually rebuilds, but every one of them observes a
        # bumped generation. Report the rebuild once.
        self._pool_reset_lock = threading.Lock()
        self._last_reported_pool_generation = 0

    # ------------------------------------------------------------------

    def _coord_url(self, path: str) -> str:
        return f"{self.cfg.coordinator_url.rstrip('/')}{path}"

    def _claim_one(self) -> Optional[dict]:
        """POST /v2/claim. Returns the parsed body on 200, or None
        on 204 (drain). 5xx triggers backoff+retry. 4xx other than
        404 raises.
        """
        url = self._coord_url("/v2/claim")
        body = {"worker_id": self.cfg.worker_id, "stage_id": self.cfg.stage_id}
        last_err: Optional[str] = None
        for attempt, delay in enumerate((0.0,) + tuple(self.cfg.retry_backoff_s)):
            if delay > 0:
                time.sleep(delay)
            try:
                status, resp_body, _ = self.cfg.http_post_json(url, body)
            except (urllib.error.URLError, OSError) as e:
                # URLError covers connect failures; a bare OSError
                # (socket.timeout / TimeoutError, ConnectionResetError,
                # RemoteDisconnected) is what urllib raises when the
                # coordinator goes quiet AFTER the connection is up --
                # the remote-worker-over-flaky-tailnet case. Both are
                # transient: back off and retry, never crash the thread.
                last_err = f"{type(e).__name__} attempt {attempt}: {e}"
                log.warning("[claim_loop] %s", last_err)
                continue
            if status == 200:
                return json.loads(resp_body.decode("utf-8"))
            if status == 204:
                return None
            if 500 <= status < 600:
                last_err = f"HTTP {status} on /v2/claim attempt {attempt}"
                log.warning("[claim_loop] %s", last_err)
                continue
            # 4xx other than the well-known 204 path: fatal.
            raise RuntimeError(
                f"/v2/claim returned {status}: {resp_body[:200]!r}"
            )
        # Exhausted retries.
        raise RuntimeError(last_err or "/v2/claim retries exhausted")

    def _report_one(self, claim: dict, result: GameResult) -> str:
        """Drop the result's blobs into shared storage, then POST a
        JSON meta + URI ping to ``/v2/report_result``.

        Returns one of ``"accepted"`` / ``"conflict"`` / ``"unknown"``.
        5xx triggers backoff+retry. Both 200 and 202 are treated as
        success — Phase 2B will switch the coord to 202 (returns
        immediately, rehydrates blobs from the URI off-thread); during
        the rollout the old 200 path still works.
        """
        meta: dict[str, Any] = {
            "claim_id": claim["claim_id"],
            "outcome": result.outcome,
            "winner": result.winner,
            "n_samples": result.n_samples,
            "duration_s": result.duration_s,
            "shard_label": self.cfg.shard_label,
        }
        # Eval extras — coordinator's record_report reads them off
        # the meta JSON and lands them on the results row.
        if result.wins_new is not None:
            meta["wins_new"] = result.wins_new
        if result.wins_old is not None:
            meta["wins_old"] = result.wins_old
        if result.draws is not None:
            meta["draws"] = result.draws
        # Crash forensics. ``record_report`` stores the whole meta dict
        # verbatim in ``claims.report_json``, so this is how an
        # operator tells a BrokenProcessPool death apart from a game
        # body that threw.
        if result.error_traceback:
            meta["traceback"] = (
                result.error_traceback[:MAX_REPORTED_TRACEBACK_CHARS]
            )

        # Upload artifacts FIRST so the URI is in hand by the time we
        # POST the meta. Failed uploads surface as exceptions and
        # propagate up to the claim-loop's crash handler (which then
        # reports a "crashed" outcome) — same shape as a runner
        # exception. The uploader is deterministic in the claim_id,
        # so a retry produces the same URI; a partial-upload then
        # full-upload cycle ends with the coord seeing one canonical
        # URI either way.
        npz_uri: Optional[str] = None
        replay_uri: Optional[str] = None
        if result.npz_bytes:
            npz_uri = self.cfg.artifact_uploader.upload(
                result.npz_bytes,
                kind="npz",
                stage_id=self.cfg.stage_id,
                shard_label=self.cfg.shard_label,
                claim_id=claim["claim_id"],
            )
        if result.replay_bytes:
            replay_uri = self.cfg.artifact_uploader.upload(
                result.replay_bytes,
                kind="replay",
                stage_id=self.cfg.stage_id,
                shard_label=self.cfg.shard_label,
                claim_id=claim["claim_id"],
            )

        body = {
            "meta": meta,
            "npz_uri": npz_uri,
            "replay_uri": replay_uri,
            "npz_size_bytes": (
                len(result.npz_bytes) if result.npz_bytes else 0
            ),
            "replay_size_bytes": (
                len(result.replay_bytes) if result.replay_bytes else 0
            ),
        }

        url = self._coord_url("/v2/report_result")
        last_err: Optional[str] = None
        for attempt, delay in enumerate((0.0,) + tuple(self.cfg.retry_backoff_s)):
            if delay > 0:
                time.sleep(delay)
            try:
                status, resp_body, _ = self.cfg.http_post_json(url, body)
            except (urllib.error.URLError, OSError) as e:
                # Same transient-transport set as _claim_one.
                last_err = f"{type(e).__name__} attempt {attempt}: {e}"
                log.warning("[report_loop] %s", last_err)
                continue
            # 200 = legacy synchronous coord path (Phase 1 + early 2A
            # rollout). 202 = Phase 2B's async-write coord (rehydrates
            # the blob off-thread; returns immediately). Accept both
            # during the rollout window.
            if status in (200, 202):
                return "accepted"
            if status == 409:
                # Late duplicate / re-delivered claim. Per-doc: drop
                # and continue the loop. NOT an error.
                return "conflict"
            if status == 404:
                # The coordinator doesn't know this claim_id. Rare —
                # only happens if the queue.db was wiped between claim
                # and report. Treat as conflict so the loop continues.
                return "unknown"
            if 500 <= status < 600:
                last_err = (
                    f"HTTP {status} on /v2/report_result attempt {attempt}"
                )
                log.warning("[report_loop] %s", last_err)
                continue
            raise RuntimeError(
                f"/v2/report_result returned {status}: {resp_body[:200]!r}"
            )
        raise RuntimeError(last_err or "/v2/report_result retries exhausted")

    # ------------------------------------------------------------------

    def _recover_pool(self, generation: int, thread_id: int) -> None:
        """Rebuild the runner's process pool after a hard subprocess
        death and record the reset on the daemon's counters.

        Safe under concurrency: every claim-loop thread passes the
        generation it *observed* before its game, so the first thread
        through rebuilds and the peers (which tripped over the same
        dead pool) see a bumped generation and no-op. Runners that own
        no pool return the caller's generation unchanged and nothing
        is counted.
        """
        try:
            new_generation = int(self.runner.reset_pool(generation))
        except Exception:
            # A failed rebuild is not itself fatal - the next game will
            # trip the same BrokenProcessPool and try again, and the
            # consecutive-crash counter bounds how long that can go on.
            log.exception("[claim_loop] pool rebuild failed")
            return
        if new_generation == generation:
            # Pool-less runner, or the runner declined to rebuild.
            return
        with self._pool_reset_lock:
            if new_generation <= self._last_reported_pool_generation:
                # A peer thread already reported this same rebuild.
                return
            self._last_reported_pool_generation = new_generation
        log.warning(
            "[claim_loop] thread %d rebuilt the process pool "
            "(generation %d -> %d)",
            thread_id, generation, new_generation,
        )
        if self.state.on_pool_reset is not None:
            self.state.on_pool_reset(thread_id, new_generation)

    def run_once(self, thread_id: int = 0) -> str:
        """Run one full claim/play/report turn.

        Returns:
        - ``"drained"`` if /claim returned 204 (loop should exit).
        - ``"continue"`` after a successful report (or 409 drop).
        - ``"crashed"`` when the runner blew up mid-game. The claim was
          reported ``crashed``, the process pool was rebuilt if it was
          the pool that died, and the caller decides whether this is
          the Nth consecutive failure that warrants ERROR.
        """
        if self.state.is_stop_requested():
            return "drained"
        claim = self._claim_one()
        if claim is None:
            return "drained"
        self.state.on_claim()
        # Snapshot the pool identity BEFORE the game so a rebuild
        # triggered by a peer thread (same dead pool, different claim)
        # doesn't get duplicated.
        try:
            pool_generation = int(self.runner.pool_generation())
        except Exception:  # noqa: BLE001 - duck-typed/stub runners
            pool_generation = 0
        try:
            t0 = time.perf_counter()
            result = self.runner.play_one_game(claim, self.cfg.shard_label)
            # If the runner didn't populate duration_s itself, fill it.
            if result.duration_s == 0.0:
                result.duration_s = time.perf_counter() - t0
        except Exception as exc:
            # Runner crashed mid-game. Report a "crashed" outcome so
            # the coordinator's queue accounting stays sane, rebuild
            # the pool if this was a hard subprocess death, then hand
            # "crashed" back to the caller instead of re-raising. A
            # single dead pool worker used to kill the claim thread and
            # park the whole daemon in ERROR for the rest of the stage.
            tb = traceback.format_exc()
            log.exception("[claim_loop] game crashed on thread %d", thread_id)
            crashed = GameResult(
                outcome="crashed",
                duration_s=time.perf_counter() - t0,
                error_traceback=tb,
            )
            try:
                self._report_one(claim, crashed)
            except Exception:
                log.exception("[claim_loop] failed to report crashed game")
            self.state.on_drop()
            if isinstance(exc, concurrent.futures.BrokenExecutor):
                # A broken ProcessPoolExecutor is permanently unusable:
                # every subsequent submit() raises immediately. Rebuild
                # it or the daemon spins reporting "crashed" forever.
                self._recover_pool(pool_generation, thread_id)
            if self.state.on_game_crash is not None:
                self.state.on_game_crash(thread_id, tb)
            return "crashed"
        outcome = self._report_one(claim, result)
        if outcome == "accepted":
            self.state.on_report()
        else:
            # 409 / unknown — drop without crediting games_done.
            self.state.on_drop()
        return "continue"

    def run(self) -> None:
        """Main loop body. Spawns ``cfg.n_workers`` parallel
        claim/play/report threads so the daemon plays up to N games
        concurrently. Returns when the stage drains, ``/v2/stop``
        fires, or a fatal error pushes the daemon into ERROR.

        Each thread independently calls :meth:`run_once` in its own
        ``while`` loop — ``WorkerState``'s counters are already lock-
        protected and the production runner's per-version weight
        cache is guarded by the runner itself, so the threads share
        no mutable state that needs additional synchronization here.

        ``n_workers`` is clamped to ``>=1`` — a single-threaded daemon
        is still a valid configuration (and is what tests exercise).
        """
        try:
            self.runner.setup(
                self.cfg.coordinator_url,
                self.cfg.weights_root,
                self.cfg.kind,
                self.cfg.n_workers,
            )
        except Exception:
            self.state.mark_error(
                f"runner setup failed: {traceback.format_exc()}"
            )
            return
        # Setup done — pool/NN are ready to play games.
        self.state.mark_running()

        n_threads = max(1, int(self.cfg.n_workers))
        # Set by any thread that crashes — guards the post-join
        # mark_stopping/mark_idle so we don't clobber ERROR state.
        crashed_flag = threading.Event()

        max_consecutive = max(1, int(self.cfg.max_consecutive_crashes))

        def _thread_body(tid: int) -> None:
            consecutive_crashes = 0
            try:
                while True:
                    if self.state.is_stop_requested():
                        break
                    status = self.run_once(tid)
                    if status == "drained":
                        break
                    if status == "crashed":
                        consecutive_crashes += 1
                        if consecutive_crashes >= max_consecutive:
                            # Recovery isn't working - something
                            # structural is wrong. Park the daemon so a
                            # human looks at it rather than chewing
                            # through the queue reporting "crashed".
                            crashed_flag.set()
                            self.state.mark_error(
                                f"claim loop thread {tid} gave up after "
                                f"{consecutive_crashes} consecutive game "
                                f"crashes (limit {max_consecutive})"
                            )
                            break
                        continue
                    if consecutive_crashes:
                        # A clean game clears the streak - the pool
                        # rebuild worked.
                        consecutive_crashes = 0
                        if self.state.on_thread_recovered is not None:
                            self.state.on_thread_recovered(tid)
            except Exception:
                # Non-game failures (claim/report retries exhausted,
                # artifact upload wedged, ...) are still fatal: they
                # aren't something a pool rebuild fixes. ``mark_error``
                # flips ``stop_requested`` so peer threads exit on
                # their next loop iteration.
                crashed_flag.set()
                self.state.mark_error(
                    f"claim loop thread {tid} crashed: "
                    f"{traceback.format_exc()}"
                )

        threads = [
            threading.Thread(
                target=_thread_body, args=(tid,),
                daemon=True, name=f"claim-loop-{tid}",
            )
            for tid in range(n_threads)
        ]
        for t in threads:
            t.start()
        # Bounded join — but ONLY enforce the timeout once stop has
        # been requested. Natural drain (claim returns 204 because the
        # queue is empty) lets a thread finish its current game first,
        # and that wait can legitimately reach ``per_game_timeout_sec``
        # (~600s in production). If we time-bound the natural-drain
        # path, in-progress games get abandoned, their claims rot in
        # the coordinator's queue.db until claim_ttl_seconds expires,
        # and the stage's done counter undercounts. Repro'd on the
        # 2026-05-15 post-bounded-drain smoke: master claimed 14
        # games, completed 4 in the 60s window, abandoned the other
        # 10 mid-game → coordinator stuck with 8 in_flight forever.
        # The timeout still kicks in once ``stop_requested`` fires
        # (e.g. /v2/stop arrived or a peer thread crashed), which is
        # the only scenario where the daemon has been told to abort
        # rather than to finish what it has.
        timeout_s = float(self.cfg.drain_join_timeout_s)
        stop_deadline: Optional[float] = None
        stuck_threads: list[str] = []
        for t in threads:
            while t.is_alive():
                if stop_deadline is not None:
                    remaining = max(0.0, stop_deadline - time.monotonic())
                    if remaining <= 0:
                        stuck_threads.append(t.name)
                        break
                    t.join(timeout=min(remaining, 2.0))
                else:
                    # No stop observed yet: poll briefly and re-check
                    # ``is_stop_requested`` between waits so a /v2/stop
                    # mid-drain transitions us into bounded mode within
                    # ~2s.
                    t.join(timeout=2.0)
                    if t.is_alive() and self.state.is_stop_requested():
                        stop_deadline = time.monotonic() + timeout_s
        if stuck_threads:
            log.warning(
                "[claim_loop] %d/%d threads still alive %.1fs after "
                "stop was requested: %s. Abandoning them as daemon "
                "threads and transitioning to IDLE so the next stage "
                "can start; they'll die with the daemon process.",
                len(stuck_threads), len(threads),
                timeout_s, stuck_threads,
            )

        try:
            self.runner.teardown()
        except Exception:
            log.exception("[claim_loop] runner.teardown failed")

        # If any thread pushed the daemon into ERROR the state already
        # reflects that — stay there. Otherwise normal completion:
        # mark STOPPING (in case it was already, this is idempotent)
        # then IDLE. Stuck threads are abandoned — the IDLE transition
        # is correct from the operational standpoint (daemon ready for
        # next stage); subprocess leaks (if any) are bounded by the
        # number of stuck games per stage, which is rare.
        if not crashed_flag.is_set():
            self.state.mark_stopping()
            self.state.mark_idle()


# ---------------------------------------------------------------------------
# State-callback adapter
# ---------------------------------------------------------------------------


@dataclass
class StateCallbacks:
    """Tiny adapter so :class:`ClaimLoopRunner` doesn't import
    :mod:`mtg_bot.worker_daemon` directly (would be a cycle since
    worker_daemon imports the loop module).
    """

    is_stop_requested: Callable[[], bool]
    on_claim: Callable[[], None]
    on_report: Callable[[], None]
    on_drop: Callable[[], None]
    mark_running: Callable[[], None]
    mark_stopping: Callable[[], None]
    mark_idle: Callable[[], None]
    mark_error: Callable[[str], None]
    # Crash-recovery telemetry. Optional so every existing
    # ``StateCallbacks(...)`` construction (tests + the daemon's own
    # pre-recovery wiring) keeps working; ``None`` just drops the
    # event. ``worker_daemon.create_app`` wires all three so the
    # counters surface on ``/v2/heartbeat``.
    #
    # - ``on_game_crash(thread_id, traceback_text)``: a game died and
    #   was reported ``crashed``; the thread is still alive.
    # - ``on_pool_reset(thread_id, generation)``: the runner's process
    #   pool was actually rebuilt (peers that no-op'd don't fire).
    # - ``on_thread_recovered(thread_id)``: a clean game cleared the
    #   thread's consecutive-crash streak.
    on_game_crash: Optional[Callable[[int, str], None]] = None
    on_pool_reset: Optional[Callable[[int, int], None]] = None
    on_thread_recovered: Optional[Callable[[int], None]] = None


# ---------------------------------------------------------------------------
# Production game-runner builders.
#
# The real game-execution body — torch model load, deck pool sample,
# NN-PIMC search, npz-bytes encode — lives in
# :mod:`mtg_bot.worker_daemon_production_runner` so heavy torch / numpy
# imports don't fire at worker_daemon import time. We re-export the
# factories here as a back-compat surface (Phase 2b code calls them
# under these names) and delegate via lazy import.
# ---------------------------------------------------------------------------


def build_production_self_play_runner(
    coordinator_url: str,
    stage_id: str,
    n_workers: int,
    weights_cache_root: Path,
    worker_id: str,
    log_event: Optional[Callable[[str, dict], None]] = None,
    *,
    deck_pool_path: Optional[str] = None,
    http_get: Callable[..., tuple[int, bytes, dict[str, str]]] = _http_get,
) -> "GameRunner":
    """Construct the production self-play GameRunner.

    Heavy imports (torch, numpy, the data_gen game body) are deferred
    to the first ``setup`` call by routing through
    :func:`mtg_bot.worker_daemon_production_runner.build_self_play_runner`.

    ``log_event`` is an optional ``(event_name, payload_dict)`` callback
    the runner calls on per-game milestones (game_start, game_end,
    weights_loaded, ...). When omitted, events are dropped.
    """
    from mtg_bot.worker_daemon_production_runner import (  # noqa: PLC0415
        build_self_play_runner,
    )

    return build_self_play_runner(
        coordinator_url=coordinator_url,
        stage_id=stage_id,
        n_workers=n_workers,
        weights_cache_root=weights_cache_root,
        worker_id=worker_id,
        log_event=log_event,
        deck_pool_path=deck_pool_path,
        http_get=http_get,
    )


def build_production_eval_runner(
    coordinator_url: str,
    stage_id: str,
    n_workers: int,
    weights_cache_root: Path,
    worker_id: str,
    log_event: Optional[Callable[[str, dict], None]] = None,
    *,
    deck_pool_path: Optional[str] = None,
    http_get: Callable[..., tuple[int, bytes, dict[str, str]]] = _http_get,
) -> "GameRunner":
    """Construct the production eval GameRunner.

    Eval claims carry ``weights: {new, old}`` and the runner loads
    both versions into separate evaluators; the per-game result
    populates ``wins_new`` / ``wins_old`` (and ``draws``) instead of
    ``n_samples``.
    """
    from mtg_bot.worker_daemon_production_runner import (  # noqa: PLC0415
        build_eval_runner,
    )

    return build_eval_runner(
        coordinator_url=coordinator_url,
        stage_id=stage_id,
        n_workers=n_workers,
        weights_cache_root=weights_cache_root,
        worker_id=worker_id,
        log_event=log_event,
        deck_pool_path=deck_pool_path,
        http_get=http_get,
    )
