"""Tests for the structured-architecture path in
``mtg_bot.search.nn_evaluator.NNEvaluator``.

Slice E of the Step 1 NN-representation roadmap (see
``docs/NN_REPRESENTATION_ROADMAP.md``) wires the loader + inference
dispatch so MCTS / PIMC can call either the legacy
``ValuePolicyMLP`` or the new ``StructuredModel`` based on the loaded
version's ``ModelMetadata.architecture`` field.

The state-tokenizer dependency
(``mtg_bot.training.state_tokenizer.tokenize_state``) is provided by a
sibling slice and may not be present on the branch base; these tests
stub it via ``sys.modules`` injection so they cover the evaluator's
dispatch path without depending on the tokenizer landing first.

Coverage targets:

- Constructor dispatch by architecture string (``"structured"``
  routes to ``StructuredModel``; ``"shared"`` / ``"separate"`` keep
  routing to the MLP heads — regression).
- ``from_metadata`` classmethod picks the right architecture branch
  off ``ModelMetadata.architecture``.
- ``evaluate``, ``batch_evaluate``, ``evaluate_with_policy``,
  ``batch_evaluate_with_policy``, ``evaluate_logits``,
  ``batch_evaluate_logits`` return correctly-shaped + typed results
  on a structured evaluator.
- Save / load round-trip on a structured network reproduces
  predictions.
- Terminal-state short-circuit on the structured path does not call
  the tokenizer (matches the MLP path's contract).
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import torch

from mtg_bot.search import nn_evaluator as nn_evaluator_mod
from mtg_bot.search.nn_evaluator import (
    ARCHITECTURE_SEPARATE,
    ARCHITECTURE_SHARED,
    ARCHITECTURE_STRUCTURED,
    NNEvaluator,
    SUPPORTED_ARCHITECTURES,
    _build_dual_head_model,
    _build_structured_model,
    _collate_structured_token_dicts,
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
    scalar_width_for_schema,
    N_TOKEN_TYPES,
    STEP_VOCAB_SIZE,
    StructuredModel,
    TARGET_KIND_VOCAB_SIZE,
    VARIANT_VOCAB_SIZE,
)


# ---------------------------------------------------------------------
# Fixtures: tiny structured config + fake tokenizer
# ---------------------------------------------------------------------


# Hyperparams sized so the structured model trains / forwards quickly.
# Matches the SMALL_CONFIG in test_structured_model.py to stay
# consistent with the model-side unit tests.
SMALL_KWARGS: dict[str, Any] = {
    "architecture": ARCHITECTURE_STRUCTURED,
    "structured_emb_dim": 16,
    "structured_n_heads": 2,
    "structured_n_layers": 2,
    "structured_hidden_dim": 32,
    "structured_action_history_n": 4,
    "structured_n_printings": 32,
}


def _fake_tokenizer_module(*, seq_len: int = 5):
    """Build a stand-in for ``mtg_bot.training.state_tokenizer`` that
    emits a fixed-shape token dict regardless of input.

    Returns the module object; caller is responsible for swapping it
    into ``sys.modules['mtg_bot.training.state_tokenizer']`` and
    clearing the evaluator's lazy cache so the next ``_state_tokenizer``
    call picks it up.
    """
    mod = types.ModuleType("mtg_bot.training.state_tokenizer")

    def tokenize_state(state, viewer_id, recent_actions, n=32, *,
                       n_printings_cap=320,
                       scalar_schema_version=DEFAULT_SCALAR_SCHEMA_VERSION):
        scalar_width = scalar_width_for_schema(scalar_schema_version)
        # Seed-on-id(state) keeps each state's tokens consistent
        # across calls within a test, while still letting different
        # states produce different inputs.
        rng = np.random.default_rng(abs(hash((id(state), viewer_id))) % (2**32))
        token_type = rng.integers(0, N_TOKEN_TYPES, size=seq_len, dtype=np.int64)
        # Respect each field's vocab size — the model's embedding
        # tables only have a fixed number of rows per field and
        # over-indexing into them raises IndexError on the embedding
        # lookup. The structured model passes `n_printings_cap` to
        # the tokenizer so the printing ids stay in range; this stub
        # respects the cap directly.
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

    mod.tokenize_state = tokenize_state
    return mod


@pytest.fixture
def fake_tokenizer(monkeypatch):
    """Install a stub state_tokenizer module for the duration of a
    test. Yields the module so a test can inspect / replace
    ``tokenize_state`` mid-run if needed."""
    mod = _fake_tokenizer_module()
    monkeypatch.setitem(
        sys.modules, "mtg_bot.training.state_tokenizer", mod,
    )
    # Reset the evaluator module's lazy cache so the next lookup
    # picks up the stub. ``monkeypatch`` restores both this attribute
    # and the sys.modules entry at teardown.
    monkeypatch.setattr(
        nn_evaluator_mod, "_STATE_TOKENIZER_MODULE", None,
    )
    return mod


def _legal_mask_all_true(state, viewer, version="positional_v1"):
    """Stub for ``legal_action_mask`` that says "every slot is legal."
    Lets the structured-evaluator tests exercise the masked-softmax
    path with the fake adapter (which has no engine state to actually
    enumerate legal actions from)."""
    return np.ones(ACTION_VOCAB_SIZE, dtype=bool)


@pytest.fixture
def patched_legal_mask(monkeypatch):
    """Patch ``legal_action_mask`` on the lazily-resolved action-
    encoding module so the with-policy paths don't need a real
    engine state. The evaluator routes every mask call through
    ``_action_encoding().legal_action_mask``; replacing that one
    attribute on the cached module is enough."""
    ae = nn_evaluator_mod._action_encoding()
    monkeypatch.setattr(ae, "legal_action_mask", _legal_mask_all_true)
    return ae


class _FakeAdapter:
    """Minimal duck-type for ``GameState`` / adapter contract:
    ``is_terminal()``, ``winner()``, and an ``engine_state`` attribute
    so the evaluator's ``_engine_state`` helper short-circuits."""

    def __init__(self, terminal: bool = False, winner_id: Any = None) -> None:
        self._terminal = terminal
        self._winner = winner_id
        # The fake tokenizer ignores its first arg; we still pass
        # something with a stable id() for the seed.
        self.engine_state = object()

    def is_terminal(self) -> bool:
        return self._terminal

    def winner(self):
        return self._winner


