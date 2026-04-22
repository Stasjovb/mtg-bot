"""Tests for the +1/+1 counter primitive: effective P/T, combat, and SBAs."""

from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.combat import declare_attackers, declare_blockers, resolve_combat_damage
from mtg_bot.game import (
    GameObject,
    GameState,
    Player,
    Zone,
    effective_power,
    effective_toughness,
)
from mtg_bot.turn import state_based_actions


def _put_on_bf(state, printing, controller_id=0, counters=0):
    obj = state.new_object(printing, owner_id=controller_id, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    obj.plus_one_counters = counters
    state.battlefield.append(obj)
    return obj


def _setup_two_players():
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    return state


def test_effective_power_adds_counters():
    state = _setup_two_players()
    bear = _put_on_bf(state, SYNTHETIC_CREATURES["Wild Bear"], counters=2)  # 2/2 base
    assert effective_power(bear) == 4
    assert effective_toughness(bear) == 4


def test_effective_power_of_non_creature_is_zero():
    state = _setup_two_players()
    from mtg_bot.cards import BASIC_LANDS
    forest = _put_on_bf(state, BASIC_LANDS["Forest"])
    assert effective_power(forest) == 0
    assert effective_toughness(forest) == 0


def test_counter_prevents_lethal_damage():
    state = _setup_two_players()
    bear = _put_on_bf(state, SYNTHETIC_CREATURES["Wild Bear"], counters=1)  # now 3/3
    bear.damage = 2  # not lethal for 3-toughness creature
    state_based_actions(state)
    assert bear in state.battlefield


def test_damage_reaches_lethal_even_with_counter():
    state = _setup_two_players()
    bear = _put_on_bf(state, SYNTHETIC_CREATURES["Wild Bear"], counters=1)  # 3/3
    bear.damage = 3
    state_based_actions(state)
    assert bear not in state.battlefield


def test_counter_boosts_combat_damage_dealt():
    state = _setup_two_players()
    attacker = _put_on_bf(state, SYNTHETIC_CREATURES["Wild Bear"], 0, counters=1)  # 3/3
    declare_attackers(state, [attacker.id])
    resolve_combat_damage(state, defending_player_id=1)
    assert state.players[1].life == 20 - 3


def test_bigger_creature_with_counter_survives_smaller_attacker():
    state = _setup_two_players()
    attacker = _put_on_bf(state, SYNTHETIC_CREATURES["Wild Bear"], 0)       # 2/2
    blocker = _put_on_bf(state, SYNTHETIC_CREATURES["Wild Bear"], 1, counters=1)  # 3/3
    declare_attackers(state, [attacker.id])
    declare_blockers(state, {blocker.id: attacker.id})
    resolve_combat_damage(state, defending_player_id=1)
    state_based_actions(state)
    # 2/2 vs 3/3: attacker takes 3 (dies), blocker takes 2 (still has 1 left)
    assert attacker not in state.battlefield
    assert blocker in state.battlefield
    assert blocker.damage == 2


def test_counters_default_to_zero():
    state = _setup_two_players()
    obj = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.HAND)
    assert obj.plus_one_counters == 0


def test_serialize_exposes_counter_count_and_effective_pt():
    from mtg_bot.serialize import serialize_permanent

    state = _setup_two_players()
    bear = _put_on_bf(state, SYNTHETIC_CREATURES["Wild Bear"], counters=2)
    d = serialize_permanent(bear)
    assert d["plus_one_counters"] == 2
    assert d["effective_power"] == 4
    assert d["effective_toughness"] == 4
    assert d["power"] == 2  # base still present
    assert d["toughness"] == 2
