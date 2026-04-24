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
- ``expansion``  — ``ExpansionPolicy`` ABC + ``FullEnumeration`` (classic)
                   and ``ProgressiveWidening`` (budget-aware) — pluggable
                   into MCTS for tunable tree growth.
- ``harness``    — Agent-vs-agent match runner + win-rate stats.
- ``toys.*``     — Tiny self-contained ``GameState`` implementations
                   (tic-tac-toe, TTT-with-chance) used to exercise
                   search on known-good games.
- ``tactical``   — ``DefaultTacticalAgent``: deterministic policy
                   used by the real-engine adapter for mid-resolution
                   + combat callbacks.
- ``engine_adapter`` — ``MtgGameStateAdapter``: wraps a real
                   ``mtg_bot.game.GameState`` to implement the
                   search ``GameState`` protocol.
- ``combat_decisions`` — ``AttackerDecision`` / ``BlockerDecision``
                   search-side decision types for factored combat
                   when the adapter is opt-in for combat exposure.

Search code (protocol, evaluator, strategy, mcts, harness, toys)
remains ignorant of MTG — only ``engine_adapter`` and ``tactical``
import from the engine side.
"""

from __future__ import annotations

from mtg_bot.search.budget import Budget
from mtg_bot.search.combat_decisions import (
    AttackerDecision, BlockerDecision,
)
from mtg_bot.search.engine_adapter import MtgGameStateAdapter
from mtg_bot.search.evaluator import (
    Evaluator,
    RandomRolloutEvaluator,
)
from mtg_bot.search.expansion import (
    ExpansionPolicy,
    FullEnumeration,
    ProgressiveWidening,
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
from mtg_bot.search.tactical import DefaultTacticalAgent

__all__ = [
    "AttackerDecision",
    "BlockerDecision",
    "Budget",
    "CHANCE_PLAYER",
    "Decision",
    "DefaultTacticalAgent",
    "Evaluator",
    "ExpansionPolicy",
    "FullEnumeration",
    "GameState",
    "MCTS",
    "MatchResult",
    "MtgGameStateAdapter",
    "PlayerID",
    "ProgressiveWidening",
    "RandomChoice",
    "RandomRolloutEvaluator",
    "SearchStrategy",
    "play_one_game",
    "run_match",
]
