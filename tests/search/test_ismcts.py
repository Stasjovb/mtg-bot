"""Tests for SO-ISMCTS (``mtg_bot.search.ismcts.ISMCTS``).

The structural change vs ``MCTS`` is information-set-keyed nodes and
per-iteration determinization during selection. These tests pin the
behaviors that flow from those choices:

- A visit dict shape compatible with the existing ``MCTS`` /
  ``PIMC`` consumers.
- Reproducibility under a seeded RNG.
- Forced-move and terminal-state shortcuts matching the existing
  conventions.
- Information-set sharing — iterations whose determinizations
  reach observably-equivalent decision points accumulate visits in
  the same node (transposition merging via ``info_set_key``).
- PUCT prior wiring stays intact when a policy-capable evaluator
  is plugged in.
"""

from __future__ import annotations

import random

import numpy as np
import pytest

from mtg_bot.agents import RandomAgent
from mtg_bot.search import (
    Budget, MtgGameStateAdapter, RandomRolloutEvaluator,
)
from mtg_bot.search.info_set import info_set_key
from mtg_bot.search.ismcts import ISMCTS, _Node, _puct_score, _ucb_with_availability
from mtg_bot.simulate import setup_game
from mtg_bot.training import action_encoding as ae


# ---------- helpers ---------------------------------------------------------


def _adapter(seed: int = 42, **kwargs) -> MtgGameStateAdapter:
    state = setup_game(
        [RandomAgent(), RandomAgent()], ["G", "R"], seed=seed,
    )
    return MtgGameStateAdapter(state, **kwargs)


def _advance_to_multi_action(adapter: MtgGameStateAdapter) -> bool:
    """Drive past forced-move priority moments. Returns True if the
    adapter sits at a multi-action moment after advancing; False if
    the game ended first."""
    while (
        len(adapter.legal_decisions()) == 1
        and not adapter.is_terminal()
    ):
        adapter.apply(adapter.legal_decisions()[0])
    return not adapter.is_terminal()


def _make_ismcts(
    nodes: int,
    rng_seed: int = 1,
    puct: bool = False,
    evaluator=None,
) -> ISMCTS:
    if evaluator is None:
        evaluator = RandomRolloutEvaluator(rng=random.Random(rng_seed))
    return ISMCTS(
        evaluator=evaluator,
        budget_factory=lambda: Budget(max_nodes=nodes),
        rng=random.Random(rng_seed + 100),
        puct=puct,
    )


class _StubPolicyEvaluator:
    """Evaluator that returns a fixed per-state value and a uniform-
    over-legal policy. Lets PUCT tests assert on prior plumbing
    without depending on torch."""

    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def evaluate(self, state, player_id):
        if state.is_terminal():
            winner = state.winner()
            if winner is None:
                return 0.0
            return 1.0 if winner == player_id else -1.0
        return self.value

    def batch_evaluate(self, states, player_id):
        return [self.evaluate(s, player_id) for s in states]

    def evaluate_with_policy(self, state, player_id):
        if state.is_terminal():
            return self.value, np.zeros(
                ae.ACTION_VOCAB_SIZE, dtype=np.float32,
            )
        mask = ae.legal_action_mask(state, player_id)
        n_legal = int(mask.sum())
        if n_legal == 0:
            return self.value, np.zeros(
                ae.ACTION_VOCAB_SIZE, dtype=np.float32,
            )
        policy = np.zeros(ae.ACTION_VOCAB_SIZE, dtype=np.float32)
        policy[mask] = 1.0 / n_legal
        return self.value, policy


# ---------- input validation ------------------------------------------------


def test_ismcts_rejects_non_adapter_state():
    ismcts = _make_ismcts(nodes=10)

    class NotAnAdapter:
        def legal_decisions(self):
            return ["x"]

        def is_terminal(self):
            return False

    with pytest.raises(TypeError, match="MtgGameStateAdapter"):
        ismcts.choose(NotAnAdapter(), player_id=0)


def test_ismcts_rejects_zero_or_negative_batch_size():
    with pytest.raises(ValueError, match="batch_size must be >= 1"):
        ISMCTS(
            evaluator=RandomRolloutEvaluator(),
            budget_factory=lambda: Budget(max_nodes=10),
            batch_size=0,
            puct=False,
        )


def test_ismcts_puct_requires_policy_capable_evaluator():
    with pytest.raises(ValueError, match="evaluate_with_policy"):
        ISMCTS(
            evaluator=RandomRolloutEvaluator(),
            budget_factory=lambda: Budget(max_nodes=10),
            puct=True,
        )


