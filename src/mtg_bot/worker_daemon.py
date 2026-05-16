"""Worker daemon — Phase 2b.

Implements the worker-side REST surface described in
``docs/DISTRIBUTED_API_v2.md`` and ``docs/DISTRIBUTED_RUN_FLOW.md``.

Phase 2b scope (this module): the Flask app, the state machine, the
``/v2/start_self_play`` / ``/v2/start_eval`` / ``/v2/stop`` /
``/v2/heartbeat`` endpoints, a CLI entry point, **and the real
claim/play/report loop** that talks to the coordinator's v2 endpoints
(``/v2/claim``, ``/v2/report_result``, ``/v2/weights/<v>``).

The claim-loop body is encapsulated in
:class:`ClaimLoopRunner` so tests can swap the game runner for a stub
and exercise the full lifecycle without spawning a torch model.

Contract patches folded into this revision:

- ``/v2/healthz`` is the coordinator-side liveness endpoint; the
  worker uses ``/v2/heartbeat`` (the rich snapshot).
- The ``/v2/start_self_play`` / ``/v2/start_eval`` 202 response carries
  ``stage_started_at`` (renamed from ``started_at`` to disambiguate
  from the daemon process start time).
- ``/v2/heartbeat`` payload carries ``process_started_at`` at the top
  level alongside ``uptime_s``.
- ``/v2/stop`` returns ``{state, previous_state, drain_in_flight_games,
  stopped_at}`` and is idempotent on already-IDLE.
- Windows ``load_avg_1m`` is the rolling 60s ``cpu_percent`` average
  (best cross-platform analog; documented in ``collect_host_metrics``).
"""

from __future__ import annotations

import argparse
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import psutil
from flask import Flask, jsonify, request

from mtg_bot import worker_daemon_claim_loop as _claim_loop
from mtg_bot.worker_daemon_claim_loop import resolve_worker_id

if TYPE_CHECKING:  # pragma: no cover - imports just for type hints
    from mtg_bot.worker_daemon_claim_loop import (
        ClaimLoopConfig,
        ClaimLoopRunner,
        GameRunner,
        StateCallbacks,
    )

# How long /v2/stop waits for the runner thread to drain before
# returning. Set short so the handler stays responsive; the runner
# itself will continue to drain its in-flight game after the response
# ships, eventually flipping the daemon to IDLE.
_STOP_JOIN_TIMEOUT_S = 2.0


