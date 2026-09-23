"""Tests for the structured-architecture path on the shared-memory NN
eval server (Slice F of the Step 1 NN-representation roadmap).

Slice F lights up ``SharedTensorNNEvalServer`` for ``StructuredModel``
weights: the per-slot input substrate switches from the flat 51-dim
feature row to the four per-token tensors (``token_type``,
``token_emb_ids``, ``token_scalars``, ``attention_mask``) padded up
to ``MAX_SEQ_LEN``. Output slots (value + masked policy) stay
fixed-shape because the model's output side is identical.

Coverage:

- Lifecycle (start / stop / context manager) on a structured server.
- Handle carries the architecture flag + per-token shared tensors.
- ``with_policy`` is force-True for structured (mirrors NNEvaluator).
- Round-trip correctness vs a direct ``NNEvaluator(architecture=
  'structured')`` on the same input — bit-equal within float
  tolerance.
- Variable-length tokenizer output: slot writer pads up to
  MAX_SEQ_LEN, padded positions get ``attention_mask=False``.
- MAX_SEQ_LEN overflow: a request exceeding the cap raises with a
  clear error rather than silently truncating.
- Architecture validation at server construction time.
- Backpressure: chunked submits when N > n_slots.
- Teardown: stop() with in-flight workers raises ``server stopped``
  on each in-flight call (documents the teardown-race scenario the
  brief flagged; the fix lives in the base server's
  ``server_stopped`` event, which the structured client inherits).
"""

from __future__ import annotations

import sys
import threading
import time
import types
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import torch

from mtg_bot.search import nn_evaluator as nn_evaluator_mod
from mtg_bot.search.nn_evaluator import (
    ARCHITECTURE_SHARED,
    ARCHITECTURE_STRUCTURED,
    NNEvaluator,
)
from mtg_bot.search.shm_nn_eval_server import (
    DEFAULT_MAX_SEQ_LEN,
    SharedTensorNNEvalClient,
    SharedTensorNNEvalServer,
    SharedTensorServerHandle,
)
from mtg_bot.training.action_encoding import ACTION_VOCAB_SIZE
from mtg_bot.training.structured_model import (
    ACTION_KIND_VOCAB_SIZE,
    CONTROLLER_VOCAB_SIZE,
    EMB_FIELD_ACTION_KIND,
    EMB_FIELD_CONTROLLER,
    EMB_FIELD_PRINTING,
    EMB_FIELD_STEP,
    EMB_FIELD_TARGET_KIND,
    EMB_FIELD_TARGET_PRINTING,
    EMB_FIELD_VARIANT,
    N_EMB_FIELDS,
    DEFAULT_SCALAR_SCHEMA_VERSION,
    N_SCALAR_FIELDS_V2,
    scalar_width_for_schema,
    N_TOKEN_TYPES,
    STEP_VOCAB_SIZE,
    TARGET_KIND_VOCAB_SIZE,
    VARIANT_VOCAB_SIZE,
)


# Match the SMALL_KWARGS pattern used in test_nn_evaluator_structured.py
# so the SHM-side tests exercise the same tiny structured model the
# evaluator's structured tests use.
SMALL_KWARGS: dict[str, Any] = {
    "structured_emb_dim": 16,
    "structured_n_heads": 2,
    "structured_n_layers": 2,
    "structured_hidden_dim": 32,
    "structured_action_history_n": 4,
    "structured_n_printings": 32,
}


def _make_token_dict(
    *,
    seq_len: int,
    seed: int = 0,
    n_printings_cap: int = 32,
    scalar_width: int = N_SCALAR_FIELDS_V2,
) -> dict[str, np.ndarray]:
    """Build a random-but-valid token dict matching the tokenizer's
    output schema. Used both as the seed for the fake tokenizer and
    by the cap-overflow test which writes raw token dicts directly.
    """
    rng = np.random.default_rng(seed)
    token_type = rng.integers(
        0, N_TOKEN_TYPES, size=seq_len, dtype=np.int64,
    )
    token_emb_ids = np.zeros((seq_len, N_EMB_FIELDS), dtype=np.int64)
    token_emb_ids[:, EMB_FIELD_PRINTING] = rng.integers(
        0, n_printings_cap, size=seq_len, dtype=np.int64,
    )
    token_emb_ids[:, EMB_FIELD_ACTION_KIND] = rng.integers(
        0, ACTION_KIND_VOCAB_SIZE, size=seq_len, dtype=np.int64,
    )
    token_emb_ids[:, EMB_FIELD_CONTROLLER] = rng.integers(
        0, CONTROLLER_VOCAB_SIZE, size=seq_len, dtype=np.int64,
    )
    token_emb_ids[:, EMB_FIELD_TARGET_PRINTING] = rng.integers(
        0, n_printings_cap, size=seq_len, dtype=np.int64,
    )
    token_emb_ids[:, EMB_FIELD_TARGET_KIND] = rng.integers(
        0, TARGET_KIND_VOCAB_SIZE, size=seq_len, dtype=np.int64,
    )
    token_emb_ids[:, EMB_FIELD_VARIANT] = rng.integers(
        0, VARIANT_VOCAB_SIZE, size=seq_len, dtype=np.int64,
    )
    token_emb_ids[:, EMB_FIELD_STEP] = rng.integers(
        0, STEP_VOCAB_SIZE, size=seq_len, dtype=np.int64,
    )
    token_scalars = rng.standard_normal(
        (seq_len, scalar_width),
    ).astype(np.float32)
    attention_mask = np.ones(seq_len, dtype=bool)
    return {
        "token_type": token_type,
        "token_emb_ids": token_emb_ids,
        "token_scalars": token_scalars,
        "attention_mask": attention_mask,
    }