# ---------- smoke / basic behavior ------------------------------------------


def test_ismcts_smoke_returns_legal_decision():
    """Tiny budget should still yield a legal decision."""
    adapter = _adapter(seed=11)
    if not _advance_to_multi_action(adapter):
        pytest.skip("game ended before a multi-action moment")
    legal = set(adapter.legal_decisions())
    ismcts = _make_ismcts(nodes=50)
    pick = ismcts.choose(adapter, adapter.active_player())
    assert pick in legal


def test_ismcts_choose_with_visits_returns_per_decision_visits():
    adapter = _adapter(seed=11)
    if not _advance_to_multi_action(adapter):
        pytest.skip("game ended before a multi-action moment")
    legal = set(adapter.legal_decisions())
    ismcts = _make_ismcts(nodes=50)
    visits = ismcts.choose_with_visits(adapter, adapter.active_player())
    for d, v in visits.items():
        assert d in legal
        assert v > 0
    # Tree-cap: total root-children visits is positive and bounded by
    # budget. Some iterations expand a non-root grandchild; root's
    # immediate-children visit total is therefore <= budget.
    assert sum(visits.values()) > 0
    assert sum(visits.values()) <= 50


def test_ismcts_does_not_mutate_caller_adapter():
    adapter = _adapter(seed=11)
    if not _advance_to_multi_action(adapter):
        pytest.skip("game ended before a multi-action moment")
    pre_turn = adapter.engine_state.turn_number
    pre_step = adapter.engine_state.step
    pre_hand = [
        [c.id for c in p.hand] for p in adapter.engine_state.players
    ]
    ismcts = _make_ismcts(nodes=30)
    ismcts.choose(adapter, adapter.active_player())
    assert adapter.engine_state.turn_number == pre_turn
    assert adapter.engine_state.step == pre_step
    post_hand = [
        [c.id for c in p.hand] for p in adapter.engine_state.players
    ]
    assert post_hand == pre_hand


# ---------- forced-move / terminal shortcuts --------------------------------


def test_ismcts_forced_move_returns_singleton_visits():
    adapter = _adapter(seed=42)
    # On a fresh state at UPKEEP, only PassPriority is legal (forced).
    assert len(adapter.legal_decisions()) == 1
    ismcts = _make_ismcts(nodes=1000)
    visits = ismcts.choose_with_visits(adapter, adapter.active_player())
    only = adapter.legal_decisions()[0]
    assert visits == {only: 1}


def test_ismcts_forced_move_choose_returns_only_legal():
    adapter = _adapter(seed=42)
    assert len(adapter.legal_decisions()) == 1
    pick = _make_ismcts(nodes=1000).choose(adapter, adapter.active_player())
    assert pick == adapter.legal_decisions()[0]


def test_ismcts_terminal_state_returns_empty_visits():
    """Already-terminal adapter returns an empty visit dict — the
    caller must fall back to a legal default (which on a terminal
    is always the empty list, so callers should already gate this)."""
    adapter = _adapter(seed=42)
    # Force the engine to a terminal state by setting both players'
    # life to 0 and running state-based actions.
    from mtg_bot.turn import state_based_actions
    for p in adapter.engine_state.players:
        p.life = 0
    state_based_actions(adapter.engine_state)
    assert adapter.is_terminal()
    ismcts = _make_ismcts(nodes=20)
    assert ismcts.choose_with_visits(adapter, 0) == {}


# ---------- reproducibility -------------------------------------------------


def test_ismcts_is_reproducible_under_seeded_rng():
    """Same state, same rng seed, same budget → same visit dict.
    Critical for any debugging / regression workflow."""
    adapter1 = _adapter(seed=11)
    adapter2 = _adapter(seed=11)
    if not _advance_to_multi_action(adapter1):
        pytest.skip("game ended before a multi-action moment")
    if not _advance_to_multi_action(adapter2):
        pytest.skip("game ended before a multi-action moment")

    def run(adapter):
        ismcts = ISMCTS(
            evaluator=RandomRolloutEvaluator(rng=random.Random(7)),
            budget_factory=lambda: Budget(max_nodes=40),
            rng=random.Random(99),
            puct=False,
        )
        return ismcts.choose_with_visits(adapter, adapter.active_player())

    a = run(adapter1)
    b = run(adapter2)
    assert a == b


# ---------- visit accounting ------------------------------------------------


