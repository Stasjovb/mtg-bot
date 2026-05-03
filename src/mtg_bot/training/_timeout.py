"""Per-game wall-clock timeout helper.

PIMC games occasionally hit a state where MCTS expansion grinds
forever inside ``effects/combinators.resolve`` (the residual engine
state-corruption bug tracked by todo ``e3b7d9c1`` / ``d4f2a8c1``).
Without a timeout, one stuck game blocks the whole worker pool —
the parent's ``imap_unordered`` waits indefinitely for the result,
the other 23 workers stay idle, and the eval/data-gen run requires
manual killing.

This module wraps a single game in a daemon thread with a
configurable wall-clock budget. If the budget is exceeded, the
caller raises ``TimeoutError``; the eval/data-gen worker-crash
handler (``eval-pool-resilience`` and the equivalent in
``data_gen``) catches it and converts to the standard "dropped
game" sentinel.

Caveat: when the timeout fires, the daemon thread that's actually
running the game keeps running in the background. We don't kill
threads in CPython — ``thread.cancel`` doesn't exist, and SIGKILL-
equivalents only work at the process level. The hung thread will:

  - Continue burning CPU until the worker process exits (pool
    teardown). On a 32-core box with 24 workers each potentially
    holding one zombie thread, that's a maximum ~1 extra core
    pinned per worker. Manageable.
  - Prevent the worker process from cleanly exiting until SOMETHING
    kills it. ``mp.Pool.__exit__`` calls ``terminate()`` which
    sends SIGTERM (Windows: TerminateProcess), which kills the
    process and all its threads. Confirmed via the Phase-1
    eval-pool-resilience tests.

A fully-correct fix would require process-per-game (heavy spawn
cost) or a cooperative timeout check inside MCTS itself
(invasive). The thread approach is the pragmatic mitigation —
exactly what the user asked for ("a simple timeout may suffice").
"""

from __future__ import annotations

import concurrent.futures
from typing import Any, Callable, TypeVar

T = TypeVar("T")


def run_with_timeout(
    func: Callable[..., T],
    args: tuple,
    timeout_sec: float,
) -> T:
    """Run ``func(*args)`` in a daemon thread with a ``timeout_sec``
    wall-clock cap. Returns the function's result on success.

    Raises ``TimeoutError`` if ``timeout_sec`` elapses before the
    function returns. The daemon thread continues running in the
    background — see module docstring for the implications.

    The thread releases the GIL periodically (every
    ``sys.setswitchinterval()``, default ~5ms) so this caller can
    wake up and observe the timeout even when the inner code is
    a tight Python loop. CUDA / NumPy / native code release the
    GIL more aggressively, so timeouts there fire promptly.
    """
    if timeout_sec is None or timeout_sec <= 0:
        return func(*args)

    # daemon=True so the thread doesn't block process exit if it
    # ends up zombie. ThreadPoolExecutor's default daemons follow
    # the executor lifetime; with shutdown(wait=False) the thread
    # is effectively orphaned and dies with the process.
    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="game-timeout",
    )
    try:
        future = executor.submit(func, *args)
        try:
            return future.result(timeout=timeout_sec)
        except concurrent.futures.TimeoutError as exc:
            # Standard library lifts FuturesTimeoutError into the
            # builtin TimeoutError on Python 3.11+; either way the
            # public surface should be the unambiguous builtin.
            raise TimeoutError(
                f"game exceeded {timeout_sec:.1f}s wall-clock; "
                f"abandoning."
            ) from exc
    finally:
        # ``wait=False`` — don't block process exit on a hung
        # thread. The thread keeps running until the worker
        # process is terminated by the pool at run end.
        executor.shutdown(wait=False)
