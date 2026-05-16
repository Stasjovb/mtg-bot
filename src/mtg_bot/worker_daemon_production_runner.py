"""Production GameRunners for the worker daemon (Phase 2c).

Lifted from ``mtg_bot.cli.shard._run_pull_shard`` / ``_run_eval_shard``
and ``mtg_bot.training.distributed.run_shard_pull`` /
``run_shard_eval_pull``. Where those drive a pull-mode SQLite-backed
master queue, this module drives the v2 REST claim/play/report loop
one game at a time.

Key shape differences from the SSH-era shards:

- The deck pool is loaded once at setup time from a fixed path; the
  per-game ``deck_indices`` from the ``/v2/claim`` response select two
  archetypes from that pool (rather than re-running the legacy
  ``_sample_decks_for_game`` per-game-seed sampler). This is the
  authoritative deck selection — the coordinator's stage spec is the
  source of truth.
- Weights are fetched lazily on first claim that needs them, then
  cached in memory by version. A version change between claims (rare
  in self-play, normal in eval where p0=new and p1=old) re-runs
  ``fetch_weights_if_missing`` and rebuilds the NN evaluator.
- The runner is synchronous: one game at a time per
  :class:`mtg_bot.worker_daemon_claim_loop.ClaimLoopRunner`. The
  ``n_workers`` field on the start request is currently stored but not
  used to fan games out — Phase 2c picks the simplest correct shape;
  parallelism returns when the daemon spawns multiple claim-loop
  threads (see the "Open questions" in the PR-2c report).
- No SHM NN eval server. At the small per-game volume this runner sees
  (1 in flight), a per-call ``NNEvaluator.forward`` is fine; the SHM
  fan-out was a benefit of the pool-with-workers shape that we now
  flatten. The SHM path stays available for the master's in-process
  iterate runs via ``run_shard_local``.

The npz file the SSH shard wrote to disk is here returned as raw bytes
in :attr:`GameResult.npz_bytes` and shipped over multipart in the
``/v2/report_result`` POST. The coordinator's ``record_report`` writes
it under ``iterate_data/<stage>_<shard>_<safe_claim>.npz`` — same
naming the SSH writer used, so downstream train / UI keep working
unchanged.
"""

from __future__ import annotations

import io
import logging
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Optional

from mtg_bot.worker_daemon_claim_loop import (
    CallableGameRunner,
    GameResult,
    GameRunner,
    _http_get,
    fetch_weights_if_missing,
)


log = logging.getLogger(__name__)


# Default deck pool path. Matches the path that
# ``mtg_bot iterate`` / ``mtg_bot eval`` / the SSH shard runner have
# used since the synthetic mono-color G/R fallback was retired.
DEFAULT_DECK_POOL_PATH = "data/17lands/eoe_decks.json.gz"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _resolve_deck_pool_path(explicit: Optional[str]) -> Path:
    """Resolve the deck pool path. Honors explicit override; falls
    back to the system-wide default.
    """
    if explicit:
        return Path(explicit)
    return Path(DEFAULT_DECK_POOL_PATH)


def _read_metadata_json(weights_dir: Path) -> dict[str, Any]:
    """Read the version's ``metadata.json`` sidecar. Returns an empty
    dict on failure so callers fall back to ``NNEvaluator`` defaults.
    """
    import json

    meta_path = weights_dir / "metadata.json"
    if not meta_path.is_file():
        return {}
    try:
        with meta_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _build_nn_pimc_config(weights_path: Path, metadata: dict[str, Any]):
    """Construct an ``NNPimcConfig`` from the version's metadata
    sidecar. Mirrors the architecture / policy / action-encoding
    auto-discovery the iterate orchestrator does today.
    """
    from mtg_bot.training import NNPimcConfig

    training = metadata.get("training") or {}
    # Schema reminder: `architecture`, `hidden_sizes`,
    # `policy_hidden_sizes`, `with_policy`, and `action_encoding_version`
    # are at the TOP LEVEL of metadata.json (where every registered
    # version v5+ writes them). Fall back to `training.*` for forward-
    # compat with any future trainer that nests them.
    hs = metadata.get("hidden_sizes") or training.get("hidden_sizes")
    phs = metadata.get("policy_hidden_sizes") or training.get(
        "policy_hidden_sizes"
    )
    architecture = (
        metadata.get("architecture") or training.get("architecture")
    )
    action_encoding_version = metadata.get("action_encoding_version")
    with_policy = bool(
        metadata.get("with_policy", training.get("with_policy", True))
    )

    return NNPimcConfig(
        weights_path=str(weights_path),
        samples=4,  # Default; overridden per-claim if claim carries `samples`.
        inner_nodes=200,  # Default; overridden per-claim.
        hidden_sizes=tuple(hs) if hs else None,
        architecture=architecture,
        policy_hidden_sizes=tuple(phs) if phs else None,
        action_encoding_version=action_encoding_version,
        with_policy=with_policy,
        puct=with_policy,  # PUCT requires a policy head.
        batch_size=32,
        # ``device=None`` resolves to NNEvaluator's CPU default — safe
        # for the daemon, which doesn't pre-prime CUDA on its main
        # thread. Future optimization: thread an "auto" sentinel and
        # resolve in build() (matches run_shard_pull's pattern), but
        # that requires the daemon to never have called
        # ``torch.cuda.is_available()`` upstream first.
        device=None,
    )


