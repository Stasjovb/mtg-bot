"""Tests for Infinite Guideline Station's multicolored-count triggers."""

from mtg_bot.actions import drain_stack, put_into_battlefield, resolve_top_of_stack
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES, TOKEN_PRINTINGS
from mtg_bot.combat import declare_attackers
from mtg_bot.effects import (
    CreateTokenPerMulticoloredPermanent,
    DrawCardPerMulticoloredPermanent,
    _multicolored_permanents_count,
)
from mtg_bot.game import GameState, Player, Zone

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def test_multicolored_count_zero_when_no_multicolored():
    state = _new_state()
    # Single-color permanent.
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    assert _multicolored_permanents_count(state, 0) == 0


def test_multicolored_count_one_when_two_color_permanent():
    """Cosmogoyf is {B}{G} — two colors."""
    state = _new_state()
    goyf = state.new_object(
        _PRINTINGS["Cosmogoyf"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(goyf)
    assert _multicolored_permanents_count(state, 0) == 1


def test_multicolored_count_ignores_opponents():
    state = _new_state()
    goyf = state.new_object(
        _PRINTINGS["Cosmogoyf"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(goyf)
    assert _multicolored_permanents_count(state, 0) == 0


def test_create_token_per_multicolored_creates_n_tokens():
    state = _new_state()
    # Two multicolored creatures under P0.
    for _ in range(2):
        g = state.new_object(
            _PRINTINGS["Cosmogoyf"], 0, Zone.BATTLEFIELD,
        )
        state.battlefield.append(g)
    CreateTokenPerMulticoloredPermanent(
        token_printing=TOKEN_PRINTINGS["Robot"], tapped=True,
    ).resolve(state, 0, ())
    robots = [
        o for o in state.battlefield
        if o.printing.name == "Robot" and o.controller_id == 0
    ]
    assert len(robots) == 2
    for r in robots:
        assert r.tapped


def test_create_token_per_multicolored_zero_noop():
    state = _new_state()
    CreateTokenPerMulticoloredPermanent(
        token_printing=TOKEN_PRINTINGS["Robot"],
    ).resolve(state, 0, ())
    robots = [o for o in state.battlefield if o.printing.name == "Robot"]
    assert robots == []


def test_draw_card_per_multicolored_draws_n():
    state = _new_state()
    p = state.players[0]
    for _ in range(3):
        c = state.new_object(BASIC_LANDS["Forest"], 0, Zone.LIBRARY)
        p.library.append(c)
    for _ in range(2):
        g = state.new_object(
            _PRINTINGS["Cosmogoyf"], 0, Zone.BATTLEFIELD,
        )
        state.battlefield.append(g)
    DrawCardPerMulticoloredPermanent().resolve(state, 0, ())
    assert len(p.hand) == 2


def test_draw_card_per_multicolored_empty_library_no_crash():
    state = _new_state()
    goyf = state.new_object(
        _PRINTINGS["Cosmogoyf"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(goyf)
    DrawCardPerMulticoloredPermanent().resolve(state, 0, ())


def test_infinite_guideline_station_etb_creates_tokens():
    state = _new_state()
    goyf = state.new_object(
        _PRINTINGS["Cosmogoyf"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(goyf)
    ship = state.new_object(
        _PRINTINGS["Infinite Guideline Station"], 0, Zone.HAND,
    )
    put_into_battlefield(state, ship, controller_id=0)
    # Resolve stack ETB trigger.
    while state.stack:
        resolve_top_of_stack(state)
    # Infinite Guideline Station is itself multicolored (WUBRG), so it
    # counts as a multicolored permanent on ETB. Cosmogoyf (BG) +
    # Infinite Guideline Station = 2 multicolored permanents → 2 Robots.
    robots = [
        o for o in state.battlefield
        if o.printing.name == "Robot" and o.controller_id == 0
    ]
    assert len(robots) == 2


def test_infinite_guideline_station_attack_trigger_draws():
    state = _new_state()
    p = state.players[0]
    # Put Cosmogoyf on battlefield and a card in library.
    goyf = state.new_object(
        _PRINTINGS["Cosmogoyf"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(goyf)
    drawn = state.new_object(BASIC_LANDS["Forest"], 0, Zone.LIBRARY)
    p.library.append(drawn)
    # Infinite Guideline stationed to creature.
    ship = state.new_object(
        _PRINTINGS["Infinite Guideline Station"], 0, Zone.BATTLEFIELD,
    )
    ship.charge_counters = 12
    ship.summoning_sick = False
    state.battlefield.append(ship)
    declare_attackers(state, [ship.id])
    drain_stack(state)
    assert drawn in p.hand


def test_infinite_guideline_station_threshold_corrected_to_12():
    ship = _PRINTINGS["Infinite Guideline Station"]
    assert ship.station_threshold == 12
