"""Search strategies: produce a ``Decision`` given a ``GameState``.

``SearchStrategy`` is the top-level interface. ``RandomChoice`` is the
trivial baseline that every real strategy must beat to justify its
existence.

MCTS lives in its own module (``mcts``) because it's substantially
bigger and depends on ``Evaluator`` + ``Budget``.
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod

from mtg_bot.search.protocol import Decision, GameState, PlayerID


class SearchStrategy(ABC):
    """Produce a decision for ``player_id`` at ``state``.

    The strategy is free to clone state, run rollouts, consult
    evaluators, etc. Must NOT mutate the caller's ``state``.
    """

    @abstractmethod
    def choose(
        self, state: GameState, player_id: PlayerID
    ) -> Decision:
        """Return one of ``state.legal_decisions()`` for
        ``player_id``. Caller's ``state`` must be unchanged on return.
        """


class RandomChoice(SearchStrategy):
    """Pick uniformly among legal decisions. Zero-heuristic baseline.

    The yardstick every smarter strategy must beat in head-to-head
    matches.
    """

    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random()

    def choose(
        self, state: GameState, player_id: PlayerID
    ) -> Decision:
        legal = state.legal_decisions()
        if not legal:
            raise ValueError(
                "RandomChoice called on a state with no legal decisions"
            )
        return self.rng.choice(legal)
