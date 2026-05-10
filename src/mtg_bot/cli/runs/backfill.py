"""Backfill historical ``training_progress/*.json`` into ``runs.db``.

Phase 2 of the runs-DB migration swaps the training UI off the JSON
files and onto SQLite. Most masters have hundreds of pre-Phase-1 JSON
files describing completed iterate / self-play / train / eval / bench
runs that pre-date the dual-write loop and therefore have NO matching
DB row. If the UI swap landed without a backfill, all that history
would silently disappear from the dashboard.

This module walks ``progress_dir/*.json`` and idempotently upserts
each file's contents into ``runs`` + ``run_progress`` (+ a
``run_artifacts`` row pointing at the JSON itself).

Idempotency contract
--------------------
The backfill is safe to re-run any number of times:

* If the ``runs`` row for ``run_id`` already exists AND its DB status
  is terminal (``completed`` / ``failed`` / ``killed``), the row is
  left untouched — we never resurrect a finished run as ``running``.
* If the existing DB row's status is non-terminal (``running``), the
  JSON's terminal status (when present) wins — this lets a stuck
  ``running`` row get advanced by a re-run after the producer wrote
  its final JSON.
* ``run_progress`` is upserted unconditionally — counters can move
  forward only.
* ``run_artifacts`` keys on ``(run_id, artifact_type, path)`` so
  re-registering the same JSON path is a no-op except for refreshing
  the ``bytes`` column (in case the file grew).

Status-mapping
--------------
The DB schema's ``status`` enum is ``running / completed / failed /
killed``. Producer JSONs (especially ``iterate.py``'s stop-sentinel
path) widely use ``"stopped"`` to mean "user requested a clean stop".
We map ``stopped`` -> ``killed`` on insert and stash the original
JSON-side status in ``extra_json["original_status"]`` so the UI can
still display "stopped" verbatim.

Stale-running heuristic
-----------------------
A JSON with ``status="running"`` and no ``ended_at`` is *almost
always* the corpse of a producer that died before finalizing. We mark
those as terminal via these signals, in priority order:

1. The JSON has ``ended_at`` set -> trust the JSON, use its status.
2. The JSON has ``status != "running"`` -> trust the JSON, use it.
3. The JSON's mtime is older than ``stale_after_hours`` (default 6h)
   -> stamp ``status="killed"``, ``ended_at = file mtime``,
   ``notes`` notes the heuristic.
4. The JSON's mtime is recent BUT a sibling ``.STOP_<run_id>``
   sentinel exists -> same treatment.
5. Otherwise -> the run might genuinely still be running, so import
   the row with ``status="running"`` and let the next producer-side
   write (or the next backfill invocation) move it forward.

The 6-hour cutoff is a heuristic, not a guarantee. The dual-write
producer continues to run alongside the backfill, so any race the
heuristic gets wrong gets immediately corrected by the producer's
next ``finish_run`` call.

Per-shard files
---------------
A filename matching ``<run_id>_shard_<label>.json`` is treated as
the per-shard ``run_progress`` row. The aggregate ``<run_id>.json``
becomes the ``shard_label IS NULL`` row. Per-shard JSONs without a
matching aggregate JSON still create a ``runs`` row (synthesizing
the aggregate from the shard's run_id stem) so the UI's per-shard
sub-cards have a parent to render against.

Excluded files
--------------
* ``*_events.jsonl`` — shard event log files (line-delimited),
  not run records.
* ``*_result.json`` — shard distinguishing result file used by
  the queue lease; not a run record.
* Files under any directory beginning with ``_quarantine`` —
  intentionally retired runs the user has set aside.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from mtg_bot.cli.runs import db as runs_db
from mtg_bot.cli.runs.models import (
    Artifact, ProgressUpdate, Run,
)


# Default "stale running" cutoff for the heuristic. 6 hours is well
# beyond any single producer stage's wall time (longest is the cycle
# itself, but ``ended_at`` gets stamped on it via the lifecycle
# wrapper). Live producers refresh their JSON every minute or two, so
# 6h of no-mtime-update == "this is dead".
DEFAULT_STALE_AFTER_HOURS = 6.0

# JSON kind -> DB kind mapping. The DB schema's enum is canonical;
# the JSONs have historical / UI-facing names that don't all match.
_KIND_JSON_TO_DB = {
    "data_gen": "self_play",
    "cycle": "iterate",
    # Already-canonical kinds pass through unchanged.
    "self_play": "self_play",
    "iterate": "iterate",
    "eval": "eval",
    "training": "training",
    "bench": "bench",
    "capture": "capture",
}

# Statuses we accept from the JSON but the DB enum doesn't carry.
_STATUS_JSON_TO_DB = {
    "running": "running",
    "completed": "completed",
    "failed": "failed",
    "killed": "killed",
    "stopped": "killed",  # Map to closest DB enum; preserved in extra_json.
}

# Counter fields that map directly into run_progress columns. Anything
# else flows through extra_json.
_PROGRESS_COLUMN_FIELDS = (
    "n_games_done",
    "n_games_total",
    "elapsed_seconds",
    "crashed",
    "timed_out",
    "wins_new",
    "wins_old",
    "draws",
)

# Top-level JSON fields that live on the ``runs`` row directly. Anything
# else either flows into run_progress (via _PROGRESS_COLUMN_FIELDS) or
# into run_progress.extra_json (everything else).
_RUNS_COLUMN_FIELDS = (
    "run_id", "kind", "status", "started_at", "ended_at",
    "git_commit", "notes", "label", "parent_run_id",
)

# Filename pattern for per-shard JSONs.
_SHARD_FILENAME_RE = re.compile(r"^(?P<stem>.+)_shard_(?P<label>[^/\\]+?)\.json$")


@dataclass
class BackfillSummary:
    """Counters returned by :func:`backfill_progress_dir`. The CLI
    prints these in the human-readable summary so the user can sanity
    check that "N runs upserted" matches ~the JSON count."""

    runs_inserted: int = 0
    runs_updated: int = 0
    runs_skipped_terminal: int = 0
    progress_rows_upserted: int = 0
    shard_rows_upserted: int = 0
    artifacts_registered: int = 0
    stale_running_marked_terminal: int = 0
    files_skipped: int = 0
    files_unparseable: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        return d

    def render(self) -> str:
        """Multi-line human-readable summary. Used by the CLI."""
        lines = [
            f"runs inserted               : {self.runs_inserted}",
            f"runs updated (non-terminal) : {self.runs_updated}",
            f"runs left alone (terminal)  : {self.runs_skipped_terminal}",
            f"progress rows upserted      : {self.progress_rows_upserted}",
            f"per-shard rows upserted     : {self.shard_rows_upserted}",
            f"artifacts registered        : {self.artifacts_registered}",
            f"stale-running -> terminal   : {self.stale_running_marked_terminal}",
            f"files skipped (non-record)  : {self.files_skipped}",
            f"files unparseable           : {self.files_unparseable}",
        ]
        if self.errors:
            lines.append("errors:")
            for err in self.errors:
                lines.append(f"  - {err}")
        return "\n".join(lines)


def _read_json(path: Path) -> Optional[dict[str, Any]]:
    """Read one JSON file. Returns ``None`` for unparseable, missing,
    or non-dict content. Handles BOM-prefixed UTF-8 (some early
    producer JSONs were written by tools that prepend a BOM)."""
    try:
        # ``utf-8-sig`` transparently strips a leading BOM if present
        # but works fine on plain UTF-8 too.
        with path.open("r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _is_excluded_filename(name: str) -> bool:
    """Filter out non-run-record files. Per-shard JSONs are NOT
    excluded — the caller separates them via :func:`_shard_match`.

    Note: ``*_events.jsonl`` files are NOT considered here because
    the caller's outer ``glob('*.json')`` already filters them out
    (the ``.jsonl`` extension doesn't match). They're documented in
    the module docstring as "excluded files" so reading the source
    isn't surprising — the fact that the glob handles it is an
    implementation detail.
    """
    if name.endswith("_result.json"):
        return True
    return False


def _shard_match(name: str) -> Optional[tuple[str, str]]:
    """If ``name`` is a per-shard file, return ``(parent_run_id,
    shard_label)``. Otherwise None.

    Filename convention: ``<parent_run_id>_shard_<label>.json``. We
    purposefully match against the trailing ``_shard_<label>`` suffix
    so unrelated underscores in ``parent_run_id`` (which is common —
    e.g. ``iter_001_self_play_v6``) don't confuse the regex."""
    m = _SHARD_FILENAME_RE.match(name)
    if not m:
        return None
    return m.group("stem"), m.group("label")


def _now_iso() -> str:
    return runs_db.now_iso()


def _file_mtime_iso(path: Path) -> str:
    """ISO timestamp from file mtime. Used for ``ended_at`` on stale-
    running runs the heuristic finalizes."""
    ts = path.stat().st_mtime
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


def _is_stop_sentinel_present(progress_dir: Path, run_id: str) -> bool:
    """A ``.STOP_<run_id>`` file in progress_dir is the user's UI-side
    stop request. If we see one alongside a stale-running JSON, the
    producer crashed/exited without honoring it — treat as terminal."""
    return (progress_dir / f".STOP_{run_id}").is_file()


def _resolve_status_and_kind(
    payload: dict[str, Any],
    json_path: Path,
    *,
    progress_dir: Path,
    stale_after_hours: float,
    now: float,
) -> tuple[str, Optional[str], dict[str, Any]]:
    """Apply the stale-running heuristic + DB-enum mapping.

    Returns ``(db_status, db_ended_at, extra_overrides)``. ``extra_overrides``
    is a dict of fields to merge into ``extra_json`` so the UI can
    surface the human-readable original values (e.g. JSON status
    ``"stopped"`` becomes DB ``"killed"``; UI gets ``original_status:
    "stopped"`` from extra_json).
    """
    raw_status = payload.get("status") or "running"
    extra: dict[str, Any] = {}

    # Map JSON status to DB enum, stashing the original.
    db_status = _STATUS_JSON_TO_DB.get(raw_status, raw_status)
    if db_status != raw_status:
        extra["original_status"] = raw_status

    # Resolve ended_at preference: JSON > stale heuristic > None.
    ended_at = payload.get("ended_at")

    if db_status == "running":
        # Heuristic only applies if JSON itself says it's still running.
        if ended_at:
            # If the producer wrote ended_at AND status=running, the
            # producer is buggy — but the wall-clock end time is real.
            # Promote to ``killed`` and stash the inconsistency.
            extra["original_status"] = raw_status
            extra["backfill_note"] = (
                "JSON had status=running with ended_at set; "
                "promoted to killed."
            )
            db_status = "killed"
        else:
            try:
                mtime = json_path.stat().st_mtime
            except OSError:
                mtime = 0.0
            age_hours = (now - mtime) / 3600.0 if mtime else float("inf")
            stale_by_age = age_hours >= stale_after_hours
            stop_sentinel = _is_stop_sentinel_present(
                progress_dir, payload.get("run_id") or json_path.stem,
            )
            if stale_by_age or stop_sentinel:
                # File is older than the cutoff (or a stop was
                # requested) but no producer-side finalization landed.
                # Treat as user-stopped/killed.
                ended_at = _file_mtime_iso(json_path) if mtime else _now_iso()
                db_status = "killed"
                extra["original_status"] = raw_status
                if stop_sentinel and not stale_by_age:
                    reason = "stop sentinel present, producer never finalized"
                else:
                    reason = (
                        f"mtime age >= {stale_after_hours}h "
                        f"({age_hours:.1f}h); no producer-side finalize"
                    )
                extra["backfill_note"] = (
                    f"stale-running heuristic: {reason}"
                )

    return db_status, ended_at, extra


def _split_payload(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Slice the JSON payload into three buckets:

    * ``run_fields`` — keys that map to the ``runs`` table columns.
    * ``progress_fields`` — keys that map to ``run_progress`` columns.
    * ``extra`` — everything else, headed for ``extra_json``.

    The triplet preserves keys verbatim; the caller still has to map
    JSON kind/status to DB enum (see :func:`_resolve_status_and_kind`).
    """
    run_fields: dict[str, Any] = {}
    progress_fields: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    for k, v in payload.items():
        if k.startswith("_"):
            # Internal markers like _filename added by the UI loader;
            # skip on the backfill side.
            continue
        if k in _RUNS_COLUMN_FIELDS:
            run_fields[k] = v
        elif k in _PROGRESS_COLUMN_FIELDS:
            progress_fields[k] = v
        else:
            extra[k] = v
    return run_fields, progress_fields, extra


def _existing_run_status(
    conn, run_id: str,
) -> Optional[str]:
    """Return the DB-side ``status`` for ``run_id``, or ``None`` if
    no row exists."""
    row = conn.execute(
        "SELECT status FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    return row["status"] if row is not None else None


_TERMINAL_STATUSES = ("completed", "failed", "killed")


def _upsert_run_row(
    conn,
    run_id: str,
    *,
    db_kind: str,
    db_status: str,
    started_at: str,
    ended_at: Optional[str],
    git_commit: str,
    config_json: str,
    parent_run_id: Optional[str],
    label: Optional[str],
    notes: Optional[str],
) -> str:
    """Insert or update one row in ``runs``. Returns one of
    ``"inserted"`` / ``"updated"`` / ``"skipped_terminal"``.

    The terminal-skip check is the central idempotency guarantee: an
    accidental re-run of the backfill against a DB whose master has
    since written newer rows MUST NOT clobber the master's authoritative
    finalization with a stale JSON.
    """
    existing = _existing_run_status(conn, run_id)
    if existing is None:
        # Brand new row.
        runs_db.insert_run(
            conn,
            Run(
                run_id=run_id,
                kind=db_kind,
                status=db_status,
                started_at=started_at,
                ended_at=ended_at,
                git_commit=git_commit,
                config_json=config_json,
                parent_run_id=parent_run_id,
                label=label,
                notes=notes,
            ),
        )
        return "inserted"
    if existing in _TERMINAL_STATUSES:
        # DB already has a terminal status. Per the idempotency
        # contract, leave it alone — the producer's ``finish_run`` is
        # authoritative over the JSON's possibly-out-of-date status.
        return "skipped_terminal"
    # Existing row but non-terminal: advance status / fill in
    # ended_at / notes when the JSON has them. We DON'T touch
    # started_at / kind / git_commit / config_json (the row's primary
    # identifying fields); a producer wrote those at start_run time
    # and they should stay anchored.
    with runs_db.transaction(conn):
        conn.execute(
            """
            UPDATE runs
            SET status        = ?,
                ended_at      = COALESCE(?, ended_at),
                notes         = COALESCE(?, notes),
                label         = COALESCE(?, label),
                parent_run_id = COALESCE(?, parent_run_id)
            WHERE run_id = ?
            """,
            (db_status, ended_at, notes, label, parent_run_id, run_id),
        )
    return "updated"


def _backfill_one_aggregate(
    conn,
    payload: dict[str, Any],
    json_path: Path,
    *,
    progress_dir: Path,
    stale_after_hours: float,
    now: float,
    summary: BackfillSummary,
) -> Optional[str]:
    """Backfill the aggregate (parent) row for one JSON file. Returns
    the run_id on success, or ``None`` if the JSON wasn't shaped like
    a run record (no run_id, no kind, ...). Mutates ``summary`` in
    place."""
    run_id = payload.get("run_id") or json_path.stem
    raw_kind = payload.get("kind")
    db_kind = _KIND_JSON_TO_DB.get(raw_kind) if raw_kind else None

    if not run_id or not db_kind:
        # Some legacy JSONs (e.g. ``baseline.json`` from very early
        # one-off runs) carry kind=data_gen / kind=eval but no run_id.
        # We default run_id to the filename stem above. If kind itself
        # is missing or unrecognized we can't synthesize meaningfully.
        if not db_kind:
            summary.errors.append(
                f"{json_path.name}: unknown or missing 'kind' "
                f"(raw={raw_kind!r}); skipping"
            )
            summary.files_skipped += 1
            return None

    started_at = payload.get("started_at") or _now_iso()
    git_commit = payload.get("git_commit") or "unknown"

    # Build config_json from the payload itself when no other source
    # exists. The JSON IS our config-of-record for backfilled rows;
    # the producer-side dual-write would have a richer dict, but for
    # historical rows the JSON is all we have.
    config_json = json.dumps(
        {"_source": "backfill_from_json", "filename": json_path.name},
        sort_keys=True,
    )

    db_status, db_ended_at, extra_overrides = _resolve_status_and_kind(
        payload, json_path,
        progress_dir=progress_dir,
        stale_after_hours=stale_after_hours,
        now=now,
    )

    notes = payload.get("notes") or None
    parent_run_id = payload.get("cycle_id") or payload.get("parent_run_id")
    label = payload.get("label")

    # Avoid violating the FK on ``runs.parent_run_id -> runs.run_id``:
    # if the JSON points at a parent we haven't seen yet (or never
    # will), insert with NULL instead. The UI's stop endpoint reads
    # ``cycle_id`` straight from the JSON for cycle-targeting, so this
    # doesn't break stop semantics; it just keeps the FK clean.
    if parent_run_id and _existing_run_status(conn, parent_run_id) is None:
        # Stash the original cycle_id so a future backfill (or the UI)
        # can still recover it. Not currently used by the UI's stop
        # endpoint (which re-reads JSON each time) but the data point
        # is cheap.
        extra_overrides.setdefault("orphan_cycle_id", parent_run_id)
        parent_run_id = None

    action = _upsert_run_row(
        conn, run_id,
        db_kind=db_kind,
        db_status=db_status,
        started_at=started_at,
        ended_at=db_ended_at,
        git_commit=git_commit,
        config_json=config_json,
        parent_run_id=parent_run_id,
        label=label,
        notes=notes,
    )
    if action == "inserted":
        summary.runs_inserted += 1
    elif action == "updated":
        summary.runs_updated += 1
    else:
        summary.runs_skipped_terminal += 1
    if extra_overrides.get("backfill_note", "").startswith(
        "stale-running heuristic"
    ):
        summary.stale_running_marked_terminal += 1

    # Build the aggregate progress row from the payload's counter
    # fields, threading anything left over (machines, train_losses,
    # ...) into extra_json. Skip if the run_row insert was a
    # terminal-skip — we don't want to overwrite an authoritative
    # progress row with stale JSON data either.
    if action != "skipped_terminal":
        _, progress_fields, extra = _split_payload(payload)
        extra.update(extra_overrides)
        _upsert_progress_row(
            conn, run_id, shard_label=None,
            progress_fields=progress_fields,
            extra=extra,
            summary=summary,
        )

    # Register the JSON as an artifact regardless of terminal-skip;
    # the artifacts table is a best-effort index of "where on disk
    # are this run's byproducts" and is fine to refresh.
    try:
        size = json_path.stat().st_size
    except OSError:
        size = None
    runs_db.upsert_artifact(
        conn,
        Artifact(
            run_id=run_id,
            artifact_type="progress_json",
            path=str(json_path),
            bytes=size,
        ),
    )
    summary.artifacts_registered += 1
    return run_id


def _upsert_progress_row(
    conn,
    run_id: str,
    *,
    shard_label: Optional[str],
    progress_fields: dict[str, Any],
    extra: dict[str, Any],
    summary: BackfillSummary,
) -> None:
    """Upsert the ``run_progress`` row for ``(run_id, shard_label)``.

    Empty progress + empty extra still writes a row — this is the
    "we know this run exists; counters are zero" placeholder. The
    cost is a single row per run, well under any reasonable
    concern."""
    extra_json = json.dumps(extra, sort_keys=True, default=str) if extra else None
    update = ProgressUpdate(
        run_id=run_id,
        shard_label=shard_label,
        n_games_done=progress_fields.get("n_games_done"),
        n_games_total=progress_fields.get("n_games_total"),
        elapsed_seconds=progress_fields.get("elapsed_seconds"),
        crashed=progress_fields.get("crashed"),
        timed_out=progress_fields.get("timed_out"),
        wins_new=progress_fields.get("wins_new"),
        wins_old=progress_fields.get("wins_old"),
        draws=progress_fields.get("draws"),
        extra_json=extra_json,
    )
    runs_db.upsert_progress(conn, update)
    if shard_label is None:
        summary.progress_rows_upserted += 1
    else:
        summary.shard_rows_upserted += 1


def _ensure_parent_run_for_orphan_shard(
    conn,
    parent_run_id: str,
    shard_payload: dict[str, Any],
    json_path: Path,
    *,
    summary: BackfillSummary,
) -> None:
    """A per-shard JSON exists but no aggregate JSON did. Synthesize
    a minimal parent ``runs`` row so the shard's foreign key has
    somewhere to land. The shard's payload usually carries enough
    metadata (``kind`` / ``started_at``) to derive a sensible parent
    row; if it doesn't, we fall back to placeholders."""
    if _existing_run_status(conn, parent_run_id) is not None:
        return  # parent already there from an earlier file in the loop
    raw_kind = shard_payload.get("kind") or "self_play"
    db_kind = _KIND_JSON_TO_DB.get(raw_kind, "self_play")
    runs_db.insert_run(
        conn,
        Run(
            run_id=parent_run_id,
            kind=db_kind,
            status="killed",
            started_at=shard_payload.get("started_at") or _now_iso(),
            ended_at=shard_payload.get("ended_at") or _file_mtime_iso(json_path),
            git_commit=shard_payload.get("git_commit") or "unknown",
            config_json=json.dumps(
                {"_source": "backfill_orphan_shard_synthesis"},
                sort_keys=True,
            ),
            parent_run_id=None,
            label=None,
            notes=(
                f"synthesized parent for orphan shard "
                f"{shard_payload.get('run_id') or json_path.name}"
            ),
        ),
    )
    summary.runs_inserted += 1


def backfill_progress_dir(
    progress_dir: Path,
    db_path: Path,
    *,
    stale_after_hours: float = DEFAULT_STALE_AFTER_HOURS,
    now: Optional[float] = None,
) -> BackfillSummary:
    """Walk ``progress_dir`` and idempotently upsert every run record
    into ``db_path``. Creates the DB if missing.

    ``now`` is the wall-clock time used by the stale-running
    heuristic; defaults to ``time.time()``. Tests pass a fixed value
    so the heuristic is deterministic.
    """
    progress_dir = Path(progress_dir)
    db_path = Path(db_path)
    if now is None:
        now = time.time()
    summary = BackfillSummary()

    if not progress_dir.is_dir():
        summary.errors.append(
            f"progress_dir does not exist: {progress_dir}"
        )
        return summary

    aggregate_payloads: list[tuple[Path, dict[str, Any]]] = []
    shard_payloads: list[tuple[Path, dict[str, Any], str, str]] = []

    for path in sorted(progress_dir.glob("*.json")):
        name = path.name
        if _is_excluded_filename(name):
            summary.files_skipped += 1
            continue
        payload = _read_json(path)
        if payload is None:
            summary.files_unparseable += 1
            continue
        shard = _shard_match(name)
        if shard is not None:
            stem, label = shard
            shard_payloads.append((path, payload, stem, label))
        else:
            aggregate_payloads.append((path, payload))

    conn = runs_db.connect(db_path)
    try:
        # Aggregate first so per-shard rows can rely on the parent
        # being inserted (foreign key on run_progress.run_id ->
        # runs.run_id).
        seen_run_ids: set[str] = set()
        for json_path, payload in aggregate_payloads:
            try:
                rid = _backfill_one_aggregate(
                    conn, payload, json_path,
                    progress_dir=progress_dir,
                    stale_after_hours=stale_after_hours,
                    now=now,
                    summary=summary,
                )
                if rid is not None:
                    seen_run_ids.add(rid)
            except Exception as exc:  # noqa: BLE001
                summary.errors.append(
                    f"{json_path.name}: aggregate failed: {exc}"
                )

        for json_path, payload, parent_run_id, shard_label in shard_payloads:
            try:
                if parent_run_id not in seen_run_ids:
                    _ensure_parent_run_for_orphan_shard(
                        conn, parent_run_id, payload, json_path,
                        summary=summary,
                    )
                    seen_run_ids.add(parent_run_id)
                _, progress_fields, extra = _split_payload(payload)
                _upsert_progress_row(
                    conn, parent_run_id,
                    shard_label=shard_label,
                    progress_fields=progress_fields,
                    extra=extra,
                    summary=summary,
                )
                # Register the per-shard JSON as an artifact too.
                try:
                    size = json_path.stat().st_size
                except OSError:
                    size = None
                runs_db.upsert_artifact(
                    conn,
                    Artifact(
                        run_id=parent_run_id,
                        artifact_type="shard_progress_json",
                        path=str(json_path),
                        bytes=size,
                    ),
                )
                summary.artifacts_registered += 1
            except Exception as exc:  # noqa: BLE001
                summary.errors.append(
                    f"{json_path.name}: shard failed: {exc}"
                )
    finally:
        conn.close()

    return summary


def iter_progress_json_files(progress_dir: Path) -> Iterable[Path]:
    """Iterate the files this backfill considers — used by tests
    asserting that exclusion rules cover the expected edge cases.

    Matches every ``*.json`` directly under ``progress_dir`` that
    isn't on the explicit exclusion list. Per-shard files ARE included
    here; the caller separates them via :func:`_shard_match`.
    """
    if not progress_dir.is_dir():
        return []
    return [
        p for p in sorted(progress_dir.glob("*.json"))
        if not _is_excluded_filename(p.name)
    ]


__all__ = [
    "BackfillSummary",
    "DEFAULT_STALE_AFTER_HOURS",
    "backfill_progress_dir",
    "iter_progress_json_files",
]
