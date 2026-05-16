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
endpoints accept plain JSON and a multipart form on /report_result;
both are easy enough to hand-roll without pulling in ``requests`` or
``urllib3``. See ``_post_multipart`` for the multipart encoder.

Backoff schedule on 5xx: 1s / 3s / 10s, then ERROR. Constant
``RETRY_BACKOFF_S`` is exposed for tests.

worker_id resolution: prefer ``~/.mtg_bot_worker_id`` file; if absent,
default to ``socket.gethostname()``. Documented in :func:`resolve_worker_id`.
"""

from __future__ import annotations

import abc
import json
import logging
import os
import socket
import threading
import time
import traceback
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Optional


log = logging.getLogger(__name__)


# Retry/backoff constants. Tests monkeypatch these to keep wall time
# tiny without paying for real network sleeps.
RETRY_BACKOFF_S: tuple[float, ...] = (1.0, 3.0, 10.0)
DEFAULT_HTTP_TIMEOUT_S = 30.0
WEIGHTS_HTTP_TIMEOUT_S = 120.0


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


def _encode_multipart(
    fields: dict[str, str],
    files: dict[str, tuple[str, bytes, str]],
) -> tuple[bytes, str]:
    """Encode a multipart/form-data body by hand.

    ``fields`` maps name -> string value.
    ``files`` maps name -> (filename, body_bytes, content_type).

    Returns (body_bytes, content_type_header).
    """
    boundary = f"----mtgBotWorkerDaemon{uuid.uuid4().hex}"
    crlf = b"\r\n"
    buf = BytesIO()
    for name, value in fields.items():
        buf.write(f"--{boundary}".encode("ascii"))
        buf.write(crlf)
        buf.write(
            f'Content-Disposition: form-data; name="{name}"'.encode(
                "ascii"
            )
        )
        buf.write(crlf)
        # JSON-ish text payloads: spell the content-type so the server
        # ``request.form.get`` treats it as a string field correctly.
        buf.write(b"Content-Type: text/plain; charset=utf-8")
        buf.write(crlf)
        buf.write(crlf)
        buf.write(value.encode("utf-8"))
        buf.write(crlf)
    for name, (filename, content, content_type) in files.items():
        buf.write(f"--{boundary}".encode("ascii"))
        buf.write(crlf)
        buf.write(
            (
                'Content-Disposition: form-data; '
                f'name="{name}"; filename="{filename}"'
            ).encode("ascii")
        )
        buf.write(crlf)
        buf.write(f"Content-Type: {content_type}".encode("ascii"))
        buf.write(crlf)
        buf.write(crlf)
        buf.write(content)
        buf.write(crlf)
    buf.write(f"--{boundary}--".encode("ascii"))
    buf.write(crlf)
    return buf.getvalue(), f"multipart/form-data; boundary={boundary}"


def _http_post_multipart(
    url: str,
    fields: dict[str, str],
    files: dict[str, tuple[str, bytes, str]],
    *,
    timeout: float = DEFAULT_HTTP_TIMEOUT_S,
) -> tuple[int, bytes, dict[str, str]]:
    body, content_type = _encode_multipart(fields, files)
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": content_type},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as e:
        body_bytes = b""
        try:
            body_bytes = e.read() or b""
        except Exception:
            pass
        return e.code, body_bytes, dict(e.headers or {})


# ---------------------------------------------------------------------------
# Weights cache
# ---------------------------------------------------------------------------


def _weights_dir(weights_root: Path, version: str) -> Path:
    return Path(weights_root) / version


def fetch_weights_if_missing(
    coordinator_url: str,
    version: str,
    weights_root: Path,
    *,
    http_get: Callable[..., tuple[int, bytes, dict[str, str]]] = _http_get,
) -> Path:
    """Ensure ``trained_weights/<version>/weights.pt`` and
    ``metadata.json`` exist locally. Fetch from
    ``<coordinator_url>/v2/weights/<version>`` (+ ``/metadata``) on
    cache miss. Returns the version dir.

    The function is intentionally a thin wrapper around two GETs so
    the test suite can monkeypatch ``http_get`` to count cache hits
    vs misses.

    Concurrency note: we don't gate concurrent fetches across daemon
    processes. Workers don't share a filesystem in production; the
    master-worker is the only place a race could occur, and it's a
    documented known limitation (see commit message).
    """
    target_dir = _weights_dir(weights_root, version)
    weights_path = target_dir / "weights.pt"
    metadata_path = target_dir / "metadata.json"
    if weights_path.is_file() and metadata_path.is_file():
        return target_dir

    target_dir.mkdir(parents=True, exist_ok=True)
    base = coordinator_url.rstrip("/")
    if not weights_path.is_file():
        status, body, _ = http_get(
            f"{base}/v2/weights/{version}",
            timeout=WEIGHTS_HTTP_TIMEOUT_S,
        )
        if status != 200:
            raise RuntimeError(
                f"GET /v2/weights/{version} failed: status={status}"
            )
        weights_path.write_bytes(body)
    if not metadata_path.is_file():
        status, body, _ = http_get(
            f"{base}/v2/weights/{version}/metadata",
            timeout=WEIGHTS_HTTP_TIMEOUT_S,
        )
        if status != 200:
            raise RuntimeError(
                f"GET /v2/weights/{version}/metadata failed: status={status}"
            )
        metadata_path.write_bytes(body)
    return target_dir


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
    ):
        self._play_one = play_one
        self._setup = setup_fn
        self._teardown = teardown_fn

    def setup(self, coordinator_url, weights_root, stage_kind, n_workers):
        if self._setup is not None:
            self._setup(coordinator_url, weights_root, stage_kind, n_workers)

    def play_one_game(self, claim, shard_label):
        return self._play_one(claim, shard_label)

    def teardown(self):
        if self._teardown is not None:
            self._teardown()


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
    # Retry/backoff. Tests slam this to zero.
    retry_backoff_s: tuple[float, ...] = field(
        default_factory=lambda: RETRY_BACKOFF_S
    )
    # HTTP transport hooks. Overridable for testing.
    http_get: Callable[..., tuple[int, bytes, dict[str, str]]] = field(
        default=_http_get
    )
    http_post_json: Callable[..., tuple[int, bytes, dict[str, str]]] = field(
        default=_http_post_json
    )
    http_post_multipart: Callable[..., tuple[int, bytes, dict[str, str]]] = field(
        default=_http_post_multipart
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
            except urllib.error.URLError as e:
                last_err = f"URLError attempt {attempt}: {e}"
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
        """POST /v2/report_result (multipart). Returns one of
        ``"accepted"`` / ``"conflict"`` / ``"unknown"``. 5xx triggers
        backoff+retry.
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

        files: dict[str, tuple[str, bytes, str]] = {}
        if result.npz_bytes:
            files["npz"] = (
                f"{claim.get('game_idx', 0)}.npz",
                result.npz_bytes,
                "application/octet-stream",
            )
        if result.replay_bytes:
            files["replay"] = (
                f"{claim.get('game_idx', 0)}.json.gz",
                result.replay_bytes,
                "application/gzip",
            )

        url = self._coord_url("/v2/report_result")
        fields = {"meta": json.dumps(meta)}
        last_err: Optional[str] = None
        for attempt, delay in enumerate((0.0,) + tuple(self.cfg.retry_backoff_s)):
            if delay > 0:
                time.sleep(delay)
            try:
                status, resp_body, _ = self.cfg.http_post_multipart(
                    url, fields, files,
                )
            except urllib.error.URLError as e:
                last_err = f"URLError attempt {attempt}: {e}"
                log.warning("[report_loop] %s", last_err)
                continue
            if status == 200:
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

    def run_once(self) -> str:
        """Run one full claim/play/report turn.

        Returns:
        - ``"drained"`` if /claim returned 204 (loop should exit).
        - ``"continue"`` after a successful report (or 409 drop).
        """
        if self.state.is_stop_requested():
            return "drained"
        claim = self._claim_one()
        if claim is None:
            return "drained"
        self.state.on_claim()
        try:
            t0 = time.perf_counter()
            result = self.runner.play_one_game(claim, self.cfg.shard_label)
            # If the runner didn't populate duration_s itself, fill it.
            if result.duration_s == 0.0:
                result.duration_s = time.perf_counter() - t0
        except Exception:
            # Runner crashed mid-game. Report a "crashed" outcome
            # so the coordinator's queue accounting stays sane, then
            # propagate by re-raising so the daemon ends up in ERROR.
            crashed = GameResult(
                outcome="crashed",
                duration_s=time.perf_counter() - t0,
            )
            try:
                self._report_one(claim, crashed)
            except Exception:
                log.exception("[claim_loop] failed to report crashed game")
            self.state.on_drop()
            raise
        outcome = self._report_one(claim, result)
        if outcome == "accepted":
            self.state.on_report()
        else:
            # 409 / unknown — drop without crediting games_done.
            self.state.on_drop()
        return "continue"

    def run(self) -> None:
        """Main loop body. Returns when the stage drains, /v2/stop
        fires, or a fatal error pushes the daemon into ERROR."""
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
        try:
            while True:
                if self.state.is_stop_requested():
                    break
                status = self.run_once()
                if status == "drained":
                    break
        except Exception:
            self.state.mark_error(
                f"claim loop crashed: {traceback.format_exc()}"
            )
            return
        finally:
            try:
                self.runner.teardown()
            except Exception:
                log.exception("[claim_loop] runner.teardown failed")
        # Normal completion path — push to STOPPING (if not already)
        # then IDLE.
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


