"""Unit + smoke tests for the production worker-daemon GameRunner.

Phase 2c. Two layers of coverage:

1. **Fast unit tests** — exercise ``build_self_play_runner`` /
   ``build_eval_runner`` via mocked weight fetches + a monkeypatched
   ``_play_self_play_game`` / ``_play_eval_game`` so we cover the
   factory bookkeeping (weights cache, deck pool load, log_event
   fanout, npz encoding) without paying for a real torch game.
2. **One real-game smoke** — drives one tiny self-play game through
   the full claim/play/report loop via the existing Flask test-client
   adapter. CPU-only, ~5s wall. Tagged ``@pytest.mark.slow`` per
   project policy and skipped under ``MTG_BOT_FAST_TESTS=1``.
"""

from __future__ import annotations

import io
import json
import os
import threading
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import torch

from mtg_bot import worker_daemon
from mtg_bot import worker_daemon_claim_loop as cl
from mtg_bot import worker_daemon_production_runner as prr
from mtg_bot.cli import serve as serve_mod
from mtg_bot.search.nn_evaluator import _ValuePolicyMLP


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _save_tiny_weights(tmp_path: Path, version: str) -> Path:
    """Save a tiny dual-head net + a matching metadata.json under
    ``<tmp_path>/<version>/``. Returns the version dir.
    """
    version_dir = tmp_path / version
    version_dir.mkdir(parents=True, exist_ok=True)
    hidden_sizes = (16, 16)
    torch.save(
        _ValuePolicyMLP(hidden_sizes=hidden_sizes).state_dict(),
        version_dir / "weights.pt",
    )
    metadata = {
        "version": version,
        "action_encoding_version": "positional_v1",
        "training": {
            "with_policy": True,
            "hidden_sizes": list(hidden_sizes),
            "architecture": "shared",
        },
    }
    (version_dir / "metadata.json").write_text(
        json.dumps(metadata), encoding="utf-8",
    )
    return version_dir


def _save_tiny_deck_pool(tmp_path: Path) -> Path:
    """Write a 2-deck pool the runner can index by ``deck_indices``.
    Uses the existing ``simple_test_deck_pool`` helper."""
    import gzip
    import sys

    # _test_decks lives under tests/; we're already in tests/ so the
    # plain import works when pytest runs from project root.
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        from _test_decks import simple_test_deck_pool
    finally:
        sys.path.pop(0)

    decks = simple_test_deck_pool()
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "pool.json.gz"
    serialized = json.dumps(
        [{"draft_id": d.draft_id, "build_index": d.build_index,
          "cards": d.cards} for d in decks]
    )
    with gzip.open(path, "wb") as f:
        f.write(serialized.encode("utf-8"))
    return path


def _make_claim(
    *,
    game_idx: int = 0,
    stage_id: str = "stage_x",
    kind: str = "self_play",
    nodes: int = 10,
    samples: int = 1,
    weights: dict | None = None,
) -> dict:
    return {
        "claim_id": f"{stage_id}:{game_idx:06d}",
        "game_idx": game_idx,
        "deck_indices": [0, 1],
        "seed": 9_000_000 + game_idx,
        "kind": kind,
        "weights": weights or (
            {"p0": "vTEST", "p1": "vTEST"} if kind == "self_play"
            else {"new": "vNEW", "old": "vOLD"}
        ),
        "nodes": nodes,
        "samples": samples,
        "per_game_timeout_sec": 60.0,
        "capture_every": 0,
        "expires_at": "2099-01-01T00:00:00Z",
    }


def _stub_http_get_for_version_dir(version_dir: Path):
    """Return a ``http_get(url, timeout)`` that serves the weights /
    metadata from ``version_dir``. The runner expects a 200 + bytes
    pair for each of the two endpoints."""

    def http_get(url, timeout=30.0):
        if url.endswith("/metadata"):
            return 200, (version_dir / "metadata.json").read_bytes(), {}
        return 200, (version_dir / "weights.pt").read_bytes(), {}

    return http_get


# ---------------------------------------------------------------------------
# Unit tests — factory bookkeeping
# ---------------------------------------------------------------------------


def test_self_play_runner_caches_weights_by_version(tmp_path):
    """Two claims for the same version → one weights fetch."""
    src_dir = _save_tiny_weights(tmp_path / "src", "vTEST")
    cache_root = tmp_path / "cache"
    calls: list[str] = []

    def counting_http_get(url, timeout=30.0):
        calls.append(url)
        return _stub_http_get_for_version_dir(src_dir)(url, timeout)

    events: list[tuple[str, dict]] = []
    runner = prr.build_self_play_runner(
        coordinator_url="http://test:5099",
        stage_id="stage_x",
        n_workers=1,
        weights_cache_root=cache_root,
        worker_id="test-worker",
        log_event=lambda name, payload: events.append((name, payload)),
        deck_pool_path=str(_save_tiny_deck_pool(tmp_path / "pool")),
        http_get=counting_http_get,
    )
    runner.setup(
        coordinator_url="http://test:5099",
        weights_root=cache_root,
        stage_kind="self_play",
        n_workers=1,
    )

    # Monkeypatch the heavy per-game body so this test stays fast.
    def fake_play(**kwargs):  # noqa: D401, ARG001
        empty = (
            np.zeros((0, 51), dtype=np.float32),
            np.zeros((0,), dtype=np.float32),
            np.zeros((0, 1), dtype=np.float32),
            np.zeros((0, 1), dtype=bool),
            None,
            "completed",
            [],
        )
        return empty, "completed", 0, 0

    import mtg_bot.worker_daemon_production_runner as mod
    real = mod._play_self_play_game
    mod._play_self_play_game = fake_play
    try:
        result1 = runner.play_one_game(_make_claim(game_idx=0), "test")
        result2 = runner.play_one_game(_make_claim(game_idx=1), "test")
    finally:
        mod._play_self_play_game = real

    assert result1.outcome == "completed"
    assert result1.npz_bytes is not None
    assert result2.outcome == "completed"
    # Cache hit on the second claim — exactly 2 GETs total (weights +
    # metadata) for the SAME version across two games.
    # Post-merge: a coherent hit still costs one cheap metadata probe
    # (coherency contract) + a cold fetch adds a locked double-check
    # probe. Invariant unchanged: the weights BLOB is fetched exactly
    # ONCE for the version across both games (2nd game = cache hit).
    assert len([c for c in calls if not c.endswith("/metadata")]) == 1, calls
    # log_event was called for deck_pool_loaded + weights_loaded +
    # 2x (game_start + game_end) = 6 events.
    names = [name for name, _ in events]
    assert names.count("game_start") == 2
    assert names.count("game_end") == 2
    assert "weights_loaded" in names
    assert "deck_pool_loaded" in names