def _fake_tokenizer_module(*, seq_len_map: dict[int, int] | None = None):
    """Build a stand-in for ``mtg_bot.training.state_tokenizer`` that
    emits a deterministic-per-state token dict.

    ``seq_len_map``: optional dict mapping ``id(state)`` to a custom
    seq_len. Falls back to a default of 5 for any state not in the
    map. Used by the overflow test to inject an oversize seq_len for
    one specific state.
    """
    mod = types.ModuleType("mtg_bot.training.state_tokenizer")
    default_seq_len = 5
    seq_map = seq_len_map or {}

    def tokenize_state(state, viewer_id, recent_actions, n=32, *,
                       n_printings_cap=320,
                       scalar_schema_version=DEFAULT_SCALAR_SCHEMA_VERSION):
        seq_len = seq_map.get(id(state), default_seq_len)
        # Seed-on-id so each state has a stable dict across calls.
        seed = abs(hash((id(state), viewer_id))) % (2**32)
        return _make_token_dict(
            seq_len=seq_len, seed=seed, n_printings_cap=n_printings_cap,
            scalar_width=scalar_width_for_schema(scalar_schema_version),
        )

    mod.tokenize_state = tokenize_state
    return mod


@pytest.fixture
def fake_tokenizer(monkeypatch):
    """Install a stub state_tokenizer module for the test. Yields the
    module so a test can swap ``tokenize_state`` mid-run."""
    mod = _fake_tokenizer_module()
    monkeypatch.setitem(
        sys.modules, "mtg_bot.training.state_tokenizer", mod,
    )
    # Reset NNEvaluator's lazy cache so the same fake reaches both
    # the direct evaluator and the SHM client.
    monkeypatch.setattr(
        nn_evaluator_mod, "_STATE_TOKENIZER_MODULE", None,
    )
    return mod


@pytest.fixture
def patched_legal_mask(monkeypatch):
    """Patch ``legal_action_mask`` to say "every slot is legal." The
    SHM client and the direct evaluator share the same lazy
    action_encoding module reference, so one patch covers both."""
    ae = nn_evaluator_mod._action_encoding()

    def _all_true(state, viewer, version="positional_v1"):
        return np.ones(ACTION_VOCAB_SIZE, dtype=bool)

    monkeypatch.setattr(ae, "legal_action_mask", _all_true)
    return ae


class _FakeAdapter:
    """Minimal duck-type for ``GameState`` / adapter:
    ``is_terminal()``, ``winner()``, ``engine_state`` attribute so the
    SHM client's ``_engine_state`` helper short-circuits."""

    def __init__(
        self,
        terminal: bool = False,
        winner_id: Any = None,
    ) -> None:
        self._terminal = terminal
        self._winner = winner_id
        self.engine_state = object()

    def is_terminal(self) -> bool:
        return self._terminal

    def winner(self):
        return self._winner


