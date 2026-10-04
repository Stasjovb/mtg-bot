"""Saddle (CR 702.171) and Caustic Bronco's saddled-or-not attack trigger."""

from __future__ import annotations

from mtg_bot.actions import ActivateAbility, apply_action, drain_stack
from mtg_bot.cards.base import make_creature
from mtg_bot.cards.parser.cube_creatures_ub import parse_ub_creature_line
from mtg_bot.combat import declare_attackers
from mtg_bot.effects.generic.cube_creatures_ub import (
    BecomeSaddled,
    RevealTopCardToHandLoseLifeEqualMV,
)
from mtg_bot.game import Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step, run_cleanup_step
from tests._spells_b_helpers import PRINTINGS, add, make_state


def _creature(state, power, owner=0):
    obj = state.new_object(make_creature(f"P{power}", "{1}", power, 1), owner, Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.battlefield.append(obj)
    return obj


def test_saddle_line():
    ability = parse_ub_creature_line("Saddle 3", "X").activated[0]
    assert ability.cost.saddle == 3 and ability.sorcery_speed
    assert ability.cost.describe() == "Saddle 3"
    assert ability.effect == BecomeSaddled()
    assert "saddled" in BecomeSaddled().describe()
    bronco = PRINTINGS["Caustic Bronco"]
    assert bronco.triggered_abilities[0].effect == RevealTopCardToHandLoseLifeEqualMV(
        unless_saddled=True,
    )


def test_saddle_needs_enough_power_and_taps_the_riders():
    state = make_state()
    bronco = add(state, 0, "Caustic Bronco", Zone.BATTLEFIELD)
    act = ActivateAbility(source_id=bronco.id, ability_index=0)
    small = _creature(state, 2)
    assert act not in legal_actions(state, 0)
    other = _creature(state, 1)
    assert act in legal_actions(state, 0)
    apply_action(state, 0, act)
    drain_stack(state)
    assert bronco.saddled and small.tapped and other.tapped
    state.step = Step.CLEANUP
    run_cleanup_step(state)
    assert not bronco.saddled


def test_bronco_attack_hurts_you_unless_saddled():
    state = make_state(step=Step.DECLARE_ATTACKERS)
    bronco = add(state, 0, "Caustic Bronco", Zone.BATTLEFIELD)
    add(state, 0, "Archon of Cruelty", Zone.LIBRARY)   # MV 8
    declare_attackers(state, [bronco.id])
    drain_stack(state)
    assert state.players[0].life == 12
    assert state.players[1].life == 20


def test_saddled_bronco_drains_opponents_instead():
    state = make_state(step=Step.DECLARE_ATTACKERS)
    bronco = add(state, 0, "Caustic Bronco", Zone.BATTLEFIELD)
    bronco.saddled = True
    add(state, 0, "Dark Confidant", Zone.LIBRARY)   # MV 2
    declare_attackers(state, [bronco.id])
    drain_stack(state)
    assert state.players[0].life == 20
    assert state.players[1].life == 18
    assert [c.printing.name for c in state.players[0].hand] == ["Dark Confidant"]
    # Source gone: BecomeSaddled does nothing.
    state.resolving_source = None
    BecomeSaddled().resolve(state, 0, ())