# Type alias for the runner factory that ``create_app`` accepts. The
# factory builds the per-stage ``GameRunner`` plus the loop runner;
# tests pass a closure that owns the stub runner under test.
RunnerFactory = Callable[
    [str, "ClaimLoopConfig", "StateCallbacks"], "GameRunner"
]

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
      (incremented when a worker checks out a claim, decremented at
      report time).
    - ``games_done``: completed-and-reported games for the active stage.
    - ``games_claimed_in_flight``: claimed but not-yet-reported.
    - ``last_progress_at``: ISO timestamp of last meaningful progress
      event (bumped on start transitions, claims, and reports).
    - ``error``: non-None only in the ``ERROR`` state.
    - ``process_started_at``: ISO-8601 timestamp of when the daemon
      process started (constant per process; surfaced on
      ``/v2/heartbeat``).
    - ``stop_requested``: a graceful_stop flag the claim-loop polls
      between games.
    """

    def __init__(self, start_delay_s: float = DEFAULT_START_DELAY_S):
        self._lock = threading.Lock()
        self._process_started_at_monotonic = time.monotonic()
        self._start_delay_s = start_delay_s
        self.state = State.IDLE
        self.current_stage_id: str | None = None
        self.pool_size = 0
        self.active_workers = 0
        self.games_done = 0
        self.games_claimed_in_flight = 0
        self.last_progress_at: str | None = None
        self.error: str | None = None
        self.process_started_at: str = _utcnow_iso()
        # Drain coordination. ``stop_requested`` is the cooperative
        # signal the claim loop polls between games; ``loop_thread``
        # is whatever runner is currently executing /claim+/play+
        # /report. None when IDLE.
        self.stop_requested = False
        self.loop_thread: threading.Thread | None = None

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

        Does NOT spawn any background work — the caller wires the
        :class:`ClaimLoopRunner` thread after a successful transition.
        The ``mark_running`` / ``mark_idle`` / ``mark_error`` helpers
        push the rest of the state machine forward.
        """
        with self._lock:
            if self.state != State.IDLE:
                return False, self.state
            starting_state = (
                State.SELF_PLAY_STARTING if kind == "self_play" else State.EVAL_STARTING
            )
            self.state = starting_state
            self.current_stage_id = stage_id
            self.pool_size = n_workers
            self.active_workers = 0
            self.games_done = 0
            self.games_claimed_in_flight = 0
            self.error = None
            self.stop_requested = False
            self.last_progress_at = _utcnow_iso()
        return True, starting_state

    def mark_running(self) -> None:
        """Push STARTING → RUNNING once the pool / NN are ready.

        Idempotent. No-op if the state isn't currently ``*_STARTING``
        (e.g. a /v2/stop arrived during the warmup).
        """
        with self._lock:
            if self.state == State.SELF_PLAY_STARTING:
                self.state = State.SELF_PLAY_RUNNING
                self.last_progress_at = _utcnow_iso()
            elif self.state == State.EVAL_STARTING:
                self.state = State.EVAL_RUNNING
                self.last_progress_at = _utcnow_iso()

    def mark_stopping(self) -> None:
        """Push RUNNING → STOPPING in response to ``/v2/stop`` or a
        ``/claim`` that returned 204. Sets the cooperative drain flag
        the runner polls between games. Idempotent.
        """
        with self._lock:
            if self.state in (
                State.SELF_PLAY_RUNNING,
                State.SELF_PLAY_STARTING,
                State.EVAL_RUNNING,
                State.EVAL_STARTING,
            ):
                self.state = State.STOPPING
            self.stop_requested = True
            self.last_progress_at = _utcnow_iso()

    def mark_idle(self) -> None:
        """Final transition back to IDLE once the runner drained."""
        with self._lock:
            self.state = State.IDLE
            self.current_stage_id = None
            self.pool_size = 0
            self.active_workers = 0
            self.games_claimed_in_flight = 0
            self.stop_requested = False
            self.last_progress_at = _utcnow_iso()
            self.loop_thread = None

    def mark_error(self, err: str) -> None:
        """Push the state machine into ERROR with a non-null ``error``."""
        with self._lock:
            self.state = State.ERROR
            self.error = err
            self.stop_requested = True
            self.last_progress_at = _utcnow_iso()

    def clear_error(self) -> None:
        """Acknowledge ERROR by transitioning back to IDLE. Used by
        operators / orchestrator to recover the daemon after a fatal
        pool exception."""
        with self._lock:
            if self.state == State.ERROR:
                self.state = State.IDLE
                self.current_stage_id = None
                self.pool_size = 0
                self.active_workers = 0
                self.games_done = 0
                self.games_claimed_in_flight = 0
                self.error = None
                self.last_progress_at = _utcnow_iso()
                self.loop_thread = None

    def on_claim(self) -> None:
        """Counter bump on a successful /claim — moves a slot into
        in-flight and increments active_workers."""
        with self._lock:
            self.games_claimed_in_flight += 1
            self.active_workers += 1
            self.last_progress_at = _utcnow_iso()

    def on_report(self) -> None:
        """Counter bump on a successful /report_result — moves a slot
        from in-flight to done."""
        with self._lock:
            if self.games_claimed_in_flight > 0:
                self.games_claimed_in_flight -= 1
            if self.active_workers > 0:
                self.active_workers -= 1
            self.games_done += 1
            self.last_progress_at = _utcnow_iso()

    def on_drop(self) -> None:
        """Counter bump for a claim that was discarded (409 on report
        or runner abandoned mid-game). Moves a slot out of in-flight
        WITHOUT incrementing games_done."""
        with self._lock:
            if self.games_claimed_in_flight > 0:
                self.games_claimed_in_flight -= 1
            if self.active_workers > 0:
                self.active_workers -= 1
            self.last_progress_at = _utcnow_iso()

    def is_stop_requested(self) -> bool:
        with self._lock:
            return self.stop_requested

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
                "uptime_s": time.monotonic() - self._process_started_at_monotonic,
                "process_started_at": self.process_started_at,
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