def _encode_npz_bytes(
    chunk: tuple, write_structured_tokens: bool = False
) -> bytes:
    """Serialize one game's chunk to npz-format bytes. Mirrors the
    SSH shard's ``_flush`` writer, but to a BytesIO instead of an
    output_dir path.

    ``chunk`` is the 7-tuple returned by
    ``_play_one_parallel_game``'s success path:
    ``(features, outcomes, policy_targets, action_masks, winner,
       outcome_kind, struct_rows)``. Empty arrays for crashed / timed-
    out games encode cleanly (zero-row npz).
    """
    import numpy as np

    from mtg_bot.training import save_dataset

    features = chunk[0]
    outcomes = chunk[1]
    policy_targets = chunk[2]
    action_masks = chunk[3]
    # Write to a temp file under a BytesIO since np.savez_compressed
    # wants a file-like or path. BytesIO works because savez_compressed
    # internally uses the zipfile module which only needs seek/write.
    buf = io.BytesIO()
    if write_structured_tokens and len(chunk) > 6 and chunk[6]:
        from mtg_bot.training.data_gen import _pad_and_stack_structured_rows
        struct = _pad_and_stack_structured_rows(chunk[6])
        # Use np.savez_compressed directly with the keys save_dataset
        # would produce; we can't call save_dataset because it only
        # accepts a Path. Mirror save_dataset's array layout.
        arrays = {
            "features": features,
            "outcomes": outcomes,
            "policy_targets": policy_targets,
            "action_masks": action_masks,
            "structured_token_type": struct["structured_token_type"],
            "structured_token_emb_ids": struct["structured_token_emb_ids"],
            "structured_token_scalars": struct["structured_token_scalars"],
            "structured_attention_mask": struct["structured_attention_mask"],
        }
    else:
        arrays = {
            "features": features,
            "outcomes": outcomes,
            "policy_targets": policy_targets,
            "action_masks": action_masks,
        }
    # Drop empty rows (crashed / timed-out games): save_dataset would
    # raise on FEATURE_DIM mismatch when features is a (0, FEATURE_DIM)
    # array. The save_dataset path validates; for raw bytes we just
    # round-trip via numpy.
    np.savez_compressed(buf, **arrays)
    return buf.getvalue()


