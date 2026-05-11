"""Shared-memory NN eval server (Lever 2 v2).

The original :class:`NNEvalServer` in :mod:`mtg_bot.search.nn_eval_server`
uses Python's ``multiprocessing.connection`` for request/response wire
traffic. That protocol pickles every payload and uses one reader
thread per connection, with serialized GIL-held response writes.
The Phase 6 WSL2 migration bench (PR #39) measured ~2 ms p50 RTT
that floor — regardless of TCP vs UDS transport — because the cost
is in the Python protocol layer, not the socket.

This module replaces that wire protocol with shared-memory tensors:

- The parent allocates fixed-size shared tensors for inputs (features,
  optional mask) and outputs (value, optional policy), N rows each
  ("slots").
- Workers acquire a slot index from a ``free_slots`` mp.Queue (which
  doubles as backpressure: in-flight requests cap at N).
- Worker writes the input row in-place, puts the slot index on the
  ``request_queue``, then waits on a per-slot ``response_event``.
- A single dispatcher thread in the server pulls slot indices off
  ``request_queue`` (batched up to ``batch_size`` over a
  ``batch_wait_s`` window), runs ONE forward over the gathered batch,
  writes outputs back to the corresponding output-slot rows, and
  signals each slot's ``response_event``.
- Worker reads the output row, clears the event, returns the slot to
  ``free_slots``.

Substrate measurement (single client, 1000 iterations on WSL2 Ubuntu
24.04 + Python 3.13.13): p50 round-trip 74 us, vs the existing
mp.connection's 2 ms — ~27x lower per-request overhead. With batching
across multiple workers, aggregate throughput should easily exceed
the per-worker local-NN reference of 1,355 RPS (PR #39 bench).

Constraints:

- Fork-only: the design relies on children inheriting shared-tensor
  storage + mp.Event file descriptors via fork. Spawn-launched
  workers would need explicit re-construction of the shared
  state, which we don't support. On Linux this is fine — the
  production master uses fork after the WSL2 migration. Windows
  is out of scope for this module.
- One server per master process. Multiple instances on the same
  host work but each holds its own slot pool + dispatcher thread.

The API mirrors :class:`NNEvalServer` / :class:`NNEvalClient` so a
PIMC config can swap implementations transparently. Where the two
diverge: this server doesn't take ``address`` (no socket) and the
handle is a Python object holding shared-tensor + event references
that only works across fork (not pickle-across-host).
"""

from __future__ import annotations

import dataclasses
import logging
import multiprocessing as mp
import queue
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Sequence

import numpy as np
import torch

if TYPE_CHECKING:  # pragma: no cover
    from mtg_bot.search.evaluator import Evaluator as _EvaluatorBase
    from mtg_bot.search.types import GameState, PlayerID

# Re-use the model classes from the existing module so we don't
# duplicate the NN definition. Pull in extract_features + Evaluator
# base + action-encoding helpers to mirror NNEvalClient's API exactly.
from mtg_bot.features import FEATURE_DIM, extract_features
from mtg_bot.search.evaluator import Evaluator
from mtg_bot.search.nn_evaluator import (
    HIDDEN_SIZES,
    NNEvaluator,
    _ValueMLP,
    _ValuePolicyMLP,
    _build_dual_head_model,
)


def _action_encoding():
    """Lazy import so the module load doesn't pull in
    mtg_bot.training.action_encoding (a heavy chain via training.config)."""
    from mtg_bot.training import action_encoding as _ae
    return _ae


# Worker-process globals. The "default" handle is the back-compat
# single-server slot used by self-play (``run_shard_pull`` /
# ``mtg_bot bench nn-eval-server --mode shm``). The "by weights_path"
# dict supports the eval case where the master has TWO servers (one
# per weights set) and workers route requests by the cfg's
# ``weights_path``. Both are unset in the master parent and in
# non-SHM workers; :func:`maybe_get_worker_handle` returns ``None``
# in that case, which preserves the legacy ``NNEvaluator`` path.
_WORKER_SHM_DEFAULT_HANDLE: Optional["SharedTensorServerHandle"] = None
_WORKER_SHM_HANDLES_BY_PATH: dict[str, "SharedTensorServerHandle"] = {}


