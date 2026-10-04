"""Subtlety (owner tucks a target creature/planeswalker spell on top or
bottom of their library) and Deep-Cavern Bat (exile a nonland card from
an opponent's hand until this creature leaves the battlefield)."""

from __future__ import annotations

from mtg_bot.actions import (
    CastSpell,
    StackItem,
    apply_action,
    drain_stack,
    put_into_battlefield,
    resolve_top_of_stack,
)
from mtg_bot.cards.parser.cube_creatures_ub import parse_ub_effect
from mtg_bot.effects.generic.cube_creatures_ub import (
    CounterTargetStackObject,
    LookAtHandMayExileNonlandUntilSourceLeaves,
    OwnerPutsTargetSpellOnTopOrBottom,
)
from mtg_bot.game import Zone
from mtg_bot.turn import move_off_battlefield
from tests._spells_b_helpers import PRINTINGS, ScriptedAgent, add, add_lands, make_state


def _names(zone):
    return [c.printing.name for c in zone]


# ---------------------------------------------------------------- Subtlety


def test_subtlety_parses_with_its_types_and_evoke():
    pr = PRINTINGS["Subtlety"]
    assert pr.evoke_exile_from_hand is not None   # base Evoke (pitch)
    eff = pr.triggered_abilities[0].effect
    assert eff == OwnerPutsTargetSpellOnTopOrBottom(
        card_types=("Creature", "Planeswalker"), up_to_one=True,
    )
    assert eff.target_count_range() == (0, 1)
    assert "creature spell or planeswalker spell" in eff.describe()
    assert parse_ub_effect(
        "choose target artifact spell. Its owner puts it on their choice of "
        "the top or bottom of their library"
    ) == OwnerPutsTargetSpellOnTopOrBottom(card_types=("Artifact",))


def _cast_creature(state, pid, name, lands):
    add_lands(state, pid, "Island", lands)
    card = add(state, pid, name, Zone.HAND)
    apply_action(state, pid, CastSpell(card.id))
    return card


def test_subtlety_puts_creature_spell_on_top_by_owner_choice():
    state = make_state()
    add(state, 1, "Swamp", Zone.LIBRARY)
    snap = _cast_creature(state, 1, "Snapcaster Mage", 2)
    eff = OwnerPutsTargetSpellOnTopOrBottom(card_types=("Creature",))
    assert eff.legal_targets(state, 0) == [("stack", 0)]
    eff.resolve(state, 0, (("stack", 0),))
    assert state.stack == []
    assert state.players[1].library[0] is snap and snap.zone == Zone.LIBRARY


def test_subtlety_owner_may_choose_bottom():
    state = make_state(agent1=ScriptedAgent(yes_no=[False]))
    add(state, 1, "Swamp", Zone.LIBRARY)
    snap = _cast_creature(state, 1, "Snapcaster Mage", 2)
    OwnerPutsTargetSpellOnTopOrBottom().resolve(state, 0, (("stack", 0),))
    assert state.players[1].library[-1] is snap
    assert _names(state.players[1].library) == ["Swamp", "Snapcaster Mage"]


def test_subtlety_ignores_noncreature_spells_and_missing_targets():
    state = make_state()
    eff = OwnerPutsTargetSpellOnTopOrBottom()
    eff.resolve(state, 0, ())
    eff.resolve(state, 0, (("stack", 3),))
    add_lands(state, 1, "Mountain", 1)
    bolt = add(state, 1, "Lightning Bolt", Zone.HAND)
    apply_action(state, 1, CastSpell(bolt.id))
    assert eff.legal_targets(state, 0) == []
    eff.resolve(state, 0, (("stack", 0),))
    assert state.stack[0].source is bolt


