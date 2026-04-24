"""Tests for ``ExpansionPolicy`` and the two concrete implementations
(``FullEnumeration`` and ``ProgressiveWidening``).

Policy behavior is tested in isolation (via a fake-node
``SimpleNamespace``) so we don't tangle in MCTS's selection logic.
Integration tests live in ``test_mcts.py``.
"""

import math
import random
from types import SimpleNamespace

import pytest

from mtg_bot.search import (
    Budget, ExpansionPolicy, FullEnumeration, MCTS, ProgressiveWidening,
    RandomChoice, RandomRolloutEvaluator, run_match,
)
from mtg_bot.search.toys.pig import Pig
from mtg_bot.search.toys.tic_tac_toe import TicTacToe


def _node_stub(visits: int, n_children: int = 0) -> SimpleNamespace:
    """Minimal duck-typed node — only ``visits`` and ``children``
    are read by the policies."""
    return SimpleNamespace(
        visits=visits, children=[object()] * n_children,
    )


# ============================================================
# FullEnumeration
# ============================================================

def test_full_enumeration_iterator_yields_all_legal_decisions():
    policy = FullEnumeration()
    state = TicTacToe()
    decisions = list(policy.make_decision_iterator(state))
    assert decisions == state.legal_decisions()
    assert len(decisions) == 9


def test_full_enumeration_always_expands():
    policy = FullEnumeration()
    for visits in (0, 1, 5, 100, 100_000):
        for n_children in (0, 1, 5, 100):
            assert policy.should_expand(
                _node_stub(visits=visits, n_children=n_children)
            )


def test_full_enumeration_is_an_expansion_policy():
    assert isinstance(FullEnumeration(), ExpansionPolicy)


# ============================================================
# ProgressiveWidening
# ============================================================

def test_progressive_widening_is_an_expansion_policy():
    assert isinstance(ProgressiveWidening(), ExpansionPolicy)


def test_progressive_widening_rejects_invalid_c():
    with pytest.raises(ValueError):
        ProgressiveWidening(c=0)
    with pytest.raises(ValueError):
        ProgressiveWidening(c=-1.0)


def test_progressive_widening_rejects_invalid_alpha():
    with pytest.raises(ValueError):
        ProgressiveWidening(alpha=0)  # must be > 0
    with pytest.raises(ValueError):
        ProgressiveWidening(alpha=1.0)  # must be < 1
    with pytest.raises(ValueError):
        ProgressiveWidening(alpha=2.0)


def test_progressive_widening_unvisited_node_always_expands_once():
    """First-ever call at a node (visits=0, no children) should
    expand. Otherwise MCTS is dead in the water at the root."""
    policy = ProgressiveWidening(c=2.0, alpha=0.5)
    assert policy.should_expand(_node_stub(visits=0, n_children=0))


def test_progressive_widening_caps_children_by_visits():
    """Cap formula is ⌈c × visits^α⌉ (min 1). At visits=4, α=0.5,
    c=2: cap = ⌈2 × 2⌉ = 4."""
    policy = ProgressiveWidening(c=2.0, alpha=0.5)
    # visits=4, 3 children: should allow one more (cap=4).
    assert policy.should_expand(_node_stub(visits=4, n_children=3))
    # visits=4, 4 children: at cap — refuse.
    assert not policy.should_expand(_node_stub(visits=4, n_children=4))


def test_progressive_widening_scales_with_visits():
    """At visits=100, α=0.5, c=2: cap = ⌈2 × 10⌉ = 20."""
    policy = ProgressiveWidening(c=2.0, alpha=0.5)
    assert policy.should_expand(_node_stub(visits=100, n_children=19))
    assert not policy.should_expand(_node_stub(visits=100, n_children=20))


def test_progressive_widening_with_small_alpha_grows_slowly():
    """Low α => tree stays narrow much longer."""
    policy = ProgressiveWidening(c=2.0, alpha=0.2)
    # visits=100, α=0.2 → cap = ⌈2 × 100^0.2⌉ = ⌈2 × 2.51⌉ = 6
    cap_at_100 = max(1, math.ceil(2.0 * (100 ** 0.2)))
    assert policy.should_expand(
        _node_stub(visits=100, n_children=cap_at_100 - 1)
    )
    assert not policy.should_expand(
        _node_stub(visits=100, n_children=cap_at_100)
    )


def test_progressive_widening_default_iterator_matches_legal_decisions():
    """With no prior, the iterator is whatever ``legal_decisions()``
    returns in its native order."""
    policy = ProgressiveWidening()
    state = TicTacToe()
    decisions = list(policy.make_decision_iterator(state))
    assert decisions == state.legal_decisions()


def test_progressive_widening_uses_prior_for_iteration_order():
    """With a prior, decisions come out in the prior's order —
    progressive widening's first few pulls see the best decisions
    first."""
    # Prior orders: center (4) first, then corners.
    def center_first_prior(state):
        legal = state.legal_decisions()
        preferred = [4, 0, 2, 6, 8]  # center, corners
        return (
            [d for d in preferred if d in legal]
            + [d for d in legal if d not in preferred]
        )

    policy = ProgressiveWidening(prior=center_first_prior)
    state = TicTacToe()
    decisions = list(policy.make_decision_iterator(state))
    assert decisions[0] == 4
    assert set(decisions[:5]) == {4, 0, 2, 6, 8}


