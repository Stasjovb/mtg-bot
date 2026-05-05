"""Sentinel-file-based stop-run mechanism.

The training UI's "Stop run" button writes a sentinel file
``training_progress/.STOP_<run_id>`` (optionally containing a JSON
body with ``{"requested_at": ISO, "reason": str}``). Long-running
producers (``iterate_alphazero`` cycle loop, ``data_gen``'s
imap_unordered loop, ``self_play.run_match_parallel``'s eval pool,
the queue server in ``serve_setup_scripts.py``) check for the
sentinel at well-defined boundaries and exit cleanly when they see
it, finalizing their progress JSON with status="stopped" so the UI
labels them as user-aborted rather than failed.

v1 design — checks happen at *stage boundaries* (between iterate
stages; between game-batch dispatches in the eval/data-gen pools;
on each ``/queue/take`` request). Mid-game responsiveness is NOT a
goal — see ``docs/SEARCH_LIMITATIONS.md`` for the documented
divergence.

Cycle-vs-single-run targeting:

- ``iterate_alphazero`` writes a cycle-level progress JSON (one per
  iteration) with ``run_id`` == cycle_id. Child runs (self-play,
  train, eval) carry a ``cycle_id`` field pointing back to the
  cycle.
- The UI's stop handler looks at the clicked run's ``cycle_id``;
  when present, the sentinel is written for the cycle (which stops
  the whole iteration), otherwise for the single run.
- The cycle loop checks for ``.STOP_<cycle_id>`` between stages.
- The child producers check for ``.STOP_<child_run_id>`` AND
  ``.STOP_<cycle_id>`` (if a cycle_id is known) so a cycle-level
  stop also halts an in-flight stage.

Public API:

- ``sentinel_path(progress_dir, run_id)``
- ``stop_requested(progress_dir, run_id)``
- ``write_stop(progress_dir, run_id, reason=None)``
- ``cleanup_orphans(progress_dir, active_run_ids)``
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

# Filename prefix for sentinel files. Chosen with a leading dot so
# the sentinel never gets globbed by the UI's ``*.json`` listing,
# and so a casual ``ls`` of the progress dir won't surface them.
_SENTINEL_PREFIX = ".STOP_"


def sentinel_path(progress_dir: Path, run_id: str) -> Path:
    """Return the canonical sentinel path for ``run_id`` inside
    ``progress_dir``. Pure function — does not touch the filesystem."""
    return Path(progress_dir) / f"{_SENTINEL_PREFIX}{run_id}"


def stop_requested(
    progress_dir: Path, run_id: str,
    *,
    cycle_id: Optional[str] = None,
) -> bool:
    """``True`` if a stop sentinel exists for ``run_id`` (or for
    ``cycle_id``, when given). Either sentinel halts the run — a
    cycle-level stop must propagate to in-flight children.

    Robust to the progress dir not existing yet (returns False —
    nothing to stop) and to transient FS errors (a brief OSError
    during a sentinel-file probe shouldn't abort an in-flight run;
    we'd rather miss one tick of the check than crash the producer).
    """
    progress_dir = Path(progress_dir)
    if not progress_dir.is_dir():
        return False
    candidates = [run_id]
    if cycle_id and cycle_id != run_id:
        candidates.append(cycle_id)
    for rid in candidates:
        try:
            if sentinel_path(progress_dir, rid).exists():
                return True
        except OSError:
            # FS hiccup; treat as "no stop requested" for this tick.
            # The next call will retry.
            continue
    return False


def write_stop(
    progress_dir: Path,
    run_id: str,
    *,
    reason: Optional[str] = None,
) -> Path:
    """Write a sentinel file requesting a stop for ``run_id``.

    Idempotent — calling twice does NOT error; the second call
    overwrites the body with a fresh timestamp + reason. The body is
    a small JSON document so logs / post-mortems can attribute the
    stop, but consumers only need to check for file existence.

    Creates ``progress_dir`` if it doesn't exist — the UI may be the
    first writer (the producer creates ``progress_dir`` lazily on
    first flush, and the user might click stop before any progress
    file lands).
    """
    progress_dir = Path(progress_dir)
    progress_dir.mkdir(parents=True, exist_ok=True)
    path = sentinel_path(progress_dir, run_id)
    payload = {
        "run_id": run_id,
        "requested_at": datetime.now(timezone.utc).isoformat(
            timespec="seconds",
        ),
        "reason": reason or "",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def cleanup_orphans(
    progress_dir: Path,
    active_run_ids: Iterable[str],
) -> list[Path]:
    """Delete sentinel files in ``progress_dir`` whose run_id is NOT
    in ``active_run_ids``. Called when a fresh run starts (or at the
    top of a new cycle in iterate_alphazero) to drop any stale
    sentinels left over from previous sessions — without this, a
    sentinel from yesterday's iter_001 would immediately abort
    today's iter_001.

    Returns the list of removed paths so the caller can log what was
    cleaned up.
    """
    progress_dir = Path(progress_dir)
    if not progress_dir.is_dir():
        return []
    keep = set(active_run_ids)
    removed: list[Path] = []
    for path in progress_dir.iterdir():
        name = path.name
        if not name.startswith(_SENTINEL_PREFIX):
            continue
        rid = name[len(_SENTINEL_PREFIX):]
        if rid in keep:
            continue
        try:
            path.unlink()
            removed.append(path)
        except OSError:
            # Best-effort; if another process holds the file we'll
            # try again next cleanup. A leftover sentinel is at
            # worst an immediate stop of a re-used run_id, which
            # already requires the user to opt in (they have to
            # reuse an exact id from a prior session).
            continue
    return removed


def read_stop_payload(
    progress_dir: Path, run_id: str,
) -> Optional[dict]:
    """Read the JSON body of an existing sentinel, if any. Returns
    ``None`` if the sentinel doesn't exist or the body isn't
    parseable — callers should treat that as "stop was requested,
    no metadata available" rather than as "no stop." Useful for
    log messages and progress-finalize reasons.
    """
    path = sentinel_path(progress_dir, run_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
