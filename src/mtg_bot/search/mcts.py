"""Monte Carlo Tree Search with UCB1 selection, chance-node sampling,
and evaluator-at-leaf.

Scope: two-player zero-sum games. Chance nodes are expanded but not
optimized over — MCTS samples an outcome by its declared probability
and keeps descending. This matches the canonical "imperfect but
fast" handling of stochastic games in the MCTS literature.

Final-move policy: pick the root's most-visited child. Standard
MCTS — visits track how much confidence we have, which empirically
outperforms picking the highest-value child (prefers robustness
over lucky-eval).

Injectable pieces:

- ``evaluator``        — state → scalar value at leaves.
- ``expansion_policy`` — controls when/what to expand (full
  enumeration by default; swap in progressive widening or a
  prior-driven policy for large action spaces).
- ``budget_factory``   — time or node cap per ``choose()`` call.

Selection (UCB1) and backprop are still hardcoded here; extract to
their own policies if and when we need alternates (PUCT, RAVE, etc.).
"""

from __future__ import annotations

import math
import random
from typing import Iterator, Optional

from mtg_bot.search.budget import Budget
from mtg_bot.search.evaluator import Evaluator
from mtg_bot.search.expansion import ExpansionPolicy, FullEnumeration
from mtg_bot.search.protocol import (
    CHANCE_PLAYER, Decision, GameState, PlayerID,
)
from mtg_bot.search.strategy import SearchStrategy


class _Node:
    """Internal MCTS tree node.

    ``state`` is an independent clone held for expansion/rollouts.
    ``decision`` is the move taken at ``parent`` to reach this node
    (None at the root). ``total_value`` sums values from the
    perspective of the *parent's* active player, which is the player
    who chose to come here — matches UCB1's expected interpretation.

    ``pending_decisions`` is a lazy iterator of decisions that haven't
    been expanded yet at this node. The iterator is built by the
    ``ExpansionPolicy`` and may be truncated — progressive widening
    only pulls it when the policy says a new child is warranted.

    Implemented as a plain ``__slots__`` class (not ``@dataclass``)
    because CPython 3.13's specializing interpreter had a
    reproducible bug against the dataclass-mutation pattern in our
    backprop hot loop (intermittent ``NameError``/``AttributeError``
    crashes). Plain class instances with fixed slots avoid the
    specializer's buggy fast path.
    """

    __slots__ = (
        "state", "parent", "decision", "children",
        "pending_decisions", "visits", "total_value",
    )

    def __init__(
        self,
        state: GameState,
        parent: Optional["_Node"] = None,
        decision: Optional[Decision] = None,
        pending_decisions: Optional[Iterator[Decision]] = None,
    ) -> None:
        self.state = state
        self.parent = parent
        self.decision = decision
        self.children: list["_Node"] = []
        self.pending_decisions: Iterator[Decision] = (
            pending_decisions if pending_decisions is not None
            else iter(())
        )
        self.visits: int = 0
        self.total_value: float = 0.0

    def is_leaf(self) -> bool:
        return self.state.is_terminal()

    def mean_value(self) -> float:
        return self.total_value / self.visits if self.visits else 0.0

    def ucb1(self, parent_visits: int, c: float) -> float:
        if self.visits == 0:
            return math.inf
        exploit = self.mean_value()
        explore = c * math.sqrt(math.log(parent_visits) / self.visits)
        return exploit + explore