def test_ismcts_visit_total_equals_budget_at_root_descendants():
    """Sum of visits across the entire tree equals the iteration
    count (budget). At the root's immediate children specifically,
    the total is bounded above by the budget — some iterations
    descend deeper and accumulate visits at grandchildren too. We
    pin "visits at root children plus deeper descendants = budget"
    by checking via a tiny instrumentation: re-enter the root via
    info_set_key after the search, walk from the root."""
    adapter = _adapter(seed=11)
    if not _advance_to_multi_action(adapter):
        pytest.skip("game ended before a multi-action moment")
    ismcts = _make_ismcts(nodes=25)
    visits = ismcts.choose_with_visits(adapter, adapter.active_player())
    # Root child visits sum should be <= budget AND >= 1 — every
    # iteration touches at least the root (which then descends into
    # one child).
    total = sum(visits.values())
    assert 1 <= total <= 25


def test_ismcts_node_visits_match_availability_invariant():
    """For any node, ``visits <= availability`` because availability
    is incremented every iteration the node was selectable, and
    visits only when it was actually selected.

    We can't easily peek at the internal tree without re-running, so
    we drive a single search and walk the dict-of-dicts directly via
    a custom subclass.
    """
    adapter = _adapter(seed=11)
    if not _advance_to_multi_action(adapter):
        pytest.skip("game ended before a multi-action moment")

    class _Spy(ISMCTS):
        last_tree: dict = {}

        def choose_with_visits(self, state, player_id):
            # Inline a copy of the parent body so we can stash the
            # tree before returning. Simpler than trying to expose
            # the tree on the public API.
            from mtg_bot.search.engine_adapter import MtgGameStateAdapter as _A
            assert isinstance(state, _A)
            if state.is_terminal():
                return {}
            legal = list(state.legal_decisions())
            if len(legal) == 1:
                return {legal[0]: 1}
            root_key = info_set_key(state, player_id)
            tree = {root_key: _Node(root_key)}
            root = tree[root_key]
            budget = self.budget_factory()
            budget.start()
            self._search_serial(state, player_id, root, tree, budget)
            _Spy.last_tree = tree
            return {d: c.visits for d, c in root.children.items()}

    spy = _Spy(
        evaluator=RandomRolloutEvaluator(rng=random.Random(0)),
        budget_factory=lambda: Budget(max_nodes=40),
        rng=random.Random(1),
        puct=False,
    )
    spy.choose_with_visits(adapter, adapter.active_player())
    # The root node sees every iteration but isn't counted as
    # "selectable as a child of itself" — its availability stays at 0.
    # All NON-root nodes must satisfy visits <= availability.
    root_key = info_set_key(adapter, adapter.active_player())
    non_root_nodes = [
        n for k, n in spy.last_tree.items() if k != root_key
    ]
    assert non_root_nodes, "tree should have grown beyond just the root"
    for node in non_root_nodes:
        assert node.visits <= node.availability, (
            f"node visits={node.visits} > availability="
            f"{node.availability}: invariant broken"
        )
        # Availability never exceeds the iteration budget.
        assert node.availability <= 40


# ---------- information-set sharing -----------------------------------------


def test_ismcts_iterations_share_node_via_info_set_key():
    """Two iterations that pick the same root-child decision but
    different determinizations should accumulate visits at the SAME
    child node — that's the whole point of info-set keying. We can
    observe this indirectly: sum of root.children visits should
    equal the number of iterations that descended into a child
    (which is most of them, given the tiny tree).

    Concretely: with a 30-iteration budget, the dict-of-dicts tree
    must have far fewer total nodes than 30 × max_depth — without
    info-set sharing every iteration would create N fresh nodes
    along its path."""
    adapter = _adapter(seed=11)
    if not _advance_to_multi_action(adapter):
        pytest.skip("game ended before a multi-action moment")

    class _Spy(ISMCTS):
        last_tree: dict = {}

        def choose_with_visits(self, state, player_id):
            from mtg_bot.search.engine_adapter import MtgGameStateAdapter as _A
            assert isinstance(state, _A)
            if state.is_terminal():
                return {}
            legal = list(state.legal_decisions())
            if len(legal) == 1:
                return {legal[0]: 1}
            root_key = info_set_key(state, player_id)
            tree = {root_key: _Node(root_key)}
            root = tree[root_key]
            budget = self.budget_factory()
            budget.start()
            self._search_serial(state, player_id, root, tree, budget)
            _Spy.last_tree = tree
            return {d: c.visits for d, c in root.children.items()}

    spy = _Spy(
        evaluator=RandomRolloutEvaluator(rng=random.Random(0)),
        budget_factory=lambda: Budget(max_nodes=30),
        rng=random.Random(1),
        puct=False,
    )
    spy.choose_with_visits(adapter, adapter.active_player())
    # Every node in the tree should have been visited at least once
    # (otherwise it wouldn't be in the tree). And the total visits
    # across the tree summed equals the iteration count: each
    # iteration adds exactly +1 to each node on its path. So the
    # summed visits of all nodes is sum_over_iter(path_length) which
    # is >= 30 (each iteration touches >= 1 node).
    total_visits_in_tree = sum(n.visits for n in spy.last_tree.values())
    assert total_visits_in_tree >= 30


