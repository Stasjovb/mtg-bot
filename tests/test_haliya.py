"""Tests for Haliya, Ascendant Cadet's ETB + attacks triggers."""

from mtg_bot.actions import drain_stack, put_into_battlefield, resolve_top_of_stack
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import BASIC_LANDS, EOE_CREATURES, SYNTHETIC_CREATURES
from mtg_bot.combat import (
    _fire_combat_damage_to_player_triggers,
    declare_attackers,
)
from mtg_bot.game import GameState, Player, Zone
from tests._etb_helpers import _legacy_or_inferred_key, _matches_legacy_key


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state(agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=agent or _PickFirstAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def test_haliya_etb_puts_counter_on_target():
    state = _new_state(_PickFirstAgent())
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    haliya = state.new_object(
        EOE_CREATURES["Haliya, Ascendant Cadet"], 0, Zone.HAND,
    )
    put_into_battlefield(state, haliya, controller_id=0)
    while state.stack:
        resolve_top_of_stack(state)
    # Agent picks first legal target — legal_targets returns creatures
    # P0 controls (Bear + Haliya). Picks first = bear.
    assert bear.plus_one_counters == 1 or haliya.plus_one_counters == 1


def test_haliya_attack_puts_counter_on_target():
    state = _new_state(_PickFirstAgent())
    haliya = state.new_object(
        EOE_CREATURES["Haliya, Ascendant Cadet"], 0, Zone.BATTLEFIELD,
    )
    haliya.summoning_sick = False
    state.battlefield.append(haliya)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    declare_attackers(state, [haliya.id])
    drain_stack(state)
    # Attacks trigger fires, some creature gets a counter.
    assert haliya.plus_one_counters + bear.plus_one_counters >= 1


def test_haliya_printing_has_both_triggers():
    h = EOE_CREATURES["Haliya, Ascendant Cadet"]
    triggers = {_legacy_or_inferred_key(ab) for ab in h.triggered_abilities}
    assert "etb" in triggers
    assert "attacks" in triggers
    assert (
        "your_counter_creature_combat_damage_to_player_aggregated"
        in triggers
    )


def test_haliya_legendary():
    h = EOE_CREATURES["Haliya, Ascendant Cadet"]
    assert "Legendary" in h.supertypes


# -----------------------
# Aggregated combat-damage trigger (draw a card)
# -----------------------


def _stock_library(state, player_id, n):
    p = state.players[player_id]
    for _ in range(n):
        c = state.new_object(BASIC_LANDS["Plains"], player_id, Zone.LIBRARY)
        p.library.append(c)


def _new_combat_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    state.players.append(Player(id=2, agent=RandomAgent()))
    return state


def test_haliya_aggregated_one_counter_creature_draws_one():
    state = _new_combat_state()
    _stock_library(state, 0, 5)
    haliya = state.new_object(
        EOE_CREATURES["Haliya, Ascendant Cadet"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(haliya)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    bear.plus_one_counters = 1
    state.battlefield.append(bear)
    _fire_combat_damage_to_player_triggers(state, [(bear.id, 1, 2)])
    assert len(state.players[0].hand) == 1


def test_haliya_aggregated_two_counter_creatures_same_player_draws_one():
    state = _new_combat_state()
    _stock_library(state, 0, 5)
    haliya = state.new_object(
        EOE_CREATURES["Haliya, Ascendant Cadet"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(haliya)
    bear1 = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    bear1.plus_one_counters = 1
    state.battlefield.append(bear1)
    bear2 = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    bear2.plus_one_counters = 1
    state.battlefield.append(bear2)
    _fire_combat_damage_to_player_triggers(
        state, [(bear1.id, 1, 2), (bear2.id, 1, 2)],
    )
    # Aggregated: only one card drawn even though two qualifying sources
    # hit P1.
    assert len(state.players[0].hand) == 1


def test_haliya_aggregated_two_counter_creatures_different_players_draws_two():
    state = _new_combat_state()
    _stock_library(state, 0, 5)
    haliya = state.new_object(
        EOE_CREATURES["Haliya, Ascendant Cadet"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(haliya)
    bear1 = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    bear1.plus_one_counters = 1
    state.battlefield.append(bear1)
    bear2 = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    bear2.plus_one_counters = 1
    state.battlefield.append(bear2)
    _fire_combat_damage_to_player_triggers(
        state, [(bear1.id, 1, 2), (bear2.id, 2, 2)],
    )
    # Two distinct (controller, target_player) pairs => two cards.
    assert len(state.players[0].hand) == 2


def test_haliya_aggregated_no_counter_creature_draws_zero():
    state = _new_combat_state()
    _stock_library(state, 0, 5)
    haliya = state.new_object(
        EOE_CREATURES["Haliya, Ascendant Cadet"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(haliya)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    # Deliberately NO +1/+1 counters on the source.
    state.battlefield.append(bear)
    _fire_combat_damage_to_player_triggers(state, [(bear.id, 1, 2)])
    assert len(state.players[0].hand) == 0
