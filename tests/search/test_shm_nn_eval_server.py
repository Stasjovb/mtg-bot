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


# ---------- batched submit (real batching, not per-state for-loop) ----------
#
# Regression coverage for the Lever 2 investigation finding (PR #45):
# the previous ``batch_evaluate_with_policy`` was a Python for-loop
# over single-slot round-trips, so a worker could have at most one
# request in flight per batch. The new implementation acquires N
# slots, writes all input rows, submits *all* slot indices before
# waiting on any response. The dispatcher sees the N items together
# and fuses them into one (or few) forward passes.


def _terminal_adapter() -> MtgGameStateAdapter:
    """Build a fresh adapter and force it into a terminal state
    (both players at 0 life → state-based actions resolve the game).
    Returns the adapter for use in mixed-batch tests."""
    from mtg_bot.turn import state_based_actions

    state = setup_game(
        [RandomAgent(), RandomAgent()],
        decks=simple_test_decklists(),
        seed=7,
    )
    adapter = MtgGameStateAdapter(state)
    for p in adapter.engine_state.players:
        p.life = 0
    state_based_actions(adapter.engine_state)
    assert adapter.is_terminal()
    return adapter


def test_batched_with_policy_matches_local_for_n_states(
    server_factory, adapter,
):
    """The new batched call must produce bit-for-bit (within float
    epsilon) the same outputs as the legacy NNEvaluator's batched
    call given matched weights. The load-bearing correctness check
    for this PR."""
    server, ref, _ = server_factory(
        with_policy=True, batch_size=8, batch_wait_ms=2.0, n_slots=16,
    )
    adapters = [adapter, adapter, adapter, adapter, adapter]
    with server:
        client = SharedTensorNNEvalClient(server.handle())
        server_results = client.batch_evaluate_with_policy(
            adapters, player_id=0,
        )
    local_results = ref.batch_evaluate_with_policy(adapters, player_id=0)
    assert len(server_results) == len(local_results)
    for (v_s, p_s), (v_l, p_l) in zip(server_results, local_results):
        assert v_s == pytest.approx(float(v_l), abs=1e-5)
        np.testing.assert_allclose(p_s, p_l, atol=1e-5)


def test_batched_value_only_matches_local_for_n_states(
    server_factory, adapter,
):
    """Value-only batched call mirrors the with-policy path."""
    server, ref, _ = server_factory(
        with_policy=False, batch_size=8, batch_wait_ms=2.0, n_slots=16,
    )
    adapters = [adapter] * 5
    with server:
        client = SharedTensorNNEvalClient(server.handle())
        server_values = client.batch_evaluate(adapters, player_id=0)
    local_values = ref.batch_evaluate(adapters, player_id=0)
    assert len(server_values) == len(local_values)
    for v_s, v_l in zip(server_values, local_values):
        assert v_s == pytest.approx(float(v_l), abs=1e-5)


def test_batched_submits_all_slots_before_waiting(server_factory, adapter):
    """The batched call must put all N slot indices on the request
    queue *before* waiting on any response — so the dispatcher fuses
    them into a single batch. Verified via the dispatcher's
    batch_sizes telemetry: with batch_wait_ms generous enough for
    all submits to land in the same window, batch_sizes should show
    one batch of size N (not N batches of size 1)."""
    server, _, _ = server_factory(
        with_policy=True,
        batch_size=8,
        batch_wait_ms=20.0,
        n_slots=16,
    )
    adapters = [adapter] * 6
    with server:
        client = SharedTensorNNEvalClient(server.handle())
        results = client.batch_evaluate_with_policy(adapters, player_id=0)
    assert len(results) == 6
    # The whole point: the dispatcher saw all 6 requests as one batch
    # (or at worst a small handful), NOT as 6 sequential batch=1
    # dispatches.
    assert server.requests_served == 6
    assert max(server.batch_sizes) >= 2, (
        f"batched submit produced no fusion: batch_sizes={server.batch_sizes}"
    )
    # In practice with batch_wait_ms=20 and a CPU dispatcher, all 6
    # land in one batch — but we tolerate <=3 to absorb scheduler
    # variance.
    assert server.batches_dispatched <= 3


