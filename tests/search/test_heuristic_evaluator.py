"""Tests for ``MtgHeuristicEvaluator``."""

from __future__ import annotations

import pytest

from mtg_bot.agents import RandomAgent
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.game import Zone
from mtg_bot.search import MtgGameStateAdapter
from mtg_bot.search.heuristic_evaluator import MtgHeuristicEvaluator
from mtg_bot.simulate import setup_game


def _adapter(seed: int = 42) -> MtgGameStateAdapter:
    state = setup_game(
        [RandomAgent(), RandomAgent()], ["G", "R"], seed=seed,
    )
    return MtgGameStateAdapter(state)


def _put_creature(state, name: str, controller_id: int):
    obj = state.new_object(
        SYNTHETIC_CREATURES[name], owner_id=controller_id,
        zone=Zone.BATTLEFIELD,
    )
    obj.summoning_sick = False
    state.battlefield.append(obj)
    return obj


# =====================================================================
# Construction / weights
# =====================================================================

def test_default_weights_normalize():
    evaluator = MtgHeuristicEvaluator()
    total = (
        evaluator.life_weight
        + evaluator.board_weight
        + evaluator.card_weight
    )
    assert abs(total - 1.0) < 1e-9


def test_custom_weights_renormalized():
    evaluator = MtgHeuristicEvaluator(
        life_weight=2.0, board_weight=2.0, card_weight=1.0,
    )
    total = (
        evaluator.life_weight
        + evaluator.board_weight
        + evaluator.card_weight
    )
    assert abs(total - 1.0) < 1e-9
    assert evaluator.life_weight == evaluator.board_weight
    assert evaluator.card_weight < evaluator.life_weight


def test_zero_weights_rejected():
    with pytest.raises(ValueError):
        MtgHeuristicEvaluator(
            life_weight=0, board_weight=0, card_weight=0,
        )


# =====================================================================
# Score range
# =====================================================================

def test_evaluator_returns_value_in_unit_interval():
    """Whatever the position, score must be in [-1, 1]."""
    adapter = _adapter()
    evaluator = MtgHeuristicEvaluator()
    for player_id in (0, 1):
        v = evaluator.evaluate(adapter, player_id)
        assert -1.0 <= v <= 1.0


def test_terminal_short_circuits_to_winner_signal():
    """The base ``Evaluator`` short-circuits terminal states. Verify
    via the public evaluate() method."""
    adapter = _adapter()
    adapter.engine_state.winner_id = 0
    evaluator = MtgHeuristicEvaluator()
    assert evaluator.evaluate(adapter, player_id=0) == 1.0
    assert evaluator.evaluate(adapter, player_id=1) == -1.0


# =====================================================================
# Component sensitivity
# =====================================================================

def test_higher_life_yields_higher_score():
    adapter = _adapter()
    engine = adapter.engine_state
    # P0 is way ahead on life.
    engine.players[0].life = 30
    engine.players[1].life = 5
    evaluator = MtgHeuristicEvaluator()
    assert evaluator.evaluate(adapter, player_id=0) > 0
    assert evaluator.evaluate(adapter, player_id=1) < 0


def test_lower_life_yields_lower_score():
    adapter = _adapter()
    engine = adapter.engine_state
    engine.players[0].life = 5
    engine.players[1].life = 20
    evaluator = MtgHeuristicEvaluator()
    assert evaluator.evaluate(adapter, player_id=0) < 0
    # Symmetry: opponent's score is the negation (zero-sum).
    assert evaluator.evaluate(adapter, player_id=1) > 0


def test_bigger_board_yields_higher_score():
    """All else equal, controlling more creatures wins more."""
    adapter = _adapter()
    engine = adapter.engine_state
    # Equalize life and hand size; only board differs.
    engine.players[0].life = engine.players[1].life
    while len(engine.players[0].hand) > len(engine.players[1].hand):
        engine.players[0].hand.pop()
    while len(engine.players[1].hand) > len(engine.players[0].hand):
        engine.players[1].hand.pop()
    # Five 3/3s for P0; nothing for P1.
    for _ in range(5):
        _put_creature(engine, "Forest Giant", 0)
    evaluator = MtgHeuristicEvaluator()
    assert evaluator.evaluate(adapter, player_id=0) > 0
    assert evaluator.evaluate(adapter, player_id=1) < 0


def test_more_cards_in_hand_yields_higher_score():
    adapter = _adapter()
    engine = adapter.engine_state
    # Equalize life and board; only hand differs.
    engine.players[0].life = engine.players[1].life
    # P0 keeps full hand, P1 has 0 cards.
    engine.players[1].hand.clear()
    evaluator = MtgHeuristicEvaluator()
    assert evaluator.evaluate(adapter, player_id=0) > 0


# =====================================================================
# Symmetry (zero-sum)
# =====================================================================

def test_score_is_approximately_zero_sum():
    """In a 2-player position, P0's score should equal -P1's score
    (perfectly when no clamping happens; bounded by |1| otherwise)."""
    adapter = _adapter()
    engine = adapter.engine_state
    engine.players[0].life = 18
    engine.players[1].life = 14
    evaluator = MtgHeuristicEvaluator()
    s0 = evaluator.evaluate(adapter, player_id=0)
    s1 = evaluator.evaluate(adapter, player_id=1)
    assert abs(s0 + s1) < 1e-9


def test_balanced_position_scores_near_zero():
    """An equal-life, no-board, equal-hand position should score
    very close to 0 from either player's perspective."""
    adapter = _adapter()
    engine = adapter.engine_state
    engine.players[0].life = 20
    engine.players[1].life = 20
    # Match hand sizes.
    while len(engine.players[0].hand) > len(engine.players[1].hand):
        engine.players[0].hand.pop()
    while len(engine.players[1].hand) > len(engine.players[0].hand):
        engine.players[1].hand.pop()
    evaluator = MtgHeuristicEvaluator()
    score = evaluator.evaluate(adapter, player_id=0)
    assert abs(score) < 1e-9


# =====================================================================
# Adapter passthrough
# =====================================================================

def test_evaluator_works_with_raw_engine_state():
    """Falls through to the engine state when given one directly
    (no adapter), for testing convenience."""
    adapter = _adapter()
    engine = adapter.engine_state
    engine.players[0].life = 20
    engine.players[1].life = 10
    evaluator = MtgHeuristicEvaluator()
    # Pass the engine state directly.
    score = evaluator._evaluate_nonterminal(engine, player_id=0)
    assert score > 0
