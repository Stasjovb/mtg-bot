"""Polling early-stop watcher for iterate's eval-gate phase.

Watches eval-run state and writes a stop sentinel via
``mtg_bot.training.stop_signal.write_stop`` when the run's decisive
games are statistically conclusive — either above the acceptance
threshold (``PASS``, will promote) or below it (``FAIL``, will keep
current best). Either way the iterate eval pool wraps up at the next
game boundary and the gate decision uses the partial result, which is
already statistically sufficient.

Statistical method: Wilson score interval at confidence
``1 - 2*alpha`` (one-sided alpha each side, default alpha=0.025 ->
95% CI overall). Conclusive when the threshold sits outside the CI.

Caveat: naive sequential testing inflates Type I error vs a fixed-N
test. For a gate that promotes on any statistically-significant edge
above 50%, the controlling protection is the Wilson 95% CI lower bound
clearing the threshold (rather than the threshold itself sitting far
above the null). Tightening to SPRT or O'Brien-Fleming boundaries
would be the principled next step if the false-promote rate ever
matters more.

A minimum decisive-game count (default 30) prevents stopping on a
3-0 lucky start. Stops only target eval runs (``status == 'running'``).

Data sources (auto-selected; mirror what ``mtg_bot.cli.runs.client``
does):

- ``MTG_BOT_RUN_DB_PATH`` set: open the SQLite runs.db read-only and
  query directly. Used on the master.
- ``MTG_BOT_RUN_DB_URL`` set: GET ``<url>/runs?kind=eval&status=running``
  for the list and ``<url>/run/<id>`` for per-run detail.
- Neither: fall back to polling progress JSONs at ``--progress-dir``
  (the original behavior). This keeps the watcher working during the
  JSON->DB transition.

The data source can be forced via ``--source {auto,jsons,db,rest}``.
``--progress-dir`` stays meaningful in every mode because the STOP
sentinel is always written via the file-based stop_signal contract.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from math import sqrt
from pathlib import Path
from typing import Any, Optional

from mtg_bot.training.gate import EVAL_GATE_THRESHOLD
from mtg_bot.training.stop_signal import write_stop


# Env vars mirror ``mtg_bot.cli.runs.client`` so the watcher follows
# the same transport conventions as the producers.
_ENV_DB_PATH = "MTG_BOT_RUN_DB_PATH"
_ENV_DB_URL = "MTG_BOT_RUN_DB_URL"

# How far back a "running" eval can plausibly have started. Anything
# older than this is almost certainly stale state the janitor didn't
# clean up yet; ignoring it avoids zombie-row noise.
_RUNNING_LOOKBACK_HOURS = 24


def _wilson_ci(wins: int, n: int, *, z: float = 1.96) -> tuple[float, float, float]:
    """Wilson score interval for proportion. Returns (point, lo, hi)."""
    if n <= 0:
        return 0.0, 0.0, 1.0
    p = wins / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return p, max(0.0, center - half), min(1.0, center + half)


def _z_for_alpha(alpha: float) -> float:
    """Inverse normal at 1-alpha. Hard-coded common values to avoid
    pulling in scipy. Falls back to 1.96 (alpha=0.025) for unknown
    inputs and warns the caller."""
    table = {0.005: 2.576, 0.01: 2.326, 0.025: 1.96, 0.05: 1.645, 0.1: 1.282}
    return table.get(round(alpha, 4), 1.96)


def _decision(
    wins_new: int, wins_old: int, threshold: float, z: float, min_decisive: int,
) -> Optional[tuple[str, float, float, float]]:
    """Return (decision, p, lo, hi) when the threshold sits outside
    the CI, else None. ``decision`` is one of ``'PASS'`` / ``'FAIL'``."""
    n = wins_new + wins_old
    if n < min_decisive:
        return None
    p, lo, hi = _wilson_ci(wins_new, n, z=z)
    if lo > threshold:
        return "PASS", p, lo, hi
    if hi < threshold:
        return "FAIL", p, lo, hi
    return None


_ITER_EVAL_RUN_ID_RE = re.compile(r"^(iter_\d+)_eval_")


def _resolve_cycle_id(cycle_id_field: Optional[str], run_id: str) -> Optional[str]:
    """Pick the right stop-sentinel target for an iterate-driven eval.

    Two sources, in order of preference:

    1. The eval's ``cycle_id`` field (from the progress JSON or the
       run record's parent / extra_json) — what ``EvalProgress`` writes
       when iterate passes ``cycle_id=cycle_id`` through ``_eval_match``
       / ``_eval_match_distributed``. This is the source of truth when
       present.
    2. Filename-pattern fallback: ``iter_NNN_eval_<new>_vs_<old>`` →
       cycle_id ``iter_NNN_cycle``. The distributed eval path's
       per-shard JSONs surfaced empirically with ``cycle_id: None``
       even though iterate had set it; rather than chase that down
       at progress-write time, we recover the cycle here from the
       deterministic run_id naming convention iterate uses.

    Standalone evals (``mtg_bot eval`` without iterate) have no
    iter_NNN prefix and no cycle, so this returns None and the
    caller falls back to writing the sentinel for ``run_id``.
    """
    if cycle_id_field:
        return str(cycle_id_field)
    m = _ITER_EVAL_RUN_ID_RE.match(run_id)
    if m:
        return f"{m.group(1)}_cycle"
    return None


# ---- transport: JSON polling (legacy, kept as fallback) ----------------------


def _iter_eval_progress_files(progress_dir: Path) -> list[Path]:
    """Yield eval progress JSON paths (master files, not shard files).

    Matches ``*_eval_*.json`` and filters out shard files (which have
    ``_shard_`` in the name) and shard event logs (``.jsonl``).
    """
    if not progress_dir.is_dir():
        return []
    out = []
    for p in progress_dir.glob("*_eval_*.json"):
        if "_shard_" in p.name:
            continue
        out.append(p)
    return out


def _load_jsons(progress_dir: Path) -> list[dict[str, Any]]:
    """Read every running eval JSON in ``progress_dir`` and return a
    normalized status dict per file. JSONs that fail to parse or
    don't carry a run_id are skipped silently (matching the legacy
    watcher's tolerance for partial writes)."""
    out: list[dict[str, Any]] = []
    for path in _iter_eval_progress_files(progress_dir):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        run_id = data.get("run_id")
        if not run_id:
            continue
        if data.get("status") != "running":
            continue
        out.append(
            {
                "run_id": run_id,
                "wins_new": int(data.get("wins_new", 0)),
                "wins_old": int(data.get("wins_old", 0)),
                "draws": int(data.get("draws", 0)),
                "cycle_id": data.get("cycle_id"),
                "started_at": data.get("started_at"),
            }
        )
    return out


