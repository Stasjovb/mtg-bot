"""Tests for the tic-tac-toe toy GameState.

Verifies the protocol is implemented correctly — cloning, legality,
terminal detection, winner identification. These tests don't use
search; they're about the state machine itself.
"""

from mtg_bot.search import CHANCE_PLAYER
from mtg_bot.search.toys.tic_tac_toe import TicTacToe


def test_initial_state_is_empty_and_p0_to_move():
    s = TicTacToe()
    assert s.active_player() == 0
    assert s.legal_decisions() == list(range(9))
    assert s.is_terminal() is False
    assert s.winner() is None


def test_apply_alternates_players():
    s = TicTacToe()
    s.apply(4)  # X center
    assert s.active_player() == 1
    assert 4 not in s.legal_decisions()
    s.apply(0)  # O corner
    assert s.active_player() == 0
    assert s.cells()[4] == 0 and s.cells()[0] == 1


def test_clone_is_independent():
    s = TicTacToe()
    s.apply(0)
    clone = s.clone()
    s.apply(4)
    # Clone still thinks it's P1's turn with only cell 0 filled.
    assert clone.active_player() == 1
    assert clone.cells()[4] is None
    assert clone.cells()[0] == 0


def test_winner_detection_horizontal():
    s = TicTacToe()
    # X: 0, 1, 2 — wins on row 0
    for move in [0, 3, 1, 4, 2]:
        s.apply(move)
    assert s.is_terminal() is True
    assert s.winner() == 0


def test_winner_detection_vertical():
    s = TicTacToe()
    # X: 0, 3, 6 — wins on col 0
    for move in [0, 1, 3, 4, 6]:
        s.apply(move)
    assert s.winner() == 0


def test_winner_detection_diagonal():
    s = TicTacToe()
    # X: 0, 4, 8 — wins on main diagonal
    for move in [0, 1, 4, 2, 8]:
        s.apply(move)
    assert s.winner() == 0


def test_draw_has_no_winner_but_is_terminal():
    s = TicTacToe()
    # A cat's game:
    #   X O X
    #   X X O
    #   O X O
    # Move order (alternating X, O): X=0, O=1, X=2, O=5, X=3, O=8,
    # X=4, O=6, X=7. No line of three for either player.
    for move in [0, 1, 2, 5, 3, 8, 4, 6, 7]:
        s.apply(move)
    assert s.is_terminal()
    assert s.winner() is None


def test_illegal_apply_raises():
    s = TicTacToe()
    s.apply(0)
    import pytest
    with pytest.raises(ValueError):
        s.apply(0)


def test_terminal_legal_decisions_is_empty():
    s = TicTacToe()
    for move in [0, 3, 1, 4, 2]:
        s.apply(move)
    assert s.legal_decisions() == []


def test_no_chance_outcomes():
    s = TicTacToe()
    assert s.chance_outcomes() == []


def test_active_player_never_chance():
    s = TicTacToe()
    assert s.active_player() != CHANCE_PLAYER


def test_players_returns_two():
    s = TicTacToe()
    assert s.players() == [0, 1]


def test_repr_shows_board():
    s = TicTacToe()
    s.apply(0)
    s.apply(4)
    rep = repr(s)
    assert "X" in rep
    assert "O" in rep
    assert "." in rep
