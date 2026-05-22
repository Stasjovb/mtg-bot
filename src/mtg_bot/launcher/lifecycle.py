"""Cycle lifecycle: a single ``cycle_lifecycle`` ctx mgr that wires
``runs.db`` start-and-finish around the launcher's whole orchestration.

Why this exists: every iter_NNN session has historically had at
least one path that exits without writing a terminal status to the
DB (signal, exception, Python crash, OS reboot mid-launch) -- which
leaves the UI showing the cycle ``running`` long after it's dead.
The cycle_lifecycle ctx mgr funnels EVERY exit path through ONE
``_finalize_cycle(status)`` call so the UI never lies about cycle
state.

Hooks installed on enter:

- ``signal.SIGINT`` / ``signal.SIGTERM`` -> translate to a clean
  ``KeyboardInterrupt`` which the ctx mgr catches and marks
  ``killed``.
- ``atexit`` -> last-resort backstop; fires on interpreter shutdown
  even when the normal ctx-mgr exit path was bypassed (segfault in
  a C extension, hard kill of a child subprocess that left this
  process limping out, ...).

Exit-status mapping:

- Normal completion (no exception) -> ``completed``.
- ``KeyboardInterrupt`` (from a signal) -> ``killed``.
- Any other exception -> ``failed``, exception message routed into
  the ``notes`` column for forensics.

The ctx mgr SPANS the iterate subprocess. The Phase A launcher
spawns ``mtg_bot iterate`` as a Popen child (NOT execv -- see the
"Plan deviation: subprocess vs execv" section in the README); the
launcher process stays alive for the whole iterate run so the
lifecycle finaliser can fire on launcher death and clean up the
DB row + AWS fleet (Phase B).
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import platform
import signal
import subprocess
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Optional

from mtg_bot.cli.runs import client as _runs_client


logger = logging.getLogger(__name__)


# Signals the ctx mgr installs handlers for. SIGTERM is what
# Windows Task Scheduler / a `kill -TERM` from the operator sends;
# SIGINT is Ctrl-C in the foreground terminal.
_SIGNALS = (signal.SIGINT, signal.SIGTERM)


@dataclass
class CycleLifecycle:
    """Mutable holder the ctx mgr returns to the body.

    ``set_completed_status()`` lets the body explicitly mark a
    non-failure terminal status -- e.g. iterate's subprocess
    returned a non-zero exit code that the launcher interpreted as
    "killed by user" rather than "crashed".

    ``mark_finalized()`` is an escape hatch for body code that has
    already written the terminal status itself (rare; the normal
    contract is "let the ctx mgr do it").
    """

    cycle_id: str
    _finalized: bool = False
    _explicit_status: Optional[str] = None

    def mark_finalized(self) -> None:
        """Tell the ctx mgr the body has already written the
        terminal status; skip the finaliser."""
        self._finalized = True

    def set_completed_status(self, status: str) -> None:
        """Override the default ``completed`` on normal exit.

        ``status`` must be one of ``completed`` / ``failed`` /
        ``killed``. Useful when the iterate subprocess returned a
        non-zero code that the launcher wants to characterise (e.g.
        the user pressed Stop and iterate drained -> ``killed``,
        not ``failed``).
        """
        if status not in ("completed", "failed", "killed"):
            raise ValueError(
                f"set_completed_status: status must be one of "
                f"completed/failed/killed; got {status!r}",
            )
        self._explicit_status = status


def _serialize_config(config: dict[str, Any]) -> str:
    """Stable JSON for the ``config_json`` column.

    sort_keys=True so a diff between two runs is meaningful;
    default=str so any non-JSON-native value (Path, etc.) serialises
    without crashing the launcher.
    """
    return json.dumps(config, sort_keys=True, default=str)


def _resolve_status_from_exception(exc: BaseException) -> tuple[str, str]:
    """Translate an exception type into ``(status, notes)``.

    ``KeyboardInterrupt`` (raised by our SIGINT/SIGTERM handler) -> ``killed``.
    Everything else -> ``failed``.
    """
    if isinstance(exc, KeyboardInterrupt):
        return "killed", "killed by signal / KeyboardInterrupt"
    return "failed", f"{type(exc).__name__}: {exc}"


@contextmanager
def cycle_lifecycle(
    cycle_id: str,
    *,
    config: dict[str, Any],
    git_commit: str,
    kind: str = "iterate",
    label: Optional[str] = None,
    started_at: Optional[str] = None,
    force_resume_from_failed: bool = False,
) -> Iterator[CycleLifecycle]:
    """Register the cycle in runs.db, install signal + atexit
    finalisers, yield a :class:`CycleLifecycle`, and guarantee the
    cycle ends with a terminal status in the DB no matter how the
    body exits.

    Parameters:

    - ``cycle_id`` -- runs.db row id (typically ``iter_NNN_cycle``).
    - ``config`` -- dict serialised into ``runs.config_json`` for
      the DB row + UI forensics.
    - ``git_commit`` -- short hash for the ``git_commit`` column.
    - ``kind`` -- DB ``kind`` column. Defaults to ``"iterate"``
      because that's the launcher's only Phase A consumer.
    - ``label`` -- optional human-readable cycle label
      (``iter_021``).
    - ``started_at`` -- ISO-8601 UTC; defaults to "now" inside the
      runs client.
    - ``force_resume_from_failed`` -- on a conflict (running /
      completed row), bail unless this flag is set. Today the
      runs.client swallows conflicts as warnings -- the flag is
      reserved for future strict-mode behavior; the body still
      runs.

    Yields a :class:`CycleLifecycle` the body can use to override
    the terminal status (``set_completed_status``) or signal the
    body already handled finalisation (``mark_finalized``).

    Idempotent against re-entry: the ctx mgr does not currently
    support nesting two lifecycles for the same cycle_id, but
    finalisation is guarded by ``handle.mark_finalized`` /
    ``_finalized`` so the at-exit hook never double-writes.
    """
    handle = CycleLifecycle(cycle_id=cycle_id)
    # Lock guards the finaliser body so a signal arriving mid-finalise
    # (or two threads racing to finalise) only emits one finish_run.
    finalize_lock = threading.Lock()

    def _finalize(status: str, notes: Optional[str] = None) -> None:
        with finalize_lock:
            if handle._finalized:
                return
            handle._finalized = True
        # Best-effort: the runs.client already swallows network
        # errors; this just adds an extra "swallow-and-log" layer
        # for sqlite/SQLAlchemy-style failures that could surface
        # if the DB file went away between start and finish.
        try:
            _runs_client.finish_run(cycle_id, status, notes=notes)
        except Exception:  # noqa: BLE001 - last-resort log
            logger.exception(
                "cycle_lifecycle: finish_run(%s, %s) failed; "
                "the UI may continue to show this cycle as running.",
                cycle_id, status,
            )

    # ---- Register the cycle row (must succeed before any side effect)
    _runs_client.start_run(
        cycle_id,
        kind=kind,
        config_json=_serialize_config(config),
        git_commit=git_commit,
        label=label,
        started_at=started_at,
        pid=os.getpid(),
        host=platform.node(),
    )
    # _ unused -- the flag exists for the CLI surface only.
    _ = force_resume_from_failed

    # ---- atexit backstop (fires even on hard interpreter shutdown)
    def _atexit_finalize() -> None:
        # If the body completed cleanly, _finalized is already True
        # and this is a no-op. The atexit hook is for the
        # "interpreter died without unwinding the ctx mgr" path
        # (segfault, os._exit, etc.).
        if not handle._finalized:
            _finalize("failed", notes="atexit fallback (no clean shutdown)")

    atexit.register(_atexit_finalize)

    # ---- Signal handlers
    # Translate SIGTERM / SIGINT into KeyboardInterrupt so the
    # ctx mgr's exception-handling branch picks it up. Save the
    # previous handlers so we can restore on exit (otherwise we
    # leak global state into any code that runs after the
    # launcher's main returns -- e.g. test fixtures).
    saved_handlers: dict[int, Any] = {}

    def _raise_kbi(signum, frame):  # noqa: ARG001 - signal-handler signature
        # Raising from a signal handler trips Python's "interrupt
        # the main thread" path -- which is what we want. Stash the
        # signum on the handle so debug logs can see which signal
        # arrived (not used by the finaliser today; reserved).
        raise KeyboardInterrupt(f"signal {signum} -> KeyboardInterrupt")

    # signal.signal() only works on the main thread; if the
    # launcher is invoked from a non-main thread (unusual; tests),
    # silently skip installation rather than crashing.
    in_main_thread = threading.current_thread() is threading.main_thread()
    if in_main_thread:
        for sig in _SIGNALS:
            try:
                saved_handlers[sig] = signal.signal(sig, _raise_kbi)
            except (OSError, ValueError):
                # Windows doesn't support SIGTERM-via-signal in all
                # contexts; the atexit backstop + KeyboardInterrupt
                # from Ctrl-C still cover the normal case.
                pass

    try:
        yield handle
    except KeyboardInterrupt as exc:
        status, notes = _resolve_status_from_exception(exc)
        _finalize(status, notes=notes)
        raise
    except Exception as exc:  # noqa: BLE001 - we re-raise after finalising
        status, notes = _resolve_status_from_exception(exc)
        _finalize(status, notes=notes)
        raise
    else:
        explicit = handle._explicit_status
        _finalize(explicit if explicit is not None else "completed")
    finally:
        # Restore the prior signal handlers no matter what.
        if in_main_thread:
            for sig, prev in saved_handlers.items():
                try:
                    signal.signal(sig, prev)
                except (OSError, ValueError):
                    pass


# ---------------------------------------------------------------------------
# Helper: spawn iterate as a subprocess + wait
# ---------------------------------------------------------------------------


def spawn_iterate_subprocess(
    argv: list[str],
    *,
    env: Optional[dict[str, str]] = None,
    cwd: Optional[str] = None,
    popen_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
) -> int:
    """Run ``mtg_bot iterate ...`` as a child subprocess and wait.

    Returns iterate's exit code. Forwards SIGINT/SIGTERM the parent
    receives to the child so a Ctrl-C in the launcher's terminal
    cleanly drains iterate (which already understands the
    .STOP_<cycle_id> sentinel + stop-requested flag in the DB).

    ``popen_factory`` is the indirection used by tests to swap in a
    stub that records the argv without actually spawning a process.
    """
    proc = popen_factory(
        argv,
        env=env or os.environ.copy(),
        cwd=cwd,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    try:
        return proc.wait()
    except KeyboardInterrupt:
        # Propagate to the child. The launcher's signal handler has
        # already raised KBI in the parent -- forward to the child
        # so it drains cleanly rather than orphaning.
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001 - best-effort
            pass
        # Give the child a moment, then proceed to re-raise so the
        # ctx mgr's exception branch fires.
        try:
            proc.wait(timeout=30)
        except Exception:  # noqa: BLE001
            pass
        raise


__all__ = [
    "CycleLifecycle",
    "cycle_lifecycle",
    "spawn_iterate_subprocess",
]