def _make_structured_server(
    tmp_path: Path,
    *,
    n_slots: int = 4,
    batch_size: int = 4,
    batch_wait_ms: float = 0.0,
    max_seq_len: int = DEFAULT_MAX_SEQ_LEN,
) -> tuple[SharedTensorNNEvalServer, NNEvaluator, Path]:
    """Build (server, ref-evaluator, weights_path) sharing weights.

    Construction order matters: build the ref evaluator first with
    fixed seed → save its state_dict → load it into the server. That
    way ``client.evaluate_*`` and ``ref.evaluate_*`` use the same
    weights, so output equality is the load-bearing correctness check.
    """
    torch.manual_seed(0)
    ref = NNEvaluator(
        architecture=ARCHITECTURE_STRUCTURED, **SMALL_KWARGS,
    )
    weights_path = tmp_path / "structured.pt"
    ref.save(weights_path)
    server = SharedTensorNNEvalServer(
        weights_path=weights_path,
        device="cpu",
        architecture=ARCHITECTURE_STRUCTURED,
        batch_size=batch_size,
        batch_wait_ms=batch_wait_ms,
        n_slots=n_slots,
        max_seq_len=max_seq_len,
        **SMALL_KWARGS,
    )
    return server, ref, weights_path


# ---------- handle / config -------------------------------------------------


def test_structured_handle_carries_structured_tensors(tmp_path: Path):
    server, _, _ = _make_structured_server(
        tmp_path, n_slots=8, max_seq_len=64,
    )
    handle = server.handle()
    assert isinstance(handle, SharedTensorServerHandle)
    assert handle.architecture == ARCHITECTURE_STRUCTURED
    assert handle.with_policy is True  # forced
    assert handle.max_seq_len == 64
    assert handle.n_slots == 8
    # Structured per-token tensors are populated; ``features`` is a
    # zero-element placeholder.
    assert handle.token_type is not None
    assert handle.token_type.shape == (8, 64)
    assert handle.token_emb_ids is not None
    assert handle.token_emb_ids.shape == (8, 64, N_EMB_FIELDS)
    assert handle.token_scalars is not None
    assert handle.token_scalars.shape == (8, 64, N_SCALAR_FIELDS_V2)
    assert handle.attention_mask is not None
    assert handle.attention_mask.shape == (8, 64)
    # Each input tensor is on shared memory so workers can attach.
    assert handle.token_type.is_shared()
    assert handle.token_emb_ids.is_shared()
    assert handle.token_scalars.is_shared()
    assert handle.attention_mask.is_shared()
    # Output slots unchanged.
    assert handle.values.shape == (8, 1)
    assert handle.masks is not None
    assert handle.policies is not None
    assert handle.policies.shape == (8, ACTION_VOCAB_SIZE)
    # Flat-feature placeholder is empty.
    assert handle.features.shape == (8, 0)


def test_structured_server_forces_with_policy_true(tmp_path: Path):
    """``with_policy=False`` passed to a structured server is silently
    upgraded — the StructuredModel always has a policy head, and the
    SHM substrate writes both outputs in a single forward pass."""
    torch.manual_seed(0)
    server = SharedTensorNNEvalServer(
        weights_path=None,
        device="cpu",
        architecture=ARCHITECTURE_STRUCTURED,
        with_policy=False,  # explicitly False — should be upgraded
        n_slots=2,
        batch_size=1,
        batch_wait_ms=0.0,
        **SMALL_KWARGS,
    )
    assert server.handle().with_policy is True


def test_structured_server_rejects_unknown_architecture(tmp_path: Path):
    """A typo at construction time must surface immediately."""
    with pytest.raises(ValueError, match="architecture must be one of"):
        SharedTensorNNEvalServer(
            architecture="quantum-encoder-9000",
            n_slots=2,
            batch_size=1,
            batch_wait_ms=0.0,
        )


def test_handle_default_architecture_back_compat(tmp_path: Path):
    """Constructing without ``architecture`` keeps the flat MLP path —
    the handle's architecture is ``"shared"`` and the structured
    tensors are None. This is the legacy contract Slice F must not
    break."""
    server = SharedTensorNNEvalServer(
        weights_path=None,
        device="cpu",
        with_policy=True,
        n_slots=2,
        batch_size=1,
        batch_wait_ms=0.0,
    )
    handle = server.handle()
    assert handle.architecture == ARCHITECTURE_SHARED
    assert handle.max_seq_len == 0
    assert handle.token_type is None
    assert handle.token_emb_ids is None
    assert handle.token_scalars is None
    assert handle.attention_mask is None


# ---------- correctness vs direct NNEvaluator ------------------------------


def test_structured_evaluate_with_policy_matches_direct_evaluator(
    tmp_path: Path, fake_tokenizer, patched_legal_mask,
):
    """Single-state ``evaluate_with_policy`` on the structured SHM
    server matches ``NNEvaluator(architecture='structured')`` exactly
    when both use the same weights and the same tokenized input.
    The load-bearing correctness check for Slice F."""
    server, ref, _ = _make_structured_server(
        tmp_path, n_slots=4, batch_size=1, batch_wait_ms=0.0,
    )
    state = _FakeAdapter()
    with server:
        client = SharedTensorNNEvalClient(server.handle())
        v_server, p_server = client.evaluate_with_policy(state, player_id=0)
    v_local, p_local = ref.evaluate_with_policy(state, player_id=0)
    assert v_server == pytest.approx(float(v_local), abs=1e-5)
    np.testing.assert_allclose(p_server, p_local, atol=1e-5)


