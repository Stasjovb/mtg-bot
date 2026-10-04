"""Wan Shi Tong, All-Knowing: the owner's second-from-top-or-bottom tuck,
the "cards put into a library from anywhere" trigger, and the Spirit
tokens' block restriction."""

from __future__ import annotations

from mtg_bot.actions import CastSpell, apply_action, drain_stack, put_into_battlefield
from mtg_bot.cards.base import make_creature
from mtg_bot.combat import can_block
from mtg_bot.effects.generic.cube_creatures_ub import (
    OwnerPutsTargetSecondFromTopOrBottom,
)
from mtg_bot.effects.generic.cube_walkers import PutCardsFromHandOnTopOfLibrary
from mtg_bot.effects.predicates import Event
from mtg_bot.game import Zone
from mtg_bot.turn import note_cards_put_into_library
from tests._spells_b_helpers import PRINTINGS, ScriptedAgent, add, add_lands, make_state


def _spirits(state):
    return [o for o in state.battlefield if o.printing.name == "Spirit"]


def test_printing_shapes():
    wst = PRINTINGS["Wan Shi Tong, All-Knowing"]
    events = [t.event for t in wst.triggered_abilities]
    assert Event.CARDS_PUT_INTO_LIBRARY in events
    token = wst.triggered_abilities[1].effect.token_printing
    assert token.blocks_only_with_subtype == "Spirit"
    assert "second from the top" in OwnerPutsTargetSecondFromTopOrBottom().describe()


def test_etb_tucks_second_from_top_and_makes_spirits():
    agent1 = ScriptedAgent(yes_no=[True])
    state = make_state(agent1=agent1)
    for name in ("Island", "Swamp", "Forest"):
        add(state, 1, name, Zone.LIBRARY)
    victim = add(state, 1, "Dark Confidant", Zone.BATTLEFIELD)
    state.players[0].agent.scripts["target"] = [("creature", victim.id)]
    wst = state.new_object(PRINTINGS["Wan Shi Tong, All-Knowing"], 0, Zone.HAND)
    put_into_battlefield(state, wst, 0)
    drain_stack(state)
    assert state.players[1].library[1] is victim
    assert len(_spirits(state)) == 2


def test_owner_may_choose_the_bottom():
    agent1 = ScriptedAgent(yes_no=[False])
    state = make_state(agent1=agent1)
    for name in ("Island", "Swamp"):
        add(state, 1, name, Zone.LIBRARY)
    victim = add(state, 1, "Sol Ring", Zone.BATTLEFIELD)
    OwnerPutsTargetSecondFromTopOrBottom().resolve(state, 0, (("permanent", victim.id),))
    assert state.players[1].library[-1] is victim
    OwnerPutsTargetSecondFromTopOrBottom().resolve(state, 0, ())
    OwnerPutsTargetSecondFromTopOrBottom().resolve(state, 0, (("permanent", 999),))


def test_brainstorm_put_back_triggers_once():
    state = make_state()
    add(state, 0, "Wan Shi Tong, All-Knowing", Zone.BATTLEFIELD)
    for name in ("Island", "Swamp", "Forest", "Mountain"):
        add(state, 1, name, Zone.HAND)
    PutCardsFromHandOnTopOfLibrary(amount=2).resolve(state, 1, ())
    drain_stack(state)
    assert len(_spirits(state)) == 2


def test_no_observer_is_a_noop_and_explicit_player_default():
    state = make_state()
    note_cards_put_into_library(state, 0)
    add(state, 0, "Wan Shi Tong, All-Knowing", Zone.BATTLEFIELD)
    note_cards_put_into_library(state)
    drain_stack(state)
    assert len(_spirits(state)) == 2


def test_spirit_block_restriction():
    state = make_state()
    add(state, 0, "Wan Shi Tong, All-Knowing", Zone.BATTLEFIELD)
    note_cards_put_into_library(state, 0)
    drain_stack(state)
    spirit_a, spirit_b = _spirits(state)
    bear = state.new_object(make_creature("Bear", "{1}{G}", 2, 2), 1, Zone.BATTLEFIELD)
    state.battlefield.append(bear)
    other_spirit = state.new_object(
        make_creature("Ghost", "{1}{W}", 1, 1, subtypes=("Spirit",)), 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(other_spirit)
    assert not can_block(state, spirit_a, bear)
    assert not can_block(state, bear, spirit_a)
    assert can_block(state, other_spirit, spirit_a)
    assert can_block(state, spirit_b, other_spirit)
