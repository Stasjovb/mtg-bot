"""Defensive filesystem helpers around the weights directory.

Two layers:

1. **Preflight checks** — verify a target dir is writable (or a source
   dir is listable) before the trainer does several minutes of work
   and then crashes mid-run with a cryptic ``WinError 5``. The check
   raises a ``PermissionError`` whose message embeds the canonical
   repair commands so the operator (or a future agent reading the
   traceback) can paste them into an elevated PowerShell and recover.

2. **Inheritance enablement** — after ``mkdir`` on Windows, call
   ``icacls <path> /inheritance:e`` so the new directory always picks
   up the parent's ACL. Without this, a directory created by an
   elevated process (e.g., training launched from an elevated shell)
   can land with ACL inheritance disabled and only Administrators in
   the access list; subsequent operations from the unelevated user
   token then fail. Best-effort defense; failures are swallowed.

Both helpers are no-ops on non-Windows where the underlying ACL
issues don't exist. They are pure / side-effect-free with respect to
file content — they only touch ACLs and write a single tiny probe
file that they delete immediately.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

# Probe filename used by preflight_writable_dir. Kept unique enough
# that it can't be confused with a real weights artifact, but plain
# enough that a stale one is obviously a probe leftover.
_PROBE_NAME = ".mtg_bot_weights_io_preflight"

# Repair hint embedded in PermissionError messages. The triple of
# commands (takeown -> reset -> inheritance:e) restores ownership to
# the user, wipes broken non-inherited ACL entries, and forces the
# directory to inherit parent perms — the same recipe that recovers
# a busted ``trained_weights\vNN`` dir.
_REPAIR_HINT_WINDOWS = (
    "This is usually a Windows ACL inheritance break (directory "
    "created by an elevated process, then unelevated calls can't "
    "traverse it). Run these from an elevated PowerShell to repair:\n"
    "  takeown /F \"{path}\" /R /D Y\n"
    "  icacls \"{path}\" /reset /T /C\n"
    "  icacls \"{path}\" /inheritance:e /T"
)


def preflight_writable_dir(path: Path) -> None:
    """Verify that ``path`` can be created (if missing) and that we
    can write a file inside it. Raise ``PermissionError`` with an
    actionable repair message on Windows if not.

    Idempotent — the probe file is created and immediately deleted.

    This is intended to run at second 0 of any operation that will
    later write into the directory, so the failure mode is "loud
    early with a fix command" rather than "cryptic Windows error 5
    halfway through epoch 6 after an hour of compute".
    """
    path = Path(path)
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / _PROBE_NAME
        probe.write_bytes(b"ok")
        probe.unlink()
    except PermissionError as exc:
        raise PermissionError(_format_perm_msg(path, exc, write=True)) from exc


def preflight_readable_dir(path: Path) -> None:
    """Verify that ``path`` can be listed. Raise ``PermissionError``
    with the canonical repair message on Windows if not.

    Returns silently (does NOT raise) if ``path`` doesn't exist — the
    caller will hit a clearer ``FileNotFoundError`` later. Returns
    silently if the path exists and lists fine.
    """
    path = Path(path)
    if not path.exists():
        return
    try:
        # Force materialization of the iterator. iterdir() is lazy
        # and a broken directory ACL only fails on the first read.
        list(path.iterdir())
    except PermissionError as exc:
        raise PermissionError(_format_perm_msg(path, exc, write=False)) from exc


def ensure_inheritance_enabled(path: Path) -> None:
    """On Windows, ensure ``path`` has ACL inheritance enabled.

    No-op on non-Windows. No-op if ``icacls`` isn't on PATH. Failures
    from ``icacls`` itself are swallowed — this is a belt-and-suspenders
    defense and should never block the caller's work, even if it can't
    confirm the inheritance bit was actually flipped.

    Effect (when successful): a child directory inside ``trained_weights/``
    that was just created — possibly by a process running with an
    elevated token whose default ACL omits the unelevated user —
    re-inherits the parent's ACL, which on this project includes the
    user's full-control entry.
    """
    if sys.platform != "win32":
        return
    icacls = shutil.which("icacls")
    if icacls is None:
        return
    try:
        subprocess.run(
            [icacls, str(path), "/inheritance:e"],
            capture_output=True,
            text=True,
            timeout=10.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        # Best-effort. The trainer doesn't depend on this succeeding;
        # if icacls is wedged we just lose the defensive layer.
        pass


# ---------------------------------------------------------------------


def _format_perm_msg(path: Path, exc: PermissionError, *, write: bool) -> str:
    """Compose the user-facing PermissionError message.

    On Windows we attach the takeown/icacls repair recipe. Elsewhere
    we just propagate the original errno text with our own framing
    so the traceback origin is unambiguous (this helper, not some
    arbitrary file op deep in numpy / torch).
    """
    verb = "write to" if write else "list"
    base = f"Cannot {verb} {path}: {exc}"
    if sys.platform == "win32":
        hint = _REPAIR_HINT_WINDOWS.format(path=path)
        return f"{base}\n\n{hint}"
    return base
