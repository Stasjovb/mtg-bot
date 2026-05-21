"""Windows job-object guard for subprocess pools (iter_019 BUG #4).

The multiprocessing.Pool on Windows uses the ``spawn`` start method:
each worker is a fresh ``python.exe`` process launched via
``CreateProcess``. The default Pool exit path (``__exit__`` →
``terminate``) correctly tears these down on normal exits AND on
Python exceptions — the ``with Pool() as p:`` context manager calls
``terminate`` from ``__exit__`` whether the body returned normally
or raised.

The leak Lane I diagnosed is a different failure mode: the master
process is killed HARDER than that — ``taskkill /F``, a C-level
segfault, an OOM kill, or any other death that skips Python-level
cleanup. In those cases ``__exit__`` never runs, and on Windows the
spawn-children are NOT in a process group / job object — they orphan
and keep running until manually reaped.

This module provides a thin ``ctypes`` wrapper around the Win32 job
object API to make the kernel itself reap our children when the
master dies for ANY reason. The design:

  guard = JobObjectGuard()                     # creates the job
  with mp.Pool(...) as pool:
      guard.attach_pool_workers(pool)           # adds each spawned
                                                # worker to the job
      ...                                       # work runs
  guard.close()                                 # safe: workers are
                                                # already dead from
                                                # Pool's terminate()

Why we DO NOT add the master to the job (the obvious alternative):
KILL_ON_JOB_CLOSE means "kill every process currently in the job
when the last handle closes." If the master is in the job and we
close our handle (via ``__del__`` at function return, or explicit
``close``), the kernel kills the master itself. The "add children
only" pattern sidesteps that: the job is empty when we close,
nothing to kill. If the master dies mid-pool — without running
``close()`` — the OS closes the handle automatically, the job has
in-flight children inside it, and KILL_ON_JOB_CLOSE fires on those
children. Exactly the property we want.

Why we attach AFTER the pool's children spawn (not via inheritance):
Inheritance requires the master to be in the job pre-spawn, which
is the trap above. Post-spawn attach uses
``OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, FALSE, pid)``
to get a handle on each child, then ``AssignProcessToJobObject``.
The Pool's internal ``_pool`` list exposes the child PIDs.

POSIX is a no-op: ``multiprocessing.Pool`` on Linux/macOS uses
``fork``/``forkserver``, and the worker_daemon's claim-loop pattern
handles those paths separately. The iter_019 leak was a Windows-only
observation; we keep the fix scoped accordingly.

Tested manually by running a smoke that spawns a Pool, attaches the
guard, then ``taskkill /F`` on the master — children die within
milliseconds. Without the guard, children persist until manually
killed.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    import multiprocessing.pool

log = logging.getLogger(__name__)


# ----- Win32 constants ---------------------------------------------------

_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JobObjectExtendedLimitInformation = 9

# OpenProcess access bits we need.
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
        ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _kernel32() -> Optional[ctypes.WinDLL]:
    """Return kernel32 or None on non-Windows. Cached at module load."""
    if sys.platform != "win32":
        return None
    return ctypes.windll.kernel32


class JobObjectGuard:
    """Owns a Win32 job object that auto-kills its members on close.

    Lifecycle:

    1. ``__init__`` creates the job and arms KILL_ON_JOB_CLOSE.
    2. ``attach_pid(pid)`` or ``attach_pool_workers(pool)`` puts
       worker processes into the job. The MASTER is intentionally
       never added (see module docstring).
    3. Hold the instance live for the duration of the work the job
       protects.
    4. ``close()`` releases our handle. If the job is empty (normal
       teardown after pool exit), nothing happens. If the master
       crashes WITHOUT calling ``close()`` while children are still
       in the job, the OS closes the handle on process exit and
       KILL_ON_JOB_CLOSE terminates the remaining workers.

    Non-Windows platforms instantiate cleanly but every method is a
    no-op. Callers don't need a platform check.
    """

    def __init__(self, name: Optional[str] = None) -> None:
        self._handle: Optional[int] = None
        self._k32 = _kernel32()
        self._closed = False
        if self._k32 is None:
            return
        self._k32.CreateJobObjectW.restype = wintypes.HANDLE
        self._k32.CreateJobObjectW.argtypes = [
            wintypes.LPVOID, wintypes.LPCWSTR,
        ]
        handle = self._k32.CreateJobObjectW(None, name)
        if not handle:
            err = ctypes.get_last_error()
            raise OSError(
                f"CreateJobObjectW failed (error={err})"
            )
        self._handle = int(handle)

        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = (
            _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        self._k32.SetInformationJobObject.restype = wintypes.BOOL
        self._k32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int,
            wintypes.LPVOID, wintypes.DWORD,
        ]
        ok = self._k32.SetInformationJobObject(
            self._handle,
            _JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            err = ctypes.get_last_error()
            self.close()
            raise OSError(
                f"SetInformationJobObject failed (error={err})"
            )

    def attach_pid(self, pid: int) -> bool:
        """Put one process (by PID) into the job. Returns True on
        success, False on failure (logged at WARNING).

        Failure modes that are NOT fatal:
        - The PID is already a job member of an incompatible job
          (older Windows / certain Task Scheduler configs); on
          modern Win10+ nested jobs are allowed and this succeeds.
        - The PID exited between Pool spawn and our attach call;
          there's nothing to do.

        We log and return False rather than raising so the caller
        can use this opportunistically — losing the kill-net for
        one stale worker is far better than aborting the whole run.
        """
        if self._k32 is None or self._handle is None:
            return False
        self._k32.OpenProcess.restype = wintypes.HANDLE
        self._k32.OpenProcess.argtypes = [
            wintypes.DWORD, wintypes.BOOL, wintypes.DWORD,
        ]
        proc_handle = self._k32.OpenProcess(
            _PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, int(pid),
        )
        if not proc_handle:
            err = ctypes.get_last_error()
            log.warning(
                "[win32_job] OpenProcess(pid=%d) failed (error=%d); "
                "child stays outside the kill-net.", pid, err,
            )
            return False
        try:
            self._k32.AssignProcessToJobObject.restype = wintypes.BOOL
            self._k32.AssignProcessToJobObject.argtypes = [
                wintypes.HANDLE, wintypes.HANDLE,
            ]
            ok = self._k32.AssignProcessToJobObject(
                self._handle, proc_handle,
            )
            if not ok:
                err = ctypes.get_last_error()
                log.warning(
                    "[win32_job] AssignProcessToJobObject(pid=%d) "
                    "failed (error=%d).", pid, err,
                )
                return False
            return True
        finally:
            self._k32.CloseHandle.restype = wintypes.BOOL
            self._k32.CloseHandle.argtypes = [wintypes.HANDLE]
            self._k32.CloseHandle(proc_handle)

    def attach_pool_workers(
        self, pool: "multiprocessing.pool.Pool",
    ) -> int:
        """Attach every spawned worker in ``pool`` to the job.

        Returns the number of workers successfully attached. The
        mp.Pool exposes its workers via ``_pool`` (a list of
        ``Process`` objects). This is a private attribute but stable
        in CPython for ~15 years; if it ever changes we'll catch it
        via the attribute check below.

        Idempotent: if a worker was already attached on a prior call,
        the second AssignProcessToJobObject is silently OK on
        Win10+.
        """
        if self._k32 is None or self._handle is None:
            return 0
        workers = getattr(pool, "_pool", None)
        if workers is None:
            log.warning(
                "[win32_job] pool has no _pool attribute; "
                "mp.Pool internal API changed?"
            )
            return 0
        attached = 0
        for w in workers:
            pid = getattr(w, "pid", None)
            if pid is None:
                # Process not yet spawned; skip. Caller can retry
                # after Pool work begins, but mp.Pool spawns eagerly
                # so this branch is defensive only.
                continue
            if self.attach_pid(int(pid)):
                attached += 1
        return attached

    def close(self) -> None:
        """Drop our handle. If the job is non-empty and
        KILL_ON_JOB_CLOSE is armed, the kernel terminates every
        process in it. The intended use is to call ``close()`` only
        after the Pool has been torn down (job is empty), or to let
        ``__del__`` fire at interpreter exit / on hard process
        death.
        """
        if self._closed:
            return
        self._closed = True
        if self._k32 is None or self._handle is None:
            return
        self._k32.CloseHandle.restype = wintypes.BOOL
        self._k32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._k32.CloseHandle(self._handle)
        self._handle = None

    def __enter__(self) -> "JobObjectGuard":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:  # noqa: BLE001
            # __del__ MUST NOT raise; close failures during interpreter
            # shutdown are common and not actionable.
            pass

    @property
    def active(self) -> bool:
        """True iff the guard owns a live job handle (Windows + open)."""
        return self._handle is not None and not self._closed
