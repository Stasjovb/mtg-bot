"""Tests for Skystinger's "blocks a creature with flying" trigger."""

from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.actions import drain_stack
from mtg_bot.combat import declare_blockers
from mtg_bot.game import GameState, Player, Zone, effective_power

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def test_skystinger_pumps_when_blocking_flier():
    state = _new_state()
    stinger = state.new_object(
        _PRINTINGS["Skystinger"], 0, Zone.BATTLEFIELD,
    )
    stinger.summoning_sick = False
    state.battlefield.append(stinger)
    flier = state.new_object(
        SYNTHETIC_CREATURES["Sky Sentinel"], 1, Zone.BATTLEFIELD,
    )
    # Sky Sentinel is 1/3 with no flying baseline — give it flying.
    # Wait actually check keywords.
    state.battlefield.append(flier)
    # Use Scale Drake (2/3) or similar with flying. Check keywords.
    # Let me just give this one flying manually for the test.
    flier.temp_keywords = flier.temp_keywords | frozenset({"flying"})
    flier.attacking = True
    declare_blockers(state, {stinger.id: flier.id})
    drain_stack(state)
    # Skystinger gets +5/+0 UEOT.
    assert stinger.temp_power_bonus == 5
    assert stinger.temp_toughness_bonus == 0
    assert effective_power(state, stinger) == 3 + 5


def test_skystinger_no_pump_when_blocking_non_flier():
    state = _new_state()
    stinger = state.new_object(
        _PRINTINGS["Skystinger"], 0, Zone.BATTLEFIELD,
    )
    stinger.summoning_sick = False
    state.battlefield.append(stinger)
    ground = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    ground.attacking = True
    state.battlefield.append(ground)
    declare_blockers(state, {stinger.id: ground.id})
    assert stinger.temp_power_bonus == 0