# ---------------------------------------------------------------------
# Architecture constant / dispatch
# ---------------------------------------------------------------------


def test_supported_architectures_includes_structured():
    """``SUPPORTED_ARCHITECTURES`` is the load-time validation
    backstop; ``"structured"`` must be in it or the constructor
    will reject the value before dispatch."""
    assert ARCHITECTURE_STRUCTURED in SUPPORTED_ARCHITECTURES
    assert ARCHITECTURE_STRUCTURED == "structured"


def test_build_dual_head_model_rejects_structured():
    """The MLP builder must refuse ``"structured"`` — the structured
    trunk has a different input shape and is routed through
    ``_build_structured_model`` instead. Mixing them would feed
    flat features into a transformer (or vice versa)."""
    with pytest.raises(ValueError, match="StructuredModel"):
        _build_dual_head_model(ARCHITECTURE_STRUCTURED)


def test_build_structured_model_returns_structured_model():
    """Spot-check the builder constructs a real ``StructuredModel``
    with the requested config knobs honored."""
    model = _build_structured_model(
        emb_dim=16, n_heads=2, n_layers=2, hidden_dim=32,
        action_history_n=8, n_printings=32,
    )
    assert isinstance(model, StructuredModel)
    assert model.config.emb_dim == 16
    assert model.config.n_heads == 2
    assert model.config.n_layers == 2
    assert model.config.action_history_n == 8
    assert model.config.n_printings == 32


def test_nn_evaluator_dispatches_structured_by_architecture():
    """Constructor branch: ``architecture='structured'`` instantiates
    a ``StructuredModel`` regardless of ``with_policy`` (which is
    forced True for structured) and sets the ``is_structured`` flag."""
    ev = NNEvaluator(**SMALL_KWARGS)
    assert ev.is_structured is True
    assert ev.with_policy is True
    assert ev.architecture == ARCHITECTURE_STRUCTURED
    assert isinstance(ev.model, StructuredModel)


def test_nn_evaluator_mlp_paths_still_default_when_not_structured():
    """Regression: leaving ``architecture`` at its default (``"shared"``)
    must keep building the existing MLP models. Slice E should not
    change any legacy-architecture behaviour."""
    ev = NNEvaluator()
    assert ev.is_structured is False
    assert ev.architecture == ARCHITECTURE_SHARED
    # Default is value-only — the dual-head MLP is opt-in via
    # ``with_policy=True``.
    assert ev.with_policy is False

    ev_shared = NNEvaluator(with_policy=True, architecture=ARCHITECTURE_SHARED)
    assert ev_shared.is_structured is False
    assert ev_shared.architecture == ARCHITECTURE_SHARED

    ev_separate = NNEvaluator(
        with_policy=True, architecture=ARCHITECTURE_SEPARATE,
    )
    assert ev_separate.is_structured is False
    assert ev_separate.architecture == ARCHITECTURE_SEPARATE


def test_unknown_architecture_rejected():
    """Typos at construction time must surface immediately, not at
    first-call time as a confusing forward-pass error."""
    with pytest.raises(ValueError, match="architecture must be one of"):
        NNEvaluator(architecture="quantum-encoder-9000")


# ---------------------------------------------------------------------
# Forward-pass shape contracts (with mocked tokenizer)
# ---------------------------------------------------------------------


def test_structured_evaluate_returns_scalar_in_unit_interval(fake_tokenizer):
    """``evaluate`` on a structured evaluator must return a Python
    float in ``[-1, +1]`` — the tanh-activated value head's range
    contract."""
    ev = NNEvaluator(**SMALL_KWARGS)
    state = _FakeAdapter()
    value = ev.evaluate(state, player_id=0)
    assert isinstance(value, float)
    assert -1.0 <= value <= 1.0
    assert np.isfinite(value)


def test_structured_batch_evaluate_returns_per_state_floats(fake_tokenizer):
    """``batch_evaluate`` returns one float per input state, in
    order; mixing terminal + non-terminal states preserves indexing.
    """
    ev = NNEvaluator(**SMALL_KWARGS)
    states = [
        _FakeAdapter(),
        _FakeAdapter(terminal=True, winner_id=0),
        _FakeAdapter(),
        _FakeAdapter(terminal=True, winner_id=None),  # draw
    ]
    values = ev.batch_evaluate(states, player_id=0)
    assert len(values) == 4
    # Terminal short-circuits land at the engine-truth values; non-
    # terminal slots come from the NN's tanh output.
    assert values[1] == 1.0
    assert values[3] == 0.0
    for v in (values[0], values[2]):
        assert isinstance(v, float)
        assert -1.0 <= v <= 1.0


