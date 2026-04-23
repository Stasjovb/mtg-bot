"""Tests for Requiem Monolith's simplified one-shot activated ability."""

from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS, EOE_SPELLS, SYNTHETIC_CREATURES
from mtg_bot.effects import RequiemMonolithActivatedEffect
from mtg_bot.game import GameState, Player, Zone


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def test_effect_pings_target_and_draws_loses_life():
    state = _new_state()
    for _ in range(3):
        c = state.new_object(BASIC_LANDS["Plains"], 1, Zone.LIBRARY)
        state.players[1].library.append(c)
    enemy_bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    life_before = state.players[1].life
    RequiemMonolithActivatedEffect().resolve(
        state, 0, (("creature", enemy_bear.id),),
    )
    assert enemy_bear.damage == 1
    assert state.players[1].life == life_before - 1
    assert len(state.players[1].hand) == 1


def test_effect_noop_no_target():
    state = _new_state()
    RequiemMonolithActivatedEffect().resolve(state, 0, ())


def test_effect_wrong_kind_noop():
    state = _new_state()
    RequiemMonolithActivatedEffect().resolve(state, 0, (("player", 0),))


def test_effect_describe():
    d = RequiemMonolithActivatedEffect().describe()
    assert "target creature" in d


def test_requiem_printing_has_sorcery_speed_activated():
    m = EOE_SPELLS["Requiem Monolith"]
    assert len(m.activated_abilities) == 1
    a = m.activated_abilities[0]
    assert a.sorcery_speed
    assert a.cost.tap_self