def test_structured_evaluate_value_only_matches_direct(
    tmp_path: Path, fake_tokenizer, patched_legal_mask,
):
    """The value-only ``evaluate`` path routes through the same
    structured forward (policy head materialized + discarded) and
    must produce the same value as the direct evaluator's
    ``evaluate``."""
    server, ref, _ = _make_structured_server(
        tmp_path, n_slots=4, batch_size=1, batch_wait_ms=0.0,
    )
    state = _FakeAdapter()
    with server:
        client = SharedTensorNNEvalClient(server.handle())
        v_server = client.evaluate(state, player_id=0)
    v_local = float(ref.evaluate(state, player_id=0))
    assert v_server == pytest.approx(v_local, abs=1e-5)


def test_structured_batch_evaluate_with_policy_matches_direct(
    tmp_path: Path, fake_tokenizer, patched_legal_mask,
):
    """Batched with-policy submit matches direct batched evaluator for
    a heterogeneous batch of mixed-seq_len states."""
    server, ref, _ = _make_structured_server(
        tmp_path, n_slots=8, batch_size=8, batch_wait_ms=2.0,
    )
    # Use multiple distinct adapter ids so the fake tokenizer emits
    # different token dicts per state — heterogeneous batch.
    states = [_FakeAdapter() for _ in range(4)]
    with server:
        client = SharedTensorNNEvalClient(server.handle())
        server_results = client.batch_evaluate_with_policy(states, 0)
    local_results = ref.batch_evaluate_with_policy(states, 0)
    assert len(server_results) == len(local_results)
    for (v_s, p_s), (v_l, p_l) in zip(server_results, local_results):
        assert v_s == pytest.approx(float(v_l), abs=1e-5)
        np.testing.assert_allclose(p_s, p_l, atol=1e-5)


def test_structured_batch_evaluate_value_only_matches_direct(
    tmp_path: Path, fake_tokenizer, patched_legal_mask,
):
    """Value-only batched path matches direct value-only batched."""
    server, ref, _ = _make_structured_server(
        tmp_path, n_slots=8, batch_size=8, batch_wait_ms=2.0,
    )
    states = [_FakeAdapter() for _ in range(3)]
    with server:
        client = SharedTensorNNEvalClient(server.handle())
        v_server = client.batch_evaluate(states, player_id=0)
    v_local = ref.batch_evaluate(states, player_id=0)
    assert len(v_server) == len(v_local)
    for vs, vl in zip(v_server, v_local):
        assert vs == pytest.approx(float(vl), abs=1e-5)


def test_structured_batch_with_mixed_terminal_states(
    tmp_path: Path, fake_tokenizer, patched_legal_mask,
):
    """Terminal states short-circuit without hitting the server;
    non-terminal results match the direct evaluator. Order
    preservation across the mix is what makes the indexing correct."""
    server, ref, _ = _make_structured_server(
        tmp_path, n_slots=4, batch_size=4, batch_wait_ms=2.0,
    )
    terminal_p0 = _FakeAdapter(terminal=True, winner_id=0)
    terminal_draw = _FakeAdapter(terminal=True, winner_id=None)
    nonterm = _FakeAdapter()
    mixed = [terminal_p0, nonterm, terminal_draw, nonterm]
    with server:
        client = SharedTensorNNEvalClient(server.handle())
        out = client.batch_evaluate_with_policy(mixed, player_id=0)
    # Terminal slots match the reference short-circuit (engine truth).
    assert out[0][0] == 1.0
    np.testing.assert_array_equal(out[0][1], np.zeros(ACTION_VOCAB_SIZE))
    assert out[2][0] == 0.0
    np.testing.assert_array_equal(out[2][1], np.zeros(ACTION_VOCAB_SIZE))
    # Non-terminal slots match the direct evaluator.
    for i in (1, 3):
        v_l, p_l = ref.evaluate_with_policy(mixed[i], player_id=0)
        assert out[i][0] == pytest.approx(float(v_l), abs=1e-5)
        np.testing.assert_allclose(out[i][1], p_l, atol=1e-5)
    # Only the 2 non-terminal states hit the server.
    assert server.requests_served == 2


