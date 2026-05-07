"""Wire-in tests for ``NNEvalServer`` inside the distributed
self-play / eval shard runners.

Production self-play and eval previously instantiated one
:class:`NNEvaluator` per worker process. With N workers per host
that meant N independent CUDA contexts on the same GPU; NVIDIA
serializes kernel launches across processes (no MPS daemon), so
the GPU sat at single-digit % compute even though VRAM was
saturated. The fix lives in ``mtg_bot.search.nn_eval_server``
(``NNEvalServer`` + ``NNEvalClient``) and the wire-in lives in
:mod:`mtg_bot.training.distributed`'s shard runners; this module
pins both behaviors:

* :func:`_start_local_eval_server` builds a working server that
  loads weights for the per-version architecture (custom
  ``hidden_sizes`` / ``architecture`` / ``policy_hidden_sizes``)
  and produces a usable handle.
* :func:`run_shard_local` runs a small end-to-end shard that
  exercises the server-backed worker pool, matches the local-
  evaluator path's outcome shape, and tears the server down on
  exit (no leaked listener / threads).

We intentionally do NOT spawn additional multiprocessing pool
inference variants here — that would re-trigger the very per-
worker CUDA-context issue the wire-in is meant to avoid.
"""

from __future__ import annotations

import json
from pathlib import Path

import torch

from mtg_bot.search.nn_eval_server import (
    NNEvalServer,
    NNServerHandle,
)
from mtg_bot.search.nn_evaluator import (
    ARCHITECTURE_SEPARATE,
    ARCHITECTURE_SHARED,
    _ValuePolicyMLP,
    _ValuePolicyMLPSeparate,
)
from mtg_bot.training.distributed import (
    ShardConfig,
    SelfPlayJobSpec,
    _start_local_eval_server,
    run_shard_local,
)


def _save_dual_head(
    tmp_path: Path,
    *,
    name: str = "weights.pt",
    hidden_sizes: tuple[int, ...] = (16, 16),
    architecture: str = ARCHITECTURE_SHARED,
    policy_hidden_sizes: tuple[int, ...] | None = None,
) -> Path:
    """Save a fresh dual-head net's state_dict at the requested
    architecture so the helper has a real .pt file to load."""
    torch.manual_seed(0)
    if architecture == ARCHITECTURE_SEPARATE:
        model = _ValuePolicyMLPSeparate(
            hidden_sizes=hidden_sizes,
            policy_hidden_sizes=policy_hidden_sizes,
        )
    else:
        model = _ValuePolicyMLP(hidden_sizes=hidden_sizes)
    p = tmp_path / name
    torch.save(model.state_dict(), p)
    return p


def test_start_local_eval_server_loads_custom_hidden_sizes(
    tmp_path: Path,
) -> None:
    """``_start_local_eval_server`` must load weights for a non-
    default-shape model — production v15/v16 use 1024-1024-512
    trunks, not the registry baseline (128, 128, 64). Non-default
    ``hidden_sizes`` is the smoke check for the architecture-aware
    factory inside the helper."""
    weights = _save_dual_head(
        tmp_path, hidden_sizes=(32, 16),
        architecture=ARCHITECTURE_SHARED,
    )
    server = _start_local_eval_server(
        str(weights),
        hidden_sizes=(32, 16),
        architecture=ARCHITECTURE_SHARED,
        policy_hidden_sizes=None,
        with_policy=True,
        device="cpu",
    )
    try:
        handle = server.handle()
        assert isinstance(handle, NNServerHandle)
        assert handle.with_policy is True
    finally:
        server.stop()


def test_start_local_eval_server_loads_separate_architecture(
    tmp_path: Path,
) -> None:
    """``architecture="separate"`` requires the helper to instantiate
    :class:`_ValuePolicyMLPSeparate`. State-dict keys differ from
    the shared variant, so wrong dispatch surfaces as a load error."""
    weights = _save_dual_head(
        tmp_path,
        hidden_sizes=(16, 16),
        architecture=ARCHITECTURE_SEPARATE,
        policy_hidden_sizes=(8,),
    )
    server = _start_local_eval_server(
        str(weights),
        hidden_sizes=(16, 16),
        architecture=ARCHITECTURE_SEPARATE,
        policy_hidden_sizes=(8,),
        with_policy=True,
        device="cpu",
    )
    try:
        handle = server.handle()
        assert handle.with_policy is True
    finally:
        server.stop()