def _play_self_play_game(
    *,
    factory,
    base_seed: int,
    game_idx: int,
    deck_pool,
    deck_indices: list[int],
    per_game_timeout_sec: Optional[float],
    capture_every: int,
    action_encoding_version: Optional[str],
    write_structured_tokens: bool,
) -> tuple[tuple, str, Optional[int], int]:
    """Run one self-play game synchronously in this thread.

    Returns ``(chunk, outcome_kind, winner, n_samples)``.

    The deck pool is indexed by the claim's ``deck_indices`` rather
    than re-running the legacy ``_sample_decks_for_game`` seed-based
    sampler — the coordinator's stage spec is authoritative for which
    archetypes each game runs.
    """
    from mtg_bot.training.data_gen import (
        _empty_arrays,
        _generate_one_game_data,
    )

    # Honor the claim's deck_indices. If the pool is smaller than the
    # claim requested, fall back to modulo-wrap rather than crashing —
    # tiny test pools can still drive an end-to-end smoke.
    n = len(deck_pool)
    if n == 0:
        raise RuntimeError("deck pool is empty; cannot play game")
    a_idx = int(deck_indices[0]) % n
    b_idx = int(deck_indices[1]) % n if len(deck_indices) > 1 else a_idx
    selected_pool = [deck_pool[a_idx], deck_pool[b_idx]]

    try:
        chunk = _generate_one_game_data(
            game_idx=game_idx,
            p0_factory=factory,
            p1_factory=factory,
            base_seed=base_seed,
            decision_cap=4000,
            sample_every=1,
            replay_config=None,
            deck_pool=selected_pool,
            per_game_timeout_sec=per_game_timeout_sec,
            hang_dump_dir=None,
            heuristics=None,
            action_encoding_version=(
                action_encoding_version or "positional_v1"
            ),
            structured_tokens=write_structured_tokens,
        )
    except TimeoutError:
        f, o, p, m = _empty_arrays()
        chunk = (f, o, p, m, None, "timed_out", [])
    except Exception:  # noqa: BLE001 - intentional broad catch
        log.exception(
            "[self_play_runner] game %d crashed; dropping", game_idx
        )
        f, o, p, m = _empty_arrays()
        chunk = (f, o, p, m, None, "crashed", [])

    # ``chunk`` is now a 7-tuple ``(features, outcomes, policy_targets,
    # action_masks, winner, outcome_kind, struct_rows)``.
    winner = chunk[4]
    outcome_kind = chunk[5] if len(chunk) > 5 else (
        "crashed" if winner is None and not bool(getattr(chunk[0], "size", 0))
        else "completed"
    )
    n_samples = int(chunk[0].shape[0]) if hasattr(chunk[0], "shape") else 0
    return chunk, outcome_kind, winner, n_samples


def _play_eval_game(
    *,
    p0_factory,
    p1_factory,
    base_seed: int,
    game_idx: int,
    deck_pool,
    deck_indices: list[int],
    per_game_timeout_sec: Optional[float],
) -> tuple[Optional[int], int, str]:
    """Run one eval game synchronously in this thread.

    Returns ``(winner_remapped, decisions, outcome_kind)`` where
    ``winner_remapped == 0`` always means "the original ``new`` seat
    won" and ``1`` means "the original ``old`` seat won" — the
    seat-alternation remap from
    ``_play_one_match_game_alternating_indexed``.
    """
    from mtg_bot.training.self_play import _play_one_match_game

    n = len(deck_pool)
    if n == 0:
        raise RuntimeError("deck pool is empty; cannot play eval game")
    a_idx = int(deck_indices[0]) % n
    b_idx = int(deck_indices[1]) % n if len(deck_indices) > 1 else a_idx
    selected_pool = [deck_pool[a_idx], deck_pool[b_idx]]

    # Alternate seat on odd game_idx (mirror
    # _play_one_match_game_alternating_indexed). Even game_idx: p0=new
    # plays seat 0. Odd: factories swap; the returned winner is
    # remapped so 0=>"new won" regardless of seating.
    if game_idx % 2 == 0:
        p0, p1 = p0_factory, p1_factory
    else:
        p0, p1 = p1_factory, p0_factory

    try:
        winner, decisions = _play_one_match_game(
            game_idx=game_idx,
            p0_factory=p0,
            p1_factory=p1,
            base_seed=base_seed,
            decision_cap=4000,
            per_game_timeout_sec=per_game_timeout_sec,
            deck_pool=selected_pool,
            replay_config=None,
            hang_dump_dir=None,
            heuristics=None,
            heartbeat_path=None,
        )
        outcome_kind = "completed"
    except TimeoutError as exc:
        partial = int(getattr(exc, "decisions_completed", 0) or 0)
        return None, partial, "timed_out"
    except Exception:  # noqa: BLE001 - intentional broad catch
        log.exception(
            "[eval_runner] game %d crashed; dropping", game_idx
        )
        return None, 0, "crashed"

    if game_idx % 2 == 1 and winner is not None:
        winner = 1 - winner
    return winner, decisions, outcome_kind


# ---------------------------------------------------------------------------
# Self-play GameRunner
# ---------------------------------------------------------------------------