def test_structured_batch_empty_input_returns_empty(
    tmp_path: Path, fake_tokenizer,
):
    server, _, _ = _make_structured_server(
        tmp_path, n_slots=2, batch_size=1, batch_wait_ms=0.0,
    )
    with server:
        client = SharedTensorNNEvalClient(server.handle())
        assert client.batch_evaluate_with_policy([], player_id=0) == []
        assert client.batch_evaluate([], player_id=0) == []
    assert server.requests_served == 0


# ---------- variable-length padding -----------------------------------------


def test_structured_variable_length_padding_zero_tail(
    tmp_path: Path, monkeypatch,
):
    """A short tokenized state padded up to MAX_SEQ_LEN has zero
    values + False mask in the tail. The slot writer must zero a
    prior request's leftover before writing the new (shorter) one;
    without that, padded positions could leak stale ids into the
    forward pass."""
    server, _, _ = _make_structured_server(
        tmp_path, n_slots=2, batch_size=1, batch_wait_ms=0.0,
        max_seq_len=8,
    )
    # First "request": fill slot 0 with a long-row token dict
    # directly via the writer. The mask should be fully True for the
    # seq_len positions and False past them.
    long_td = _make_token_dict(seq_len=8, seed=1, n_printings_cap=32)
    # Mark every position as non-NA so we can detect tail leakage.
    long_td["token_type"][:] = 7
    short_td = _make_token_dict(seq_len=3, seed=2, n_printings_cap=32)
    short_td["token_type"][:] = 5
    mask = np.ones(ACTION_VOCAB_SIZE, dtype=bool)

    server.start()
    try:
        client = SharedTensorNNEvalClient(server.handle())
        # Write the long row first, then overwrite slot 0 with the
        # shorter one. The leftover ``token_type=7`` in positions
        # 3..7 must be zeroed by the writer before submit.
        client._write_structured_row(slot=0, token_dict=long_td, mask=mask)
        client._write_structured_row(slot=0, token_dict=short_td, mask=mask)
        # Read the slot's per-token tensors and verify the layout.
        h = server.handle()
        tt = h.token_type[0].clone().numpy()
        am = h.attention_mask[0].clone().numpy()
        # Positions 0..2 carry the new short row (value 5); positions
        # 3..7 are zeroed (NA).
        assert tt[0:3].tolist() == [5, 5, 5]
        assert tt[3:8].tolist() == [0, 0, 0, 0, 0]
        # attention_mask: True for the valid positions, False after.
        assert am[0:3].tolist() == [True, True, True]
        assert am[3:8].tolist() == [False] * 5
    finally:
        server.stop(timeout=2.0)


# ---------- MAX_SEQ_LEN overflow --------------------------------------------


def test_structured_seq_len_overflow_raises_loudly(
    tmp_path: Path, monkeypatch, patched_legal_mask,
):
    """A request whose tokenized seq_len > MAX_SEQ_LEN must raise a
    clear error rather than silently truncating. Truncation would
    drop the tail tokens, which carry the freshest action history —
    the strongest signal Step 1's trunk has."""
    state = _FakeAdapter()
    # Fake tokenizer returns seq_len=16 for this specific state's
    # engine_state (the SHM client routes through ``_engine_state``,
    # so the tokenizer sees ``state.engine_state``, not ``state``).
    fake = _fake_tokenizer_module(
        seq_len_map={id(state.engine_state): 16},
    )
    monkeypatch.setitem(sys.modules, "mtg_bot.training.state_tokenizer", fake)
    monkeypatch.setattr(
        nn_evaluator_mod, "_STATE_TOKENIZER_MODULE", None,
    )

    server, _, _ = _make_structured_server(
        tmp_path, n_slots=2, batch_size=1, batch_wait_ms=0.0,
        max_seq_len=8,  # < tokenizer's 16
    )
    with server:
        client = SharedTensorNNEvalClient(server.handle())
        # Single-state path raises.
        with pytest.raises(ValueError, match="exceeds the SHM"):
            client.evaluate_with_policy(state, player_id=0)
        # Batched path raises during the up-front validation, before
        # any slot is acquired.
        with pytest.raises(ValueError, match="exceeds the SHM"):
            client.batch_evaluate_with_policy([state], player_id=0)
        # No slot leaked.
        assert server.requests_served == 0


