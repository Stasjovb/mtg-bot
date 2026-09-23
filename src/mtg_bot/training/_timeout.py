"""Per-game wall-clock timeout helper.

PIMC games occasionally hit a state where MCTS expansion grinds
forever inside ``effects/combinators.resolve`` (the residual engine
state-corruption bug tracked by todo ``e3b7d9c1`` / ``d4f2a8c1``), and
far more often a game is simply expensive enough to blow the wall
budget. Without a timeout, one stuck game blocks the whole worker pool
— the parent's ``imap_unordered`` waits indefinitely for the result,
the other workers stay idle, and the eval/data-gen run requires manual
killing.

This module wraps a single game in a daemon thread with a
configurable wall-clock budget. If the budget is exceeded, the
caller raises ``TimeoutError``; the eval/data-gen worker-crash
handler (``eval-pool-resilience`` and the equivalent in
``data_gen``) catches it and converts to the standard "dropped
game" sentinel.

Cooperative stop (2026-09-23)
-----------------------------

The original version of this module simply abandoned the thread and
documented the consequences as "manageable." They were not. CPython
can't kill a thread, so the abandoned game kept running inside the
multiprocessing worker while the pool handed that same worker the
next game: two full games executing concurrently in one process,
sharing the interpreter, the numpy/torch runtimes, the module-level
tokenizer caches and the process-global search telemetry. The
2026-09-23 production logs show the result directly —
``ladder_runs/prod_2026-09-23/run.log`` has two
``Fatal Python error: _PyEval_EvalFrameDefault: Executing a cache.``
dumps whose thread lists contain **two** live
``self_play._play_capped_game`` frames in one worker, followed
immediately by a torn tokenizer dict surfacing as
``ValueError: could not broadcast input array from shape (59,7) into
shape (58,7)`` out of ``_collate_structured_token_dicts``.

A zombie thread also permanently burns a core for the rest of the
run, so every timeout shrinks the pool's effective width and makes
the *next* timeout more likely — a feedback loop that is visible in
the ladder's random-vs-v13s pair.

So: on timeout we now flip a ``CancelToken`` bound to the game
thread (``mtg_bot.cancellation``) and wait up to
``DEFAULT_STOP_GRACE_SEC`` for it to unwind. The game loop and the
MCTS / ISMCTS / PIMC search loops call ``raise_if_cancelled()``, so
the stop normally lands within one search iteration (sub-millisecond
to a few ms). Only if the thread is wedged inside a single
non-cooperative call (a genuine engine hang — the case the module was
originally written for) do we fall back to the old behavior of
leaving it running, and then we say so loudly on stderr.

``mp.Pool.__exit__`` calls ``terminate()``, which kills the worker
process and any surviving thread with it, so a wedged thread is
still bounded by run duration.
"""

from __future__ import annotations

import concurrent.futures
import sys
import threading
from typing import Any, Callable, TypeVar

from mtg_bot.cancellation import CancelToken, bind_token, unbind_token

T = TypeVar("T")

# How long to wait for a cancelled game thread to unwind before
# giving up on it and returning to the caller. The cooperative checks
# sit in the MCTS/ISMCTS iteration loops and the per-decision game
# loop, so a healthy thread stops in well under a second; the generous
# default only matters for a thread wedged inside one long
# non-cooperative call, where waiting longer wouldn't help anyway.
DEFAULT_STOP_GRACE_SEC = 30.0


def run_with_timeout(
    func: Callable[..., T],
    args: tuple,
    timeout_sec: float,
    *,
    stop_grace_sec: float = DEFAULT_STOP_GRACE_SEC,
) -> T:
    """Run ``func(*args)`` in a daemon thread with a ``timeout_sec``
    wall-clock cap. Returns the function's result on success.

    Raises ``TimeoutError`` if ``timeout_sec`` elapses before the
    function returns. Before raising, the game thread is asked to
    stop cooperatively and joined for up to ``stop_grace_sec``; the
    exception message records whether the stop landed.

    ``timeout_sec`` of ``None`` / ``<= 0`` runs ``func`` inline in the
    calling thread with no token bound — cancellation checks are then
    unconditional no-ops, matching the pre-cancellation behavior.

    The thread releases the GIL periodically (every
    ``sys.setswitchinterval()``, default ~5ms) so this caller can
    wake up and observe the timeout even when the inner code is
    a tight Python loop. CUDA / NumPy / native code release the
    GIL more aggressively, so timeouts there fire promptly.
    """
    if timeout_sec is None or timeout_sec <= 0:
        return func(*args)

    token = CancelToken()
    finished = threading.Event()

    def _runner() -> Any:
        bind_token(token)
        try:
            return func(*args)
        finally:
            unbind_token()
            finished.set()

    # daemon=True so the thread doesn't block process exit if it
    # ends up zombie. ThreadPoolExecutor's default daemons follow
    # the executor lifetime; with shutdown(wait=False) the thread
    # is effectively orphaned and dies with the process.
    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="game-timeout",
    )
    try:
        future = executor.submit(_runner)
        try:
            return future.result(timeout=timeout_sec)
        except concurrent.futures.TimeoutError as exc:
            stopped = _stop_and_wait(
                token, finished, timeout_sec, stop_grace_sec,
            )
            # Standard library lifts FuturesTimeoutError into the
            # builtin TimeoutError on Python 3.11+; either way the
            # public surface should be the unambiguous builtin.
            suffix = (
                "game thread stopped cleanly."
                if stopped
                else (
                    "game thread did NOT stop within "
                    f"{stop_grace_sec:.0f}s and is still running — it "
                    "will be reaped when the pool terminates the "
                    "worker."
                )
            )
            raise TimeoutError(
                f"game exceeded {timeout_sec:.1f}s wall-clock; "
                f"abandoning. {suffix}"
            ) from exc
    finally:
        # ``wait=False`` — don't block process exit on a thread that
        # refused to stop. The cooperative cancel above is what makes
        # this safe in the normal case.
        executor.shutdown(wait=False)


def _stop_and_wait(
    token: CancelToken,
    finished: threading.Event,
    timeout_sec: float,
    stop_grace_sec: float,
) -> bool:
    """Cancel ``token`` and wait for the game thread to unwind.

    Returns True if the thread finished within ``stop_grace_sec``.
    Emits a loud stderr warning when it didn't, because that is the
    only remaining path to the two-games-in-one-process corruption
    this machinery exists to prevent.
    """
    token.cancel(
        f"per-game wall-clock budget of {timeout_sec:.1f}s exceeded",
    )
    if stop_grace_sec <= 0:
        stopped = finished.is_set()
    else:
        stopped = finished.wait(timeout=stop_grace_sec)
    if not stopped:
        print(
            "[timeout] WARNING: abandoned game thread did not honour "
            f"the cooperative stop within {stop_grace_sec:.0f}s. It is "
            "still running and now shares this worker process with the "
            "next game — expect torn shared state. This is the wedged-"
            "in-native-code case; capture a hang dump.",
            file=sys.stderr,
        )
    return stopped
