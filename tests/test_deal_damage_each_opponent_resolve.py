"""Engine-resolve tests for ``DealDamageEachOpponent``.

This is the mass-burn half of Ruinous Rampage's choice. Parser tests
match the recognizer; this file exercises the resolve loop directly:
controller-skip, has_lost-skip, multi-opponent damage, and the log
shape.
"""

from __future__ import annotations

from mtg_bot.effects.generic import DealDamageEachOpponent
from mtg_bot.game import GameState, Player


def _new_state(n_players=2):
    state = GameState()
    for i in range(n_players):
        state.players.append(Player(id=i, agent=None))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    return state


def test_resolve_damages_single_opponent():
    state = _new_state()
    state.players[0].life = 20
    state.players[1].life = 20
    DealDamageEachOpponent(amount=3).resolve(state, 0, ())
    assert state.players[0].life == 20  # controller untouched
    assert state.players[1].life == 17
    assert any("P1 takes 3 (life: 17)" in line for line in state.log)


def test_resolve_damages_each_opponent():
    state = _new_state(n_players=3)
    state.players[0].life = 20
    state.players[1].life = 20
    state.players[2].life = 15
    DealDamageEachOpponent(amount=4).resolve(state, 0, ())
    assert state.players[0].life == 20
    assert state.players[1].life == 16
    assert state.players[2].life == 11
    assert any("P1 takes 4 (life: 16)" in line for line in state.log)
    assert any("P2 takes 4 (life: 11)" in line for line in state.log)


def test_resolve_skips_lost_opponents():
    state = _new_state(n_players=3)
    state.players[1].has_lost = True
    state.players[1].life = 0
    state.players[2].life = 10
    DealDamageEachOpponent(amount=5).resolve(state, 0, ())
    # P1 (lost) untouched.
    assert state.players[1].life == 0
    assert state.players[2].life == 5
    assert not any("P1 takes" in line for line in state.log)
    assert any("P2 takes 5" in line for line in state.log)


def test_resolve_default_amount_is_one():
    state = _new_state()
    state.players[1].life = 20
    DealDamageEachOpponent().resolve(state, 0, ())
    assert state.players[1].life == 19


def test_resolve_can_drive_life_negative():
    """No clamp at zero — life-loss state-based actions handle the
    "player at 0 or less life" check elsewhere; this primitive just
    decrements."""
    state = _new_state()
    state.players[1].life = 2
    DealDamageEachOpponent(amount=10).resolve(state, 0, ())
    assert state.players[1].life == -8


def test_describe_text_includes_amount():
    desc = DealDamageEachOpponent(amount=7).describe()
    assert "7" in desc
    assert "each opponent" in desc