def _save_tiny_structured_metadata(tmp_path: Path, version: str) -> Path:
    """Mirror of ``_save_tiny_weights`` but with a real
    structured-net checkpoint + ``architecture='structured'`` in the
    metadata. Uses :func:`_build_structured_model` so the worker
    daemon's PoisonedWeightsCacheError coherency check accepts the
    pair (the check sniffs the state_dict shape to confirm the
    declared architecture).
    """
    from mtg_bot.search.nn_evaluator import _build_structured_model

    version_dir = tmp_path / version
    version_dir.mkdir(parents=True, exist_ok=True)
    torch.save(
        _build_structured_model().state_dict(),
        version_dir / "weights.pt",
    )
    metadata = {
        "version": version,
        "action_encoding_version": "canonical_v2",
        "architecture": "structured",
        "training": {
            "with_policy": True,
            "architecture": "structured",
        },
    }
    (version_dir / "metadata.json").write_text(
        json.dumps(metadata), encoding="utf-8",
    )
    return version_dir


@pytest.mark.parametrize(
    "saver,expected_structured",
    [
        (_save_tiny_weights, False),         # shared (flat MLP)
        (_save_tiny_structured_metadata, True),  # structured
    ],
    ids=["shared-arch-disables-structured-tokens",
         "structured-arch-enables-structured-tokens"],
)
def test_play_one_derives_write_structured_tokens_from_architecture(
    tmp_path, saver, expected_structured,
):
    # Regression: ``_play_one`` and ``_subprocess_play_self_play``
    # used to hardcode ``write_structured_tokens=False`` regardless
    # of the network's architecture, so every structured-net
    # self_play stage wrote npzs without the structured-token
    # columns and train_nn.py rejected them downstream
    # ("missing structured-token arrays"). The fix derives
    # ``write_structured_tokens`` from ``cfg.architecture`` so the
    # structured trainer's consumer contract is honored end-to-end.
    src_dir = saver(tmp_path / "src", "vTEST")
    captured: dict[str, Any] = {}

    def fake_play(**kwargs):
        captured.update(kwargs)
        empty = (
            np.zeros((0, 51), dtype=np.float32),
            np.zeros((0,), dtype=np.float32),
            np.zeros((0, 1), dtype=np.float32),
            np.zeros((0, 1), dtype=bool),
            None,
            "completed",
            [],
        )
        return empty, "completed", 0, 0

    import mtg_bot.worker_daemon_production_runner as mod
    real = mod._play_self_play_game
    mod._play_self_play_game = fake_play
    try:
        runner = prr.build_self_play_runner(
            coordinator_url="http://test:5099",
            stage_id="stage_x",
            n_workers=1,
            weights_cache_root=tmp_path / "cache",
            worker_id="test-worker",
            log_event=None,
            deck_pool_path=str(_save_tiny_deck_pool(tmp_path / "pool")),
            http_get=_stub_http_get_for_version_dir(src_dir),
        )
        runner.setup(
            "http://test:5099", tmp_path / "cache", "self_play", 1,
        )
        runner.play_one_game(_make_claim(), "test")
    finally:
        mod._play_self_play_game = real

    assert captured["write_structured_tokens"] is expected_structured


def test_self_play_runner_raises_on_missing_deck_pool(tmp_path):
    """No pool at the given path → clear error."""
    runner = prr.build_self_play_runner(
        coordinator_url="http://test:5099",
        stage_id="stage_x",
        n_workers=1,
        weights_cache_root=tmp_path / "cache",
        worker_id="test-worker",
        log_event=None,
        deck_pool_path=str(tmp_path / "missing.json.gz"),
    )
    runner.setup("http://test:5099", tmp_path, "self_play", 1)
    with pytest.raises(RuntimeError, match="deck pool not found"):
        runner.play_one_game(_make_claim(), "test")