def test_structured_evaluate_with_policy_shapes(
    fake_tokenizer, patched_legal_mask,
):
    """``evaluate_with_policy`` returns ``(float, ndarray)`` with the
    policy array sized to ``ACTION_VOCAB_SIZE``."""
    ev = NNEvaluator(**SMALL_KWARGS)
    state = _FakeAdapter()
    value, policy = ev.evaluate_with_policy(state, player_id=0)
    assert isinstance(value, float)
    assert -1.0 <= value <= 1.0
    assert isinstance(policy, np.ndarray)
    assert policy.shape == (ACTION_VOCAB_SIZE,)
    assert policy.dtype == np.float32
    # Policy is a probability distribution: every entry in [0, 1],
    # sum 1 within float epsilon (legal mask zeros-out the rest).
    assert (policy >= 0.0).all()
    assert (policy <= 1.0).all()
    assert policy.sum() == pytest.approx(1.0, abs=1e-5)


def test_structured_batch_evaluate_with_policy_shapes(
    fake_tokenizer, patched_legal_mask,
):
    """Batched companion preserves shape contract per element."""
    ev = NNEvaluator(**SMALL_KWARGS)
    states = [_FakeAdapter() for _ in range(3)]
    out = ev.batch_evaluate_with_policy(states, player_id=0)
    assert len(out) == 3
    for value, policy in out:
        assert isinstance(value, float)
        assert policy.shape == (ACTION_VOCAB_SIZE,)
        assert policy.dtype == np.float32
        assert policy.sum() == pytest.approx(1.0, abs=1e-5)


def test_structured_batch_evaluate_with_policy_empty_input(fake_tokenizer):
    """Empty input → empty output (no tokenizer call, no model call)."""
    ev = NNEvaluator(**SMALL_KWARGS)
    out = ev.batch_evaluate_with_policy([], player_id=0)
    assert out == []


def test_structured_batch_evaluate_empty_input(fake_tokenizer):
    """Empty input to ``batch_evaluate`` is also a no-op."""
    ev = NNEvaluator(**SMALL_KWARGS)
    out = ev.batch_evaluate([], player_id=0)
    assert out == []


def test_structured_evaluate_logits_shape(fake_tokenizer):
    """``evaluate_logits`` returns RAW logits (no mask, no softmax)
    — ISMCTS uses this to grow the union-mask over multiple
    determinizations."""
    ev = NNEvaluator(**SMALL_KWARGS)
    state = _FakeAdapter()
    value, logits = ev.evaluate_logits(state, player_id=0)
    assert isinstance(value, float)
    assert -1.0 <= value <= 1.0
    assert logits.shape == (ACTION_VOCAB_SIZE,)
    assert logits.dtype == np.float32
    # Raw logits aren't probabilities — at least one negative value
    # is statistically very likely on random init, but the actual
    # invariant is that they're finite.
    assert np.isfinite(logits).all()


def test_structured_batch_evaluate_logits_shape(fake_tokenizer):
    """Batched logits companion: per-element raw logits, preserves
    input order, terminal short-circuit yields all-zeros."""
    ev = NNEvaluator(**SMALL_KWARGS)
    states = [
        _FakeAdapter(),
        _FakeAdapter(terminal=True, winner_id=0),
        _FakeAdapter(),
    ]
    out = ev.batch_evaluate_logits(states, player_id=0)
    assert len(out) == 3
    # Terminal slot has +1 value (P0 won) and all-zero logits.
    assert out[1][0] == 1.0
    np.testing.assert_array_equal(
        out[1][1], np.zeros(ACTION_VOCAB_SIZE, dtype=np.float32),
    )
    # Non-terminal slots have real logits.
    for v, logits in (out[0], out[2]):
        assert np.isfinite(logits).all()
        assert logits.shape == (ACTION_VOCAB_SIZE,)


def test_structured_batch_evaluate_logits_empty_input(fake_tokenizer):
    """Empty batch → empty result."""
    ev = NNEvaluator(**SMALL_KWARGS)
    assert ev.batch_evaluate_logits([], player_id=0) == []


# ---------------------------------------------------------------------
# Terminal short-circuit (does NOT call the tokenizer)
# ---------------------------------------------------------------------


def test_structured_terminal_state_draw_short_circuits(fake_tokenizer):
    """A drawn terminal short-circuits to value=0.0 with all-zeros
    policy / logits across every entry point — covers the
    ``winner is None`` arm of each public method's terminal branch.
    """
    ev = NNEvaluator(**SMALL_KWARGS)
    draw = _FakeAdapter(terminal=True, winner_id=None)
    # evaluate
    assert ev.evaluate(draw, player_id=0) == 0.0
    # evaluate_with_policy
    val, pol = ev.evaluate_with_policy(draw, player_id=0)
    assert val == 0.0
    np.testing.assert_array_equal(
        pol, np.zeros(ACTION_VOCAB_SIZE, dtype=np.float32),
    )
    # evaluate_logits
    val_l, logits = ev.evaluate_logits(draw, player_id=0)
    assert val_l == 0.0
    np.testing.assert_array_equal(
        logits, np.zeros(ACTION_VOCAB_SIZE, dtype=np.float32),
    )


