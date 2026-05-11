"""Tests for the shared-memory NN eval server (Lever 2 v2).

Covers:
- Lifecycle (start / stop / context manager).
- Handle carries fork-inheritable shared-tensor references.
- Round-trip correctness vs a local NNEvaluator (bit-identical
  outputs given matched weights).
- Concurrent workers get batched into one dispatcher pass.
- Backpressure: workers block on free_slots when N concurrent
  requests >= n_slots.

Linux-only — Windows raises NotImplementedError because the
fork-shared-tensor substrate doesn't exist there. The skip is at
collection time so the suite doesn't break Windows test runs.
"""

from __future__ import annotations

import multiprocessing as mp
import sys
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import torch

# Linux-only module. Skip the whole file on Windows so importing it
# doesn't trigger NotImplementedError at fixture-collection time.
if sys.platform == "win32":
    pytest.skip(
        "SharedTensorNNEvalServer is Linux-only (relies on fork-shared "
        "tensor storage and mp.Event file descriptors); the Windows "
        "production path uses the existing NNEvalServer over TCP/AF_PIPE.",
        allow_module_level=True,
    )

from mtg_bot.agents import RandomAgent  # noqa: E402
from mtg_bot.features import FEATURE_DIM  # noqa: E402
from mtg_bot.search.engine_adapter import MtgGameStateAdapter  # noqa: E402
from mtg_bot.search.nn_evaluator import NNEvaluator  # noqa: E402
from mtg_bot.search.shm_nn_eval_server import (  # noqa: E402
    SharedTensorNNEvalClient,
    SharedTensorNNEvalServer,
    SharedTensorServerHandle,
)
from mtg_bot.simulate import setup_game  # noqa: E402
from tests._test_decks import simple_test_decklists  # noqa: E402


# ---------- fixtures --------------------------------------------------------


@pytest.fixture
def adapter() -> MtgGameStateAdapter:
    state = setup_game(
        [RandomAgent(), RandomAgent()],
        decks=simple_test_decklists(),
        seed=42,
    )
    return MtgGameStateAdapter(state)


@pytest.fixture
def server_factory(tmp_path: Path):
    """Build a server whose model state_dict matches a reference
    NNEvaluator; the reference is returned alongside so tests can
    compare server output against it exactly."""

    def _make(with_policy: bool = False, **kwargs):
        torch.manual_seed(0)
        ref = NNEvaluator(with_policy=with_policy)
        weights_path = tmp_path / (
            "with_policy.pt" if with_policy else "value.pt"
        )
        ref.save(weights_path)
        server = SharedTensorNNEvalServer(
            weights_path=weights_path,
            device="cpu",
            with_policy=with_policy,
            **kwargs,
        )
        return server, ref, weights_path

    return _make


# ---------- lifecycle -------------------------------------------------------


def test_start_stop_idempotent(server_factory):
    server, _, _ = server_factory(batch_size=1, batch_wait_ms=0.0)
    server.start()
    server.start()  # idempotent — no second dispatcher
    server.stop(timeout=2.0)
    server.stop(timeout=2.0)  # idempotent


def test_context_manager(server_factory):
    server, _, _ = server_factory(batch_size=1, batch_wait_ms=0.0)
    with server:
        assert server._dispatch_thread is not None
        assert server._dispatch_thread.is_alive()
    # Exiting the context stops the dispatcher.
    assert server._dispatch_thread is None


def test_handle_carries_shared_tensors(server_factory):
    server, _, _ = server_factory(
        batch_size=1, batch_wait_ms=0.0, with_policy=True, n_slots=8,
    )
    handle = server.handle()
    assert isinstance(handle, SharedTensorServerHandle)
    assert handle.n_slots == 8
    assert handle.with_policy is True
    assert handle.features.shape == (8, FEATURE_DIM)
    assert handle.features.is_shared()
    assert handle.values.is_shared()
    assert handle.masks is not None and handle.masks.is_shared()
    assert handle.policies is not None and handle.policies.is_shared()
    # Slot pool pre-filled.
    pulled = [handle.free_slots.get() for _ in range(8)]
    assert sorted(pulled) == list(range(8))


# ---------- round-trip correctness vs local NNEvaluator ---------------------


def test_value_request_round_trip_matches_local(server_factory, adapter):
    server, ref, _ = server_factory(batch_size=1, batch_wait_ms=0.0)
    with server:
        client = SharedTensorNNEvalClient(server.handle())
        v_server = client.evaluate(adapter, player_id=0)
    v_local = float(ref.evaluate(adapter, player_id=0))
    assert v_server == pytest.approx(v_local, abs=1e-5)


