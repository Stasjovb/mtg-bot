"""Flask app showing live progress of NN training runs.

Phase 3 of the runs-DB rollout: this UI reads run records from
the SQLite ``runs.db`` as the single source of truth, with NO
JSON-side backfill. Every producer (``iterate``, ``train``,
``shard``, standalone ``eval``) now pushes its lifecycle directly
to the DB via ``mtg_bot.cli.runs.client``; the JSON files that
remain on disk are historical artifacts and ignored by this UI.

Stale ``running`` rows (producer died before ``finish_run``) are
demoted by the periodic janitor inside ``mtg_bot serve`` — see
``mtg_bot.cli.runs.janitor``. The previous request-time backfill
no longer fires.

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
producer's writes. Connections are cheap (~hundreds of microseconds)
so we don't pool them.

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
from pathlib import Path
from typing import Any, Optional

from flask import Flask, abort, jsonify, render_template, request

from mtg_bot.cli.runs import db as runs_db
from mtg_bot.training.gate import EVAL_GATE_THRESHOLD
from mtg_bot.training.stop_signal import (
    sentinel_path, stop_requested, write_stop,
)
from mtg_bot.training_ui.launcher import (
    build_iterate_schema, find_spawn_for_run, kill_process_tree,
    spawn_iterate,
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
    All producers push directly to the DB via
    ``mtg_bot.cli.runs.client``; this read path is pure DB.

    Per-shard runs (``shard_label`` populated) are NOT listed here —
    the aggregate (``shard_label IS NULL``) row is the card; per-shard
    rows surface inside the detail endpoint as sub-cards.
    """
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
    unknown to the DB."""
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


def _force_kill_matched_spawn(
    progress_dir: Path,
    target_run_id: str,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Look up the spawn record that plausibly belongs to
    ``target_run_id`` via timestamp proximity (see
    :func:`mtg_bot.training_ui.launcher.find_spawn_for_run`) and
    OS-kill the process tree. Returns a dict of fields to merge into
    the force_kill response so the frontend can surface what happened:

    - ``os_kill_attempted`` (bool)
    - ``os_kill_ok`` (bool)
    - ``os_killed_pid`` (int or None)
    - ``os_kill_errors`` (list[str])
    - ``matched_launch_id`` (str or None) — for log/audit trail

    Any failure (no matching spawn, kill error) is reported as
    data, NOT raised — the DB-write side of force_kill is the
    authoritative status; OS-kill is best-effort cleanup.
    """
    target_row = conn.execute(
        "SELECT started_at FROM runs WHERE run_id = ?",
        (target_run_id,),
    ).fetchone()
    target_started = (
        target_row["started_at"] if target_row is not None else None
    )
    match = find_spawn_for_run(
        progress_dir, run_id=target_run_id,
        run_started_at=target_started,
    )
    if match is None:
        return {
            "os_kill_attempted": False,
            "os_kill_ok": False,
            "os_killed_pid": None,
            "os_kill_errors": [],
            "matched_launch_id": None,
        }
    outcome = kill_process_tree(match["pid"])
    return {
        "os_kill_attempted": True,
        "os_kill_ok": outcome["ok"],
        "os_killed_pid": match["pid"],
        "os_kill_errors": outcome["errors"],
        "matched_launch_id": match.get("launch_id"),
    }


