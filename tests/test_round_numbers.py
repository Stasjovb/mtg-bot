"""``mtg_bot.round_numbers.round_of``: both players' turns share a round."""

import pytest

from mtg_bot.round_numbers import round_of


@pytest.mark.parametrize("turn, expected", [
    (1, 1),   # the starting player's first turn
    (2, 1),   # the other player's first turn: same round
    (3, 2),   # the starting player's second turn
    (4, 2),
    (5, 3),
    (199, 100),
    (200, 100),
])
def test_both_turns_of_a_round_share_its_number(turn, expected):
    assert round_of(turn) == expected


def test_turn_zero_maps_to_round_zero():
    # Before the first turn there is no round; the helper must not raise.
    assert round_of(0) == 0


def test_the_screen_gets_the_round_and_the_engine_keeps_the_turn():
    from mtg_bot.game import GameState, Player
    from mtg_bot.serialize import serialize_state

    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    state.turn_number = 2  # the other player's first turn
    snap = serialize_state(state)
    assert snap["turn_number"] == 2
    assert snap["round_number"] == 1
    state.turn_number = 3
    assert serialize_state(state)["round_number"] == 2