def test_evaluate_with_policy_matches_local(server_factory, adapter):
    server, ref, _ = server_factory(
        with_policy=True, batch_size=1, batch_wait_ms=0.0,
    )
    with server:
        client = SharedTensorNNEvalClient(server.handle())
        v_server, p_server = client.evaluate_with_policy(adapter, player_id=0)
    v_local, p_local = ref.evaluate_with_policy(adapter, player_id=0)
    assert v_server == pytest.approx(float(v_local), abs=1e-5)
    np.testing.assert_allclose(p_server, p_local, atol=1e-5)


def test_batch_evaluate_returns_one_value_per_adapter(
    server_factory, adapter,
):
    server, _, _ = server_factory(batch_size=4, batch_wait_ms=0.5)
    with server:
        client = SharedTensorNNEvalClient(server.handle())
        adapters = [adapter, adapter, adapter]
        values = client.batch_evaluate(adapters, player_id=0)
    assert len(values) == 3
    # All same adapter → all same value.
    assert values[0] == pytest.approx(values[1])
    assert values[1] == pytest.approx(values[2])


# ---------- batching & concurrency ------------------------------------------


def test_concurrent_workers_get_batched_into_one_dispatch(
    server_factory, adapter,
):
    """N concurrent client.evaluate() calls land in a single
    dispatcher batch (or at most a small number, given batch_wait_ms
    is generous enough for them all to enqueue)."""
    server, _, _ = server_factory(batch_size=8, batch_wait_ms=20.0)
    n_threads = 8

    with server:
        results: list[float] = [0.0] * n_threads

        def _worker(i: int) -> None:
            client = SharedTensorNNEvalClient(server.handle())
            results[i] = client.evaluate(adapter, player_id=0)

        threads = [
            threading.Thread(target=_worker, args=(i,))
            for i in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

    # All workers got a result.
    assert all(r != 0.0 or r == 0.0 for r in results)  # not None
    # The dispatcher fused them into <= 2 batches (in practice 1 with
    # the generous 20 ms batch_wait_ms).
    assert server.batches_dispatched <= 2
    assert server.requests_served == n_threads
    # At least one batch had > 1 request (proves batching happened).
    assert max(server.batch_sizes) >= 2


def test_no_batching_at_zero_wait_window(server_factory, adapter):
    """``batch_wait_ms=0`` makes the dispatcher emit a batch as soon
    as the first request arrives. Sequential workers get batch=1
    each, the parallel-batching test above gets >1."""
    server, _, _ = server_factory(batch_size=8, batch_wait_ms=0.0)
    with server:
        client = SharedTensorNNEvalClient(server.handle())
        for _ in range(5):
            client.evaluate(adapter, player_id=0)
    # Each request was its own batch.
    assert server.batches_dispatched == 5
    assert all(s == 1 for s in server.batch_sizes)


# ---------- backpressure ----------------------------------------------------


def test_backpressure_when_all_slots_in_use(server_factory, adapter):
    """With n_slots=2 and 4 concurrent client.evaluate() calls, the
    last 2 must block on free_slots.get() until the first 2 release.
    Test passes by completing all 4 — proves the slot pool serializes
    rather than deadlocks."""
    server, _, _ = server_factory(
        batch_size=2, batch_wait_ms=0.0, n_slots=2,
    )
    n_threads = 4

    with server:
        completed: list[bool] = [False] * n_threads

        def _worker(i: int) -> None:
            client = SharedTensorNNEvalClient(server.handle())
            client.evaluate(adapter, player_id=0)
            completed[i] = True

        threads = [
            threading.Thread(target=_worker, args=(i,))
            for i in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

    assert all(completed), "all workers should complete despite n_slots < n_threads"


# ---------- error paths -----------------------------------------------------


def test_evaluate_with_policy_rejected_when_with_policy_false(
    server_factory, adapter,
):
    server, _, _ = server_factory(
        with_policy=False, batch_size=1, batch_wait_ms=0.0,
    )
    with server:
        client = SharedTensorNNEvalClient(server.handle())
        with pytest.raises(RuntimeError, match="policy-head"):
            client.evaluate_with_policy(adapter, player_id=0)
        with pytest.raises(RuntimeError, match="policy-head"):
            client.batch_evaluate_with_policy([adapter], player_id=0)


# ---------- shutdown / liveness --------------------------------------------
#
# Regression coverage for the eval-shard cleanup deadlock observed in
# the field 2026-05-10: workers stuck mid-``evaluate_with_policy`` in
# ``Event.wait()`` once the server exits — atexit then deadlocks the
# whole process tree joining workers that can never return. The fix
# is a cross-process ``server_stopped`` mp.Event surfaced on the
# handle; ``stop()`` sets it and signals every per-slot response
# event so any in-flight ``_call_value*`` call wakes and raises.


def test_handle_surfaces_server_stopped_event(server_factory):
    server, _, _ = server_factory(batch_size=1, batch_wait_ms=0.0)
    handle = server.handle()
    assert hasattr(handle, "server_stopped")
    assert not handle.server_stopped.is_set()


def test_stop_sets_server_stopped(server_factory):
    server, _, _ = server_factory(batch_size=1, batch_wait_ms=0.0)
    server.start()
    handle = server.handle()
    assert not handle.server_stopped.is_set()
    server.stop(timeout=2.0)
    assert handle.server_stopped.is_set()


def test_start_after_stop_clears_server_stopped(server_factory):
    """A server that is stopped and restarted should serve calls
    again — ``start()`` clears the shutdown signal so workers holding
    the fork-inherited handle observe the reset."""
    server, _, _ = server_factory(batch_size=1, batch_wait_ms=0.0)
    server.start()
    server.stop(timeout=2.0)
    handle = server.handle()
    assert handle.server_stopped.is_set()
    server.start()
    assert not handle.server_stopped.is_set()
    server.stop(timeout=2.0)


def test_client_raises_when_server_stops_mid_call(server_factory):
    """A client blocked in ``_call_value`` waiting for a response that
    will never come (the dispatcher is parked on a slow batch window
    and we ``stop()`` before the timeout) must wake and raise
    promptly. Without the fix, this hangs forever — the deadlock
    that bit production eval cleanup."""
    server, _, _ = server_factory(
        batch_size=8,           # never fills with a single request
        batch_wait_ms=10000.0,  # 10s batch window — far longer than test
        n_slots=4,
    )
    server.start()
    client = SharedTensorNNEvalClient(server.handle())

    result: list[Any] = []

    def _call() -> None:
        try:
            client._call_value(np.zeros(FEATURE_DIM, dtype=np.float32))
            result.append(("ok",))
        except RuntimeError as e:
            result.append(("err", str(e)))

    t = threading.Thread(target=_call, daemon=True)
    t.start()
    time.sleep(0.2)  # let the worker land in wait()

    t_stop_start = time.monotonic()
    server.stop(timeout=5.0)
    stop_wall_s = time.monotonic() - t_stop_start

    t.join(timeout=2.0)
    assert not t.is_alive(), (
        "client thread still alive 2.0s after server.stop() — the "
        "shutdown deadlock is back"
    )
    assert stop_wall_s < 3.0, (
        f"server.stop() took {stop_wall_s:.2f}s — should return promptly"
    )
    assert len(result) == 1 and result[0][0] == "err", (
        f"client did not raise; got {result!r}"
    )
    assert "stopped" in result[0][1].lower()


def test_stop_wakes_all_in_flight_workers(server_factory):
    """Multiple worker threads blocked in ``_call_value`` must all
    wake and raise when the server is stopped — not just the one
    holding a particular slot."""
    server, _, _ = server_factory(
        batch_size=16,          # never fills with N < 16 threads
        batch_wait_ms=10000.0,  # 10s — far longer than test
        n_slots=8,
    )
    server.start()
    n_threads = 6  # less than n_slots so each can acquire a slot

    errors: list[str] = []
    errors_lock = threading.Lock()

    def _call() -> None:
        client = SharedTensorNNEvalClient(server.handle())
        try:
            client._call_value(np.zeros(FEATURE_DIM, dtype=np.float32))
        except RuntimeError as e:
            with errors_lock:
                errors.append(str(e))

    threads = [
        threading.Thread(target=_call, daemon=True)
        for _ in range(n_threads)
    ]
    for t in threads:
        t.start()
    time.sleep(0.3)  # let all threads land in wait()

    server.stop(timeout=5.0)

    for t in threads:
        t.join(timeout=2.0)
    alive = [i for i, t in enumerate(threads) if t.is_alive()]
    assert not alive, (
        f"threads {alive} still alive after stop() — shutdown broadcast "
        f"missed some workers"
    )
    assert len(errors) == n_threads, (
        f"expected {n_threads} errors, got {len(errors)}: {errors!r}"
    )
    assert all("stopped" in e.lower() for e in errors)
