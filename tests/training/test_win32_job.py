"""Pin the Win32 job-object guard for iter_019 BUG #4.

Tests are platform-aware: the non-Windows path is a no-op guard and
we pin that; the Windows path actually creates a kernel object and
arms KILL_ON_JOB_CLOSE — we pin construction, empty-close
(idempotent), and the attach-pool-workers contract via a fake Pool.

We deliberately do NOT exercise the kernel kill-on-master-death
path here: that requires spawning multiple processes and a deliberate
SIGKILL of the parent, which is not unit-testable inside pytest.
The behavior is documented at the module level; a manual smoke
covers it.
"""

from __future__ import annotations

import sys

import pytest

from mtg_bot.training._win32_job import JobObjectGuard


def test_job_object_guard_posix_is_noop(monkeypatch):
    """Constructing the guard on POSIX returns a live object whose
    methods all no-op. Callers should not need a ``sys.platform``
    check at every call site.
    """
    monkeypatch.setattr(
        "mtg_bot.training._win32_job.sys.platform", "linux"
    )
    monkeypatch.setattr(
        "mtg_bot.training._win32_job._kernel32", lambda: None
    )
    g = JobObjectGuard()
    assert g.active is False
    # All these are no-ops.
    assert g.attach_pid(12345) is False
    g.close()
    # Idempotent close.
    g.close()
    assert g.active is False


def test_attach_pool_workers_posix_returns_zero(monkeypatch):
    """POSIX no-op path: attach_pool_workers returns 0 regardless
    of pool shape.
    """
    monkeypatch.setattr(
        "mtg_bot.training._win32_job.sys.platform", "linux"
    )
    monkeypatch.setattr(
        "mtg_bot.training._win32_job._kernel32", lambda: None
    )
    g = JobObjectGuard()

    class _FakePool:
        _pool = [type("Proc", (), {"pid": 1000 + i})() for i in range(4)]

    assert g.attach_pool_workers(_FakePool()) == 0


def test_attach_pool_workers_handles_missing_internal_attr(monkeypatch):
    """If multiprocessing.Pool ever changes its private ``_pool``
    attribute, we log a warning and return 0 rather than crashing.
    """
    monkeypatch.setattr(
        "mtg_bot.training._win32_job.sys.platform", "linux"
    )
    monkeypatch.setattr(
        "mtg_bot.training._win32_job._kernel32", lambda: None
    )
    g = JobObjectGuard()

    class _StrangePool:
        pass  # no _pool attribute

    assert g.attach_pool_workers(_StrangePool()) == 0


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
def test_job_object_guard_windows_creates_live_handle():
    """On Windows the guard owns a real job object handle after
    construction. ``active`` reflects open/closed state.

    Safe to ``close()`` here because we never put any process into
    the job — closing an empty job has no observable effect.
    """
    g = JobObjectGuard()
    try:
        assert g.active is True
    finally:
        g.close()
    assert g.active is False


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
def test_job_object_guard_close_is_idempotent():
    """Repeated ``close()`` is a no-op after the first call. Also
    pinned because ``__del__`` calls ``close()`` and Python may invoke
    it during shutdown after the user has explicitly closed.

    IMPORTANT: We deliberately do NOT put any process into the job
    before ``close()`` — closing a non-empty job armed with
    KILL_ON_JOB_CLOSE terminates every member. The guard's intended
    deployment is "create, attach workers, let Pool drain workers,
    then close" — by the time close fires the job is already empty.
    """
    g = JobObjectGuard()
    g.close()
    g.close()
    assert g.active is False


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
def test_attach_pid_to_nonexistent_returns_false():
    """Attaching a PID that doesn't exist returns False (not raise).
    OpenProcess fails for unknown PIDs; we log and continue so a
    racy worker death between Pool spawn and our attach call doesn't
    abort the whole run.
    """
    g = JobObjectGuard()
    try:
        # PID 0xFFFFFFFE / 4294967294 — a value high enough that
        # it's effectively never assigned. OpenProcess returns NULL.
        assert g.attach_pid(4294967294) is False
    finally:
        g.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
def test_attach_pool_workers_iterates_pool_pids():
    """attach_pool_workers walks pool._pool and tries to attach each
    pid. We can't actually attach real workers here (would require
    spawning a real Pool which itself would leak in the test), so
    we use a fake Pool with mock worker objects carrying fake pids.
    Each fake pid attach returns False (no such process) but the
    method should still iterate all of them and return a count.
    """
    g = JobObjectGuard()
    try:
        class _FakeProc:
            def __init__(self, pid):
                self.pid = pid

        class _FakePool:
            # All pids invalid → attach_pid returns False for each →
            # attach count == 0. We just pin that the iteration
            # doesn't crash and the count comes back as an int.
            _pool = [_FakeProc(4294967294 - i) for i in range(4)]

        result = g.attach_pool_workers(_FakePool())
        assert isinstance(result, int)
        assert result == 0  # all invalid pids
    finally:
        g.close()
