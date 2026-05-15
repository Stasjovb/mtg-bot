"""Worker daemon — Phase 2a skeleton.

Implements the worker-side REST surface described in
``docs/DISTRIBUTED_API_v2.md`` and ``docs/DISTRIBUTED_RUN_FLOW.md``.

Phase 2a scope (this module): the Flask app, the state machine, the
``/v2/start_self_play`` / ``/v2/start_eval`` / ``/v2/stop`` /
``/v2/heartbeat`` endpoints, and a CLI entry point. **No real
work runs yet** — ``/v2/start_*`` only transitions state; a stub
background thread bumps STARTING → RUNNING after a brief delay so the
tests can observe both. The actual ``/v2/claim`` loop, multiprocessing
pool, weights fetch, etc. land in Phase 2b together with the lift-and-
shift of ``cli/shard.py``'s body.

The handlers exchange JSON shapes that match the contract verbatim so
Phase 2b only has to fill in behavior, not re-negotiate the wire.
"""

from __future__ import annotations

import argparse
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

import psutil
from flask import Flask, jsonify, request

# ---------------------------------------------------------------------------
# Optional pynvml import — Mac / CPU-only hosts run without it. The
# heartbeat handler swallows ImportError and omits the gpu_* fields.
# We resolve the module lazily inside the heartbeat handler so tests can
# monkeypatch ``sys.modules['pynvml']`` to either a stub or ``None`` and
# observe the resulting payload shape.
# ---------------------------------------------------------------------------


def _try_import_pynvml():  # pragma: no cover - thin shim, exercised via tests
    """Return the imported pynvml module or ``None`` if unavailable.

    Isolated into a function so tests can monkeypatch this directly
    without going through Python's import machinery.
    """
    try:
        import pynvml  # type: ignore[import-not-found]

        return pynvml
    except Exception:
        return None


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


class State:
    """String constants for the worker state machine.

    Kept as a namespace of strings (not an enum) so they serialize
    straight into JSON and compare cheaply across threads.
    """

    IDLE = "IDLE"
    SELF_PLAY_STARTING = "SELF_PLAY_STARTING"
    SELF_PLAY_RUNNING = "SELF_PLAY_RUNNING"
    EVAL_STARTING = "EVAL_STARTING"
    EVAL_RUNNING = "EVAL_RUNNING"
    STOPPING = "STOPPING"
    ERROR = "ERROR"


# Delay (seconds) between STARTING and RUNNING in the skeleton's stub
# background thread. Tests override this to a tiny value so the
# transition is observable without slowing the suite down.
DEFAULT_START_DELAY_S = 0.05


