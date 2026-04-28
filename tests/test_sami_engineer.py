"""Tests for Sami, Ship's Engineer — end-step tapped Robot token
when you control 2+ tapped creatures."""

from mtg_bot.actions import drain_stack
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import run_beginning_of_end_step_triggers
from tests._etb_helpers import _legacy_or_inferred_key, _matches_legacy_key

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    state.active_player_idx = 0
    return state


def _put_tapped(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    obj.tapped = True
    state.battlefield.append(obj)
    return obj


def test_sami_creates_tapped_robot_with_two_tapped_creatures():
    state = _new_state()
    sami = _put_tapped(state, _PRINTINGS["Sami, Ship's Engineer"])
    # Another tapped creature → 2 total.
    _put_tapped(state, SYNTHETIC_CREATURES["Wild Bear"])
    run_beginning_of_end_step_triggers(state)
    drain_stack(state)
    robots = [
        o for o in state.battlefield
        if o.printing.name == "Robot" and o.controller_id == 0
    ]
    assert len(robots) == 1
    assert robots[0].tapped is True
    # Sami herself was already tapped — sanity check she's still on the field.
    assert sami in state.battlefield


def test_sami_does_nothing_with_only_one_tapped_creature():
    state = _new_state()
    _put_tapped(state, _PRINTINGS["Sami, Ship's Engineer"])
    # No other tapped creature → only 1 total.
    run_beginning_of_end_step_triggers(state)
    assert not any(o.printing.name == "Robot" for o in state.battlefield)


def test_sami_does_not_count_opponents_tapped_creatures():
    state = _new_state()
    _put_tapped(state, _PRINTINGS["Sami, Ship's Engineer"])
    # Opponent's tapped bear — shouldn't count toward Sami's threshold.
    _put_tapped(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    run_beginning_of_end_step_triggers(state)
    assert not any(o.printing.name == "Robot" for o in state.battlefield)


def test_sami_printing_metadata():
    s = _PRINTINGS["Sami, Ship's Engineer"]
    assert "Legendary" in s.supertypes
    triggers = {_legacy_or_inferred_key(ab) for ab in s.triggered_abilities}
    assert "beginning_of_end_step" in triggers
