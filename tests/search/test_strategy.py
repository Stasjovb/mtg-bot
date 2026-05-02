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


def test_random_choice_choose_with_visits_returns_empty_dict():
    """The default ``choose_with_visits`` lives on ``SearchStrategy``
    and returns ``{}`` for strategies (like ``RandomChoice``) that
    don't expose visit counts. The data-gen pipeline relies on this
    contract — an empty dict signals "no policy supervision for
    this sample" so the row is recorded value-only."""
    s = TicTacToe()
    visits = RandomChoice(rng=random.Random(42)).choose_with_visits(
        s, player_id=0,
    )
    assert visits == {}


def test_choose_with_visits_default_does_not_run_search():
    """The base default returns ``{}`` without calling ``choose()``
    or any other search method — important because data-gen's
    sample path calls ``choose_with_visits`` first and only falls
    back to ``choose()`` when the visits dict is empty. If the
    default re-entered ``choose``, baseline strategies would
    double-pay (and MCTS subclasses that override the method
    would be unaffected)."""

    class _Recorder(SearchStrategy):
        def __init__(self):
            self.choose_calls = 0

        def choose(self, state, player_id):
            self.choose_calls += 1
            return next(iter(state.legal_decisions()))

    rec = _Recorder()
    s = TicTacToe()
    visits = rec.choose_with_visits(s, player_id=0)
    assert visits == {}
    assert rec.choose_calls == 0