def build_self_play_runner(
    coordinator_url: str,
    stage_id: str,
    n_workers: int,
    weights_cache_root: Path,
    worker_id: str,
    log_event: Optional[Callable[[str, dict], None]] = None,
    *,
    deck_pool_path: Optional[str] = None,
    http_get: Callable[..., tuple[int, bytes, dict[str, str]]] = _http_get,
) -> GameRunner:
    """Production self-play :class:`GameRunner`.

    Per-claim flow:

    1. Resolve ``weights["p0"]`` from the claim payload. (Self-play
       stages always carry ``p0 == p1`` per the API contract, so we
       only build one evaluator.)
    2. Fetch the weights blob + metadata sidecar from
       ``<coordinator_url>/v2/weights/<version>``; cache by version
       under ``weights_cache_root``.
    3. Build (or reuse cached) ``NNPimcConfig`` from the metadata
       sidecar — architecture / hidden_sizes / policy_hidden_sizes /
       action_encoding_version all auto-discover.
    4. Override per-claim knobs (``nodes``, ``samples``) on the cached
       config.
    5. Run one game via ``_generate_one_game_data`` — synchronous in
       the current thread.
    6. Encode the per-game chunk to npz bytes; return :class:`GameResult`.
    """

    # In-memory caches. The runner is single-threaded inside one
    # ClaimLoopRunner, so plain dicts are race-free.
    state: dict[str, Any] = {
        "deck_pool": None,
        "configs_by_version": {},  # version -> NNPimcConfig
    }

    def _emit(name: str, payload: dict) -> None:
        if log_event is not None:
            try:
                log_event(name, payload)
            except Exception:  # noqa: BLE001 - swallow logger failures
                log.exception("[self_play_runner] log_event %s raised", name)

    def _ensure_deck_pool() -> None:
        if state["deck_pool"] is not None:
            return
        path = _resolve_deck_pool_path(deck_pool_path)
        if not path.is_file():
            raise RuntimeError(
                f"deck pool not found at {path}; pass deck_pool_path "
                f"explicitly via /v2/start_self_play body, or place "
                f"the canonical pool at {DEFAULT_DECK_POOL_PATH}."
            )
        from mtg_bot.decks import decks_from_json
        state["deck_pool"] = decks_from_json(path)
        _emit(
            "deck_pool_loaded",
            {"path": str(path), "n_decks": len(state["deck_pool"])},
        )

    def _ensure_config(version: str):
        cfg = state["configs_by_version"].get(version)
        if cfg is not None:
            return cfg
        weights_dir = fetch_weights_if_missing(
            coordinator_url=coordinator_url,
            version=version,
            weights_root=Path(weights_cache_root),
            http_get=http_get,
        )
        metadata = _read_metadata_json(weights_dir)
        cfg = _build_nn_pimc_config(
            weights_dir / "weights.pt", metadata,
        )
        state["configs_by_version"][version] = cfg
        _emit(
            "weights_loaded",
            {
                "version": version,
                "architecture": cfg.architecture,
                "action_encoding_version": cfg.action_encoding_version,
            },
        )
        return cfg

    def _setup(coord_url_unused, weights_root_unused, kind, n_workers_unused):
        # All lazy — weight load happens on first claim, deck pool is
        # loaded on first game. ``setup`` just records the kind for
        # the assertion below; misuse (calling the self-play factory
        # for an eval stage) surfaces as a clear error rather than
        # silent wrong-runner behavior.
        state["kind"] = kind
        if kind != "self_play":
            log.warning(
                "[self_play_runner] setup called with kind=%s "
                "(expected self_play)", kind,
            )

    def _play_one(claim: dict, shard_label: str) -> GameResult:
        t0 = time.perf_counter()
        _ensure_deck_pool()

        weights = claim.get("weights") or {}
        version = weights.get("p0") or weights.get("new")
        if not version:
            raise RuntimeError(
                f"self-play claim missing weights.p0: claim={claim}"
            )
        cfg = _ensure_config(version)

        # Apply per-claim search knobs on top of the metadata-derived
        # config. The metadata defaults are sensible (200/4) but the
        # coordinator's stage spec is authoritative.
        nodes = int(claim.get("nodes") or cfg.inner_nodes)
        samples = int(claim.get("samples") or cfg.samples)
        per_game_timeout_sec = claim.get("per_game_timeout_sec")
        if per_game_timeout_sec is not None:
            per_game_timeout_sec = float(per_game_timeout_sec)
        capture_every = int(claim.get("capture_every") or 0)
        seed = int(claim.get("seed") or 0)
        game_idx = int(claim.get("game_idx") or 0)
        deck_indices = list(claim.get("deck_indices") or [0, 0])

        # Per-claim re-build with overridden samples/inner_nodes; the
        # underlying NNEvaluator is rebuilt fresh each time which costs
        # a (cheap) state_dict load. Reusing the evaluator across games
        # would require pulling it out of ``cfg.build`` — premature
        # optimization until profiling says so.
        from mtg_bot.training import NNPimcConfig
        per_game_cfg = NNPimcConfig(
            weights_path=cfg.weights_path,
            samples=samples,
            inner_nodes=nodes,
            hidden_sizes=cfg.hidden_sizes,
            architecture=cfg.architecture,
            policy_hidden_sizes=cfg.policy_hidden_sizes,
            action_encoding_version=cfg.action_encoding_version,
            with_policy=cfg.with_policy,
            puct=cfg.puct,
            batch_size=cfg.batch_size,
            device=cfg.device,
        )
        factory = per_game_cfg.build

        _emit(
            "game_start",
            {
                "claim_id": claim.get("claim_id"),
                "game_idx": game_idx,
                "version": version,
                "nodes": nodes,
                "samples": samples,
            },
        )

        chunk, outcome_kind, winner, n_samples = _play_self_play_game(
            factory=factory,
            base_seed=seed,
            game_idx=game_idx,
            deck_pool=state["deck_pool"],
            deck_indices=deck_indices,
            per_game_timeout_sec=per_game_timeout_sec,
            capture_every=capture_every,
            action_encoding_version=cfg.action_encoding_version,
            write_structured_tokens=False,
        )

        npz_bytes = _encode_npz_bytes(chunk, write_structured_tokens=False)
        duration_s = time.perf_counter() - t0
        _emit(
            "game_end",
            {
                "claim_id": claim.get("claim_id"),
                "game_idx": game_idx,
                "outcome": outcome_kind,
                "winner": winner,
                "n_samples": n_samples,
                "duration_s": duration_s,
            },
        )
        return GameResult(
            outcome=outcome_kind,
            winner=winner,
            n_samples=n_samples,
            duration_s=duration_s,
            npz_bytes=npz_bytes,
        )

    def _teardown() -> None:
        state["configs_by_version"].clear()
        state["deck_pool"] = None

    return CallableGameRunner(_play_one, _setup, _teardown)


