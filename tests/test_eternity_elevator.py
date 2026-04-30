"""Tests for The Eternity Elevator — non-animating Legendary Spacecraft.

Covers the engine additions from engine-kavaron-elevator:
- ``make_spacecraft(station_threshold=None)`` produces a Spacecraft that
  never becomes a creature (``is_stationed`` always returns False).
- ``ActivatedAbility(tier_threshold=N)`` gates the tier-gated mana ability
  on the Spacecraft having enough charge counters.
- ``effective_activated_abilities`` filters out gated abilities when the
  source doesn't meet the threshold.
- ``AddChargeCounterManaOfChosenColor`` produces X mana of any one color
  where X is the source's charge_counter count at resolve time.
"""

from __future__ import annotations

import pytest

from mtg_bot.agents import RandomAgent
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.effects.generic import AddChargeCounterManaOfChosenColor, AddManaToPool
from mtg_bot.game import GameState, Player, Zone, effective_activated_abilities

_PARSER_PRINTINGS = OracleParserCardSource().get_printings()


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    state.active_player_idx = 0
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


# ---------------------------------------------------------------------------
# Parser claims
# ---------------------------------------------------------------------------


def test_eternity_elevator_claimed_by_parser():
    assert "The Eternity Elevator" in _PARSER_PRINTINGS


def test_eternity_elevator_type_line():
    """Grammar-built Eternity Elevator has the correct Legendary Spacecraft
    type line — the bespoke entry previously used ``make_artifact`` without
    the Spacecraft subtype, so this verifies the fix."""
    ee = _PARSER_PRINTINGS["The Eternity Elevator"]
    assert ee.type_line == "Legendary Artifact — Spacecraft"
    assert ee.is_spacecraft
    assert "Legendary" in ee.supertypes


def test_eternity_elevator_never_animates():
    """Eternity Elevator has no station_threshold — it never becomes a
    creature regardless of how many charge counters it accumulates."""
    from mtg_bot.game import is_stationed

    ee = _PARSER_PRINTINGS["The Eternity Elevator"]
    assert ee.station_threshold is None
    state = _new_state()
    obj = _put(state, ee)
    # With no charge counters.
    assert is_stationed(obj) is False
    # Even with many charge counters it should never be stationed.
    obj.charge_counters = 9999
    assert is_stationed(obj) is False


def test_eternity_elevator_has_two_activated_abilities():
    """Grammar-built Eternity Elevator has two activated abilities:
    1. {T}: Add {C}{C}{C} (always-on mana ability)
    2. 20+ | {T}: Add X mana of any one color (tier-gated mana ability)
    """
    ee = _PARSER_PRINTINGS["The Eternity Elevator"]
    assert len(ee.activated_abilities) == 2


def test_eternity_elevator_colorless_mana_ability():
    """First ability is {T}: Add {C}{C}{C} — always-on, is_mana_ability=True."""
    ee = _PARSER_PRINTINGS["The Eternity Elevator"]
    # The {T}: Add {C}{C}{C} ability has no tier_threshold.
    mana_abs = [a for a in ee.activated_abilities if a.tier_threshold == 0]
    assert len(mana_abs) == 1
    ab = mana_abs[0]
    assert ab.cost.tap_self is True
    assert ab.is_mana_ability is True
    assert isinstance(ab.effect, AddManaToPool)
    assert ab.effect.produces == (("C", 3),)


def test_eternity_elevator_tier_gated_mana_ability():
    """Second ability is gated at tier_threshold=20 and produces X mana."""
    ee = _PARSER_PRINTINGS["The Eternity Elevator"]
    tier_abs = [a for a in ee.activated_abilities if a.tier_threshold == 20]
    assert len(tier_abs) == 1
    ab = tier_abs[0]
    assert ab.cost.tap_self is True
    assert ab.is_mana_ability is True
    assert isinstance(ab.effect, AddChargeCounterManaOfChosenColor)


def test_tier_gate_hides_ability_below_threshold():
    """Below 20 charge counters, effective_activated_abilities shows only
    the always-on colorless mana ability."""
    state = _new_state()
    ee_printing = _PARSER_PRINTINGS["The Eternity Elevator"]
    obj = _put(state, ee_printing)
    obj.charge_counters = 0
    avail = effective_activated_abilities(state, obj)
    # Only the {T}: Add {C}{C}{C} ability is available.
    assert len(avail) == 1
    assert avail[0].tier_threshold == 0


def test_tier_gate_shows_ability_at_threshold():
    """At 20+ charge counters, both abilities are available."""
    state = _new_state()
    ee_printing = _PARSER_PRINTINGS["The Eternity Elevator"]
    obj = _put(state, ee_printing)
    obj.charge_counters = 20
    avail = effective_activated_abilities(state, obj)
    assert len(avail) == 2


def test_tier_gate_shows_ability_above_threshold():
    """At 35 charge counters, both abilities are available."""
    state = _new_state()
    ee_printing = _PARSER_PRINTINGS["The Eternity Elevator"]
    obj = _put(state, ee_printing)
    obj.charge_counters = 35
    avail = effective_activated_abilities(state, obj)
    assert len(avail) == 2


# ---------------------------------------------------------------------------
# AddChargeCounterManaOfChosenColor resolution
# ---------------------------------------------------------------------------


def test_add_charge_counter_mana_produces_correct_amount():
    """AddChargeCounterManaOfChosenColor adds mana equal to charge counters."""
    state = _new_state()
    ee_printing = _PARSER_PRINTINGS["The Eternity Elevator"]
    obj = _put(state, ee_printing)
    obj.charge_counters = 7
    state.resolving_source = obj
    try:
        AddChargeCounterManaOfChosenColor().resolve(state, 0, ())
    finally:
        state.resolving_source = None
    p = state.players[0]
    # Agent picks a color; we just verify 7 mana coins were added.
    assert len(p.mana_pool) == 7
    # All coins should be the same color (one color chosen).
    colors = {coin.color for coin in p.mana_pool}
    assert len(colors) == 1


def test_add_charge_counter_mana_noop_when_no_counters():
    """AddChargeCounterManaOfChosenColor is a no-op when charge counters = 0."""
    state = _new_state()
    ee_printing = _PARSER_PRINTINGS["The Eternity Elevator"]
    obj = _put(state, ee_printing)
    obj.charge_counters = 0
    state.resolving_source = obj
    try:
        AddChargeCounterManaOfChosenColor().resolve(state, 0, ())
    finally:
        state.resolving_source = None
    assert len(state.players[0].mana_pool) == 0


def test_add_charge_counter_mana_noop_when_no_source():
    """AddChargeCounterManaOfChosenColor is a no-op when resolving_source is None."""
    state = _new_state()
    state.resolving_source = None
    AddChargeCounterManaOfChosenColor().resolve(state, 0, ())
    assert len(state.players[0].mana_pool) == 0


def test_add_charge_counter_mana_describe():
    d = AddChargeCounterManaOfChosenColor().describe()
    assert "charge counters" in d and "mana" in d