def test_batched_preserves_input_order(server_factory):
    """Run a heterogeneous batch by mixing distinct adapter seeds, and
    verify that the position-i output corresponds to the position-i
    input. Without correct indexing, the result list could be
    permuted by slot-allocation order."""
    server, ref, _ = server_factory(
        with_policy=True, batch_size=8, batch_wait_ms=2.0, n_slots=16,
    )
    # Construct adapters that produce distinguishable values so a
    # permutation would be visible.
    adapters = []
    for seed in (1, 2, 3, 4, 5):
        state = setup_game(
            [RandomAgent(), RandomAgent()],
            decks=simple_test_decklists(),
            seed=seed,
        )
        adapters.append(MtgGameStateAdapter(state))
    with server:
        client = SharedTensorNNEvalClient(server.handle())
        batched = client.batch_evaluate_with_policy(adapters, player_id=0)
    # Compare against per-state single calls — the order MUST match
    # the input states' order, not slot order.
    for i, (v_b, p_b) in enumerate(batched):
        v_l, p_l = ref.evaluate_with_policy(adapters[i], player_id=0)
        assert v_b == pytest.approx(float(v_l), abs=1e-5), (
            f"value at position {i} mismatched — likely a "
            f"slot-vs-index ordering bug"
        )
        np.testing.assert_allclose(p_b, p_l, atol=1e-5)


def test_batched_with_policy_handles_mixed_terminal_states(
    server_factory, adapter,
):
    """Realistic case: an MCTS batch can contain terminal leaves
    alongside non-terminal ones. Terminal states must short-circuit
    to the synthetic (winner-determined value, all-zeros policy)
    WITHOUT acquiring a slot; non-terminal states must hit the
    server. Order preservation across the mix is what makes the
    indexing correct."""
    server, ref, _ = server_factory(
        with_policy=True, batch_size=8, batch_wait_ms=2.0, n_slots=16,
    )
    terminal = _terminal_adapter()
    # 5 states: terminal, non-term, non-term, terminal, non-term.
    mixed = [terminal, adapter, adapter, terminal, adapter]
    with server:
        client = SharedTensorNNEvalClient(server.handle())
        results = client.batch_evaluate_with_policy(mixed, player_id=0)
    assert len(results) == 5
    # Terminal positions must match the single-call evaluate_with_policy
    # short-circuit: both-zero-life finish is a draw → value 0.0,
    # policy all zeros. (Same value the legacy single-state path
    # returns; cross-verified via the local reference.)
    term_v_ref, term_p_ref = ref.evaluate_with_policy(terminal, 0)
    assert term_v_ref == 0.0
    for i in (0, 3):
        v, p = results[i]
        assert v == pytest.approx(float(term_v_ref), abs=1e-5)
        np.testing.assert_array_equal(p, term_p_ref)
    # Non-terminal positions match the legacy single-state path.
    for i in (1, 2, 4):
        v_b, p_b = results[i]
        v_l, p_l = ref.evaluate_with_policy(mixed[i], 0)
        assert v_b == pytest.approx(float(v_l), abs=1e-5)
        np.testing.assert_allclose(p_b, p_l, atol=1e-5)
    # Critically: only the non-terminal subset hit the server. We
    # had 3 non-terminals; expect 3 requests served.
    assert server.requests_served == 3


def test_batched_value_only_handles_mixed_terminal_states(
    server_factory, adapter,
):
    """Same coverage as the with-policy mix, for the value-only path."""
    server, ref, _ = server_factory(
        with_policy=False, batch_size=8, batch_wait_ms=2.0, n_slots=16,
    )
    terminal = _terminal_adapter()
    mixed = [adapter, terminal, adapter, terminal]
    with server:
        client = SharedTensorNNEvalClient(server.handle())
        results = client.batch_evaluate(mixed, player_id=0)
    assert len(results) == 4
    # Terminal positions: draw (both at 0 life) → 0.0.
    assert results[1] == pytest.approx(0.0)
    assert results[3] == pytest.approx(0.0)
    # Non-terminal positions match local NN.
    local_v = ref.batch_evaluate([adapter], player_id=0)[0]
    assert results[0] == pytest.approx(float(local_v), abs=1e-5)
    assert results[2] == pytest.approx(float(local_v), abs=1e-5)
    # Only 2 non-terminals hit the server.
    assert server.requests_served == 2


