"""Tests for Pinnacle Starcage — mass exile-until-leaves ETB +
grave-and-robots sac-self activated ability."""

from mtg_bot.actions import put_into_battlefield, resolve_top_of_stack
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import EOE_SPELLS, SYNTHETIC_CREATURES
from mtg_bot.effects import PinnacleStarcageETBEffect, PinnacleStarcageSacEffect
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import destroy


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


# -----------------------
# ETB effect
# -----------------------


def test_etb_exiles_small_creatures_and_artifacts():
    state = _new_state()
    cage = _put(state, EOE_SPELLS["Pinnacle Starcage"])
    # MV 2 creature — will be exiled.
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    # MV 1 artifact — will be exiled.
    block = _put(state, EOE_SPELLS["Nutrient Block"])
    # MV 4 artifact — will NOT be exiled.
    vault = _put(state, EOE_SPELLS["Memorial Vault"])
    state.resolving_source = cage
    try:
        PinnacleStarcageETBEffect().resolve(state, 0, ())
    finally:
        state.resolving_source = None
    assert bear not in state.battlefield
    assert block not in state.battlefield
    assert vault in state.battlefield


def test_etb_skips_lands_and_the_source_itself():
    state = _new_state()
    cage = _put(state, EOE_SPELLS["Pinnacle Starcage"])
    from mtg_bot.cards import BASIC_LANDS
    forest = _put(state, BASIC_LANDS["Forest"])
    state.resolving_source = cage
    try:
        PinnacleStarcageETBEffect().resolve(state, 0, ())
    finally:
        state.resolving_source = None
    assert cage in state.battlefield
    assert forest in state.battlefield


def test_etb_describe():
    d = PinnacleStarcageETBEffect().describe()
    assert "exile" in d and "2 or less" in d


# -----------------------
# Sac effect
# -----------------------


def test_sac_moves_exiled_to_graveyards_and_creates_robots():
    state = _new_state()
    cage = _put(state, EOE_SPELLS["Pinnacle Starcage"])
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    state.resolving_source = cage
    try:
        PinnacleStarcageETBEffect().resolve(state, 0, ())
    finally:
        state.resolving_source = None
    assert bear not in state.battlefield
    # Now activate the sac ability.
    state.resolving_source = cage
    try:
        PinnacleStarcageSacEffect().resolve(state, 0, ())
    finally:
        state.resolving_source = None
    # Bear moved to graveyard.
    assert bear in state.players[0].graveyard
    # One Robot token created.
    robots = [o for o in state.battlefield if o.printing.name == "Robot"]
    assert len(robots) == 1
    # Starcage sacrificed.
    assert cage not in state.battlefield


def test_starcage_cage_leaving_releases_exiled_back_to_battlefield():
    """If Starcage is destroyed (not sacrificed via the activated
    ability), the exiled-until-leaves bookkeeping returns cards."""
    state = _new_state()
    cage = _put(state, EOE_SPELLS["Pinnacle Starcage"])
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    state.resolving_source = cage
    try:
        PinnacleStarcageETBEffect().resolve(state, 0, ())
    finally:
        state.resolving_source = None
    assert bear not in state.battlefield
    destroy(state, cage)
    # Bear released back to battlefield.
    assert bear in state.battlefield
