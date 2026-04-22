"""Tests for the EoE Void turn-state tracking primitive."""

from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS, EOE_SPELLS, SYNTHETIC_CREATURES
from mtg_bot.game import GameState, Player, Zone, is_void_active
from mtg_bot.turn import (
    move_off_battlefield,
    run_cleanup_step,
    state_based_actions,
)


def _setup():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def test_void_inactive_by_default():
    state = _setup()
    assert is_void_active(state) is False


def test_nonland_permanent_leaving_battlefield_activates_void():
    state = _setup()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD
    )
    state.battlefield.append(bear)
    assert not is_void_active(state)
    move_off_battlefield(state, bear, destination="graveyard")
    assert is_void_active(state)
    assert state.permanent_left_battlefield_this_turn is True


def test_token_ceasing_to_exist_activates_void():
    """A token is a nonland permanent. When it ceases to exist it left the
    battlefield, so Void becomes active."""
    from mtg_bot.cards import TOKEN_PRINTINGS

    state = _setup()
    token = state.new_object(
        TOKEN_PRINTINGS["Human Soldier"], owner_id=0, zone=Zone.BATTLEFIELD
    )
    state.battlefield.append(token)
    move_off_battlefield(state, token, destination="graveyard")
    assert is_void_active(state)


def test_land_leaving_battlefield_does_not_activate_void():
    state = _setup()
    forest = state.new_object(
        BASIC_LANDS["Forest"], owner_id=0, zone=Zone.BATTLEFIELD
    )
    state.battlefield.append(forest)
    move_off_battlefield(state, forest, destination="graveyard")
    assert is_void_active(state) is False


def test_creature_dying_via_state_based_actions_activates_void():
    state = _setup()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD
    )
    bear.damage = 2  # lethal for a 2-tough creature
    state.battlefield.append(bear)
    state_based_actions(state)
    assert bear not in state.battlefield
    assert is_void_active(state)


def test_warp_cast_sets_spell_warped_this_turn():
    from mtg_bot.actions import CastSpell, apply_action
    from mtg_bot.cards import EOE_CREATURES

    state = _setup()
    # Enough lands to pay warp cost ({2}{R} for Nova Hellkite)
    state.active_player_idx = 0
    state.priority_player_idx = 0
    hellkite = state.new_object(
        EOE_CREATURES["Nova Hellkite"], owner_id=0, zone=Zone.HAND
    )
    state.players[0].hand.append(hellkite)
    for _ in range(3):
        m = state.new_object(BASIC_LANDS["Mountain"], owner_id=0, zone=Zone.BATTLEFIELD)
        state.battlefield.append(m)
    # Need at least one legal target for the ETB (or the spell can't resolve,
    # but the warp flag is set at CAST time regardless).
    victim = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.BATTLEFIELD
    )
    state.battlefield.append(victim)

    assert not is_void_active(state)
    apply_action(state, 0, CastSpell(hellkite.id, use_warp=True))
    assert state.spell_warped_this_turn is True
    assert is_void_active(state)


def test_void_resets_at_cleanup():
    state = _setup()
    state.active_player_idx = 0
    state.permanent_left_battlefield_this_turn = True
    state.spell_warped_this_turn = True
    assert is_void_active(state)
    run_cleanup_step(state)
    assert not is_void_active(state)
