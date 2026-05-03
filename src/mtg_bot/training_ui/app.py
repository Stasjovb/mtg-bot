"""Flask app showing live progress of NN training runs.

Read-only viewer over the JSON files written by
``train_value_network(progress_path=...)``. The trainer is the
producer; this UI is one of (potentially) many consumers. We never
write back into the progress directory.

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

from flask import Flask, abort, jsonify, render_template


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
    write should make that vanishingly rare in practice."""
    if not progress_dir.is_dir():
        return []
    runs: list[dict[str, Any]] = []
    for path in progress_dir.glob("*.json"):
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

    return app
