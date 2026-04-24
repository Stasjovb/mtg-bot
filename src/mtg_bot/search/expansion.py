"""Pluggable expansion policy for tree search.

The ``ExpansionPolicy`` decides two things, per node, during MCTS
selection-and-expansion:

1. **Should we expand another child at this node right now?**
   (``should_expand(node)``). The simplest policy — "yes, as long as
   there's an untried decision" — gives classic full-enumeration
   MCTS. Progressive widening says "cap the child count by a
   function of visits," so the tree grows in breadth only as
   investigation deepens.

2. **What decision comes next?** (``make_decision_iterator(state)``).
   The policy returns a lazy iterator of decisions to try. Order
   matters a lot under progressive widening — the first few pulls
   dominate what the tree actually looks like with modest budgets.
   A good prior (heuristic, learned, or uniform) here is where most
   of the domain-specific tuning will live.

Both hooks together let search swap tree-building strategies
without changing the MCTS main loop.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from typing import Callable, Iterable, Iterator, Optional, TYPE_CHECKING

from mtg_bot.search.protocol import Decision, GameState

if TYPE_CHECKING:
    from mtg_bot.search.mcts import _Node


class ExpansionPolicy(ABC):
    """Strategy for how MCTS grows the tree at a given node.

    Instances should be cheap to construct and stateless across
    nodes — per-node state (e.g., the current position in the
    decision iterator) lives on the ``_Node``, not here.
    """

    @abstractmethod
    def make_decision_iterator(
        self, state: GameState
    ) -> Iterator[Decision]:
        """Return the sequence of decisions to try at ``state``, in
        the order they should be expanded. May be lazy — progressive
        widening will only pull the first few; full enumeration
        drains it.
        """

    @abstractmethod
    def should_expand(self, node: "_Node") -> bool:
        """Given a node's current visit count and number of
        children, should MCTS expand another child right now?

        Return True to expand (and MCTS will call ``next()`` on the
        node's pending-decisions iterator); False to skip expansion
        and descend via UCB1 among existing children instead.
        """


class FullEnumeration(ExpansionPolicy):
    """Classic MCTS: enumerate every legal decision once.

    Fine for small branching factors. Wasteful for large ones — if
    a node has 200 legal decisions, MCTS will faithfully expand all
    200 children before ever revisiting any of them.
    """

    def make_decision_iterator(
        self, state: GameState
    ) -> Iterator[Decision]:
        return iter(state.legal_decisions())

    def should_expand(self, node: "_Node") -> bool:
        return True


class ProgressiveWidening(ExpansionPolicy):
    """Cap the number of children by ``max(1, ⌈c × visits^α⌉)``.

    Standard progressive widening (Coulom 2007, Chaslot et al.). With
    ``α ∈ [0.2, 0.5]`` and ``c ∈ [1, 5]`` the tree grows sub-linearly
    in visits: a node with 100 visits has ≤20 children (c=2, α=0.5);
    a node with 10,000 visits has ≤200. The search spends its
    budget refining a small number of children before widening.

    ``prior`` optionally supplies a decision-ordering function —
    ``prior(state) -> Iterable[Decision]`` — so the most promising
    decisions come first. With a good prior, progressive widening
    approaches full enumeration's strength at a fraction of the
    nodes. Without a prior, falls back to ``state.legal_decisions()``
    order.
    """

    def __init__(
        self,
        c: float = 2.0,
        alpha: float = 0.5,
        prior: Optional[Callable[[GameState], Iterable[Decision]]] = None,
    ) -> None:
        if c <= 0:
            raise ValueError(f"c must be positive; got {c}")
        if not (0.0 < alpha < 1.0):
            raise ValueError(
                f"alpha must be in (0, 1); got {alpha}"
            )
        self.c = c
        self.alpha = alpha
        self.prior = prior

    def make_decision_iterator(
        self, state: GameState
    ) -> Iterator[Decision]:
        if self.prior is not None:
            return iter(self.prior(state))
        return iter(state.legal_decisions())

    def should_expand(self, node: "_Node") -> bool:
        cap = max(1, math.ceil(self.c * (node.visits ** self.alpha)))
        return len(node.children) < cap
