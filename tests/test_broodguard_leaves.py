"""Tests for Broodguard Elite's leaves-battlefield counter transfer."""

from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import EOE_SPELLS, SYNTHETIC_CREATURES
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import destroy


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state(agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=agent or _PickFirstAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def test_broodguard_transfer_counters_on_death():
    state = _new_state(_PickFirstAgent())
    broodguard = state.new_object(
        EOE_SPELLS["Broodguard Elite"], 0, Zone.BATTLEFIELD,
    )
    broodguard.plus_one_counters = 3
    state.battlefield.append(broodguard)
    # Give P0 a valid target creature.
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    destroy(state, broodguard)
    # Bear now has the 3 counters.
    assert bear.plus_one_counters == 3


def test_broodguard_transfer_counters_zero_noop():
    """If Broodguard has no counters (e.g., X=0), leaves-battlefield
    trigger does nothing useful."""
    state = _new_state(_PickFirstAgent())
    broodguard = state.new_object(
        EOE_SPELLS["Broodguard Elite"], 0, Zone.BATTLEFIELD,
    )
    broodguard.plus_one_counters = 0
    state.battlefield.append(broodguard)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    destroy(state, broodguard)
    assert bear.plus_one_counters == 0


def test_broodguard_printing_has_leaves_trigger():
    p = EOE_SPELLS["Broodguard Elite"]
    triggers = [ab for ab in p.triggered_abilities
                if ab.trigger == "leaves_battlefield"]
    assert len(triggers) == 1
    assert "Insect" in p.subtypes
    assert "Knight" in p.subtypes
