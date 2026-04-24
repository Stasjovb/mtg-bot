"""Agent-vs-agent match runner.

One ``SearchStrategy`` per player. Plays ``n_games`` complete games
and reports wins, losses, draws, and win-rate for player 0. Used to
measure whether a smarter strategy beats a baseline.

Resetting the initial state between games is the caller's
responsibility — they pass a ``state_factory`` (zero-arg callable
returning a fresh initial state). Chance-node sampling during play
uses the supplied RNG.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable

from mtg_bot.search.protocol import CHANCE_PLAYER, GameState, PlayerID
from mtg_bot.search.strategy import SearchStrategy


@dataclass
class MatchResult:
    """Aggregate record across ``n_games`` games."""

    wins_by_player: dict[PlayerID, int]
    draws: int
    games: int

    def win_rate(self, player_id: PlayerID) -> float:
        """Fraction of games ``player_id`` won (draws don't count)."""
        return self.wins_by_player.get(player_id, 0) / self.games


def play_one_game(
    state_factory: Callable[[], GameState],
    strategies: dict[PlayerID, SearchStrategy],
    rng: random.Random,
) -> PlayerID | None:
    """Play a single game to completion; return the winner's id, or
    ``None`` for a draw.

    Chance nodes are resolved by sampling from the state's
    ``chance_outcomes`` distribution using ``rng``.
    """
    state = state_factory()
    while not state.is_terminal():
        active = state.active_player()
        if active == CHANCE_PLAYER:
            outcomes = state.chance_outcomes()
            decisions = [d for d, _ in outcomes]
            weights = [w for _, w in outcomes]
            decision = rng.choices(decisions, weights=weights, k=1)[0]
            state.apply(decision)
        else:
            strategy = strategies[active]
            decision = strategy.choose(state, active)
            state.apply(decision)
    return state.winner()


def run_match(
    state_factory: Callable[[], GameState],
    strategies: dict[PlayerID, SearchStrategy],
    n_games: int,
    rng: random.Random | None = None,
) -> MatchResult:
    """Play ``n_games`` and return aggregate statistics.

    ``strategies`` maps ``player_id → SearchStrategy``; every
    non-chance player id the game uses must have a strategy.
    """
    rng = rng or random.Random()
    wins: dict[PlayerID, int] = {}
    draws = 0
    for _ in range(n_games):
        winner = play_one_game(state_factory, strategies, rng)
        if winner is None:
            draws += 1
        else:
            wins[winner] = wins.get(winner, 0) + 1
    return MatchResult(wins_by_player=wins, draws=draws, games=n_games)