def create_app(
    progress_dir: Path,
    *,
    registry_root: Optional[Path] = None,
    deck_pool_dir: Optional[Path] = None,
    spawn_cwd: Optional[Path] = None,
) -> Flask:
    """Build the Flask app. ``progress_dir`` is the directory that
    holds both the per-run progress JSON files (legacy + producer
    dual-write source) AND the ``runs.db`` SQLite file (Phase 2 sole
    source of truth read by the UI). The directory does NOT have to
    exist at app-creation time — every endpoint reads it lazily on
    each request, so a UI started before the first training run still
    works.

    ``registry_root`` (optional) is the trained-weights registry root
    used by the launch-iterate form to populate the bootstrap-version
    dropdown. ``deck_pool_dir`` is the corresponding source for the
    deck-pool dropdown. When either is ``None``, the matching
    dropdown shows empty choices and the user can still type any
    string (which iterate itself validates at spawn time).

    ``spawn_cwd`` (optional) is the directory the launched iterate
    subprocess starts in. iterate's ``--registry-root``,
    ``--data-dir``, ``--progress-dir`` etc. all default to relative
    paths, so this must point at the directory where your
    ``trained_weights/`` / ``iterate_data/`` / ``training_progress/``
    live. When ``None``, the launcher falls back to its on-disk
    location (typically the worktree where ``launcher.py`` lives,
    which only works if all paths exist relative to that worktree —
    pass an explicit value when running the UI from a worktree
    against a main-checkout's data."""
    progress_dir = Path(progress_dir).resolve()
    if registry_root is not None:
        registry_root = Path(registry_root).resolve()
    if deck_pool_dir is not None:
        deck_pool_dir = Path(deck_pool_dir).resolve()
    if spawn_cwd is not None:
        spawn_cwd = Path(spawn_cwd).resolve()

    template_dir = Path(__file__).parent / "templates"
    static_dir = Path(__file__).parent / "static"
    app = Flask(
        __name__,
        template_folder=str(template_dir),
        static_folder=str(static_dir),
    )
    app.config["PROGRESS_DIR"] = progress_dir
    app.config["REGISTRY_ROOT"] = registry_root
    app.config["DECK_POOL_DIR"] = deck_pool_dir
    app.config["SPAWN_CWD"] = spawn_cwd

    @app.route("/")
    def index():  # noqa: D401 - Flask view
        # ``eval_gate_threshold`` is rendered into the inline JS as
        # the single source of truth for the gate-band overlay; see
        # ``mtg_bot.training.gate``. Updating that constant
        # automatically updates both the Python defaults (iterate,
        # watcher) AND the UI label and overlay.
        return render_template(
            "index.html",
            eval_gate_threshold=EVAL_GATE_THRESHOLD,
        )

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

    @app.route("/api/runs/<run_id>/force_kill", methods=["POST"])
    def api_run_force_kill(run_id: str):
        """Force-kill ``run_id`` immediately, bypassing the
        producer-drain handshake.

        Use this for ZOMBIE runs whose master is already dead — the
        clean ``/stop`` path waits for a producer to poll the sentinel
        and finalize its JSON, which a dead master will never do.
        Force-kill writes the terminal status directly to ``runs.db``:
        ``UPDATE runs SET status='killed', ended_at=NOW() WHERE
        run_id=? AND status='running'``.

        Process termination is OUT OF SCOPE for this endpoint — we
        do NOT signal / kill any OS process. (That needs a PID column
        on ``runs`` which is being added in a sibling slice.) The
        sentinel write below is cheap insurance against a straggler
        worker that's still alive: if one happens to be polling, it
        will see the sentinel and drop out cleanly even though the
        DB row already shows terminal.

        Cycle-vs-single-run targeting matches ``/stop``: if the run
        has a ``cycle_id`` (JSON-side, freshest) or a
        ``parent_run_id`` (DB-side, canonical post-backfill), the
        cycle is the actual target — child stages will inherit
        terminal status on the next backfill pass.

        Idempotent: if the row is already terminal (completed /
        failed / killed), the endpoint returns ``forced=false`` with
        the existing status and does NOT mutate the DB, the
        ``extra_json``, or the sentinel. The ``forced=true`` path
        also stashes ``original_status="force_killed"`` in the
        target's ``run_progress`` aggregate-row ``extra_json`` so
        the UI labels the row as ``force_killed`` (distinct from a
        clean ``stopped`` or the backfill heuristic's ``killed``).

        Request body is an optional JSON ``{"reason": str}`` —
        threaded into the sentinel (cheap audit trail).
        """
        progress_dir: Path = app.config["PROGRESS_DIR"]
        run = _get_run_detail(progress_dir, run_id)
        if run is None:
            abort(404)
        body = request.get_json(silent=True) or {}
        reason = body.get("reason") if isinstance(body, dict) else None

        # Cycle-vs-single targeting — same priority order as /stop.
        cycle_id = (
            _read_json_cycle_id(progress_dir, run_id)
            or run.get("parent_run_id")
        )
        target_id = cycle_id if cycle_id else run_id

        # Re-read the target row directly so the idempotency check sees
        # the canonical DB status (not the UI-translated ``original_status``
        # the JSON-side might shadow over ``killed`` etc.). If the user
        # clicked force-kill on a child run we want to look at the
        # cycle's DB status, not the child's.
        db_path = progress_dir / "runs.db"
        if not db_path.is_file():
            # Defensive: detail lookup above already exercises the
            # backfill which creates the DB, but if the file is missing
            # there's nothing to force-kill.
            abort(404)
        conn = runs_db.connect(db_path)
        try:
            target_row = conn.execute(
                "SELECT status FROM runs WHERE run_id = ?", (target_id,),
            ).fetchone()
            if target_row is None:
                # The cycle pointer dangled — shouldn't happen post-
                # backfill, but if it does, fall back to the clicked
                # run_id as the target so the user still gets feedback.
                target_id = run_id
                target_row = conn.execute(
                    "SELECT status FROM runs WHERE run_id = ?", (run_id,),
                ).fetchone()
            previous_status = (
                target_row["status"] if target_row is not None else None
            )
            if previous_status != "running":
                # Idempotent no-op for the DB-row update — but a
                # process spawned via the UI launch endpoint may
                # still be alive (e.g. the user clicked Force Kill
                # because the cycle row went terminal but the
                # subprocess didn't drain). Try the OS-kill anyway
                # and report what happened.
                kill_outcome = _force_kill_matched_spawn(
                    progress_dir, target_id, conn,
                )
                return jsonify({
                    "ok": True,
                    "run_id": run_id,
                    "stopped_target": target_id,
                    "is_cycle_stop": bool(cycle_id),
                    "forced": False,
                    "previous_status": previous_status,
                    "sentinel_path": None,
                    **kill_outcome,
                })

            # 1) Direct DB write — UPDATE status='killed', ended_at=NOW().
            #    Guarded by status='running' so a concurrent finalize
            #    can't be clobbered.
            ended = runs_db.now_iso()
            with runs_db.transaction(conn):
                conn.execute(
                    """
                    UPDATE runs
                    SET status = 'killed', ended_at = ?
                    WHERE run_id = ? AND status = 'running'
                    """,
                    (ended, target_id),
                )
                # 2) Stamp original_status="force_killed" on the
                #    aggregate run_progress row so the UI distinguishes
                #    this from a clean "stopped" or the stale-running
                #    backfill's "killed". We merge into existing
                #    extra_json rather than replace.
                agg = conn.execute(
                    """
                    SELECT extra_json FROM run_progress
                    WHERE run_id = ? AND shard_label IS NULL
                    """,
                    (target_id,),
                ).fetchone()
                if agg is not None:
                    extra_raw = agg["extra_json"]
                    try:
                        extra = (
                            json.loads(extra_raw)
                            if extra_raw else {}
                        )
                        if not isinstance(extra, dict):
                            extra = {}
                    except (json.JSONDecodeError, TypeError):
                        extra = {}
                    extra["original_status"] = "force_killed"
                    conn.execute(
                        """
                        UPDATE run_progress
                        SET extra_json = ?, updated_at = ?
                        WHERE run_id = ? AND shard_label IS NULL
                        """,
                        (json.dumps(extra), ended, target_id),
                    )
                else:
                    # No aggregate row yet — create one with just the
                    # original_status marker so the UI surfaces the
                    # distinct label. Other counter columns stay NULL.
                    conn.execute(
                        """
                        INSERT INTO run_progress(
                            run_id, shard_label, extra_json, updated_at
                        ) VALUES (?, NULL, ?, ?)
                        """,
                        (
                            target_id,
                            json.dumps({
                                "original_status": "force_killed",
                            }),
                            ended,
                        ),
                    )
            # 3) OS-kill any subprocess spawned by the UI launch
            #    endpoint that matches this run by spawned_at /
            #    started_at proximity. Must happen INSIDE the
            #    ``with runs_db.transaction(conn)`` block's outer
            #    ``try`` so we still get the launched.json read
            #    even after the DB write commits.
            kill_outcome = _force_kill_matched_spawn(
                progress_dir, target_id, conn,
            )
        finally:
            conn.close()

        # 4) Sentinel write — straggler insurance. A worker that's
        #    still alive AND polling will exit cleanly when it sees
        #    this. For true zombies (master dead), the sentinel is
        #    harmless on-disk noise that cleanup_orphans() reaps on
        #    the next iterate kickoff.
        path = write_stop(progress_dir, target_id, reason=reason)

        return jsonify({
            "ok": True,
            "run_id": run_id,
            "stopped_target": target_id,
            "is_cycle_stop": bool(cycle_id),
            "forced": True,
            "previous_status": previous_status,
            "sentinel_path": str(path),
            **kill_outcome,
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

    @app.route("/api/launch/iterate/schema")
    def api_launch_iterate_schema():
        """Return the schema describing every iterate CLI argument.

        Rebuilt per request so the bootstrap-version dropdown picks
        up newly-trained versions without a UI restart. The live
        ``EVAL_GATE_THRESHOLD`` and per-game-timeout defaults also
        flow through, but those rarely change.
        """
        schema = build_iterate_schema(
            registry_root=app.config.get("REGISTRY_ROOT"),
            deck_pool_dir=app.config.get("DECK_POOL_DIR"),
        )
        return jsonify({"schema": schema})

    @app.route("/api/launch/iterate", methods=["POST"])
    def api_launch_iterate():
        """Spawn ``mtg_bot.cli iterate`` as a detached subprocess.

        Body shape: ``{"args": {<flag_name>: <value>, ...}}``. Flags
        whose value matches the schema default are dropped at command-
        build time so the spawned command line stays minimal.

        Returns the spawned PID + the path to the console-log file
        the subprocess's combined stdout/stderr is teeing to. The
        process is fully decoupled from the Flask process — restart
        the UI freely; the iterate run keeps going. To stop it, use
        the existing ``POST /api/runs/<run_id>/stop`` endpoint once
        iterate has registered its cycle row in runs.db (typically
        within a few seconds of spawn).
        """
        body = request.get_json(silent=True) or {}
        submitted = body.get("args") if isinstance(body, dict) else None
        if not isinstance(submitted, dict):
            return jsonify({
                "ok": False,
                "error": "request body must be JSON with an 'args' object",
            }), 400
        try:
            schema = build_iterate_schema(
                registry_root=app.config.get("REGISTRY_ROOT"),
            )
            result = spawn_iterate(
                submitted, app.config["PROGRESS_DIR"],
                schema=schema,
                repo_root=app.config.get("SPAWN_CWD"),
            )
        except ValueError as e:
            # Schema-validation failure (missing required, unknown key,
            # bad choice, non-numeric int, ...). 422 = unprocessable
            # entity so the frontend can surface the message inline.
            return jsonify({"ok": False, "error": str(e)}), 422
        except OSError as e:
            # Subprocess spawn failed (e.g. python_executable missing).
            return jsonify({
                "ok": False,
                "error": f"spawn failed: {e}",
            }), 500
        return jsonify(result)

    return app
