"""Search budget: how long the search gets before it has to commit.

A single ``Budget`` instance represents one call's compute allowance.
Call ``start()`` once before search begins, then ``consume_node()``
each time you expand a node, and check ``exhausted()`` inside the
main loop to decide when to stop.

The user's plan was explicit: "budget unit = nodes-expanded or
wall-clock, NOT sims-per-decision" because decision branching factor
varies wildly in MTG.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from mtg_bot.search import eval_counters


@dataclass
class Budget:
    """Either a wall-clock cap, a node-count cap, or both.

    - ``max_seconds`` is elapsed wall time since ``start()``.
    - ``max_nodes`` is the count of ``consume_node()`` calls since
      ``start()``.

    If both are set, the first to trip wins. If both are None, the
    budget never exhausts (useful for tests; dangerous in production).
    """

    max_seconds: float | None = None
    max_nodes: int | None = None
    _start_time: float = field(default=0.0, init=False, repr=False)
    _nodes_expanded: int = field(default=0, init=False, repr=False)

    def start(self) -> None:
        """Mark the start of a search. Resets node count and
        deadline. Call exactly once per search invocation."""
        self._start_time = time.perf_counter()
        self._nodes_expanded = 0

    def consume_node(self) -> None:
        """Record that one more node was expanded."""
        self._nodes_expanded += 1
        # Process-global search-work telemetry. Fires once per
        # expanded node in every search path that honours the Budget
        # contract (serial MCTS, batched MCTS, ISMCTS). See
        # ``eval_counters`` for the depth-invariant-unit rationale.
        eval_counters.record_node()

    def nodes_expanded(self) -> int:
        """Diagnostic: how many nodes consumed so far in this call."""
        return self._nodes_expanded

    def elapsed(self) -> float:
        """Diagnostic: seconds since ``start()``."""
        return time.perf_counter() - self._start_time

    def exhausted(self) -> bool:
        """True iff the budget has been used up. Check in the main
        search loop."""
        if (
            self.max_nodes is not None
            and self._nodes_expanded >= self.max_nodes
        ):
            return True
        if (
            self.max_seconds is not None
            and time.perf_counter() - self._start_time >= self.max_seconds
        ):
            return True
        return False