def test_subtlety_reindexes_stack_targets_above_the_spell():
    state = make_state()
    snap = _cast_creature(state, 1, "Snapcaster Mage", 2)
    add_lands(state, 1, "Mountain", 1)
    bolt = add(state, 1, "Lightning Bolt", Zone.HAND)
    apply_action(state, 1, CastSpell(bolt.id))
    # A pending counter ability above both, aimed at the bolt (index 1).
    frog = add(state, 0, "Snapcaster Mage", Zone.BATTLEFIELD)
    from mtg_bot.effects.base import TriggeredAbility

    ability = TriggeredAbility(trigger="etb", effect=CounterTargetStackObject())
    state.stack.append(StackItem(
        source=frog, controller_id=0, ability=ability, targets=(("stack", 1),),
    ))
    OwnerPutsTargetSpellOnTopOrBottom().resolve(state, 0, (("stack", 0),))
    assert snap in state.players[1].library
    assert state.stack[-1].targets == (("stack", 0),)
    resolve_top_of_stack(state)
    assert state.stack[0].countered


def test_subtlety_copy_of_a_spell_ceases_to_exist():
    state = make_state()
    snap = _cast_creature(state, 1, "Snapcaster Mage", 2)
    snap.is_spell_copy = True
    OwnerPutsTargetSpellOnTopOrBottom().resolve(state, 0, (("stack", 0),))
    assert state.stack == [] and snap not in state.players[1].library


def test_subtlety_enters_and_tucks_via_its_trigger():
    state = make_state()
    snap = _cast_creature(state, 1, "Snapcaster Mage", 2)
    state.players[0].agent.scripts["target"] = [("stack", 0)]
    sub = state.new_object(PRINTINGS["Subtlety"], 0, Zone.HAND)
    put_into_battlefield(state, sub, 0)
    resolve_top_of_stack(state)
    assert state.players[1].library[0] is snap


# ---------------------------------------------------------------- Deep-Cavern Bat


def test_bat_parses_to_the_hand_exile_link():
    eff = PRINTINGS["Deep-Cavern Bat"].triggered_abilities[0].effect
    assert eff == LookAtHandMayExileNonlandUntilSourceLeaves()
    assert "until this creature leaves" in eff.describe()


def _bat_state(**kw):
    state = make_state(**kw)
    bolt = add(state, 1, "Lightning Bolt", Zone.HAND)
    add(state, 1, "Mountain", Zone.HAND)
    return state, bolt


def test_bat_exiles_then_returns_card_to_hand_when_it_leaves():
    state, bolt = _bat_state()
    bat = state.new_object(PRINTINGS["Deep-Cavern Bat"], 0, Zone.HAND)
    state.players[0].agent.scripts["target"] = [("player", 1)]
    put_into_battlefield(state, bat, 0)
    drain_stack(state)
    assert bolt in state.players[1].exile and bolt.exiled_by_source == bat.id
    assert _names(state.players[1].hand) == ["Mountain"]
    move_off_battlefield(state, bat, "graveyard")
    assert bolt in state.players[1].hand and bolt.zone == Zone.HAND
    assert bolt not in state.players[1].exile
    assert not bolt.exiled_until_leaves_from_hand and bolt.exiled_by_source is None


def test_bat_may_decline_and_needs_a_nonland_card():
    state, bolt = _bat_state(agent0=ScriptedAgent(yes_no=[False]))
    bat = add(state, 0, "Deep-Cavern Bat", Zone.BATTLEFIELD)
    state.resolving_source = bat
    eff = LookAtHandMayExileNonlandUntilSourceLeaves()
    assert eff.legal_targets(state, 0) == [("player", 1)]
    eff.resolve(state, 0, (("player", 1),))
    assert bolt in state.players[1].hand
    eff.resolve(state, 0, ())
    state.players[1].hand.remove(bolt)
    eff.resolve(state, 0, (("player", 1),))
    assert state.players[1].exile == []


def test_bat_exiles_nothing_if_it_already_left():
    state, bolt = _bat_state()
    bat = add(state, 0, "Deep-Cavern Bat", Zone.GRAVEYARD)
    state.resolving_source = bat
    LookAtHandMayExileNonlandUntilSourceLeaves().resolve(
        state, 0, (("player", 1),),
    )
    assert bolt in state.players[1].hand and state.players[1].exile == []