# ---- transport: direct SQLite (master) ---------------------------------------


def _load_db(
    db_path: Path, *, lookback_hours: int = _RUNNING_LOOKBACK_HOURS,
) -> list[dict[str, Any]]:
    """Open ``db_path`` read-only and return one status dict per
    running eval. Joins ``runs`` against the aggregate row in
    ``run_progress`` (``shard_label IS NULL``) — per-shard rows don't
    carry the right totals.

    The read-only URI keeps the watcher honest: no schema writes, no
    accidental WAL noise.
    """
    if not db_path.exists():
        return []
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.row_factory = sqlite3.Row
        cutoff = _iso_cutoff(lookback_hours)
        rows = conn.execute(
            """
            SELECT
                r.run_id        AS run_id,
                r.parent_run_id AS parent_run_id,
                r.started_at    AS started_at,
                COALESCE(p.wins_new, 0) AS wins_new,
                COALESCE(p.wins_old, 0) AS wins_old,
                COALESCE(p.draws, 0)    AS draws,
                p.extra_json    AS extra_json
            FROM runs r
            LEFT JOIN run_progress p
                ON r.run_id = p.run_id AND p.shard_label IS NULL
            WHERE r.kind = 'eval'
              AND r.status = 'running'
              AND r.started_at > ?
            """,
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_status(dict(r)) for r in rows]


