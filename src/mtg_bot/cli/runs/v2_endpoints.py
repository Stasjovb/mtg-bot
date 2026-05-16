"""v2 REST endpoint blueprint for the coordinator.

Wired into the existing ``mtg_bot serve`` Flask app
(``mtg_bot.cli.serve.create_app``) — the doc decision was to extend
the port-5099 server rather than spin up a second process.

This module owns the v2 endpoints (``/v2/stage/...``, ``/v2/claim``,
``/v2/report_result``, ``/v2/weights/...``, ``/v2/healthz``).
Stateful machinery (the SQLite queue store + the HeartbeatPoller) is
factored out into peer modules ``queue_db.py`` and
``heartbeat_poller.py``; this file is just request parsing + dispatch.

See ``docs/DISTRIBUTED_API_v2.md`` for the wire contract and
``docs/DISTRIBUTED_RUN_FLOW.md`` for the runtime walkthrough.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Optional

from flask import Blueprint, Response, jsonify, request, send_file

from mtg_bot.cli.runs import queue_db


# Stage_id sanity: alphanumerics, underscores, dashes, dots, colons.
# Used to defend against path-traversal when stage_id appears in
# on-disk filenames.
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.\-:]+$")
_SAFE_VERSION_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")


def _is_safe_id(s: str) -> bool:
    return bool(s) and bool(_SAFE_ID_RE.match(s))


def _is_safe_version(s: str) -> bool:
    return bool(s) and bool(_SAFE_VERSION_RE.match(s))


def _spec_signature(spec: dict[str, Any]) -> str:
    """Canonical JSON of the parts of ``spec`` that drive equality for
    the idempotency check on ``POST /v2/stage/create``.

    We compare on the *full* spec minus volatile keys (``games`` is
    included; reordering games in two calls is a different spec).
    """
    # JSON-sorted-keys gives a deterministic string. We don't care
    # about whitespace normalization here — both sides come from the
    # same dumps() path.
    return json.dumps(spec, sort_keys=True)


def _resolve_paths(
    *,
    progress_dir: Path,
    weights_root: Path,
    iterate_data_dir: Path,
    replays_root: Path,
) -> dict[str, Path]:
    """Build the dict of resolved paths the handlers reference.

    Kept separate so tests can swap in tmp_path-rooted dirs without
    monkeypatching the module.
    """
    return {
        "progress": Path(progress_dir),
        "weights_root": Path(weights_root),
        "iterate_data": Path(iterate_data_dir),
        "replays": Path(replays_root),
    }


def build_v2_blueprint(
    *,
    queue_db_path: Path,
    weights_root: Path,
    iterate_data_dir: Path,
    replays_root: Path,
    process_started_at_monotonic: float,
    heartbeat_poller_provider: Optional[callable] = None,
) -> Blueprint:
    """Construct the v2 Flask blueprint.

    ``heartbeat_poller_provider`` is a zero-arg callable that returns
    the live HeartbeatPoller instance (or None when none is running).
    Wrapped in a provider so the blueprint can be built before the
    poller starts.
    """
    bp = Blueprint("v2_coordinator", __name__)

    def _open_db():
        return queue_db.connect(queue_db_path)

    # ---- POST /v2/stage/create ---------------------------------------

    @bp.route("/v2/stage/create", methods=["POST"])
    def stage_create():
        data = request.get_json(silent=True) or {}
        stage_id = data.get("stage_id")
        kind = data.get("kind")
        games = data.get("games")
        claim_ttl_seconds = data.get("claim_ttl_seconds")
        if not _is_safe_id(stage_id or ""):
            return jsonify({
                "error": "stage_id required and must match [A-Za-z0-9_.\\-:]+",
            }), 400
        if kind not in ("self_play", "eval"):
            return jsonify({
                "error": "kind must be 'self_play' or 'eval'",
            }), 400
        if not isinstance(games, list) or len(games) == 0:
            return jsonify({"error": "games[] required, non-empty"}), 400
        if not isinstance(claim_ttl_seconds, int) or claim_ttl_seconds <= 0:
            return jsonify({
                "error": "claim_ttl_seconds required, positive int",
            }), 400
        # Validate each game entry minimally.
        for g in games:
            if not isinstance(g, dict):
                return jsonify({"error": "each game must be an object"}), 400
            if "game_idx" not in g or "deck_indices" not in g or "seed" not in g:
                return jsonify({
                    "error": "each game needs game_idx + deck_indices + seed",
                }), 400
        spec_str = _spec_signature(data)
        with queue_db.WRITE_LOCK:
            conn = _open_db()
            try:
                existing = queue_db.get_stage(conn, stage_id)
                if existing is not None:
                    if existing["spec_json"] == spec_str:
                        # Idempotent: same spec, return 200.
                        return jsonify({
                            "stage_id": stage_id,
                            "n_games_queued": len(games),
                        })
                    return jsonify({
                        "error": (
                            "stage_id exists with a different spec"
                        ),
                    }), 409
                queue_db.insert_stage(
                    conn,
                    stage_id=stage_id,
                    kind=kind,
                    spec_json=spec_str,
                    claim_ttl_seconds=claim_ttl_seconds,
                    games=games,
                )
            finally:
                conn.close()
        return jsonify({
            "stage_id": stage_id,
            "n_games_queued": len(games),
        })

    # ---- GET /v2/stage/<stage_id> ------------------------------------

    @bp.route("/v2/stage/<stage_id>", methods=["GET"])
    def stage_get(stage_id: str):
        if not _is_safe_id(stage_id):
            return jsonify({"error": "invalid stage_id"}), 400
        conn = _open_db()
        try:
            counters = queue_db.stage_counters(conn, stage_id)
        finally:
            conn.close()
        if counters is None:
            return jsonify({"error": "no such stage_id"}), 404
        return jsonify(counters)

    # ---- POST /v2/stage/<stage_id>/close ------------------------------

    @bp.route("/v2/stage/<stage_id>/close", methods=["POST"])
    def stage_close(stage_id: str):
        if not _is_safe_id(stage_id):
            return jsonify({"error": "invalid stage_id"}), 400
        # ``reason`` is logged but not used for routing.
        _ = (request.get_json(silent=True) or {}).get("reason")
        with queue_db.WRITE_LOCK:
            conn = _open_db()
            try:
                ok = queue_db.mark_drained(conn, stage_id)
                if not ok:
                    return jsonify({"error": "no such stage_id"}), 404
                # Re-read post-update to surface the drained_at timestamp.
                row = queue_db.get_stage(conn, stage_id)
            finally:
                conn.close()
        return jsonify({
            "stage_id": stage_id,
            "drained_at": row["drained_at"],
        })

    # ---- POST /v2/claim -----------------------------------------------

    @bp.route("/v2/claim", methods=["POST"])
    def claim():
        data = request.get_json(silent=True) or {}
        worker_id = data.get("worker_id")
        stage_id = data.get("stage_id")
        if not worker_id or not stage_id:
            return jsonify({
                "error": "worker_id + stage_id required",
            }), 400
        if not _is_safe_id(stage_id):
            return jsonify({"error": "invalid stage_id"}), 400
        with queue_db.WRITE_LOCK:
            conn = _open_db()
            try:
                stage_row = queue_db.get_stage(conn, stage_id)
                if stage_row is None:
                    return jsonify({"error": "no such stage_id"}), 404
                result = queue_db.claim_next_game(
                    conn,
                    stage_id=stage_id,
                    worker_id=worker_id,
                    now_unix=time.time(),
                )
                if result is None:
                    # Either drained or queue empty. Distinguish from
                    # 404 (which the API doc reserves for "no such
                    # stage_id"); both drained/empty share 204.
                    return Response(status=204)
                # Build per-game spec from the stage's stored spec.
                spec = json.loads(stage_row["spec_json"])
                kind = stage_row["kind"]
                response = {
                    "claim_id": result["claim_id"],
                    "game_idx": result["game_idx"],
                    "deck_indices": result["deck_indices"],
                    "seed": result["seed"],
                    "kind": kind,
                    "weights": spec.get("weights"),
                    "nodes": spec.get("nodes"),
                    "samples": spec.get("samples"),
                    "per_game_timeout_sec": spec.get("per_game_timeout_sec"),
                    "capture_every": spec.get("capture_every"),
                    "expires_at": result["expires_at"],
                }
                # Track in the heartbeat poller so a DEAD worker's
                # in-flight claims get re-queued promptly.
                poller = (
                    heartbeat_poller_provider()
                    if heartbeat_poller_provider is not None else None
                )
                if poller is not None:
                    poller.track_claim(worker_id, result["claim_id"])
            finally:
                conn.close()
        return jsonify(response)

    # ---- POST /v2/report_result ---------------------------------------

    @bp.route("/v2/report_result", methods=["POST"])
    def report_result():
        # multipart: meta JSON in form field, npz / replay optional file
        meta_raw = request.form.get("meta")
        if not meta_raw:
            # Tolerate application/json bodies for the "no files"
            # case — the eval path commonly skips both npz and replay.
            if request.is_json:
                meta = request.get_json(silent=True) or {}
            else:
                return jsonify({"error": "meta field required"}), 400
        else:
            try:
                meta = json.loads(meta_raw)
            except json.JSONDecodeError:
                return jsonify({"error": "meta must be JSON"}), 400
        claim_id = meta.get("claim_id")
        if not claim_id:
            return jsonify({"error": "claim_id required in meta"}), 400
        # Resolve the claim to its stage_id so we can build the on-disk
        # path under iterate_data/replays.
        conn = _open_db()
        try:
            claim_row = queue_db.get_claim(conn, claim_id)
        finally:
            conn.close()
        if claim_row is None:
            return jsonify({"error": "unknown claim_id"}), 404
        stage_id = claim_row["stage_id"]
        game_idx = int(claim_row["game_idx"])
        shard_label = meta.get("shard_label") or "unknown"
        # File writes happen *before* DB updates so a half-written
        # report doesn't leave the DB pointing at a non-existent file.
        npz_path: Optional[str] = None
        replay_path: Optional[str] = None
        npz_file = request.files.get("npz")
        replay_file = request.files.get("replay")
        if npz_file is not None:
            iterate_data_dir.mkdir(parents=True, exist_ok=True)
            # Stage + shard + claim_id basename for uniqueness; the
            # claim_id already encodes the stage and game_idx.
            safe_claim = claim_id.replace(":", "_").replace("/", "_")
            npz_filename = f"{stage_id}_{shard_label}_{safe_claim}.npz"
            target = iterate_data_dir / npz_filename
            npz_file.save(str(target))
            npz_path = str(target)
        if replay_file is not None:
            replay_subdir = replays_root / f"{stage_id}_{shard_label}"
            replay_subdir.mkdir(parents=True, exist_ok=True)
            replay_filename = f"{game_idx}.json.gz"
            target = replay_subdir / replay_filename
            replay_file.save(str(target))
            replay_path = str(target)
        with queue_db.WRITE_LOCK:
            conn = _open_db()
            try:
                outcome = queue_db.record_report(
                    conn,
                    claim_id=claim_id,
                    report_meta=meta,
                    npz_path=npz_path,
                    replay_path=replay_path,
                )
            finally:
                conn.close()
        if outcome == "accepted":
            poller = (
                heartbeat_poller_provider()
                if heartbeat_poller_provider is not None else None
            )
            if poller is not None:
                poller.untrack_claim(claim_id)
            return jsonify({"accepted": True})
        if outcome == "duplicate":
            return jsonify({"accepted": True, "duplicate": True})
        if outcome == "conflict":
            return jsonify({
                "accepted": False,
                "error": "claim was re-delivered; report dropped",
            }), 409
        # outcome == "unknown" — claim row vanished between the read
        # and the write. Treat as 404 for symmetry with the up-front
        # check.
        return jsonify({"error": "unknown claim_id"}), 404

    # ---- GET /v2/weights/<version> ------------------------------------

    @bp.route("/v2/weights/<version>", methods=["GET"])
    def weights(version: str):
        if not _is_safe_version(version):
            return jsonify({"error": "invalid version"}), 400
        target = weights_root / version / "weights.pt"
        if not target.is_file():
            return jsonify({
                "error": f"weights not found for {version!r}",
            }), 404
        return send_file(
            str(target),
            mimetype="application/octet-stream",
            as_attachment=False,
        )

    # ---- GET /v2/weights/<version>/metadata ---------------------------

    @bp.route("/v2/weights/<version>/metadata", methods=["GET"])
    def weights_metadata(version: str):
        if not _is_safe_version(version):
            return jsonify({"error": "invalid version"}), 400
        target = weights_root / version / "metadata.json"
        if not target.is_file():
            return jsonify({
                "error": f"metadata not found for {version!r}",
            }), 404
        return send_file(
            str(target),
            mimetype="application/json",
            as_attachment=False,
        )

    # ---- GET /v2/healthz ----------------------------------------------

    @bp.route("/v2/healthz", methods=["GET"])
    def healthz():
        conn = _open_db()
        try:
            depths = queue_db.queue_depths(conn)
        finally:
            conn.close()
        return jsonify({
            "status": "ok",
            "queue_depths": depths,
            "uptime_s": time.monotonic() - process_started_at_monotonic,
        })

    return bp
