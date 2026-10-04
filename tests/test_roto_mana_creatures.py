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


# ---------------------------------------------------------------------------
# Rottenmouth Viper
# ---------------------------------------------------------------------------


def _swamps(s, n):
    from mtg_bot.cards.base import make_basic_land

    land = make_basic_land("Swamp", "B")
    return [put(s, land, 0) for _ in range(n)]


def _modes(agent_, picks):
    """Script ``choose_mode`` to answer by mode-label prefix."""
    queue = list(picks)

    def choose_mode(state, player_id, modes):
        want = queue.pop(0)
        return next(i for i, m in enumerate(modes) if m.startswith(want))

    agent_.choose_mode = choose_mode


def _cast_viper(s):
    from mtg_bot.actions import CastSpell, apply_action
    from tests._roto_helpers import to_hand

    viper = to_hand(s, printing("Rottenmouth Viper"), 0)
    apply_action(s, 0, CastSpell(viper.id))
    drain_stack(s)
    return viper


def test_viper_full_price_without_sacrifices_and_enters_trigger():
    from mtg_bot.game import counter_count
    from tests._roto_helpers import agent

    s = arena()
    _swamps(s, 6)
    bear = put(s, make_creature("Bear", "{1}{G}", 2, 2), 0)
    agent(s, 0).x_value = 0
    _modes(agent(s, 1), ["lose"])
    viper = _cast_viper(s)
    assert viper in s.battlefield and bear in s.battlefield
    assert all(o.tapped for o in s.battlefield if o.printing.is_land)
    assert counter_count(viper, "blight") == 1
    assert s.players[1].life == 16


def test_viper_sacrifices_reduce_cost_one_each():
    from mtg_bot.legal import legal_actions
    from mtg_bot.actions import CastSpell
    from tests._roto_helpers import agent, to_hand

    s = arena()
    lands = _swamps(s, 4)
    bears = [put(s, make_creature("Bear", "{1}{G}", 2, 2), 0) for _ in range(2)]
    probe = to_hand(s, printing("Rottenmouth Viper"), 0)
    # {5}{B} with four lands is castable only by sacrificing both Bears
    # (lands are not "nonland permanents").
    assert CastSpell(probe.id) in legal_actions(s, 0)
    s.players[0].hand.remove(probe)
    agent(s, 0).x_value = 0  # wants none; the cost forces the minimum
    _modes(agent(s, 1), ["lose"])
    viper = _cast_viper(s)
    assert viper in s.battlefield
    assert all(b not in s.battlefield for b in bears)
    assert all(l in s.battlefield and l.tapped for l in lands)
    assert any("sacrifices Bear" in line for line in s.log)


def test_viper_unaffordable_without_enough_nonland_permanents():
    from mtg_bot.actions import CastSpell
    from mtg_bot.legal import legal_actions
    from tests._roto_helpers import to_hand

    s = arena()
    _swamps(s, 4)
    put(s, make_creature("Bear", "{1}{G}", 2, 2), 0)
    viper = to_hand(s, printing("Rottenmouth Viper"), 0)
    assert CastSpell(viper.id) not in legal_actions(s, 0)


def test_viper_may_sacrifice_more_than_needed():
    from tests._roto_helpers import agent

    s = arena()
    _swamps(s, 6)
    bears = [put(s, make_creature("Bear", "{1}{G}", 2, 2), 0) for _ in range(2)]
    agent(s, 0).x_value = 2
    _modes(agent(s, 1), ["lose"])
    viper = _cast_viper(s)
    assert viper in s.battlefield
    assert all(b not in s.battlefield for b in bears)
    # {5}{B} - 2 = four lands tapped, two left untapped.
    assert sum(o.tapped for o in s.battlefield if o.printing.is_land) == 4


def test_viper_attack_punishes_per_counter_opponent_choice():
    from mtg_bot.actions import DeclareAttackers, apply_action
    from mtg_bot.game import add_counters, counter_count
    from mtg_bot.turn import Step
    from tests._roto_helpers import agent, to_hand

    s = arena()
    viper = put(s, printing("Rottenmouth Viper"), 0)
    add_counters(s, viper, "blight", 1)
    rock = put(s, make_creature("Rock", "{1}", 1, 1), 1)
    other = put(s, make_creature("Elk", "{2}", 2, 2), 1)
    card = to_hand(s, make_creature("Elf", "{G}", 1, 1), 1)
    agent(s, 1).sacrifices = [rock.id]
    _modes(agent(s, 1), ["sacrifice", "discard"])
    s.step = Step.DECLARE_ATTACKERS
    apply_action(s, 0, DeclareAttackers(attacker_ids=frozenset({viper.id})))
    drain_stack(s)
    assert counter_count(viper, "blight") == 2
    assert rock not in s.battlefield and other in s.battlefield
    assert card in s.players[1].graveyard
    assert s.players[1].life == 20


def test_viper_punishment_offers_only_possible_options():
    s = arena()
    viper = put(s, printing("Rottenmouth Viper"), 0)
    seen = []

    def choose_mode(state, player_id, modes):
        seen.append(tuple(modes))
        return 0

    s.players[1].agent.choose_mode = choose_mode
    s.resolving_source = viper
    rm.CounterOnSourceThenPunishPerCounter(kind="blight", life=4).resolve(s, 0)
    # Opponent has no nonland permanent and no hand: only the life loss.
    assert seen == [("lose 4 life",)]
    assert s.players[1].life == 16
    assert "blight" in rm.CounterOnSourceThenPunishPerCounter().describe()


def _treasure():
    from mtg_bot.cards.base import (
        ActivatedAbility, ActivationCost, CardPrinting, ManaCost,
    )
    from mtg_bot.effects.generic import AddManaToPool

    return CardPrinting(
        name="Treasure (test)", mana_cost_str="", mana_cost=ManaCost(),
        type_line="Token Artifact — Treasure", supertypes=("Token",),
        card_types=("Artifact",), subtypes=("Treasure",),
        activated_abilities=(ActivatedAbility(
            cost=ActivationCost(sacrifice_self=True),
            effect=AddManaToPool(produces=(("any", 1),)),
            is_mana_ability=True,
        ),),
    )


def test_viper_treasure_pays_mana_or_cost_never_both():
    from mtg_bot.actions import CastSpell
    from mtg_bot.legal import legal_actions
    from tests._roto_helpers import agent, to_hand

    # Two Swamps + two Treasures: four mana, or two less for sacrificing
    # them -- never both, so {5}{B} is out of reach.
    s = arena()
    _swamps(s, 2)
    for _ in range(2):
        put(s, _treasure(), 0)
    viper = to_hand(s, printing("Rottenmouth Viper"), 0)
    assert CastSpell(viper.id) not in legal_actions(s, 0)

    # Three Swamps + two Treasures + a Bear: sacrifice the Bear for
    # {4}{B}, the Treasures pay their mana.
    s = arena()
    _swamps(s, 3)
    treasures = [put(s, _treasure(), 0) for _ in range(2)]
    bear = put(s, make_creature("Bear", "{1}{G}", 2, 2), 0)
    agent(s, 0).x_value = 0
    agent(s, 0).sacrifices = [treasures[0].id]  # refused: payment needs it
    _modes(agent(s, 1), ["lose"])
    viper = _cast_viper(s)
    assert viper in s.battlefield and bear not in s.battlefield
    assert all(t not in s.battlefield for t in treasures)
    assert s.players[0].mana_pool == []
