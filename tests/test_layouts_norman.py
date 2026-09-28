"""Cube layouts bucket: Norman Osborn // Green Goblin (a modal DFC whose
front face transforms): can't be blocked, connive, graveyard-spell cost
reduction and granted mayhem."""

from __future__ import annotations

from mtg_bot.actions import CastSpell, apply_action, drain_stack
from mtg_bot.cards.parser.layout_face_grammar import parse_face_creature_line
from mtg_bot.effects.conditions import SpellCastFromGraveyard
from mtg_bot.effects.generic.layout_face_effects import SourceConnives
from mtg_bot.game import Zone, is_cant_be_blocked
from mtg_bot.layouts import mayhem_castable, transform_permanent
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step, run_cleanup_step
from tests._spells_b_helpers import ScriptedAgent, add, add_lands, make_state, printing

NORMAN = "Norman Osborn // Green Goblin"


def test_norman_shape():
    p = printing(NORMAN)
    back = p.mdfc_back_face
    assert back is p.transform_back_face and back.name == "Green Goblin"
    assert back.grants_mayhem_to_graveyard
    (red,) = back.external_cost_reductions
    assert red.condition == SpellCastFromGraveyard() and red.amount == 2
    assert p.triggered_abilities[0].effect == SourceConnives()


def test_norman_unblockable_and_connives():
    from mtg_bot.combat import resolve_combat_damage

    agent = ScriptedAgent()
    state = make_state(agent0=agent)
    norman = add(state, 0, NORMAN, Zone.BATTLEFIELD)
    assert is_cant_be_blocked(state, norman)
    add(state, 0, "Island", Zone.LIBRARY)
    bolt = add(state, 0, "Lightning Bolt", Zone.HAND)
    agent.scripts["discard"] = [bolt.id]
    norman.attacking = True
    state.step = Step.COMBAT_DAMAGE
    resolve_combat_damage(state, 1)
    drain_stack(state)
    assert bolt in state.players[0].graveyard and norman.plus_one_counters == 1
    assert "connives" in SourceConnives().describe()


def test_connive_with_land_and_no_source():
    agent = ScriptedAgent()
    state = make_state(agent0=agent)
    add(state, 0, "Island", Zone.LIBRARY)
    SourceConnives().resolve(state, 0)
    assert len(state.players[0].graveyard) == 1


def test_green_goblin_mayhem_and_cost_reduction():
    agent = ScriptedAgent()
    state = make_state(agent0=agent)
    norman = add(state, 0, NORMAN, Zone.BATTLEFIELD)
    transform_permanent(state, norman)
    assert norman.printing.name == "Green Goblin"
    # A card discarded this turn is castable for its mana cost, minus {2}
    # for being cast from the graveyard.
    from mtg_bot.effects.generic.card_flow import discard_card

    ring = add(state, 0, "Sol Ring", Zone.HAND)
    discard_card(state, state.players[0], ring)
    assert mayhem_castable(state, 0, ring)
    assert CastSpell(ring.id) in legal_actions(state, 0)  # {1} - {2} = free
    apply_action(state, 0, CastSpell(ring.id))
    drain_stack(state)
    assert ring in state.battlefield
    # Not discarded this turn: no mayhem.
    old = add(state, 0, "Mox Pearl", Zone.GRAVEYARD)
    assert not mayhem_castable(state, 0, old)
    # Lands never have mayhem; mayhem ends with the turn.
    land = add(state, 0, "Island", Zone.HAND)
    discard_card(state, state.players[0], land)
    assert not mayhem_castable(state, 0, land)
    pearl = add(state, 0, "Mox Pearl", Zone.HAND)
    discard_card(state, state.players[0], pearl)
    state.turn_number += 1
    assert not mayhem_castable(state, 0, pearl)


def test_no_mayhem_without_green_goblin():
    state = make_state()
    add(state, 0, NORMAN, Zone.BATTLEFIELD)  # front face: no grant
    from mtg_bot.effects.generic.card_flow import discard_card

    ring = add(state, 0, "Sol Ring", Zone.HAND)
    discard_card(state, state.players[0], ring)
    assert not mayhem_castable(state, 0, ring)
    run_cleanup_step(state)
    assert ring.discarded_turn == state.turn_number


def test_cast_green_goblin_directly():
    state = make_state()
    card = add(state, 0, NORMAN, Zone.HAND)
    add_lands(state, 0, "Island", 2)
    add_lands(state, 0, "Swamp", 1)
    add_lands(state, 0, "Mountain", 1)
    assert CastSpell(card.id, cast_face="Green Goblin") in legal_actions(state, 0)


def test_face_creature_line_rejects_other_text():
    assert parse_face_creature_line("Frobnicate.", {"name": "X"}) is None
