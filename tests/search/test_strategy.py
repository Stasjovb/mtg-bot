"""Tests for ``SearchStrategy`` and the ``RandomChoice`` baseline."""

import random

import pytest

from mtg_bot.search import RandomChoice
from mtg_bot.search.strategy import SearchStrategy
from mtg_bot.search.toys.tic_tac_toe import TicTacToe


def test_random_choice_returns_a_legal_decision():
    s = TicTacToe()
    legal = set(s.legal_decisions())
    agent = RandomChoice(rng=random.Random(42))
    for _ in range(30):
        pick = agent.choose(s, player_id=0)
        assert pick in legal


def test_random_choice_does_not_mutate_state():
    s = TicTacToe()
    before = s.cells()
    RandomChoice(rng=random.Random(0)).choose(s, player_id=0)
    assert s.cells() == before


def test_random_choice_raises_on_terminal_state():
    s = TicTacToe()
    for move in [0, 3, 1, 4, 2]:  # P0 wins; no legal moves now
        s.apply(move)
    with pytest.raises(ValueError):
        RandomChoice().choose(s, player_id=0)


def test_base_strategy_is_abstract():
    with pytest.raises(TypeError):
        SearchStrategy()
