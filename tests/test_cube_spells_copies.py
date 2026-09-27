"""Cube spells-B: spell copies on the stack — Storm (Brain Freeze) and
Chain of Smog's "That player may copy this spell"."""

from __future__ import annotations

import pytest

from mtg_bot.actions import (
    CastSpell,
    apply_action,
    move_spell_off_stack,
    push_spell_copy,
    resolve_top_of_stack,
)
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.effects.generic.card_flow import TargetPlayerDiscards
from mtg_bot.effects.generic.spell_copies import (
    StormCopySpell,
    TargetPlayerMayCopyThisSpell,
    _choose_copy_targets,
)
from mtg_bot.game import StackItem, Zone
from tests._spells_b_helpers import (
    PRINTINGS,
    ScriptedAgent,
    add,
    add_lands,
    make_state,
)


@pytest.fixture(scope="module")
def cube():
    return OracleParserCardSource(pool="cube").get_printings()


def _drain(state):
    while state.stack:
        resolve_top_of_stack(state)


def test_brain_freeze_storm_copies(cube):
    assert cube["Brain Freeze"].has_storm
    state = make_state(agent0=ScriptedAgent(target=[("player", 1)] * 5))
    for _ in range(20):
        add(state, 1, "Island", Zone.LIBRARY)
    # Two spells already cast this turn (one by each player).
    state.players[0].spells_cast_this_turn = 1
    state.players[1].spells_cast_this_turn = 1
    freeze = add(state, 0, "Brain Freeze", Zone.HAND)
    add_lands(state, 0, "Island", 2)
    apply_action(state, 0, CastSpell(freeze.id))
    # Spell + storm trigger on the stack.
    assert len(state.stack) == 2
    resolve_top_of_stack(state)  # storm trigger -> two copies
    copies = [i for i in state.stack if i.source.is_spell_copy]
    assert len(copies) == 2
    _drain(state)
    assert len(state.players[1].graveyard) == 9
    assert freeze in state.players[0].graveyard
    # Copies weren't cast.
    assert state.players[0].spells_cast_this_turn == 2


def test_storm_with_no_prior_spells_makes_no_copies():
    state = make_state()
    for _ in range(5):
        add(state, 1, "Island", Zone.LIBRARY)
    freeze = add(state, 0, "Brain Freeze", Zone.HAND)
    add_lands(state, 0, "Island", 2)
    state.players[0].agent.scripts["target"] = [("player", 1)]
    apply_action(state, 0, CastSpell(freeze.id))
    _drain(state)
    assert len(state.players[1].graveyard) == 3


def test_storm_copy_uses_last_known_printing_when_spell_gone():
    state = make_state(agent0=ScriptedAgent(target=[("player", 1)]))
    for _ in range(5):
        add(state, 1, "Island", Zone.LIBRARY)
    StormCopySpell(
        spell_id=999, count=1, printing=PRINTINGS["Brain Freeze"],
    ).resolve(state, 0)
    assert len(state.stack) == 1 and state.stack[0].source.is_spell_copy
    StormCopySpell(spell_id=999, count=1, printing=None).resolve(state, 0)
    assert len(state.stack) == 1
    assert "copy this spell" in StormCopySpell(count=2).describe()


def test_countered_copy_ceases_to_exist():
    state = make_state()
    copy = push_spell_copy(state, PRINTINGS["Dark Ritual"], 0)
    state.stack[-1].countered = True
    resolve_top_of_stack(state)
    assert copy not in state.players[0].graveyard
    move_spell_off_stack(state, copy, destination="hand")
    assert copy not in state.players[0].hand


def test_choose_copy_targets_fallbacks():
    state = make_state()
    state.players[0].agent = None
    no_target = PRINTINGS["Dark Ritual"]
    assert _choose_copy_targets(state, 0, no_target, ()) == ()
    freeze = PRINTINGS["Brain Freeze"]
    assert _choose_copy_targets(state, 0, freeze, (("player", 1),)) == (("player", 1),)
    assert _choose_copy_targets(state, 0, freeze, ()) == (("player", 0),)
    state.players[0].agent = ScriptedAgent(target=[None])
    assert _choose_copy_targets(state, 0, freeze, ()) == (("player", 0),)


def test_chain_of_smog_chain_until_hands_empty(cube):
    assert cube["Chain of Smog"].spell_effect.effects == (
        TargetPlayerDiscards(amount=2), TargetPlayerMayCopyThisSpell(),
    )
    # P1 copies back at P0 once, then P0 declines.
    a0 = ScriptedAgent(target=[("player", 1)], yes_no=[False])
    a1 = ScriptedAgent(target=[("player", 0)], yes_no=[True])
    state = make_state(agent0=a0, agent1=a1)
    for _ in range(3):
        add(state, 0, "Island", Zone.HAND)
        add(state, 1, "Swamp", Zone.HAND)
    smog = add(state, 0, "Chain of Smog", Zone.HAND)
    add_lands(state, 0, "Swamp", 2)
    apply_action(state, 0, CastSpell(smog.id))
    _drain(state)
    assert len(state.players[1].hand) == 1
    assert len(state.players[0].hand) == 1
    assert smog in state.players[0].graveyard


def test_chain_of_smog_not_offered_against_empty_hands():
    state = make_state()  # default agents accept every copy offer
    smog = add(state, 0, "Chain of Smog", Zone.HAND)
    add_lands(state, 0, "Swamp", 2)
    state.players[0].agent.scripts["target"] = [("player", 1)]
    apply_action(state, 0, CastSpell(smog.id))
    _drain(state)  # terminates: nobody has cards
    assert state.stack == []


def test_may_copy_edge_cases():
    state = make_state()
    eff = TargetPlayerMayCopyThisSpell()
    eff.resolve(state, 0, (("player", 1),))  # no resolving spell
    state.resolving_spell = add(state, 0, "Chain of Smog", Zone.STACK)
    eff.resolve(state, 0, ())
    state.players[1].has_lost = True
    eff.resolve(state, 0, (("player", 1),))
    state.players[1].has_lost = False
    add(state, 1, "Island", Zone.HAND)
    state.players[1].agent = None
    eff.resolve(state, 0, (("player", 1),))
    assert state.stack == []
    assert "copy this spell" in eff.describe()


def test_target_player_discards_self_choice():
    state = make_state(agent1=ScriptedAgent())
    a = add(state, 1, "Island", Zone.HAND)
    b = add(state, 1, "Swamp", Zone.HAND)
    state.players[1].agent.scripts["discard"] = [b.id]
    eff = TargetPlayerDiscards(amount=1)
    assert eff.requires_target()
    assert eff.legal_targets(state, 0) == [("player", 0), ("player", 1)]
    eff.resolve(state, 0, (("player", 1),))
    assert state.players[1].hand == [a]
    state.players[1].agent = None
    TargetPlayerDiscards(amount=3).resolve(state, 0, (("player", 1),))
    assert state.players[1].hand == []
    eff.resolve(state, 0, ())
    assert "discards 1" in eff.describe()
