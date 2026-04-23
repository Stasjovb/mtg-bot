"""Tests for Ouroboroid's beginning-of-combat counter cascade."""

from mtg_bot.agents import RandomAgent
from mtg_bot.cards import EOE_CREATURES, SYNTHETIC_CREATURES
from mtg_bot.effects import (
    PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower,
)
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import run_beginning_of_combat_triggers


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def test_ouroboroid_adds_counters_equal_to_its_power_each_combat():
    state = _new_state()
    state.active_player_idx = 0
    ouro = state.new_object(
        EOE_CREATURES["Ouroboroid"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(ouro)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    run_beginning_of_combat_triggers(state)
    # Ouroboroid power is 1; each creature gets 1 counter.
    assert ouro.plus_one_counters == 1
    assert bear.plus_one_counters == 1


def test_ouroboroid_counter_cascade_grows_each_combat():
    """Two sequential beginning-of-combat fires: counters compound."""
    state = _new_state()
    state.active_player_idx = 0
    ouro = state.new_object(
        EOE_CREATURES["Ouroboroid"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(ouro)
    # Fire once → Ouro gets 1 counter (from itself), bear doesn't
    # exist so skipped.
    run_beginning_of_combat_triggers(state)
    assert ouro.plus_one_counters == 1
    # Fire again → Ouro power is now 2, so each creature gets 2
    # counters. Ouro is the only creature → gets 2 more → 3 total.
    run_beginning_of_combat_triggers(state)
    assert ouro.plus_one_counters == 3


def test_ouroboroid_no_buff_to_opponent_creatures():
    state = _new_state()
    state.active_player_idx = 0
    ouro = state.new_object(
        EOE_CREATURES["Ouroboroid"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(ouro)
    opp_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(opp_bear)
    run_beginning_of_combat_triggers(state)
    assert opp_bear.plus_one_counters == 0


def test_put_plus_one_counters_equal_to_source_power_no_source_noop():
    state = _new_state()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    effect = PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower()
    effect.resolve(state, 0, ())
    assert bear.plus_one_counters == 0


def test_put_plus_one_counters_equal_source_zero_power_noop():
    state = _new_state()
    source = state.new_object(
        SYNTHETIC_CREATURES["Wall of Stone"], 0, Zone.BATTLEFIELD,
    )
    # Wall of Stone is 0/5 — power 0.
    state.battlefield.append(source)
    state.resolving_source = source
    other = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(other)
    effect = PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower()
    effect.resolve(state, 0, ())
    state.resolving_source = None
    # Zero power → no counters added.
    assert other.plus_one_counters == 0


def test_put_plus_one_counters_equal_source_describe():
    effect = PutPlusOneCountersOnEachCreatureYouControlEqualToSourcePower()
    assert "X +1/+1" in effect.describe()
