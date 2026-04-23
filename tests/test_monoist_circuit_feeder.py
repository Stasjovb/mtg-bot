"""Tests for Monoist Circuit-Feeder's dual-target dynamic pump/debuff."""

from mtg_bot.actions import put_into_battlefield, resolve_top_of_stack
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import EOE_CREATURES, EOE_SPELLS, SYNTHETIC_CREATURES
from mtg_bot.effects import MonoistCircuitFeederETBEffect
from mtg_bot.game import GameState, Player, Zone


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirstAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


# -----------------------
# Effect-level
# -----------------------


def test_effect_requires_target_and_describe():
    e = MonoistCircuitFeederETBEffect()
    assert e.requires_target()
    d = e.describe()
    assert "+X/+0" in d and "-0/-X" in d


def test_effect_resolve_pumps_own_and_debuffs_opponent():
    state = _new_state()
    # 3 artifacts including Monoist itself → X = 3.
    m = state.new_object(
        EOE_CREATURES["Monoist Circuit-Feeder"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(m)
    from mtg_bot.cards import EOE_SPELLS
    art1 = state.new_object(EOE_SPELLS["Memorial Vault"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(art1)
    art2 = state.new_object(EOE_SPELLS["Infinite Guideline Station"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(art2)
    own_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(own_bear)
    enemy_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(enemy_bear)
    state.resolving_source = m
    try:
        MonoistCircuitFeederETBEffect().resolve(state, 0, ())
    finally:
        state.resolving_source = None
    # X = 3 artifacts (Monoist + Memorial Vault + IGS)
    # Own target should be pumped +3/+0; agent picks first own creature.
    # PickFirst picks Monoist itself (first in own_options) — so Monoist
    # gets +3/+0 and enemy_bear gets -0/-3.
    total_own_pump = m.temp_power_bonus + own_bear.temp_power_bonus
    assert total_own_pump == 3
    assert enemy_bear.temp_toughness_bonus == -3


def test_effect_no_opponent_creature_only_pumps_own():
    state = _new_state()
    m = state.new_object(
        EOE_CREATURES["Monoist Circuit-Feeder"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(m)
    own_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(own_bear)
    state.resolving_source = m
    try:
        MonoistCircuitFeederETBEffect().resolve(state, 0, ())
    finally:
        state.resolving_source = None
    # X = 1 (just Monoist). PickFirst picks Monoist for own slot → +1/+0.
    total_own_pump = m.temp_power_bonus + own_bear.temp_power_bonus
    assert total_own_pump == 1


def test_effect_no_own_creatures_only_debuffs_opponent():
    state = _new_state()
    # No own creatures on bf. Opponent bear.
    enemy_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(enemy_bear)
    # Pretend controller has 2 artifacts elsewhere — set via battlefield.
    from mtg_bot.cards import EOE_SPELLS
    art = state.new_object(EOE_SPELLS["Memorial Vault"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(art)
    state.resolving_source = art
    try:
        MonoistCircuitFeederETBEffect().resolve(state, 0, ())
    finally:
        state.resolving_source = None
    # X = 1 artifact. enemy_bear gets -0/-1.
    assert enemy_bear.temp_toughness_bonus == -1


# -----------------------
# Integration
# -----------------------


def test_monoist_etb_fires_through_trigger_pipeline():
    state = _new_state()
    own_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(own_bear)
    enemy_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(enemy_bear)
    monoist = state.new_object(
        EOE_CREATURES["Monoist Circuit-Feeder"], 0, Zone.HAND,
    )
    put_into_battlefield(state, monoist, controller_id=0)
    while state.stack:
        resolve_top_of_stack(state)
    # With X=1 (just Monoist), enemy_bear debuffed by 1 toughness.
    assert enemy_bear.temp_toughness_bonus == -1


def test_monoist_printing_has_flying_and_etb():
    m = EOE_CREATURES["Monoist Circuit-Feeder"]
    assert "flying" in m.keywords
    assert m.is_artifact
    triggers = {ab.trigger for ab in m.triggered_abilities}
    assert "etb" in triggers
