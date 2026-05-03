"""Tests for the AlphaZero-style PUCT path through ``MCTS``.

Backward compat (``puct=False``) is covered by the rest of the
``tests/search/`` suite; the assertions here all toggle PUCT on and
exercise the prior plumbing that comes with it:

- Construction-time validation: ``puct=True`` rejects evaluators that
  can't produce a policy.
- ``_Node.puct_score`` formula at the unvisited and visited regimes.
- End-to-end search on a real MTG state with a dual-head NN evaluator
  — proves the prior cache, the encode call, and the PUCT descent
  all wire together.
- The cache itself: priors come from ``_policy_cache``, and the
  evaluator is queried at most once per node.
"""

from __future__ import annotations

import math
import random

import numpy as np
import pytest

from mtg_bot.agents import RandomAgent
from mtg_bot.search import (
    Budget, MCTS, MtgGameStateAdapter, NNEvaluator,
    RandomRolloutEvaluator,
)
from mtg_bot.search.mcts import _Node
from mtg_bot.simulate import setup_game
from mtg_bot.training import action_encoding as ae


# ---------- helpers ---------------------------------------------------------


def _adapter(seed: int = 42) -> MtgGameStateAdapter:
    state = setup_game(
        [RandomAgent(), RandomAgent()], ["G", "R"], seed=seed,
    )
    return MtgGameStateAdapter(state)


class _CountingPolicyEvaluator:
    """Tiny ``Evaluator``-shaped object that returns a uniform-over-
    vocab policy and counts ``evaluate_with_policy`` calls keyed by
    ``id(state)``. Lets us assert "exactly one forward pass per node"
    without depending on torch internals.

    Returns 0.0 for the value (the search-side prior plumbing is what
    the tests care about; backprop value doesn't matter here)."""

    def __init__(self) -> None:
        self.calls_by_state: dict[int, int] = {}

    def evaluate(self, state, player_id):
        # Match base Evaluator's terminal short-circuit so unit calls
        # of ``_evaluate_leaf`` on terminals still produce a sane
        # value when this is plugged in for those tests.
        if state.is_terminal():
            winner = state.winner()
            if winner is None:
                return 0.0
            return 1.0 if winner == player_id else -1.0
        return 0.0

    def batch_evaluate(self, states, player_id):
        return [self.evaluate(s, player_id) for s in states]

    def evaluate_with_policy(self, state, player_id):
        self.calls_by_state[id(state)] = (
            self.calls_by_state.get(id(state), 0) + 1
        )
        if state.is_terminal():
            return 0.0, np.zeros(
                ae.ACTION_VOCAB_SIZE, dtype=np.float32,
            )
        # Uniform over legal slots (0 elsewhere) — a believable
        # untrained-network policy and easy to reason about.
        mask = ae.legal_action_mask(state, player_id)
        n_legal = int(mask.sum())
        if n_legal == 0:
            return 0.0, np.zeros(
                ae.ACTION_VOCAB_SIZE, dtype=np.float32,
            )
        policy = np.zeros(ae.ACTION_VOCAB_SIZE, dtype=np.float32)
        policy[mask] = 1.0 / n_legal
        return 0.0, policy


# ---------- construction-time validation ------------------------------------


def test_mcts_constructor_validates_puct_evaluator_has_policy():
    """``puct=True`` with a value-only evaluator must fail loudly at
    construction, not later in the middle of a search."""
    evaluator = RandomRolloutEvaluator(rng=random.Random(0))
    with pytest.raises(ValueError, match="evaluate_with_policy"):
        MCTS(
            evaluator=evaluator,
            budget_factory=lambda: Budget(max_nodes=10),
            rng=random.Random(0),
            puct=True,
        )


def test_mcts_puct_default_is_false_and_skips_validation():
    """The default path must not require a policy-capable evaluator —
    that's the whole point of the back-compat invariant."""
    evaluator = RandomRolloutEvaluator(rng=random.Random(0))
    mcts = MCTS(
        evaluator=evaluator,
        budget_factory=lambda: Budget(max_nodes=10),
        rng=random.Random(0),
    )
    assert mcts.puct is False


