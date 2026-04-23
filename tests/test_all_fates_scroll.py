"""Tests for All-Fates Scroll's simplified sac-draw activated."""

from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS, EOE_SPELLS
from mtg_bot.effects import AllFatesScrollDrawEffect
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


def test_effect_draws_equal_to_distinct_land_names():
    state = _new_state()
    # 3 Plains, 2 Forests, 1 Island → 3 distinct names → draw 3.
    for _ in range(3):
        _put(state, BASIC_LANDS["Plains"])
    for _ in range(2):
        _put(state, BASIC_LANDS["Forest"])
    _put(state, BASIC_LANDS["Island"])
    for _ in range(5):
        c = state.new_object(BASIC_LANDS["Swamp"], 0, Zone.LIBRARY)
        state.players[0].library.append(c)
    AllFatesScrollDrawEffect().resolve(state, 0, ())
    assert len(state.players[0].hand) == 3


def test_effect_draws_zero_when_no_lands():
    state = _new_state()
    for _ in range(3):
        c = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        state.players[0].library.append(c)
    AllFatesScrollDrawEffect().resolve(state, 0, ())
    assert len(state.players[0].hand) == 0


def test_effect_describe():
    d = AllFatesScrollDrawEffect().describe()
    assert "X cards" in d and "differently named" in d


def test_scroll_printing_has_activated_ability():
    s = EOE_SPELLS["All-Fates Scroll"]
    assert len(s.activated_abilities) == 1
    a = s.activated_abilities[0]
    assert a.cost.tap_self
    assert a.cost.sacrifice_self
    assert a.cost.mana_str == "{7}"
