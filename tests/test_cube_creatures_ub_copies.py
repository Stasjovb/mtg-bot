"""Clones with "except" riders (Phyrexian Metamorph, Superior
Spider-Man) and Forensic Gadgeteer's artifact-ability cost reduction."""

from __future__ import annotations

from mtg_bot.actions import (
    ActivateAbility,
    CastSpell,
    _effective_ability_mana_cost,
    apply_action,
    drain_stack,
)
from mtg_bot.cards.parser.cube_creatures_ub import parse_ub_creature_line
from mtg_bot.effects.generic.cube_creatures_ub import ExileGraveyardCardById
from mtg_bot.game import Zone, effective_power
from mtg_bot.legal import legal_actions
from tests._spells_b_helpers import PRINTINGS, ScriptedAgent, add, add_lands, make_state


def _names(zone):
    return [c.printing.name for c in zone]


# ---------------------------------------------------------------- grammar


def test_enter_as_copy_lines():
    meta = parse_ub_creature_line(
        "You may have this creature enter as a copy of any artifact or "
        "creature on the battlefield, except it's an artifact in addition to "
        "its other types.", "X",
    ).fields
    assert meta["enters_as_copy_types"] == ("Artifact", "Creature")
    assert meta["enters_as_copy_add_type"] == "Artifact"
    spidey = parse_ub_creature_line(
        "Mind Swap — You may have this creature enter as a copy of any "
        "creature card in a graveyard, except his name is this creature and "
        "he's a 4/4 Spider Human Hero in addition to his other types. When "
        "you do, exile that card.", "X",
    ).fields
    assert spidey["enters_as_copy_zone"] == "graveyard"
    assert spidey["enters_as_copy_base_pt"] == (4, 4)
    assert spidey["enters_as_copy_add_subtypes"] == ("Spider", "Human", "Hero")
    assert spidey["enters_as_copy_exiles_card"]
    for bad in (
        "You may have this creature enter as a copy of any frob on the battlefield.",
        "You may have this creature enter as a copy of any creature on the "
        "battlefield, except it flies.",
        "You may have this creature enter as a copy of any creature on the "
        "battlefield. When you do, exile that card.",
    ):
        assert parse_ub_creature_line(bad, "X") is None


# ---------------------------------------------------------------- Metamorph


def test_metamorph_copies_an_artifact_creature_as_an_artifact():
    state = make_state()
    add_lands(state, 0, "Island", 4)
    bob = add(state, 1, "Dark Confidant", Zone.BATTLEFIELD)
    meta = add(state, 0, "Phyrexian Metamorph", Zone.HAND)
    state.players[0].agent.scripts["target"] = [("permanent", bob.id)]
    state.players[0].agent.scripts["yes_no"] = [False]   # pay {U}, not life
    apply_action(state, 0, CastSpell(meta.id))
    drain_stack(state)
    assert meta in state.battlefield
    assert meta.printing.name == "Dark Confidant"
    assert "Artifact" in meta.printing.card_types
    assert meta.original_printing.name == "Phyrexian Metamorph"


def test_metamorph_may_decline_to_copy():
    state = make_state(agent0=ScriptedAgent(target=[None]))
    add_lands(state, 0, "Island", 4)
    add(state, 1, "Sol Ring", Zone.BATTLEFIELD)
    meta = add(state, 0, "Phyrexian Metamorph", Zone.HAND)
    apply_action(state, 0, CastSpell(meta.id))
    drain_stack(state)
    # A declined copy leaves the 0/0 to die to state-based actions.
    assert meta not in state.battlefield


# ---------------------------------------------------------------- Spider-Man


def test_superior_spider_man_copies_a_graveyard_card_and_exiles_it():
    state = make_state()
    add_lands(state, 0, "Island", 2)
    add_lands(state, 0, "Swamp", 2)
    dead = add(state, 1, "Archon of Cruelty", Zone.GRAVEYARD)
    spidey = add(state, 0, "Superior Spider-Man", Zone.HAND)
    agent = state.players[0].agent
    agent.scripts["target"] = [("graveyard_card", dead.id), ("player", 1)]
    apply_action(state, 0, CastSpell(spidey.id))
    drain_stack(state)
    assert spidey in state.battlefield
    assert spidey.printing.name == "Superior Spider-Man"
    assert effective_power(state, spidey) == 4
    assert {"Spider", "Human", "Hero"} <= set(spidey.printing.subtypes)
    assert "flying" in spidey.printing.keywords          # Archon's text
    assert dead in state.players[1].exile                  # "exile that card"
    assert state.players[1].life == 17                     # Archon's ETB


def test_exile_graveyard_card_by_id_is_a_noop_when_gone():
    state = make_state()
    ExileGraveyardCardById().resolve(state, 0, ())
    ExileGraveyardCardById().resolve(state, 0, (("graveyard_card", 99),))
    assert ExileGraveyardCardById().describe() == "exile that card"


# ---------------------------------------------------------------- Gadgeteer


def test_gadgeteer_reduces_artifact_abilities_but_not_below_one():
    printing = PRINTINGS["Forensic Gadgeteer"]
    assert printing.artifact_ability_cost_reduction == 1
    state = make_state()
    spellbomb = add(state, 0, "Aether Spellbomb", Zone.BATTLEFIELD)   # {1}, {U}
    draw_ab, bounce_ab = spellbomb.printing.activated_abilities[1], spellbomb.printing.activated_abilities[0]
    before = [_effective_ability_mana_cost(state, spellbomb, a) for a in (draw_ab, bounce_ab)]
    add(state, 0, "Forensic Gadgeteer", Zone.BATTLEFIELD)
    after = [_effective_ability_mana_cost(state, spellbomb, a) for a in (draw_ab, bounce_ab)]
    # {1} stays {1} (one mana minimum); {U} has no generic to reduce.
    assert [c.total for c in after] == [c.total for c in before]
    kappa_like = add(state, 0, "Mind Stone", Zone.BATTLEFIELD)
    draw = kappa_like.printing.activated_abilities[1]           # {1}, {T}, sac
    assert _effective_ability_mana_cost(state, kappa_like, draw).total == 1
    # An opponent's Gadgeteer doesn't help.
    other = make_state()
    stone = add(other, 0, "Mind Stone", Zone.BATTLEFIELD)
    add(other, 1, "Forensic Gadgeteer", Zone.BATTLEFIELD)
    assert _effective_ability_mana_cost(other, stone, draw).total == 1


def test_gadgeteer_makes_a_two_mana_ability_cost_one():
    state = make_state()
    add(state, 0, "Forensic Gadgeteer", Zone.BATTLEFIELD)
    clue_maker = add(state, 0, "Thraben Inspector", Zone.HAND)
    add_lands(state, 0, "Plains", 1)
    apply_action(state, 0, CastSpell(clue_maker.id))
    drain_stack(state)
    clue = next(o for o in state.battlefield if o.printing.name == "Clue")
    ability = clue.printing.activated_abilities[0]                 # {2}, sac
    assert _effective_ability_mana_cost(state, clue, ability).total == 1
    add(state, 0, "Island", Zone.LIBRARY)
    add_lands(state, 0, "Island", 1)
    act = ActivateAbility(source_id=clue.id, ability_index=0)
    assert act in legal_actions(state, 0)