def test_mcts_puct_with_batch_size_gt_1_requires_batched_policy_fn():
    """PUCT + batched eval is supported when the evaluator exposes
    ``batch_evaluate_with_policy``; otherwise it must fail loudly at
    construction. Catches partially-implemented evaluators that
    define ``evaluate_with_policy`` (single) but forgot the batched
    companion. ``_CountingPolicyEvaluator`` only ships the single
    form, so it's the natural fixture for this assertion."""
    eval_ = _CountingPolicyEvaluator()
    with pytest.raises(ValueError, match="batch_evaluate_with_policy"):
        MCTS(
            evaluator=eval_,
            budget_factory=lambda: Budget(max_nodes=10),
            rng=random.Random(0),
            puct=True,
            batch_size=4,
        )


# ---------- ``_Node.puct_score`` formula ------------------------------------


def test_puct_score_pure_prior_when_unvisited():
    """At ``N_child = 0``, PUCT score collapses to
    ``c · prior · √N_parent / 1`` — no exploit term, all explore.
    Mathematically equivalent to ``c · P · √N_parent``."""
    node = _Node(state=None)  # state unused for the score
    node.prior = 0.4
    parent_visits = 9
    c = math.sqrt(2)
    expected = c * 0.4 * math.sqrt(parent_visits) / 1
    assert node.puct_score(parent_visits, c) == pytest.approx(expected)


def test_puct_score_with_zero_prior_is_zero_when_unvisited():
    """``prior=0`` and ``N=0`` → 0. Edge case for unencodable
    decisions where we leave the prior at the default."""
    node = _Node(state=None)
    assert node.puct_score(parent_visits=10, c=1.5) == pytest.approx(0.0)


def test_puct_score_combines_q_and_prior_when_visited():
    """At ``N_child > 0``, PUCT = Q + c · P · √N_parent / (1 + N).
    Q is ``total_value / visits`` (matching UCB1's exploit term)."""
    node = _Node(state=None)
    node.prior = 0.25
    node.visits = 3
    node.total_value = 1.5  # Q = 0.5
    parent_visits = 12
    c = math.sqrt(2)
    expected = 0.5 + c * 0.25 * math.sqrt(parent_visits) / (1 + 3)
    assert node.puct_score(parent_visits, c) == pytest.approx(expected)


def test_puct_score_respects_virtual_loss():
    """Virtual loss is layered on the same way UCB1 does it: augment
    the visit count and subtract the loss from total_value when
    computing Q. Ensures batched-eval virtual-loss bookkeeping won't
    re-break PUCT once the batched-with-policy path lands."""
    node = _Node(state=None)
    node.prior = 0.5
    node.visits = 2
    node.total_value = 1.0  # Q would be 0.5 without VL
    node.virtual_loss = 1
    parent_visits = 10
    c = 1.0
    n = 2 + 1
    exploit = (1.0 - 1) / n
    explore = c * 0.5 * math.sqrt(parent_visits) / (1 + n)
    expected = exploit + explore
    assert node.puct_score(parent_visits, c) == pytest.approx(expected)


# ---------- end-to-end ------------------------------------------------------


def test_puct_with_dual_head_runs_end_to_end():
    """Build the full pipeline with random-init dual-head weights and
    drive a real MTG state. Goal: prove the prior plumbing, the
    encode call, and PUCT descent all coexist; we don't assert on
    play strength (random weights have none)."""
    adapter = _adapter(seed=7)
    evaluator = NNEvaluator(with_policy=True)
    mcts = MCTS(
        evaluator=evaluator,
        budget_factory=lambda: Budget(max_nodes=50),
        rng=random.Random(11),
        puct=True,
        batch_size=1,
    )
    visits = mcts.choose_with_visits(adapter, adapter.active_player())
    # Forced-move adapters return ``{decision: 1}``; real searches
    # produce a multi-entry visit dict. Either is acceptable proof
    # that we ran without exception.
    assert visits, "PUCT search returned an empty visit dict"
    total_visits = sum(visits.values())
    assert total_visits >= 1


