"""v2 REST endpoint blueprint for the coordinator.

Wired into the existing ``mtg_bot serve`` Flask app
(``mtg_bot.cli.serve.create_app``) -- the doc decision was to extend
the port-5099 server rather than spin up a second process.

This module owns the v2 endpoints (``/v2/stage/...``, ``/v2/claim``,
``/v2/report_result``, ``/v2/weights/...``, ``/v2/healthz``).
Stateful machinery (the SQLite queue store + the HeartbeatPoller) is
factored out into peer modules ``queue_db.py`` and
``heartbeat_poller.py``; this file is just request parsing + dispatch.

``POST /v2/report_result`` is the load-bearing endpoint at cluster
scale: workers POST one per finished game. Under the multipart-blob
shape (Phase 1 and earlier) the per-request work (multipart parse +
.npz disk write + DB upsert) bottlenecked the coord under ~30+
workers -- see ``project_mtg_bot_coord_wsgi`` memory entry. Phase
2B drops multipart entirely: workers upload artifacts to shared
storage (file:// share or s3:// bucket) before POST and the JSON
body carries only the URIs. The handler validates, enqueues a
background job into a shared ThreadPoolExecutor, and returns 202
in <10ms. The background job fetches each URI via the injected
``ArtifactFetcher``, writes the bytes into ``iterate_data`` /
``replays_root`` under the SAME deterministic filenames as before,
and then calls ``queue_db.record_report``. Fetch failures retry
3x then write an ``upload_failed`` row so forensics can locate the
broken URI; the worker has already moved on so 5xx-ing is moot.

See ``docs/DISTRIBUTED_API_v2.md`` for the wire contract and
``docs/DISTRIBUTED_RUN_FLOW.md`` for the runtime walkthrough.
"""

from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import Executor
from pathlib import Path
from typing import Any, Optional

from flask import Blueprint, Response, jsonify, request, send_file

from mtg_bot.cli.runs import queue_db
from mtg_bot.cli.runs.coordinator_artifact_fetcher import (
    ArtifactFetcher,
    LocalArtifactFetcher,
    MultiSchemeFetcher,
)


logger = logging.getLogger(__name__)


# Retry schedule for the background fetch + write job. Distinct
# from the S3 fetcher's own retry loop -- this wraps the entire
# fetch+write step, including the disk I/O.
_REPORT_JOB_BACKOFF_SECONDS = (1.0, 3.0, 10.0)


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
    # about whitespace normalization here -- both sides come from the
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


def _safe_claim_basename(claim_id: str) -> str:
    """Strip ``:`` and ``/`` from a claim_id so it slots into a
    flat-file basename without smuggling extra directory levels."""
    return claim_id.replace(":", "_").replace("/", "_")