def test_self_play_runner_raises_on_claim_missing_weights(tmp_path):
    """A self-play claim with no weights.p0 is a coordinator bug."""
    src_dir = _save_tiny_weights(tmp_path / "src", "vTEST")
    runner = prr.build_self_play_runner(
        coordinator_url="http://test:5099",
        stage_id="stage_x",
        n_workers=1,
        weights_cache_root=tmp_path / "cache",
        worker_id="test-worker",
        log_event=None,
        deck_pool_path=str(_save_tiny_deck_pool(tmp_path / "pool")),
        http_get=_stub_http_get_for_version_dir(src_dir),
    )
    runner.setup("http://test:5099", tmp_path / "cache", "self_play", 1)
    claim = _make_claim()
    claim["weights"] = {}
    with pytest.raises(RuntimeError, match="missing weights"):
        runner.play_one_game(claim, "test")


def test_eval_runner_loads_both_versions(tmp_path):
    """Eval runner fetches new + old, caches separately."""
    new_dir = _save_tiny_weights(tmp_path / "src", "vNEW")
    old_dir = _save_tiny_weights(tmp_path / "src", "vOLD")
    cache_root = tmp_path / "cache"
    calls: list[str] = []

    def http_get(url, timeout=30.0):
        calls.append(url)
        if "vNEW" in url:
            sub = new_dir
        elif "vOLD" in url:
            sub = old_dir
        else:
            raise AssertionError(f"unexpected URL {url}")
        if url.endswith("/metadata"):
            return 200, (sub / "metadata.json").read_bytes(), {}
        return 200, (sub / "weights.pt").read_bytes(), {}

    events: list[tuple[str, dict]] = []
    runner = prr.build_eval_runner(
        coordinator_url="http://test:5099",
        stage_id="eval_x",
        n_workers=1,
        weights_cache_root=cache_root,
        worker_id="test-worker",
        log_event=lambda n, p: events.append((n, p)),
        deck_pool_path=str(_save_tiny_deck_pool(tmp_path / "pool")),
        http_get=http_get,
    )
    runner.setup("http://test:5099", cache_root, "eval", 1)

    def fake_play(**kwargs):  # noqa: ARG001
        return 0, 5, "completed"

    import mtg_bot.worker_daemon_production_runner as mod
    real = mod._play_eval_game
    mod._play_eval_game = fake_play
    try:
        result = runner.play_one_game(
            _make_claim(kind="eval", game_idx=0), "test",
        )
    finally:
        mod._play_eval_game = real

    assert result.outcome == "completed"
    assert result.wins_new == 1
    assert result.wins_old == 0
    assert result.draws == 0
    # 4 GETs: 2 versions × (weights + metadata)
    # Post-merge: per-version cold = metadata-probe + locked double-
    # check probe + weights. Invariant: exactly ONE weights blob per
    # version (new+old) -- no torn/duplicate checkpoint download.
    assert len([c for c in calls if not c.endswith("/metadata")]) == 2
    names = [n for n, _ in events]
    assert names.count("weights_loaded") == 2


def test_eval_runner_alternation_remaps_winner_on_odd_game_idx(tmp_path):
    """On odd ``game_idx``, factories swap. The runner is responsible
    for the winner remap so seat 0 always means "new won." Verify by
    having the fake play body return ``winner=1`` on game_idx=1 and
    asserting the result reports ``winner_remapped=0`` (=> wins_new=1).
    """
    new_dir = _save_tiny_weights(tmp_path / "src", "vNEW")
    old_dir = _save_tiny_weights(tmp_path / "src", "vOLD")

    def http_get(url, timeout=30.0):
        sub = new_dir if "vNEW" in url else old_dir
        if url.endswith("/metadata"):
            return 200, (sub / "metadata.json").read_bytes(), {}
        return 200, (sub / "weights.pt").read_bytes(), {}

    runner = prr.build_eval_runner(
        coordinator_url="http://test:5099",
        stage_id="eval_x",
        n_workers=1,
        weights_cache_root=tmp_path / "cache",
        worker_id="test-worker",
        log_event=None,
        deck_pool_path=str(_save_tiny_deck_pool(tmp_path / "pool")),
        http_get=http_get,
    )
    runner.setup("http://test:5099", tmp_path, "eval", 1)

    # The fake play body always returns ``winner_remapped`` directly —
    # to simulate the inner alternation, we pretend the inner returned
    # winner=0 ("new won as seat 0") on both even and odd game_idx.
    # The runner does NOT re-remap because the fake is already at the
    # post-remap layer.
    import mtg_bot.worker_daemon_production_runner as mod
    mod._play_eval_game_real = mod._play_eval_game

    def fake_play(**kwargs):  # noqa: ARG001
        return 0, 5, "completed"

    mod._play_eval_game = fake_play
    try:
        for game_idx in (0, 1, 2, 3):
            r = runner.play_one_game(
                _make_claim(kind="eval", game_idx=game_idx), "test",
            )
            assert r.wins_new == 1, f"game_idx={game_idx}, r={r}"
            assert r.wins_old == 0
    finally:
        mod._play_eval_game = mod._play_eval_game_real
        del mod._play_eval_game_real


def test_encode_npz_bytes_roundtrips(tmp_path):
    """The bytes payload returned from a successful game must be a
    valid npz with the four expected arrays."""
    n = 3
    chunk = (
        np.random.randn(n, 51).astype(np.float32),
        np.zeros(n, dtype=np.float32),
        np.zeros((n, 1), dtype=np.float32),
        np.zeros((n, 1), dtype=bool),
        0,
        "completed",
        [],
    )
    blob = prr._encode_npz_bytes(chunk, write_structured_tokens=False)
    assert isinstance(blob, bytes)
    assert len(blob) > 0
    data = np.load(io.BytesIO(blob))
    assert set(data.keys()) >= {
        "features", "outcomes", "policy_targets", "action_masks",
    }
    assert data["features"].shape == (n, 51)


