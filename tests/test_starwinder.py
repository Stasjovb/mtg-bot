"""Tests for Starwinder's your_creature_combat_damage_to_player observer
trigger and the DrawCardsEqualToResolvingCombatDamage effect."""

from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS, EOE_CREATURES, SYNTHETIC_CREATURES
from mtg_bot.actions import drain_stack
from mtg_bot.combat import _fire_combat_damage_to_player_triggers
from mtg_bot.effects import DrawCardsEqualToResolvingCombatDamage
from mtg_bot.game import GameState, Player, Zone


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def _stock_library(state, player_id, n):
    p = state.players[player_id]
    for _ in range(n):
        c = state.new_object(BASIC_LANDS["Plains"], player_id, Zone.LIBRARY)
        p.library.append(c)


# -----------------------
# DrawCardsEqualToResolvingCombatDamage effect
# -----------------------


def test_effect_draws_cards_equal_to_resolving_amount():
    state = _new_state()
    _stock_library(state, 0, 5)
    state.resolving_combat_damage_amount = 3
    try:
        DrawCardsEqualToResolvingCombatDamage().resolve(state, 0, ())
    finally:
        state.resolving_combat_damage_amount = 0
    assert len(state.players[0].hand) == 3


def test_effect_noop_when_zero_amount():
    state = _new_state()
    _stock_library(state, 0, 5)
    DrawCardsEqualToResolvingCombatDamage().resolve(state, 0, ())
    assert len(state.players[0].hand) == 0


def test_effect_describe_mentions_may_draw():
    d = DrawCardsEqualToResolvingCombatDamage().describe()
    assert "draw" in d


# -----------------------
# Starwinder integration via the combat-damage firing path
# -----------------------


def test_starwinder_draws_equal_to_bear_damage():
    state = _new_state()
    _stock_library(state, 0, 5)
    starwinder = state.new_object(
        EOE_CREATURES["Starwinder"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(starwinder)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    # Simulate bear (2 power) connecting with P1.
    _fire_combat_damage_to_player_triggers(state, [(bear.id, 1, 2)])
    drain_stack(state)
    assert len(state.players[0].hand) == 2


def test_starwinder_draws_equal_to_its_own_damage():
    state = _new_state()
    _stock_library(state, 0, 10)
    starwinder = state.new_object(
        EOE_CREATURES["Starwinder"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(starwinder)
    # Simulate Starwinder (7 power) itself connecting.
    _fire_combat_damage_to_player_triggers(state, [(starwinder.id, 1, 7)])
    drain_stack(state)
    assert len(state.players[0].hand) == 7


def test_starwinder_does_not_fire_for_opponents_creature():
    state = _new_state()
    _stock_library(state, 0, 5)
    starwinder = state.new_object(
        EOE_CREATURES["Starwinder"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(starwinder)
    enemy_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(enemy_bear)
    _fire_combat_damage_to_player_triggers(state, [(enemy_bear.id, 0, 2)])
    # Starwinder belongs to P0; enemy bear is P1's, so observer doesn't fire.
    assert len(state.players[0].hand) == 0


def test_starwinder_printing_has_warp_and_damage_trigger():
    s = EOE_CREATURES["Starwinder"]
    assert s.warp_cost_str == "{2}{U}{U}"
    triggers = {ab.trigger for ab in s.triggered_abilities}
    assert "your_creature_combat_damage_to_player" in triggers
