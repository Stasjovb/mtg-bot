"""Emerge (CR 702.119) and Crabomination's exile-three-cast-one ETB."""

from __future__ import annotations

from mtg_bot.actions import CastSpell, apply_action, drain_stack, put_into_battlefield
from mtg_bot.cards.parser.cube_creatures_ub import parse_ub_creature_line
from mtg_bot.creature_casting_ub import emerge_cast_actions
from mtg_bot.effects.generic.cube_creatures_ub import (
    TargetOpponentExilesThreeMayCastOneFree,
)
from mtg_bot.game import Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step
from tests._spells_b_helpers import PRINTINGS, ScriptedAgent, add, add_lands, make_state


def _names(zone):
    return [c.printing.name for c in zone]


def test_emerge_lines():
    art = parse_ub_creature_line("Emerge from artifact {5}{B}{B}", "X").fields
    assert art["emerge_sacrifice_type"] == "Artifact"
    assert art["emerge_cost_str"] == "{5}{B}{B}"
    plain = parse_ub_creature_line("Emerge {4}{U}", "X").fields
    assert plain["emerge_sacrifice_type"] == "Creature"
    assert parse_ub_creature_line("Emerge {Q}", "X") is None
    crab = PRINTINGS["Crabomination"]
    assert crab.emerge_cost is not None and crab.emerge_sacrifice_type == "Artifact"


def test_emerge_sacrifices_an_artifact_to_cut_the_cost():
    state = make_state()
    add_lands(state, 0, "Swamp", 4)
    rock = add(state, 0, "Mind Stone", Zone.BATTLEFIELD)       # MV 2
    crab = add(state, 0, "Crabomination", Zone.HAND)
    # {5}{B}{B} - 2 = {3}{B}{B}: five mana needed, four available.
    assert CastSpell(crab.id, use_emerge=True) not in legal_actions(state, 0)
    add(state, 0, "Swamp", Zone.BATTLEFIELD)
    assert CastSpell(crab.id, use_emerge=True) in legal_actions(state, 0)
    apply_action(state, 0, CastSpell(crab.id, use_emerge=True))
    assert rock not in state.battlefield
    drain_stack(state)
    assert crab in state.battlefield


def test_emerge_needs_sorcery_timing_and_a_sacrifice():
    state = make_state(step=Step.DECLARE_ATTACKERS)
    add_lands(state, 0, "Swamp", 7)
    add(state, 0, "Mind Stone", Zone.BATTLEFIELD)
    add(state, 0, "Crabomination", Zone.HAND)
    assert emerge_cast_actions(state, 0) == []
    state2 = make_state()
    add_lands(state2, 0, "Swamp", 7)
    add(state2, 0, "Crabomination", Zone.HAND)
    add(state2, 0, "Crabomination", Zone.HAND)
    assert emerge_cast_actions(state2, 0) == []   # nothing to sacrifice


def test_crabomination_exiles_three_and_casts_one_free():
    agent = ScriptedAgent()
    state = make_state(agent0=agent)
    add(state, 1, "Lightning Bolt", Zone.LIBRARY)
    add(state, 1, "Island", Zone.GRAVEYARD)
    add(state, 1, "Dark Confidant", Zone.HAND)
    agent.scripts["target"] = [("player", 1), ("player", 1)]
    crab = state.new_object(PRINTINGS["Crabomination"], 0, Zone.HAND)
    put_into_battlefield(state, crab, 0)
    drain_stack(state)
    p1 = state.players[1]
    assert p1.library == [] and p1.hand == []
    assert _names(p1.graveyard) == ["Lightning Bolt"]
    assert sorted(_names(p1.exile)) == ["Dark Confidant", "Island"]
    # The bolt (first castable option) was cast for free at P1.
    assert p1.life == 17
    assert "exiles the top card" in TargetOpponentExilesThreeMayCastOneFree().describe()


def test_crabomination_with_empty_zones_or_declining():
    eff = TargetOpponentExilesThreeMayCastOneFree()
    state = make_state(agent0=ScriptedAgent(library=[None]))
    eff.resolve(state, 0, ())
    eff.resolve(state, 0, (("player", 1),))   # nothing to exile
    add(state, 1, "Island", Zone.LIBRARY)
    eff.resolve(state, 0, (("player", 1),))   # a land: nothing castable
    add(state, 1, "Dark Confidant", Zone.HAND)
    eff.resolve(state, 0, (("player", 1),))   # declined
    assert _names(state.players[1].exile) == ["Island", "Dark Confidant"]
