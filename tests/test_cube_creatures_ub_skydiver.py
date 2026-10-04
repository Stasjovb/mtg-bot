"""Thieving Skydiver: Kicker {X} with X can't be 0, the "if it was
kicked" ETB gate, and steal-an-artifact-with-MV-X-or-less (attaching an
Equipment)."""

from __future__ import annotations

from mtg_bot.actions import CastSpell, apply_action, drain_stack, put_into_battlefield
from mtg_bot.cards.parser.cube_creatures_ub import parse_ub_creature_line
from mtg_bot.effects.generic.cube_creatures_ub import (
    GainControlOfTargetThenAttachIfEquipment,
)
from mtg_bot.effects.object_predicates import ManaValueAtMostSourceX
from mtg_bot.game import Zone
from mtg_bot.legal import legal_actions
from tests._spells_b_helpers import PRINTINGS, ScriptedAgent, add, add_lands, make_state


def test_kicker_x_line_and_printing():
    fields = parse_ub_creature_line("Kicker {X}. X can't be 0.", "X").fields
    assert fields["x_min"] == 1 and fields["kicker_cost"].x_pips == 1
    sky = PRINTINGS["Thieving Skydiver"]
    assert sky.kicker_cost is not None and sky.x_min == 1
    trig = sky.triggered_abilities[0]
    assert trig.effect == GainControlOfTargetThenAttachIfEquipment()
    assert "Equipment" in trig.effect.describe()


def test_kicked_skydiver_steals_and_equips():
    agent = ScriptedAgent(x=[2])
    state = make_state(agent0=agent)
    add_lands(state, 0, "Island", 4)
    greaves = add(state, 1, "Lightning Greaves", Zone.BATTLEFIELD)   # MV 2
    ring = add(state, 1, "Sol Ring", Zone.BATTLEFIELD)
    sky = add(state, 0, "Thieving Skydiver", Zone.HAND)
    assert CastSpell(sky.id, kicked=True) in legal_actions(state, 0)
    agent.scripts["target"] = [("permanent", greaves.id)]
    apply_action(state, 0, CastSpell(sky.id, kicked=True))
    drain_stack(state)
    assert sky.kick_count == 1 and sky.entered_x_value == 2
    assert greaves.controller_id == 0 and greaves.attached_to == sky.id
    assert ring.controller_id == 1


def test_unkicked_skydiver_does_nothing_and_kicker_needs_a_spare_mana():
    state = make_state()
    add_lands(state, 0, "Island", 2)
    add(state, 1, "Sol Ring", Zone.BATTLEFIELD)
    sky = add(state, 0, "Thieving Skydiver", Zone.HAND)
    assert CastSpell(sky.id, kicked=True) not in legal_actions(state, 0)
    apply_action(state, 0, CastSpell(sky.id))
    drain_stack(state)
    assert sky.kick_count == 0
    assert all(o.controller_id == 1 for o in state.battlefield if o.printing.name == "Sol Ring")


def test_predicates_and_edges():
    state = make_state()
    ring = add(state, 1, "Sol Ring", Zone.BATTLEFIELD)
    assert not ManaValueAtMostSourceX().test(ring, state)
    sky = add(state, 0, "Thieving Skydiver", Zone.BATTLEFIELD)
    sky.entered_x_value = 1
    state.resolving_source = sky
    assert ManaValueAtMostSourceX().test(ring, state)
    eff = GainControlOfTargetThenAttachIfEquipment()
    eff.resolve(state, 0, ())
    eff.resolve(state, 0, (("permanent", ring.id),))
    assert ring.controller_id == 0 and ring.attached_to is None