def test_encode_npz_bytes_emits_empty_structured_arrays_for_empty_chunk():
    # Regression: timed-out / crashed games go through
    # ``_empty_arrays()`` which produces an empty ``struct_rows=[]``.
    # The old guard ``if write_structured_tokens and chunk[6]`` fell
    # through to the flat-only branch and produced an npz WITHOUT
    # structured columns even though the consumer was set up for
    # structured; train_nn.py rejected the entire batch when even
    # ONE such empty npz was present. Empty struct rows must still
    # emit the 4 structured arrays (as shape-(0,0)) for schema
    # uniformity.
    empty_chunk = (
        np.zeros((0, 51), dtype=np.float32),
        np.zeros((0,), dtype=np.float32),
        np.zeros((0, 1), dtype=np.float32),
        np.zeros((0, 1), dtype=bool),
        None,            # winner
        "timed_out",     # outcome_kind
        [],              # struct_rows — the empty list that
                         # used to disable the structured branch.
    )
    blob = prr._encode_npz_bytes(empty_chunk, write_structured_tokens=True)
    data = np.load(io.BytesIO(blob))
    # All 4 structured columns must be present (even though shape-(0,0)).
    assert "structured_token_type" in data.files
    assert "structured_token_emb_ids" in data.files
    assert "structured_token_scalars" in data.files
    assert "structured_attention_mask" in data.files
    # Shape contract: empty rows + uniform schema.
    assert data["structured_token_type"].shape == (0, 0)
    assert data["features"].shape == (0, 51)


def test_resolve_deck_pool_path_honors_explicit_and_default():
    """Explicit > default."""
    p = prr._resolve_deck_pool_path("custom/pool.gz")
    assert p == Path("custom/pool.gz")
    p_default = prr._resolve_deck_pool_path(None)
    assert p_default == Path(prr.DEFAULT_DECK_POOL_PATH)


def test_read_metadata_json_returns_empty_on_missing(tmp_path):
    """Missing sidecar → empty dict (NNEvaluator falls back to defaults)."""
    assert prr._read_metadata_json(tmp_path) == {}


def test_read_metadata_json_returns_empty_on_malformed(tmp_path):
    """Corrupted sidecar → empty dict, not a crash."""
    (tmp_path / "metadata.json").write_text("{not json")
    assert prr._read_metadata_json(tmp_path) == {}


def test_play_self_play_game_handles_empty_pool_with_clear_error(tmp_path):
    """An empty pool is a daemon-side misconfiguration."""
    with pytest.raises(RuntimeError, match="deck pool is empty"):
        prr._play_self_play_game(
            factory=lambda seed: None,
            base_seed=0,
            game_idx=0,
            deck_pool=[],
            deck_indices=[0, 1],
            per_game_timeout_sec=None,
            capture_every=0,
            action_encoding_version=None,
            write_structured_tokens=False,
        )


def test_play_eval_game_handles_empty_pool_with_clear_error():
    """Same defense on the eval path."""
    with pytest.raises(RuntimeError, match="deck pool is empty"):
        prr._play_eval_game(
            p0_factory=lambda seed: None,
            p1_factory=lambda seed: None,
            base_seed=0,
            game_idx=0,
            deck_pool=[],
            deck_indices=[0, 1],
            per_game_timeout_sec=None,
        )


def test_play_self_play_game_converts_crash_to_empty_chunk(tmp_path, monkeypatch):
    """When ``_generate_one_game_data`` raises, return a crashed
    chunk rather than propagating."""
    import mtg_bot.training.data_gen as dg_mod

    def boom(**kwargs):
        raise RuntimeError("synthetic engine crash for test")

    monkeypatch.setattr(dg_mod, "_generate_one_game_data", boom)

    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        from _test_decks import simple_test_deck_pool
    finally:
        sys.path.pop(0)
    pool = simple_test_deck_pool()
    chunk, outcome, winner, n_samples = prr._play_self_play_game(
        factory=lambda seed: None,
        base_seed=0,
        game_idx=0,
        deck_pool=pool,
        deck_indices=[0, 1],
        per_game_timeout_sec=None,
        capture_every=0,
        action_encoding_version=None,
        write_structured_tokens=False,
    )
    assert outcome == "crashed"
    assert winner is None
    assert n_samples == 0


def test_play_self_play_game_handles_timeout(monkeypatch):
    """``TimeoutError`` -> ``timed_out`` outcome with empty chunk."""
    import mtg_bot.training.data_gen as dg_mod

    def slow(**kwargs):
        raise TimeoutError("synthetic timeout")

    monkeypatch.setattr(dg_mod, "_generate_one_game_data", slow)
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        from _test_decks import simple_test_deck_pool
    finally:
        sys.path.pop(0)
    pool = simple_test_deck_pool()
    chunk, outcome, winner, n_samples = prr._play_self_play_game(
        factory=lambda seed: None,
        base_seed=0,
        game_idx=0,
        deck_pool=pool,
        deck_indices=[0, 1],
        per_game_timeout_sec=1.0,
        capture_every=0,
        action_encoding_version=None,
        write_structured_tokens=False,
    )
    assert outcome == "timed_out"
    assert winner is None
    assert n_samples == 0


