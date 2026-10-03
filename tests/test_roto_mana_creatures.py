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


# ---------------------------------------------------------------------------
# Vivi Ornitier
# ---------------------------------------------------------------------------


def _vivi_mana_index(vivi):
    return next(
        i for i, a in enumerate(vivi.printing.activated_abilities)
        if a.is_mana_ability
    )


def test_vivi_adds_power_in_blue_red_once_each_of_your_turns():
    from mtg_bot.actions import ActivateAbility, apply_action
    from mtg_bot.legal import legal_actions

    s = arena()
    vivi = put(s, printing("Vivi Ornitier"), 0)
    vivi.plus_one_counters = 2  # printed power 0 -> 2
    idx = _vivi_mana_index(vivi)
    act = ActivateAbility(source_id=vivi.id, ability_index=idx)
    assert act in legal_actions(s, 0)
    s.players[0].agent.colors = ["U", "R"]
    apply_action(s, 0, act)
    assert sorted(c.color for c in s.players[0].mana_pool) == ["R", "U"]
    assert act not in legal_actions(s, 0)  # once each turn
    s.turn_number += 1
    assert act in legal_actions(s, 0)
    s.active_player_idx = 1  # not during the opponent's turn
    s.priority_player_idx = 0
    s.turn_number += 1
    assert act not in legal_actions(s, 0)


def test_vivi_grows_and_pings_on_noncreature_spells():
    from mtg_bot.actions import CastSpell, apply_action, drain_stack
    from mtg_bot.cards.base import make_basic_land

    s = arena()
    vivi = put(s, printing("Vivi Ornitier"), 0)
    put(s, make_basic_land("Mountain", "R"), 0)
    bolt = __import__("tests._roto_helpers", fromlist=["to_hand"]).to_hand(
        s, printing("Lightning Bolt"), 0,
    )
    s.players[0].agent.targets = [("player", 1)]
    apply_action(s, 0, CastSpell(bolt.id))
    drain_stack(s)
    assert vivi.plus_one_counters == 1
    assert s.players[1].life == 20 - 3 - 1


def test_once_each_turn_cost_atom():
    s = arena()
    vivi = put(s, printing("Vivi Ornitier"), 0)
    atom = rm.OnceEachTurnCost(key="k")
    assert atom.payable(s, 0, vivi)
    atom.pay(s, 0, vivi)
    assert not atom.payable(s, 0, vivi)
    s.turn_number += 1
    assert atom.payable(s, 0, vivi)
    atom.pay(s, 0, vivi)
    assert vivi.once_each_turn_used == ((s.turn_number, "k"),)
    assert "once each turn" in atom.describe()