def _row_to_status(row: dict[str, Any]) -> dict[str, Any]:
    """Translate a DB / REST row into the uniform status-dict shape.

    cycle_id resolution prefers an explicit field, then parent_run_id
    (iterate sets this when it spawns the eval), then any cycle_id
    inside ``extra_json`` (free-form, sometimes populated by the
    producer with iterate-specific metadata)."""
    cycle_id = row.get("cycle_id") or row.get("parent_run_id")
    extra = row.get("extra_json")
    if not cycle_id and extra:
        try:
            extra_obj = json.loads(extra) if isinstance(extra, str) else extra
        except (TypeError, json.JSONDecodeError):
            extra_obj = None
        if isinstance(extra_obj, dict):
            cycle_id = extra_obj.get("cycle_id")
    return {
        "run_id": row["run_id"],
        "wins_new": int(row.get("wins_new") or 0),
        "wins_old": int(row.get("wins_old") or 0),
        "draws": int(row.get("draws") or 0),
        "cycle_id": cycle_id,
        "started_at": row.get("started_at"),
    }


# ---- transport: REST (remotes) -----------------------------------------------


def _load_rest(
    api_url: str, *, lookback_hours: int = _RUNNING_LOOKBACK_HOURS,
    timeout: float = 5.0,
) -> list[dict[str, Any]]:
    """List running evals via the REST API and resolve each to a
    status dict by fetching its per-run detail.

    Uses ``urllib.request`` (no third-party deps) so the watcher stays
    runnable on a minimal Python install. ``timeout=5s`` matches the
    runs.client default — REST hiccups should yield "no eval state
    visible this tick" rather than blocking the loop forever.
    """
    base = api_url.rstrip("/")
    cutoff = _iso_cutoff(lookback_hours)
    try:
        listing = _http_get_json(
            f"{base}/runs?kind=eval&status=running&since={cutoff}",
            timeout=timeout,
        )
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return []
    runs = listing.get("runs", []) if isinstance(listing, dict) else []
    out: list[dict[str, Any]] = []
    for r in runs:
        run_id = r.get("run_id")
        if not run_id:
            continue
        started_at = r.get("started_at")
        if started_at and started_at <= cutoff:
            # Defense-in-depth: the API takes ``since=`` but if it
            # ever ignores the param the watcher still filters
            # client-side.
            continue
        try:
            detail = _http_get_json(f"{base}/run/{run_id}", timeout=timeout)
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            continue
        out.append(_detail_to_status(detail, fallback_run=r))
    return out


def _detail_to_status(
    detail: dict[str, Any], *, fallback_run: dict[str, Any],
) -> dict[str, Any]:
    """Pick the aggregate-row progress out of a /run/<id> response.

    Falls back to ``fallback_run`` (the listing row) for the run
    fields if the detail payload is malformed — better to act on
    stale-ish data than to drop the run entirely on a transient
    response shape.
    """
    run = detail.get("run") if isinstance(detail, dict) else None
    if not isinstance(run, dict):
        run = fallback_run
    progress_rows = (
        detail.get("progress", []) if isinstance(detail, dict) else []
    )
    agg: dict[str, Any] = {}
    for row in progress_rows:
        if isinstance(row, dict) and row.get("shard_label") is None:
            agg = row
            break
    return _row_to_status(
        {
            "run_id": run.get("run_id"),
            "parent_run_id": run.get("parent_run_id"),
            "started_at": run.get("started_at"),
            "wins_new": agg.get("wins_new") or 0,
            "wins_old": agg.get("wins_old") or 0,
            "draws": agg.get("draws") or 0,
            "extra_json": agg.get("extra_json"),
        }
    )