def _utcnow_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with ``Z`` suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class WorkerState:
    """Thread-safe holder for the worker's state machine + counters.

    All mutation goes through ``_lock``; readers snapshot the whole
    dict in one critical section so a heartbeat reply never mixes
    fields from before-and-after a transition.

    Fields tracked:

    - ``state``: one of :class:`State`'s constants.
    - ``current_stage_id``: ``stage_id`` from the most recent ``start_*``.
    - ``pool_size``: requested ``n_workers`` (0 when IDLE).
    - ``active_workers``: pool members currently executing a game
      (always 0 in the skeleton; populated in Phase 2b).
    - ``games_done``, ``games_claimed_in_flight``: 0 in the skeleton.
    - ``last_progress_at``: ISO timestamp of last meaningful progress
      event (currently bumped on start transitions).
    - ``error``: non-None only in the ``ERROR`` state.
    - ``started_at``: when the daemon process started (constant per
      process; used for the ``uptime_s`` calculation).
    """

    def __init__(self, start_delay_s: float = DEFAULT_START_DELAY_S):
        self._lock = threading.Lock()
        self._process_started_at = time.monotonic()
        self._start_delay_s = start_delay_s
        self.state = State.IDLE
        self.current_stage_id: str | None = None
        self.pool_size = 0
        self.active_workers = 0
        self.games_done = 0
        self.games_claimed_in_flight = 0
        self.last_progress_at: str | None = None
        self.error: str | None = None
        self.started_at: str = _utcnow_iso()

    # ------------------------------------------------------------------
    # Transitions

    def try_start(
        self,
        kind: str,
        stage_id: str,
        n_workers: int,
    ) -> tuple[bool, str]:
        """Attempt the IDLE → ``{kind}_STARTING`` transition.

        ``kind`` is ``"self_play"`` or ``"eval"``. Returns
        ``(accepted, current_state)``. When ``accepted`` is ``False``
        the caller should respond 409 with the returned current state.

        Spawns a background thread that flips STARTING → RUNNING after
        ``start_delay_s`` so tests can observe both transitions. Phase
        2b replaces this stub with the real "fetch weights → spin up
        pool → start claim loop" sequence; the STARTING → RUNNING
        transition then happens once the pool is ready.
        """
        with self._lock:
            if self.state != State.IDLE:
                return False, self.state
            starting_state = (
                State.SELF_PLAY_STARTING if kind == "self_play" else State.EVAL_STARTING
            )
            running_state = (
                State.SELF_PLAY_RUNNING if kind == "self_play" else State.EVAL_RUNNING
            )
            self.state = starting_state
            self.current_stage_id = stage_id
            self.pool_size = n_workers
            self.active_workers = 0
            self.games_done = 0
            self.games_claimed_in_flight = 0
            self.error = None
            self.last_progress_at = _utcnow_iso()

        # Stub: flip STARTING → RUNNING off-thread so a tight
        # POST/GET sequence in tests can catch either side of the edge.
        # The real implementation in Phase 2b replaces this with the
        # pool-ready callback.
        def _flip_to_running() -> None:
            time.sleep(self._start_delay_s)
            with self._lock:
                # Guard against a /v2/stop arriving during the delay.
                if self.state == starting_state:
                    self.state = running_state
                    self.last_progress_at = _utcnow_iso()

        t = threading.Thread(target=_flip_to_running, daemon=True)
        t.start()
        return True, starting_state

    def stop(self) -> str:
        """Drain in-flight work and return to IDLE.

        Skeleton implementation: no real in-flight games exist yet, so
        STOPPING is instantaneous. Phase 2b drains the pool here.

        Returns the worker's state at the time the call was received
        (per the API doc — the response reports the *receipt* state).
        """
        with self._lock:
            state_at_receipt = self.state
            if self.state in (
                State.SELF_PLAY_RUNNING,
                State.SELF_PLAY_STARTING,
                State.EVAL_RUNNING,
                State.EVAL_STARTING,
            ):
                self.state = State.STOPPING
            # Skeleton: no real in-flight games — drain is immediate.
            self.state = State.IDLE
            self.current_stage_id = None
            self.pool_size = 0
            self.active_workers = 0
            self.games_claimed_in_flight = 0
            self.last_progress_at = _utcnow_iso()
        return state_at_receipt

    # ------------------------------------------------------------------
    # Snapshots

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serializable dict of the wire-relevant fields.

        Excludes the ``host{}`` block — that's collected fresh on each
        heartbeat (see :func:`collect_host_metrics`) and merged in by
        the handler.
        """
        with self._lock:
            return {
                "state": self.state,
                "current_stage_id": self.current_stage_id,
                "games_done": self.games_done,
                "games_claimed_in_flight": self.games_claimed_in_flight,
                "last_progress_at": self.last_progress_at,
                "error": self.error,
                "uptime_s": time.monotonic() - self._process_started_at,
                "pool_size": self.pool_size,
                "active_workers": self.active_workers,
            }


# ---------------------------------------------------------------------------
# Host metrics
# ---------------------------------------------------------------------------


def collect_host_metrics(state: WorkerState) -> dict[str, Any]:
    """Build the heartbeat ``host{}`` block.

    Required fields (always present):
    ``pool_size``, ``active_workers``, ``cpu_percent``,
    ``memory_percent``, ``memory_used_gb``, ``memory_total_gb``,
    ``load_avg_1m``.

    Optional fields (present only when ``pynvml`` is available and a
    GPU is queryable): ``gpu_percent``, ``gpu_memory_percent``.

    The doc specifies system-wide CPU+mem (NOT per-process), so we use
    the bare ``psutil`` module-level calls.
    """
    snap = state.snapshot()
    mem = psutil.virtual_memory()
    cpu_percent = psutil.cpu_percent(interval=None)
    # load_avg_1m: POSIX has getloadavg; on Windows psutil.getloadavg()
    # returns the rolling 60s cpu_percent average — same shape per the
    # doc. Avoid raising on platforms where it's unavailable.
    try:
        load_avg_1m = psutil.getloadavg()[0]
    except (AttributeError, OSError):  # pragma: no cover - platform-dependent
        load_avg_1m = float(cpu_percent)

    host: dict[str, Any] = {
        "pool_size": snap["pool_size"],
        "active_workers": snap["active_workers"],
        "cpu_percent": float(cpu_percent),
        "memory_percent": float(mem.percent),
        "memory_used_gb": float(mem.used) / (1024**3),
        "memory_total_gb": float(mem.total) / (1024**3),
        "load_avg_1m": float(load_avg_1m),
    }

    pynvml = _try_import_pynvml()
    if pynvml is not None:
        try:
            pynvml.nvmlInit()
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            host["gpu_percent"] = float(util.gpu)
            host["gpu_memory_percent"] = float(util.memory)
        except Exception:
            # GPU absent / driver-level failure — silently omit the
            # gpu_* fields rather than poison the heartbeat. The doc
            # says "Absent fields are omitted on CPU-only hosts."
            pass
        finally:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass

    return host


# ---------------------------------------------------------------------------
# Flask app factory
# ---------------------------------------------------------------------------


def create_app(start_delay_s: float = DEFAULT_START_DELAY_S) -> Flask:
    """Build the Flask app with the v2 endpoints wired.

    Each app instance owns its own :class:`WorkerState`. Tests use
    Flask's ``app.test_client()`` to drive the handlers without binding
    a real socket.
    """
    app = Flask(__name__)
    state = WorkerState(start_delay_s=start_delay_s)
    # Expose for tests / introspection. Not part of the wire contract.
    app.config["WORKER_STATE"] = state

    def _start(kind: str):
        body = request.get_json(silent=True) or {}
        stage_id = body.get("stage_id")
        n_workers = int(body.get("n_workers", 0))
        accepted, current_state = state.try_start(kind, stage_id, n_workers)
        if not accepted:
            return (
                jsonify({"error": "worker_busy", "current_state": current_state}),
                409,
            )
        return (
            jsonify(
                {
                    "stage_id": stage_id,
                    "started_at": _utcnow_iso(),
                }
            ),
            202,
        )

    @app.route("/v2/start_self_play", methods=["POST"])
    def start_self_play():  # noqa: D401 - Flask handler
        return _start("self_play")

    @app.route("/v2/start_eval", methods=["POST"])
    def start_eval():  # noqa: D401 - Flask handler
        return _start("eval")

    @app.route("/v2/stop", methods=["POST"])
    def stop():  # noqa: D401 - Flask handler
        receipt_state = state.stop()
        return (
            jsonify(
                {
                    "state": state.snapshot()["state"],
                    "state_at_receipt": receipt_state,
                }
            ),
            200,
        )

    @app.route("/v2/heartbeat", methods=["GET"])
    def heartbeat():  # noqa: D401 - Flask handler
        snap = state.snapshot()
        # The host{} block has its own pool_size / active_workers; the
        # top-level snapshot keeps them too for backward compat with
        # any consumer that reads either spot. The contract's example
        # nests them under host{}.
        host = collect_host_metrics(state)
        payload = {
            "state": snap["state"],
            "current_stage_id": snap["current_stage_id"],
            "games_done": snap["games_done"],
            "games_claimed_in_flight": snap["games_claimed_in_flight"],
            "last_progress_at": snap["last_progress_at"],
            "error": snap["error"],
            "uptime_s": snap["uptime_s"],
            "host": host,
        }
        return jsonify(payload), 200

    return app


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:  # pragma: no cover - argparse
    parser = argparse.ArgumentParser(
        prog="mtg_bot.worker_daemon",
        description="MTG-bot distributed worker daemon (REST, Phase 2a skeleton).",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help=(
            "Bind address. Default: 127.0.0.1 (safe for local testing). "
            "Production deployments bind to the tailnet IP — operator's choice."
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5198,
        help="Bind port. Default: 5198 (worker daemon canonical port).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - argparse
    parser = _build_parser()
    args = parser.parse_args(argv)
    app = create_app()
    # Flask's dev server is fine for Phase 2a — Phase 2c swaps in a
    # native service supervisor (systemd / launchd / Task Scheduler)
    # and a production-grade WSGI runner if needed.
    app.run(host=args.host, port=args.port, threaded=True)
    return 0


if __name__ == "__main__":  # pragma: no cover - module CLI
    raise SystemExit(main())
