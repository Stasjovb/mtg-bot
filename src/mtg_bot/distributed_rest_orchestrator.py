"""REST-based distributed-stage orchestrator (v2-cutover).

Replaces the SSH-driven ``run_distributed_self_play`` /
``run_distributed_eval`` orchestrators in
``mtg_bot.training.distributed`` with a thin client that drives the
v2 REST contract end-to-end:

1. POST ``/v2/stage/create`` on the coordinator (the existing
   ``mtg_bot serve`` port-5099 server with the v2 blueprint enabled).
2. POST ``/v2/start_self_play`` (or ``/v2/start_eval``) to every
   worker URL in parallel. ``202`` = accepted; ``409 worker_busy`` =
   error.
3. Poll ``GET /v2/stage/<id>`` every ``poll_interval_s`` until
   ``status == "complete"`` (auto-close handles the natural-drain
   path).
4. Return the final counters.

The contract details — endpoint shapes, status semantics, retry
policy — live in ``docs/DISTRIBUTED_API_v2.md``. This module is just
the orchestrator-side glue.

Threading: parallel ``/v2/start_*`` POSTs use ``threading.Thread``
(small N, ~3-4 workers, matches the codebase style; no asyncio).

Note on scope: per the v2-cutover design, the orchestrator does NOT
build per-game stage specs from a SelfPlayJobSpec dataclass any more.
The orchestrator's only responsibility is to assemble the
``games: [{game_idx, deck_indices, seed}]`` array and the per-stage
knobs (nodes, samples, weights, per_game_timeout_sec, capture_every,
claim_ttl_seconds) — everything else is worker-local config.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


log = logging.getLogger(__name__)


# Tunables. Tests monkeypatch ``poll_interval_s`` to a tiny value so the
# stage-poll loop doesn't pace the suite at 5s per drain.
DEFAULT_POLL_INTERVAL_S = 5.0
DEFAULT_HTTP_TIMEOUT_S = 30.0


# --------------------------------------------------------------------------
# Shards-config (worker URL list)
# --------------------------------------------------------------------------


def load_worker_urls(path: Path) -> list[str]:
    """Read ``shards_config.json`` and return the worker URL list.

    Post-cutover the file shape is::

        {"worker_urls": ["http://desktop:5198", "http://mac:5198", ...]}

    Reuses :func:`mtg_bot.cli.runs.heartbeat_poller.load_shards_config`
    for the parser so all consumers share one rejection-of-legacy-shape
    code path. Returns just the URL strings (the heartbeat-poller
    flavor wraps them in dicts for back-compat with its
    ``_id_to_url`` mapping; here we only need the URLs).
    """
    from mtg_bot.cli.runs.heartbeat_poller import load_shards_config
    entries = load_shards_config(Path(path))
    out: list[str] = []
    for e in entries:
        url = e.get("worker_url")
        if isinstance(url, str) and url:
            out.append(url)
    return out


# --------------------------------------------------------------------------
# HTTP helpers
# --------------------------------------------------------------------------


def _http_post_json(
    url: str,
    payload: dict[str, Any],
    *,
    timeout: float = DEFAULT_HTTP_TIMEOUT_S,
) -> tuple[int, bytes]:
    """POST a JSON body. Returns ``(status, body_bytes)``. Network
    errors surface as :class:`urllib.error.URLError`.
    """
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        body = b""
        try:
            body = e.read() or b""
        except Exception:
            pass
        return e.code, body


def _http_get_json(
    url: str, *, timeout: float = DEFAULT_HTTP_TIMEOUT_S,
) -> tuple[int, bytes]:
    """GET a URL. Returns ``(status, body_bytes)``."""
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        body = b""
        try:
            body = e.read() or b""
        except Exception:
            pass
        return e.code, body


# --------------------------------------------------------------------------
# Stage-running
# --------------------------------------------------------------------------


@dataclass
class StageSpec:
    """Coordinator-side stage spec the orchestrator POSTs to
    ``/v2/stage/create``. Mirrors the JSON shape in
    ``docs/DISTRIBUTED_API_v2.md``."""

    stage_id: str
    kind: str  # "self_play" | "eval"
    weights: dict[str, str]
    nodes: int
    samples: int
    per_game_timeout_sec: float
    capture_every: int
    claim_ttl_seconds: int
    games: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage_id": self.stage_id,
            "kind": self.kind,
            "weights": self.weights,
            "nodes": self.nodes,
            "samples": self.samples,
            "per_game_timeout_sec": self.per_game_timeout_sec,
            "capture_every": self.capture_every,
            "claim_ttl_seconds": self.claim_ttl_seconds,
            "games": self.games,
        }


@dataclass
class StageResult:
    """Final counters returned by :func:`run_stage`."""

    stage_id: str
    status: str
    n_games_done: int
    crashed: int
    timed_out: int
    wins_new: Optional[int] = None
    wins_old: Optional[int] = None
    draws: int = 0


class StartWorkerError(RuntimeError):
    """One or more workers refused the ``/v2/start_*`` POST."""


def start_workers(
    *,
    worker_urls: list[str],
    stage_id: str,
    coordinator_url: str,
    kind: str,  # "self_play" | "eval"
    http_post_json: Callable[..., tuple[int, bytes]] = _http_post_json,
) -> list[dict[str, Any]]:
    """POST ``/v2/start_<kind>`` to every worker URL in parallel.

    Returns the list of per-worker response payloads from the 202.
    Raises :class:`StartWorkerError` if any worker returned 409 or any
    other non-202 status.

    The request body carries ONLY ``{stage_id, coordinator_url}`` —
    per the v2 contract, worker-owned config (n_workers,
    deck_pool_path, weights_cache_root) is NOT sent on the wire.
    """
    assert kind in ("self_play", "eval")
    endpoint = f"/v2/start_{kind}"
    payload = {
        "stage_id": stage_id,
        "coordinator_url": coordinator_url,
    }
    results: list[Optional[tuple[int, bytes]]] = [None] * len(worker_urls)
    threads: list[threading.Thread] = []

    def _worker(idx: int, url: str) -> None:
        try:
            results[idx] = http_post_json(
                url.rstrip("/") + endpoint, payload,
            )
        except Exception as e:  # noqa: BLE001
            results[idx] = (0, f"exception: {e}".encode("utf-8"))

    for idx, url in enumerate(worker_urls):
        t = threading.Thread(
            target=_worker, args=(idx, url), daemon=True,
            name=f"rest-orch-start-{idx}",
        )
        t.start()
        threads.append(t)
    for t in threads:
        t.join(timeout=DEFAULT_HTTP_TIMEOUT_S + 5.0)

    payloads: list[dict[str, Any]] = []
    failures: list[str] = []
    for url, status_body in zip(worker_urls, results):
        if status_body is None:
            failures.append(f"{url}: no response")
            continue
        status, body = status_body
        if status == 202:
            try:
                payloads.append(json.loads(body.decode("utf-8")))
            except json.JSONDecodeError:
                payloads.append({})
            continue
        if status == 409:
            failures.append(
                f"{url}: worker_busy (409); body={body[:200]!r}"
            )
            continue
        failures.append(f"{url}: status={status} body={body[:200]!r}")
    if failures:
        raise StartWorkerError(
            f"start_workers ({kind}) failed: " + "; ".join(failures)
        )
    return payloads


def poll_stage(
    *,
    coordinator_url: str,
    stage_id: str,
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
    timeout_s: Optional[float] = None,
    sleep: Callable[[float], None] = time.sleep,
    http_get: Callable[..., tuple[int, bytes]] = _http_get_json,
    stop_check: Optional[Callable[[], bool]] = None,
    progress_writer: Optional[Callable[[dict[str, Any]], None]] = None,
) -> StageResult:
    """Poll ``GET /v2/stage/<stage_id>`` every ``poll_interval_s``
    until ``status == "complete"``.

    ``stop_check`` is invoked between polls; if it returns True the
    poller exits early with the LAST-seen counters. Used by the
    UI-driven abort path.

    ``progress_writer`` is invoked with the parsed stage status dict
    after every successful poll (including the final one). Pre-built
    factory :func:`make_runs_db_progress_writer` produces a writer
    that pushes the aggregate + per-shard ``run_progress`` rows the
    training UI consumes. Pass ``None`` to skip live progress writes
    (default — callers that only want the final ``StageResult`` need
    nothing extra).

    The auto-close from ``feature/stage-auto-close`` handles the
    natural-drain transition to ``"complete"`` server-side, so this
    function just needs to GET and check.
    """
    url = coordinator_url.rstrip("/") + f"/v2/stage/{stage_id}"
    deadline = (
        (time.monotonic() + timeout_s) if timeout_s is not None else None
    )
    last: dict[str, Any] = {}
    while True:
        if stop_check is not None and stop_check():
            break
        status, body = http_get(url)
        if status == 200:
            try:
                last = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError:
                last = {}
            if progress_writer is not None and last:
                try:
                    progress_writer(last)
                except Exception:  # noqa: BLE001
                    # Progress writes are advisory; a transient
                    # runs.db lock or a serialization bug must not
                    # bring down the orchestrator's poll loop.
                    log.exception(
                        "poll_stage: progress_writer raised; continuing",
                    )
            if last.get("status") == "complete":
                break
        elif status == 404:
            raise RuntimeError(
                f"poll_stage: stage_id={stage_id!r} not found at "
                f"{coordinator_url}"
            )
        # 5xx / transient — just retry next tick.
        if deadline is not None and time.monotonic() >= deadline:
            log.warning(
                "poll_stage: timeout reached without complete; "
                "last status=%s",
                last.get("status"),
            )
            break
        sleep(poll_interval_s)
    return StageResult(
        stage_id=stage_id,
        status=last.get("status", "unknown"),
        n_games_done=int(last.get("n_games_done", 0)),
        crashed=int(last.get("crashed", 0)),
        timed_out=int(last.get("timed_out", 0)),
        wins_new=(
            int(last["wins_new"]) if last.get("wins_new") is not None else None
        ),
        wins_old=(
            int(last["wins_old"]) if last.get("wins_old") is not None else None
        ),
        draws=int(last.get("draws", 0) or 0),
    )


def run_stage(
    *,
    coordinator_url: str,
    worker_urls: list[str],
    spec: StageSpec,
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
    timeout_s: Optional[float] = None,
    stop_check: Optional[Callable[[], bool]] = None,
    progress_writer: Optional[Callable[[dict[str, Any]], None]] = None,
    http_post_json: Callable[..., tuple[int, bytes]] = _http_post_json,
    http_get_json: Callable[..., tuple[int, bytes]] = _http_get_json,
    sleep: Callable[[float], None] = time.sleep,
) -> StageResult:
    """End-to-end run of one stage. Combines the three steps:

    1. POST ``/v2/stage/create``.
    2. POST ``/v2/start_<kind>`` to every worker URL in parallel.
    3. Poll ``/v2/stage/<id>`` until complete.

    The function does NOT abort on ``/v2/start_*`` 409 (worker_busy)
    — that's a fatal config error and signals the operator that a
    prior stage didn't drain. Callers can catch
    :class:`StartWorkerError` if they want to handle it.

    Returns a :class:`StageResult` with the final counters.
    """
    # 1. Create the stage on the coordinator.
    create_url = coordinator_url.rstrip("/") + "/v2/stage/create"
    status, body = http_post_json(create_url, spec.to_dict())
    if status not in (200, 409):
        raise RuntimeError(
            f"/v2/stage/create returned {status}: {body[:200]!r}"
        )
    # 409 is fine: idempotent re-submit with identical spec (the
    # coordinator's stage_create handler returns 200 on identical
    # spec, 409 only on spec mismatch).
    if status == 409:
        raise RuntimeError(
            f"/v2/stage/create: stage_id={spec.stage_id!r} exists with "
            f"a different spec; body={body[:200]!r}"
        )

    # 2. Tell every worker to start pulling.
    start_workers(
        worker_urls=worker_urls,
        stage_id=spec.stage_id,
        coordinator_url=coordinator_url,
        kind=spec.kind,
        http_post_json=http_post_json,
    )

    # 3. Poll until complete (or stop_check fires).
    return poll_stage(
        coordinator_url=coordinator_url,
        stage_id=spec.stage_id,
        poll_interval_s=poll_interval_s,
        timeout_s=timeout_s,
        sleep=sleep,
        http_get=http_get_json,
        progress_writer=progress_writer,
        stop_check=stop_check,
    )


# --------------------------------------------------------------------------
# Stage-spec builders for self-play / eval (orchestrator-side helpers)
# --------------------------------------------------------------------------


def build_self_play_games(
    *,
    n_games: int,
    base_seed: int,
    deck_pool_size: int,
    deck_picker: Optional[Callable[[int], tuple[int, int]]] = None,
) -> list[dict[str, Any]]:
    """Generate the per-game spec list for a self-play stage.

    ``deck_picker(game_idx)`` returns ``(deck_a_idx, deck_b_idx)``.
    Default: deterministic round-robin pairing through the pool so
    every game has two distinct deck indices.
    """
    if n_games <= 0:
        return []
    if deck_pool_size <= 0:
        raise ValueError("deck_pool_size must be positive")

    def default_picker(game_idx: int) -> tuple[int, int]:
        a = (game_idx * 7) % deck_pool_size
        b = (game_idx * 7 + 1 + (game_idx % (deck_pool_size - 1))) % deck_pool_size
        if b == a:
            b = (b + 1) % deck_pool_size
        return a, b

    pick = deck_picker if deck_picker is not None else default_picker
    games: list[dict[str, Any]] = []
    for i in range(n_games):
        a, b = pick(i)
        games.append({
            "game_idx": i,
            "deck_indices": [int(a), int(b)],
            "seed": int(base_seed) + i,
        })
    return games


def make_self_play_stage_spec(
    *,
    stage_id: str,
    n_games: int,
    base_seed: int,
    deck_pool_size: int,
    weights_version: str,
    nodes: int,
    samples: int,
    per_game_timeout_sec: float,
    capture_every: int = 0,
    claim_ttl_seconds: int = 1200,
) -> StageSpec:
    """Build a self-play :class:`StageSpec`. ``weights_version`` is the
    string label both seats share (e.g. ``"v6"``)."""
    games = build_self_play_games(
        n_games=n_games, base_seed=base_seed,
        deck_pool_size=deck_pool_size,
    )
    return StageSpec(
        stage_id=stage_id,
        kind="self_play",
        weights={"p0": weights_version, "p1": weights_version},
        nodes=nodes,
        samples=samples,
        per_game_timeout_sec=per_game_timeout_sec,
        capture_every=capture_every,
        claim_ttl_seconds=claim_ttl_seconds,
        games=games,
    )


def make_eval_stage_spec(
    *,
    stage_id: str,
    n_games: int,
    base_seed: int,
    deck_pool_size: int,
    new_version: str,
    old_version: str,
    nodes: int,
    samples: int,
    per_game_timeout_sec: float,
    capture_every: int = 0,
    claim_ttl_seconds: int = 1200,
) -> StageSpec:
    """Build an eval :class:`StageSpec`."""
    games = build_self_play_games(
        n_games=n_games, base_seed=base_seed,
        deck_pool_size=deck_pool_size,
    )
    return StageSpec(
        stage_id=stage_id,
        kind="eval",
        weights={"new": new_version, "old": old_version},
        nodes=nodes,
        samples=samples,
        per_game_timeout_sec=per_game_timeout_sec,
        capture_every=capture_every,
        claim_ttl_seconds=claim_ttl_seconds,
        games=games,
    )


# --------------------------------------------------------------------------
# runs.db progress writer (Training UI plumbing)
# --------------------------------------------------------------------------


def make_runs_db_progress_writer(
    run_id: str,
    *,
    started_perf: Optional[float] = None,
    client_module: Any = None,
) -> Callable[[dict[str, Any]], None]:
    """Build a :func:`run_stage` ``progress_writer`` callback that
    streams the coordinator's stage status into ``run_progress`` rows
    keyed under ``run_id``.

    Writes two layers on each invocation:

    - The **aggregate** row (``shard_label=None``) carries the totals
      the training UI's headline stats read: ``n_games_done``,
      ``n_games_total``, ``elapsed_seconds``, ``crashed``,
      ``timed_out``, ``wins_new``/``wins_old``/``draws`` for eval, plus
      ``n_samples`` and ``n_workers`` in ``extra_json`` (those two
      surface the UI's "Samples" and "Workers" stat cards and feed the
      derived "Games/hr", "Samples/hr", and "ETA" math in
      ``training_ui/app.py``).
    - One **per-shard** row per machine in ``stage_status["machines"]``,
      carrying the same fields scoped to that worker — surfaces on
      the UI's per-machine cards.

    ``started_perf`` lets the caller pin an explicit
    ``time.perf_counter()`` start so ``elapsed_seconds`` matches the
    caller's notion of "stage runtime" (default: first writer
    invocation). ``client_module`` is for tests — defaults to the
    real ``mtg_bot.cli.runs.client``.

    Exceptions are caught and logged by ``poll_stage``'s wrapper; this
    writer doesn't try/except itself so a real bug surfaces in tests.
    """
    if client_module is None:
        from mtg_bot.cli.runs import client as client_module  # noqa: PLW0127
    # Lazy init so the first poll's elapsed_seconds is ~0 instead of
    # whatever wall time the orchestrator spent in setup.
    started: dict[str, float] = {}

    def _push(status: dict[str, Any]) -> None:
        if "perf" not in started:
            started["perf"] = (
                started_perf if started_perf is not None
                else time.perf_counter()
            )
        elapsed = time.perf_counter() - started["perf"]
        kind = status.get("kind", "self_play")
        n_done = int(status.get("n_games_done", 0) or 0)
        n_total = int(status.get("n_games_total", 0) or 0)
        crashed = int(status.get("crashed", 0) or 0)
        timed_out = int(status.get("timed_out", 0) or 0)
        n_samples = int(status.get("n_samples", 0) or 0)
        n_workers = int(status.get("n_workers", 0) or 0)
        is_eval = kind == "eval"

        # Aggregate row — ``shard_label=None`` upserts the
        # stage-level totals row.
        client_module.push_progress(
            run_id,
            n_games_done=n_done,
            n_games_total=n_total,
            elapsed_seconds=elapsed,
            crashed=crashed,
            timed_out=timed_out,
            wins_new=(
                int(status.get("wins_new") or 0) if is_eval else None
            ),
            wins_old=(
                int(status.get("wins_old") or 0) if is_eval else None
            ),
            draws=int(status.get("draws", 0) or 0),
            extra={
                "n_samples": n_samples,
                "n_workers": n_workers,
            },
        )

        # Per-shard rows — one per machine. ``n_games_total`` on each
        # shard row mirrors the stage total so the UI's "X of N"
        # rendering has the denominator either way.
        for m in status.get("machines", []) or []:
            label = m.get("label")
            if not label:
                continue
            m_done = int(m.get("n_games_done", 0) or 0)
            m_inflight = int(m.get("n_in_flight", 0) or 0)
            m_total_dur = float(m.get("total_duration_s", 0.0) or 0.0)
            client_module.push_progress(
                run_id,
                shard_label=label,
                n_games_done=m_done,
                n_games_total=n_total,
                # Per-machine elapsed_seconds is the actual wall time
                # the machine spent on completed games (sum of
                # duration_s). Differs from the stage's elapsed
                # wall clock — the UI prefers per-game-seconds-avg
                # which is computed from this.
                elapsed_seconds=m_total_dur if m_total_dur > 0 else None,
                crashed=int(m.get("crashed", 0) or 0),
                timed_out=int(m.get("timed_out", 0) or 0),
                wins_new=(
                    int(m.get("wins_new") or 0)
                    if is_eval and m.get("wins_new") is not None
                    else None
                ),
                wins_old=(
                    int(m.get("wins_old") or 0)
                    if is_eval and m.get("wins_old") is not None
                    else None
                ),
                draws=int(m.get("draws", 0) or 0),
                extra={
                    "n_samples": int(m.get("n_samples", 0) or 0),
                    "n_in_flight": m_inflight,
                    # n_workers on a per-shard row = "this machine is
                    # one worker"; sum across shards = total machines.
                    "n_workers": 1,
                },
            )

    return _push