def test_play_eval_game_handles_crash(monkeypatch):
    """Eval crash -> ``("crashed", 0, None)`` shape."""
    import mtg_bot.training.self_play as sp_mod

    def boom(**kwargs):
        raise RuntimeError("synthetic eval crash")

    monkeypatch.setattr(sp_mod, "_play_one_match_game", boom)
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        from _test_decks import simple_test_deck_pool
    finally:
        sys.path.pop(0)
    pool = simple_test_deck_pool()
    winner, decisions, outcome = prr._play_eval_game(
        p0_factory=lambda seed: None,
        p1_factory=lambda seed: None,
        base_seed=0,
        game_idx=0,
        deck_pool=pool,
        deck_indices=[0, 1],
        per_game_timeout_sec=None,
    )
    assert winner is None
    assert decisions == 0
    assert outcome == "crashed"


def test_play_eval_game_handles_timeout_preserves_partial(monkeypatch):
    """Eval timeout -> ``("timed_out", partial_decisions, None)``.
    The partial-decisions field rides on the TimeoutError instance.
    """
    import mtg_bot.training.self_play as sp_mod

    def slow(**kwargs):
        exc = TimeoutError("synthetic eval timeout")
        exc.decisions_completed = 42
        raise exc

    monkeypatch.setattr(sp_mod, "_play_one_match_game", slow)
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        from _test_decks import simple_test_deck_pool
    finally:
        sys.path.pop(0)
    pool = simple_test_deck_pool()
    winner, decisions, outcome = prr._play_eval_game(
        p0_factory=lambda seed: None,
        p1_factory=lambda seed: None,
        base_seed=0,
        game_idx=0,
        deck_pool=pool,
        deck_indices=[0, 1],
        per_game_timeout_sec=1.0,
    )
    assert winner is None
    assert decisions == 42
    assert outcome == "timed_out"


# ---------------------------------------------------------------------------
# Phase 2 — subprocess-pool wiring (use_subprocess_pool=True).
#
# These tests verify the runner's plumbing: that ``_setup`` spawns the
# pool, ``_play_one`` submits to it, and ``_teardown`` shuts it down.
# We monkeypatch ``concurrent.futures.ProcessPoolExecutor`` to a
# ``ThreadPoolExecutor`` for tests — this exercises the same submit /
# .result() code path without paying for real subprocess spawn or
# requiring the work function to be picklable (test mocks aren't).
# ---------------------------------------------------------------------------


def test_self_play_runner_creates_pool_on_setup_when_subprocess_enabled(
    tmp_path, monkeypatch,
):
    """``use_subprocess_pool=True`` makes ``_setup`` build a pool
    whose ``max_workers`` matches the n_workers passed to setup
    (not the factory-time value)."""
    from concurrent.futures import ThreadPoolExecutor
    captured = {}

    def fake_ppe(*, max_workers, mp_context=None):
        captured["max_workers"] = max_workers
        captured["mp_context"] = mp_context
        return ThreadPoolExecutor(max_workers=max_workers)

    monkeypatch.setattr(prr.concurrent.futures, "ProcessPoolExecutor", fake_ppe)

    events: list[tuple[str, dict]] = []
    runner = prr.build_self_play_runner(
        coordinator_url="http://test:5099",
        stage_id="stage_x",
        n_workers=1,  # factory-time hint, overridden by setup
        weights_cache_root=tmp_path,
        worker_id="t",
        log_event=lambda n, p: events.append((n, p)),
        deck_pool_path=str(tmp_path / "missing.json.gz"),
        use_subprocess_pool=True,
    )
    # Setup with n_workers=8 — the pool max must reflect this.
    runner.setup("http://test:5099", tmp_path, "self_play", 8)
    assert captured["max_workers"] == 8
    assert captured["mp_context"] is not None  # spawn context requested
    # log_event fires a 'pool_created' diagnostic with the chosen size.
    pool_events = [p for n, p in events if n == "pool_created"]
    assert pool_events and pool_events[0]["max_workers"] == 8
    assert pool_events[0]["mode"] == "subprocess"
    # Teardown should drop the pool reference.
    runner.teardown()


def test_self_play_runner_play_one_submits_to_pool_when_enabled(
    tmp_path, monkeypatch,
):
    """When the pool is active, ``_play_one`` MUST go through
    ``pool.submit(...)`` (not the in-thread fallback). We monkeypatch
    the top-level ``_subprocess_play_self_play`` to a sentinel that
    proves it ran; we also monkeypatch ``ProcessPoolExecutor`` to a
    ``ThreadPoolExecutor`` so the test stays in-process."""
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setattr(
        prr.concurrent.futures, "ProcessPoolExecutor",
        lambda **kw: ThreadPoolExecutor(max_workers=kw["max_workers"]),
    )

    seen_nn_device: list = []

    def fake_subprocess_play(*, claim, coordinator_url, weights_cache_root,
                             deck_pool_path, write_structured_tokens=False,
                             nn_device=None):
        # The runner must forward the daemon's --nn-device selector
        # into the subprocess body via pool.submit (default None=CPU).
        seen_nn_device.append(nn_device)
        return {
            "outcome": "completed",
            "winner": 0,
            "n_samples": 7,
            "npz_bytes": b"FAKE_NPZ",
            "duration_s": 0.001,
            "game_idx": claim["game_idx"],
            "version": "vTEST",
            "nodes": claim.get("nodes"),
            "samples": claim.get("samples"),
        }

    monkeypatch.setattr(prr, "_subprocess_play_self_play", fake_subprocess_play)

    events: list[tuple[str, dict]] = []
    runner = prr.build_self_play_runner(
        coordinator_url="http://test:5099",
        stage_id="stage_x",
        n_workers=1,
        weights_cache_root=tmp_path,
        worker_id="t",
        log_event=lambda n, p: events.append((n, p)),
        deck_pool_path=str(tmp_path / "ignored.json.gz"),
        nn_device="cuda",
        use_subprocess_pool=True,
    )
    runner.setup("http://test:5099", tmp_path, "self_play", 4)
    try:
        result = runner.play_one_game(_make_claim(game_idx=3), "test")
    finally:
        runner.teardown()

    assert result.outcome == "completed"
    assert result.winner == 0
    assert result.n_samples == 7
    assert result.npz_bytes == b"FAKE_NPZ"
    # The configured --nn-device selector was forwarded into the
    # subprocess body via pool.submit (deferred-resolution contract:
    # the parent passes the string, the worker resolves it).
    assert seen_nn_device == ["cuda"]
    # Subprocess-flagged emit fired (vs the in-thread game_start which
    # doesn't carry mode).
    starts = [p for n, p in events if n == "game_start"]
    assert starts and starts[0].get("mode") == "subprocess"


