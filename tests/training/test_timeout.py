"""Tests for ``mtg_bot.training._timeout.run_with_timeout``.

The wrapper has a tight contract: pass through the result on
success, raise ``TimeoutError`` after ``timeout_sec`` elapses, and
do NOT block process exit on a hung thread (so the eval pool can
move on to the next game).
"""

from __future__ import annotations

import threading
import time

import pytest

from mtg_bot.training._timeout import run_with_timeout


def _quick(x: int) -> int:
    return x * 2


def _slow(seconds: float) -> str:
    time.sleep(seconds)
    return "done"


def _stuck(stop: threading.Event) -> None:
    """Pure-Python loop that releases the GIL via the global
    switch-interval (~5ms in CPython 3.x) so the wrapper can
    observe the timeout. Models the engine-bug-induced infinite
    loop: a tight Python loop that doesn't terminate until the
    process exits. ``stop`` lets tests release the function so
    it doesn't keep burning CPU after the test passes."""
    while not stop.is_set():
        # Trivial work; switch-interval lets the timeout thread
        # wake briefly and observe the timeout. Without any work
        # the interpreter still releases the GIL periodically,
        # but adding a no-op kept-busy is more realistic.
        _ = sum(range(100))


# ---------- happy paths -----------------------------------------------------


def test_returns_result_when_function_completes_within_timeout():
    assert run_with_timeout(_quick, (5,), timeout_sec=2.0) == 10


def test_zero_timeout_disables_wrapping():
    """``timeout_sec <= 0`` is the documented "no timeout" mode —
    the wrapper short-circuits and calls ``func(*args)`` directly,
    avoiding the thread-spawn overhead. A function that would
    exceed any positive budget completes normally."""
    assert run_with_timeout(_quick, (3,), timeout_sec=0) == 6
    assert run_with_timeout(_quick, (3,), timeout_sec=-1) == 6


def test_none_timeout_disables_wrapping():
    """``timeout_sec=None`` is the library default; same behavior
    as <= 0: pass-through, no thread."""
    # Cast through Any since the type signature says float; runtime
    # behavior tolerates None per the implementation.
    assert run_with_timeout(_quick, (4,), timeout_sec=None) == 8  # type: ignore[arg-type]


# ---------- timeout firing --------------------------------------------------


def test_raises_timeout_error_when_function_exceeds_budget():
    """The whole point: a function that takes longer than
    ``timeout_sec`` raises ``TimeoutError``. We use ``time.sleep``
    (which releases the GIL) so the timeout fires cleanly."""
    with pytest.raises(TimeoutError, match="exceeded"):
        run_with_timeout(_slow, (1.0,), timeout_sec=0.1)


def test_timeout_fires_on_pure_python_busy_loop():
    """Models the actual engine-bug shape: a busy Python loop
    that doesn't yield to I/O. CPython releases the GIL every
    ``sys.setswitchinterval()`` (~5ms default) so the timeout
    thread wakes and observes the timeout. Without this, hot
    Python loops would never time out."""
    stop = threading.Event()
    try:
        with pytest.raises(TimeoutError):
            run_with_timeout(_stuck, (stop,), timeout_sec=0.15)
    finally:
        # Release the zombie thread so it doesn't keep burning
        # CPU through the rest of the test session.
        stop.set()


def test_timeout_does_not_block_caller_after_firing():
    """After ``TimeoutError`` is raised, the caller should be
    able to continue immediately — the executor's ``shutdown(
    wait=False)`` orphans the hung thread but doesn't block on
    it. Verifies the caller can do more work in the same
    process within a tight time budget."""
    stop = threading.Event()
    started = time.perf_counter()
    try:
        try:
            run_with_timeout(_stuck, (stop,), timeout_sec=0.1)
        except TimeoutError:
            pass
        # The next line must execute promptly — within a generous
        # 1s — even though the zombie thread is still spinning.
        elapsed_after_timeout = time.perf_counter() - started
        assert elapsed_after_timeout < 1.0, (
            f"caller blocked {elapsed_after_timeout:.2f}s after "
            f"timeout — shutdown(wait=False) didn't release"
        )
    finally:
        stop.set()


# ---------- argument forwarding ---------------------------------------------


def test_args_are_forwarded_positionally():
    def add(a, b, c):
        return a + b + c

    assert run_with_timeout(add, (1, 2, 3), timeout_sec=1.0) == 6


def test_function_exception_bubbles_through():
    """Non-timeout exceptions raised by the wrapped function are
    re-raised with their original type and message — the caller's
    existing try/except (eval-pool-resilience) catches engine
    crashes via this path, NOT via TimeoutError."""
    def boom():
        raise ValueError("custom message")

    with pytest.raises(ValueError, match="custom message"):
        run_with_timeout(boom, (), timeout_sec=1.0)