# ---------------------------------------------------------------------------
# Eval GameRunner
# ---------------------------------------------------------------------------


def build_eval_runner(
    coordinator_url: str,
    stage_id: str,
    n_workers: int,
    weights_cache_root: Path,
    worker_id: str,
    log_event: Optional[Callable[[str, dict], None]] = None,
    *,
    deck_pool_path: Optional[str] = None,
    http_get: Callable[..., tuple[int, bytes, dict[str, str]]] = _http_get,
) -> GameRunner:
    """Production eval :class:`GameRunner`.

    Per-claim flow:

    1. Read ``weights["new"]`` and ``weights["old"]`` from the claim
       payload.
    2. Fetch both weights+metadata blobs (cache-aware).
    3. Build (or reuse) one ``NNPimcConfig`` per version.
    4. Run one match game; alternate seats by ``game_idx`` parity and
       remap the winner so seat 0 always means "new won."
    5. Return :class:`GameResult` with ``wins_new`` / ``wins_old`` /
       ``draws``.
    """

    state: dict[str, Any] = {
        "deck_pool": None,
        "configs_by_version": {},
    }

    def _emit(name: str, payload: dict) -> None:
        if log_event is not None:
            try:
                log_event(name, payload)
            except Exception:  # noqa: BLE001
                log.exception("[eval_runner] log_event %s raised", name)

    def _ensure_deck_pool() -> None:
        if state["deck_pool"] is not None:
            return
        path = _resolve_deck_pool_path(deck_pool_path)
        if not path.is_file():
            raise RuntimeError(
                f"deck pool not found at {path}; pass deck_pool_path "
                f"explicitly via /v2/start_eval body, or place the "
                f"canonical pool at {DEFAULT_DECK_POOL_PATH}."
            )
        from mtg_bot.decks import decks_from_json
        state["deck_pool"] = decks_from_json(path)
        _emit(
            "deck_pool_loaded",
            {"path": str(path), "n_decks": len(state["deck_pool"])},
        )

    def _ensure_config(version: str):
        cfg = state["configs_by_version"].get(version)
        if cfg is not None:
            return cfg
        weights_dir = fetch_weights_if_missing(
            coordinator_url=coordinator_url,
            version=version,
            weights_root=Path(weights_cache_root),
            http_get=http_get,
        )
        metadata = _read_metadata_json(weights_dir)
        cfg = _build_nn_pimc_config(
            weights_dir / "weights.pt", metadata,
        )
        state["configs_by_version"][version] = cfg
        _emit(
            "weights_loaded",
            {
                "version": version,
                "architecture": cfg.architecture,
                "action_encoding_version": cfg.action_encoding_version,
            },
        )
        return cfg

    def _setup(coord_url_unused, weights_root_unused, kind, n_workers_unused):
        state["kind"] = kind
        if kind != "eval":
            log.warning(
                "[eval_runner] setup called with kind=%s "
                "(expected eval)", kind,
            )

    def _play_one(claim: dict, shard_label: str) -> GameResult:
        t0 = time.perf_counter()
        _ensure_deck_pool()

        weights = claim.get("weights") or {}
        new_version = weights.get("new") or weights.get("p0")
        old_version = weights.get("old") or weights.get("p1")
        if not new_version or not old_version:
            raise RuntimeError(
                f"eval claim missing weights.new / weights.old: "
                f"claim={claim}"
            )

        new_cfg_base = _ensure_config(new_version)
        old_cfg_base = _ensure_config(old_version)

        nodes = int(claim.get("nodes") or new_cfg_base.inner_nodes)
        samples = int(claim.get("samples") or new_cfg_base.samples)
        per_game_timeout_sec = claim.get("per_game_timeout_sec")
        if per_game_timeout_sec is not None:
            per_game_timeout_sec = float(per_game_timeout_sec)
        seed = int(claim.get("seed") or 0)
        game_idx = int(claim.get("game_idx") or 0)
        deck_indices = list(claim.get("deck_indices") or [0, 0])

        from mtg_bot.training import NNPimcConfig

        def _per_game(cfg):
            return NNPimcConfig(
                weights_path=cfg.weights_path,
                samples=samples,
                inner_nodes=nodes,
                hidden_sizes=cfg.hidden_sizes,
                architecture=cfg.architecture,
                policy_hidden_sizes=cfg.policy_hidden_sizes,
                action_encoding_version=cfg.action_encoding_version,
                with_policy=cfg.with_policy,
                puct=cfg.puct,
                batch_size=cfg.batch_size,
                device=cfg.device,
            )

        new_factory = _per_game(new_cfg_base).build
        old_factory = _per_game(old_cfg_base).build

        _emit(
            "game_start",
            {
                "claim_id": claim.get("claim_id"),
                "game_idx": game_idx,
                "new_version": new_version,
                "old_version": old_version,
                "nodes": nodes,
                "samples": samples,
            },
        )

        winner_remapped, decisions, outcome_kind = _play_eval_game(
            p0_factory=new_factory,
            p1_factory=old_factory,
            base_seed=seed,
            game_idx=game_idx,
            deck_pool=state["deck_pool"],
            deck_indices=deck_indices,
            per_game_timeout_sec=per_game_timeout_sec,
        )

        wins_new = 1 if winner_remapped == 0 else 0
        wins_old = 1 if winner_remapped == 1 else 0
        draws = 1 if (
            outcome_kind == "completed" and winner_remapped is None
        ) else 0
        duration_s = time.perf_counter() - t0
        _emit(
            "game_end",
            {
                "claim_id": claim.get("claim_id"),
                "game_idx": game_idx,
                "outcome": outcome_kind,
                "winner_remapped": winner_remapped,
                "decisions": decisions,
                "duration_s": duration_s,
            },
        )
        return GameResult(
            outcome=outcome_kind,
            winner=winner_remapped,
            n_samples=0,
            duration_s=duration_s,
            wins_new=wins_new,
            wins_old=wins_old,
            draws=draws,
            npz_bytes=None,
        )

    def _teardown() -> None:
        state["configs_by_version"].clear()
        state["deck_pool"] = None

    return CallableGameRunner(_play_one, _setup, _teardown)
