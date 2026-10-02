"""Vintage Roto P3: creature-side costs (Phyrexian Dreadnought, ...)."""

from __future__ import annotations

from mtg_bot.actions import drain_stack, put_into_battlefield
from mtg_bot.cards.base import make_creature
from mtg_bot.effects.generic import roto_mana as rm
from mtg_bot.game import Zone

from tests._roto_helpers import arena, printing, put


def _enter(state, printing_, controller=0):
    obj = state.new_object(printing_, owner_id=controller, zone=Zone.STACK)
    put_into_battlefield(state, obj, controller)
    return obj


def test_dreadnought_dies_without_twelve_power_to_sacrifice():
    s = arena()
    bear = put(s, make_creature("Bear", "{1}{G}", 2, 2), 0)
    s.players[0].agent.yes = False
    dread = _enter(s, printing("Phyrexian Dreadnought"))
    drain_stack(s)
    assert dread not in s.battlefield and bear in s.battlefield


def test_dreadnought_stays_when_other_creatures_pay_the_power():
    s = arena()
    giants = [put(s, make_creature("Giant", "{6}", 6, 6), 0) for _ in range(2)]
    bear = put(s, make_creature("Bear", "{1}{G}", 2, 2), 0)
    s.players[0].agent.sacrifices = [g.id for g in giants]
    dread = _enter(s, printing("Phyrexian Dreadnought"))
    drain_stack(s)
    assert dread in s.battlefield and bear in s.battlefield
    assert all(g not in s.battlefield for g in giants)


def test_dreadnought_can_pay_with_itself():
    s = arena()
    s.players[0].agent.sacrifices = []
    dread = _enter(s, printing("Phyrexian Dreadnought"))
    drain_stack(s)
    # Its own 12 power pays: it is sacrificed either way.
    assert dread not in s.battlefield
    assert "total power 12" in rm.SacrificeSourceUnlessSacrificeTotalPower(
        total_power=12,
    ).describe()
