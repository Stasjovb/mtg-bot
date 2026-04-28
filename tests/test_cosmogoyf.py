"""Tests for Cosmogoyf: dynamic P/T from cards owned in exile."""

from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.game import (
    GameState,
    Player,
    Zone,
    effective_power,
    effective_toughness,
)

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def test_cosmogoyf_zero_exile_is_zero_over_one():
    state = _new_state()
    goyf = state.new_object(
        _PRINTINGS["Cosmogoyf"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(goyf)
    assert effective_power(state, goyf) == 0
    assert effective_toughness(state, goyf) == 1


def test_cosmogoyf_scales_with_exile_size():
    state = _new_state()
    p = state.players[0]
    goyf = state.new_object(
        _PRINTINGS["Cosmogoyf"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(goyf)
    # Add three cards to P0's exile.
    for _ in range(3):
        c = state.new_object(BASIC_LANDS["Plains"], 0, Zone.EXILE)
        p.exile.append(c)
    assert effective_power(state, goyf) == 3
    assert effective_toughness(state, goyf) == 4


def test_cosmogoyf_opponent_exile_does_not_count():
    """Cosmogoyf reads the CONTROLLER's exile, not the opponent's."""
    state = _new_state()
    p1 = state.players[1]
    goyf = state.new_object(
        _PRINTINGS["Cosmogoyf"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(goyf)
    # Put 5 cards in the opponent's exile.
    for _ in range(5):
        c = state.new_object(BASIC_LANDS["Plains"], 1, Zone.EXILE)
        p1.exile.append(c)
    assert effective_power(state, goyf) == 0


def test_cosmogoyf_plus_one_counters_add_on_top_of_dynamic():
    """Static +1/+1 bonuses + counters still add to Cosmogoyf's
    dynamic base."""
    state = _new_state()
    p = state.players[0]
    goyf = state.new_object(
        _PRINTINGS["Cosmogoyf"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(goyf)
    for _ in range(2):
        c = state.new_object(BASIC_LANDS["Plains"], 0, Zone.EXILE)
        p.exile.append(c)
    goyf.plus_one_counters = 1
    # Dynamic base = 2/3, +1/+1 counter → 3/4.
    assert effective_power(state, goyf) == 3
    assert effective_toughness(state, goyf) == 4


def test_cosmogoyf_subtypes():
    goyf = _PRINTINGS["Cosmogoyf"]
    assert "Elemental" in goyf.subtypes
    assert "Lhurgoyf" in goyf.subtypes


def test_cosmogoyf_dynamic_pt_formula_set():
    assert _PRINTINGS["Cosmogoyf"].dynamic_pt_formula == "cosmogoyf"


def test_non_dynamic_creature_uses_printed_pt():
    """Regression: existing creatures without dynamic_pt_formula must
    continue to use printed P/T."""
    state = _new_state()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    assert bear.printing.dynamic_pt_formula is None
    assert effective_power(state, bear) == 2
    assert effective_toughness(state, bear) == 2