def test_puct_priors_match_evaluator_policy():
    """After expansion, every child's ``prior`` equals
    ``parent._policy_cache[encode(decision, eng, root_player)]``.
    Catches off-by-one or wrong-viewer mistakes in the prior path."""
    adapter = _adapter(seed=13)
    eval_ = _CountingPolicyEvaluator()
    mcts = MCTS(
        evaluator=eval_,
        budget_factory=lambda: Budget(max_nodes=20),
        rng=random.Random(0),
        puct=True,
    )
    root_player = adapter.active_player()
    visits = mcts.choose_with_visits(adapter, root_player)
    if not visits:
        pytest.skip(
            "search produced no children — adapter forced a move; "
            "uninteresting for this test"
        )
    # Reach into MCTS to get the root we just built. Easier than
    # re-running: rebuild a single iteration through ``_select_and_
    # expand`` and inspect the resulting tree.
    root = _Node(
        state=adapter.clone(),
        pending_decisions=mcts.expansion_policy.make_decision_iterator(
            adapter,
        ),
    )
    # Force-expand the root by walking children until the iterator
    # is drained. Easiest: call _select_and_expand a handful of
    # times to populate children.
    for _ in range(20):
        mcts._select_and_expand(root, root_player)
    assert root._policy_cache is not None, (
        "expanding any child must populate the root's policy cache"
    )
    for child in root.children:
        eng = getattr(root.state, "engine_state", root.state)
        try:
            slot = ae.encode(child.decision, eng, root_player)
        except ae.EncodingOverflowError:
            # Unencodable decision → prior left at 0; skip the
            # equality check.
            assert child.prior == pytest.approx(0.0)
            continue
        assert child.prior == pytest.approx(
            float(root._policy_cache[slot])
        ), (
            f"child for decision={child.decision!r} has prior="
            f"{child.prior}, expected {root._policy_cache[slot]}"
        )


def test_puct_uses_evaluator_only_once_per_node():
    """Build a small tree, expand many children of a single node,
    descend through them more than once, and assert
    ``evaluate_with_policy`` was called exactly once per distinct
    node — the policy cache is what saves us from N-call overhead."""
    adapter = _adapter(seed=21)
    eval_ = _CountingPolicyEvaluator()
    mcts = MCTS(
        evaluator=eval_,
        budget_factory=lambda: Budget(max_nodes=30),
        rng=random.Random(0),
        puct=True,
    )
    root = _Node(
        state=adapter.clone(),
        pending_decisions=mcts.expansion_policy.make_decision_iterator(
            adapter,
        ),
    )
    root_player = adapter.active_player()
    # Drive 20 selections through the same root. Each iteration
    # either expands a new child (which calls evaluate_with_policy
    # once on the root if the cache is unset) or descends — neither
    # path should bump the per-state call counter for the root
    # beyond 1.
    for _ in range(20):
        mcts._select_and_expand(root, root_player)
    # Root was queried at most once.
    assert eval_.calls_by_state.get(id(root.state), 0) <= 1
    # And per-child caches are also at most one call apiece. Grab a
    # snapshot keyed by state-id so we can assert tightly.
    for child in root.children:
        assert eval_.calls_by_state.get(id(child.state), 0) <= 1


# ---------- visit-distribution sanity ---------------------------------------


def test_puct_visit_distribution_is_well_formed():
    """Sanity check: PUCT against the dual-head NN should produce
    a non-degenerate visit distribution at the root. With random-
    init weights the policy isn't informative, but the search must
    still spread visits across more than one child rather than
    collapsing to a single arm — that would mean the prior is
    pinned at one slot and PUCT's exploit/explore tradeoff is
    broken."""
    adapter = _adapter(seed=29)
    evaluator = NNEvaluator(with_policy=True)
    mcts = MCTS(
        evaluator=evaluator,
        budget_factory=lambda: Budget(max_nodes=80),
        rng=random.Random(0),
        puct=True,
    )
    visits = mcts.choose_with_visits(adapter, adapter.active_player())
    if len(visits) <= 1:
        pytest.skip(
            "adapter offered ≤1 legal decision; nothing to spread "
            "visits over"
        )
    # All counts non-negative, total == sum of visits, > 1 child got
    # explored.
    assert all(v >= 0 for v in visits.values())
    explored = sum(1 for v in visits.values() if v > 0)
    assert explored >= 2, (
        f"PUCT collapsed onto a single arm: visits={visits}"
    )
