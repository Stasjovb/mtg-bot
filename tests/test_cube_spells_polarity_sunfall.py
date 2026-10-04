"""Cube spells-B: Invert Polarity (coin flip: steal or counter a spell)
and Sunfall (exile all creatures, incubate X; Incubator transform)."""

from __future__ import annotations

import pytest

from mtg_bot.actions import (
    ActivateAbility,
    CastSpell,
    apply_action,
    resolve_top_of_stack,
)
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.cards.tokens import TOKEN_PRINTINGS
from mtg_bot.effects.generic.incubate import (
    ExileAllCreaturesThenIncubate,
    Incubate,
    TransformSelfIntoPrinting,
)
from mtg_bot.effects.generic.spell_copies import FlipCoinStealOrCounterTargetSpell
from mtg_bot.effects.formulas import Constant
from mtg_bot.game import StackItem, Zone, effective_power, is_creature_now
from mtg_bot.turn import state_based_actions
from tests._spells_b_helpers import ScriptedAgent, add, add_lands, make_state


@pytest.fixture(scope="module")
def cube():
    return OracleParserCardSource(pool="cube").get_printings()


def _creature(state, pid, name):
    obj = state.new_object(SYNTHETIC_CREATURES[name], pid, Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.battlefield.append(obj)
    return obj


class _Rng:
    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value


def _spell_on_stack(state, pid, name, targets=()):
    card = add(state, pid, name, Zone.STACK)
    state.stack.append(StackItem(source=card, controller_id=pid, targets=targets))
    return card


def test_invert_polarity_printing(cube):
    assert cube["Invert Polarity"].spell_effect == FlipCoinStealOrCounterTargetSpell()


def test_invert_polarity_win_steals_and_retargets():
    state = make_state(agent0=ScriptedAgent(target=[("player", 1)]))
    for _ in range(3):
        add(state, 1, "Island", Zone.LIBRARY)
    recall = _spell_on_stack(state, 1, "Ancestral Recall", (("player", 1),))
    state.rng = _Rng(0.1)
    eff = FlipCoinStealOrCounterTargetSpell()
    assert eff.legal_targets(state, 0) == [("stack", 0)]
    eff.resolve(state, 0, (("stack", 0),))
    item = state.stack[0]
    assert item.controller_id == 0 and recall.controller_id == 0
    assert item.targets == (("player", 1),)
    resolve_top_of_stack(state)
    assert len(state.players[1].hand) == 3  # the scripted retarget kept P1


def test_invert_polarity_loss_counters():
    state = make_state()
    _spell_on_stack(state, 1, "Dark Ritual")
    state.rng = _Rng(0.9)
    FlipCoinStealOrCounterTargetSpell().resolve(state, 0, (("stack", 0),))
    assert state.stack[0].countered


def test_invert_polarity_loss_uncounterable_and_edge_cases():
    import dataclasses

    state = make_state()
    card = _spell_on_stack(state, 1, "Dark Ritual")
    card.printing = dataclasses.replace(card.printing, spell_is_uncounterable=True)
    state.rng = _Rng(0.9)
    eff = FlipCoinStealOrCounterTargetSpell()
    eff.resolve(state, 0, (("stack", 0),))
    assert not state.stack[0].countered
    eff.resolve(state, 0, ())
    eff.resolve(state, 0, (("stack", 5),))
    state.stack[0].countered = True
    eff.resolve(state, 0, (("stack", 0),))
    assert "flip a coin" in eff.describe()


def test_invert_polarity_full_cast():
    state = make_state()
    target = _spell_on_stack(state, 1, "Dark Ritual")
    card = add(state, 0, "Invert Polarity", Zone.HAND)
    add_lands(state, 0, "Island", 2)
    add_lands(state, 0, "Mountain", 1)
    apply_action(state, 0, CastSpell(card.id))
    state.rng.seed(0)
    resolve_top_of_stack(state)
    assert state.stack[0].countered or state.stack[0].controller_id == 0


def test_sunfall_exiles_creatures_and_incubates(cube):
    assert cube["Sunfall"].spell_effect == ExileAllCreaturesThenIncubate()
    state = make_state()
    mine = _creature(state, 0, "Wild Bear")
    theirs = [_creature(state, 1, "Stone Ogre"), _creature(state, 1, "Raging Goblin")]
    land = add(state, 1, "Swamp", Zone.BATTLEFIELD)
    card = add(state, 0, "Sunfall", Zone.HAND)
    add_lands(state, 0, "Plains", 5)
    apply_action(state, 0, CastSpell(card.id))
    resolve_top_of_stack(state)
    assert mine in state.players[0].exile
    assert all(c in state.players[1].exile for c in theirs)
    assert land in state.battlefield
    incubator = next(o for o in state.battlefield if o.printing.name == "Incubator")
    assert incubator.plus_one_counters == 3
    assert not is_creature_now(incubator)
    # {2}: transform into a 3/3 Phyrexian artifact creature.
    add_lands(state, 0, "Plains", 2)
    apply_action(state, 0, ActivateAbility(incubator.id, 0))
    resolve_top_of_stack(state)
    assert incubator.printing is TOKEN_PRINTINGS["Phyrexian"]
    assert is_creature_now(incubator)
    assert effective_power(state, incubator) == 3


def test_incubate_zero_dies_after_transform():
    state = make_state()
    token = None
    Incubate(amount=Constant(0)).resolve(state, 0)
    token = state.battlefield[0]
    state.resolving_source = token
    TransformSelfIntoPrinting(back_printing=TOKEN_PRINTINGS["Phyrexian"]).resolve(state, 0)
    TransformSelfIntoPrinting(back_printing=TOKEN_PRINTINGS["Phyrexian"]).resolve(state, 0)
    state.resolving_source = None
    state_based_actions(state)
    assert state.battlefield == []
    TransformSelfIntoPrinting().resolve(state, 0)
    assert Incubate(amount=2).describe() == "incubate 2"
    assert Incubate(amount=Constant(1)).describe() == "incubate X"
    assert "transform" in TransformSelfIntoPrinting().describe()
    assert "incubate X" in ExileAllCreaturesThenIncubate().describe()