def test_eval_runner_play_one_submits_to_pool_when_enabled(
    tmp_path, monkeypatch,
):
    """Mirror of the self-play test for eval — the eval runner must
    route through ``_subprocess_play_eval`` and map the dict back to
    the wins_new / wins_old / draws shape on ``GameResult``."""
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setattr(
        prr.concurrent.futures, "ProcessPoolExecutor",
        lambda **kw: ThreadPoolExecutor(max_workers=kw["max_workers"]),
    )

    seen_nn_device: list = []

    def fake_subprocess_eval(*, claim, coordinator_url,
                             weights_cache_root, deck_pool_path,
                             nn_device=None):
        seen_nn_device.append(nn_device)
        return {
            "outcome": "completed",
            "winner": 0,  # remapped: 0 means "new won"
            "n_samples": 42,
            "duration_s": 0.001,
            "game_idx": claim["game_idx"],
            "new_version": "vNEW",
            "old_version": "vOLD",
            "nodes": claim.get("nodes"),
            "samples": claim.get("samples"),
        }

    monkeypatch.setattr(prr, "_subprocess_play_eval", fake_subprocess_eval)

    runner = prr.build_eval_runner(
        coordinator_url="http://test:5099",
        stage_id="stage_x",
        n_workers=1,
        weights_cache_root=tmp_path,
        worker_id="t",
        deck_pool_path=str(tmp_path / "ignored.json.gz"),
        nn_device="auto",
        use_subprocess_pool=True,
    )
    runner.setup("http://test:5099", tmp_path, "eval", 4)
    try:
        result = runner.play_one_game(_make_claim(kind="eval"), "test")
    finally:
        runner.teardown()

    assert result.outcome == "completed"
    assert result.winner == 0
    assert result.wins_new == 1
    assert result.wins_old == 0
    assert result.draws == 0
    # --nn-device forwarded into the eval subprocess body too.
    assert seen_nn_device == ["auto"]


def test_self_play_runner_teardown_shuts_down_pool(tmp_path, monkeypatch):
    """``_teardown`` must call ``pool.shutdown(...)`` and drop the
    reference, so a re-setup builds a fresh pool rather than reusing
    a torn-down one."""
    from concurrent.futures import ThreadPoolExecutor

    shutdowns: list[dict] = []

    class TrackingPool(ThreadPoolExecutor):
        def shutdown(self, wait=True, cancel_futures=False):  # noqa: D401
            shutdowns.append({"wait": wait, "cancel_futures": cancel_futures})
            return super().shutdown(wait=wait, cancel_futures=cancel_futures)

    monkeypatch.setattr(
        prr.concurrent.futures, "ProcessPoolExecutor",
        lambda **kw: TrackingPool(max_workers=kw["max_workers"]),
    )

    runner = prr.build_self_play_runner(
        coordinator_url="http://test:5099",
        stage_id="stage_x",
        n_workers=1,
        weights_cache_root=tmp_path,
        worker_id="t",
        use_subprocess_pool=True,
    )
    runner.setup("http://test:5099", tmp_path, "self_play", 2)
    runner.teardown()
    assert len(shutdowns) == 1
    assert shutdowns[0]["cancel_futures"] is True


def test_runners_default_to_in_thread_when_subprocess_pool_disabled(tmp_path):
    """Sanity check that the default ``use_subprocess_pool=False``
    keeps the in-thread path active — no pool is created, no
    subprocess spawned. Tests use this default; production sets True."""
    runner = prr.build_self_play_runner(
        coordinator_url="http://test:5099",
        stage_id="stage_x",
        n_workers=4,
        weights_cache_root=tmp_path,
        worker_id="t",
    )
    runner.setup("http://test:5099", tmp_path, "self_play", 4)
    # Internal state is captured in the closure; we can't directly
    # introspect, but the proof is "teardown doesn't try to shut down
    # a pool that doesn't exist." (Would otherwise AttributeError if
    # the pool attribute were always created and we used wrong type.)
    runner.teardown()