# ============================================================
# MCTS with each policy — integration
# ============================================================

def _mcts_with(policy, seed_offset=0) -> MCTS:
    return MCTS(
        evaluator=RandomRolloutEvaluator(
            rng=random.Random(10 + seed_offset)
        ),
        budget_factory=lambda: Budget(max_nodes=100),
        rng=random.Random(11 + seed_offset),
        expansion_policy=policy,
    )


def test_mcts_with_full_enumeration_matches_classic_behavior():
    """Default MCTS uses FullEnumeration — MCTS() with no
    expansion_policy arg should behave identically to one with an
    explicit FullEnumeration instance."""
    state = TicTacToe()
    a = _mcts_with(FullEnumeration(), seed_offset=0)
    pick_a = a.choose(state, 0)
    b = _mcts_with(None, seed_offset=0)  # explicitly None → default
    pick_b = b.choose(state, 0)
    assert pick_a == pick_b


def test_mcts_with_progressive_widening_produces_legal_decision():
    state = TicTacToe()
    mcts = _mcts_with(ProgressiveWidening(c=2.0, alpha=0.5))
    pick = mcts.choose(state, 0)
    assert pick in state.legal_decisions()


def test_mcts_with_progressive_widening_beats_random_at_tic_tac_toe():
    """Progressive widening still gives MCTS enough strength to
    win tic-tac-toe against a random baseline (TTT is small — even
    the narrow-tree policy should find good moves)."""
    mcts = MCTS(
        evaluator=RandomRolloutEvaluator(rng=random.Random(1)),
        budget_factory=lambda: Budget(max_nodes=300),
        rng=random.Random(2),
        expansion_policy=ProgressiveWidening(c=2.0, alpha=0.5),
    )
    rnd = RandomChoice(rng=random.Random(3))
    result = run_match(
        state_factory=TicTacToe,
        strategies={0: mcts, 1: rnd},
        n_games=20,
        rng=random.Random(4),
    )
    assert result.win_rate(0) >= 0.7


def test_mcts_with_progressive_widening_handles_chance_nodes():
    """Progressive widening should not break chance-node descent —
    chance children are created on demand in _descend_chance, not
    via the expansion policy."""
    mcts = MCTS(
        evaluator=RandomRolloutEvaluator(rng=random.Random(0)),
        budget_factory=lambda: Budget(max_nodes=50),
        rng=random.Random(0),
        expansion_policy=ProgressiveWidening(),
    )
    s = Pig(target=5)
    pick = mcts.choose(s, player_id=0)
    assert pick in {"roll", "hold"}


def test_mcts_progressive_widening_grows_narrower_tree_than_full():
    """Under identical budgets on a state with many legal moves,
    progressive widening should produce FEWER root children than
    full enumeration — that's the whole point."""
    state = TicTacToe()  # 9 legal moves at opening

    full_mcts = MCTS(
        evaluator=RandomRolloutEvaluator(rng=random.Random(0)),
        budget_factory=lambda: Budget(max_nodes=15),
        rng=random.Random(0),
        expansion_policy=FullEnumeration(),
    )
    narrow_mcts = MCTS(
        evaluator=RandomRolloutEvaluator(rng=random.Random(0)),
        budget_factory=lambda: Budget(max_nodes=15),
        rng=random.Random(0),
        expansion_policy=ProgressiveWidening(c=1.5, alpha=0.3),
    )

    # Peek at root children via a probe: have both run, count how
    # many distinct decisions each considered.
    # (MCTS.choose returns the best decision but doesn't expose the
    # tree. Run the internals manually.)
    from mtg_bot.search.mcts import _Node

    full_root = _Node(
        state=state.clone(),
        pending_decisions=FullEnumeration().make_decision_iterator(state),
    )
    narrow_root = _Node(
        state=state.clone(),
        pending_decisions=ProgressiveWidening(
            c=1.5, alpha=0.3
        ).make_decision_iterator(state),
    )

    budget = Budget(max_nodes=15)
    budget.start()
    while not budget.exhausted():
        leaf = full_mcts._select_and_expand(full_root)
        val = full_mcts._evaluate_leaf(leaf, 0)
        full_mcts._backprop(leaf, val, 0)
        budget.consume_node()

    budget = Budget(max_nodes=15)
    budget.start()
    while not budget.exhausted():
        leaf = narrow_mcts._select_and_expand(narrow_root)
        val = narrow_mcts._evaluate_leaf(leaf, 0)
        narrow_mcts._backprop(leaf, val, 0)
        budget.consume_node()

    # Under the same tiny budget, progressive widening should have
    # strictly fewer root children than full enumeration.
    assert len(narrow_root.children) < len(full_root.children)
    # And FullEnumeration should have expanded every legal move.
    assert len(full_root.children) == len(state.legal_decisions())