def test_config_level_max_seq_len_covers_real_state_p99(tmp_path: Path):
    """Config-level assertion: the DEFAULT_MAX_SEQ_LEN is comfortably
    larger than the measured real-state seq_len p99 (~110 inferred
    from the median=53 / p95=82 distribution called out in the Slice F
    brief). The 128 default sits ~16-20 tokens above p99; if a future
    tokenizer growth makes this no longer true, this test fires and
    the SHM server's default needs to bump.

    The check is "bigger than the conservative estimate of p99," not
    a precise distribution check, because we don't ship a fixture of
    real-state distributions. A precise check would live in the
    tokenizer's bench script."""
    p99_conservative_upper_bound = 110
    assert DEFAULT_MAX_SEQ_LEN > p99_conservative_upper_bound, (
        f"DEFAULT_MAX_SEQ_LEN={DEFAULT_MAX_SEQ_LEN} is too small for "
        f"the conservative real-state p99 upper bound "
        f"({p99_conservative_upper_bound}); bump the default and the "
        f"linked rationale in shm_nn_eval_server.py."
    )


# ---------- backpressure: chunking ------------------------------------------


def test_structured_chunks_when_request_exceeds_slot_pool(
    tmp_path: Path, fake_tokenizer, patched_legal_mask,
):
    """An oversize request (N > n_slots) chunks into sub-batches
    rather than raising. The 5-state submit on a 2-slot pool runs
    3 dispatches (2 + 2 + 1) and returns 5 results in input order
    that match the direct evaluator."""
    server, ref, _ = _make_structured_server(
        tmp_path, n_slots=2, batch_size=2, batch_wait_ms=0.0,
    )
    states = [_FakeAdapter() for _ in range(5)]
    with server:
        client = SharedTensorNNEvalClient(server.handle())
        out = client.batch_evaluate_with_policy(states, 0)
    local = ref.batch_evaluate_with_policy(states, 0)
    assert len(out) == 5
    for (v_s, p_s), (v_l, p_l) in zip(out, local):
        assert v_s == pytest.approx(float(v_l), abs=1e-5)
        np.testing.assert_allclose(p_s, p_l, atol=1e-5)
    assert server.requests_served == 5
    assert server.batches_dispatched >= 3


# ---------- teardown / shutdown ---------------------------------------------


def test_structured_clean_stop_after_idle(tmp_path: Path):
    """No in-flight requests → ``stop()`` returns promptly and the
    server can restart cleanly."""
    server, _, _ = _make_structured_server(
        tmp_path, n_slots=2, batch_size=1, batch_wait_ms=0.0,
    )
    server.start()
    server.stop(timeout=2.0)
    # Restart works (matches the flat-path back-compat test).
    server.start()
    server.stop(timeout=2.0)


def test_structured_stop_wakes_in_flight_workers(
    tmp_path: Path, fake_tokenizer, patched_legal_mask,
):
    """A worker mid-``evaluate_with_policy`` waiting on a response
    that will never come (dispatcher parked on a slow batch window)
    must wake and raise when the server is stopped. This pins the
    "stop() while workers in flight" behaviour the brief asked us to
    document — the fix inherits from the base server's
    ``server_stopped`` event, which the structured client uses
    unchanged."""
    server, _, _ = _make_structured_server(
        tmp_path,
        n_slots=4,
        batch_size=16,           # never fills with a single request
        batch_wait_ms=10000.0,   # 10s window — far longer than test
    )
    server.start()
    client = SharedTensorNNEvalClient(server.handle())
    state = _FakeAdapter()
    result: list[Any] = []

    def _call() -> None:
        try:
            client.evaluate_with_policy(state, player_id=0)
            result.append(("ok",))
        except RuntimeError as e:
            result.append(("err", str(e)))

    t = threading.Thread(target=_call, daemon=True)
    t.start()
    time.sleep(0.2)  # let worker land in _await_response

    t_stop_start = time.monotonic()
    server.stop(timeout=5.0)
    stop_wall = time.monotonic() - t_stop_start

    t.join(timeout=2.0)
    assert not t.is_alive(), (
        "structured-client thread still alive 2.0s after server.stop() — "
        "the shutdown deadlock would be back if we'd dropped "
        "server_stopped on the structured path"
    )
    assert stop_wall < 3.0
    assert len(result) == 1 and result[0][0] == "err"
    assert "stopped" in result[0][1].lower()


