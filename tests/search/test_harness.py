"""Tests for the match-runner harness."""

import random

from mtg_bot.search import MatchResult, RandomChoice, play_one_game, run_match
from mtg_bot.search.toys.pig import Pig
from mtg_bot.search.toys.tic_tac_toe import TicTacToe


def test_play_one_game_tic_tac_toe_returns_player_or_draw():
    rng = random.Random(0)
    strategies = {0: RandomChoice(rng=random.Random(1)),
                  1: RandomChoice(rng=random.Random(2))}
    winner = play_one_game(TicTacToe, strategies, rng)
    assert winner in (0, 1, None)


def test_play_one_game_pig_resolves_chance_nodes_via_rng():
    rng = random.Random(42)
    strategies = {0: RandomChoice(rng=random.Random(1)),
                  1: RandomChoice(rng=random.Random(2))}
    winner = play_one_game(lambda: Pig(target=5), strategies, rng)
    # Pig with target=5 always terminates with a winner (no draws).
    assert winner in (0, 1)


def test_run_match_aggregates_results():
    rng = random.Random(0)
    strategies = {0: RandomChoice(rng=random.Random(1)),
                  1: RandomChoice(rng=random.Random(2))}
    result = run_match(
        state_factory=TicTacToe,
        strategies=strategies,
        n_games=10,
        rng=rng,
    )
    assert isinstance(result, MatchResult)
    assert result.games == 10
    total = sum(result.wins_by_player.values()) + result.draws
    assert total == 10


def test_win_rate_calculation():
    r = MatchResult(wins_by_player={0: 7, 1: 2}, draws=1, games=10)
    assert r.win_rate(0) == 0.7
    assert r.win_rate(1) == 0.2
    # A player with no wins gets 0.0 (no KeyError).
    assert r.win_rate(999) == 0.0


def test_run_match_default_rng():
    # Smoke: when rng is None, a default is created.
    strategies = {0: RandomChoice(rng=random.Random(1)),
                  1: RandomChoice(rng=random.Random(2))}
    result = run_match(
        state_factory=TicTacToe,
        strategies=strategies,
        n_games=3,
    )
    assert result.games == 3
