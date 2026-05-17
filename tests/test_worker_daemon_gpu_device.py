"""Plumbing tests for the opt-in GPU NN-eval device flag
(``feature/worker-daemon-gpu-device``).

These tests exercise ONLY the device-selector PLUMBING — they assert
that the value flows ``--nn-device`` → argparse → ``main`` resolution
→ ``create_app`` → ``ClaimLoopConfig`` → the production-runner builders
→ ``_build_nn_pimc_config`` → the ``NNPimcConfig`` the runner builds.
They do NOT require a GPU and they never execute CUDA: the deferred
``"auto"`` / ``"cuda"`` sentinel is resolved per-worker inside
``NNPimcConfig.build()`` (which runs in the PPE subprocess), so
asserting ``cfg.device`` proves the wiring without touching the torch
CUDA driver on the test process.

The critical invariant under test is the OPT-IN guarantee: the
default (``--nn-device cpu`` → resolved ``None``) leaves the built
``NNPimcConfig.device`` exactly as it was before this flag existed
(``None``), so every non-GPU worker and the entire existing test
suite are byte-unaffected.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import torch

from mtg_bot import worker_daemon
from mtg_bot import worker_daemon_claim_loop as cl
from mtg_bot import worker_daemon_production_runner as prr
from mtg_bot.search.nn_evaluator import _ValuePolicyMLP
from mtg_bot.training import NNPimcConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _save_tiny_weights(tmp_path: Path, version: str = "vTEST") -> Path:
    """Save a tiny dual-head net + matching metadata.json under
    ``<tmp_path>/<version>/``. Returns the version dir."""
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
    """Write a 2-deck pool the runner can index by ``deck_indices``."""
    import gzip
    import sys

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


def _stub_http_get_for_version_dir(version_dir: Path):
    def http_get(url, timeout=30.0):
        if url.endswith("/metadata"):
            return 200, (version_dir / "metadata.json").read_bytes(), {}
        return 200, (version_dir / "weights.pt").read_bytes(), {}

    return http_get


# ---------------------------------------------------------------------------
# Layer 1: _build_nn_pimc_config — the innermost seam
# ---------------------------------------------------------------------------


def _minimal_metadata() -> dict:
    return {
        "action_encoding_version": "positional_v1",
        "training": {
            "with_policy": True,
            "hidden_sizes": [16, 16],
            "architecture": "shared",
        },
    }


def test_build_nn_pimc_config_default_device_is_none_byte_identical():
    """OPT-IN guarantee: with no ``device`` argument the built
    ``NNPimcConfig.device`` is ``None`` — EXACTLY the value the
    function hardcoded before this flag existed. This is the
    assertion that proves the existing test suite + every non-GPU
    worker are byte-unaffected."""
    cfg = prr._build_nn_pimc_config(
        Path("weights.pt"), _minimal_metadata(),
    )
    assert cfg.device is None


@pytest.mark.parametrize("device", ["cuda", "auto"])
def test_build_nn_pimc_config_threads_device_verbatim(device):
    """``cuda`` / ``auto`` are carried straight onto
    ``NNPimcConfig.device`` UNRESOLVED — no ``auto_device()`` call,
    no CUDA probe in this (parent) process. ``build()`` resolves it
    per-worker."""
    cfg = prr._build_nn_pimc_config(
        Path("weights.pt"), _minimal_metadata(), device=device,
    )
    assert cfg.device == device


def test_build_nn_pimc_config_explicit_none_matches_default():
    """Passing ``device=None`` explicitly is identical to the default
    (the ``--nn-device cpu`` → ``None`` resolution path)."""
    cfg = prr._build_nn_pimc_config(
        Path("weights.pt"), _minimal_metadata(), device=None,
    )
    assert cfg.device is None


def test_build_nn_pimc_config_does_not_probe_cuda(monkeypatch):
    """Hard guarantee: building the config (even with device='cuda')
    must NOT call ``torch.cuda.is_available()`` / ``auto_device()`` in
    the daemon parent. Priming the CUDA driver here is exactly what
    breaks Windows-spawn / Linux-fork per-worker context init."""
    import mtg_bot.training.trainer as trainer_mod

    def _boom():  # pragma: no cover - must never be called
        raise AssertionError(
            "auto_device() called in the daemon parent — this primes "
            "CUDA before the subprocess pool spawns and is the exact "
            "bug the deferred sentinel pattern exists to prevent."
        )

    monkeypatch.setattr(trainer_mod, "auto_device", _boom)
    # cuda/auto must still thread through without resolving.
    for device in ("cuda", "auto", None):
        cfg = prr._build_nn_pimc_config(
            Path("weights.pt"), _minimal_metadata(), device=device,
        )
        assert cfg.device == device


# ---------------------------------------------------------------------------
# Layer 2: the production-runner builders thread nn_device into the
# cached NNPimcConfig the runner actually builds.
# ---------------------------------------------------------------------------


def _capture_built_config(monkeypatch) -> list:
    """Monkeypatch ``_build_nn_pimc_config`` to record the ``device``
    kwarg it was called with while still returning a real config."""
    seen: list = []
    real = prr._build_nn_pimc_config

    def spy(weights_path, metadata, *, device=None):
        seen.append(device)
        return real(weights_path, metadata, device=device)

    monkeypatch.setattr(prr, "_build_nn_pimc_config", spy)
    return seen


def test_self_play_builder_default_threads_none(tmp_path, monkeypatch):
    """``build_self_play_runner`` with no ``nn_device`` builds a
    config with ``device=None`` (CPU) — unchanged behavior."""
    src_dir = _save_tiny_weights(tmp_path / "src")
    seen = _capture_built_config(monkeypatch)
    runner = prr.build_self_play_runner(
        coordinator_url="http://test:5099",
        stage_id="stage_x",
        n_workers=1,
        weights_cache_root=tmp_path / "cache",
        worker_id="w",
        deck_pool_path=str(_save_tiny_deck_pool(tmp_path / "pool")),
        http_get=_stub_http_get_for_version_dir(src_dir),
    )
    runner.setup("http://test:5099", tmp_path / "cache", "self_play", 1)
    # Drive _ensure_config via the in-thread path: invoke the private
    # closure indirectly by reaching the cached config through a claim.
    # We only need the config build, so monkeypatch the heavy game body.
    monkeypatch.setattr(
        prr, "_play_self_play_game",
        lambda **kw: (
            (
                __import__("numpy").zeros((0, 51), dtype="float32"),
                __import__("numpy").zeros((0,), dtype="float32"),
                __import__("numpy").zeros((0, 1), dtype="float32"),
                __import__("numpy").zeros((0, 1), dtype=bool),
                None, "completed", [],
            ),
            "completed", 0, 0,
        ),
    )
    claim = {
        "claim_id": "c0", "game_idx": 0, "deck_indices": [0, 1],
        "seed": 1, "kind": "self_play",
        "weights": {"p0": "vTEST", "p1": "vTEST"},
        "nodes": 4, "samples": 1, "per_game_timeout_sec": 60.0,
        "capture_every": 0, "expires_at": "2099-01-01T00:00:00Z",
    }
    runner.play_one_game(claim, "test")
    assert seen == [None]


@pytest.mark.parametrize("nn_device", ["cuda", "auto"])
def test_self_play_builder_threads_nn_device(
    tmp_path, monkeypatch, nn_device,
):
    """``build_self_play_runner(nn_device=...)`` threads the selector
    into the ``NNPimcConfig`` the runner builds — assert the config
    field, NOT that CUDA executes."""
    src_dir = _save_tiny_weights(tmp_path / "src")
    seen = _capture_built_config(monkeypatch)
    runner = prr.build_self_play_runner(
        coordinator_url="http://test:5099",
        stage_id="stage_x",
        n_workers=1,
        weights_cache_root=tmp_path / "cache",
        worker_id="w",
        deck_pool_path=str(_save_tiny_deck_pool(tmp_path / "pool")),
        nn_device=nn_device,
        http_get=_stub_http_get_for_version_dir(src_dir),
    )
    runner.setup("http://test:5099", tmp_path / "cache", "self_play", 1)
    monkeypatch.setattr(
        prr, "_play_self_play_game",
        lambda **kw: (
            (
                __import__("numpy").zeros((0, 51), dtype="float32"),
                __import__("numpy").zeros((0,), dtype="float32"),
                __import__("numpy").zeros((0, 1), dtype="float32"),
                __import__("numpy").zeros((0, 1), dtype=bool),
                None, "completed", [],
            ),
            "completed", 0, 0,
        ),
    )
    claim = {
        "claim_id": "c0", "game_idx": 0, "deck_indices": [0, 1],
        "seed": 1, "kind": "self_play",
        "weights": {"p0": "vTEST", "p1": "vTEST"},
        "nodes": 4, "samples": 1, "per_game_timeout_sec": 60.0,
        "capture_every": 0, "expires_at": "2099-01-01T00:00:00Z",
    }
    runner.play_one_game(claim, "test")
    assert seen == [nn_device]


@pytest.mark.parametrize("nn_device", [None, "cuda", "auto"])
def test_eval_builder_threads_nn_device(tmp_path, monkeypatch, nn_device):
    """``build_eval_runner`` threads ``nn_device`` into BOTH the new
    and old cached configs (one ``_build_nn_pimc_config`` per
    version)."""
    new_dir = _save_tiny_weights(tmp_path / "src", "vNEW")
    old_dir = _save_tiny_weights(tmp_path / "src", "vOLD")
    seen = _capture_built_config(monkeypatch)

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
        worker_id="w",
        deck_pool_path=str(_save_tiny_deck_pool(tmp_path / "pool")),
        nn_device=nn_device,
        http_get=http_get,
    )
    runner.setup("http://test:5099", tmp_path / "cache", "eval", 1)
    monkeypatch.setattr(
        prr, "_play_eval_game", lambda **kw: (0, 5, "completed"),
    )
    claim = {
        "claim_id": "c0", "game_idx": 0, "deck_indices": [0, 1],
        "seed": 1, "kind": "eval",
        "weights": {"new": "vNEW", "old": "vOLD"},
        "nodes": 4, "samples": 1, "per_game_timeout_sec": 60.0,
        "capture_every": 0, "expires_at": "2099-01-01T00:00:00Z",
    }
    runner.play_one_game(claim, "test")
    assert seen == [nn_device, nn_device]


# ---------------------------------------------------------------------------
# Layer 3: ClaimLoopConfig carries nn_device with a back-compat default.
# ---------------------------------------------------------------------------


def test_claim_loop_config_nn_device_defaults_none():
    cfg = cl.ClaimLoopConfig(
        coordinator_url="http://c:5099",
        stage_id="s",
        kind="self_play",
        n_workers=1,
        worker_id="w",
        weights_root=Path("."),
        shard_label="w",
    )
    assert cfg.nn_device is None


def test_claim_loop_config_accepts_nn_device():
    cfg = cl.ClaimLoopConfig(
        coordinator_url="http://c:5099",
        stage_id="s",
        kind="self_play",
        n_workers=1,
        worker_id="w",
        weights_root=Path("."),
        shard_label="w",
        nn_device="cuda",
    )
    assert cfg.nn_device == "cuda"


# ---------------------------------------------------------------------------
# Layer 4: argparse — default cpu, accepts auto/cuda, rejects junk.
# ---------------------------------------------------------------------------


def test_parser_nn_device_defaults_to_cpu():
    parser = worker_daemon._build_parser()
    args = parser.parse_args([])
    assert args.nn_device == "cpu"


@pytest.mark.parametrize("value", ["cpu", "cuda", "auto"])
def test_parser_nn_device_accepts_valid_choices(value):
    parser = worker_daemon._build_parser()
    args = parser.parse_args(["--nn-device", value])
    assert args.nn_device == value


def test_parser_nn_device_rejects_invalid(capsys):
    parser = worker_daemon._build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--nn-device", "tpu"])
    assert "invalid choice" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Layer 4b: _resolve_nn_device — the opt-in invariant in one helper.
# ---------------------------------------------------------------------------


def test_resolve_nn_device_cpu_maps_to_none():
    """THE opt-in invariant: the default 'cpu' resolves to ``None``,
    which is the exact ``device`` value the production runner used
    before this flag existed. Byte-identical for non-GPU workers and
    the existing test suite."""
    assert worker_daemon._resolve_nn_device("cpu") is None


@pytest.mark.parametrize("value", ["cuda", "auto"])
def test_resolve_nn_device_passes_gpu_choices_through(value):
    assert worker_daemon._resolve_nn_device(value) == value


# ---------------------------------------------------------------------------
# Layer 5: create_app stores NN_DEVICE and threads it into the
# ClaimLoopConfig the real runner gets.
# ---------------------------------------------------------------------------


def test_create_app_default_nn_device_is_none():
    app = worker_daemon.create_app(start_delay_s=0.01)
    assert app.config["NN_DEVICE"] is None


@pytest.mark.parametrize("value", ["cuda", "auto"])
def test_create_app_stores_nn_device(value):
    app = worker_daemon.create_app(start_delay_s=0.01, nn_device=value)
    assert app.config["NN_DEVICE"] == value


@pytest.mark.parametrize("nn_device", [None, "cuda", "auto"])
def test_create_app_threads_nn_device_into_claim_loop_config(nn_device):
    """The ``ClaimLoopConfig`` the daemon hands the runner factory
    carries the configured ``nn_device``. We capture it via a runner
    factory that records the cfg and refuses to spawn real work."""
    captured: list = []

    def recording_factory(kind, cfg, cbs):
        captured.append(cfg)
        # Return a no-op runner; we only care about the cfg.
        return cl.CallableGameRunner(
            lambda claim, label: cl.GameResult(
                outcome="completed", winner=None, n_samples=0,
                duration_s=0.0,
            ),
            None,
            None,
        )

    app = worker_daemon.create_app(
        start_delay_s=0.01,
        nn_device=nn_device,
        runner_factory=recording_factory,
    )
    app.testing = True
    client = app.test_client()
    resp = client.post(
        "/v2/start_self_play",
        json={"stage_id": "s1", "coordinator_url": "http://coord:5099"},
    )
    assert resp.status_code == 202
    assert captured, "runner factory was never invoked"
    assert captured[0].nn_device == nn_device