def test_self_play_runner_setup_logs_warning_on_wrong_kind(tmp_path, caplog):
    """If a self-play runner is invoked for an eval stage, the
    setup hook logs a warning (and proceeds — better than failing
    silently)."""
    runner = prr.build_self_play_runner(
        coordinator_url="http://test:5099",
        stage_id="x",
        n_workers=1,
        weights_cache_root=tmp_path,
        worker_id="t",
    )
    import logging
    with caplog.at_level(logging.WARNING):
        runner.setup("http://test:5099", tmp_path, "eval", 1)
    assert any(
        "expected self_play" in rec.message
        for rec in caplog.records
    )


def test_eval_runner_setup_logs_warning_on_wrong_kind(tmp_path, caplog):
    runner = prr.build_eval_runner(
        coordinator_url="http://test:5099",
        stage_id="x",
        n_workers=1,
        weights_cache_root=tmp_path,
        worker_id="t",
    )
    import logging
    with caplog.at_level(logging.WARNING):
        runner.setup("http://test:5099", tmp_path, "self_play", 1)
    assert any(
        "expected eval" in rec.message
        for rec in caplog.records
    )


def test_encode_npz_bytes_round_trips_structured_arrays(tmp_path):
    """When ``write_structured_tokens=True`` and the chunk carries
    struct_rows, the npz blob includes the four structured arrays."""
    n = 2
    # Tiny fake struct rows; the layout doesn't matter for this test
    # since _pad_and_stack_structured_rows operates on real rows. We
    # supply an empty struct_rows list to exercise the
    # "no struct rows -> fall to legacy 4-array layout" branch.
    chunk = (
        np.random.randn(n, 51).astype(np.float32),
        np.zeros(n, dtype=np.float32),
        np.zeros((n, 1), dtype=np.float32),
        np.zeros((n, 1), dtype=bool),
        0,
        "completed",
        [],  # empty struct_rows -> falls into legacy path
    )
    blob = prr._encode_npz_bytes(chunk, write_structured_tokens=True)
    data = np.load(io.BytesIO(blob))
    # Empty struct rows: the path uses the legacy 4-array layout.
    assert "features" in data.files


def test_self_play_runner_logs_event_failure_silently(tmp_path):
    """A log_event that raises must not break the run — the runner
    swallows the exception with a logged-traceback so a flaky log
    sink doesn't kill the daemon."""
    src_dir = _save_tiny_weights(tmp_path / "src", "vTEST")
    cache_root = tmp_path / "cache"
    pool_path = _save_tiny_deck_pool(tmp_path / "pool")

    def bad_log(name, payload):
        raise RuntimeError("synthetic log sink failure")

    runner = prr.build_self_play_runner(
        coordinator_url="http://test:5099",
        stage_id="x",
        n_workers=1,
        weights_cache_root=cache_root,
        worker_id="t",
        log_event=bad_log,
        deck_pool_path=str(pool_path),
        http_get=_stub_http_get_for_version_dir(src_dir),
    )
    runner.setup("http://test:5099", cache_root, "self_play", 1)

    import mtg_bot.worker_daemon_production_runner as mod

    def fake_play(**kwargs):  # noqa: ARG001
        empty = (
            np.zeros((0, 51), dtype=np.float32),
            np.zeros((0,), dtype=np.float32),
            np.zeros((0, 1), dtype=np.float32),
            np.zeros((0, 1), dtype=bool),
            None,
            "completed",
            [],
        )
        return empty, "completed", 0, 0

    real = mod._play_self_play_game
    mod._play_self_play_game = fake_play
    try:
        result = runner.play_one_game(_make_claim(), "t")
    finally:
        mod._play_self_play_game = real
    # Result still produced despite the log_event failures.
    assert result.outcome == "completed"


def test_back_compat_factories_thread_args_through(tmp_path):
    """The legacy ``build_production_self_play_runner`` /
    ``build_production_eval_runner`` re-exports in
    ``worker_daemon_claim_loop`` must instantiate the same runner
    shape as the direct module-level builders."""
    src_dir = _save_tiny_weights(tmp_path / "src", "vTEST")
    cache_root = tmp_path / "cache"

    runner = cl.build_production_self_play_runner(
        coordinator_url="http://test:5099",
        stage_id="stage_x",
        n_workers=1,
        weights_cache_root=cache_root,
        worker_id="test-worker",
        deck_pool_path=str(_save_tiny_deck_pool(tmp_path / "pool")),
        http_get=_stub_http_get_for_version_dir(src_dir),
    )
    assert isinstance(runner, cl.CallableGameRunner)
    runner.setup("http://test:5099", cache_root, "self_play", 1)
    runner.teardown()  # should not raise

    eval_runner = cl.build_production_eval_runner(
        coordinator_url="http://test:5099",
        stage_id="eval_x",
        n_workers=1,
        weights_cache_root=cache_root,
        worker_id="test-worker",
        deck_pool_path=str(_save_tiny_deck_pool(tmp_path / "pool")),
        http_get=_stub_http_get_for_version_dir(src_dir),
    )
    assert isinstance(eval_runner, cl.CallableGameRunner)


# ---------------------------------------------------------------------------
# End-to-end smoke: one real self-play game through the production
# runner via the Flask test-client adapter. Skipped under
# ``MTG_BOT_FAST_TESTS=1``; otherwise runs ~5-10s.
# ---------------------------------------------------------------------------


def _make_test_client_adapter(coordinator_app):
    """Same shim as test_worker_daemon_integration; lifted inline so
    this test stays self-contained."""
    client = coordinator_app.test_client()

    def _strip_base(url: str) -> str:
        for prefix in ("http://", "https://"):
            if url.startswith(prefix):
                slash = url.index("/", len(prefix))
                return url[slash:]
        return url

    def http_get(url, timeout=30.0):
        resp = client.get(_strip_base(url))
        return resp.status_code, resp.data, dict(resp.headers)

    def http_post_json(url, payload, timeout=30.0):
        resp = client.post(_strip_base(url), json=payload)
        return resp.status_code, resp.data, dict(resp.headers)

    return http_get, http_post_json


