"""Tree-search + evaluator decision-making framework.

Organized so that the search code is **ignorant of MTG** and talks only
to the abstract ``GameState`` protocol in ``protocol``. This lets us
validate search correctness on toy games (tic-tac-toe, a chance-toy
stand-in for card draw) before wiring it up against the real MTG
engine — per the build plan agreed with the user.

Module map:

- ``protocol``   — ``GameState`` Protocol, ``Decision`` alias, ``PlayerID``.
- ``evaluator``  — ``Evaluator`` ABC (state → scalar in ``[-1, 1]`` from
                   a player's perspective).
- ``budget``     — ``Budget`` dataclass (wall-clock or node-count cap
                   on a single search call).
- ``strategy``   — ``SearchStrategy`` ABC + ``RandomChoice`` baseline.
- ``mcts``       — ``MCTS`` implementation with UCB1 selection, chance-
                   node sampling, and evaluator-at-leaf.
- ``harness``    — Agent-vs-agent match runner + win-rate stats.
- ``toys.*``     — Tiny self-contained ``GameState`` implementations
                   (tic-tac-toe, TTT-with-chance) used to exercise
                   search on known-good games.

Nothing in this subpackage imports from ``mtg_bot.game`` or any other
MTG engine module. Once the scaffold is validated, a real-engine
adapter will live alongside these modules.
"""

from __future__ import annotations

from mtg_bot.search.budget import Budget
from mtg_bot.search.evaluator import (
    Evaluator,
    RandomRolloutEvaluator,
)
from mtg_bot.search.harness import MatchResult, play_one_game, run_match
from mtg_bot.search.mcts import MCTS
from mtg_bot.search.protocol import (
    CHANCE_PLAYER,
    Decision,
    GameState,
    PlayerID,
)
from mtg_bot.search.strategy import RandomChoice, SearchStrategy

__all__ = [
    "Budget",
    "CHANCE_PLAYER",
    "Decision",
    "Evaluator",
    "GameState",
    "MCTS",
    "MatchResult",
    "PlayerID",
    "RandomChoice",
    "RandomRolloutEvaluator",
    "SearchStrategy",
    "play_one_game",
    "run_match",
]
