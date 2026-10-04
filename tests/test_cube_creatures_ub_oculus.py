"""Abhorrent Oculus: the exile-N-cards-from-your-graveyard additional
cost and the each-opponent's-upkeep manifest dread trigger."""

from __future__ import annotations

from mtg_bot.actions import CastSpell, apply_action, drain_stack
from mtg_bot.cards.parser.cube_creatures_ub import parse_ub_creature_line
from mtg_bot.cards.parser.effects import _parse_effect
from mtg_bot.game import Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step, run_beginning_of_upkeep_triggers
from tests._spells_b_helpers import PRINTINGS, add, add_lands, make_state


def test_additional_exile_line():
    out = parse_ub_creature_line(
        "As an additional cost to cast this spell, exile six cards from your "
        "graveyard.", "X",
    )
    assert out.fields == {"additional_cost_exile_from_graveyard": 6}
    assert PRINTINGS["Abhorrent Oculus"].additional_cost_exile_from_graveyard == 6


def test_oculus_needs_six_graveyard_cards_and_exiles_them():
    state = make_state()
    add_lands(state, 0, "Island", 3)
    oculus = add(state, 0, "Abhorrent Oculus", Zone.HAND)
    for _ in range(5):
        add(state, 0, "Swamp", Zone.GRAVEYARD)
    assert CastSpell(oculus.id) not in legal_actions(state, 0)
    add(state, 0, "Island", Zone.GRAVEYARD)
    add(state, 0, "Island", Zone.GRAVEYARD)
    assert CastSpell(oculus.id) in legal_actions(state, 0)
    apply_action(state, 0, CastSpell(oculus.id))
    drain_stack(state)
    assert oculus in state.battlefield
    assert len(state.players[0].graveyard) == 1
    assert len(state.players[0].exile) == 6


def test_oculus_manifests_dread_in_each_opponents_upkeep_only():
    state = make_state(step=Step.UPKEEP)
    add(state, 0, "Abhorrent Oculus", Zone.BATTLEFIELD)
    for _ in range(3):
        add(state, 0, "Island", Zone.LIBRARY)
    run_beginning_of_upkeep_triggers(state)      # its controller's upkeep
    assert not state.stack
    state.active_player_idx = 1
    run_beginning_of_upkeep_triggers(state)
    drain_stack(state)
    face_down = [o for o in state.battlefield if o.face_down]
    assert len(face_down) == 1 and face_down[0].controller_id == 0


def test_reanimation_counter_rider_needs_engine_semantics():
    assert _parse_effect(
        "return target creature card from your graveyard to the battlefield "
        "with a finality counter on it"
    ) is None