def set_worker_handle(
    handle: Optional["SharedTensorServerHandle"],
    weights_path: Optional[str] = None,
) -> None:
    """Install a fork-inherited SHM server handle on the calling
    worker process. Intended for use as an mp.Pool initializer when
    the master has spun up one or more :class:`SharedTensorNNEvalServer`.

    Two registration shapes:

    - ``weights_path=None`` (default) → install as the "singleton"
      handle, used by callers that don't disambiguate by weights
      path. ``handle=None`` clears it.
    - ``weights_path="...pt"`` → register under the given key so
      ``maybe_get_worker_handle(weights_path)`` returns this handle.
      Used by the eval path where the master holds two servers
      (new + old weights), workers route via the cfg's
      ``weights_path``.
    """
    global _WORKER_SHM_DEFAULT_HANDLE
    if weights_path is None:
        _WORKER_SHM_DEFAULT_HANDLE = handle
    else:
        if handle is None:
            _WORKER_SHM_HANDLES_BY_PATH.pop(weights_path, None)
        else:
            _WORKER_SHM_HANDLES_BY_PATH[weights_path] = handle


def maybe_get_worker_handle(
    weights_path: Optional[str] = None,
) -> Optional["SharedTensorServerHandle"]:
    """Return the worker's SHM handle if one was installed via
    :func:`set_worker_handle`, else ``None``.

    Lookup order:

    1. If ``weights_path`` is provided and matches a registered
       per-path handle, return that. This is the eval path's
       routing key.
    2. Otherwise return the singleton handle (or ``None`` if not
       set). Self-play registers only the singleton; legacy callers
       that don't pass ``weights_path`` continue to work unchanged.
    """
    if weights_path is not None:
        h = _WORKER_SHM_HANDLES_BY_PATH.get(weights_path)
        if h is not None:
            return h
    return _WORKER_SHM_DEFAULT_HANDLE


def clear_worker_handles() -> None:
    """Forget all installed handles. Used by tests to isolate state
    between cases."""
    global _WORKER_SHM_DEFAULT_HANDLE
    _WORKER_SHM_DEFAULT_HANDLE = None
    _WORKER_SHM_HANDLES_BY_PATH.clear()


@dataclasses.dataclass
class SharedTensorServerHandle:
    """Lightweight handle a worker uses to attach to the server.

    All fields are fork-inheritable (mp.Queue, mp.Event lists, shared
    tensors). Do not pickle this handle across processes — pass it
    through fork-inherited references only.
    """
    free_slots: "mp.Queue[int]"
    request_queue: "mp.Queue[int]"
    response_events: list[Any]  # list[mp.Event] — typing imprecise
    # Cross-process shutdown signal. The server sets this in ``stop()``
    # so that workers blocked in ``_call_value*`` notice the server is
    # gone and raise instead of hanging on a response event that will
    # never be signaled. Set once, never reset within a server's
    # lifetime; ``start()`` allocates a fresh handle if reused.
    server_stopped: Any  # mp.Event
    # Cross-process lock serializing the multi-slot acquire phase of
    # ``SharedTensorNNEvalClient._submit_batch``. Without this, N
    # concurrent workers each calling ``free_slots.get()`` in a tight
    # loop can each accumulate partial allocations, exhaust the pool
    # before any worker reaches its full count, and deadlock — the
    # multi-worker contention regression test pins this scenario.
    # The lock only gates the *acquire* phase (microseconds in the
    # uncontended case); writes, submits, waits, and reads all
    # proceed in parallel as before, so dispatcher fusion across
    # workers is unaffected.
    acquire_lock: Any  # mp.synchronize.Lock
    # Shared tensors. ``features``, ``values`` always present;
    # ``masks`` / ``policies`` only when ``with_policy=True``.
    features: torch.Tensor
    values: torch.Tensor
    masks: Optional[torch.Tensor]
    policies: Optional[torch.Tensor]
    with_policy: bool
    n_slots: int
    feature_dim: int
    action_vocab_size: int


