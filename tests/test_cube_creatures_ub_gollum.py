"""Gollum, Riddle Master: the odd/even choice as it enters, the
opponent-casts-a-spell-of-the-chosen-quality trigger, and "choose one
that hasn't been chosen"."""

from __future__ import annotations

from mtg_bot.actions import CastSpell, apply_action, drain_stack, put_into_battlefield
from mtg_bot.cards.parser.cube_creatures_ub import parse_ub_creature_line
from mtg_bot.effects.generic.cube_creatures_ub import (
    ModalChooseOneNotYetChosen,
    SpellMVHasSourceParity,
)
from mtg_bot.game import Zone
from tests._spells_b_helpers import PRINTINGS, ScriptedAgent, add, add_lands, make_state


def _gollum(state, parity_index=0):
    state.players[0].agent.scripts["mode"] = [parity_index]
    g = state.new_object(PRINTINGS["Gollum, Riddle Master"], 0, Zone.HAND)
    put_into_battlefield(state, g, 0)
    return g


def test_gollum_printing():
    assert parse_ub_creature_line(
        "As this creature enters, choose odd or even.", "X",
    ).fields == {"chooses_parity_as_enters": True}
    g = PRINTINGS["Gollum, Riddle Master"]
    assert g.chooses_parity_as_enters
    eff = g.triggered_abilities[0].effect
    assert isinstance(eff, ModalChooseOneNotYetChosen) and len(eff.modes) == 3
    assert "hasn't been chosen" in eff.describe()


def test_parity_is_chosen_as_it_enters():
    state = make_state()
    assert _gollum(state, 1).chosen_parity == "even"
    other = make_state()
    assert _gollum(other, 0).chosen_parity == "odd"


def test_each_mode_once_then_nothing():
    agent1 = ScriptedAgent(target=[("player", 0)] * 4)
    state = make_state(agent1=agent1)
    g = _gollum(state, 0)                       # odd
    add(state, 0, "Island", Zone.LIBRARY)
    add_lands(state, 1, "Mountain", 4)
    for i in range(4):
        bolt = add(state, 1, "Lightning Bolt", Zone.HAND)   # MV 1: odd
        state.players[0].agent.scripts["mode"] = [0]
        apply_action(state, 1, CastSpell(bolt.id))
        drain_stack(state)
    assert sorted(g.modes_chosen) == [0, 1, 2]
    assert g.plus_one_counters == 1
    assert state.players[1].life == 18 and len(state.players[0].hand) == 1


def test_even_spells_do_not_trigger_an_odd_gollum():
    state = make_state()
    g = _gollum(state, 0)
    add_lands(state, 1, "Island", 2)
    ring = add(state, 1, "Mind Stone", Zone.HAND)       # MV 2: even
    apply_action(state, 1, CastSpell(ring.id))
    assert len(state.stack) == 1                         # just the spell
    drain_stack(state)
    assert g.modes_chosen == ()


def test_parity_predicate_edge_cases():
    pred = SpellMVHasSourceParity()
    state = make_state()
    g = add(state, 0, "Gollum, Riddle Master", Zone.BATTLEFIELD)
    assert not pred.matches(state, {}, g)
    assert not pred.matches(state, {"spell": g}, g)      # no parity chosen
    eff = ModalChooseOneNotYetChosen(modes=())
    state.resolving_source = None
    eff.resolve(state, 0, ())