class MCTS(SearchStrategy):
    """Budget-bounded MCTS with pluggable expansion.

    Call ``choose(state, player_id)`` once per decision. A fresh tree
    is built each call — we don't reuse across decisions yet (would
    need tree pruning and state-identity equality, both deferred).
    """

    def __init__(
        self,
        evaluator: Evaluator,
        budget_factory,
        rng: random.Random | None = None,
        exploration_c: float = math.sqrt(2),
        expansion_policy: Optional[ExpansionPolicy] = None,
    ) -> None:
        """
        ``evaluator`` scores leaves from ``player_id``'s perspective
        (in ``[-1, 1]``; terminals short-circuit to ±1/0).

        ``budget_factory`` is a zero-arg callable that returns a new
        ``Budget`` — one per ``choose`` call.

        ``exploration_c`` is UCB1's exploration constant. ``√2`` is
        the theoretical default for values in ``[-1, 1]``.

        ``expansion_policy`` controls tree growth. Defaults to
        ``FullEnumeration`` — preserves classic MCTS behavior.
        Swap in ``ProgressiveWidening`` (optionally with a prior)
        for large action spaces.
        """
        self.evaluator = evaluator
        self.budget_factory = budget_factory
        self.rng = rng or random.Random()
        self.exploration_c = exploration_c
        self.expansion_policy: ExpansionPolicy = (
            expansion_policy if expansion_policy is not None
            else FullEnumeration()
        )

    def choose(
        self, state: GameState, player_id: PlayerID
    ) -> Decision:
        # Forced-move shortcut: if there's exactly one legal decision,
        # take it. Computed eagerly up front because it's cheap and
        # lets us skip the whole tree build for trivial priority
        # moments (MTG has lots of these — "only PassPriority legal"
        # is the common case during upkeep/draw/combat).
        legal = list(state.legal_decisions())
        if len(legal) == 1:
            return legal[0]

        root = _Node(
            state=state.clone(),
            pending_decisions=self.expansion_policy.make_decision_iterator(
                state
            ),
        )

        budget = self.budget_factory()
        budget.start()
        while not budget.exhausted():
            leaf = self._select_and_expand(root)
            value = self._evaluate_leaf(leaf, player_id)
            self._backprop(leaf, value, player_id)
            budget.consume_node()

        if not root.children:
            # Budget too small to expand even once. Fall back to a
            # random legal decision so the caller still gets an answer.
            return self.rng.choice(legal)
        # Standard MCTS final-move policy: pick the most-visited child.
        best = max(root.children, key=lambda n: n.visits)
        return best.decision

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _select_and_expand(self, root: _Node) -> _Node:
        """Walk down the tree until we find a node to score.

        - At chance nodes, sample an outcome by its probability and
          descend (creating a new child if needed).
        - At real-player nodes, ask the ``ExpansionPolicy`` whether
          to add a new child. If yes and the pending-iterator has
          more decisions, expand and return the new child.
        - Otherwise, descend into the UCB1-best existing child.
        - At terminals, return as-is.
        """
        node = root
        while not node.is_leaf():
            if node.state.active_player() == CHANCE_PLAYER:
                node = self._descend_chance(node)
                continue

            expanded = self._try_expand(node)
            if expanded is not None:
                return expanded

            if not node.children:
                # No children to descend into and policy refused to
                # expand — dead end. Return this node as the leaf
                # so evaluation still happens. (Shouldn't arise
                # under FullEnumeration; a badly-tuned
                # ProgressiveWidening could get here if it caps
                # children at 0.)
                return node
            # Fully widened (per policy) — UCB1 descent.
            node = max(
                node.children,
                key=lambda c: c.ucb1(node.visits, self.exploration_c),
            )
        return node

    def _try_expand(self, node: _Node) -> Optional[_Node]:
        """If the policy permits and the pending iterator has more,
        expand a new child and return it. Otherwise return None."""
        if not self.expansion_policy.should_expand(node):
            return None
        try:
            decision = next(node.pending_decisions)
        except StopIteration:
            return None
        return self._make_child(node, decision)

    def _make_child(self, parent: _Node, decision: Decision) -> _Node:
        """Build and attach a new child for ``decision`` at
        ``parent``. The child's pending-decisions iterator is
        freshly built from the expansion policy."""
        child_state = parent.state.clone()
        child_state.apply(decision)
        pending = (
            self.expansion_policy.make_decision_iterator(child_state)
            if not child_state.is_terminal() else iter(())
        )
        child = _Node(
            state=child_state,
            parent=parent,
            decision=decision,
            pending_decisions=pending,
        )
        parent.children.append(child)
        return child

    def _descend_chance(self, node: _Node) -> _Node:
        """Sample a chance outcome, either picking the existing
        child for that outcome or creating one."""
        outcomes = node.state.chance_outcomes()
        decisions = [d for d, _ in outcomes]
        weights = [w for _, w in outcomes]
        decision = self.rng.choices(decisions, weights=weights, k=1)[0]
        for child in node.children:
            if child.decision == decision:
                return child
        # First time we sampled this outcome — create the child.
        return self._make_child(node, decision)

    def _evaluate_leaf(
        self, leaf: _Node, root_player: PlayerID
    ) -> float:
        """Return the leaf's value from ``root_player``'s perspective,
        in ``[-1, 1]``. The evaluator handles terminal vs non-terminal
        internally."""
        return self.evaluator.evaluate(leaf.state, root_player)

    def _backprop(
        self, leaf: _Node, value_for_root: float,
        root_player: PlayerID,
    ) -> None:
        """Walk from leaf to root, updating visits and total_value.

        ``total_value`` is stored from the perspective of the parent's
        active player (the one who chose to move to this child). In a
        two-player zero-sum game the perspectives differ only by sign.
        """
        node: _Node | None = leaf
        while node is not None:
            node.visits += 1
            if node.parent is not None:
                parent_player = node.parent.state.active_player()
                if parent_player == root_player:
                    node.total_value += value_for_root
                elif parent_player == CHANCE_PLAYER:
                    # Chance parents don't have a "mover perspective" —
                    # total_value is unused for their children (we
                    # sample rather than UCB-select). Leave it zero.
                    pass
                else:
                    node.total_value += -value_for_root
            node = node.parent
