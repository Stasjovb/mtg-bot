"""Tests for ``Evaluator`` and ``RandomRolloutEvaluator``."""

import random

import pytest

from mtg_bot.search import RandomRolloutEvaluator
from mtg_bot.search.evaluator import Evaluator
from mtg_bot.search.toys.pig import Pig
from mtg_bot.search.toys.tic_tac_toe import TicTacToe


class _LifeDelta(Evaluator):
    """Trivial evaluator for tests — never called on terminals since
    the base class short-circuits."""

    def _evaluate_nonterminal(self, state, player_id):
        # Pig scores; ratio from player_id's perspective in [-1, 1].
        s = state.scores()
        diff = s[player_id] - s[1 - player_id]
        target = 10
        return max(-1.0, min(1.0, diff / target))


def test_base_evaluator_short_circuits_on_terminal_win():
    """Base ``evaluate`` should return +1 for winner regardless of
    what the subclass's non-terminal eval would say."""
    s = TicTacToe()
    for move in [0, 3, 1, 4, 2]:  # X wins top row
        s.apply(move)

    # Dummy subclass; its _evaluate_nonterminal shouldn't be called
    # because the state is terminal.
    class _BadEval(Evaluator):
        def _evaluate_nonterminal(self, state, player_id):
            raise AssertionError("should not be called on terminals")

    assert _BadEval().evaluate(s, player_id=0) == 1.0
    assert _BadEval().evaluate(s, player_id=1) == -1.0


def test_base_evaluator_returns_zero_on_draw():
    s = TicTacToe()
    # Cat's game — sequence matching test_tic_tac_toe.py's draw case.
    for move in [0, 1, 2, 5, 3, 8, 4, 6, 7]:
        s.apply(move)
    assert s.winner() is None and s.is_terminal()

    class _AnyEval(Evaluator):
        def _evaluate_nonterminal(self, state, player_id):
            return 0.5

    assert _AnyEval().evaluate(s, player_id=0) == 0.0


def test_nonterminal_delegates_to_subclass():
    s = Pig(scores=(4, 1), to_move=0, target=10)
    e = _LifeDelta()
    assert e.evaluate(s, player_id=0) == pytest.approx(0.3)
    assert e.evaluate(s, player_id=1) == pytest.approx(-0.3)


def test_base_class_is_abstract():
    with pytest.raises(TypeError):
        Evaluator()  # can't instantiate abstract


def test_rollout_evaluator_returns_sane_value_on_tic_tac_toe():
    # At start of a TTT game, a random-vs-random rollout can go either
    # way. The value must be in [-1, 1].
    e = RandomRolloutEvaluator(rng=random.Random(42))
    s = TicTacToe()
    v = e.evaluate(s, player_id=0)
    assert -1.0 <= v <= 1.0


def test_rollout_evaluator_handles_chance_node():
    e = RandomRolloutEvaluator(rng=random.Random(42))
    s = Pig(target=5)
    v = e.evaluate(s, player_id=0)
    assert -1.0 <= v <= 1.0


def test_rollout_evaluator_terminal_returns_exact_outcome():
    """At a terminal leaf the rollout should short-circuit via the
    base class, returning exact ±1 or 0."""
    e = RandomRolloutEvaluator()
    s = TicTacToe()
    for move in [0, 3, 1, 4, 2]:
        s.apply(move)
    assert e.evaluate(s, player_id=0) == 1.0
    assert e.evaluate(s, player_id=1) == -1.0


def test_rollout_evaluator_does_not_mutate_input_state():
    e = RandomRolloutEvaluator(rng=random.Random(42))
    s = TicTacToe()
    before = s.cells()
    e.evaluate(s, player_id=0)
    assert s.cells() == before