def test_structured_stop_releases_slots_mid_batch(
    tmp_path: Path, fake_tokenizer, patched_legal_mask,
):
    """If a batched structured call is mid-await when the server
    stops, every slot it acquired must be released to the pool so a
    restart doesn't observe a leak — mirrors the flat-path
    test_batched_release_all_slots_on_server_stop_mid_call coverage."""
    server, _, _ = _make_structured_server(
        tmp_path,
        n_slots=4,
        batch_size=16,
        batch_wait_ms=10000.0,
    )
    server.start()
    client = SharedTensorNNEvalClient(server.handle())
    state = _FakeAdapter()
    result: list[Any] = []

    def _call() -> None:
        try:
            client.batch_evaluate_with_policy(
                [state, state, state], player_id=0,
            )
            result.append(("ok",))
        except RuntimeError as e:
            result.append(("err", str(e)))

    t = threading.Thread(target=_call, daemon=True)
    t.start()
    time.sleep(0.3)

    server.stop(timeout=5.0)
    t.join(timeout=3.0)
    assert not t.is_alive()
    assert len(result) == 1 and result[0][0] == "err"

    # Restart and drain free_slots — all 4 slots back in the pool.
    server.start()
    drained: list[int] = []
    try:
        for _ in range(4):
            drained.append(server.handle().free_slots.get(timeout=2.0))
        assert sorted(drained) == list(range(4))
    finally:
        server.stop(timeout=2.0)


# ---------- concurrent workers (basic fusion check) -------------------------


