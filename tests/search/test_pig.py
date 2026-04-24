"""Tests for the Pig push-your-luck dice toy GameState.

Covers chance-node behavior, turn flow, termination, and the
``GameState`` protocol conformance.
"""

import pytest

from mtg_bot.search import CHANCE_PLAYER
from mtg_bot.search.toys.pig import ADVANCE_PROB, BUST_PROB, Pig


def test_initial_state():
    g = Pig()
    assert g.active_player() == 0
    assert g.legal_decisions() == ["roll", "hold"]
    assert g.is_terminal() is False
    assert g.scores() == (0, 0)
    assert g.pending() == 0
    assert g.chance_outcomes() == []


def test_clone_is_independent():
    g = Pig()
    g.apply("roll")
    clone = g.clone()
    clone.apply("advance")
    # Original should still be at its chance node, unchanged.
    assert g.active_player() == CHANCE_PLAYER
    assert g.pending() == 0
    assert clone.pending() == 1


def test_roll_transitions_to_chance_node():
    g = Pig()
    g.apply("roll")
    assert g.active_player() == CHANCE_PLAYER
    assert g.legal_decisions() == ["advance", "bust"]
    outcomes = g.chance_outcomes()
    assert len(outcomes) == 2
    # Probabilities sum to 1.0
    total = sum(p for _, p in outcomes)
    assert abs(total - 1.0) < 1e-9


def test_advance_increments_pending_and_returns_to_roller():
    g = Pig()
    g.apply("roll")
    g.apply("advance")
    assert g.active_player() == 0
    assert g.pending() == 1
    assert g.legal_decisions() == ["roll", "hold"]


def test_bust_clears_pending_and_passes_turn():
    g = Pig()
    g.apply("roll")
    g.apply("advance")
    g.apply("roll")
    g.apply("bust")
    assert g.active_player() == 1
    assert g.pending() == 0
    assert g.scores() == (0, 0)


def test_hold_banks_pending_and_passes_turn():
    g = Pig()
    g.apply("roll")
    g.apply("advance")
    g.apply("roll")
    g.apply("advance")
    g.apply("hold")
    assert g.scores() == (2, 0)
    assert g.pending() == 0
    assert g.active_player() == 1


def test_game_ends_when_target_reached():
    g = Pig(scores=(9, 0), to_move=0, pending=0, target=10)
    g.apply("roll")
    g.apply("advance")
    g.apply("hold")
    assert g.is_terminal()
    assert g.winner() == 0


def test_both_players_tracked_separately():
    g = Pig()
    # P0 banks 3
    g.apply("roll")
    g.apply("advance")
    g.apply("roll")
    g.apply("advance")
    g.apply("roll")
    g.apply("advance")
    g.apply("hold")
    assert g.scores() == (3, 0)
    # P1 banks 2
    g.apply("roll")
    g.apply("advance")
    g.apply("roll")
    g.apply("advance")
    g.apply("hold")
    assert g.scores() == (3, 2)


def test_illegal_decision_raises():
    g = Pig()
    with pytest.raises(ValueError):
        g.apply("frobnicate")


def test_illegal_chance_outcome_raises():
    g = Pig()
    g.apply("roll")
    with pytest.raises(ValueError):
        g.apply("explode")


def test_advance_and_bust_probabilities():
    assert abs(ADVANCE_PROB - 5.0 / 6.0) < 1e-9
    assert abs(BUST_PROB - 1.0 / 6.0) < 1e-9
    assert abs((ADVANCE_PROB + BUST_PROB) - 1.0) < 1e-9


def test_players_returns_two():
    assert Pig().players() == [0, 1]


def test_winner_while_ongoing_is_none():
    assert Pig().winner() is None


def test_terminal_legal_decisions_is_empty():
    g = Pig(scores=(10, 3), to_move=1, target=10)
    assert g.is_terminal()
    assert g.legal_decisions() == []
    assert g.chance_outcomes() == []


def test_repr_reflects_current_state():
    g = Pig()
    g.apply("roll")
    assert "chance" in repr(g).lower()