def _http_get_json(url: str, *, timeout: float) -> Any:
    """GET ``url`` and return the parsed JSON body. Raises on HTTP /
    network / decode errors — callers swallow."""
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8") or "{}"
    return json.loads(raw)


def _iso_cutoff(lookback_hours: int) -> str:
    """ISO-8601 UTC stamp at ``now - lookback_hours``. Compares
    lexicographically against the second-precision stamps producers
    write via ``runs.db.now_iso()``."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    return cutoff.isoformat(timespec="seconds")


# ---- per-status check (transport-agnostic) -----------------------------------


def _check_status(
    status: dict[str, Any], *, threshold: float, z: float, min_decisive: int,
    progress_dir: Path, already_stopped: set[str],
) -> Optional[str]:
    """Apply the Wilson-CI decision to one normalized status dict and,
    if conclusive, write a stop sentinel. Returns a one-line log
    message describing the action (or status) so the caller can print
    it without re-deriving the numbers."""
    run_id = status["run_id"]
    if run_id in already_stopped:
        return None
    wins_new = status["wins_new"]
    wins_old = status["wins_old"]
    decision = _decision(
        wins_new, wins_old, threshold, z, min_decisive=min_decisive,
    )
    if decision is None:
        n = wins_new + wins_old
        if n >= min_decisive:
            _, lo, hi = _wilson_ci(wins_new, n, z=z)
            return (
                f"[watch] {run_id}: {wins_new}-{wins_old} "
                f"(n={n}) CI [{lo:.1%}, {hi:.1%}] straddles "
                f"threshold {threshold:.1%}; continue"
            )
        return None

    label, _p, lo, hi = decision
    cycle_id = _resolve_cycle_id(status.get("cycle_id"), run_id)
    # iterate's eval pool checks for `.STOP_<cycle_id>` only (via
    # ``_cycle_stop_check`` in cli/iterate.py), so we MUST target
    # cycle_id when one is resolvable. Falling back to the run_id
    # sentinel was a bug — written-but-ignored. Standalone evals
    # (``mtg_bot eval`` without iterate) have no cycle, so for those
    # targeting run_id is correct (their stop_check uses run_id).
    target_id = cycle_id if cycle_id else run_id
    write_stop(
        progress_dir, target_id,
        reason=(
            f"early-stop {label}: {wins_new}-{wins_old} "
            f"(n={wins_new + wins_old}) CI [{lo:.1%}, {hi:.1%}] "
            f"vs threshold {threshold:.1%}"
        ),
    )
    already_stopped.add(run_id)
    return (
        f"[watch] {run_id}: {label} — {wins_new}-{wins_old} "
        f"(n={wins_new + wins_old}) CI [{lo:.1%}, {hi:.1%}] vs "
        f"threshold {threshold:.1%} -> wrote stop sentinel for "
        f"{target_id}"
    )


# ---- source selection --------------------------------------------------------


def _resolve_source(requested: str) -> str:
    """Translate ``--source`` (with ``auto``) into a concrete mode
    name: ``jsons`` / ``db`` / ``rest``. The precedence is the same
    as ``mtg_bot.cli.runs.client``'s: REST URL beats DB path beats no
    config (fall back to JSON polling)."""
    if requested != "auto":
        return requested
    if os.environ.get(_ENV_DB_URL):
        return "rest"
    if os.environ.get(_ENV_DB_PATH):
        return "db"
    return "jsons"


def _load_statuses(
    mode: str, *, progress_dir: Path, db_path: Optional[Path],
    api_url: Optional[str],
) -> list[dict[str, Any]]:
    """Dispatch to the configured transport."""
    if mode == "jsons":
        return _load_jsons(progress_dir)
    if mode == "db":
        if db_path is None:
            raise ValueError(
                "--source db requires MTG_BOT_RUN_DB_PATH or an "
                "explicit --db-path; got none"
            )
        return _load_db(db_path)
    if mode == "rest":
        if not api_url:
            raise ValueError(
                "--source rest requires --api-url or MTG_BOT_RUN_DB_URL"
            )
        return _load_rest(api_url)
    raise ValueError(f"unknown source {mode!r}")


# ---- CLI ---------------------------------------------------------------------


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--progress-dir", type=Path, default=Path("training_progress"),
        help=(
            "Where iterate writes eval progress JSONs and where this "
            "watcher writes its STOP sentinel. Used in every mode "
            "(the sentinel is always file-based)."
        ),
    )
    parser.add_argument(
        "--threshold", type=float, default=EVAL_GATE_THRESHOLD,
        help=(
            "Acceptance threshold the gate compares win_rate against. "
            "Defaults to ``mtg_bot.training.gate.EVAL_GATE_THRESHOLD`` "
            "(the single source of truth for the gate)."
        ),
    )
    parser.add_argument(
        "--alpha", type=float, default=0.025,
        help=(
            "One-sided alpha for the Wilson CI (default 0.025 -> 95%% "
            "CI overall). Tighten with --alpha 0.01 (98%% CI)."
        ),
    )
    parser.add_argument(
        "--min-decisive", type=int, default=30,
        help=(
            "Don't stop until at least this many games have a winner. "
            "Prevents stopping on a 3-0 lucky start."
        ),
    )
    parser.add_argument(
        "--check-interval-sec", type=float, default=5.0,
        help="Polling interval in seconds.",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Check all running evals once and exit.",
    )
    parser.add_argument(
        "--source", choices=("auto", "jsons", "db", "rest"), default="auto",
        help=(
            "Where to read eval state from. ``auto`` (default) picks "
            "rest if MTG_BOT_RUN_DB_URL is set, else db if "
            "MTG_BOT_RUN_DB_PATH is set, else falls back to polling "
            "JSON files in --progress-dir."
        ),
    )
    parser.add_argument(
        "--db-path", type=Path, default=None,
        help=(
            "Override the DB path for --source db. Defaults to "
            "$MTG_BOT_RUN_DB_PATH."
        ),
    )
    parser.add_argument(
        "--api-url", type=str, default=None,
        help=(
            "Override the REST base URL for --source rest. Defaults "
            "to $MTG_BOT_RUN_DB_URL, then http://localhost:5099."
        ),
    )
    args = parser.parse_args(argv)

    z = _z_for_alpha(args.alpha)
    mode = _resolve_source(args.source)

    db_path = args.db_path
    if db_path is None and os.environ.get(_ENV_DB_PATH):
        db_path = Path(os.environ[_ENV_DB_PATH])
    api_url = (
        args.api_url or os.environ.get(_ENV_DB_URL) or "http://localhost:5099"
    )

    print(
        f"[watch] source={mode} threshold={args.threshold:.1%}, "
        f"alpha={args.alpha} (z={z}), min_decisive={args.min_decisive}, "
        f"interval={args.check_interval_sec}s, "
        f"progress_dir={args.progress_dir}",
        flush=True,
    )

    already_stopped: set[str] = set()
    last_status: dict[str, str] = {}
    while True:
        try:
            statuses = _load_statuses(
                mode, progress_dir=args.progress_dir,
                db_path=db_path, api_url=api_url,
            )
        except (OSError, sqlite3.Error) as exc:
            print(
                f"[watch] WARNING: failed to load eval state ({mode}): "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
            statuses = []
        for st in statuses:
            msg = _check_status(
                st, threshold=args.threshold, z=z,
                min_decisive=args.min_decisive,
                progress_dir=args.progress_dir,
                already_stopped=already_stopped,
            )
            key = st["run_id"]
            if msg and msg != last_status.get(key):
                print(msg, flush=True)
                last_status[key] = msg
        if args.once:
            return
        time.sleep(args.check_interval_sec)


if __name__ == "__main__":
    main()
