"""Tests for Magus of the Moon ({2}{R}) — Special Guests creature.

Oracle: Nonbasic lands are Mountains.
"""

from mtg_bot.actions import CastSpell, can_pay_cost, apply_action
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS, SHOCK_LANDS, SYNTHETIC_CREATURES, parse_mana_cost
from mtg_bot.game import (
    GameState, Player, Zone,
    effective_activated_abilities,
    effective_land_produces,
    magus_of_the_moon_active,
)
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put_magus(state: GameState, controller: int = 0):
    obj = state.new_object(
        _PRINTINGS["Magus of the Moon"], controller,
        Zone.BATTLEFIELD,
    )
    state.battlefield.append(obj)
    return obj


def test_magus_is_wired_up():
    m = _PRINTINGS["Magus of the Moon"]
    assert m.mana_cost_str == "{2}{R}"
    assert m.power == 2 and m.toughness == 2
    assert "Human" in m.subtypes and "Wizard" in m.subtypes
    assert m.nonbasic_lands_are_mountains is True


def test_magus_active_helper():
    state = _new_state()
    assert magus_of_the_moon_active(state) is False
    _put_magus(state, 0)
    assert magus_of_the_moon_active(state) is True


def test_effective_produces_basics_unchanged():
    """Basic lands keep their printed colors under Magus."""
    state = _new_state()
    _put_magus(state, 0)
    forest = state.new_object(BASIC_LANDS["Forest"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(forest)
    assert effective_land_produces(state, forest) == frozenset({"G"})


def test_effective_produces_nonbasic_collapses_to_red():
    """Shock lands and utility lands produce only {R} under Magus."""
    state = _new_state()
    _put_magus(state, 0)

    # Hallowed Fountain: Plains Island, produces W/U.
    if "Hallowed Fountain" in SHOCK_LANDS:
        shock = state.new_object(
            SHOCK_LANDS["Hallowed Fountain"], 0, Zone.BATTLEFIELD,
        )
    else:
        shock = state.new_object(
            next(iter(SHOCK_LANDS.values())), 0, Zone.BATTLEFIELD,
        )
    state.battlefield.append(shock)
    assert effective_land_produces(state, shock) == frozenset({"R"})


def test_effective_produces_without_magus():
    """Without Magus on the battlefield, nonbasic lands produce their
    printed colors."""
    state = _new_state()
    shock = state.new_object(
        next(iter(SHOCK_LANDS.values())), 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(shock)
    # Should equal printed `produces`.
    assert effective_land_produces(state, shock) == shock.printing.produces


def test_nonbasic_activated_abilities_suppressed():
    """Utility-land activated abilities are suppressed under Magus."""
    state = _new_state()
    _put_magus(state, 0)
    # Ancient Tomb has an activated ability ({T}: Add {C}{C} + 2 dmg).
    tomb = state.new_object(
        _PRINTINGS["Ancient Tomb"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(tomb)
    assert effective_activated_abilities(state, tomb) == ()


def test_basic_land_activated_abilities_passthrough():
    """Basic lands (which have no printed activated abilities in our
    engine) are not affected by the Magus suppression logic."""
    state = _new_state()
    _put_magus(state, 0)
    forest = state.new_object(BASIC_LANDS["Forest"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(forest)
    # No change — basic lands never had activated abilities anyway.
    assert effective_activated_abilities(state, forest) == (
        forest.printing.activated_abilities
    )


def test_can_pay_red_cost_using_only_nonbasic_under_magus():
    """With two nonbasic lands and Magus in play, a red creature spell
    is payable."""
    state = _new_state()
    _put_magus(state, 0)
    # Put a nonbasic utility land in play (Hallowed Fountain is non-red
    # by default but under Magus taps for {R}).
    shock = state.new_object(
        next(iter(SHOCK_LANDS.values())), 0, Zone.BATTLEFIELD,
    )
    shock.tapped = False
    state.battlefield.append(shock)
    # And one Mountain for the other {R} pip.
    mountain = state.new_object(
        BASIC_LANDS["Mountain"], 0, Zone.BATTLEFIELD,
    )
    mountain.tapped = False
    state.battlefield.append(mountain)
    # Cost {R}{R}.
    cost = parse_mana_cost("{R}{R}")
    assert can_pay_cost(state, 0, cost) is True


def test_cannot_pay_non_red_cost_under_magus_without_basics():
    """Only nonbasics in play + Magus: can't pay {U}."""
    state = _new_state()
    _put_magus(state, 0)
    # Put two Hallowed-Fountain-style shocks in play (printed W/U)
    # but under Magus they produce only {R}.
    for _ in range(2):
        shock = state.new_object(
            next(iter(SHOCK_LANDS.values())), 0, Zone.BATTLEFIELD,
        )
        state.battlefield.append(shock)
    cost = parse_mana_cost("{U}")
    assert can_pay_cost(state, 0, cost) is False


def test_magus_leaving_restores_normal_mana():
    """When Magus leaves play, nonbasic lands revert to their printed
    colors. No caching — each query recomputes."""
    state = _new_state()
    magus = _put_magus(state, 0)
    shock = state.new_object(
        next(iter(SHOCK_LANDS.values())), 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(shock)
    assert effective_land_produces(state, shock) == frozenset({"R"})
    state.battlefield.remove(magus)
    assert effective_land_produces(state, shock) == shock.printing.produces


def test_magus_opponent_controlled_still_applies():
    """Oracle doesn't care whose Magus it is — nonbasic lands become
    Mountains regardless of who controls the creature."""
    state = _new_state()
    _put_magus(state, 1)  # OPPONENT's Magus
    shock = state.new_object(
        next(iter(SHOCK_LANDS.values())), 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(shock)
    assert effective_land_produces(state, shock) == frozenset({"R"})
