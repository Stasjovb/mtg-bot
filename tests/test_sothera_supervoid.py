"""Tests for Sothera, the Supervoid — dies-exile-opponent and end-step
reanimate effects."""

from mtg_bot.actions import drain_stack
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import EOE_SPELLS, SYNTHETIC_CREATURES
from mtg_bot.effects import SotheraEndStepReanimateEffect, SotheraExileOpponentCreatureEffect
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import destroy, run_beginning_of_end_step_triggers
from tests._etb_helpers import _legacy_or_inferred_key, _matches_legacy_key


class _PickFirstAgent(Agent):
    def choose_sacrifice(self, state, player_id, legal_ids):
        return legal_ids[0] if legal_ids else None

    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirstAgent()))
    state.players.append(Player(id=1, agent=_PickFirstAgent()))
    state.active_player_idx = 0
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


# -----------------------
# Dies observer effect
# -----------------------


def test_dies_observer_exiles_opponent_creature():
    state = _new_state()
    sothera = _put(state, EOE_SPELLS["Sothera, the Supervoid"])
    enemy = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    state.resolving_source = sothera
    try:
        SotheraExileOpponentCreatureEffect().resolve(state, 0, ())
    finally:
        state.resolving_source = None
    assert enemy not in state.battlefield
    assert enemy.exiled_by_source == sothera.id
    assert enemy in state.players[1].exile


def test_dies_observer_skips_controller():
    """Each opponent — not controller — chooses their creature."""
    state = _new_state()
    sothera = _put(state, EOE_SPELLS["Sothera, the Supervoid"])
    own = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    state.resolving_source = sothera
    try:
        SotheraExileOpponentCreatureEffect().resolve(state, 0, ())
    finally:
        state.resolving_source = None
    # Own creature untouched.
    assert own in state.battlefield


def test_dies_observer_describe():
    d = SotheraExileOpponentCreatureEffect().describe()
    assert "opponent" in d and "exile" in d


# -----------------------
# Integration: creature dies → observer fires
# -----------------------


def test_creature_dies_triggers_observer_via_pipeline():
    state = _new_state()
    sothera = _put(state, EOE_SPELLS["Sothera, the Supervoid"])
    enemy = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    my_bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    destroy(state, my_bear)
    drain_stack(state)
    assert enemy not in state.battlefield


# -----------------------
# End-step reanimate
# -----------------------


def test_end_step_does_nothing_if_all_players_have_creatures():
    state = _new_state()
    sothera = _put(state, EOE_SPELLS["Sothera, the Supervoid"])
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    run_beginning_of_end_step_triggers(state)
    assert sothera in state.battlefield


def test_end_step_sacrifices_sothera_and_reanimates_when_player_creatureless():
    state = _new_state()
    sothera = _put(state, EOE_SPELLS["Sothera, the Supervoid"])
    # P0 controls no creatures (only Sothera — an enchantment).
    # P1 controls a Wild Bear.
    enemy = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    # Mark the bear exiled-by-Sothera (simulating earlier dies trigger).
    enemy.exiled_by_source = sothera.id
    state.battlefield.remove(enemy)
    enemy.zone = Zone.EXILE
    state.players[1].exile.append(enemy)
    # Now P1 controls no creatures. End-step fires.
    run_beginning_of_end_step_triggers(state)
    drain_stack(state)
    # Sothera sacrificed.
    assert sothera not in state.battlefield
    # Bear reanimated under P0's control with +1/+1 counters.
    assert enemy in state.battlefield
    assert enemy.controller_id == 0
    assert enemy.plus_one_counters == 2


def test_sothera_printing_metadata():
    s = EOE_SPELLS["Sothera, the Supervoid"]
    assert "Legendary" in s.supertypes
    triggers = {_legacy_or_inferred_key(ab) for ab in s.triggered_abilities}
    assert "your_creature_or_artifact_dies" in triggers
    assert "beginning_of_end_step" in triggers
