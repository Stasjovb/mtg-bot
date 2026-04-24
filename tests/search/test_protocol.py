"""Tests for the ``GameState`` protocol surface.

These verify that the toy implementations satisfy the structural
protocol — any future MTG-engine adapter must pass the same checks.
"""

from mtg_bot.search import CHANCE_PLAYER, GameState
from mtg_bot.search.toys.pig import Pig
from mtg_bot.search.toys.tic_tac_toe import TicTacToe


def test_tic_tac_toe_satisfies_protocol():
    """``isinstance(x, GameState)`` works thanks to
    ``@runtime_checkable``."""
    assert isinstance(TicTacToe(), GameState)


def test_pig_satisfies_protocol():
    assert isinstance(Pig(), GameState)


def test_chance_player_sentinel_is_negative():
    # Real players use non-negative ids; chance is -1 so int-indexing
    # a player list never accidentally collides.
    assert CHANCE_PLAYER < 0
