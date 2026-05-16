"""Coordinator-side heartbeat poller.

Polls each worker's ``GET /v2/heartbeat`` every ``poll_interval_s``
(default 10s). Maintains an in-memory ``dict[worker_url, WorkerState]``
with the latest snapshot, the derived liveness label
(ALIVE / STALE / DEAD), and the set of in-flight claim_ids currently
held by that worker. On a transition into DEAD, immediately re-queues
all of that worker's in-flight claims via :mod:`queue_db.requeue_claim`.

The poller is a daemon thread, started by ``mtg_bot.cli.serve``'s
``create_app`` factory. Tests construct it directly with a tiny
``poll_interval_s`` (e.g. 0.05s) against an in-process Flask server
running on an ephemeral port.

State is *not* persisted — on coordinator restart the in-memory map
is empty, and abandoned claims get reclaimed via the claim-TTL sweep
in :func:`queue_db.requeue_expired_claims`. The heartbeat-driven path
is just the fast lane.

Configuration shape: reads ``shards_config.json``. Post-cutover the
ONLY supported shape is::

    {"worker_urls": ["http://host1:5198", "http://host2:5198", ...]}

The legacy shapes (``{"shards": [{host, user, repo_path, ...}]}`` from
the SSH era, and the transitional ``{"workers": [{worker_id,
worker_url, n_workers}]}`` shape used during the migration) are
rejected loudly so an operator can't silently run with a stale config.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from mtg_bot.cli.runs import queue_db


# Liveness thresholds in seconds.
ALIVE_MAX_S = 30.0
STALE_MAX_S = 90.0


class LegacyShardsConfigError(ValueError):
    """Raised when ``shards_config.json`` uses a pre-v2-cutover shape.

    Carries a clear migration message so the operator knows exactly
    what to change. The cutover was a hard cut — there is no
    in-process fallback to the legacy ``{shards: [...]}`` /
    ``{workers: [{worker_id, worker_url, n_workers}]}`` shapes.
    """


def load_shards_config(path: Path) -> list[dict[str, Any]]:
    """Read ``shards_config.json`` and return the worker list as
    ``[{worker_url}, ...]``.

    Post-cutover the ONLY accepted shape is::

        {"worker_urls": ["http://host1:5198", "http://host2:5198"]}

    The legacy ``{shards: [...]}`` (SSH-era) and the transitional
    ``{workers: [{worker_id, worker_url, n_workers}]}`` shapes raise
    :class:`LegacyShardsConfigError` with a clear migration message.
    Per-worker operational config (n_workers, deck_pool_path,
    weights_cache_root) lives on each worker daemon's CLI flags, NOT
    in this file — see ``docs/DISTRIBUTED_API_v2.md``.
    """
    path = Path(path)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    if "shards" in data or "workers" in data:
        raise LegacyShardsConfigError(
            f"legacy shards_config.json detected at {path}; please "
            "migrate to {'worker_urls': ['http://host:5198', ...]} "
            "shape. The v2 cutover removed per-worker fields "
            "(n_workers, host, user, repo_path, venv_python, "
            "ssh_port, worker_id) — each daemon now owns those via "
            "its own CLI flags (see deploy/README.md). See "
            "docs/DISTRIBUTED_API_v2.md for the full migration."
        )
    if "worker_urls" not in data:
        return []
    urls = data["worker_urls"]
    if not isinstance(urls, list):
        raise ValueError(
            f"shards_config.json {path}: 'worker_urls' must be a list, "
            f"got {type(urls).__name__}"
        )
    out: list[dict[str, Any]] = []
    for url in urls:
        if not isinstance(url, str):
            continue
        out.append({"worker_url": url})
    return out


@dataclass
class WorkerLiveness:
    """In-memory liveness record for one worker_url.

    ``last_heartbeat_at`` is a wall-clock monotonic-friendly float
    (``time.monotonic()``) so the staleness check is robust against
    clock skew. ``last_heartbeat_payload`` is the raw JSON dict from
    the worker's ``/v2/heartbeat`` response — fed straight to the UI
    if needed.

    ``in_flight_claim_ids`` is the set of claim_ids the coordinator
    *believes* this worker is currently holding (updated by
    :func:`HeartbeatPoller.track_claim` and ``untrack_claim``). On a
    DEAD transition the poller iterates this set and re-queues each
    claim. The set is cleared on any DEAD→ALIVE transition (the
    worker's fresh state is IDLE per the API doc).
    """

    last_heartbeat_at: Optional[float] = None
    last_heartbeat_payload: Optional[dict[str, Any]] = None
    liveness: str = "UNKNOWN"  # ALIVE | STALE | DEAD | UNKNOWN
    in_flight_claim_ids: set[str] = field(default_factory=set)


class HeartbeatPoller:
    """Background poller. Owns the per-worker liveness map and the
    DEAD-transition re-queue logic.

    Public API used by the v2 endpoint blueprint:

    - :meth:`track_claim` — call when ``/v2/claim`` hands a game out
      to ``worker_id``; the coordinator looks up the worker's URL via
      the cached config so the poller doesn't need to know how the
      handler reached it.
    - :meth:`untrack_claim` — call when ``/v2/report_result`` accepts
      a claim, so the coordinator stops counting it against the
      worker.
    - :meth:`worker_states` — snapshot dict for the UI's per-machine
      sub-cards.

    Tests inject a custom ``http_get`` callable (one that hits a
    local Flask test server on an ephemeral port) and a tiny
    ``poll_interval_s`` (~50ms) for fast feedback.
    """

    def __init__(
        self,
        *,
        queue_db_path: Path,
        shards_config_path: Path,
        poll_interval_s: float = 10.0,
        http_timeout_s: float = 3.0,
        alive_max_s: float = ALIVE_MAX_S,
        stale_max_s: float = STALE_MAX_S,
        clock: callable = time.monotonic,
        http_get: Optional[callable] = None,
    ):
        self._queue_db_path = Path(queue_db_path)
        self._shards_config_path = Path(shards_config_path)
        self._poll_interval_s = poll_interval_s
        self._http_timeout_s = http_timeout_s
        self._alive_max_s = alive_max_s
        self._stale_max_s = stale_max_s
        self._clock = clock
        self._http_get = http_get or self._default_http_get
        # worker_id -> worker_url so handlers can look up by id only.
        self._id_to_url: dict[str, str] = {}
        # worker_url -> WorkerLiveness
        self._workers: dict[str, WorkerLiveness] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._refresh_config()

    # ------------------------------------------------------------------
    # Config / mapping

    def _refresh_config(self) -> None:
        entries = load_shards_config(self._shards_config_path)
        with self._lock:
            for e in entries:
                worker_url = e.get("worker_url")
                if not worker_url:
                    continue
                if worker_url not in self._workers:
                    self._workers[worker_url] = WorkerLiveness()

    # ------------------------------------------------------------------
    # Lifecycle

    def start(self) -> None:
        """Begin the polling loop on a daemon thread. Idempotent."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="HeartbeatPoller", daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """Signal the loop to exit and join the thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    # ------------------------------------------------------------------
    # Claim tracking (called by v2_endpoints handlers)

    def track_claim(self, worker_id: str, claim_id: str) -> None:
        with self._lock:
            url = self._id_to_url.get(worker_id)
            if url is None:
                # Unknown worker_id (not in shards_config). The
                # coordinator still serves the claim, but liveness
                # tracking is a no-op for this worker.
                return
            state = self._workers.setdefault(url, WorkerLiveness())
            state.in_flight_claim_ids.add(claim_id)

    def untrack_claim(self, claim_id: str) -> None:
        with self._lock:
            for state in self._workers.values():
                state.in_flight_claim_ids.discard(claim_id)

    # ------------------------------------------------------------------
    # Snapshot

    def worker_states(self) -> dict[str, dict[str, Any]]:
        """Snapshot of the liveness map for the UI / tests."""
        out: dict[str, dict[str, Any]] = {}
        with self._lock:
            for url, state in self._workers.items():
                out[url] = {
                    "liveness": state.liveness,
                    "last_heartbeat_at": state.last_heartbeat_at,
                    "last_heartbeat_payload": state.last_heartbeat_payload,
                    "in_flight_claim_ids": sorted(
                        state.in_flight_claim_ids,
                    ),
                }
        return out

    # ------------------------------------------------------------------
    # Polling loop

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.tick()
            # Use the Event's wait() so stop() returns promptly even
            # mid-sleep. (Plain time.sleep would block the full
            # interval after a stop() call.)
            self._stop_event.wait(self._poll_interval_s)

    def tick(self) -> None:
        """One poll cycle: hit every known worker_url, update liveness,
        re-queue DEAD-worker claims. Public for tests.

        Post-cutover, the worker_id → worker_url mapping is learned
        from each heartbeat payload's ``worker_id`` field (the daemon
        self-identifies on every heartbeat). This replaces the static
        config-file mapping the legacy ``{workers: [{worker_id,
        worker_url, ...}]}`` shape provided.
        """
        with self._lock:
            urls = list(self._workers.keys())
        for url in urls:
            payload = self._http_get(url, self._http_timeout_s)
            with self._lock:
                state = self._workers.setdefault(url, WorkerLiveness())
                if payload is not None:
                    state.last_heartbeat_at = self._clock()
                    state.last_heartbeat_payload = payload
                    # Learn the worker_id → worker_url mapping from the
                    # payload so track_claim() can find this worker by
                    # its self-reported id.
                    wid = payload.get("worker_id") if isinstance(payload, dict) else None
                    if isinstance(wid, str) and wid:
                        self._id_to_url[wid] = url
            self._refresh_liveness(url)

    def _refresh_liveness(self, url: str) -> None:
        """Recompute the liveness label from ``last_heartbeat_at`` and
        fire the DEAD-transition re-queue side effect when applicable.
        Caller does NOT need to hold the lock; the method takes it."""
        with self._lock:
            state = self._workers.get(url)
            if state is None:
                return
            now = self._clock()
            prior = state.liveness
            if state.last_heartbeat_at is None:
                # Never heard from this worker; treat as DEAD-ish
                # for re-queue purposes only after we'd normally have
                # marked it dead. The "no heartbeat ever received"
                # case stays UNKNOWN — there are no claims to re-queue
                # since none were served via /v2/claim.
                new = "UNKNOWN"
            else:
                age = now - state.last_heartbeat_at
                if age <= self._alive_max_s:
                    new = "ALIVE"
                elif age <= self._stale_max_s:
                    new = "STALE"
                else:
                    new = "DEAD"
            state.liveness = new
            transitioned_to_dead = (prior != "DEAD" and new == "DEAD")
            transitioned_from_dead = (prior == "DEAD" and new == "ALIVE")
            claims_to_requeue = []
            if transitioned_to_dead:
                claims_to_requeue = list(state.in_flight_claim_ids)
                # Per the API doc: DEAD-transition immediately re-queues
                # all in-flight claims; the worker's fresh-restart state
                # is IDLE so it doesn't hold them any more.
                state.in_flight_claim_ids.clear()
            if transitioned_from_dead:
                state.in_flight_claim_ids.clear()
        # Side effects outside the lock.
        if claims_to_requeue:
            self._requeue_claims(claims_to_requeue)

    def _requeue_claims(self, claim_ids: list[str]) -> None:
        """Re-queue a batch of claim_ids via queue_db. Logs+swallows
        per-claim errors so one bad row doesn't poison the rest."""
        conn = queue_db.connect(self._queue_db_path)
        try:
            with queue_db.WRITE_LOCK:
                for cid in claim_ids:
                    try:
                        queue_db.requeue_claim(conn, cid)
                    except Exception:  # noqa: BLE001
                        # Best-effort: a missing or already-reported
                        # claim is fine (idempotent in requeue_claim).
                        pass
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Default HTTP

    def _default_http_get(
        self, base_url: str, timeout_s: float,
    ) -> Optional[dict[str, Any]]:
        """Hit ``<base_url>/v2/heartbeat``; return the parsed JSON or
        ``None`` on any error. Tests inject a custom callable in
        place of this."""
        url = base_url.rstrip("/") + "/v2/heartbeat"
        try:
            with urllib.request.urlopen(url, timeout=timeout_s) as resp:
                if resp.status != 200:
                    return None
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError, OSError):
            return None