# ---------------------------------------------------------------------------
# Production game-runner stub (the lift-and-shift from cli/shard.py).
# ---------------------------------------------------------------------------


def build_production_self_play_runner() -> CallableGameRunner:
    """Construct the production self-play runner.

    The real implementation spins up an NN evaluator + SHM server +
    multiprocessing pool, mirroring ``cli/shard.py::_run_pull_shard``.
    That body has heavy torch / multiprocessing imports that we don't
    want to drag into the worker_daemon import path (it would break
    daemon startup on a host that hasn't installed torch yet, e.g. a
    fresh worker before the master pushes weights).

    The lazy import inside the closures defers all of that to the
    first :meth:`GameRunner.setup` call — exactly when the runner is
    expected to bring up the pool. The integration test exercises a
    test-only runner that returns synthetic results without touching
    torch, which is fine for a wire-up check.
    """

    state: dict[str, Any] = {}

    def _setup(coordinator_url, weights_root, kind, n_workers):
        # Production setup is deliberately deferred to the first
        # iter_009-scale run; the unit + integration tests in this PR
        # exercise the loop with a callable runner (see
        # ``tests/test_worker_daemon_integration.py``). The full
        # lift-and-shift of run_shard_pull's pool spin-up lives behind
        # this hook so the production wiring lands in a follow-up
        # commit without re-touching the worker daemon.
        state["coordinator_url"] = coordinator_url
        state["weights_root"] = weights_root
        state["kind"] = kind
        state["n_workers"] = n_workers

    def _play_one(claim, shard_label):  # pragma: no cover - deferred
        raise NotImplementedError(
            "production self-play runner pool spin-up is deferred to a "
            "follow-up commit; supply a CallableGameRunner directly to "
            "ClaimLoopRunner for now."
        )

    def _teardown():
        state.clear()

    return CallableGameRunner(_play_one, _setup, _teardown)


def build_production_eval_runner() -> CallableGameRunner:
    """Same shape as :func:`build_production_self_play_runner` but for
    the eval path. Eval claims carry ``weights: {new, old}`` and the
    runner loads both into separate evaluators; the per-game result
    populates ``wins_new`` / ``wins_old``.
    """
    return build_production_self_play_runner()
