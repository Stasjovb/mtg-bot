"""Tests for Terrasymbiosis — counters-added-to-your-creature observer
+ once-per-turn draw."""

from mtg_bot.actions import drain_stack
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS, EOE_SPELLS, SYNTHETIC_CREATURES
from mtg_bot.effects import DrawCardsEqualToResolvingCounterAmount
from mtg_bot.game import GameState, Player, Zone, add_plus_one_counters
from tests._etb_helpers import _legacy_or_inferred_key, _matches_legacy_key


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    state.active_player_idx = 0
    return state


def _stock_library(state, player_id, n):
    p = state.players[player_id]
    for _ in range(n):
        c = state.new_object(BASIC_LANDS["Plains"], player_id, Zone.LIBRARY)
        p.library.append(c)


# -----------------------
# DrawCardsEqualToResolvingCounterAmount effect
# -----------------------


def test_effect_draws_equal_to_amount():
    state = _new_state()
    _stock_library(state, 0, 3)
    state.resolving_counter_amount = 2
    try:
        DrawCardsEqualToResolvingCounterAmount().resolve(state, 0, ())
    finally:
        state.resolving_counter_amount = 0
    assert len(state.players[0].hand) == 2


def test_effect_noop_when_zero_amount():
    state = _new_state()
    _stock_library(state, 0, 3)
    DrawCardsEqualToResolvingCounterAmount().resolve(state, 0, ())
    assert len(state.players[0].hand) == 0


def test_effect_describe():
    d = DrawCardsEqualToResolvingCounterAmount().describe()
    assert "draw" in d


# -----------------------
# Terrasymbiosis integration
# -----------------------


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def test_terrasymbiosis_fires_when_counter_added_to_own_creature():
    state = _new_state()
    _put(state, EOE_SPELLS["Terrasymbiosis"])
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    _stock_library(state, 0, 3)
    add_plus_one_counters(state, bear, 1)
    drain_stack(state)
    assert len(state.players[0].hand) == 1


def test_terrasymbiosis_draws_multiple_when_multiple_counters():
    state = _new_state()
    _put(state, EOE_SPELLS["Terrasymbiosis"])
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    _stock_library(state, 0, 5)
    add_plus_one_counters(state, bear, 3)
    drain_stack(state)
    assert len(state.players[0].hand) == 3


def test_terrasymbiosis_once_per_turn():
    state = _new_state()
    _put(state, EOE_SPELLS["Terrasymbiosis"])
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    _stock_library(state, 0, 5)
    add_plus_one_counters(state, bear, 1)
    drain_stack(state)
    add_plus_one_counters(state, bear, 2)
    drain_stack(state)
    # Second add should NOT draw — once per turn.
    assert len(state.players[0].hand) == 1


def test_terrasymbiosis_does_not_fire_for_opponents_counters():
    state = _new_state()
    _put(state, EOE_SPELLS["Terrasymbiosis"])
    enemy_bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    _stock_library(state, 0, 3)
    add_plus_one_counters(state, enemy_bear, 2)
    # Terrasymbiosis belongs to P0; enemy_bear is P1's → doesn't fire.
    assert len(state.players[0].hand) == 0


def test_terrasymbiosis_printing_has_trigger():
    t = EOE_SPELLS["Terrasymbiosis"]
    triggers = {_legacy_or_inferred_key(ab) for ab in t.triggered_abilities}
    assert "counters_added_to_your_creature" in triggers
