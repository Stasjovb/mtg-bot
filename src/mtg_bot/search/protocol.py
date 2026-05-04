"""Abstract ``GameState`` protocol the search framework talks to.

The search code knows nothing about MTG — every interaction with the
game goes through this interface. Two-player zero-sum games only for
the scaffold; generalizing to multi-player is a later wave.

Chance nodes (e.g., card draw) are modeled as decisions made by a
distinguished ``CHANCE_PLAYER``. Selection algorithms (MCTS UCB1,
alpha-beta, etc.) must *not* apply their usual policy at chance nodes
— they sample from ``chance_outcomes()`` instead.

A concrete ``GameState`` must be:
- **Cloneable**: ``clone()`` returns an independent copy. Thousands of
  clones per decision is the target workload.
- **Mutable**: ``apply(decision)`` mutates ``self`` rather than
  returning a new state. Search clones before applying.
- **Turn-ended detectable**: ``is_terminal()`` must be O(1).

Decisions must be hashable so searches can build transposition tables
and use them as dict keys. Any hashable value works — ints, strings,
tuples, frozen dataclasses.
"""

from __future__ import annotations

from typing import Hashable, Protocol, runtime_checkable

PlayerID = int
"""A player identifier. Non-negative ints for real players; the
sentinel ``CHANCE_PLAYER`` for chance nodes."""

CHANCE_PLAYER: PlayerID = -1
"""Returned by ``GameState.active_player()`` at chance nodes. Search
algorithms must sample outcomes rather than apply their policy."""

Decision = Hashable
"""A decision applied to a state via ``GameState.apply``. Any hashable
value. Concrete games are free to pick whatever representation is
clearest — ints, strings, named tuples, frozen dataclasses."""


@runtime_checkable
class GameState(Protocol):
    """The surface the search sees. All implementations must provide
    these, and only these, to satisfy the framework."""

    def clone(self) -> "GameState":
        """Return an independent copy. Mutating the clone must NOT
        affect the original, and vice versa. Target: thousands per
        second on a reasonable mid-game state."""
        ...  # pragma: no cover

    def active_player(self) -> PlayerID:
        """Whose decision it is *now*. Returns ``CHANCE_PLAYER`` at
        chance nodes. Result is undefined when ``is_terminal()``."""
        ...  # pragma: no cover

    def legal_decisions(self) -> list[Decision]:
        """All legal decisions for the active player. Empty iff
        ``is_terminal()``. At a chance node, returns the list of
        possible outcomes (same as the first element of each tuple
        from ``chance_outcomes()``)."""
        ...  # pragma: no cover

    def chance_outcomes(self) -> list[tuple[Decision, float]]:
        """For chance nodes, return ``(outcome, probability)`` pairs.
        Probabilities must sum to 1.0 (to within float epsilon). Must
        return an empty list when ``active_player() != CHANCE_PLAYER``
        — search algorithms key off the empty-vs-nonempty distinction.

        A concrete game decides what the "outcomes" are — for card
        draw, each outcome is a possible top-card; for a coin flip,
        ``[(True, 0.5), (False, 0.5)]``; and so on.
        """
        ...  # pragma: no cover

    def apply(self, decision: Decision) -> None:
        """Mutate ``self`` by applying ``decision``. Caller is
        responsible for cloning first if they want to preserve the
        pre-apply state. ``decision`` must be one of the values
        returned from the most recent ``legal_decisions()`` call."""
        ...  # pragma: no cover

    def is_terminal(self) -> bool:
        """O(1) terminal check. Once True, no further decisions
        should be applied; ``winner()`` is defined."""
        ...  # pragma: no cover

    def winner(self) -> PlayerID | None:
        """The winning player id, or ``None`` for a draw. Only valid
        when ``is_terminal()``; behavior is undefined otherwise."""
        ...  # pragma: no cover

    def players(self) -> list[PlayerID]:
        """All real player ids in the game, in stable order. Used by
        search algorithms that need to evaluate every player's value
        from a single state. Does NOT include ``CHANCE_PLAYER``."""
        ...  # pragma: no cover