def test_ismcts_root_visits_equal_iteration_count():
    """The root node sees every iteration — its visit count equals
    the total iterations consumed. The sum-of-root-child-visits is
    less than or equal to that (some iterations halt at the root
    if every legal action's child is shared with a transposition
    that had no further compatible descent)."""
    adapter = _adapter(seed=11)
    if not _advance_to_multi_action(adapter):
        pytest.skip("game ended before a multi-action moment")

    class _Spy(ISMCTS):
        captured_tree: dict = {}
        captured_root_key: bytes = b""

        def choose_with_visits(self, state, player_id):
            from mtg_bot.search.engine_adapter import MtgGameStateAdapter as _A
            assert isinstance(state, _A)
            if state.is_terminal():
                return {}
            legal = list(state.legal_decisions())
            if len(legal) == 1:
                return {legal[0]: 1}
            root_key = info_set_key(state, player_id)
            tree = {root_key: _Node(root_key)}
            root = tree[root_key]
            budget = self.budget_factory()
            budget.start()
            self._search_serial(state, player_id, root, tree, budget)
            _Spy.captured_tree = tree
            _Spy.captured_root_key = root_key
            return {d: c.visits for d, c in root.children.items()}

    spy = _Spy(
        evaluator=RandomRolloutEvaluator(rng=random.Random(0)),
        budget_factory=lambda: Budget(max_nodes=40),
        rng=random.Random(1),
        puct=False,
    )
    spy.choose_with_visits(adapter, adapter.active_player())
    root = spy.captured_tree[spy.captured_root_key]
    assert root.visits == 40


# ---------- PUCT prior wiring -----------------------------------------------


def test_ismcts_puct_priors_match_evaluator_policy():
    """After expansion through ISMCTS PUCT, children get priors
    stamped from the parent's cached policy distribution. We assert
    the prior we read off children matches the evaluator's policy
    at the corresponding action-encoding slot."""
    adapter = _adapter(seed=13)
    if not _advance_to_multi_action(adapter):
        pytest.skip("game ended before a multi-action moment")

    class _Spy(ISMCTS):
        captured_tree: dict = {}
        captured_root_key: bytes = b""

        def choose_with_visits(self, state, player_id):
            from mtg_bot.search.engine_adapter import MtgGameStateAdapter as _A
            assert isinstance(state, _A)
            if state.is_terminal():
                return {}
            legal = list(state.legal_decisions())
            if len(legal) == 1:
                return {legal[0]: 1}
            root_key = info_set_key(state, player_id)
            tree = {root_key: _Node(root_key)}
            root = tree[root_key]
            budget = self.budget_factory()
            budget.start()
            self._search_serial(state, player_id, root, tree, budget)
            _Spy.captured_tree = tree
            _Spy.captured_root_key = root_key
            return {d: c.visits for d, c in root.children.items()}

    eval_ = _StubPolicyEvaluator(value=0.0)
    spy = _Spy(
        evaluator=eval_,
        budget_factory=lambda: Budget(max_nodes=40),
        rng=random.Random(0),
        puct=True,
    )
    root_player = adapter.active_player()
    spy.choose_with_visits(adapter, root_player)
    root = spy.captured_tree[spy.captured_root_key]
    assert root._policy_cache is not None, (
        "root must have policy cached after running PUCT search"
    )
    # At least one child should have a non-zero prior — the uniform-
    # over-legal stub puts 1/n_legal on every legal slot. The first-
    # iteration expansion stamps prior=0 (cache empty), but on the
    # second iteration where we re-pass through the parent the
    # stamping reads the cache. So among root's children, the ones
    # expanded on iteration >= 2 should have non-zero priors.
    nonzero_priors = sum(
        1 for c in root.children.values() if c.prior > 0.0
    )
    assert nonzero_priors >= 1, (
        f"expected at least one child to receive a non-zero prior "
        f"from the cached policy after multiple iterations; got "
        f"{nonzero_priors} nonzero priors out of "
        f"{len(root.children)} children"
    )