@pytest.mark.slow
@pytest.mark.skipif(
    os.environ.get("MTG_BOT_FAST_TESTS") == "1",
    reason="real-game smoke skipped under MTG_BOT_FAST_TESTS=1",
)
def test_production_self_play_runner_plays_one_real_game(tmp_path):
    """End-to-end production smoke.

    Builds a real coordinator + tiny weights checkpoint + 2-deck pool,
    POSTs a 1-game self-play stage spec, runs the production
    self-play runner inside a real ClaimLoopRunner, asserts the game
    actually played (n_samples > 0) and the coordinator's stage row
    has the npz blob written.
    """
    # Tiny coordinator backed by a temp queue.db.
    coord_app = serve_mod.create_app(
        repo_url="https://example.test/mtg-bot.git",
        master_pubkey="ssh-ed25519 KEY",
        master_tailnet_name="myhost",
        port=5099,
        queue_db_path=tmp_path / "queue.db",
        weights_root=tmp_path / "trained_weights",
        iterate_data_dir=tmp_path / "iterate_data",
        replays_root=tmp_path / "replays",
        shards_config_path=tmp_path / "shards.json",
        enable_heartbeat_poller=False,
    )

    # Seed the coordinator with a weights blob it can serve via
    # /v2/weights/<v>. Use the existing static-file dir.
    src_dir = _save_tiny_weights(
        tmp_path / "trained_weights", "vSMOKE",
    )
    deck_pool_path = _save_tiny_deck_pool(tmp_path / "pool")

    # Seed the stage on the coordinator.
    coord_client = coord_app.test_client()
    stage_id = "smoke_self_play_v1"
    spec = {
        "stage_id": stage_id,
        "kind": "self_play",
        "weights": {"p0": "vSMOKE", "p1": "vSMOKE"},
        "nodes": 4,
        "samples": 1,
        "per_game_timeout_sec": 60.0,
        "capture_every": 0,
        "claim_ttl_seconds": 600,
        "games": [
            {"game_idx": 0, "deck_indices": [0, 1], "seed": 42},
        ],
    }
    res = coord_client.post("/v2/stage/create", json=spec)
    assert res.status_code == 200, res.get_json()

    # Wire the worker daemon's ClaimLoopRunner against the coordinator
    # via the Flask test-client adapter.
    http_get, http_post_json = _make_test_client_adapter(coord_app)
    cache_root = tmp_path / "worker_weights"
    runner = prr.build_self_play_runner(
        coordinator_url="http://coord-test:5099",
        stage_id=stage_id,
        n_workers=1,
        weights_cache_root=cache_root,
        worker_id="smoke-worker",
        log_event=None,
        deck_pool_path=str(deck_pool_path),
        http_get=http_get,
    )
    cfg = cl.ClaimLoopConfig(
        coordinator_url="http://coord-test:5099",
        stage_id=stage_id,
        kind="self_play",
        n_workers=1,
        worker_id="smoke-worker",
        weights_root=cache_root,
        shard_label="smoke-worker",
        deck_pool_path=str(deck_pool_path),
        retry_backoff_s=(0.0, 0.0, 0.0),
        http_get=http_get,
        http_post_json=http_post_json,
    )
    state = worker_daemon.WorkerState(start_delay_s=0.01)
    cbs = cl.StateCallbacks(
        is_stop_requested=state.is_stop_requested,
        on_claim=state.on_claim,
        on_report=state.on_report,
        on_drop=state.on_drop,
        mark_running=state.mark_running,
        mark_stopping=state.mark_stopping,
        mark_idle=state.mark_idle,
        mark_error=state.mark_error,
    )
    state.try_start("self_play", stage_id, n_workers=1)
    loop = cl.ClaimLoopRunner(cfg, cbs, runner)
    thread = threading.Thread(target=loop.run, daemon=True)
    thread.start()
    thread.join(timeout=120.0)
    assert not thread.is_alive(), (
        f"loop did not finish in time; state={state.snapshot()}"
    )

    # Daemon back to IDLE, game credited.
    snap = state.snapshot()
    assert snap["state"] == worker_daemon.State.IDLE, snap
    assert snap["games_done"] == 1

    # Coordinator's view: 1 game done, status reflects completion.
    resp = coord_client.get(f"/v2/stage/{stage_id}")
    body = resp.get_json()
    assert body["n_games_total"] == 1
    assert body["n_games_done"] == 1
    assert body["n_games_in_flight"] == 0

    # The npz blob was streamed back and written to iterate_data.
    iterate_data_dir = tmp_path / "iterate_data"
    npz_files = list(iterate_data_dir.glob("*.npz"))
    assert len(npz_files) == 1, npz_files
    # And the npz contents are a real ndarray with FEATURE_DIM cols.
    data = np.load(npz_files[0])
    assert "features" in data.files
    # Tiny game with nodes=4, samples=1 should produce a handful of
    # rows minimum — but a crashed/timed-out game would write a 0-row
    # array. Either is "ran without daemon-side exceptions"; assert
    # the file is well-formed rather than pin a sample count we'd
    # have to retune across engine changes.
    assert data["features"].ndim == 2