def test_structured_no_legal_actions_returns_zero_policy(
    fake_tokenizer, monkeypatch,
):
    """Defensive: if ``legal_action_mask`` returns all-False (no
    legal slot), the masked softmax would be NaN. Both single and
    batched ``with_policy`` paths must instead return an all-zeros
    policy without calling softmax. Same convention as the legacy
    MLP path."""
    ae = nn_evaluator_mod._action_encoding()
    monkeypatch.setattr(
        ae, "legal_action_mask",
        lambda s, v, version="positional_v1": np.zeros(
            ACTION_VOCAB_SIZE, dtype=bool,
        ),
    )
    ev = NNEvaluator(**SMALL_KWARGS)
    state = _FakeAdapter()
    # Single-state path.
    val, pol = ev.evaluate_with_policy(state, player_id=0)
    assert isinstance(val, float)
    np.testing.assert_array_equal(
        pol, np.zeros(ACTION_VOCAB_SIZE, dtype=np.float32),
    )
    # Batched path.
    out = ev.batch_evaluate_with_policy([state, state], player_id=0)
    for v, p in out:
        assert isinstance(v, float)
        np.testing.assert_array_equal(
            p, np.zeros(ACTION_VOCAB_SIZE, dtype=np.float32),
        )


def test_structured_terminal_state_does_not_call_tokenizer(monkeypatch):
    """``evaluate_with_policy`` on a terminal state must short-circuit
    without invoking the tokenizer — terminals have a known +1/-1/0
    value and no legal action, so tokenization is a wasted call.
    """
    calls: list[Any] = []

    fake = types.ModuleType("mtg_bot.training.state_tokenizer")

    def tokenize_state(*args, **kwargs):
        calls.append(args)
        raise AssertionError(
            "tokenize_state must not be called for terminal states",
        )

    fake.tokenize_state = tokenize_state
    monkeypatch.setitem(
        sys.modules, "mtg_bot.training.state_tokenizer", fake,
    )
    monkeypatch.setattr(
        nn_evaluator_mod, "_STATE_TOKENIZER_MODULE", None,
    )

    ev = NNEvaluator(**SMALL_KWARGS)
    terminal = _FakeAdapter(terminal=True, winner_id=0)
    value, policy = ev.evaluate_with_policy(terminal, player_id=0)
    assert value == 1.0
    np.testing.assert_array_equal(
        policy, np.zeros(ACTION_VOCAB_SIZE, dtype=np.float32),
    )
    assert calls == []

    # ``evaluate`` (the value-only path) also short-circuits.
    assert ev.evaluate(terminal, player_id=0) == 1.0
    assert ev.evaluate(terminal, player_id=1) == -1.0

    # And ``evaluate_logits`` does too.
    val_l, logits = ev.evaluate_logits(terminal, player_id=0)
    assert val_l == 1.0
    np.testing.assert_array_equal(
        logits, np.zeros(ACTION_VOCAB_SIZE, dtype=np.float32),
    )
    assert calls == []


# ---------------------------------------------------------------------
# Save / load round-trip
# ---------------------------------------------------------------------


def test_structured_save_and_load_round_trip(
    tmp_path: Path, fake_tokenizer, patched_legal_mask,
):
    """Save weights from a structured evaluator and load them into a
    fresh one with matching hyperparams; predictions must reproduce."""
    a = NNEvaluator(**SMALL_KWARGS)
    weights_path = tmp_path / "weights.pt"
    a.save(weights_path)
    assert weights_path.exists()

    b = NNEvaluator(weights_path=weights_path, **SMALL_KWARGS)
    state = _FakeAdapter()
    val_a, pol_a = a.evaluate_with_policy(state, player_id=0)
    val_b, pol_b = b.evaluate_with_policy(state, player_id=0)
    assert val_a == pytest.approx(val_b, abs=1e-6)
    np.testing.assert_allclose(pol_a, pol_b, atol=1e-6, rtol=0)


# ---------------------------------------------------------------------
# Collate helper
# ---------------------------------------------------------------------


