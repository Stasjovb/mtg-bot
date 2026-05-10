"""Flask app showing live progress of NN training runs.

Phase 2 of the runs-DB rollout: this UI now reads run records from
the SQLite ``runs.db`` as the single source of truth. Producer-side
JSON writes are still authoritative on disk (``Phase 1 dual-write``
invariant — see ``CLAUDE.md`` "Run database"); we honor that by
running an idempotent backfill from ``progress_dir/*.json`` into the
DB at the top of each ``/api/runs`` request. Subcommands that don't
yet dual-write (``iterate`` / ``train`` / ``shard`` / ``capture`` /
``bench``) thus still surface in the UI without manual ops steps —
their JSONs are folded into the DB on the next request.

DB query shape per endpoint:

- ``/api/runs``: ``SELECT * FROM runs ORDER BY started_at DESC``,
  LEFT JOIN with the aggregate (``shard_label IS NULL``) row from
  ``run_progress``. The aggregate row's ``extra_json`` is fanned out
  to the top level so the front-end's JSON-shape renderer (machines /
  win_rate / opponent_label / train_losses / ...) reads naturally.
- ``/api/runs/<run_id>``: the full DB record (run row + all progress
  rows + last 100 events + artifacts), with the aggregate progress
  row's columns + extra_json fanned to the top level. Per-shard
  progress rows surface under ``_db_progress_per_shard``.
- ``/api/runs/recent``: last 20 (configurable) completed runs across
  all kinds with summary stats from the aggregate ``run_progress``
  row.

extra_json fan-out:

The DB schema only carries the structured counters (``n_games_done``,
``wins_new``, ``elapsed_seconds``, ...). Everything else the UI
front-end needs — training loss arrays, per-machine summaries, eval
metadata, replay paths — flows through ``run_progress.extra_json``
(JSON-encoded blob). On the read path we ``json.loads`` the column
and ``setdefault`` each top-level key onto the run dict so the
existing front-end JS keeps working untouched.

Connection lifecycle: each request opens its own short-lived
``sqlite3.Connection`` via :func:`mtg_bot.cli.runs.db.connect`. WAL
mode (set on connect) lets these reads run concurrently with the
producer's writes (and with the per-request backfill's writes,
which serialize through SQLite's own per-file lock). Connections
are cheap (~hundreds of microseconds) so we don't pool them.

Write surface: ``POST /api/runs/<run_id>/stop`` drops a
``.STOP_<run_id>`` sentinel file in the progress directory — long-
running producers (iterate cycle, self-play pool, eval pool, queue
server) check for the sentinel at stage boundaries and exit cleanly
when they see it. Cycle-vs-single-run targeting comes from
``runs.parent_run_id`` (DB) when set, else from a fresh-read of
the JSON ``cycle_id`` field as a fallback for runs not yet
backfilled.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional

from flask import Flask, abort, jsonify, render_template, request

from mtg_bot.cli.runs import backfill as runs_backfill, db as runs_db
from mtg_bot.training.stop_signal import (
    sentinel_path, stop_requested, write_stop,
)


# ---- DB <-> UI kind translation -------------------------------------------

# The DB schema's ``kind`` enum (see ``cli.runs.db.SCHEMA_SQL``) uses
# canonical names; the UI front-end (the inline JS in index.html)
# discriminates cards on JSON-shape ``kind`` strings. The two diverge
# only on self-play: the DB calls it ``self_play``, the UI calls it
# ``data_gen`` (for historical reasons — the JSON predates the DB).
# Map DB->UI on the read path so the renderer doesn't need to know
# about the DB enum.
_DB_TO_UI_KIND = {"self_play": "data_gen"}

# We also re-export ``cycle`` as the iterate-card discriminator so
# the rendered cycle row keeps the JSON-era ``kind=cycle`` literal.
_DB_KIND_TO_UI = {
    "self_play": "data_gen",
    "iterate": "cycle",
}


def _ui_kind_from_db(db_kind: Optional[str]) -> Optional[str]:
    """Translate the canonical DB enum to the UI's JSON-shape kind.
    Unknown / None passthrough; ``self_play`` -> ``data_gen``;
    ``iterate`` -> ``cycle``."""
    if db_kind is None:
        return None
    return _DB_KIND_TO_UI.get(db_kind, db_kind)


# ---- Backfill orchestration ----------------------------------------------

# The backfill runs at the top of each /api/runs request. We guard it
# with a per-process lock so a burst of polls doesn't spawn N concurrent
# backfills that all fight over SQLite's writer slot. The lock is
# briefly held; the backfill itself is bounded by the JSON dir size
# (currently <300 files, ~50ms wall time on the master).
_BACKFILL_LOCK = threading.Lock()


def _ensure_backfill(progress_dir: Path) -> None:
    """Run a fresh backfill from ``progress_dir`` into ``runs.db``.

    Idempotent (see ``runs_backfill.backfill_progress_dir``). Catches
    every exception so a backfill failure can never 500 the listing
    endpoint — the worst case is the UI shows whatever the DB had at
    the previous backfill.
    """
    db_path = progress_dir / "runs.db"
    with _BACKFILL_LOCK:
        try:
            runs_backfill.backfill_progress_dir(progress_dir, db_path)
        except Exception:  # noqa: BLE001
            # Logging is intentionally best-effort; this path runs on
            # every request and a chatty stderr would spam logs.
            pass


# ---- DB read helpers ------------------------------------------------------


def _open_conn(progress_dir: Path) -> Optional[sqlite3.Connection]:
    """Open a fresh read connection to the runs DB colocated with
    ``progress_dir``. Returns ``None`` if the DB file doesn't exist
    yet (a fresh checkout that hasn't been backfilled and has no
    JSONs to backfill from)."""
    db_path = progress_dir / "runs.db"
    if not db_path.is_file():
        return None
    try:
        return runs_db.connect(db_path)
    except sqlite3.Error:
        return None


def _row_to_ui_dict(
    run_row: dict[str, Any],
    progress_row: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """Project a ``runs`` + aggregate ``run_progress`` pair into the
    JSON-shape dict the front-end expects.

    Strategy: copy the row fields verbatim (renaming kind -> UI kind),
    surface the aggregate counter columns, then ``json.loads`` the
    aggregate's ``extra_json`` and ``setdefault`` each key onto the
    output. ``setdefault`` (not overwrite) means a column-side value
    always wins over an extra_json value of the same key — the
    structured counters are authoritative when they're set.

    Edge case: if ``extra_json`` is malformed, the listing must still
    surface the run with its core fields. We swallow ``JSONDecodeError``
    silently — a future producer bug shouldn't break the UI.
    """
    ui: dict[str, Any] = {
        "run_id": run_row["run_id"],
        "kind": _ui_kind_from_db(run_row.get("kind")),
        "status": run_row.get("status"),
        "started_at": run_row.get("started_at"),
        "ended_at": run_row.get("ended_at"),
        "git_commit": run_row.get("git_commit"),
        "label": run_row.get("label"),
        "notes": run_row.get("notes"),
        "parent_run_id": run_row.get("parent_run_id"),
        "_db_kind": run_row.get("kind"),
    }
    if progress_row is not None:
        for key in (
            "n_games_done", "n_games_total", "elapsed_seconds",
            "crashed", "timed_out", "wins_new", "wins_old", "draws",
        ):
            val = progress_row.get(key)
            if val is not None:
                ui[key] = val
        # Fan out extra_json keys onto the top-level dict. Setdefault
        # so the structured counters above always win.
        extra_raw = progress_row.get("extra_json")
        if extra_raw:
            try:
                extra = json.loads(extra_raw)
                if isinstance(extra, dict):
                    for k, v in extra.items():
                        if k.startswith("_"):
                            # Internal markers (e.g. ``original_status``,
                            # ``backfill_note``) flow through under their
                            # own key so the UI can surface them when it
                            # wants without overwriting structured fields.
                            ui[k] = v
                        else:
                            ui.setdefault(k, v)
            except (json.JSONDecodeError, TypeError):
                pass
    # If the backfill mapped a JSON ``stopped`` to DB ``killed`` and
    # stashed ``original_status`` in extra_json, prefer the original
    # for UI display so the user sees ``stopped`` (their nomenclature)
    # rather than ``killed`` (DB's).
    if isinstance(progress_row, dict) and progress_row.get("extra_json"):
        try:
            extra = json.loads(progress_row["extra_json"])
            if (
                isinstance(extra, dict)
                and "original_status" in extra
            ):
                ui["status"] = extra["original_status"]
        except (json.JSONDecodeError, TypeError):
            pass
    return ui


def _list_runs(progress_dir: Path) -> list[dict[str, Any]]:
    """All runs visible to the UI, newest-first by ``started_at``.

    DB-first: every run surfaces here lives in ``runs.db``. The
    backfill at the top of the request folds new JSONs into the DB
    so JSON-only producers (today: iterate / train / shard / capture /
    bench) still appear without delay.

    Per-shard runs (``shard_label`` populated) are NOT listed here —
    the aggregate (``shard_label IS NULL``) row is the card; per-shard
    rows surface inside the detail endpoint as sub-cards.
    """
    _ensure_backfill(progress_dir)
    conn = _open_conn(progress_dir)
    if conn is None:
        return []
    try:
        rows = conn.execute(
            """
            SELECT r.*, p.n_games_done, p.n_games_total,
                   p.elapsed_seconds, p.crashed, p.timed_out,
                   p.wins_new, p.wins_old, p.draws, p.extra_json
            FROM runs r
            LEFT JOIN run_progress p
              ON p.run_id = r.run_id AND p.shard_label IS NULL
            ORDER BY r.started_at DESC
            """,
        ).fetchall()
    finally:
        conn.close()

    out: list[dict[str, Any]] = []
    for row in rows:
        run_dict = {k: row[k] for k in row.keys() if not k.startswith(
            ("n_games_", "elapsed_seconds", "crashed", "timed_out",
             "wins_", "draws", "extra_json"),
        )}
        progress_dict = {
            "n_games_done": row["n_games_done"],
            "n_games_total": row["n_games_total"],
            "elapsed_seconds": row["elapsed_seconds"],
            "crashed": row["crashed"],
            "timed_out": row["timed_out"],
            "wins_new": row["wins_new"],
            "wins_old": row["wins_old"],
            "draws": row["draws"],
            "extra_json": row["extra_json"],
        }
        out.append(_row_to_ui_dict(run_dict, progress_dict))
    return out


def _get_run_detail(
    progress_dir: Path, run_id: str,
) -> Optional[dict[str, Any]]:
    """Per-run detail: DB row + aggregate progress + per-shard rows
    + last 100 events + artifacts. Returns ``None`` if the run is
    unknown to the DB. The backfill runs first so a JSON-only run
    that just landed surfaces immediately."""
    _ensure_backfill(progress_dir)
    conn = _open_conn(progress_dir)
    if conn is None:
        return None
    try:
        record = runs_db.get_run(conn, run_id)
    finally:
        conn.close()
    if record is None:
        return None

    run_row = record["run"]
    agg = None
    per_shard: list[dict[str, Any]] = []
    for p in record.get("progress", []):
        if p.get("shard_label") is None:
            agg = p
        else:
            per_shard.append(p)
    ui = _row_to_ui_dict(run_row, agg)
    ui["_db_progress_per_shard"] = per_shard
    ui["_db_events"] = record.get("events", [])
    ui["_db_artifacts"] = record.get("artifacts", [])

    # Synthesize a "machines" array from per_shard rows for the front-
    # end's per-machine sub-card renderer. Eval / data_gen JSONs used
    # to carry this directly; with the DB-first path we derive it from
    # the structured per_shard records.
    if per_shard and "machines" not in ui:
        ui["machines"] = _per_shard_to_machines(per_shard)
    return ui


def _per_shard_to_machines(
    per_shard: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert ``run_progress`` per-shard rows into the
    ``machines = [{label, n_games_done, n_workers, status, crashed}, ...]``
    array the front-end expects.

    ``status``, ``n_workers``, ``per_game_seconds_avg``, etc. live in
    the per-shard row's ``extra_json`` (the structured columns only
    cover counters). We fan those out so the renderer's
    ``machines[i].n_workers`` lookup keeps working.
    """
    machines: list[dict[str, Any]] = []
    for row in per_shard:
        m: dict[str, Any] = {
            "label": row.get("shard_label"),
            "n_games_done": row.get("n_games_done"),
            "crashed": row.get("crashed"),
        }
        extra_raw = row.get("extra_json")
        if extra_raw:
            try:
                extra = json.loads(extra_raw)
                if isinstance(extra, dict):
                    for k, v in extra.items():
                        if k.startswith("_"):
                            continue
                        m.setdefault(k, v)
            except (json.JSONDecodeError, TypeError):
                pass
        machines.append(m)
    return machines