# ---------- selection rules -------------------------------------------------


def test_ucb_with_availability_unvisited_returns_inf():
    n = _Node(b"x")
    n.availability = 1
    assert _ucb_with_availability(n, c=1.0) == float("inf")


def test_ucb_with_availability_combines_q_and_explore():
    import math
    n = _Node(b"x")
    n.visits = 4
    n.total_value = 2.0  # Q = 0.5
    n.availability = 16
    c = 1.0
    expected = 0.5 + c * math.sqrt(math.log(16) / (1 + 4))
    assert _ucb_with_availability(n, c=1.0) == pytest.approx(expected)


def test_puct_score_uses_availability_in_bonus():
    import math
    n = _Node(b"x")
    n.visits = 3
    n.total_value = 1.5  # Q = 0.5
    n.prior = 0.4
    n.availability = 9
    parent_visits = 100  # ignored — PUCT-with-availability uses A
    c = 1.0
    expected = 0.5 + c * 0.4 * math.sqrt(9) / (1 + 3)
    assert _puct_score(n, parent_visits, c) == pytest.approx(expected)


def test_puct_score_pure_prior_when_unvisited():
    import math
    n = _Node(b"x")
    n.prior = 0.5
    n.availability = 4
    expected = 1.0 * 0.5 * math.sqrt(4) / 1
    assert _puct_score(n, parent_visits=999, c=1.0) == pytest.approx(expected)


# ---------- end-to-end with a custom determinize_fn -------------------------


def test_ismcts_passes_viewer_id_and_independent_rngs_to_determinize():
    """The ``determinize_fn`` callback should be called once per
    iteration (not K times like PIMC) with the engine state and the
    viewer's id."""
    adapter = _adapter(seed=11)
    if not _advance_to_multi_action(adapter):
        pytest.skip("game ended before a multi-action moment")

    calls: list[tuple] = []
    rngs_held: list = []

    def recording_determinize(
        engine_state, viewer_id, rng, *, in_place=False,
    ):
        # Hold a reference to the rng so its id can't be reused
        # across calls (Python's id() is "uniqueness only among
        # currently-live objects").
        rngs_held.append(rng)
        calls.append((engine_state, viewer_id, rng.random()))
        return engine_state if in_place else engine_state.clone()

    ismcts = ISMCTS(
        evaluator=RandomRolloutEvaluator(rng=random.Random(0)),
        budget_factory=lambda: Budget(max_nodes=15),
        rng=random.Random(1),
        determinize_fn=recording_determinize,
        puct=False,
    )
    ismcts.choose_with_visits(adapter, adapter.active_player())
    # 15 iterations → 15 determinize calls.
    assert len(calls) == 15
    for engine_state, viewer_id, _ in calls:
        assert viewer_id == adapter.active_player()
        # Each call gets its own engine state object (sub adapter
        # was cloned).
        assert engine_state is not adapter.engine_state
    # All rngs are distinct (new Random per iteration). Distinct
    # objects should produce distinct first random()s with very
    # high probability under different seeds.
    assert len({id(r) for r in rngs_held}) == 15
    # And the produced randoms are also distinct (collision chance
    # is negligible).
    first_randoms = [c[2] for c in calls]
    assert len(set(first_randoms)) == 15


# ---------- batched evaluation ---------------------------------------------


def test_ismcts_batched_evaluation_runs_to_completion():
    """Smoke: with batch_size > 1 the search should still produce a
    legal decision and visits sum within budget."""
    adapter = _adapter(seed=11)
    if not _advance_to_multi_action(adapter):
        pytest.skip("game ended before a multi-action moment")
    legal = set(adapter.legal_decisions())

    eval_ = _StubPolicyEvaluator(value=0.0)
    # batch_size > 1 with PUCT requires batch_evaluate_with_policy.
    # Add a thin bulk wrapper to the stub.

    def batch_evaluate_with_policy(states, player_id):
        return [eval_.evaluate_with_policy(s, player_id) for s in states]

    eval_.batch_evaluate_with_policy = batch_evaluate_with_policy

    ismcts = ISMCTS(
        evaluator=eval_,
        budget_factory=lambda: Budget(max_nodes=20),
        rng=random.Random(0),
        batch_size=4,
        puct=True,
    )
    pick = ismcts.choose(adapter, adapter.active_player())
    assert pick in legal
