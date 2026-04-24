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

Design notes for later waves:

- ``_rollout`` currently just calls the evaluator at the leaf. Swap
  for a hybrid (evaluator + random rollout) when a learned evaluator
  is in place.
- Transposition tables deferred — they pay off when the search tree
  has many transpositions, which is noise-level for MTG's branching
  factor. Revisit after the real-engine adapter is running.
"""

from __future__ import annotations

import math
import random
from typing import Optional

from mtg_bot.search.budget import Budget
from mtg_bot.search.evaluator import Evaluator
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

    Implemented as a plain class (not ``@dataclass``) because
    CPython 3.13's specializing interpreter had a reproducible bug
    against the dataclass-mutation pattern in our backprop hot loop
    (intermittent ``NameError``/``AttributeError`` crashes). Plain
    class instances with ``__dict__`` attribute access avoid the
    specializer's buggy fast path.
    """

    __slots__ = (
        "state", "parent", "decision", "children",
        "untried_decisions", "visits", "total_value",
    )

    def __init__(
        self,
        state: GameState,
        parent: Optional["_Node"] = None,
        decision: Optional[Decision] = None,
        untried_decisions: Optional[list[Decision]] = None,
    ) -> None:
        self.state = state
        self.parent = parent
        self.decision = decision
        self.children: list["_Node"] = []
        self.untried_decisions: list[Decision] = (
            list(untried_decisions) if untried_decisions is not None else []
        )
        self.visits: int = 0
        self.total_value: float = 0.0

    def is_fully_expanded(self) -> bool:
        return not self.untried_decisions

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
    """Budget-bounded MCTS with UCB1 selection + evaluator-at-leaf.

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
    ) -> None:
        """
        ``evaluator`` is called at every leaf expansion to score the
        state from each player's perspective (via their winner-or-
        draw result at terminals, otherwise via the evaluator's
        non-terminal heuristic).

        ``budget_factory`` is a zero-arg callable that returns a new
        ``Budget`` — one per ``choose`` call. Keeping it a factory
        (rather than a single Budget) lets the same MCTS instance be
        reused across many decisions without manually resetting.

        ``exploration_c`` is UCB1's exploration constant. ``sqrt(2)``
        is the theoretical default for values in ``[-1, 1]``; the
        user's plan defaulted to 1.4 which is essentially the same
        thing rounded. Tune per game in later waves.
        """
        self.evaluator = evaluator
        self.budget_factory = budget_factory
        self.rng = rng or random.Random()
        self.exploration_c = exploration_c

    def choose(
        self, state: GameState, player_id: PlayerID
    ) -> Decision:
        root = _Node(
            state=state.clone(),
            untried_decisions=list(state.legal_decisions()),
        )
        if len(root.untried_decisions) == 1:
            # Forced move — skip the search entirely.
            return root.untried_decisions[0]

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
            return self.rng.choice(state.legal_decisions())
        # Standard MCTS final-move policy: pick the most-visited child.
        best = max(root.children, key=lambda n: n.visits)
        return best.decision

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _select_and_expand(self, root: _Node) -> _Node:
        """Walk down the tree until we find a node to score.

        - At fully-expanded non-terminal real-player nodes, pick the
          UCB1-best child and descend.
        - At chance nodes, sample an outcome by its probability and
          descend (creating a new child if needed).
        - At non-fully-expanded nodes, expand one untried decision
          and return the new child.
        - At terminals, return as-is.
        """
        node = root
        while not node.is_leaf():
            if node.state.active_player() == CHANCE_PLAYER:
                node = self._descend_chance(node)
                continue
            if not node.is_fully_expanded():
                return self._expand_one(node)
            # Fully expanded real-player node: UCB1 descent.
            node = max(
                node.children,
                key=lambda c: c.ucb1(node.visits, self.exploration_c),
            )
        return node

    def _expand_one(self, node: _Node) -> _Node:
        """Create a new child for one untried decision and return it."""
        decision = node.untried_decisions.pop()
        child_state = node.state.clone()
        child_state.apply(decision)
        child = _Node(
            state=child_state,
            parent=node,
            decision=decision,
            untried_decisions=(
                list(child_state.legal_decisions())
                if not child_state.is_terminal() else []
            ),
        )
        node.children.append(child)
        return child

    def _descend_chance(self, node: _Node) -> _Node:
        """Sample a chance outcome, either picking the existing
        child for that outcome or creating it."""
        outcomes = node.state.chance_outcomes()
        decisions = [d for d, _ in outcomes]
        weights = [w for _, w in outcomes]
        decision = self.rng.choices(decisions, weights=weights, k=1)[0]
        for child in node.children:
            if child.decision == decision:
                return child
        # First time we sampled this outcome — create the child.
        child_state = node.state.clone()
        child_state.apply(decision)
        child = _Node(
            state=child_state,
            parent=node,
            decision=decision,
            untried_decisions=(
                list(child_state.legal_decisions())
                if not child_state.is_terminal() else []
            ),
        )
        node.children.append(child)
        return child

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