def _list_recent_runs(
    progress_dir: Path, limit: int = 20,
) -> list[dict[str, Any]]:
    """Last N completed runs across all kinds with summary stats. The
    ``status='completed'`` filter mirrors the brief's "older pane"
    semantics — we surface the user's terminal history and exclude
    in-flight rows.

    Uses a single LEFT JOIN against the aggregate progress row so the
    response shape carries the headline counters without an N+1 trip.
    """
    _ensure_backfill(progress_dir)
    conn = _open_conn(progress_dir)
    if conn is None:
        return []
    try:
        rows = conn.execute(
            """
            SELECT r.*,
                   p.n_games_done   AS p_n_games_done,
                   p.n_games_total  AS p_n_games_total,
                   p.elapsed_seconds AS p_elapsed_seconds,
                   p.wins_new       AS p_wins_new,
                   p.wins_old       AS p_wins_old,
                   p.draws          AS p_draws,
                   p.crashed        AS p_crashed,
                   p.timed_out      AS p_timed_out,
                   p.extra_json     AS p_extra_json
            FROM runs r
            LEFT JOIN run_progress p
              ON p.run_id = r.run_id AND p.shard_label IS NULL
            WHERE r.status = 'completed'
            ORDER BY r.started_at DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    finally:
        conn.close()
    out: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        out.append({
            "run_id": d["run_id"],
            "kind": _ui_kind_from_db(d.get("kind")),
            "status": d.get("status"),
            "started_at": d.get("started_at"),
            "ended_at": d.get("ended_at"),
            "git_commit": d.get("git_commit"),
            "label": d.get("label"),
            "n_games_done": d.get("p_n_games_done"),
            "n_games_total": d.get("p_n_games_total"),
            "elapsed_seconds": d.get("p_elapsed_seconds"),
            "wins_new": d.get("p_wins_new"),
            "wins_old": d.get("p_wins_old"),
            "draws": d.get("p_draws"),
            "crashed": d.get("p_crashed"),
            "timed_out": d.get("p_timed_out"),
        })
    return out


# ---- Stop-signal helpers -------------------------------------------------


def _read_json_cycle_id(progress_dir: Path, run_id: str) -> Optional[str]:
    """Best-effort lookup of the legacy ``cycle_id`` JSON field.

    The DB row's ``parent_run_id`` is the canonical pointer post-backfill,
    but for a producer that's running RIGHT NOW (and hasn't been re-
    backfilled), the JSON is the freshest source. We try the JSON
    first when stopping a child stage so cycle-stop semantics fire
    immediately, even before the next request-side backfill pass.
    """
    json_path = progress_dir / f"{run_id}.json"
    if not json_path.is_file():
        return None
    try:
        with json_path.open("r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    cid = data.get("cycle_id")
    return cid if isinstance(cid, str) else None


# ---- Flask app factory ----------------------------------------------------


def create_app(progress_dir: Path) -> Flask:
    """Build the Flask app. ``progress_dir`` is the directory that
    holds both the per-run progress JSON files (legacy + producer
    dual-write source) AND the ``runs.db`` SQLite file (Phase 2 sole
    source of truth read by the UI). The directory does NOT have to
    exist at app-creation time — every endpoint reads it lazily on
    each request, so a UI started before the first training run still
    works."""
    progress_dir = Path(progress_dir).resolve()

    template_dir = Path(__file__).parent / "templates"
    static_dir = Path(__file__).parent / "static"
    app = Flask(
        __name__,
        template_folder=str(template_dir),
        static_folder=str(static_dir),
    )
    app.config["PROGRESS_DIR"] = progress_dir

    @app.route("/")
    def index():  # noqa: D401 - Flask view
        return render_template("index.html")

    @app.route("/api/runs")
    def api_runs():
        runs = _list_runs(app.config["PROGRESS_DIR"])
        return jsonify({"runs": runs})

    @app.route("/api/runs/recent")
    def api_runs_recent():
        """Last N completed runs across all kinds. Light-weight cross-
        run summary panel."""
        limit_raw = request.args.get("limit", "20")
        try:
            limit = max(1, min(int(limit_raw), 200))
        except (TypeError, ValueError):
            limit = 20
        runs = _list_recent_runs(app.config["PROGRESS_DIR"], limit=limit)
        return jsonify({"runs": runs, "limit": limit})

    @app.route("/api/runs/<run_id>")
    def api_run(run_id: str):
        run = _get_run_detail(app.config["PROGRESS_DIR"], run_id)
        if run is None:
            abort(404)
        return jsonify(run)

    @app.route("/api/runs/<run_id>/replays")
    def api_run_replays(run_id: str):
        """List captured replay files for a given run.

        ``replays_dir`` lives in the producer's progress JSON (and
        flows through ``run_progress.extra_json`` after the backfill).
        We read it from whichever the run-detail dict surfaces.
        """
        run = _get_run_detail(app.config["PROGRESS_DIR"], run_id)
        if run is None:
            abort(404)
        replays_dir_str = run.get("replays_dir")
        if not replays_dir_str:
            return jsonify({
                "replays_dir": None,
                "replays": [],
                "count": 0,
                "note": "this run did not capture replays",
            })
        replays_dir = Path(replays_dir_str)
        if not replays_dir.is_dir():
            return jsonify({
                "replays_dir": str(replays_dir),
                "replays": [],
                "count": 0,
                "note": "replays_dir does not exist (yet?)",
            })
        files = sorted(p.name for p in replays_dir.glob("*.json.gz"))
        subdir = replays_dir.name
        return jsonify({
            "replays_dir": str(replays_dir),
            "replays": [
                {"filename": name, "subpath": f"{subdir}/{name}"}
                for name in files
            ],
            "count": len(files),
        })

    @app.route("/api/runs/<run_id>/stop", methods=["POST"])
    def api_run_stop(run_id: str):
        """Request a stop for ``run_id``.

        Drops a sentinel file ``.STOP_<target_id>`` in the progress
        directory. Producers (iterate cycle / self-play / eval / queue
        server) poll for that sentinel at stage boundaries and exit
        cleanly, finalizing their progress JSON with ``status="stopped"``
        (which the next backfill maps to DB ``killed``).

        Cycle-vs-single-run targeting: read in priority order
          1. Live JSON ``cycle_id`` (freshest if a producer just
             updated its status file but the DB hasn't re-synced yet)
          2. DB ``runs.parent_run_id`` (canonical post-backfill)
        Otherwise the sentinel targets ``run_id`` itself.

        Idempotent — calling twice does NOT error; the second call
        refreshes the sentinel's timestamp + reason. Body is an
        optional JSON ``{"reason": str}`` for log/audit metadata.
        """
        progress_dir: Path = app.config["PROGRESS_DIR"]
        run = _get_run_detail(progress_dir, run_id)
        if run is None:
            abort(404)
        body = request.get_json(silent=True) or {}
        reason = body.get("reason") if isinstance(body, dict) else None
        cycle_id = (
            _read_json_cycle_id(progress_dir, run_id)
            or run.get("parent_run_id")
        )
        target_id = cycle_id if cycle_id else run_id
        path = write_stop(progress_dir, target_id, reason=reason)
        return jsonify({
            "ok": True,
            "run_id": run_id,
            "stopped_target": target_id,
            "is_cycle_stop": bool(cycle_id),
            "sentinel_path": str(path),
        })

    @app.route("/api/runs/<run_id>/stop", methods=["GET"])
    def api_run_stop_status(run_id: str):
        """Diagnostic: report whether a stop has been requested for
        ``run_id`` (or its parent cycle, if any)."""
        progress_dir: Path = app.config["PROGRESS_DIR"]
        run = _get_run_detail(progress_dir, run_id)
        if run is None:
            abort(404)
        cycle_id = (
            _read_json_cycle_id(progress_dir, run_id)
            or run.get("parent_run_id")
        )
        own = sentinel_path(progress_dir, run_id).is_file()
        cycle = bool(cycle_id) and sentinel_path(
            progress_dir, cycle_id,
        ).is_file()
        return jsonify({
            "run_id": run_id,
            "cycle_id": cycle_id,
            "stop_requested": own or cycle or stop_requested(
                progress_dir, run_id, cycle_id=cycle_id,
            ),
            "own_sentinel": own,
            "cycle_sentinel": cycle,
        })

    return app