def test_batched_empty_states_returns_empty(server_factory):
    """Empty input → empty output, no slot acquisition, no server
    traffic. (Important: don't block on free_slots.get() for zero
    states.)"""
    server, _, _ = server_factory(
        with_policy=True, batch_size=8, batch_wait_ms=2.0, n_slots=16,
    )
    with server:
        client = SharedTensorNNEvalClient(server.handle())
        assert client.batch_evaluate_with_policy([], player_id=0) == []
        assert client.batch_evaluate([], player_id=0) == []
    assert server.requests_served == 0


def test_batched_with_policy_all_terminal_skips_server(
    server_factory,
):
    """A batch consisting entirely of terminal states must return
    immediately without acquiring a single slot — important so that
    a terminal-heavy MCTS frontier doesn't pointlessly serialize on
    the request queue."""
    server, _, _ = server_factory(
        with_policy=True, batch_size=4, batch_wait_ms=2.0, n_slots=4,
    )
    terminal = _terminal_adapter()
    with server:
        client = SharedTensorNNEvalClient(server.handle())
        results = client.batch_evaluate_with_policy(
            [terminal, terminal, terminal], player_id=0,
        )
    assert len(results) == 3
    for v, p in results:
        assert v == pytest.approx(0.0)
        np.testing.assert_array_equal(p, np.zeros_like(p))
    assert server.requests_served == 0


def test_batched_raises_when_request_exceeds_slot_pool(
    server_factory, adapter,
):
    """Backpressure option (a): asking for more states than n_slots
    is a config bug; raise loudly rather than chunk. Production sizes
    n_slots >= MCTS batch_size + N_workers precisely so this never
    fires; the test confirms we catch a misconfiguration."""
    server, _, _ = server_factory(
        with_policy=True, batch_size=2, batch_wait_ms=0.0, n_slots=2,
    )
    with server:
        client = SharedTensorNNEvalClient(server.handle())
        # 3 non-terminal states, pool of 2 → clear error.
        with pytest.raises(RuntimeError, match="slot pool|slots, but"):
            client.batch_evaluate_with_policy(
                [adapter, adapter, adapter], player_id=0,
            )


def test_batched_value_only_raises_when_request_exceeds_slot_pool(
    server_factory, adapter,
):
    server, _, _ = server_factory(
        with_policy=False, batch_size=2, batch_wait_ms=0.0, n_slots=2,
    )
    with server:
        client = SharedTensorNNEvalClient(server.handle())
        with pytest.raises(RuntimeError, match="slot pool|slots, but"):
            client.batch_evaluate(
                [adapter, adapter, adapter], player_id=0,
            )


def test_batched_release_all_slots_on_server_stop_mid_call(
    server_factory, adapter,
):
    """If the server stops while a batched call is mid-await, every
    slot acquired by the call must be returned to the pool so the
    next run doesn't observe a leak. We park the dispatcher on a
    long batch window (batch_wait_ms = 10s, batch_size larger than
    the request) so the call is guaranteed to be waiting at
    ``_await_response`` when we stop the server; then we restart it
    and verify free_slots is full."""
    server, _, _ = server_factory(
        with_policy=True,
        batch_size=16,           # never fills with N < 16
        batch_wait_ms=10000.0,   # 10s window
        n_slots=8,
    )
    server.start()
    client = SharedTensorNNEvalClient(server.handle())

    result: list[Any] = []

    def _call() -> None:
        try:
            client.batch_evaluate_with_policy(
                [adapter, adapter, adapter, adapter], player_id=0,
            )
            result.append(("ok",))
        except RuntimeError as e:
            result.append(("err", str(e)))

    t = threading.Thread(target=_call, daemon=True)
    t.start()
    time.sleep(0.3)  # let the call land in _await_response

    server.stop(timeout=5.0)
    t.join(timeout=3.0)
    assert not t.is_alive(), (
        "batched-call thread did not return after server.stop()"
    )
    assert len(result) == 1 and result[0][0] == "err", (
        f"expected RuntimeError; got {result!r}"
    )

    # All 4 slots that were acquired must have been released.
    # Restart the server and drain free_slots — it should yield all
    # n_slots = 8 indices.
    server.start()
    drained: list[int] = []
    for _ in range(8):
        # Use a timeout so the test fails fast instead of hanging if
        # slots were leaked.
        drained.append(server.handle().free_slots.get(timeout=2.0))
    assert sorted(drained) == list(range(8)), (
        f"slot pool not full after stop+restart; drained={drained}"
    )
    server.stop(timeout=2.0)