def test_collate_structured_token_dicts_pads_to_max_len():
    """The collator must left-align each row in a zero-padded
    matrix sized to ``max(seq_len_i)`` and mark padded positions
    with ``attention_mask=False``."""
    d_short = {
        "token_type": np.array([1, 2], dtype=np.int64),
        "token_emb_ids": np.array(
            [[1, 0, 0, 0, 0, 0, 0], [2, 0, 0, 0, 0, 0, 0]],
            dtype=np.int64,
        ),
        "token_scalars": np.array(
            [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
            dtype=np.float32,
        ),
        "attention_mask": np.array([True, True], dtype=bool),
    }
    d_long = {
        "token_type": np.array([3, 4, 5, 6], dtype=np.int64),
        "token_emb_ids": np.array(
            [
                [3, 0, 0, 0, 0, 0, 0],
                [4, 0, 0, 0, 0, 0, 0],
                [5, 0, 0, 0, 0, 0, 0],
                [6, 0, 0, 0, 0, 0, 0],
            ],
            dtype=np.int64,
        ),
        "token_scalars": np.zeros((4, 3), dtype=np.float32),
        "attention_mask": np.array([True, True, True, True], dtype=bool),
    }
    batch = _collate_structured_token_dicts(
        [d_short, d_long], device=torch.device("cpu"),
    )
    # Shape: 2 rows × 4 columns (max_len from d_long).
    assert tuple(batch["token_type"].shape) == (2, 4)
    assert tuple(batch["token_emb_ids"].shape) == (2, 4, 7)
    assert tuple(batch["token_scalars"].shape) == (2, 4, 3)
    assert tuple(batch["attention_mask"].shape) == (2, 4)
    # Row 0 (the short one) is padded with zeros + False mask in the
    # tail columns; row 1 is fully valid.
    assert batch["token_type"][0, 0].item() == 1
    assert batch["token_type"][0, 1].item() == 2
    assert batch["token_type"][0, 2].item() == 0
    assert batch["token_type"][0, 3].item() == 0
    assert batch["attention_mask"][0].tolist() == [True, True, False, False]
    assert batch["attention_mask"][1].tolist() == [True, True, True, True]


def test_collate_structured_token_dicts_empty_input_raises():
    """An empty token-dict list has no max_len to infer; the helper
    must complain rather than return a malformed batch."""
    with pytest.raises(ValueError, match="non-empty"):
        _collate_structured_token_dicts([], device=torch.device("cpu"))


# ---------------------------------------------------------------------
# from_metadata dispatch
# ---------------------------------------------------------------------


def _make_structured_metadata(tmp_path: Path) -> tuple[Path, Any]:
    """Train a tiny structured evaluator, save its weights, and
    return ``(weights_path, metadata)`` where ``metadata`` is a
    minimal stand-in for ``ModelMetadata`` carrying the structured
    architecture + the trained hyperparams under ``training``."""
    ev = NNEvaluator(**SMALL_KWARGS)
    weights_path = tmp_path / "structured.pt"
    ev.save(weights_path)

    class _MetaStub:
        architecture = ARCHITECTURE_STRUCTURED
        action_encoding_version = "positional_v1"
        hidden_sizes: list[int] = []
        with_policy = True
        training = {
            "structured_emb_dim": 16,
            "structured_n_heads": 2,
            "structured_n_layers": 2,
            "structured_hidden_dim": 32,
            "structured_action_history_n": 4,
            "structured_n_printings": 32,
        }

    return weights_path, _MetaStub()


def test_from_metadata_dispatches_structured(tmp_path: Path):
    """``NNEvaluator.from_metadata`` reads ``architecture='structured'``
    off the metadata and constructs a structured evaluator that loads
    the saved weights cleanly. No weight-shape error and the
    architecture flag round-trips."""
    weights_path, meta = _make_structured_metadata(tmp_path)
    ev = NNEvaluator.from_metadata(weights_path, meta)
    assert ev.is_structured is True
    assert ev.architecture == ARCHITECTURE_STRUCTURED
    assert isinstance(ev.model, StructuredModel)
    # Hyperparams from metadata propagated into the model config.
    assert ev.model.config.emb_dim == 16
    assert ev.model.config.action_history_n == 4
    assert ev.model.config.n_printings == 32


def test_from_metadata_dispatch_uses_architecture_not_weight_shape(
    tmp_path: Path,
):
    """A metadata with a different ``training`` payload but the same
    ``architecture`` still routes through the structured branch — the
    classmethod must dispatch by the metadata field, not by guessing
    from the on-disk weight shape (which would be fragile and would
    silently misroute weights that happen to overlap)."""
    weights_path, meta = _make_structured_metadata(tmp_path)
    # Strip the structured-training keys so only `architecture` selects
    # the branch. The model will fall back to StructuredModelConfig
    # defaults, which won't match the saved weights' shape — but we
    # don't load weights for this test; we just verify routing.
    meta.training = {}
    # Skip the weights load step to avoid the shape mismatch — pass a
    # path that doesn't exist on disk along with a from_metadata
    # call that bypasses loading. The simplest way: construct
    # directly via the helper logic.
    # Instead: re-save with the default-config evaluator so weights
    # match. This is the architecture-only path.
    ev = NNEvaluator(architecture=ARCHITECTURE_STRUCTURED)
    fresh_weights = tmp_path / "default.pt"
    ev.save(fresh_weights)
    routed = NNEvaluator.from_metadata(fresh_weights, meta)
    assert routed.is_structured is True


def test_from_metadata_dispatches_mlp_for_shared_architecture(
    tmp_path: Path,
):
    """Regression: ``architecture='shared'`` still routes to the dual-
    head MLP — Slice E must not change the legacy dispatch path."""
    src = NNEvaluator(with_policy=True, architecture=ARCHITECTURE_SHARED)
    weights_path = tmp_path / "shared.pt"
    src.save(weights_path)

    class _SharedMeta:
        architecture = ARCHITECTURE_SHARED
        action_encoding_version = "positional_v1"
        hidden_sizes = [128, 128, 64]
        with_policy = True
        training: dict[str, Any] = {}

    ev = NNEvaluator.from_metadata(weights_path, _SharedMeta())
    assert ev.is_structured is False
    assert ev.architecture == ARCHITECTURE_SHARED
    assert ev.with_policy is True


def test_from_metadata_dispatches_value_only_for_legacy_metadata(
    tmp_path: Path,
):
    """A minimal stub representing v1/v2-style metadata
    (``with_policy=False``, no architecture key default-mapped to
    ``"shared"``) still loads as a value-only ``_ValueMLP``."""
    src = NNEvaluator()
    weights_path = tmp_path / "value_only.pt"
    src.save(weights_path)

    class _LegacyMeta:
        architecture = ARCHITECTURE_SHARED
        action_encoding_version = "positional_v1"
        hidden_sizes = [128, 128, 64]
        with_policy = False
        training: dict[str, Any] = {}

    ev = NNEvaluator.from_metadata(weights_path, _LegacyMeta())
    assert ev.is_structured is False
    assert ev.with_policy is False


# ---------------------------------------------------------------------
# from_metadata: nested ``structured_config`` layout compat
# ---------------------------------------------------------------------
#
# Background (iter_019 BUG #2): the trainer in ``mtg_bot.cli.train``
# writes a nested ``training.structured_config = {emb_dim, n_heads,
# n_layers, hidden_dim, action_history_n, n_printings}`` dict alongside
# the rest of the training-config knobs. The loader (this module's
# ``from_metadata``) historically only read flat ``structured_emb_dim``
# / ``structured_n_heads`` / ... keys. The mismatch went unnoticed
# until a non-default-trunk bootstrap (v13) tried to load and silently
# fell back to ``StructuredModelConfig`` defaults (128/4/2/256), at
# which point the weight-shape mismatch surfaced loudly. v5 worked as
# bootstrap only because its dims happened to match the defaults.
#
# Fix: ``from_metadata`` resolves each structured dim via
# ``_resolve_structured_dim`` which prefers the flat key (forward-
# compat with existing flat-key metadata, including v13's hand-patched
# variant) and falls back to the nested ``structured_config[key]`` from
# the trainer's writer when the flat key is absent.


def _nested_meta_stub(
    weights_path: Path,
    nested: dict[str, Any],
) -> Any:
    """Minimal stand-in for ``ModelMetadata`` with ONLY the nested
    ``structured_config`` layout — no flat ``structured_*`` keys."""
    class _NestedMeta:
        architecture = ARCHITECTURE_STRUCTURED
        action_encoding_version = "positional_v1"
        hidden_sizes: list[int] = []
        with_policy = True
        training = {"structured_config": dict(nested)}

    return _NestedMeta()


def test_from_metadata_reads_nested_structured_config(tmp_path: Path):
    """Regression for iter_019 BUG #2: the trainer's nested
    ``training.structured_config`` dict must drive the loaded
    evaluator's structured config when the flat ``structured_*`` keys
    are absent. Without the loader-side compat shim the loader silently
    falls back to ``StructuredModelConfig`` defaults and the weight
    shapes don't match the trained network."""
    ev = NNEvaluator(**SMALL_KWARGS)
    weights_path = tmp_path / "structured_nested.pt"
    ev.save(weights_path)

    meta = _nested_meta_stub(
        weights_path,
        nested={
            "emb_dim": SMALL_KWARGS["structured_emb_dim"],
            "n_heads": SMALL_KWARGS["structured_n_heads"],
            "n_layers": SMALL_KWARGS["structured_n_layers"],
            "hidden_dim": SMALL_KWARGS["structured_hidden_dim"],
            "action_history_n": SMALL_KWARGS["structured_action_history_n"],
            "n_printings": SMALL_KWARGS["structured_n_printings"],
        },
    )

    loaded = NNEvaluator.from_metadata(weights_path, meta)
    assert loaded.is_structured is True
    # Each dim resolved from the nested dict, not from the defaults.
    assert loaded.model.config.emb_dim == SMALL_KWARGS["structured_emb_dim"]
    assert loaded.model.config.n_heads == SMALL_KWARGS["structured_n_heads"]
    assert loaded.model.config.n_layers == SMALL_KWARGS["structured_n_layers"]
    assert (
        loaded.model.config.hidden_dim == SMALL_KWARGS["structured_hidden_dim"]
    )
    assert (
        loaded.model.config.action_history_n
        == SMALL_KWARGS["structured_action_history_n"]
    )
    assert (
        loaded.model.config.n_printings
        == SMALL_KWARGS["structured_n_printings"]
    )


def test_from_metadata_flat_keys_still_win_over_nested(tmp_path: Path):
    """Forward-compat: a metadata file with BOTH layouts present (e.g.
    v13's hand-patched workaround, where flat keys were promoted on
    top of the trainer's nested dict) must still resolve to the flat
    values. Flat wins."""
    ev = NNEvaluator(**SMALL_KWARGS)
    weights_path = tmp_path / "structured_both.pt"
    ev.save(weights_path)

    class _BothLayoutsMeta:
        architecture = ARCHITECTURE_STRUCTURED
        action_encoding_version = "positional_v1"
        hidden_sizes: list[int] = []
        with_policy = True
        # Flat keys carry the real dims; nested carries deliberately
        # wrong values so we can detect if the loader prefers nested.
        training = {
            "structured_emb_dim": SMALL_KWARGS["structured_emb_dim"],
            "structured_n_heads": SMALL_KWARGS["structured_n_heads"],
            "structured_n_layers": SMALL_KWARGS["structured_n_layers"],
            "structured_hidden_dim": SMALL_KWARGS["structured_hidden_dim"],
            "structured_action_history_n": (
                SMALL_KWARGS["structured_action_history_n"]
            ),
            "structured_n_printings": SMALL_KWARGS["structured_n_printings"],
            "structured_config": {
                "emb_dim": 999,
                "n_heads": 999,
                "n_layers": 999,
                "hidden_dim": 999,
                "action_history_n": 999,
                "n_printings": 999,
            },
        }

    loaded = NNEvaluator.from_metadata(weights_path, _BothLayoutsMeta())
    assert loaded.model.config.emb_dim == SMALL_KWARGS["structured_emb_dim"]
    assert loaded.model.config.n_heads == SMALL_KWARGS["structured_n_heads"]


def test_from_metadata_no_dim_metadata_falls_back_to_defaults(
    tmp_path: Path,
):
    """When neither layout is present, the loader still falls back to
    ``StructuredModelConfig`` defaults — back-compat with v1/v2-era
    structured metadata (pre-iter_007 retrofitted writers, mostly
    historical at this point)."""
    # Build a default-config structured evaluator so the weights load.
    ev = NNEvaluator(architecture=ARCHITECTURE_STRUCTURED)
    weights_path = tmp_path / "structured_defaults.pt"
    ev.save(weights_path)

    class _EmptyMeta:
        architecture = ARCHITECTURE_STRUCTURED
        action_encoding_version = "positional_v1"
        hidden_sizes: list[int] = []
        with_policy = True
        training: dict[str, Any] = {}

    loaded = NNEvaluator.from_metadata(weights_path, _EmptyMeta())
    assert loaded.is_structured is True
    # Default dims (128/4/2/256/32/320 per StructuredModelConfig).
    assert loaded.model.config.emb_dim == 128
    assert loaded.model.config.n_heads == 4
    assert loaded.model.config.n_layers == 2
    assert loaded.model.config.hidden_dim == 256


def test_from_metadata_trainer_writer_to_loader_reader_roundtrip(
    tmp_path: Path,
):
    """Pin test for the structural fix: a metadata payload constructed
    using EXACTLY the trainer's ``training`` dict shape (see
    ``mtg_bot.cli.train`` lines ~1095-1120 — the structured-architecture
    branch) round-trips through ``from_metadata`` with the trained
    non-default dims preserved. The v13-shape values (emb_dim=256,
    n_heads=8, n_layers=4, hidden_dim=512) are the canonical
    non-default-trunk bootstrap the original bug surfaced on; we use
    the test-tiny dims here so the test doesn't pay for a 40M-param
    forward pass, but the layout is byte-identical to the trainer
    writer's."""
    ev = NNEvaluator(**SMALL_KWARGS)
    weights_path = tmp_path / "structured_roundtrip.pt"
    ev.save(weights_path)

    # Mirror ``train_config['structured_config']`` exactly (cli/train.py).
    trainer_structured_config = {
        "emb_dim": SMALL_KWARGS["structured_emb_dim"],
        "n_heads": SMALL_KWARGS["structured_n_heads"],
        "n_layers": SMALL_KWARGS["structured_n_layers"],
        "hidden_dim": SMALL_KWARGS["structured_hidden_dim"],
        "action_history_n": SMALL_KWARGS["structured_action_history_n"],
        "n_printings": SMALL_KWARGS["structured_n_printings"],
    }

    # Mirror ``ModelMetadata.training`` exactly (cli/train.py: the
    # structured branch writes ``"structured_config":
    # train_config['structured_config']`` inside ``training``).
    class _TrainerWriterMeta:
        architecture = ARCHITECTURE_STRUCTURED
        action_encoding_version = "canonical_v2"
        hidden_sizes: list[int] = []
        with_policy = True
        training = {
            "data_dir": "iterate_data",
            "epochs": 1,
            "batch_size": 256,
            "learning_rate": 1e-3,
            "structured_config": trainer_structured_config,
        }

    loaded = NNEvaluator.from_metadata(weights_path, _TrainerWriterMeta())
    assert loaded.is_structured is True
    cfg = loaded.model.config
    assert cfg.emb_dim == SMALL_KWARGS["structured_emb_dim"]
    assert cfg.n_heads == SMALL_KWARGS["structured_n_heads"]
    assert cfg.n_layers == SMALL_KWARGS["structured_n_layers"]
    assert cfg.hidden_dim == SMALL_KWARGS["structured_hidden_dim"]
    assert cfg.action_history_n == SMALL_KWARGS["structured_action_history_n"]
    assert cfg.n_printings == SMALL_KWARGS["structured_n_printings"]


# ---------------------------------------------------------------------
# Determinism / multi-call consistency
# ---------------------------------------------------------------------


def test_structured_inference_is_deterministic(
    fake_tokenizer, patched_legal_mask,
):
    """Same state, same evaluator, repeated calls — same value +
    policy. The model is in ``eval`` mode (no dropout, no batchnorm)
    and the fake tokenizer is deterministic on input id."""
    ev = NNEvaluator(**SMALL_KWARGS)
    state = _FakeAdapter()
    v1, p1 = ev.evaluate_with_policy(state, player_id=0)
    v2, p2 = ev.evaluate_with_policy(state, player_id=0)
    assert v1 == v2
    np.testing.assert_array_equal(p1, p2)


def test_structured_with_policy_kwarg_is_forced_true(
    fake_tokenizer, patched_legal_mask,
):
    """The structured trunk always has a policy head; the
    ``with_policy=False`` kwarg is silently upgraded to True."""
    ev = NNEvaluator(with_policy=False, **{
        k: v for k, v in SMALL_KWARGS.items() if k != "with_policy"
    })
    assert ev.with_policy is True
    # And evaluate_with_policy works (no RuntimeError).
    state = _FakeAdapter()
    val, pol = ev.evaluate_with_policy(state, player_id=0)
    assert pol.shape == (ACTION_VOCAB_SIZE,)


# ---------------------------------------------------------------------
# Scalar schema: loader picks the projection width from metadata
# ---------------------------------------------------------------------


def _small_kwargs_with_schema(version: int) -> dict[str, Any]:
    kw = dict(SMALL_KWARGS)
    kw["structured_scalar_schema_version"] = version
    return kw


def _small_model_metadata(version_field, *, include_field: bool):
    """Real ``ModelMetadata`` for SMALL_KWARGS; ``include_field=False``
    mimics a pre-v2 metadata.json (no ``scalar_schema_version`` key ->
    ``from_dict`` defaults it to 1)."""
    from mtg_bot.training.registry import ModelMetadata
    d = {
        "version": "v_test",
        "created_at": "2026-01-01T00:00:00Z",
        "feature_dim": 0,
        "hidden_sizes": [],
        "with_policy": True,
        "architecture": ARCHITECTURE_STRUCTURED,
        "action_encoding_version": "positional_v1",
        "training": {
            "structured_emb_dim": SMALL_KWARGS["structured_emb_dim"],
            "structured_n_heads": SMALL_KWARGS["structured_n_heads"],
            "structured_n_layers": SMALL_KWARGS["structured_n_layers"],
            "structured_hidden_dim": SMALL_KWARGS["structured_hidden_dim"],
            "structured_action_history_n": (
                SMALL_KWARGS["structured_action_history_n"]
            ),
            "structured_n_printings": SMALL_KWARGS["structured_n_printings"],
        },
    }
    if include_field:
        d["scalar_schema_version"] = version_field
    return ModelMetadata.from_dict(d)


def test_nn_evaluator_default_schema_is_v2_and_tokenizer_gets_it(
    fake_tokenizer,
):
    from mtg_bot.training.structured_model import N_SCALAR_FIELDS_V2
    ev = NNEvaluator(**SMALL_KWARGS)
    assert ev.model.config.scalar_schema_version == 2
    assert ev.model.scalar_proj.in_features == N_SCALAR_FIELDS_V2
    assert ev._structured_scalar_schema_version == 2


def test_nn_evaluator_explicit_schema_v1_builds_three_wide_projection(
    fake_tokenizer,
):
    ev = NNEvaluator(**_small_kwargs_with_schema(1))
    assert ev.model.scalar_proj.in_features == 3
    assert ev._structured_scalar_schema_version == 1
    # Inference goes through the stub tokenizer which honours the
    # requested schema width — the forward must succeed on 3-wide rows.
    v = ev.evaluate(_FakeAdapter(), player_id=0)
    assert -1.0 <= v <= 1.0


@pytest.mark.parametrize("version", [1, 2])
def test_from_metadata_picks_scalar_width_from_metadata(
    tmp_path: Path, version: int,
):
    from mtg_bot.training.structured_model import scalar_width_for_schema
    ev = NNEvaluator(**_small_kwargs_with_schema(version))
    weights_path = tmp_path / f"structured_v{version}.pt"
    ev.save(weights_path)
    meta = _small_model_metadata(version, include_field=True)
    assert meta.scalar_schema_version == version
    loaded = NNEvaluator.from_metadata(weights_path, meta)
    assert loaded.model.config.scalar_schema_version == version
    assert (
        loaded.model.scalar_proj.in_features
        == scalar_width_for_schema(version)
    )
    assert loaded._structured_scalar_schema_version == version


def test_from_metadata_without_field_loads_legacy_v1_weights(
    tmp_path: Path,
):
    """A metadata.json that predates ``scalar_schema_version`` (every
    v1..v14 / v13s checkpoint) must load as schema 1 with a 3-wide
    ``scalar_proj`` — identical to pre-feature behaviour."""
    ev = NNEvaluator(**_small_kwargs_with_schema(1))
    weights_path = tmp_path / "legacy.pt"
    ev.save(weights_path)
    meta = _small_model_metadata(None, include_field=False)
    assert meta.scalar_schema_version == 1
    loaded = NNEvaluator.from_metadata(weights_path, meta)
    assert loaded.model.config.scalar_schema_version == 1
    assert loaded.model.scalar_proj.in_features == 3


def test_from_metadata_field_mismatch_fails_loudly(tmp_path: Path):
    """Metadata claiming schema 1 for weights trained on schema 2
    surfaces as the usual load_state_dict size-mismatch error."""
    ev = NNEvaluator(**_small_kwargs_with_schema(2))
    weights_path = tmp_path / "v2_weights.pt"
    ev.save(weights_path)
    meta = _small_model_metadata(1, include_field=True)
    with pytest.raises(RuntimeError, match="size mismatch"):
        NNEvaluator.from_metadata(weights_path, meta)


def test_from_metadata_stand_in_reads_schema_from_training_dict(
    tmp_path: Path,
):
    """Duck-typed metadata without the top-level attribute falls back
    to ``training.structured_config.scalar_schema_version``."""
    ev = NNEvaluator(**_small_kwargs_with_schema(1))
    weights_path = tmp_path / "nested_schema.pt"
    ev.save(weights_path)
    meta = _nested_meta_stub(
        weights_path,
        nested={
            "emb_dim": SMALL_KWARGS["structured_emb_dim"],
            "n_heads": SMALL_KWARGS["structured_n_heads"],
            "n_layers": SMALL_KWARGS["structured_n_layers"],
            "hidden_dim": SMALL_KWARGS["structured_hidden_dim"],
            "action_history_n": SMALL_KWARGS["structured_action_history_n"],
            "n_printings": SMALL_KWARGS["structured_n_printings"],
            "scalar_schema_version": 1,
        },
    )
    loaded = NNEvaluator.from_metadata(weights_path, meta)
    assert loaded.model.scalar_proj.in_features == 3


def test_collate_structured_token_dicts_rejects_mixed_widths():
    d3 = {
        "token_type": np.array([1], dtype=np.int64),
        "token_emb_ids": np.zeros((1, 7), dtype=np.int64),
        "token_scalars": np.zeros((1, 3), dtype=np.float32),
        "attention_mask": np.array([True]),
    }
    d29 = dict(d3)
    d29["token_scalars"] = np.zeros((1, 29), dtype=np.float32)
    with pytest.raises(ValueError, match="scalar_schema_version"):
        _collate_structured_token_dicts([d3, d29], device=torch.device("cpu"))
