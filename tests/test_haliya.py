"""Tests for Haliya, Ascendant Cadet's ETB + attacks triggers."""

from mtg_bot.actions import drain_stack, put_into_battlefield, resolve_top_of_stack
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import EOE_CREATURES, SYNTHETIC_CREATURES
from mtg_bot.combat import declare_attackers
from mtg_bot.game import GameState, Player, Zone


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
    triggers = {ab.trigger for ab in h.triggered_abilities}
    assert "etb" in triggers
    assert "attacks" in triggers


def test_haliya_legendary():
    h = EOE_CREATURES["Haliya, Ascendant Cadet"]
    assert "Legendary" in h.supertypes
