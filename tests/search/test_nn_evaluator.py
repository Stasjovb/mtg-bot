"""Tests for ``mtg_bot.search.nn_evaluator.NNEvaluator``.

Phase C scaffolding: no training in this PR, so these tests cover
the *infrastructure* (architecture, save/load, integration with the
search stack) rather than play strength. Phase D adds tests that
actually train and assert "trained NN beats heuristic in self-play."
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import torch

from mtg_bot.agents import RandomAgent
from mtg_bot.features import FEATURE_DIM
from mtg_bot.search import (
    Budget, MCTS, MtgGameStateAdapter, NNEvaluator,
)
from mtg_bot.search.nn_evaluator import (
    ARCHITECTURE_SEPARATE,
    ARCHITECTURE_SHARED,
    HIDDEN_SIZES,
    _ValueMLP,
    _ValuePolicyMLP,
    _ValuePolicyMLPSeparate,
    _build_dual_head_model,
)
from mtg_bot.simulate import setup_game
from mtg_bot.training.action_encoding import (
    ACTION_VOCAB_SIZE, legal_action_mask,
)
from tests._test_decks import simple_test_decklists


def _adapter(seed: int = 42) -> MtgGameStateAdapter:
    state = setup_game([RandomAgent(), RandomAgent()], decks=simple_test_decklists(), seed=seed,
    )
    return MtgGameStateAdapter(state)


# ---------- architecture ----------------------------------------------------


def test_value_mlp_input_output_shape():
    net = _ValueMLP()
    batch = torch.zeros(4, FEATURE_DIM)
    out = net(batch)
    assert out.shape == (4, 1)


def test_value_mlp_output_is_in_unit_interval():
    """Tanh on the last layer must keep outputs in [-1, 1] regardless
    of input magnitude. Smoke this with extreme inputs to confirm."""
    net = _ValueMLP()
    extreme = torch.full((8, FEATURE_DIM), 1e6)
    out = net(extreme)
    assert torch.all(out >= -1.0)
    assert torch.all(out <= 1.0)


def test_value_mlp_parameter_count_is_reasonable():
    """Sanity check on architecture size — bumping past the upper
    bound unintentionally would mean we lost track of
    ``HIDDEN_SIZES``."""
    net = _ValueMLP()
    total = sum(p.numel() for p in net.parameters())
    # Current 51→512→512→256→1 is ~420k params. The pre-2026-05-02
    # default 51→128→128→64→1 was ~25k. Cap at 2M as a sanity
    # ceiling — a value-only net beyond that starts overfitting at
    # our data scale.
    assert 1_000 <= total <= 2_000_000, (
        f"network has {total} params; expected 1k–2M for the "
        f"default HIDDEN_SIZES={HIDDEN_SIZES}"
    )


# ---------- NNEvaluator: random init ----------------------------------------


def test_nn_evaluator_default_init_returns_random_value_in_range():
    """Untrained network should still return a finite value in
    [-1, 1] for any input — tanh on the output guarantees the
    range, weight init guarantees finiteness."""
    evaluator = NNEvaluator()
    adapter = _adapter()
    value = evaluator.evaluate(adapter, player_id=0)
    assert isinstance(value, float)
    assert np.isfinite(value)
    assert -1.0 <= value <= 1.0


def test_nn_evaluator_inference_is_deterministic():
    """Same network, same state, same player → same value across
    repeated calls. (Trivially true since model.eval() + no dropout,
    but worth pinning.)"""
    evaluator = NNEvaluator()
    adapter = _adapter()
    a = evaluator.evaluate(adapter, player_id=0)
    b = evaluator.evaluate(adapter, player_id=0)
    assert a == b


def test_nn_evaluator_different_states_can_give_different_values():
    """Sanity: swapping the viewer or moving to a different state
    should be able to produce different values (random network, but
    inputs differ)."""
    evaluator = NNEvaluator()
    a = _adapter(seed=42)
    b = _adapter(seed=99)
    val_a = evaluator.evaluate(a, player_id=0)
    val_b = evaluator.evaluate(b, player_id=0)
    # Random network — usually different, but not guaranteed. A loose
    # check: at least one of (different state, different viewer) gives
    # a different value.
    val_a_p1 = evaluator.evaluate(a, player_id=1)
    assert val_a != val_b or val_a != val_a_p1, (
        "evaluator collapsed all inputs to the same value — likely a "
        "feature-extraction or forward-pass bug"
    )


# ---------- terminal short-circuit ------------------------------------------


def test_nn_evaluator_returns_plus_one_for_winning_terminal():
    """The Evaluator base class short-circuits terminal states to
    ±1 / 0 without consulting _evaluate_nonterminal. NNEvaluator
    inherits that for free; verify it works."""
    adapter = _adapter()
    # Force a terminal where P0 won.
    adapter.engine_state.players[1].has_lost = True
    adapter.engine_state.winner_id = 0
    assert adapter.is_terminal()
    evaluator = NNEvaluator()
    assert evaluator.evaluate(adapter, player_id=0) == 1.0
    assert evaluator.evaluate(adapter, player_id=1) == -1.0


# ---------- save / load -----------------------------------------------------


def test_nn_evaluator_save_and_load_round_trip(tmp_path: Path):
    """Save weights, load into a fresh evaluator, check that both
    evaluate to the same value on the same state."""
    a = NNEvaluator()
    weights_path = tmp_path / "weights.pt"
    a.save(weights_path)
    assert weights_path.exists()

    b = NNEvaluator(weights_path=weights_path)

    adapter = _adapter()
    val_a = a.evaluate(adapter, player_id=0)
    val_b = b.evaluate(adapter, player_id=0)
    assert val_a == val_b


def test_loaded_weights_differ_from_random_init(tmp_path: Path):
    """Two NNEvaluators with no weights given are random-initialized
    with different weights (assuming default torch RNG state moves
    forward between constructors). Loading from a saved file should
    reproduce the saved weights, not give yet another random init."""
    saver = NNEvaluator()
    weights_path = tmp_path / "saved.pt"
    saver.save(weights_path)

    fresh_random = NNEvaluator()
    loaded = NNEvaluator(weights_path=weights_path)

    adapter = _adapter()
    saver_val = saver.evaluate(adapter, player_id=0)
    fresh_val = fresh_random.evaluate(adapter, player_id=0)
    loaded_val = loaded.evaluate(adapter, player_id=0)

    # Loaded matches saver.
    assert loaded_val == saver_val
    # Fresh-random typically differs from saver (if torch's global
    # RNG state advanced between constructions).
    # We assert that loaded is NOT equal to fresh_random — which would
    # be the case if "load" was silently a no-op.
    assert loaded_val != fresh_val or saver_val == fresh_val, (
        "loaded value matches a fresh random init — "
        "weights may not have actually loaded"
    )


# ---------- integration with MCTS -------------------------------------------


def test_nn_evaluator_drives_mcts_without_crashing():
    """Drop NNEvaluator into MCTS and confirm it can return a legal
    decision against the real engine. Smoke test — untrained net, so
    decision quality is meaningless. Just verifies the wiring."""
    adapter = _adapter()
    evaluator = NNEvaluator()
    mcts = MCTS(
        evaluator=evaluator,
        budget_factory=lambda: Budget(max_nodes=8),
        rng=__import__("random").Random(0),
    )
    legal = adapter.legal_decisions()
    decision = mcts.choose(adapter, adapter.active_player())
    assert decision in legal


# ---------- dual-head architecture (A4) -------------------------------------


def test_value_policy_mlp_forward_shape():
    """Synthetic batch through ``_ValuePolicyMLP`` returns the right
    shapes from each head. Pinning the dual-tuple contract: shape
    ``(B, 1)`` value + ``(B, ACTION_VOCAB_SIZE)`` policy."""
    net = _ValuePolicyMLP()
    x = torch.zeros(8, FEATURE_DIM)
    value, policy = net(x)
    assert value.shape == (8, 1)
    assert policy.shape == (8, ACTION_VOCAB_SIZE)
    # Value-head tanh keeps outputs in [-1, 1] — sanity-pin the same
    # contract that ``_ValueMLP`` provides.
    assert torch.all(value >= -1.0) and torch.all(value <= 1.0)


def test_value_policy_mlp_param_count_is_reasonable():
    """Param count for the dual-head architecture should be modestly
    larger than the value-only baseline — most of the delta comes
    from the policy head (h_last × ACTION_VOCAB_SIZE + ACTION_VOCAB_SIZE
    ≈ 33k extra at the current shapes). 60k total is the headline
    number to sanity-check; cap at 150k as the upper sanity bound
    (anything past that means HIDDEN_SIZES drifted)."""
    net = _ValuePolicyMLP()
    total = sum(p.numel() for p in net.parameters())
    # Lower bound: ~30k; upper bound: 150k.
    assert 30_000 <= total <= 150_000, (
        f"_ValuePolicyMLP has {total} params; expected ~30k-150k for "
        f"HIDDEN_SIZES={HIDDEN_SIZES} + policy_dim={ACTION_VOCAB_SIZE}"
    )


def test_evaluate_with_policy_returns_legal_distribution():
    """Run a forward pass over a real engine state, confirm the
    returned policy is a valid distribution over the legal slots:
    sums to 1.0, illegal slots are exactly 0.0, legal slots are
    strictly positive (softmax of a finite logit > 0)."""
    evaluator = NNEvaluator(with_policy=True)
    adapter = _adapter()
    value, policy = evaluator.evaluate_with_policy(adapter, player_id=0)
    assert isinstance(value, float)
    assert -1.0 <= value <= 1.0
    assert policy.shape == (ACTION_VOCAB_SIZE,)
    assert policy.dtype == np.float32

    mask = legal_action_mask(adapter, viewer=0)
    # Sanity: at least one legal action — the engine wouldn't be
    # asking for a decision otherwise.
    assert mask.any(), "no legal actions on the chosen seed; pick another"

    # Illegal slots are exactly 0.
    np.testing.assert_array_equal(policy[~mask], 0.0)
    # Legal slots are positive (softmax of finite logits).
    assert np.all(policy[mask] > 0.0)
    # Distribution sums to 1.
    assert policy.sum() == pytest.approx(1.0, rel=0, abs=1e-5)


def test_evaluate_with_policy_handles_terminal_state():
    """Terminal short-circuit: returns the right value sign without
    touching the network, plus an all-zeros policy because no
    decision is taken at a terminal."""
    adapter = _adapter()
    # Force a terminal where P0 won.
    adapter.engine_state.players[1].has_lost = True
    adapter.engine_state.winner_id = 0
    assert adapter.is_terminal()
    evaluator = NNEvaluator(with_policy=True)

    val_p0, pol_p0 = evaluator.evaluate_with_policy(adapter, player_id=0)
    val_p1, pol_p1 = evaluator.evaluate_with_policy(adapter, player_id=1)

    assert val_p0 == 1.0
    assert val_p1 == -1.0
    np.testing.assert_array_equal(
        pol_p0, np.zeros(ACTION_VOCAB_SIZE, dtype=np.float32),
    )
    np.testing.assert_array_equal(
        pol_p1, np.zeros(ACTION_VOCAB_SIZE, dtype=np.float32),
    )


def test_batch_evaluate_with_policy_matches_per_state():
    """Stacking 8 adapters into one batched call should return the
    same per-state result as 8 individual ``evaluate_with_policy``
    calls (within float-rounding tolerance — same forward pass, same
    masking, just different batch axis on the matmul)."""
    evaluator = NNEvaluator(with_policy=True)
    adapters = [_adapter(seed=s) for s in range(8)]

    per_state = [
        evaluator.evaluate_with_policy(a, player_id=0) for a in adapters
    ]
    batched = evaluator.batch_evaluate_with_policy(adapters, player_id=0)

    assert len(per_state) == len(batched)
    for (v_a, p_a), (v_b, p_b) in zip(per_state, batched):
        assert v_a == pytest.approx(v_b, abs=1e-5)
        np.testing.assert_allclose(p_a, p_b, atol=1e-5, rtol=0)


def test_save_load_round_trip_dual_head(tmp_path: Path):
    """One synthetic training step (a manual SGD update on a random
    target), save weights, reload via ``with_policy=True``, predictions
    match. The training step proves the save format reflects post-
    update weights, not just the random init that would round-trip
    trivially through any save format."""
    a = NNEvaluator(with_policy=True)
    # Synthetic gradient step: random input, random value+policy
    # targets, MSE on value + cross-entropy on policy. Torch's
    # cross_entropy expects raw logits + target indices, so we use
    # a dummy target index for the policy head.
    a.model.train()
    optimizer = torch.optim.SGD(a.model.parameters(), lr=0.01)
    x = torch.randn(4, FEATURE_DIM)
    target_value = torch.zeros(4, 1)
    target_policy_idx = torch.zeros(4, dtype=torch.long)
    value, logits = a.model(x)
    loss = (
        ((value - target_value) ** 2).mean()
        + torch.nn.functional.cross_entropy(logits, target_policy_idx)
    )
    optimizer.zero_grad()
    loss.backward()
    optimizer.step()
    a.model.eval()

    weights_path = tmp_path / "weights.pt"
    a.save(weights_path)
    assert weights_path.exists()

    b = NNEvaluator(weights_path=weights_path, with_policy=True)

    adapter = _adapter()
    val_a, pol_a = a.evaluate_with_policy(adapter, player_id=0)
    val_b, pol_b = b.evaluate_with_policy(adapter, player_id=0)
    assert val_a == val_b
    np.testing.assert_array_equal(pol_a, pol_b)


def test_evaluate_with_policy_requires_with_policy_flag():
    """Calling ``evaluate_with_policy`` on a value-only evaluator
    is a programming error — surface it loudly rather than silently
    returning bogus output. Same contract for the batched call."""
    evaluator = NNEvaluator()  # default: with_policy=False
    adapter = _adapter()
    with pytest.raises(RuntimeError, match="with_policy=True"):
        evaluator.evaluate_with_policy(adapter, player_id=0)
    with pytest.raises(RuntimeError, match="with_policy=True"):
        evaluator.batch_evaluate_with_policy([adapter], player_id=0)


def test_value_only_path_still_uses_value_mlp():
    """Backward-compat invariant: ``with_policy=False`` (default)
    must instantiate ``_ValueMLP`` so v1/v2 weight loading + bit-
    exact inference is preserved."""
    evaluator = NNEvaluator()
    assert isinstance(evaluator.model, _ValueMLP)
    assert evaluator.with_policy is False


def test_with_policy_path_uses_value_policy_mlp():
    """Mirror of the above for the dual-head path."""
    evaluator = NNEvaluator(with_policy=True)
    assert isinstance(evaluator.model, _ValuePolicyMLP)
    assert evaluator.with_policy is True


def test_batch_evaluate_with_policy_handles_empty_input():
    """Empty input → empty output. Mirrors ``batch_evaluate``."""
    evaluator = NNEvaluator(with_policy=True)
    assert evaluator.batch_evaluate_with_policy([], player_id=0) == []


def test_batch_evaluate_with_policy_mixes_terminal_and_nonterminal():
    """Mixed batch: terminal states short-circuit per element while
    non-terminal states go through the network in a single forward
    pass. Result list preserves input order."""
    evaluator = NNEvaluator(with_policy=True)
    nonterm = _adapter(seed=42)
    term = _adapter(seed=99)
    term.engine_state.players[1].has_lost = True
    term.engine_state.winner_id = 0
    assert term.is_terminal()
    assert not nonterm.is_terminal()

    out = evaluator.batch_evaluate_with_policy(
        [nonterm, term, nonterm], player_id=0,
    )
    assert len(out) == 3
    # Terminal P0-win value is 1.0, all-zero policy.
    val_t, pol_t = out[1]
    assert val_t == 1.0
    np.testing.assert_array_equal(
        pol_t, np.zeros(ACTION_VOCAB_SIZE, dtype=np.float32),
    )
    # Non-terminal slots match per-state path.
    val_n0, pol_n0 = out[0]
    val_n2, pol_n2 = out[2]
    val_ref, pol_ref = evaluator.evaluate_with_policy(nonterm, player_id=0)
    assert val_n0 == pytest.approx(val_ref, abs=1e-5)
    assert val_n2 == pytest.approx(val_ref, abs=1e-5)
    np.testing.assert_allclose(pol_n0, pol_ref, atol=1e-5, rtol=0)
    np.testing.assert_allclose(pol_n2, pol_ref, atol=1e-5, rtol=0)


# ---------- separate-trunks architecture ------------------------------------


def test_value_policy_mlp_separate_forward_shape():
    """Synthetic batch through ``_ValuePolicyMLPSeparate`` returns the
    same dual-tuple shape as the shared-trunk variant: ``(B, 1)`` value
    + ``(B, ACTION_VOCAB_SIZE)`` policy. Same public contract."""
    net = _ValuePolicyMLPSeparate()
    x = torch.zeros(8, FEATURE_DIM)
    value, policy = net(x)
    assert value.shape == (8, 1)
    assert policy.shape == (8, ACTION_VOCAB_SIZE)
    assert torch.all(value >= -1.0) and torch.all(value <= 1.0)


def test_value_policy_mlp_separate_state_dict_has_both_trunks():
    """State_dict layout pin: separate-trunks model exposes both
    ``value_trunk.*`` and ``policy_trunk.*`` keys (vs the shared
    variant's single ``trunk.*``). Catches accidental sharing-by-
    aliasing in the constructor."""
    net = _ValuePolicyMLPSeparate()
    keys = set(net.state_dict().keys())
    assert any(k.startswith("value_trunk.") for k in keys), keys
    assert any(k.startswith("policy_trunk.") for k in keys), keys
    assert any(k.startswith("value_head.") for k in keys), keys
    assert any(k.startswith("policy_head.") for k in keys), keys
    # No bare ``trunk.*`` keys (those come from the shared variant).
    assert not any(
        k.startswith("trunk.") for k in keys
    ), f"unexpected shared-trunk keys: {keys}"


def test_value_policy_mlp_separate_param_count_exceeds_shared():
    """Parallel-trunks variant has roughly 2x the trunk parameters of
    the shared variant at the same hidden_sizes (heads are unchanged
    so the delta is exactly one extra trunk worth of weights)."""
    shared = _ValuePolicyMLP()
    separate = _ValuePolicyMLPSeparate()
    shared_params = sum(p.numel() for p in shared.parameters())
    separate_params = sum(p.numel() for p in separate.parameters())
    # The extra trunk adds at least the input→hidden_sizes[0] and
    # any subsequent hidden-to-hidden Linear layers — well over zero.
    assert separate_params > shared_params, (
        f"separate {separate_params} not > shared {shared_params}"
    )


def test_value_policy_mlp_separate_supports_asymmetric_policy_trunk():
    """A custom ``policy_hidden_sizes`` lets the policy_trunk diverge
    from the value_trunk. The two trunks become independently sized."""
    net = _ValuePolicyMLPSeparate(
        hidden_sizes=(64, 32),
        policy_hidden_sizes=(128, 128, 64),
    )
    x = torch.zeros(2, FEATURE_DIM)
    value, policy = net(x)
    assert value.shape == (2, 1)
    assert policy.shape == (2, ACTION_VOCAB_SIZE)


def test_build_dual_head_model_dispatch():
    """``_build_dual_head_model`` returns the right class for each
    architecture string and raises on unknown values."""
    shared = _build_dual_head_model(ARCHITECTURE_SHARED)
    separate = _build_dual_head_model(ARCHITECTURE_SEPARATE)
    assert isinstance(shared, _ValuePolicyMLP)
    assert isinstance(separate, _ValuePolicyMLPSeparate)
    with pytest.raises(ValueError, match="unknown architecture"):
        _build_dual_head_model("nonsense")
    # ``structured`` is recognized but routes through a separate
    # trainer — this MLP-flavored builder must reject it loudly so a
    # future caller can't accidentally instantiate an MLP trunk for a
    # structured-architecture version.
    with pytest.raises(
        ValueError, match="train_structured_model",
    ):
        _build_dual_head_model("structured")


def test_nn_evaluator_separate_architecture_uses_separate_class():
    """``NNEvaluator(with_policy=True, architecture="separate")``
    instantiates ``_ValuePolicyMLPSeparate`` rather than the shared
    variant — the dispatch the loader relies on."""
    ev = NNEvaluator(
        with_policy=True, architecture=ARCHITECTURE_SEPARATE,
    )
    assert isinstance(ev.model, _ValuePolicyMLPSeparate)
    assert ev.architecture == ARCHITECTURE_SEPARATE


def test_nn_evaluator_default_architecture_is_shared():
    """Back-compat: ``NNEvaluator(with_policy=True)`` without an
    explicit architecture still builds the shared-trunk class so
    v1-v15 weights load unchanged."""
    ev = NNEvaluator(with_policy=True)
    assert isinstance(ev.model, _ValuePolicyMLP)
    assert ev.architecture == ARCHITECTURE_SHARED


def test_nn_evaluator_rejects_unknown_architecture():
    """Loud failure for typos / invalid architecture strings rather
    than silent fall-through to a default."""
    with pytest.raises(ValueError, match="architecture"):
        NNEvaluator(with_policy=True, architecture="nonsense")


def test_nn_evaluator_separate_save_load_round_trip(tmp_path: Path):
    """One synthetic SGD step on a separate-trunks model, save weights,
    reload through ``NNEvaluator(architecture="separate")``, predictions
    match. Pins that the state_dict format the trainer writes for
    separate matches what NNEvaluator reads at load time."""
    a = NNEvaluator(
        with_policy=True, architecture=ARCHITECTURE_SEPARATE,
    )
    a.model.train()
    optimizer = torch.optim.SGD(a.model.parameters(), lr=0.01)
    x = torch.randn(4, FEATURE_DIM)
    target_value = torch.zeros(4, 1)
    target_policy_idx = torch.zeros(4, dtype=torch.long)
    value, logits = a.model(x)
    loss = (
        ((value - target_value) ** 2).mean()
        + torch.nn.functional.cross_entropy(logits, target_policy_idx)
    )
    optimizer.zero_grad()
    loss.backward()
    optimizer.step()
    a.model.eval()

    weights_path = tmp_path / "sep.pt"
    a.save(weights_path)
    assert weights_path.exists()

    b = NNEvaluator(
        weights_path=weights_path,
        with_policy=True,
        architecture=ARCHITECTURE_SEPARATE,
    )
    adapter = _adapter()
    val_a, pol_a = a.evaluate_with_policy(adapter, player_id=0)
    val_b, pol_b = b.evaluate_with_policy(adapter, player_id=0)
    assert val_a == val_b
    np.testing.assert_array_equal(pol_a, pol_b)


def test_nn_evaluator_separate_weights_dont_load_into_shared(
    tmp_path: Path,
):
    """Cross-loading is rejected loudly: a separate-trunks state_dict
    does not match a shared-trunk model's keys, and PyTorch raises
    on the load. The two architectures are distinct schemas — the
    metadata-driven dispatch is the only correct way to load them."""
    a = NNEvaluator(
        with_policy=True, architecture=ARCHITECTURE_SEPARATE,
    )
    weights_path = tmp_path / "sep.pt"
    a.save(weights_path)
    with pytest.raises(RuntimeError):
        NNEvaluator(
            weights_path=weights_path,
            with_policy=True,
            architecture=ARCHITECTURE_SHARED,
        )