def create_app(
    start_delay_s: float = DEFAULT_START_DELAY_S,
    *,
    weights_root: Path | None = None,
    runner_factory: "RunnerFactory | None" = None,
    retry_backoff_s: tuple[float, ...] | None = None,
    worker_id: str | None = None,
) -> Flask:
    """Build the Flask app with the v2 endpoints wired.

    Each app instance owns its own :class:`WorkerState`. Tests use
    Flask's ``app.test_client()`` to drive the handlers without binding
    a real socket.

    Parameters
    ----------
    start_delay_s:
        Back-compat parameter, retained so existing tests can keep
        passing it. Phase 2b uses a real claim-loop runner whose
        STARTING → RUNNING transition is driven by the runner.setup()
        completion, so this only affects test-only stub fallback
        behavior (the in-process runner does mark_running immediately
        if no runner_factory is supplied).
    weights_root:
        Directory the daemon caches downloaded weights under. Defaults
        to ``./trained_weights/`` relative to the daemon's cwd —
        matches the existing ``cli/shard.py`` convention.
    runner_factory:
        Optional callable invoked with ``(kind, claim_loop_cfg, state_cbs)``
        that returns a :class:`ClaimLoopRunner`. The default factory
        builds a no-op stub runner that just flips STARTING → RUNNING
        after ``start_delay_s`` (so existing tests behave identically
        to the Phase 2a skeleton). Tests that want to exercise the
        full loop supply a factory backed by a callable game runner.
    retry_backoff_s:
        Override the default (1, 3, 10) backoff schedule. Useful in
        tests that hammer 5xx without paying for real sleeps.
    worker_id:
        Override the default :func:`resolve_worker_id` result. Set
        from the CLI's ``--worker-id`` flag.
    """
    app = Flask(__name__)
    state = WorkerState(start_delay_s=start_delay_s)
    # Expose for tests / introspection. Not part of the wire contract.
    app.config["WORKER_STATE"] = state
    resolved_worker_id = worker_id or resolve_worker_id()
    app.config["WORKER_ID"] = resolved_worker_id
    effective_weights_root = (
        Path(weights_root) if weights_root is not None
        else Path("trained_weights")
    )
    app.config["WEIGHTS_ROOT"] = effective_weights_root
    effective_backoff = (
        retry_backoff_s if retry_backoff_s is not None
        else _claim_loop.RETRY_BACKOFF_S
    )
    app.config["RETRY_BACKOFF_S"] = effective_backoff
    app.config["RUNNER_FACTORY"] = runner_factory

    def _state_callbacks() -> _claim_loop.StateCallbacks:
        return _claim_loop.StateCallbacks(
            is_stop_requested=state.is_stop_requested,
            on_claim=state.on_claim,
            on_report=state.on_report,
            on_drop=state.on_drop,
            mark_running=state.mark_running,
            mark_stopping=state.mark_stopping,
            mark_idle=state.mark_idle,
            mark_error=state.mark_error,
        )

    def _spawn_stub_runner(kind: str) -> None:
        """Back-compat: the original Phase 2a skeleton flipped STARTING
        → RUNNING off-thread after a tiny delay. The Phase 2b default
        (no ``runner_factory`` supplied) keeps that behavior so the
        existing test suite passes unchanged.
        """

        def _run() -> None:
            time.sleep(start_delay_s)
            state.mark_running()

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        with state._lock:  # noqa: SLF001
            state.loop_thread = t

    def _spawn_real_runner(
        kind: str,
        body: dict[str, Any],
    ) -> None:
        """Wire the real claim/play/report loop.

        Runs in a daemon thread so the Flask handler can return 202
        without blocking on weights fetch / pool spin-up.
        """
        # ``deck_pool_path`` is an optional field on the start_*
        # request body. ``None`` makes the production runner fall
        # back to the system-wide default
        # (``data/17lands/eoe_decks.json.gz``). Stage-spec callers
        # use it to point at tiny test pools for smoke runs.
        cfg = _claim_loop.ClaimLoopConfig(
            coordinator_url=body["coordinator_url"],
            stage_id=body["stage_id"],
            kind=kind,
            n_workers=int(body.get("n_workers", 0)),
            worker_id=resolved_worker_id,
            weights_root=effective_weights_root,
            shard_label=resolved_worker_id,
            deck_pool_path=body.get("deck_pool_path"),
            retry_backoff_s=effective_backoff,
        )
        cbs = _state_callbacks()
        assert runner_factory is not None  # narrowed via caller
        runner = runner_factory(kind, cfg, cbs)
        loop_runner = _claim_loop.ClaimLoopRunner(cfg, cbs, runner)
        t = threading.Thread(target=loop_runner.run, daemon=True)
        t.start()
        with state._lock:  # noqa: SLF001
            state.loop_thread = t

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
        stage_started_at = _utcnow_iso()
        if runner_factory is not None and body.get("coordinator_url"):
            _spawn_real_runner(kind, body)
        else:
            _spawn_stub_runner(kind)
        return (
            jsonify(
                {
                    "stage_id": stage_id,
                    "stage_started_at": stage_started_at,
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
        # Capture the previous state BEFORE flipping anything.
        previous_state = state.snapshot()["state"]
        # Snapshot the in-flight count so the response reports the
        # number of games being drained at the moment /v2/stop landed.
        with state._lock:  # noqa: SLF001
            drain_in_flight = state.games_claimed_in_flight
        stopped_at = _utcnow_iso()
        if previous_state == State.IDLE:
            # Idempotent. Nothing to do — no thread, no drain.
            return (
                jsonify(
                    {
                        "state": State.IDLE,
                        "previous_state": State.IDLE,
                        "drain_in_flight_games": 0,
                        "stopped_at": stopped_at,
                    }
                ),
                200,
            )
        state.mark_stopping()
        # If a runner thread is running, wait briefly for it to drain.
        # Real-world drain can take ~per_game_timeout_sec; here we cap
        # the synchronous wait so the handler returns quickly. Phase 2c
        # may expose an async "wait for drain" pattern.
        runner_thread = state.loop_thread
        if runner_thread is not None and runner_thread.is_alive():
            runner_thread.join(timeout=_STOP_JOIN_TIMEOUT_S)
        if runner_thread is None or not runner_thread.is_alive():
            # Drained promptly — flip to IDLE here so the response
            # reflects the final state. If the thread is still alive
            # (slow drain), leave the state at STOPPING; the runner
            # itself will flip to IDLE when it finishes.
            state.mark_idle()
        return (
            jsonify(
                {
                    "state": state.snapshot()["state"],
                    "previous_state": previous_state,
                    "drain_in_flight_games": drain_in_flight,
                    "stopped_at": stopped_at,
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
            "process_started_at": snap["process_started_at"],
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
