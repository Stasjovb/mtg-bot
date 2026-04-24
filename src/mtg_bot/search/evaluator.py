"""State evaluators.

An ``Evaluator`` turns a (non-terminal) ``GameState`` into a scalar in
``[-1, 1]`` from a player's perspective. -1 = certain loss, +1 =
certain win, 0 = even. Search algorithms call the evaluator at leaf
nodes to avoid playing the game out to completion — this is the
"give up at some depth and rely on evaluators" part of the agreed
plan.

For terminal states, evaluators SHOULD short-circuit to the true
result (+1 if the asked-for player won, -1 if they lost, 0 for a
draw). The base ABC handles this automatically so subclasses only
need to implement ``_evaluate_nonterminal``.
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod

from mtg_bot.search.protocol import CHANCE_PLAYER, GameState, PlayerID


class Evaluator(ABC):
    """A value function on ``GameState``. Output in ``[-1, 1]`` from
    ``player_id``'s perspective."""

    def evaluate(self, state: GameState, player_id: PlayerID) -> float:
        """Return the value of ``state`` for ``player_id``.

        Terminal states short-circuit to the true result; non-terminal
        states delegate to ``_evaluate_nonterminal``. Subclasses
        override the latter, not this method.
        """
        if state.is_terminal():
            winner = state.winner()
            if winner is None:
                return 0.0
            return 1.0 if winner == player_id else -1.0
        return self._evaluate_nonterminal(state, player_id)

    @abstractmethod
    def _evaluate_nonterminal(
        self, state: GameState, player_id: PlayerID
    ) -> float:
        """Non-terminal value. Must return a value in ``[-1, 1]``."""


class RandomRolloutEvaluator(Evaluator):
    """Play the game out with uniformly-random decisions and report the
    result. A clean, zero-heuristic baseline — the evaluator you use
    when you have no domain knowledge. Slower than a handcrafted
    eval but theoretically unbiased.

    At chance nodes, samples by the declared probability distribution.
    Uses its own ``random.Random`` so search is reproducible when the
    RNG is seeded.
    """

    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random()

    def _evaluate_nonterminal(
        self, state: GameState, player_id: PlayerID
    ) -> float:
        working = state.clone()
        # Walk the game forward, picking decisions uniformly at random
        # at real-player nodes and sampling outcomes at chance nodes.
        while not working.is_terminal():
            active = working.active_player()
            if active == CHANCE_PLAYER:
                outcomes = working.chance_outcomes()
                decisions = [o for o, _ in outcomes]
                weights = [p for _, p in outcomes]
                pick = self.rng.choices(decisions, weights=weights, k=1)[0]
                working.apply(pick)
            else:
                legal = working.legal_decisions()
                if not legal:
                    # Malformed state or degenerate game — bail out.
                    break
                # Store the pick in a local before applying. Inlining
                # the call (``working.apply(self.rng.choice(legal))``)
                # triggered a reproducible Python 3.13 specializing-
                # interpreter bug on this hot path where choice()
                # returned the whole sequence instead of an element.
                pick = self.rng.choice(legal)
                working.apply(pick)
        # Use the base class's terminal handling.
        return self.evaluate(working, player_id)
