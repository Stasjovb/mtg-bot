"""Flask app showing live progress of NN training runs.

Mostly-read viewer over the JSON files written by
``train_value_network(progress_path=...)``. The trainer is the
producer; this UI is one of (potentially) many consumers. The only
write surface is ``POST /api/runs/<run_id>/stop``, which drops a
``.STOP_<run_id>`` sentinel file in the progress directory — long-
running producers (iterate cycle, self-play pool, eval pool, queue
server) check for the sentinel at stage boundaries and exit
cleanly when they see it.

Each run is one ``<run_id>.json`` file in ``progress_dir`` (default
``training_progress/`` under the cwd of the process serving the UI).
The UI polls ``/api/runs`` every couple of seconds; the trainer
writes atomically via ``os.replace``, so concurrent reads are
race-free without any explicit locking.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from flask import Flask, abort, jsonify, render_template, request

from mtg_bot.training.stop_signal import (
    sentinel_path, stop_requested, write_stop,
)


def _read_run_file(path: Path) -> Optional[dict[str, Any]]:
    """Read one progress JSON file. Returns ``None`` if the file is
    missing or unparseable — the trainer's atomic write should
    prevent half-files in normal operation, but the file COULD be
    deleted out from under us between listdir and read, and a future
    trainer-side bug shouldn't take down the whole UI."""
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    # Stamp the source filename so the UI has a stable handle even
    # when run_id is missing or duplicated.
    data.setdefault("run_id", path.stem)
    data["_filename"] = path.name
    return data


def _list_runs(progress_dir: Path) -> list[dict[str, Any]]:
    """All progress JSON files in ``progress_dir``, deserialized and
    sorted by ``started_at`` descending (newest first). Files that
    fail to parse are silently skipped — the producer's atomic
    write should make that vanishingly rare in practice.

    Per-shard files from distributed runs (``*_shard_*.json``) are
    skipped: the orchestrator writes a rolled-up ``<run_id>.json``
    aggregate alongside them, and the UI shows that one card
    instead of N per-shard cards."""
    if not progress_dir.is_dir():
        return []
    runs: list[dict[str, Any]] = []
    for path in progress_dir.glob("*.json"):
        if "_shard_" in path.name:
            continue
        run = _read_run_file(path)
        if run is not None:
            runs.append(run)
    # Sort by started_at desc; missing/empty values sort last.
    runs.sort(key=lambda r: r.get("started_at") or "", reverse=True)
    return runs


def create_app(progress_dir: Path) -> Flask:
    """Build the Flask app. ``progress_dir`` is the directory of
    per-run progress JSON files. The directory does NOT have to
    exist at app-creation time — it's read lazily on every request,
    so a UI started before the first training run still works."""
    progress_dir = Path(progress_dir).resolve()

    # Templates live next to this file (mirroring how mtg_bot.ui.py
    # uses src/mtg_bot/templates). Static assets — favicon, etc. —
    # live in the sibling ``static/`` and are served at ``/static/``
    # by Flask's default static_url_path.
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

    @app.route("/api/runs/<run_id>")
    def api_run(run_id: str):
        # Lookup by exact filename stem first (the trainer's
        # convention). Fall back to scanning runs for a matching
        # run_id field, which lets a renamed file still be found
        # by id.
        progress_dir: Path = app.config["PROGRESS_DIR"]
        candidate = progress_dir / f"{run_id}.json"
        run = _read_run_file(candidate) if candidate.is_file() else None
        if run is None:
            for r in _list_runs(progress_dir):
                if r.get("run_id") == run_id:
                    run = r
                    break
        if run is None:
            abort(404)
        return jsonify(run)

    @app.route("/api/runs/<run_id>/replays")
    def api_run_replays(run_id: str):
        """List captured replay files for a given run.

        The producer (iterate_alphazero) writes ``replays_dir`` into
        the run's progress JSON pointing at the directory it captured
        into. This endpoint reads that hint and returns the
        ``.json.gz`` files alongside the subpath the main mtg_bot UI
        needs to load them via ``/api/load_replay/<subpath>``. Subpath
        = ``<replays_dir.name>/<filename>``, since the main UI's
        ``--replays-root`` is meant to point at the parent directory.
        """
        progress_dir: Path = app.config["PROGRESS_DIR"]
        candidate = progress_dir / f"{run_id}.json"
        run = _read_run_file(candidate) if candidate.is_file() else None
        if run is None:
            for r in _list_runs(progress_dir):
                if r.get("run_id") == run_id:
                    run = r
                    break
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

        Writes a sentinel file ``.STOP_<target_id>`` in the progress
        directory. The producer (iterate cycle / self-play /
        eval pool / queue server) polls for that sentinel at stage
        boundaries and exits cleanly, finalizing its progress JSON
        with ``status="stopped"``.

        Cycle-vs-single-run targeting: when the run's progress JSON
        has a ``cycle_id`` field (set by ``iterate_alphazero`` for
        all child stages — self-play, train, eval), the sentinel is
        written for the cycle, which propagates to the in-flight
        child via the dual-id check in
        ``stop_signal.stop_requested``. Otherwise the sentinel is
        written for the single run.

        Idempotent — calling twice does NOT error; the second call
        refreshes the sentinel's timestamp + reason. Body is an
        optional JSON ``{"reason": str}`` for log/audit metadata.
        """
        progress_dir: Path = app.config["PROGRESS_DIR"]
        candidate = progress_dir / f"{run_id}.json"
        run = _read_run_file(candidate) if candidate.is_file() else None
        if run is None:
            for r in _list_runs(progress_dir):
                if r.get("run_id") == run_id:
                    run = r
                    break
        if run is None:
            abort(404)
        body = request.get_json(silent=True) or {}
        reason = body.get("reason") if isinstance(body, dict) else None
        # Cycle-aware targeting: a child stage's progress JSON carries
        # a ``cycle_id`` back-pointer when iterate_alphazero owns it.
        # Stopping the cycle is what the user typically wants — the
        # iter loop checks the cycle sentinel between stages and
        # short-circuits the rest of the cycle.
        cycle_id = run.get("cycle_id")
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
        ``run_id`` (or its parent cycle, if any). Useful for the UI
        to show "stop pending" between the click and the next
        producer-side stage boundary, and for tests."""
        progress_dir: Path = app.config["PROGRESS_DIR"]
        candidate = progress_dir / f"{run_id}.json"
        run = _read_run_file(candidate) if candidate.is_file() else None
        if run is None:
            for r in _list_runs(progress_dir):
                if r.get("run_id") == run_id:
                    run = r
                    break
        if run is None:
            abort(404)
        cycle_id = run.get("cycle_id")
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