class SharedTensorNNEvalServer:
    """A single-server-per-master NN evaluator that batches requests
    from N worker processes via shared memory + mp.Event.

    Lifecycle:

        server = SharedTensorNNEvalServer(weights_path=..., with_policy=True)
        server.start()                 # spawns dispatcher thread
        handle = server.handle()       # pass to workers (fork-inheritable)
        # ... workers do their thing ...
        server.stop()                  # joins dispatcher

    Or as a context manager: ``with server: ...``.
    """

    def __init__(
        self,
        weights_path: Optional[Path] = None,
        *,
        device: Optional[str] = None,
        with_policy: bool = False,
        batch_size: int = 32,
        batch_wait_ms: float = 0.5,
        n_slots: int = 64,
        hidden_sizes: Optional[tuple[int, ...]] = None,
        architecture: Optional[str] = None,
        policy_hidden_sizes: Optional[tuple[int, ...]] = None,
        model_factory: Optional[Any] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        if sys.platform == "win32":
            raise NotImplementedError(
                "SharedTensorNNEvalServer is Linux-only — relies on "
                "fork-inherited shared-tensor storage. Use the existing "
                "NNEvalServer with TCP/UDS on Windows."
            )

        # Deferred CUDA resolution: same pattern as PR #36's fix to
        # NNEvalServer. Don't call torch.cuda.is_available() in any
        # function default or at module import — it primes CUDA on
        # the parent and breaks fork().
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self._device = torch.device(device)
        self._with_policy = with_policy
        self._batch_size = max(1, int(batch_size))
        self._batch_wait_s = max(0.0, float(batch_wait_ms)) / 1000.0
        self._n_slots = max(1, int(n_slots))
        self._logger = logger or logging.getLogger(
            "mtg_bot.search.shm_nn_eval_server"
        )

        # Build the model. Dispatch by ``with_policy`` + ``architecture``
        # the same way NNEvaluator does so the SHM server can host any
        # production-shape weights (1024-trunk dual-head, separate-trunks,
        # value-only). ``hidden_sizes=None`` falls through to the
        # underlying class default (HIDDEN_SIZES) — matches NNEvaluator.
        effective_hidden = (
            tuple(hidden_sizes) if hidden_sizes is not None else HIDDEN_SIZES
        )
        if model_factory is not None:
            self._model = model_factory()
        elif with_policy:
            arch = architecture if architecture is not None else "shared"
            self._model = _build_dual_head_model(
                arch,
                hidden_sizes=effective_hidden,
                policy_hidden_sizes=policy_hidden_sizes,
            )
        else:
            self._model = _ValueMLP(hidden_sizes=effective_hidden)
        if weights_path is not None and model_factory is None:
            state_dict = torch.load(
                weights_path,
                map_location=self._device,
                weights_only=True,
            )
            self._model.load_state_dict(state_dict)
        self._model.to(self._device)
        self._model.eval()

        # Resolve dimensions for slot allocation.
        from mtg_bot.features import FEATURE_DIM
        self._feature_dim = FEATURE_DIM
        if with_policy:
            from mtg_bot.training.action_encoding import ACTION_VOCAB_SIZE
            self._action_vocab_size = ACTION_VOCAB_SIZE
        else:
            self._action_vocab_size = 0

        # Allocate shared tensors. share_memory_() puts the storage
        # on shm (anonymous-mmap on Linux); fork-inherited.
        self._features = torch.zeros(
            self._n_slots, self._feature_dim, dtype=torch.float32,
        ).share_memory_()
        self._values = torch.zeros(
            self._n_slots, 1, dtype=torch.float32,
        ).share_memory_()
        if with_policy:
            self._masks = torch.zeros(
                self._n_slots, self._action_vocab_size, dtype=torch.bool,
            ).share_memory_()
            self._policies = torch.zeros(
                self._n_slots, self._action_vocab_size, dtype=torch.float32,
            ).share_memory_()
        else:
            self._masks = None
            self._policies = None

        # Sync primitives.
        ctx = mp.get_context("fork")
        # ``free_slots`` is the slot allocator. Pre-fill with all N
        # indices. Workers do .get() to acquire and .put() to release.
        self._free_slots: "mp.Queue[int]" = ctx.Queue()
        for i in range(self._n_slots):
            self._free_slots.put(i)
        # ``request_queue`` is the dispatcher's input. Workers put
        # slot_idx after writing the input row.
        self._request_queue: "mp.Queue[int]" = ctx.Queue()
        # Per-slot response events. Worker waits on its slot's event
        # after submitting; server sets it after writing the output.
        self._response_events = [ctx.Event() for _ in range(self._n_slots)]
        # Cross-process shutdown signal — set in ``stop()`` so that
        # any worker mid-``_call_value*`` notices the server is gone
        # and raises ``RuntimeError`` instead of hanging on a response
        # event that will never be signaled. The dispatcher does NOT
        # consult this; the dispatcher's own loop is gated by
        # ``_stop_evt`` (a thread-local event), since the dispatcher
        # lives in the same process as the server.
        self._server_stopped = ctx.Event()
        # Cross-process lock used by clients to serialize the multi-
        # slot acquire phase of ``_submit_batch``. See
        # ``SharedTensorServerHandle.acquire_lock`` for rationale.
        self._acquire_lock = ctx.Lock()

        # Dispatcher state.
        self._stop_evt = threading.Event()
        self._dispatch_thread: Optional[threading.Thread] = None

        # Telemetry.
        self.batches_dispatched = 0
        self.requests_served = 0
        self.batch_sizes: list[int] = []

    # ---- public lifecycle --------------------------------------------------

    def start(self) -> None:
        if self._dispatch_thread is not None:
            return
        self._stop_evt.clear()
        # Clear the cross-process shutdown signal so a restart-after-
        # stop server doesn't immediately fail every client call.
        self._server_stopped.clear()
        self._dispatch_thread = threading.Thread(
            target=self._dispatch_loop,
            name="shm-nn-eval-server-dispatcher",
            daemon=True,
        )
        self._dispatch_thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        if self._dispatch_thread is None:
            return
        # Order matters here. Before joining the dispatcher we must
        # unblock any worker stuck in ``_call_value*`` on a per-slot
        # response event. Otherwise the worker's wait() hangs forever
        # (the dispatcher won't dispatch the slot after we stop) and
        # at process exit ``concurrent.futures.process._python_exit``
        # deadlocks joining the worker proc, which deadlocks joining
        # its own internal threads — observed in the field as a 40+
        # minute hang on eval-shard cleanup.
        # Step 1: tell workers the server is going down so any in-
        # flight call raises after wake.
        self._server_stopped.set()
        # Step 2: signal every per-slot response event. Workers
        # currently in wait() return immediately and check
        # _server_stopped on the next line. Workers about to enter
        # wait() see the event already set and exit the same path.
        for ev in self._response_events:
            try:
                ev.set()
            except Exception:  # noqa: BLE001
                pass
        # Step 3: stop the dispatcher.
        self._stop_evt.set()
        # Wake the dispatcher if it's blocked on the request_queue.
        # Sentinel value -1 (slot indices are always >= 0).
        try:
            self._request_queue.put(-1)
        except Exception:  # noqa: BLE001
            pass
        self._dispatch_thread.join(timeout=timeout)
        self._dispatch_thread = None

    def __enter__(self) -> "SharedTensorNNEvalServer":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()

    def handle(self) -> SharedTensorServerHandle:
        return SharedTensorServerHandle(
            free_slots=self._free_slots,
            request_queue=self._request_queue,
            response_events=self._response_events,
            server_stopped=self._server_stopped,
            acquire_lock=self._acquire_lock,
            features=self._features,
            values=self._values,
            masks=self._masks,
            policies=self._policies,
            with_policy=self._with_policy,
            n_slots=self._n_slots,
            feature_dim=self._feature_dim,
            action_vocab_size=self._action_vocab_size,
        )

    # ---- dispatcher --------------------------------------------------------

    def _dispatch_loop(self) -> None:
        """Drain request_queue, batch up to batch_size, run forward,
        write outputs, signal response events."""
        while not self._stop_evt.is_set():
            try:
                first = self._request_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if first == -1:
                # Stop sentinel.
                return

            batch: list[int] = [first]
            deadline = time.monotonic() + self._batch_wait_s
            while len(batch) < self._batch_size:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    item = self._request_queue.get(timeout=remaining)
                except queue.Empty:
                    break
                if item == -1:
                    # Stop sentinel mid-batch — process what we have,
                    # then exit on next loop.
                    self._request_queue.put(-1)
                    break
                batch.append(item)

            self._dispatch_batch(batch)

    def _dispatch_batch(self, slot_indices: list[int]) -> None:
        """Gather inputs from the shared tensors, run the forward,
        scatter outputs back, signal response events."""
        if not slot_indices:
            return
        idx_tensor = torch.tensor(slot_indices, dtype=torch.long)
        feat_batch = self._features.index_select(0, idx_tensor)
        with torch.no_grad():
            feat_dev = feat_batch.to(self._device)
            if self._with_policy:
                mask_batch = (
                    self._masks.index_select(0, idx_tensor)
                    .to(self._device)
                )
                value_t, policy_logits = self._model(feat_dev)
                # Apply the mask: -inf where mask is False, then softmax.
                neg_inf = torch.tensor(
                    float("-inf"), dtype=policy_logits.dtype,
                    device=self._device,
                )
                masked_logits = torch.where(
                    mask_batch, policy_logits, neg_inf,
                )
                policy = torch.softmax(masked_logits, dim=-1)
                # Write outputs back to the original slots.
                value_cpu = value_t.detach().to(torch.float32).cpu()
                policy_cpu = policy.detach().to(torch.float32).cpu()
                for i, slot in enumerate(slot_indices):
                    self._values[slot, 0] = value_cpu[i].squeeze()
                    self._policies[slot].copy_(policy_cpu[i])
                    self._response_events[slot].set()
            else:
                value_t = self._model(feat_dev)
                if isinstance(value_t, tuple):
                    value_t = value_t[0]
                value_cpu = value_t.detach().to(torch.float32).cpu()
                for i, slot in enumerate(slot_indices):
                    self._values[slot, 0] = value_cpu[i].squeeze()
                    self._response_events[slot].set()

        # Telemetry.
        self.batches_dispatched += 1
        self.requests_served += len(slot_indices)
        self.batch_sizes.append(len(slot_indices))


class SharedTensorNNEvalClient(Evaluator):
    """Drop-in Evaluator that ships requests to a SharedTensorNNEvalServer
    via shared-memory tensors. Public API matches ``NNEvaluator`` /
    ``NNEvalClient`` exactly so PIMC configs can swap implementations
    transparently.

    Constructed in a worker process from a SharedTensorServerHandle
    inherited via fork. Stateless w.r.t. the server — each request
    acquires a slot, writes input rows, signals the server, waits for
    the response event, reads output rows, releases the slot.
    """

    def __init__(self, handle: SharedTensorServerHandle) -> None:
        self._h = handle
        self._with_policy = handle.with_policy

    @property
    def with_policy(self) -> bool:
        return self._with_policy

    # ---- Evaluator API ---------------------------------------------------

    def _evaluate_nonterminal(
        self, state: "GameState", player_id: "PlayerID",
    ) -> float:
        """Concrete implementation of the abstract base method.
        Base class ``Evaluator.evaluate`` handles the terminal short-
        circuit; this method only ever sees non-terminal states.
        Server batches across worker-process boundaries already; the
        slot round-trip is the unit of work."""
        engine = _engine_state(state)
        feats = extract_features(engine, player_id)
        return self._call_value(feats)

    # ``evaluate`` inherits the base-class implementation: terminal
    # short-circuit, then delegate to ``_evaluate_nonterminal``.
    # ``batch_evaluate`` is overridden below to submit all N requests
    # before waiting on any — without this, the dispatcher only ever
    # sees one in-flight request per worker, capping cross-worker
    # fusion at ``N_workers`` instead of ``N_workers * batch_size``.
    # See ``docs/LEVER2_INVESTIGATION_2026_05_10.md`` for the wire-up
    # numbers behind this design.

    def evaluate_with_policy(
        self, state: "GameState", player_id: "PlayerID",
    ) -> tuple[float, np.ndarray]:
        if not self._with_policy:
            raise RuntimeError(
                "evaluate_with_policy requires a policy-head server",
            )
        ae = _action_encoding()
        vocab_size = ae.ACTION_VOCAB_SIZE
        if state.is_terminal():
            winner = state.winner()
            if winner is None:
                value = 0.0
            else:
                value = 1.0 if winner == player_id else -1.0
            return value, np.zeros(vocab_size, dtype=np.float32)
        engine = _engine_state(state)
        feats = extract_features(engine, player_id)
        mask = ae.legal_action_mask(state, player_id)
        return self._call_value_policy(feats, mask)

    def batch_evaluate(
        self, states: "Sequence[GameState]", player_id: "PlayerID",
    ) -> list[float]:
        """Batched value-only evaluation.

        Submits all non-terminal slot indices to the request queue
        *before* waiting on any response, so the dispatcher fuses the
        N requests into one (or few) GPU forward passes. The legacy
        for-loop sent each request as its own round-trip and capped
        each worker's in-flight count at 1 — see the Lever 2
        investigation doc for the wall-time math.

        Terminal states short-circuit per-element to the engine's
        true result (matching ``Evaluator.evaluate``) without touching
        the slot machinery. The returned list preserves input order
        and mixes terminal + non-terminal values transparently.

        Backpressure: if the non-terminal subset exceeds the slot
        pool size, the call automatically chunks into ``ceil(N /
        n_slots)`` sub-batches run sequentially through the existing
        batched-submit path, then concatenates results in input order.
        ``N <= n_slots`` (the production-sized case) is unchanged —
        a single submit, identical to the pre-chunking behavior.
        """
        if not states:
            return []

        # Partition. Terminal states get their value immediately and
        # never acquire a slot. Non-terminal states extract features
        # up front so the slot's I/O window is as tight as possible.
        out: list[float] = [0.0] * len(states)
        nonterminal_indices: list[int] = []
        nonterminal_features: list[np.ndarray] = []
        for i, s in enumerate(states):
            if s.is_terminal():
                winner = s.winner()
                if winner is None:
                    out[i] = 0.0
                else:
                    out[i] = 1.0 if winner == player_id else -1.0
                continue
            engine = _engine_state(s)
            nonterminal_indices.append(i)
            nonterminal_features.append(
                extract_features(engine, player_id),
            )

        if not nonterminal_indices:
            return out

        values, _ = self._call_chunked(
            features=nonterminal_features,
            masks=None,
            vocab_size=0,
        )
        for k, v in enumerate(values):
            out[nonterminal_indices[k]] = v
        return out

    def batch_evaluate_with_policy(
        self, states: "Sequence[GameState]", player_id: "PlayerID",
    ) -> list[tuple[float, np.ndarray]]:
        """Batched (value + policy) evaluation. Same shape as
        :meth:`batch_evaluate`: submit all slot indices, then drain
        responses. See that method for the backpressure rationale.

        Terminal states short-circuit to ``(±1/0, all-zeros policy)``,
        matching the single-state ``evaluate_with_policy`` semantics.
        Result list preserves input order.
        """
        if not self._with_policy:
            raise RuntimeError(
                "batch_evaluate_with_policy requires a policy-head server",
            )
        ae = _action_encoding()
        vocab_size = ae.ACTION_VOCAB_SIZE
        if not states:
            return []

        # Partition. Terminal states get the synthetic (value, zeros)
        # answer immediately; non-terminals are bundled into one
        # batched submit.
        out: list[tuple[float, np.ndarray]] = [
            (0.0, np.zeros(vocab_size, dtype=np.float32))
            for _ in states
        ]
        nonterminal_indices: list[int] = []
        nonterminal_features: list[np.ndarray] = []
        nonterminal_masks: list[np.ndarray] = []
        for i, s in enumerate(states):
            if s.is_terminal():
                winner = s.winner()
                if winner is None:
                    value = 0.0
                else:
                    value = 1.0 if winner == player_id else -1.0
                out[i] = (value, np.zeros(vocab_size, dtype=np.float32))
                continue
            engine = _engine_state(s)
            nonterminal_indices.append(i)
            nonterminal_features.append(
                extract_features(engine, player_id),
            )
            nonterminal_masks.append(
                ae.legal_action_mask(s, player_id),
            )

        if not nonterminal_indices:
            return out

        values, policies = self._call_chunked(
            features=nonterminal_features,
            masks=nonterminal_masks,
            vocab_size=vocab_size,
        )
        for k, v in enumerate(values):
            out[nonterminal_indices[k]] = (v, policies[k])
        return out

    def _call_chunked(
        self,
        *,
        features: list[np.ndarray],
        masks: Optional[list[np.ndarray]],
        vocab_size: int,
    ) -> tuple[list[float], list[np.ndarray]]:
        """Submit ``features`` (and optionally ``masks``) through the
        SHM slot machinery, chunking into sub-batches of at most
        ``self._h.n_slots`` so any oversize request degrades gracefully
        instead of crashing or blocking on a too-small slot pool.

        Returns ``(values, policies)``. ``policies`` is an empty list
        when ``masks is None`` (value-only path); otherwise one
        np.ndarray of length ``vocab_size`` per input row, in input
        order.

        Common case (``N <= n_slots``): one chunk, single submit —
        identical to the pre-chunking path. Only oversize batches
        take the multi-chunk route, which is the rare config-mismatch
        case PR #49 hit before n_slots was bumped.

        Invariants preserved across chunks:
        - Input order: results are appended in the order chunks are
          processed, which iterates ``features``/``masks`` in order.
        - Slot lifecycle: each chunk acquires + writes + submits +
          waits + releases its slots within a ``try/finally`` so
          exceptions (including ``server_stopped`` raised by
          ``_await_response``) don't leak slots.
        - ``server_stopped`` detection: the first sub-batch to hit a
          stopped server raises immediately; subsequent chunks are
          not started.
        """
        n = len(features)
        if masks is not None:
            assert len(masks) == n
        if n == 0:
            return [], []

        chunk_size = min(n, self._h.n_slots)
        values: list[float] = []
        policies: list[np.ndarray] = []

        for start in range(0, n, chunk_size):
            end = min(start + chunk_size, n)
            chunk_features = features[start:end]
            chunk_masks = (
                masks[start:end] if masks is not None else None
            )
            slots = self._submit_batch(
                features=chunk_features,
                masks=chunk_masks,
            )
            try:
                for slot in slots:
                    self._await_response(slot)
                    values.append(
                        float(self._h.values[slot, 0].item())
                    )
                    if masks is not None:
                        assert self._h.policies is not None
                        policies.append(
                            self._h.policies[slot].clone().numpy()
                        )
            finally:
                for slot in slots:
                    self._h.free_slots.put(slot)
        return values, policies

    def _submit_batch(
        self,
        *,
        features: list[np.ndarray],
        masks: Optional[list[np.ndarray]],
    ) -> list[int]:
        """Acquire ``len(features)`` slots, write all input rows, then
        submit every slot index to the request queue.

        The "submit all before waiting on any" ordering is the whole
        point: it gives the dispatcher up to ``len(features)`` items
        on its queue at once, which is what enables it to fuse them
        into a single forward pass.

        The acquire phase is serialized across workers by the
        handle's ``acquire_lock`` (an mp.Lock). Without that, N
        concurrent workers each grabbing slots one at a time can
        each accumulate a partial allocation, exhaust the pool, and
        deadlock — see the multi-worker contention regression test.
        Holding the lock only for the acquire is deliberate: writes,
        submits, waits, and reads all run in parallel as before, so
        cross-worker dispatcher fusion is unaffected.

        On any failure (e.g. interrupted ``free_slots.get()``), the
        already-acquired slots are released before re-raising so the
        pool doesn't leak. Slots returned by this method are owned by
        the caller until released.
        """
        n = len(features)
        if masks is not None:
            assert self._h.masks is not None
            assert self._h.policies is not None
            assert len(masks) == n

        # Acquire slots atomically (all N or none). The lock prevents
        # the partial-allocation deadlock pattern. If we're
        # interrupted partway through the get() loop (BaseException,
        # e.g. KeyboardInterrupt), release whatever we have before
        # re-raising so the pool doesn't leak.
        slots: list[int] = []
        try:
            with self._h.acquire_lock:
                for _ in range(n):
                    slots.append(self._h.free_slots.get())
            # Write all input rows. Tight loop — no waiting between
            # rows, no submissions yet.
            for k, slot in enumerate(slots):
                np_feats = np.ascontiguousarray(
                    features[k], dtype=np.float32,
                )
                self._h.features[slot].copy_(torch.from_numpy(np_feats))
                if masks is not None:
                    np_mask = np.ascontiguousarray(masks[k], dtype=bool)
                    self._h.masks[slot].copy_(torch.from_numpy(np_mask))
            # Submit ALL slot indices before returning so the
            # dispatcher sees them as a batched window.
            for slot in slots:
                self._h.request_queue.put(slot)
        except BaseException:
            for slot in slots:
                self._h.free_slots.put(slot)
            raise
        return slots

    # ---- raw request paths (for bench / testing) ------------------------

    # Poll interval for the shutdown-aware wait. Normal calls return in
    # microseconds-to-low-milliseconds (substrate p50 74us, production
    # p95 ~3-4 ms), so wait() almost always returns True before the
    # first tick elapses — zero perceptible cost on the happy path.
    # Worst case: a worker observes server shutdown within this many
    # seconds. 0.5s is comfortably below the per-game timeout and well
    # within ``stop(timeout=5.0)``'s budget.
    _SHUTDOWN_POLL_S = 0.5

    def _await_response(self, slot: int) -> None:
        """Wait for the dispatcher to write outputs for ``slot``, with
        shutdown detection. Raises ``RuntimeError`` if the server is
        stopped before the response is written."""
        while not self._h.response_events[slot].wait(
            timeout=self._SHUTDOWN_POLL_S,
        ):
            # wait() timed out without being set. If the server has
            # gone down, bail; otherwise loop and keep waiting.
            if self._h.server_stopped.is_set():
                raise RuntimeError(
                    "SharedTensorNNEvalServer stopped before response "
                    f"was written (slot {slot})"
                )
        # The event fired. Two cases:
        # (a) Dispatcher wrote outputs and set the event — normal path.
        # (b) Server's ``stop()`` set the event to wake us; outputs
        #     are NOT valid. Distinguish via ``server_stopped``.
        self._h.response_events[slot].clear()
        if self._h.server_stopped.is_set():
            raise RuntimeError(
                "SharedTensorNNEvalServer stopped while waiting for "
                f"response (slot {slot})"
            )

    def _call_value(self, feats: np.ndarray) -> float:
        slot = self._h.free_slots.get()
        try:
            np_feats = np.ascontiguousarray(feats, dtype=np.float32)
            self._h.features[slot].copy_(torch.from_numpy(np_feats))
            self._h.request_queue.put(slot)
            self._await_response(slot)
            return float(self._h.values[slot, 0].item())
        finally:
            self._h.free_slots.put(slot)

    def _call_value_policy(
        self, feats: np.ndarray, mask: np.ndarray,
    ) -> tuple[float, np.ndarray]:
        slot = self._h.free_slots.get()
        try:
            np_feats = np.ascontiguousarray(feats, dtype=np.float32)
            self._h.features[slot].copy_(torch.from_numpy(np_feats))
            assert self._h.masks is not None
            assert self._h.policies is not None
            np_mask = np.ascontiguousarray(mask, dtype=bool)
            self._h.masks[slot].copy_(torch.from_numpy(np_mask))
            self._h.request_queue.put(slot)
            self._await_response(slot)
            value = float(self._h.values[slot, 0].item())
            policy = self._h.policies[slot].clone().numpy()
            return value, policy
        finally:
            self._h.free_slots.put(slot)

    def close(self) -> None:
        # Nothing to close — no per-worker resources.
        pass


def _engine_state(state: "GameState") -> Any:
    """Unwrap ``state.engine_state`` if present (matches NNEvalClient's
    helper); ``GameState`` instances may carry an engine-state attribute
    for feature extraction, or pass themselves through."""
    engine = getattr(state, "engine_state", None)
    if engine is not None:
        return engine
    return state