def test_structured_concurrent_workers_get_batched(
    tmp_path: Path, fake_tokenizer, patched_legal_mask,
):
    """N concurrent ``evaluate_with_policy`` calls on the structured
    server land in a small number of dispatches (or one). The
    dispatcher's batch_sizes telemetry pins the "fusion happens"
    invariant."""
    server, _, _ = _make_structured_server(
        tmp_path, n_slots=8, batch_size=8, batch_wait_ms=20.0,
    )
    n_threads = 6
    results: list[Any] = [None] * n_threads

    with server:
        def _worker(i: int) -> None:
            client = SharedTensorNNEvalClient(server.handle())
            results[i] = client.evaluate_with_policy(
                _FakeAdapter(), player_id=0,
            )

        threads = [
            threading.Thread(target=_worker, args=(i,))
            for i in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

    assert all(r is not None for r in results)
    assert server.requests_served == n_threads
    assert max(server.batch_sizes) >= 2, (
        f"no fusion at all: batch_sizes={server.batch_sizes}"
    )
    assert server.batches_dispatched < n_threads


# ---------- structured + flat coexistence (regression) -----------------------


def test_structured_batch_value_only_terminal_winner_branches(
    tmp_path: Path, fake_tokenizer,
):
    """batch_evaluate covers each terminal-winner branch (viewer-wins
    / opponent-wins / draw) on the structured value-only path —
    mirrors the with-policy terminal coverage above."""
    server, _, _ = _make_structured_server(
        tmp_path, n_slots=2, batch_size=1, batch_wait_ms=0.0,
    )
    states = [
        _FakeAdapter(terminal=True, winner_id=0),     # viewer wins → +1
        _FakeAdapter(terminal=True, winner_id=1),     # opponent wins → -1
        _FakeAdapter(terminal=True, winner_id=None),  # draw → 0
    ]
    with server:
        client = SharedTensorNNEvalClient(server.handle())
        values = client.batch_evaluate(states, player_id=0)
    assert values == [1.0, -1.0, 0.0]
    # No request hit the server.
    assert server.requests_served == 0


def test_structured_evaluate_with_policy_terminal_short_circuit(
    tmp_path: Path, fake_tokenizer,
):
    """Terminal-state short-circuit on the structured client must
    bypass the tokenizer (matches the legacy MLP path's contract)
    — verifies +1 / -1 / 0 covering both winner branches."""
    server, _, _ = _make_structured_server(
        tmp_path, n_slots=2, batch_size=1, batch_wait_ms=0.0,
    )
    with server:
        client = SharedTensorNNEvalClient(server.handle())
        # Win: viewer == winner → +1.
        v_win, p_win = client.evaluate_with_policy(
            _FakeAdapter(terminal=True, winner_id=0), player_id=0,
        )
        assert v_win == 1.0
        np.testing.assert_array_equal(
            p_win, np.zeros(ACTION_VOCAB_SIZE, dtype=np.float32),
        )
        # Loss: opponent wins → -1.
        v_loss, p_loss = client.evaluate_with_policy(
            _FakeAdapter(terminal=True, winner_id=1), player_id=0,
        )
        assert v_loss == -1.0
        # Draw: winner is None → 0.
        v_draw, p_draw = client.evaluate_with_policy(
            _FakeAdapter(terminal=True, winner_id=None), player_id=0,
        )
        assert v_draw == 0.0
    # None of the terminals hit the server.
    assert server.requests_served == 0


def test_structured_dispatcher_failure_wakes_workers(
    tmp_path: Path, monkeypatch, patched_legal_mask,
):
    """If the dispatcher's forward throws (e.g. corrupted weights /
    out-of-range embedding id from a buggy tokenizer), the worker
    in ``_await_response`` must wake with a clear ``server stopped``
    RuntimeError instead of hanging forever. Catches the
    dispatcher-swallowed-exception deadlock that bit production
    eval cleanup before the dispatch try/except landed."""
    state = _FakeAdapter()
    # Force the tokenizer to emit a printing id outside the model's
    # n_printings_cap (32). The forward will IndexError inside the
    # embedding lookup; the dispatcher's try/except must wake the
    # worker via ``server_stopped`` rather than leave it hanging.
    mod = types.ModuleType("mtg_bot.training.state_tokenizer")

    def tokenize_state(state, viewer_id, recent_actions, n=32, *,
                       n_printings_cap=320,
                       scalar_schema_version=DEFAULT_SCALAR_SCHEMA_VERSION):
        d = _make_token_dict(
            seq_len=4, seed=42, n_printings_cap=32,
            scalar_width=scalar_width_for_schema(scalar_schema_version),
        )
        # Inject an out-of-range printing id.
        d["token_emb_ids"][0, EMB_FIELD_PRINTING] = 9999
        return d

    mod.tokenize_state = tokenize_state
    monkeypatch.setitem(
        sys.modules, "mtg_bot.training.state_tokenizer", mod,
    )
    monkeypatch.setattr(
        nn_evaluator_mod, "_STATE_TOKENIZER_MODULE", None,
    )

    server, _, _ = _make_structured_server(
        tmp_path, n_slots=2, batch_size=1, batch_wait_ms=0.0,
    )
    with server:
        client = SharedTensorNNEvalClient(server.handle())
        # The dispatcher's forward raises IndexError; the wrapper
        # signals ``server_stopped``; the client wakes and raises
        # RuntimeError with "stopped" in the message.
        with pytest.raises(RuntimeError, match="stopped"):
            client.evaluate_with_policy(state, player_id=0)


def test_structured_client_close_is_noop(tmp_path: Path):
    """Client.close() is a no-op (no per-worker resources to release).
    Same contract as the flat-path client; pin it so a future change
    that adds a resource doesn't silently regress shutdown."""
    server, _, _ = _make_structured_server(
        tmp_path, n_slots=2, batch_size=1, batch_wait_ms=0.0,
    )
    with server:
        client = SharedTensorNNEvalClient(server.handle())
        client.close()


def test_structured_chunked_internal_empty_short_circuit(
    tmp_path: Path,
):
    """``_call_chunked_structured`` with empty input returns
    ``([], [])`` without acquiring slots — pins the trivial
    short-circuit so a future refactor can't drop it."""
    server, _, _ = _make_structured_server(
        tmp_path, n_slots=2, batch_size=1, batch_wait_ms=0.0,
    )
    with server:
        client = SharedTensorNNEvalClient(server.handle())
        values, policies = client._call_chunked_structured(
            token_dicts=[], masks=[],
        )
        assert values == []
        assert policies == []


def test_structured_engine_state_fallthrough_accepts_raw_state(
    tmp_path: Path, fake_tokenizer, patched_legal_mask,
):
    """``_engine_state`` returns the input unchanged when there's no
    ``engine_state`` attribute. The structured client accepts both an
    adapter (with engine_state) and a raw state-like object."""

    class _RawState:
        """Duck-types ``GameState`` minus the ``engine_state`` attr."""
        def is_terminal(self): return False
        def winner(self): return None

    server, _, _ = _make_structured_server(
        tmp_path, n_slots=2, batch_size=1, batch_wait_ms=0.0,
    )
    state = _RawState()
    with server:
        client = SharedTensorNNEvalClient(server.handle())
        value, policy = client.evaluate_with_policy(state, player_id=0)
        assert isinstance(value, float)
        assert policy.shape == (ACTION_VOCAB_SIZE,)


def test_flat_path_still_works_when_structured_module_imported(tmp_path: Path):
    """Smoke: a flat-feature server built in the same process as a
    structured one still services flat requests. Catches the
    accidental cross-coupling where importing structured code at
    module load primed a path that breaks the legacy MLP server."""
    flat_server = SharedTensorNNEvalServer(
        weights_path=None,
        device="cpu",
        with_policy=True,
        n_slots=2,
        batch_size=1,
        batch_wait_ms=0.0,
    )
    structured_server, _, _ = _make_structured_server(
        tmp_path, n_slots=2, batch_size=1, batch_wait_ms=0.0,
    )
    # Both servers can have handles and start/stop without
    # interaction.
    with flat_server:
        assert flat_server.handle().architecture == ARCHITECTURE_SHARED
    with structured_server:
        assert (
            structured_server.handle().architecture
            == ARCHITECTURE_STRUCTURED
        )
