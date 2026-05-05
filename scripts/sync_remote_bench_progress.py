"""Sync a remote bench-progress JSON to a local path on a fixed cadence.

The Mac standalone bench (``scripts/bench_per_game_wall.py`` with
``--progress-dir``) writes a BenchProgress JSON file to local disk on
the Mac. The training UI on the master Windows box reads progress files
out of its own ``training_progress/`` directory. This helper is the
bridge: it polls a remote file via ``scp`` over tailscale and writes it
into the master's progress directory so the UI can render the bench
card alongside data-gen / training / eval runs.

Usage::

    python scripts/sync_remote_bench_progress.py \\
        --remote-host greggs-macbook-pro \\
        --remote-path /Users/greggkeithley/projects/mtg-bot/training_progress/bench_20260504T120000Z.json \\
        --local-path C:/Users/Gregg\\ Keithley/Documents/Claude/Projects/mtg-bot/training_progress/bench_20260504T120000Z.json \\
        --interval-sec 3

The poll loop stops when the synced JSON's ``status`` field is
``completed`` or ``failed``, or on Ctrl-C. Transient ``scp`` failures
(file not yet created on the remote, network blip) are swallowed —
they're expected at startup and the next tick will retry.

Logging is intentionally minimal: one line per status change plus a
final summary.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional


_TERMINAL_STATUSES = {"completed", "failed"}


def _scp_pull(
    *,
    remote_host: str,
    remote_path: str,
    local_path: Path,
    timeout_sec: float,
) -> Optional[str]:
    """Run a single scp pull. Returns None on success, an error string
    on failure. Does NOT raise — transient failures are normal at the
    start of a sync (the remote file may not exist yet) so we hand the
    error back for the caller to log/swallow as it sees fit.
    """
    local_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "scp",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=5",
        f"{remote_host}:{remote_path}",
        str(local_path),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired:
        return f"scp timeout after {timeout_sec}s"
    except FileNotFoundError:
        return "scp executable not found in PATH"
    if result.returncode != 0:
        # Trim stderr — scp prints the file-missing message on one line
        # and we don't want to spam the log on every retry.
        err = (result.stderr or result.stdout or "").strip()
        return err.splitlines()[-1] if err else (
            f"scp exit code {result.returncode}"
        )
    return None


def _read_status(local_path: Path) -> Optional[str]:
    """Return the ``status`` field from the synced JSON, or None if the
    file is missing / unreadable / malformed. The bench writes its file
    atomically (atomic_write_json) so a successful read of a non-empty
    file should yield a parseable JSON object.
    """
    try:
        text = local_path.read_text(encoding="utf-8")
    except (OSError, FileNotFoundError):
        return None
    if not text.strip():
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    status = payload.get("status")
    return str(status) if status is not None else None


def sync_loop(
    *,
    remote_host: str,
    remote_path: str,
    local_path: Path,
    interval_sec: float,
    scp_timeout_sec: float = 30.0,
) -> str:
    """Block until the remote file's status is terminal or Ctrl-C.
    Returns the final status string ("completed" / "failed" /
    "interrupted").
    """
    last_status: Optional[str] = None
    last_err: Optional[str] = None
    print(
        f"# syncing {remote_host}:{remote_path}\n"
        f"#      -> {local_path}\n"
        f"# interval={interval_sec}s",
        file=sys.stderr,
        flush=True,
    )
    try:
        while True:
            err = _scp_pull(
                remote_host=remote_host,
                remote_path=remote_path,
                local_path=local_path,
                timeout_sec=scp_timeout_sec,
            )
            if err is not None:
                if err != last_err:
                    print(
                        f"# scp transient: {err}",
                        file=sys.stderr,
                        flush=True,
                    )
                    last_err = err
            else:
                last_err = None
                status = _read_status(local_path)
                if status != last_status:
                    print(
                        f"# status: {last_status!r} -> {status!r}",
                        file=sys.stderr,
                        flush=True,
                    )
                    last_status = status
                if status in _TERMINAL_STATUSES:
                    return status
            time.sleep(interval_sec)
    except KeyboardInterrupt:
        print("# interrupted", file=sys.stderr, flush=True)
        return "interrupted"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--remote-host", required=True,
        help="ssh-resolvable host for scp (e.g. tailnet hostname).",
    )
    parser.add_argument(
        "--remote-path", required=True,
        help="Absolute path to the progress JSON on the remote.",
    )
    parser.add_argument(
        "--local-path", required=True, type=Path,
        help=(
            "Absolute path on the master where the synced JSON lands. "
            "Should be inside the training UI's progress_dir."
        ),
    )
    parser.add_argument(
        "--interval-sec", type=float, default=3.0,
        help="Seconds between scp polls (default 3.0).",
    )
    parser.add_argument(
        "--scp-timeout-sec", type=float, default=30.0,
        help=(
            "Per-scp-call timeout. Should comfortably exceed the time "
            "to copy a ~50KB JSON over tailscale (default 30.0)."
        ),
    )
    args = parser.parse_args(argv)

    final_status = sync_loop(
        remote_host=args.remote_host,
        remote_path=args.remote_path,
        local_path=args.local_path,
        interval_sec=args.interval_sec,
        scp_timeout_sec=args.scp_timeout_sec,
    )
    print(f"# final status: {final_status}", file=sys.stderr, flush=True)
    return 0 if final_status in _TERMINAL_STATUSES else 1


if __name__ == "__main__":
    sys.exit(main())
