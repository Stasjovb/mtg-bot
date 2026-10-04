"""Cube spells-B: divided damage (Pyrokinesis, Fire Covenant), the
announced division on the StackItem, and Pyrokinesis's pitch alternative
cost."""

from __future__ import annotations

import pytest

from mtg_bot.actions import CastSpell, apply_action, resolve_top_of_stack
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.cards.parser.card_flow_grammar import parse_card_flow_effect
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.effects.formulas import ResolvingX
from mtg_bot.effects.generic.card_flow import CardFilter
from mtg_bot.effects.generic.divided_damage import (
    DealDamageDividedAmongTargets,
    choose_damage_division,
)
from mtg_bot.game import Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step, state_based_actions
from tests._spells_b_helpers import (
    ScriptedAgent,
    add,
    add_lands,
    make_state,
)


@pytest.fixture(scope="module")
def cube():
    return OracleParserCardSource(pool="cube").get_printings()


def _creature(state, pid, name):
    obj = state.new_object(SYNTHETIC_CREATURES[name], pid, Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.battlefield.append(obj)
    return obj


def test_divided_damage_grammar(cube):
    assert cube["Pyrokinesis"].spell_effect == DealDamageDividedAmongTargets(amount=4)
    assert cube["Pyrokinesis"].alt_cost_exile_from_hand == CardFilter(color="R")
    assert cube["Fire Covenant"].spell_effect == DealDamageDividedAmongTargets(
        amount=ResolvingX(),
    )
    assert parse_card_flow_effect(
        "deals X damage divided as you choose among up to two target "
        "creatures and/or planeswalkers"
    ) == DealDamageDividedAmongTargets(
        amount=ResolvingX(), max_targets=2, include_planeswalkers=True,
    )
    assert parse_card_flow_effect(
        "deals 3 damage divided as you choose among up to many target creatures"
    ) is None


def test_choose_damage_division():
    state = make_state(agent0=ScriptedAgent(x=[0, 9]))
    # First pick clamps up to 1, second clamps down to the upper bound.
    assert choose_damage_division(state, 0, "Pyro", 3, 5) == (1, 3, 1)
    state.players[0].agent = None
    assert choose_damage_division(state, 0, "Pyro", 2, 4) == (3, 1)
    assert choose_damage_division(state, 0, "Pyro", 0, 4) == ()


def test_pyrokinesis_pitch_cast_and_split():
    agent = ScriptedAgent(target=[], x=[2, 1])
    state = make_state(agent0=agent, step=Step.UPKEEP)
    ogre = _creature(state, 1, "Wild Bear")        # 2/2
    goblin = _creature(state, 1, "Raging Goblin")  # 2/1
    runner = _creature(state, 1, "Goblin Runner")  # 2/1
    pyro = add(state, 0, "Pyrokinesis", Zone.HAND)
    fodder = add(state, 0, "Faithless Looting", Zone.HAND)  # red card
    add(state, 0, "Island", Zone.HAND)
    free = CastSpell(pyro.id, cast_for_free=True)
    assert free in legal_actions(state, 0)
    eff = pyro.printing.spell_effect
    agent.scripts["target"] = [("creature", ogre.id), ("creature", goblin.id),
                               ("creature", runner.id), None]
    apply_action(state, 0, free)
    item = state.stack[-1]
    assert item.division == (2, 1, 1)
    assert fodder in state.players[0].exile
    resolve_top_of_stack(state)
    state_based_actions(state)
    assert ogre in state.players[1].graveyard
    assert goblin in state.players[1].graveyard
    assert runner in state.players[1].graveyard
    assert eff.legal_targets(state, 0) == []


def test_pyrokinesis_pitch_needs_another_red_card():
    state = make_state(step=Step.UPKEEP)
    _creature(state, 1, "Stone Ogre")
    pyro = add(state, 0, "Pyrokinesis", Zone.HAND)
    add(state, 0, "Brainstorm", Zone.HAND)
    assert CastSpell(pyro.id, cast_for_free=True) not in legal_actions(state, 0)


def test_fire_covenant_pays_life_targets_capped_by_x():
    agent = ScriptedAgent(x=[3, 2])
    state = make_state(agent0=agent)
    bear = _creature(state, 1, "Wild Bear")        # 2/2
    gob = _creature(state, 1, "Raging Goblin")     # 2/1
    wurm = _creature(state, 1, "Great Wurm")
    mine = _creature(state, 0, "Sapling")
    card = add(state, 0, "Fire Covenant", Zone.HAND)
    add_lands(state, 0, "Swamp", 1)
    add_lands(state, 0, "Mountain", 2)
    eff = card.printing.spell_effect
    # Opponents' creatures are offered first.
    assert eff.legal_targets(state, 0)[-1] == ("creature", mine.id)
    agent.scripts["target"] = [("creature", bear.id), ("creature", gob.id), None]
    apply_action(state, 0, CastSpell(card.id))
    item = state.stack[-1]
    assert state.players[0].life == 17
    assert item.division == (2, 1)
    resolve_top_of_stack(state)
    state_based_actions(state)
    assert bear in state.players[1].graveyard and gob in state.players[1].graveyard
    assert wurm in state.battlefield


def test_fire_covenant_target_count_capped_by_x():
    agent = ScriptedAgent(x=[1])
    state = make_state(agent0=agent)
    bear = _creature(state, 1, "Wild Bear")
    gob = _creature(state, 1, "Raging Goblin")
    card = add(state, 0, "Fire Covenant", Zone.HAND)
    add_lands(state, 0, "Swamp", 1)
    add_lands(state, 0, "Mountain", 2)
    apply_action(state, 0, CastSpell(card.id))
    assert state.stack[-1].targets == (("creature", bear.id),)
    assert state.stack[-1].division == (1,)


def test_useful_x_cap_counts_opponent_toughness_and_loyalty():
    state = make_state()
    _creature(state, 1, "Stone Ogre")
    _creature(state, 0, "Wild Bear")
    eff = DealDamageDividedAmongTargets(amount=ResolvingX(), include_planeswalkers=True)
    assert eff.useful_x_cap(state, 0) == 3


def test_resolve_without_division_and_gone_targets():
    state = make_state()
    ogre = _creature(state, 1, "Stone Ogre")
    eff = DealDamageDividedAmongTargets(amount=2)
    eff.resolve(state, 0, (("creature", ogre.id), ("creature", 999)))
    assert ogre.damage == 2
    state.resolving_division = (1, 1)
    eff.resolve(state, 0, (("creature", ogre.id), ("creature", 999)))
    assert ogre.damage == 3
    assert "any number of" in eff.describe()
    assert "up to 2" in DealDamageDividedAmongTargets(
        amount=ResolvingX(), max_targets=2, include_planeswalkers=True,
    ).describe()


def test_planeswalker_damage_and_doubling():
    import dataclasses

    state = make_state()
    walker = _creature(state, 1, "Stone Ogre")
    walker.printing = dataclasses.replace(
        walker.printing, card_types=("Planeswalker",), type_line="Planeswalker",
    )
    walker.loyalty_counters = 5
    eff = DealDamageDividedAmongTargets(
        amount=ResolvingX(), max_targets=2, include_planeswalkers=True,
        double_if_x_at_least=6,
    )
    assert eff.legal_targets(state, 0) == [("planeswalker", walker.id)]
    assert eff.division_total(state, 0, 6) == 12
    assert eff.division_total(state, 0, 5) == 5
    state.resolving_division = (3,)
    eff.resolve(state, 0, (("planeswalker", walker.id),))
    assert walker.loyalty_counters == 2


def test_mana_x_divided_spell_truncates_targets_to_total():
    import dataclasses

    from mtg_bot.cards import parse_mana_cost

    agent = ScriptedAgent(x=[1])
    state = make_state(agent0=agent)
    bear = _creature(state, 1, "Wild Bear")
    gob = _creature(state, 1, "Raging Goblin")
    card = add(state, 0, "Fire Covenant", Zone.HAND)
    card.printing = dataclasses.replace(
        card.printing, mana_cost=parse_mana_cost("{X}{R}"), mana_cost_str="{X}{R}",
        additional_cost_pay_x_life=False,
    )
    add_lands(state, 0, "Mountain", 2)
    agent.scripts["target"] = [("creature", bear.id), ("creature", gob.id)]
    apply_action(state, 0, CastSpell(card.id))
    assert state.stack[-1].targets == (("creature", bear.id),)
    assert state.stack[-1].division == (1,)