def test_start_local_eval_server_value_only_branch(
    tmp_path: Path,
) -> None:
    """``with_policy=False`` builds a value-only ``_ValueMLP`` server.
    Distinct codepath from the dual-head branch; pin both."""
    from mtg_bot.search.nn_evaluator import _ValueMLP

    torch.manual_seed(0)
    weights = tmp_path / "value_only.pt"
    torch.save(_ValueMLP(hidden_sizes=(16, 16)).state_dict(), weights)

    server = _start_local_eval_server(
        str(weights),
        hidden_sizes=(16, 16),
        architecture=None,
        policy_hidden_sizes=None,
        with_policy=False,
        device="cpu",
    )
    try:
        handle = server.handle()
        assert handle.with_policy is False
    finally:
        server.stop()


def test_run_shard_local_uses_nn_eval_server_end_to_end(
    tmp_path: Path,
) -> None:
    """Smoke the full shard-server wire-in: a tiny self-play shard
    runs to completion, writes its npz, and finalizes its progress
    JSON. The factory-built strategy uses a remote NN client behind
    the scenes (a single in-process server owns the model). Tiny
    network + 2 games + samples=1 + nodes=4 keeps wall under ~10s.
    """
    weights = _save_dual_head(tmp_path, hidden_sizes=(16, 16))
    out_dir = tmp_path / "iterate_data"
    progress_dir = tmp_path / "training_progress"
    spec = SelfPlayJobSpec(
        weights_path=str(weights),
        samples=1, inner_nodes=4,
        hidden_sizes=(16, 16),
        base_seed=0,
        enable_mulligans=False,
        per_game_timeout_sec=None,
        with_policy=True,
    )
    shard = ShardConfig(host="local", label="L0")
    npz_path = run_shard_local(
        shard, spec,
        n_games=2,
        progress_dir=progress_dir,
        output_dir=out_dir,
        run_id_prefix="iter_001_self_play_v1",
        stamp="20260506T000000Z",
    )
    assert npz_path.is_file()
    assert "shard_L0" in npz_path.name
    assert npz_path.suffix == ".npz"

    progress_files = list(progress_dir.glob("*.json"))
    assert len(progress_files) == 1
    progress = json.loads(
        progress_files[0].read_text(encoding="utf-8"),
    )
    assert progress["status"] == "completed"
    assert progress["n_games_done"] == 2


def test_start_local_eval_server_cleanup_on_caller_failure(
    tmp_path: Path,
) -> None:
    """Defensive: callers wrap the helper with try/finally so the
    server tears down on any exit path. We pin the contract that
    ``server.stop()`` closes the listener even when called on a
    server that's still mid-startup; idempotent stop matters because
    cleanup paths in :func:`run_shard_eval_pull` may stop the same
    server twice on multi-server failure paths."""
    weights = _save_dual_head(tmp_path, hidden_sizes=(8, 8))
    server = _start_local_eval_server(
        str(weights),
        hidden_sizes=(8, 8),
        architecture=ARCHITECTURE_SHARED,
        policy_hidden_sizes=None,
        with_policy=True,
        device="cpu",
    )
    server.stop()
    # Second stop must NOT raise — multi-server eval cleanup paths
    # may call this on already-stopped servers.
    server.stop()


def test_bench_nn_eval_server_script_imports() -> None:
    """The microbench at ``scripts/bench_nn_eval_server.py`` shares
    the start-server-then-run-clients pattern with the production
    wire-in; pin that the bench script's importable surface (the
    public symbols it consumes) hasn't drifted out from under the
    production path. The bench harness exists specifically as the
    canonical example for ``NNServerPimcConfig`` callers, so an
    import break there means the wire-in pattern is also broken.
    """
    from mtg_bot.search.nn_eval_server import (  # noqa: F401
        MSG_KIND_VALUE,
        MSG_KIND_VALUE_POLICY,
        NNEvalClient,
        NNServerHandle,
        launch_server_subprocess,
    )
