"""Tests for The Seriema's tapped-legendary-indestructible static.

The printed oracle text reads ``Other tapped legendary creatures you
control have indestructible.`` with no tier-gate prefix (no ``N+ |``),
so the static is always-on the moment Seriema is on the battlefield —
it does not depend on Seriema being stationed or having any specific
charge counter count. The previous bespoke factory wired
``tier_threshold=7`` which was faithfulness drift; the parser-built
printing drops that synthetic gate and the tests below pin the
faithful printed behaviour (the static fires regardless of charge
counters).
"""

from mtg_bot.agents import RandomAgent
from mtg_bot.cards import SYNTHETIC_CREATURES, TOKEN_PRINTINGS
from mtg_bot.effects import StaticScope
from mtg_bot.game import (
    GameState,
    Player,
    Zone,
    effective_keywords,
)

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def _legendary_bear(state, controller_id):
    """Make a Wild Bear-like creature marked legendary for testing."""
    # Use All-Fates Stalker which has Legendary support... actually let
    # me just use an EOE legendary creature. Dyadrine is {X}{G}{W} and
    # is Legendary Artifact Creature.
    return state.new_object(
        _PRINTINGS["Dyadrine, Synthesis Amalgam"], controller_id,
        Zone.BATTLEFIELD,
    )


def test_seriema_grants_indestructible_to_tapped_legendaries():
    """The static is always-on (printed without an ``N+ |`` tier
    prefix). With Seriema on the battlefield, every other tapped
    legendary creature the controller controls gains indestructible
    regardless of charge counters."""
    state = _new_state()
    seriema = state.new_object(
        _PRINTINGS["The Seriema"], 0, Zone.BATTLEFIELD,
    )
    seriema.charge_counters = 7
    state.battlefield.append(seriema)
    leg = _legendary_bear(state, 0)
    leg.tapped = True
    state.battlefield.append(leg)
    kws = effective_keywords(state, leg)
    assert "indestructible" in kws


def test_seriema_grants_indestructible_below_station_threshold():
    """The static fires even before Seriema accumulates enough charge
    counters to station — the printed text has no tier-gate prefix, so
    the engine should observe the indestructible grant the moment
    Seriema is on the battlefield. Pins the faithful interpretation of
    the printed always-on shape; the previous bespoke factory's
    ``tier_threshold=7`` was synthetic faithfulness drift."""
    state = _new_state()
    seriema = state.new_object(
        _PRINTINGS["The Seriema"], 0, Zone.BATTLEFIELD,
    )
    seriema.charge_counters = 0  # un-stationed
    state.battlefield.append(seriema)
    leg = _legendary_bear(state, 0)
    leg.tapped = True
    state.battlefield.append(leg)
    kws = effective_keywords(state, leg)
    assert "indestructible" in kws


def test_seriema_doesnt_grant_to_untapped_legendaries():
    state = _new_state()
    seriema = state.new_object(
        _PRINTINGS["The Seriema"], 0, Zone.BATTLEFIELD,
    )
    seriema.charge_counters = 7
    state.battlefield.append(seriema)
    leg = _legendary_bear(state, 0)
    leg.tapped = False  # not tapped
    state.battlefield.append(leg)
    kws = effective_keywords(state, leg)
    assert "indestructible" not in kws


def test_seriema_doesnt_grant_to_non_legendaries():
    state = _new_state()
    seriema = state.new_object(
        _PRINTINGS["The Seriema"], 0, Zone.BATTLEFIELD,
    )
    seriema.charge_counters = 7
    state.battlefield.append(seriema)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    bear.tapped = True
    state.battlefield.append(bear)
    assert "indestructible" not in effective_keywords(state, bear)


def test_seriema_doesnt_grant_to_self():
    """Source is excluded by the OTHER_* scope."""
    state = _new_state()
    seriema = state.new_object(
        _PRINTINGS["The Seriema"], 0, Zone.BATTLEFIELD,
    )
    seriema.charge_counters = 7
    seriema.tapped = True
    state.battlefield.append(seriema)
    # Seriema is a stationed Spacecraft (creature) at 7+, tapped, and
    # legendary — but the OTHER_* scope excludes self.
    assert "indestructible" not in effective_keywords(state, seriema)


def test_seriema_doesnt_grant_to_opponents_legendaries():
    state = _new_state()
    seriema = state.new_object(
        _PRINTINGS["The Seriema"], 0, Zone.BATTLEFIELD,
    )
    seriema.charge_counters = 7
    state.battlefield.append(seriema)
    opp_leg = _legendary_bear(state, 1)
    opp_leg.tapped = True
    state.battlefield.append(opp_leg)
    assert "indestructible" not in effective_keywords(state, opp_leg)


def test_static_scope_constant_exists():
    assert StaticScope.OTHER_TAPPED_LEGENDARY_CREATURES_YOU_CONTROL == (
        "other_tapped_legendary_creatures_you_control"
    )
