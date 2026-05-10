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
    NNEvaluator,
    _ValueMLP,
    _ValuePolicyMLP,
)


def _action_encoding():
    """Lazy import so the module load doesn't pull in
    mtg_bot.training.action_encoding (a heavy chain via training.config)."""
    from mtg_bot.training import action_encoding as _ae
    return _ae


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

        # Build the model. Same shape as NNEvalServer's path.
        if model_factory is not None:
            self._model = model_factory()
        elif with_policy:
            self._model = _ValuePolicyMLP()
        else:
            self._model = _ValueMLP()
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
        self._dispatch_thread = threading.Thread(
            target=self._dispatch_loop,
            name="shm-nn-eval-server-dispatcher",
            daemon=True,
        )
        self._dispatch_thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        if self._dispatch_thread is None:
            return
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

    # ``evaluate`` and ``batch_evaluate`` inherit the base-class
    # implementations: ``evaluate`` short-circuits terminal states,
    # then delegates to ``_evaluate_nonterminal``; ``batch_evaluate``
    # iterates per-state (server-side batching across worker calls
    # happens automatically in the dispatcher).

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

    def batch_evaluate_with_policy(
        self, states: "Sequence[GameState]", player_id: "PlayerID",
    ) -> list[tuple[float, np.ndarray]]:
        if not self._with_policy:
            raise RuntimeError(
                "batch_evaluate_with_policy requires a policy-head server",
            )
        return [
            self.evaluate_with_policy(s, player_id) for s in states
        ]

    # ---- raw request paths (for bench / testing) ------------------------

    def _call_value(self, feats: np.ndarray) -> float:
        slot = self._h.free_slots.get()
        try:
            np_feats = np.ascontiguousarray(feats, dtype=np.float32)
            self._h.features[slot].copy_(torch.from_numpy(np_feats))
            self._h.request_queue.put(slot)
            self._h.response_events[slot].wait()
            self._h.response_events[slot].clear()
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
            self._h.response_events[slot].wait()
            self._h.response_events[slot].clear()
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
