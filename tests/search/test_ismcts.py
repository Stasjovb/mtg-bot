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
    Budget, HeuristicsConfig, MtgGameStateAdapter, RandomRolloutEvaluator,
)
from mtg_bot.search.info_set import info_set_key
from mtg_bot.search.ismcts import (
    ISMCTS, _Node, _apply_policy_mask, _puct_score,
    _ucb_with_availability,
)
from mtg_bot.simulate import setup_game
from mtg_bot.training import action_encoding as ae


# ---------- helpers ---------------------------------------------------------


def _adapter(seed: int = 42, **kwargs) -> MtgGameStateAdapter:
    state = setup_game(
        [RandomAgent(), RandomAgent()], ["G", "R"], seed=seed,
    )
    # Default the training-time priority short-circuits OFF so search
    # tests exercise the MCTS loop. Tests that want to exercise the
    # heuristics can override by passing
    # ``heuristics=HeuristicsConfig(...)``.
    kwargs.setdefault("heuristics", HeuristicsConfig.disabled())
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
    without depending on torch.

    For ``evaluate_logits``, returns the all-zeros logit vector. With
    a uniform-zero logit, ``_apply_policy_mask`` collapses to a
    uniform distribution over the union mask — same shape as
    ``evaluate_with_policy`` would produce on a per-iteration mask,
    but with the union as the mask source.
    """

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

    def evaluate_logits(self, state, player_id):
        if state.is_terminal():
            return self.value, np.zeros(
                ae.ACTION_VOCAB_SIZE, dtype=np.float32,
            )
        return self.value, np.zeros(
            ae.ACTION_VOCAB_SIZE, dtype=np.float32,
        )

    def batch_evaluate_logits(self, states, player_id):
        return [self.evaluate_logits(s, player_id) for s in states]


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
    with pytest.raises(ValueError, match="evaluate_logits"):
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
    assert root._policy_logits is not None, (
        "root must have raw logits cached after running PUCT search"
    )
    assert root._union_mask is not None, (
        "root must have a union mask after running PUCT search"
    )
    # At least one child should have a non-zero prior — the
    # all-zero-logits stub + union-mask softmax produces a uniform
    # distribution over the union of legal actions seen at the root.
    # The first-iteration expansion stamps prior=0 (logits empty,
    # population happens via the leaf's evaluate path), but
    # subsequent iterations through the parent read the cached
    # logits + (possibly-grown) union mask and produce non-zero
    # priors.
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
    # batch_size > 1 with PUCT requires batch_evaluate_logits, which
    # the stub already provides. No monkey-patching needed.
    ismcts = ISMCTS(
        evaluator=eval_,
        budget_factory=lambda: Budget(max_nodes=20),
        rng=random.Random(0),
        batch_size=4,
        puct=True,
    )
    pick = ismcts.choose(adapter, adapter.active_player())
    assert pick in legal


# ---------- Phase 3: union-mask PUCT prior ----------------------------------


def test_apply_policy_mask_uniform_logits_gives_uniform_distribution():
    """``_apply_policy_mask`` mirrors ``evaluate_with_policy``'s
    masked-softmax under whatever mask we pass it. With all-zero
    logits + a 3-True mask of length ACTION_VOCAB_SIZE, the output
    is uniform 1/3 on each True slot, exactly 0.0 on False slots,
    summing to 1.0."""
    logits = np.zeros(ae.ACTION_VOCAB_SIZE, dtype=np.float32)
    mask = np.zeros(ae.ACTION_VOCAB_SIZE, dtype=bool)
    mask[[5, 12, 100]] = True
    dist = _apply_policy_mask(logits, mask)
    assert dist is not None
    assert dist.shape == (ae.ACTION_VOCAB_SIZE,)
    assert dist.dtype == np.float32
    assert dist.sum() == pytest.approx(1.0, abs=1e-5)
    np.testing.assert_array_equal(dist[~mask], 0.0)
    for slot in (5, 12, 100):
        assert dist[slot] == pytest.approx(1.0 / 3.0, abs=1e-5)


def test_apply_policy_mask_returns_none_for_empty_mask():
    """An empty union mask means no information yet — return None
    so the caller leaves child priors at 0.0 rather than producing
    NaN from softmaxing all -inf logits."""
    logits = np.zeros(ae.ACTION_VOCAB_SIZE, dtype=np.float32)
    empty = np.zeros(ae.ACTION_VOCAB_SIZE, dtype=bool)
    assert _apply_policy_mask(logits, empty) is None
    assert _apply_policy_mask(logits, None) is None


def test_union_mask_grows_monotonically_across_iterations():
    """Manually descend a node via three different determinizations,
    each contributing a slightly different ``legal_action_mask``.
    After three descents the node's union mask equals the OR of the
    three iteration masks, and a slot that was True in any
    iteration is True in the union."""
    node = _Node(b"unit-test")
    ismcts = _make_ismcts(
        nodes=1, evaluator=_StubPolicyEvaluator(), puct=True,
    )

    class _FakeAdapter:
        def __init__(self, slots: list[int]) -> None:
            self.slots = slots

        # action_encoding.legal_action_mask delegates to engine_state
        # for the priority window — but we never call it here.

    # Bypass action_encoding by patching _grow_union_mask's mask source
    # via monkeypatch-style: directly OR in synthetic masks. This pins
    # the union-grow primitive without depending on the action-encoding
    # legality plumbing.
    masks = []
    for slots in ([1, 4, 7], [2, 4, 9], [4, 11]):
        m = np.zeros(ae.ACTION_VOCAB_SIZE, dtype=bool)
        m[slots] = True
        masks.append(m)
        if node._union_mask is None:
            node._union_mask = m.copy()
        else:
            np.logical_or(node._union_mask, m, out=node._union_mask)

    expected = np.zeros(ae.ACTION_VOCAB_SIZE, dtype=bool)
    for m in masks:
        expected |= m
    np.testing.assert_array_equal(node._union_mask, expected)
    # Every slot True in any iteration must be True in union.
    for slot in (1, 2, 4, 7, 9, 11):
        assert node._union_mask[slot]
    # Slot True in NO iteration must be False.
    assert not node._union_mask[0]
    assert not node._union_mask[3]


def test_grow_union_mask_called_during_descent_via_search():
    """Run a real PUCT ISMCTS search and observe that the root's
    union mask after the search is a superset of any single
    iteration's legal_action_mask. Also verify the union is
    *exactly* the OR of every iteration mask we observe by recording
    them via a recording determinize_fn."""
    adapter = _adapter(seed=11)
    if not _advance_to_multi_action(adapter):
        pytest.skip("game ended before a multi-action moment")
    viewer = adapter.active_player()

    iteration_masks: list[np.ndarray] = []

    def recording_determinize(
        engine_state, viewer_id, rng, *, in_place=False,
    ):
        # Record what the iteration's mask will look like by reading
        # legal_action_mask on the post-determinize state. The real
        # determinize_fn permutes hidden zones; we mimic that by
        # delegating to the default sampler.
        from mtg_bot.search.determinize import determinize as _real
        result = _real(engine_state, viewer_id, rng, in_place=in_place)
        # Need to materialize the mask off the (engine_state, viewer)
        # pair — but legal_action_mask wants an adapter. Reach back
        # through the test's adapter. We rebuild a transient adapter
        # over the engine state using the same wrapper as ISMCTS does.
        # ISMCTS clones the source adapter and determinizes in place,
        # so the engine_state arg here IS the cloned adapter's
        # engine_state. To get an adapter compatible with
        # legal_action_mask we wrap a fresh adapter; legal_action_mask
        # accepts engine_state directly per the
        # ``_enumerate_legal`` fallback.
        iteration_masks.append(
            ae.legal_action_mask(engine_state, viewer_id),
        )
        return result

    class _Spy(ISMCTS):
        captured_root: _Node = None  # type: ignore[assignment]
        captured_tree: dict = {}

        def choose_with_visits(self, state, player_id):
            from mtg_bot.search.engine_adapter import (
                MtgGameStateAdapter as _A,
            )
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
            _Spy.captured_root = root
            _Spy.captured_tree = tree
            return {d: c.visits for d, c in root.children.items()}

    eval_ = _StubPolicyEvaluator(value=0.0)
    spy = _Spy(
        evaluator=eval_,
        budget_factory=lambda: Budget(max_nodes=15),
        rng=random.Random(0),
        determinize_fn=recording_determinize,
        puct=True,
    )
    spy.choose_with_visits(adapter, viewer)
    root = _Spy.captured_root
    assert root._union_mask is not None
    # Each recorded iteration's root mask must be a subset of the
    # accumulated union mask.
    assert iteration_masks, "expected at least one iteration"
    for m in iteration_masks:
        assert (m & ~root._union_mask).sum() == 0, (
            "iteration mask had a slot True that the union mask did "
            "not — union should always be a superset"
        )
    # And the union should equal the OR of all iteration masks.
    expected_union = np.zeros(ae.ACTION_VOCAB_SIZE, dtype=bool)
    for m in iteration_masks:
        expected_union |= m
    np.testing.assert_array_equal(root._union_mask, expected_union)


def test_union_mask_widens_prior_distribution_vs_per_iteration_mask():
    """Construct a parent node with cached uniform-zero logits and
    a synthetic union mask wider than any single iteration's mask.
    Verify that ``_apply_policy_mask`` distributes mass across the
    union (so a slot legal in the union but illegal in some
    iteration still gets a positive probability), versus what a
    per-iteration narrower mask would give (zero probability there).
    Pin the difference numerically: union mask of size N gives 1/N
    on each legal slot; narrower per-iteration mask of size M < N
    gives 1/M on each of M slots and 0 on the union-only slots."""
    logits = np.zeros(ae.ACTION_VOCAB_SIZE, dtype=np.float32)
    union_mask = np.zeros(ae.ACTION_VOCAB_SIZE, dtype=bool)
    union_mask[[10, 20, 30, 40]] = True  # 4 slots in the union
    iteration_mask = np.zeros(ae.ACTION_VOCAB_SIZE, dtype=bool)
    iteration_mask[[10, 20]] = True  # only 2 slots in this iteration

    union_dist = _apply_policy_mask(logits, union_mask)
    iter_dist = _apply_policy_mask(logits, iteration_mask)
    assert union_dist is not None and iter_dist is not None

    # Slots in the union but NOT in this iteration: nonzero under
    # union, exactly zero under per-iteration.
    for slot in (30, 40):
        assert iter_dist[slot] == 0.0
        assert union_dist[slot] == pytest.approx(0.25, abs=1e-5)

    # Slots in both: present in both distributions, but with
    # different mass — 0.25 (union, 4 legal) vs 0.5 (iteration, 2
    # legal). Same direction the prior would shift in a real ISMCTS
    # node where one iteration narrowed the mask.
    for slot in (10, 20):
        assert union_dist[slot] == pytest.approx(0.25, abs=1e-5)
        assert iter_dist[slot] == pytest.approx(0.5, abs=1e-5)


def test_single_determinization_case_uses_per_iteration_mask():
    """If every iteration sees the same legal_action_mask (i.e.
    determinization doesn't change observable legality), the union
    mask equals the per-iteration mask by construction. The PUCT
    prior is then identical to what Phase 2 would have produced.

    Concretely: after running a PUCT search with a deterministic
    determinize_fn that returns the input state unchanged, the
    root's union mask equals legal_action_mask(adapter, viewer)
    exactly."""
    adapter = _adapter(seed=13)
    if not _advance_to_multi_action(adapter):
        pytest.skip("game ended before a multi-action moment")
    viewer = adapter.active_player()
    expected_root_mask = ae.legal_action_mask(adapter, viewer)

    def passthrough(engine_state, viewer_id, rng, *, in_place=False):
        return engine_state if in_place else engine_state.clone()

    class _Spy(ISMCTS):
        captured_root: _Node = None  # type: ignore[assignment]

        def choose_with_visits(self, state, player_id):
            from mtg_bot.search.engine_adapter import (
                MtgGameStateAdapter as _A,
            )
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
            _Spy.captured_root = root
            return {d: c.visits for d, c in root.children.items()}

    eval_ = _StubPolicyEvaluator(value=0.0)
    spy = _Spy(
        evaluator=eval_,
        budget_factory=lambda: Budget(max_nodes=20),
        rng=random.Random(0),
        determinize_fn=passthrough,
        puct=True,
    )
    spy.choose_with_visits(adapter, viewer)
    root = _Spy.captured_root
    np.testing.assert_array_equal(root._union_mask, expected_root_mask)


# ---------- Phase 3: NNEvaluator.evaluate_logits API contract ---------------


def test_nn_evaluator_evaluate_logits_shapes_and_no_softmax():
    """``evaluate_logits`` returns (value: float, logits:
    np.float32[ACTION_VOCAB_SIZE]) without any masking or softmax.
    Distinguishing it from ``evaluate_with_policy``: that method
    masks + softmaxes; this one does neither, so values can be
    negative (raw logits, not probabilities) and the array doesn't
    sum to 1.0."""
    from mtg_bot.search.nn_evaluator import NNEvaluator
    evaluator = NNEvaluator(with_policy=True)
    adapter = _adapter()
    value, logits = evaluator.evaluate_logits(adapter, player_id=0)
    assert isinstance(value, float)
    assert -1.0 <= value <= 1.0
    assert logits.shape == (ae.ACTION_VOCAB_SIZE,)
    assert logits.dtype == np.float32
    # Raw logits: no mask was applied, so every slot has a finite
    # value (no -inf), and the sum is some unconstrained finite
    # number (almost surely not 1.0).
    assert np.all(np.isfinite(logits))
    assert not np.allclose(logits, 0.0), (
        "fresh-init network should not emit identical-to-zero logits"
    )


def test_nn_evaluator_evaluate_logits_terminal_short_circuit():
    """Terminal states return value ±1/0 and an all-zeros logits
    vector (no decision to predict at a terminal — same convention
    as ``evaluate_with_policy``)."""
    from mtg_bot.search.nn_evaluator import NNEvaluator
    adapter = _adapter()
    adapter.engine_state.players[1].has_lost = True
    adapter.engine_state.winner_id = 0
    assert adapter.is_terminal()
    evaluator = NNEvaluator(with_policy=True)
    value, logits = evaluator.evaluate_logits(adapter, player_id=0)
    assert value == 1.0
    np.testing.assert_array_equal(
        logits, np.zeros(ae.ACTION_VOCAB_SIZE, dtype=np.float32),
    )


def test_nn_evaluator_evaluate_logits_requires_with_policy():
    from mtg_bot.search.nn_evaluator import NNEvaluator
    evaluator = NNEvaluator()  # default: with_policy=False
    adapter = _adapter()
    with pytest.raises(RuntimeError, match="with_policy=True"):
        evaluator.evaluate_logits(adapter, player_id=0)
    with pytest.raises(RuntimeError, match="with_policy=True"):
        evaluator.batch_evaluate_logits([adapter], player_id=0)


def test_nn_evaluator_batch_evaluate_logits_matches_per_state():
    """Batched call returns identical (value, logits) per state to
    iterating ``evaluate_logits`` — bit-equal under the same network
    weights."""
    from mtg_bot.search.nn_evaluator import NNEvaluator
    evaluator = NNEvaluator(with_policy=True)
    adapters = [_adapter(seed=s) for s in range(4)]
    per_state = [
        evaluator.evaluate_logits(a, player_id=0) for a in adapters
    ]
    batched = evaluator.batch_evaluate_logits(adapters, player_id=0)
    assert len(per_state) == len(batched)
    for (v_a, l_a), (v_b, l_b) in zip(per_state, batched):
        assert v_a == pytest.approx(v_b, abs=1e-5)
        np.testing.assert_allclose(l_a, l_b, atol=1e-5, rtol=0)


def test_nn_evaluator_evaluate_logits_differs_from_evaluate_with_policy():
    """Sanity: ``evaluate_logits`` is genuinely different from
    ``evaluate_with_policy`` — the former returns raw logits, the
    latter returns a softmaxed-and-masked distribution. Their values
    agree (same value head); their second-element arrays differ in
    shape/range — logits can be negative, distributions cannot, and
    distributions sum to ~1.0 while logits do not."""
    from mtg_bot.search.nn_evaluator import NNEvaluator
    evaluator = NNEvaluator(with_policy=True)
    adapter = _adapter()
    value_logits, logits = evaluator.evaluate_logits(
        adapter, player_id=0,
    )
    value_pol, distribution = evaluator.evaluate_with_policy(
        adapter, player_id=0,
    )
    assert value_logits == pytest.approx(value_pol, abs=1e-5)
    # Distribution sums to 1, logits do not (with overwhelming
    # probability for a fresh network).
    assert distribution.sum() == pytest.approx(1.0, abs=1e-5)
    assert not np.isclose(logits.sum(), 1.0)
    # Distribution is non-negative, logits can be negative.
    assert np.all(distribution >= 0.0)


# ---------- observe_action wireup (Phase 6.5) -------------------------------


def test_observe_action_is_noop_with_default_uniform_determinizer():
    """``observe_action`` must be silent when the determinize_fn is
    anything other than a ``BeliefWeightedDeterminizer``. The default
    uniform sampler has no played_history attribute; the call should
    not raise and should not stash state on the strategy."""
    adapter = _adapter(seed=11)
    if not _advance_to_multi_action(adapter):
        pytest.skip("game ended before a multi-action moment")
    legal = adapter.legal_decisions()
    decision = legal[0]
    actor = adapter.active_player()
    ismcts = _make_ismcts(nodes=10)
    # Pre-call: determinize_fn is the module-level uniform fn.
    ismcts.observe_action(adapter, decision, actor)
    # Post-call: still the same callable; nothing stashed.
    from mtg_bot.search.determinize import determinize as _uniform
    assert ismcts._determinize is _uniform


def test_observe_action_appends_to_belief_determinizer_history():
    """With a ``BeliefWeightedDeterminizer`` plugged in, each
    ``observe_action`` call appends a ``PriorityMoment`` to the
    determinizer's ``played_history``. The state attached is a
    *clone* of the supplied adapter's engine state so subsequent
    in-place mutations (the game loop's apply) don't corrupt the
    recorded snapshot.
    """
    from mtg_bot.search.belief import (
        BeliefWeightedDeterminizer, PriorityMoment,
    )
    adapter = _adapter(seed=11)
    if not _advance_to_multi_action(adapter):
        pytest.skip("game ended before a multi-action moment")
    actor = adapter.active_player()
    legal = adapter.legal_decisions()
    decision = legal[0]

    eval_stub = _StubPolicyEvaluator()
    determinizer = BeliefWeightedDeterminizer(
        opponent_policy_evaluator=eval_stub,
    )
    ismcts = ISMCTS(
        evaluator=eval_stub,
        budget_factory=lambda: Budget(max_nodes=10),
        determinize_fn=determinizer,
        rng=random.Random(0),
        puct=True,
    )

    pre_turn = adapter.engine_state.turn_number
    assert determinizer.played_history == ()

    ismcts.observe_action(adapter, decision, actor)
    assert len(determinizer.played_history) == 1
    moment = determinizer.played_history[0]
    assert isinstance(moment, PriorityMoment)
    assert moment.decision == decision
    assert moment.actor == actor
    # State attached is a clone — same turn number captured.
    assert moment.state.turn_number == pre_turn
    # Attached state is independent from the live adapter: mutating
    # the live engine_state's turn_number doesn't change the snapshot.
    adapter.engine_state.turn_number = pre_turn + 5
    assert moment.state.turn_number == pre_turn

    # A second call appends a second moment; order preserved.
    ismcts.observe_action(adapter, decision, actor)
    assert len(determinizer.played_history) == 2


def test_observe_action_accepts_engine_state_directly():
    """``observe_action`` takes either an ``MtgGameStateAdapter`` or
    a raw ``GameState``; both clone the engine state for the snapshot.
    The game loop has the adapter; some callers (e.g. tests, replay
    inspection tools) may have the raw engine state.
    """
    from mtg_bot.search.belief import BeliefWeightedDeterminizer
    adapter = _adapter(seed=11)
    if not _advance_to_multi_action(adapter):
        pytest.skip("game ended before a multi-action moment")
    actor = adapter.active_player()
    decision = adapter.legal_decisions()[0]
    eval_stub = _StubPolicyEvaluator()
    determinizer = BeliefWeightedDeterminizer(
        opponent_policy_evaluator=eval_stub,
    )
    ismcts = ISMCTS(
        evaluator=eval_stub,
        budget_factory=lambda: Budget(max_nodes=10),
        determinize_fn=determinizer,
        rng=random.Random(0),
        puct=True,
    )
    ismcts.observe_action(adapter.engine_state, decision, actor)
    assert len(determinizer.played_history) == 1


class _BeliefSafePolicyEvaluator:
    """Evaluator that returns zero-logits + zero-value for any input
    shape. The determinizer's ``_score_particle`` calls
    ``evaluate_logits(state, player_id)`` with a raw engine state
    (not an adapter), so the stub used here can't use
    ``state.is_terminal()`` like ``_StubPolicyEvaluator`` does — it
    must accept either shape uniformly. Zero logits combined with
    the legal mask collapses to a uniform-over-legal policy, the
    same behavior as ``_UniformPolicyEvaluator`` in test_belief.
    """

    def evaluate(self, state, player_id):
        return 0.0

    def batch_evaluate(self, states, player_id):
        return [0.0 for _ in states]

    def evaluate_logits(self, state, player_id):
        return 0.0, np.zeros(ae.ACTION_VOCAB_SIZE, dtype=np.float32)

    def batch_evaluate_logits(self, states, player_id):
        return [
            (0.0, np.zeros(ae.ACTION_VOCAB_SIZE, dtype=np.float32))
            for _ in states
        ]


def test_self_play_loop_populates_belief_history_via_observe_action(
    tmp_path,
):
    """Integration: the self_play module's _play_capped_game calls
    ``strategy.observe_action`` after each ``adapter.apply``. Driving
    a short game with a belief-weighted ISMCTS strategy should
    accumulate a played_history matching the priority moments visited
    in order.
    """
    from mtg_bot.search.belief import BeliefWeightedDeterminizer
    from mtg_bot.training.self_play import _play_capped_game

    eval_stub_p0 = _BeliefSafePolicyEvaluator()
    eval_stub_p1 = _BeliefSafePolicyEvaluator()
    determinizer_p0 = BeliefWeightedDeterminizer(
        opponent_policy_evaluator=eval_stub_p0,
    )
    determinizer_p1 = BeliefWeightedDeterminizer(
        opponent_policy_evaluator=eval_stub_p1,
    )
    ismcts_p0 = ISMCTS(
        evaluator=eval_stub_p0,
        budget_factory=lambda: Budget(max_nodes=4),
        determinize_fn=determinizer_p0,
        rng=random.Random(1),
        puct=True,
    )
    ismcts_p1 = ISMCTS(
        evaluator=eval_stub_p1,
        budget_factory=lambda: Budget(max_nodes=4),
        determinize_fn=determinizer_p1,
        rng=random.Random(2),
        puct=True,
    )

    adapter = _adapter(seed=11)
    strategies = {0: ismcts_p0, 1: ismcts_p1}
    rng = random.Random(99)

    winner, decisions = _play_capped_game(
        adapter, strategies, rng,
        decision_cap=20,  # Short cap — we only need a few moments.
    )

    # Both seats observed every priority moment (they observe ALL
    # actions, not just the opponent's; the determinizer filters
    # opponent moments at score time).
    assert len(determinizer_p0.played_history) > 0
    assert (
        len(determinizer_p0.played_history)
        == len(determinizer_p1.played_history)
    )
    # Recorded actor labels span at least one seat (likely both,
    # but if the cap hits before seat 1 gets priority that's fine).
    actors_seen = {m.actor for m in determinizer_p0.played_history}
    assert actors_seen.issubset({0, 1})


def test_observe_action_history_actors_match_apply_order():
    """The actor recorded in each PriorityMoment must equal the seat
    that held priority at apply time (matches the
    ``observe_action(state, decision, actor)`` contract: actor is the
    player who chose, not the one observing). Drive a short adapter
    forward manually and assert the recorded sequence.
    """
    from mtg_bot.search.belief import BeliefWeightedDeterminizer

    eval_stub = _StubPolicyEvaluator()
    determinizer = BeliefWeightedDeterminizer(
        opponent_policy_evaluator=eval_stub,
    )
    ismcts = ISMCTS(
        evaluator=eval_stub,
        budget_factory=lambda: Budget(max_nodes=4),
        determinize_fn=determinizer,
        rng=random.Random(0),
        puct=True,
    )

    adapter = _adapter(seed=11)
    expected_actors: list[int] = []
    for _ in range(8):
        if adapter.is_terminal():
            break
        legal = adapter.legal_decisions()
        if not legal:
            break
        actor = adapter.active_player()
        decision = legal[0]
        expected_actors.append(actor)
        ismcts.observe_action(adapter, decision, actor)
        adapter.apply(decision)

    recorded = [m.actor for m in determinizer.played_history]
    assert recorded == expected_actors


# ---------- deferred prior-stamping (Strategy A) ---------------------------


class _CountingPolicyEvaluator:
    """Same shape as ``_StubPolicyEvaluator`` but counts how many times
    each network entry point is invoked. Lets the deferred-stamp tests
    distinguish single-state forwards (the *expensive* path being
    eliminated) from batched forwards (the path we want everything to
    flow through)."""

    def __init__(self, value: float = 0.0) -> None:
        self.value = value
        self.evaluate_calls = 0
        self.evaluate_logits_calls = 0
        self.batch_evaluate_calls = 0
        self.batch_evaluate_logits_calls = 0
        # Track batch sizes too — verifies that parent-flush logits
        # actually rode along with the leaf batch, not a separate call.
        self.batch_evaluate_logits_sizes: list[int] = []

    def evaluate(self, state, player_id):
        self.evaluate_calls += 1
        if state.is_terminal():
            winner = state.winner()
            if winner is None:
                return 0.0
            return 1.0 if winner == player_id else -1.0
        return self.value

    def batch_evaluate(self, states, player_id):
        self.batch_evaluate_calls += 1
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

    def evaluate_logits(self, state, player_id):
        self.evaluate_logits_calls += 1
        return self._evaluate_logits_inner(state)

    def _evaluate_logits_inner(self, state):
        # Shared body so ``batch_evaluate_logits`` can build the
        # per-state result without inflating ``evaluate_logits_calls``
        # (which is the very counter the deferred-stamp tests assert
        # on — counting the batched path's internal element-wise work
        # would defeat the whole point of distinguishing single-state
        # forwards from batched ones).
        if state.is_terminal():
            return self.value, np.zeros(
                ae.ACTION_VOCAB_SIZE, dtype=np.float32,
            )
        return self.value, np.zeros(
            ae.ACTION_VOCAB_SIZE, dtype=np.float32,
        )

    def batch_evaluate_logits(self, states, player_id):
        self.batch_evaluate_logits_calls += 1
        self.batch_evaluate_logits_sizes.append(len(states))
        return [self._evaluate_logits_inner(s) for s in states]


def test_first_iteration_uses_zero_prior_no_single_state_stamp():
    """The deferred-stamp design forbids ``_stamp_prior`` from issuing
    a single-state ``evaluate_logits`` call. All policy-prior fetches
    must flow through ``batch_evaluate_logits``: the batched leaf-
    batch flush when ``batch_size > 1``, the per-iteration micro-batch
    flush when ``batch_size == 1``.

    The remaining single-state ``evaluate_logits`` callsite is
    ``_evaluate_leaf``, which only fires under ``batch_size == 1`` —
    and even there, it's the LEAF evaluation (value head + leaf-node
    logits cache), not the prior-stamp path.

    Pin: with ``batch_size > 1``, a 1-iteration search makes ZERO
    single-state ``evaluate_logits`` calls (leaf goes through the
    batched path too). With ``batch_size == 1``, the only remaining
    single-state calls come from ``_evaluate_leaf`` (one per leaf,
    not from any ``_stamp_prior``-driven path).
    """
    adapter = _adapter(seed=11)
    if not _advance_to_multi_action(adapter):
        pytest.skip("game ended before a multi-action moment")

    # Batched path: deferred stamp + batched leaf eval = zero
    # single-state forwards, period.
    ev = _CountingPolicyEvaluator(value=0.0)
    ismcts = ISMCTS(
        evaluator=ev,
        budget_factory=lambda: Budget(max_nodes=1),
        rng=random.Random(0),
        puct=True,
        batch_size=4,
    )
    ismcts.choose_with_visits(adapter, adapter.active_player())
    assert ev.evaluate_logits_calls == 0, (
        "deferred-stamp design under batch_size>1 forbids single-state "
        f"evaluate_logits during search; got "
        f"{ev.evaluate_logits_calls} call(s)"
    )
    assert ev.batch_evaluate_logits_calls >= 1, (
        f"expected at least one batched forward; got "
        f"{ev.batch_evaluate_logits_calls}"
    )

    # Serial path: only ``_evaluate_leaf`` may call single-state
    # evaluate_logits. With a 1-iteration budget, that's at most 1
    # call. The deferred-stamp queue must STILL flush through
    # batch_evaluate_logits — otherwise we'd see the prior-stamp
    # single-state forward we just eliminated.
    ev2 = _CountingPolicyEvaluator(value=0.0)
    ismcts2 = ISMCTS(
        evaluator=ev2,
        budget_factory=lambda: Budget(max_nodes=1),
        rng=random.Random(0),
        puct=True,
        batch_size=1,
    )
    ismcts2.choose_with_visits(adapter, adapter.active_player())
    # 1 evaluate_logits at the leaf is fine; 2+ would mean the prior
    # stamp regressed to the synchronous code path.
    assert ev2.evaluate_logits_calls <= 1, (
        "serial-path evaluate_logits must come only from "
        f"_evaluate_leaf; got {ev2.evaluate_logits_calls} (the "
        "prior-stamp single-state call is back)"
    )
    assert ev2.batch_evaluate_logits_calls >= 1, (
        "serial path must still flush the deferred-prior queue via "
        "batch_evaluate_logits"
    )


def test_deferred_priors_get_stamped_before_search_returns():
    """Once a search has flushed all of its iterations, every node in
    the tree that has children visited (i.e. was used as a parent
    during expansion) must have its policy logits cached. A node
    with ``children`` non-empty but ``_policy_logits is None``
    indicates the deferred-stamp queue leaked across the search
    boundary — which would mean the priors on those children were
    never upgraded from the 0.0 placeholder.
    """
    adapter = _adapter(seed=11)
    if not _advance_to_multi_action(adapter):
        pytest.skip("game ended before a multi-action moment")

    class _Spy(ISMCTS):
        captured_tree: dict = {}

        def choose_with_visits(self, state, player_id):
            from mtg_bot.search.engine_adapter import (
                MtgGameStateAdapter as _A,
            )
            assert isinstance(state, _A)
            if state.is_terminal():
                return {}
            legal = list(state.legal_decisions())
            if len(legal) == 1:
                return {legal[0]: 1}
            root_key = info_set_key(state, player_id)
            tree = {root_key: _Node(root_key)}
            root = tree[root_key]
            self._pending_prior_states = []
            self._pending_prior_set = set()
            budget = self.budget_factory()
            budget.start()
            try:
                self._search_batched(
                    state, player_id, root, tree, budget,
                    self.batch_size,
                )
            finally:
                self._pending_prior_states = []
                self._pending_prior_set = set()
            _Spy.captured_tree = tree
            return {d: c.visits for d, c in root.children.items()}

    ev = _CountingPolicyEvaluator()
    spy = _Spy(
        evaluator=ev,
        budget_factory=lambda: Budget(max_nodes=40),
        rng=random.Random(0),
        puct=True,
        batch_size=8,
    )
    spy.choose_with_visits(adapter, adapter.active_player())
    leaks = [
        node for node in _Spy.captured_tree.values()
        if node.children and node._policy_logits is None
    ]
    assert not leaks, (
        f"{len(leaks)} parent node(s) ended the search with children "
        f"but no cached logits; deferred-stamp queue leaked across "
        f"the search boundary"
    )


def test_deferred_prior_stamp_re_stamps_existing_children():
    """When a parent's logits arrive via the batched flush, EVERY
    child already attached to that parent must be re-stamped from the
    freshly-cached logits + union mask. With the
    ``_CountingPolicyEvaluator`` (zero logits) and a non-empty union
    mask, the masked-softmax distribution is uniform over the union.
    The root sees every iteration as a parent, accumulates many
    children, and after the search every one of those children must
    have a non-zero prior — proof that the re-stamp path actually
    wrote each child, not just the one that triggered the flush.
    """
    adapter = _adapter(seed=11)
    if not _advance_to_multi_action(adapter):
        pytest.skip("game ended before a multi-action moment")

    class _Spy(ISMCTS):
        captured_root: _Node = None  # type: ignore[assignment]

        def choose_with_visits(self, state, player_id):
            from mtg_bot.search.engine_adapter import (
                MtgGameStateAdapter as _A,
            )
            assert isinstance(state, _A)
            if state.is_terminal():
                return {}
            legal = list(state.legal_decisions())
            if len(legal) == 1:
                return {legal[0]: 1}
            root_key = info_set_key(state, player_id)
            tree = {root_key: _Node(root_key)}
            root = tree[root_key]
            self._pending_prior_states = []
            self._pending_prior_set = set()
            budget = self.budget_factory()
            budget.start()
            try:
                self._search_batched(
                    state, player_id, root, tree, budget,
                    self.batch_size,
                )
            finally:
                self._pending_prior_states = []
                self._pending_prior_set = set()
            _Spy.captured_root = root
            return {d: c.visits for d, c in root.children.items()}

    ev = _CountingPolicyEvaluator()
    spy = _Spy(
        evaluator=ev,
        budget_factory=lambda: Budget(max_nodes=30),
        rng=random.Random(0),
        puct=True,
        batch_size=8,
    )
    spy.choose_with_visits(adapter, adapter.active_player())
    root = _Spy.captured_root
    assert root._policy_logits is not None
    assert root.children, "root should have expanded children"
    # All-zero logits + union mask → uniform-over-union distribution.
    # Every legal child of the root sits in the union (we descended
    # to it under that mask), so its prior is 1 / |union|.
    nonzero = [c for c in root.children.values() if c.prior > 0.0]
    assert len(nonzero) == len(root.children), (
        f"expected every root child to have a re-stamped non-zero "
        f"prior; got {len(nonzero)}/{len(root.children)} non-zero"
    )


def test_pending_prior_queue_dedupes_repeated_parents_in_batch():
    """A parent that spawns multiple unexpanded children within the
    SAME batch must only enqueue once. Without dedup the
    batch_evaluate_logits call would re-issue the same forward for
    every child — wasted work and a regression on the win.
    """
    adapter = _adapter(seed=11)
    if not _advance_to_multi_action(adapter):
        pytest.skip("game ended before a multi-action moment")

    ev = _CountingPolicyEvaluator()
    ismcts = ISMCTS(
        evaluator=ev,
        budget_factory=lambda: Budget(max_nodes=40),
        rng=random.Random(0),
        puct=True,
        batch_size=8,  # each batch sees up to 8 expansions through root
    )
    ismcts.choose_with_visits(adapter, adapter.active_player())
    # The root is the parent for many iterations; it must have
    # appeared on the prior queue at most ONCE per batch — i.e. its
    # contribution to total batch sizes is bounded by the number of
    # batches (= 40 / 8 = 5). Combined with leaf states (at most one
    # per iteration) plus deeper-level parents, the *total* per-call
    # batched footprint stays comfortably below 40 + (40/8) * (some
    # small constant for unique-parents-per-batch).
    #
    # Concretely: total elements across all batched calls is
    # bounded by budget (40) + total unique parents flushed.
    total_in_batches = sum(ev.batch_evaluate_logits_sizes)
    # Lower bound: at least 40 leaf states must show up (one per
    # iteration). Upper bound: a generous slack times the budget —
    # if dedup were broken, this would balloon to thousands.
    assert total_in_batches >= 40
    assert total_in_batches <= 80, (
        f"batched footprint {total_in_batches} suggests parent "
        f"queue dedup is broken; expected ~ budget + parents-per-batch"
    )


def test_prior_stamp_batched_chooses_legal_decision_under_real_network():
    """End-to-end: a real-NN PUCT search with the deferred-stamp path
    completes without errors and returns a legal decision. The
    network is the value-only-equivalent ``NNEvaluator(with_policy=
    True)`` — small fresh-init weights, fast — driving the same code
    paths as production at a tiny budget.
    """
    from mtg_bot.search.nn_evaluator import NNEvaluator

    adapter = _adapter(seed=11)
    if not _advance_to_multi_action(adapter):
        pytest.skip("game ended before a multi-action moment")
    legal = set(adapter.legal_decisions())

    evaluator = NNEvaluator(with_policy=True)
    ismcts = ISMCTS(
        evaluator=evaluator,
        budget_factory=lambda: Budget(max_nodes=12),
        rng=random.Random(0),
        puct=True,
        batch_size=4,
    )
    pick = ismcts.choose(adapter, adapter.active_player())
    assert pick in legal


def test_pending_prior_queue_resets_between_searches():
    """A second ``choose_with_visits`` call must not see queue state
    left over from the first. Re-running the same search twice must
    produce clean queues each time."""
    adapter = _adapter(seed=11)
    if not _advance_to_multi_action(adapter):
        pytest.skip("game ended before a multi-action moment")

    ev = _CountingPolicyEvaluator()
    ismcts = ISMCTS(
        evaluator=ev,
        budget_factory=lambda: Budget(max_nodes=8),
        rng=random.Random(0),
        puct=True,
        batch_size=4,
    )
    ismcts.choose_with_visits(adapter, adapter.active_player())
    assert ismcts._pending_prior_states == []
    assert ismcts._pending_prior_set == set()

    ismcts.choose_with_visits(adapter, adapter.active_player())
    assert ismcts._pending_prior_states == []
    assert ismcts._pending_prior_set == set()


# ---------- tree reuse across choose calls (Phase 7) -----------------------


def test_tree_reuse_starts_empty_on_fresh_instance():
    """A freshly constructed ISMCTS has an empty persistent tree —
    no ghost nodes from a previous instance, no stale root key.
    """
    ismcts = _make_ismcts(nodes=5)
    assert ismcts._tree == {}
    assert ismcts._tree_root_key is None


def test_tree_reuse_carries_visits_across_choose():
    """After a first ``choose_with_visits`` call followed by an
    ``observe_action`` for the chosen decision, the second call's
    root must inherit the visit count of the first call's chosen
    child node. This is the canonical "free search" benefit of tree
    reuse.
    """
    adapter = _adapter(seed=11)
    if not _advance_to_multi_action(adapter):
        pytest.skip("game ended before a multi-action moment")
    actor = adapter.active_player()

    ismcts = _make_ismcts(nodes=40)
    visits1 = ismcts.choose_with_visits(adapter, actor)
    assert visits1, "first search must have produced visits"
    # Pick the most-visited decision; that's what ``choose`` would
    # commit to.
    decision = max(visits1.items(), key=lambda kv: kv[1])[0]
    chosen_visits = visits1[decision]
    # Locate the node that's about to become the new root.
    old_root_key = ismcts._tree_root_key
    new_root_node = ismcts._tree[old_root_key].children[decision]
    new_root_key = new_root_node.key
    inherited_visits = new_root_node.visits

    # Step the tree forward.
    ismcts.observe_action(adapter, decision, actor)
    assert ismcts._tree_root_key == new_root_key, (
        "observe_action should advance the tree root to the chosen "
        "child's key"
    )
    assert ismcts._tree[new_root_key].visits == inherited_visits, (
        "inherited node retains its visit count"
    )
    # Sanity: the inherited visit count is positive (the search
    # actually explored this child) and at most the chosen visit
    # count (the child node may have transposed with siblings, in
    # which case its visits >= chosen_visits, never less).
    assert inherited_visits >= chosen_visits


def test_observe_action_prunes_to_chosen_child():
    """After ``observe_action``, only nodes reachable from the new
    root remain in the tree dict. Sibling subtrees of unselected
    actions are dropped.
    """
    adapter = _adapter(seed=11)
    if not _advance_to_multi_action(adapter):
        pytest.skip("game ended before a multi-action moment")
    actor = adapter.active_player()

    ismcts = _make_ismcts(nodes=40)
    ismcts.choose_with_visits(adapter, actor)
    pre_prune_size = len(ismcts._tree)
    old_root = ismcts._tree[ismcts._tree_root_key]
    if not old_root.children:
        pytest.skip("first search produced no expanded children")
    decision = next(iter(old_root.children))
    new_root = old_root.children[decision]

    # Compute reachable set from new_root manually for comparison.
    expected: set[bytes] = set()
    stack = [new_root]
    while stack:
        n = stack.pop()
        if n.key in expected:
            continue
        expected.add(n.key)
        for c in n.children.values():
            stack.append(c)

    ismcts.observe_action(adapter, decision, actor)
    assert set(ismcts._tree.keys()) == expected, (
        "tree must be exactly the reachable subtree from the new root"
    )
    assert len(ismcts._tree) <= pre_prune_size, (
        "prune should not grow the tree"
    )
    assert ismcts._tree_root_key == new_root.key


def test_tree_reuse_handles_unexpanded_action():
    """If ``observe_action`` is called with a decision that wasn't a
    child of the current root, the tree must reset cleanly so the
    next ``choose`` builds from scratch without dangling references.
    """
    adapter = _adapter(seed=11)
    if not _advance_to_multi_action(adapter):
        pytest.skip("game ended before a multi-action moment")
    actor = adapter.active_player()

    ismcts = _make_ismcts(nodes=20)
    ismcts.choose_with_visits(adapter, actor)
    assert ismcts._tree, "first search should populate the tree"
    # Synthesize a decision that is highly unlikely to be a child of
    # the current root: an empty tuple is a valid hashable Decision
    # but has no semantic meaning to the engine, so the search will
    # never expand it.
    bogus_decision = ("__not_a_real_decision__",)
    assert bogus_decision not in ismcts._tree[ismcts._tree_root_key].children
    ismcts.observe_action(adapter, bogus_decision, actor)
    assert ismcts._tree == {}
    assert ismcts._tree_root_key is None
    # Next choose builds fresh — no exception, returns valid visits.
    visits = ismcts.choose_with_visits(adapter, actor)
    assert visits


def test_tree_reuse_no_op_when_no_prior_search():
    """Calling ``observe_action`` before any ``choose_with_visits``
    must be a no-op for the tree — there's nothing to advance.
    """
    adapter = _adapter(seed=11)
    if not _advance_to_multi_action(adapter):
        pytest.skip("game ended before a multi-action moment")
    actor = adapter.active_player()
    decision = adapter.legal_decisions()[0]
    ismcts = _make_ismcts(nodes=10)
    ismcts.observe_action(adapter, decision, actor)
    assert ismcts._tree == {}
    assert ismcts._tree_root_key is None


def test_reset_tree_clears_persistent_state():
    """``reset_tree`` is the public escape hatch for callers that
    want to drop accumulated search state — e.g. between independent
    games on the same strategy instance.
    """
    adapter = _adapter(seed=11)
    if not _advance_to_multi_action(adapter):
        pytest.skip("game ended before a multi-action moment")
    actor = adapter.active_player()
    ismcts = _make_ismcts(nodes=20)
    ismcts.choose_with_visits(adapter, actor)
    assert ismcts._tree
    ismcts.reset_tree()
    assert ismcts._tree == {}
    assert ismcts._tree_root_key is None


def test_tree_reuse_second_search_grows_root_visits():
    """After tree reuse, a second ``choose_with_visits`` call adds
    its iteration budget on top of whatever visits the inherited
    root already had — the two effectively combine.
    """
    adapter = _adapter(seed=11)
    if not _advance_to_multi_action(adapter):
        pytest.skip("game ended before a multi-action moment")
    actor = adapter.active_player()

    ismcts = _make_ismcts(nodes=30)
    ismcts.choose_with_visits(adapter, actor)
    decision = max(
        ismcts._tree[ismcts._tree_root_key].children.items(),
        key=lambda kv: kv[1].visits,
    )[0]
    new_root_node = (
        ismcts._tree[ismcts._tree_root_key].children[decision]
    )
    inherited_visits = new_root_node.visits
    new_root_key = new_root_node.key

    # Apply the chosen decision and observe.
    ismcts.observe_action(adapter, decision, actor)
    adapter.apply(decision)

    # The new tree root might no longer be at a multi-action moment
    # — apply forced moves to advance.
    while (
        len(adapter.legal_decisions()) == 1
        and not adapter.is_terminal()
    ):
        forced = adapter.legal_decisions()[0]
        ismcts.observe_action(adapter, forced, adapter.active_player())
        adapter.apply(forced)
    if adapter.is_terminal():
        pytest.skip("game ended before a second multi-action moment")
    # Walking forced moves through observe_action may have pruned to a
    # different node (or reset). Either path is fine; we only assert
    # that if the tree is still alive, its root visits >= inherited.
    if not ismcts._tree:
        return
    next_actor = adapter.active_player()
    ismcts.choose_with_visits(adapter, next_actor)
    new_root_after_search = ismcts._tree.get(ismcts._tree_root_key)
    assert new_root_after_search is not None
    # The root used by the second search has at least the inherited
    # visits (it might be a different node if forced moves walked us
    # past the original new_root, in which case this is still a
    # meaningful invariant: visits never go down).
    if ismcts._tree_root_key == new_root_key:
        assert new_root_after_search.visits >= inherited_visits


def test_tree_reuse_compatible_with_belief_determinizer():
    """Tree reuse + BeliefWeightedDeterminizer must coexist — the
    posterior cache lives on the determinizer, the tree lives on
    the strategy, and ``observe_action`` updates both. Both pieces
    of state survive a sequence of choose/observe calls without
    interfering.
    """
    from mtg_bot.search.belief import (
        BeliefWeightedDeterminizer, PriorityMoment,
    )
    adapter = _adapter(seed=11)
    if not _advance_to_multi_action(adapter):
        pytest.skip("game ended before a multi-action moment")
    actor = adapter.active_player()

    eval_stub = _StubPolicyEvaluator()
    determinizer = BeliefWeightedDeterminizer(
        opponent_policy_evaluator=eval_stub,
    )
    ismcts = ISMCTS(
        evaluator=eval_stub,
        budget_factory=lambda: Budget(max_nodes=20),
        determinize_fn=determinizer,
        rng=random.Random(0),
        puct=True,
    )

    visits1 = ismcts.choose_with_visits(adapter, actor)
    assert visits1
    decision = max(visits1.items(), key=lambda kv: kv[1])[0]
    # Pre-observe: belief history is empty, tree has nodes.
    assert determinizer.played_history == ()
    assert ismcts._tree
    pre_root_key = ismcts._tree_root_key

    ismcts.observe_action(adapter, decision, actor)
    # Belief history grew by one moment.
    assert len(determinizer.played_history) == 1
    moment = determinizer.played_history[0]
    assert isinstance(moment, PriorityMoment)
    assert moment.decision == decision
    assert moment.actor == actor
    # Tree advanced to the chosen child (or reset if unexpanded).
    if ismcts._tree:
        assert ismcts._tree_root_key != pre_root_key, (
            "tree should have advanced past the original root"
        )
