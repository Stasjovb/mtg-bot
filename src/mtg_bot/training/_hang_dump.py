"""Diagnostic dumps for per-game timeouts in data-gen / eval workers.

When a game hits its wall-clock budget (--per-game-timeout-sec), the
worker thread is still running and the watchdog raises ``TimeoutError``
to abandon it. Without a dump we lose the reproducer entirely — the
sentinel return advances the pool but leaves no trace of WHAT got
stuck. ``dump_hang_diagnostics`` writes a structured pair of files so
the failing game can be re-run and the live call stack inspected.

Files written per hang event::

    <dir>/hang_seed{base_seed}_idx{game_idx:04d}_<utc>.json
    <dir>/hang_seed{base_seed}_idx{game_idx:04d}_<utc>.txt

The .json carries reproducible inputs (seeds + per-call config). The
.txt is ``faulthandler.dump_traceback(all_threads=True)`` so you can
see exactly which call stack the game thread was inside when the
timeout fired — including whether it was deep in ``MCTS._search_serial``
(the runaway-MCTS manifestation) vs blocked in ``mp.queues.get`` (the
deadlock manifestation), the two patterns we've seen via py-spy.

The helper NEVER raises: a failed dump must not also break the
worker, since the existing sentinel-return path still needs to run.
"""

from __future__ import annotations

import faulthandler
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def dump_hang_diagnostics(
    dump_dir: str,
    *,
    base_seed: int,
    game_idx: int,
    engine_seed: int,
    error_type: str,
    error_message: str,
    extra: Optional[dict[str, Any]] = None,
) -> Optional[Path]:
    """Write a hang-event meta.json + traceback.txt under ``dump_dir``.

    Returns the meta.json ``Path`` on success, ``None`` if anything
    failed (filesystem error, permissions, anything). Diagnostic
    capture must never crash the worker.
    """
    try:
        dir_path = Path(dump_dir)
        dir_path.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        stem = f"hang_seed{base_seed}_idx{game_idx:04d}_{ts}"
        meta_path = dir_path / f"{stem}.json"
        traceback_path = dir_path / f"{stem}.txt"
        meta: dict[str, Any] = {
            "game_idx": game_idx,
            "base_seed": base_seed,
            "engine_seed": engine_seed,
            "error_type": error_type,
            "error_message": error_message,
            "captured_at": datetime.now(timezone.utc).isoformat(
                timespec="seconds",
            ),
            "pid": os.getpid(),
        }
        if extra:
            meta.update(extra)
        meta_path.write_text(
            json.dumps(meta, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        with traceback_path.open("w", encoding="utf-8") as f:
            faulthandler.dump_traceback(file=f, all_threads=True)
        return meta_path
    except Exception:  # noqa: BLE001 - intentional
        return None