def _process_report_job(
    *,
    claim_id: str,
    stage_id: str,
    game_idx: int,
    shard_label: str,
    meta: dict[str, Any],
    npz_uri: Optional[str],
    replay_uri: Optional[str],
    npz_size_bytes: Optional[int],
    replay_size_bytes: Optional[int],
    iterate_data_dir: Path,
    replays_root: Path,
    queue_db_path: Path,
    fetcher: ArtifactFetcher,
    heartbeat_poller_provider: Optional[Any],
) -> None:
    """Background-job body. Idempotent: if a results row already
    exists for ``claim_id`` the work is skipped.

    On terminal fetch/write failure, writes a row with
    ``outcome="upload_failed"`` so the orchestrator can see the
    failure rather than the game hanging in an in-flight state
    until the claim TTL expires.
    """
    # ---- Idempotency check -----------------------------------------
    conn = queue_db.connect(queue_db_path)
    try:
        existing_claim = queue_db.get_claim(conn, claim_id)
        if existing_claim is not None and existing_claim["reported"] == 1:
            logger.info(
                "report_result job for claim_id=%s skipped: "
                "already reported (idempotent)",
                claim_id,
            )
            return
    finally:
        conn.close()

    npz_path: Optional[str] = None
    replay_path: Optional[str] = None
    fetch_error: Optional[BaseException] = None
    broken_uri: Optional[str] = None

    # ---- Fetch + write (with retries) ------------------------------
    for attempt in range(len(_REPORT_JOB_BACKOFF_SECONDS) + 1):
        try:
            if npz_uri:
                npz_path = _fetch_and_write_npz(
                    fetcher=fetcher,
                    uri=npz_uri,
                    expected_size=npz_size_bytes,
                    stage_id=stage_id,
                    shard_label=shard_label,
                    claim_id=claim_id,
                    iterate_data_dir=iterate_data_dir,
                )
            if replay_uri:
                replay_path = _fetch_and_write_replay(
                    fetcher=fetcher,
                    uri=replay_uri,
                    expected_size=replay_size_bytes,
                    stage_id=stage_id,
                    shard_label=shard_label,
                    game_idx=game_idx,
                    replays_root=replays_root,
                )
            fetch_error = None
            broken_uri = None
            break
        except Exception as exc:  # noqa: BLE001 - retry+log shape
            fetch_error = exc
            broken_uri = npz_uri or replay_uri
            if attempt >= len(_REPORT_JOB_BACKOFF_SECONDS):
                break
            time.sleep(_REPORT_JOB_BACKOFF_SECONDS[attempt])

    # ---- Record the result -----------------------------------------
    if fetch_error is not None:
        logger.error(
            "report_result job for claim_id=%s gave up after "
            "%d attempts: npz_uri=%s replay_uri=%s err=%s",
            claim_id,
            len(_REPORT_JOB_BACKOFF_SECONDS) + 1,
            npz_uri, replay_uri, fetch_error,
        )
        # Override the worker-supplied outcome so the row state
        # tells the truth about what shipped. Keep the meta dict
        # otherwise intact for forensics.
        record_meta = dict(meta)
        record_meta["outcome"] = "upload_failed"
        with queue_db.WRITE_LOCK:
            conn = queue_db.connect(queue_db_path)
            try:
                queue_db.record_report(
                    conn,
                    claim_id=claim_id,
                    report_meta=record_meta,
                    npz_path=None,
                    replay_path=None,
                    artifact_uri=broken_uri,
                )
            finally:
                conn.close()
        return

    # Success path.
    with queue_db.WRITE_LOCK:
        conn = queue_db.connect(queue_db_path)
        try:
            outcome = queue_db.record_report(
                conn,
                claim_id=claim_id,
                report_meta=meta,
                npz_path=npz_path,
                replay_path=replay_path,
                artifact_uri=npz_uri,
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


def _fetch_and_write_npz(
    *,
    fetcher: ArtifactFetcher,
    uri: str,
    expected_size: Optional[int],
    stage_id: str,
    shard_label: str,
    claim_id: str,
    iterate_data_dir: Path,
) -> str:
    blob = fetcher.fetch(uri)
    if expected_size is not None and len(blob) != expected_size:
        raise ValueError(
            f"npz size mismatch for claim_id={claim_id}: "
            f"declared={expected_size} bytes, got={len(blob)} bytes "
            f"(uri={uri!r})",
        )
    iterate_data_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{stage_id}_{shard_label}_{_safe_claim_basename(claim_id)}.npz"
    target = iterate_data_dir / filename
    target.write_bytes(blob)
    return str(target)


def _fetch_and_write_replay(
    *,
    fetcher: ArtifactFetcher,
    uri: str,
    expected_size: Optional[int],
    stage_id: str,
    shard_label: str,
    game_idx: int,
    replays_root: Path,
) -> str:
    blob = fetcher.fetch(uri)
    if expected_size is not None and len(blob) != expected_size:
        raise ValueError(
            f"replay size mismatch for game_idx={game_idx}: "
            f"declared={expected_size} bytes, got={len(blob)} bytes "
            f"(uri={uri!r})",
        )
    replay_subdir = replays_root / f"{stage_id}_{shard_label}"
    replay_subdir.mkdir(parents=True, exist_ok=True)
    filename = f"{game_idx}.json.gz"
    target = replay_subdir / filename
    target.write_bytes(blob)
    return str(target)


def build_v2_blueprint(
    *,
    queue_db_path: Path,
    weights_root: Path,
    iterate_data_dir: Path,
    replays_root: Path,
    process_started_at_monotonic: float,
    heartbeat_poller_provider: Optional[callable] = None,
    artifact_fetcher: Optional[ArtifactFetcher] = None,
    report_executor: Optional[Executor] = None,
) -> Blueprint:
    """Construct the v2 Flask blueprint.

    ``heartbeat_poller_provider`` is a zero-arg callable that returns
    the live HeartbeatPoller instance (or None when none is running).
    Wrapped in a provider so the blueprint can be built before the
    poller starts.

    ``artifact_fetcher`` reads worker-uploaded ``.npz`` / replay
    blobs by URI. Defaults to a local-only ``MultiSchemeFetcher`` --
    callers that want S3 support pass a fully-configured fetcher in
    (set up by ``serve.create_app``). ``report_executor`` is the
    ThreadPoolExecutor that runs the background fetch+write+upsert
    job per ``/v2/report_result`` POST. Both are injected so tests
    can substitute a synchronous in-process executor and a stub
    fetcher pointed at ``tmp_path``.
    """
    bp = Blueprint("v2_coordinator", __name__)

    fetcher = artifact_fetcher or MultiSchemeFetcher(
        local=LocalArtifactFetcher(),
    )

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
        """JSON-only async drop-off. The handler validates +
        enqueues; the background executor does the fetch + write +
        DB upsert. Returns 202 with ``queued: true`` on a fresh
        accept (caller never blocks on the network or the disk)."""
        if not request.is_json:
            return jsonify({
                "error": (
                    "report_result requires application/json body "
                    "(multipart removed in Phase 2B)"
                ),
            }), 400
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "body must be a JSON object"}), 400
        meta = body.get("meta")
        if not isinstance(meta, dict):
            return jsonify({
                "error": "meta required and must be a JSON object",
            }), 400
        claim_id = meta.get("claim_id")
        if not claim_id:
            return jsonify({"error": "claim_id required in meta"}), 400
        npz_uri = body.get("npz_uri")
        replay_uri = body.get("replay_uri")
        npz_size_bytes = body.get("npz_size_bytes")
        replay_size_bytes = body.get("replay_size_bytes")
        # Resolve the claim to its stage_id + game_idx so the
        # background job has everything it needs without re-reading.
        conn = _open_db()
        try:
            claim_row = queue_db.get_claim(conn, claim_id)
        finally:
            conn.close()
        if claim_row is None:
            return jsonify({"error": "unknown claim_id"}), 404
        if claim_row["reported"] == 1:
            # Synchronous 409: don't let a duplicate POST get
            # enqueued and silently swallowed by the idempotency
            # check inside the job. The caller sees the conflict
            # immediately.
            return jsonify({
                "accepted": False,
                "error": "claim already reported",
            }), 409
        stage_id = claim_row["stage_id"]
        game_idx = int(claim_row["game_idx"])
        shard_label = meta.get("shard_label") or "unknown"

        kwargs = dict(
            claim_id=claim_id,
            stage_id=stage_id,
            game_idx=game_idx,
            shard_label=shard_label,
            meta=meta,
            npz_uri=npz_uri,
            replay_uri=replay_uri,
            npz_size_bytes=npz_size_bytes,
            replay_size_bytes=replay_size_bytes,
            iterate_data_dir=iterate_data_dir,
            replays_root=replays_root,
            queue_db_path=queue_db_path,
            fetcher=fetcher,
            heartbeat_poller_provider=heartbeat_poller_provider,
        )

        if report_executor is None:
            # Tests that don't inject an executor get synchronous
            # dispatch -- otherwise asserting on the post-job DB
            # state is racy. Production always supplies one.
            _process_report_job(**kwargs)
        else:
            report_executor.submit(_process_report_job, **kwargs)

        return jsonify({
            "accepted": True,
            "queued": True,
            "claim_id": claim_id,
        }), 202

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
