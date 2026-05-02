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

    def choose_with_visits(
        self, state: GameState, player_id: PlayerID
    ) -> dict[Decision, int]:
        """Return a per-decision visit-count distribution at the
        root.

        For MCTS-family strategies (``MCTS``, ``PIMC``) this is the
        actual search-tree visit count, and ``choose()`` is a thin
        argmax wrapper around this method's result. For strategies
        that don't have a notion of visit counts (``RandomChoice``,
        toy openers), the default returns an empty dict — the
        AlphaZero-style data-gen pipeline treats an empty dict as
        "no policy supervision available for this sample" and skips
        recording a policy target.

        Subclasses with real visit data SHOULD override this so the
        AlphaZero-style training loop can capture per-state policy
        targets. Visit-count distributions are the supervision
        signal for the policy head, much richer than the per-game
        outcome label the value head uses.

        Signature note: this method's return shape (just the visit
        dict, NOT a (decision, visits) tuple) matches the existing
        ``MCTS.choose_with_visits`` and ``PIMC.choose_with_visits``
        contracts. Callers that want the chosen decision too should
        call ``choose()`` separately or argmax over the dict.
        Sites that need both should call this method ONCE (to avoid
        re-running the search) and argmax themselves — see
        ``data_gen._play_one_game_recording`` for the canonical
        pattern.
        """
        return {}


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
