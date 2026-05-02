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

Batched evaluation: evaluators expose ``batch_evaluate(states,
player_id)`` so MCTS can collect a batch of leaves and submit them
in a single call. The base implementation iterates ``evaluate`` —
correct but with no batch advantage. Subclasses with real batched
compute (NN evaluator → tensor stacking + one forward pass)
override to capture the win.
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from typing import Sequence

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

    def batch_evaluate(
        self, states: Sequence[GameState], player_id: PlayerID,
    ) -> list[float]:
        """Evaluate a batch of states from ``player_id``'s perspective.

        Default implementation iterates ``evaluate`` — correct but
        with no batch advantage. Subclasses with real batched
        compute (NN evaluators that stack into one tensor and run a
        single forward pass) override this method.

        Terminal states are handled identically to ``evaluate`` —
        the per-state short-circuit still runs, so the returned
        list mixes terminal and non-terminal values transparently.

        Returns a list the same length as ``states``, each entry the
        value of the corresponding state for ``player_id``.
        """
        return [self.evaluate(s, player_id) for s in states]

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
