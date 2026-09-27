"""Spell copies on the stack (:mod:`mtg_bot.effects.generic.spell_copies`):
Chain Lightning's chain copy and Replicate (Lose Focus)."""

from __future__ import annotations

from mtg_bot.cards.parser.spell_cost_lines import parse_replicate_line
from mtg_bot.cards.parser.spell_misc_phrases import parse_chain_copy_damage
from mtg_bot.actions import push_spell_copy
from mtg_bot.effects.generic.spell_copies import DealDamageThenChainCopy

from tests._spells_a_helpers import (
    ScriptedAgent,
    cast,
    cube,
    lands,
    new_game,
    put,
    resolve,
    to_hand,
)


def test_chain_lightning_without_a_chain():
    state = new_game(ScriptedAgent(prefer=[("player", 1)]))
    lands(state, 0, "Mountain", 1)
    chain = to_hand(state, "Chain Lightning")
    cast(state, 0, chain)
    resolve(state)
    assert state.players[1].life == 17
    assert chain in state.players[0].graveyard
    assert state.stack == []


def test_chain_lightning_opponent_pays_and_copies_back():
    opp = ScriptedAgent(yes=True, prefer=[("player", 0)])
    state = new_game(ScriptedAgent(prefer=[("player", 1)]), opp)
    lands(state, 0, "Mountain", 1)
    lands(state, 1, "Mountain", 2)
    chain = to_hand(state, "Chain Lightning")
    cast(state, 0, chain)
    resolve(state)
    assert state.players[1].life == 17
    assert len(state.stack) == 1
    copy = state.stack[-1].source
    assert copy.is_spell_copy and state.stack[-1].controller_id == 1
    assert state.stack[-1].targets == (("player", 0),)
    resolve(state)  # the copy: P0 can't pay {R}{R} back
    assert state.players[0].life == 17
    assert copy not in state.players[1].graveyard
    assert copy not in state.players[0].graveyard
    assert any("ceases to exist" in line for line in state.log)


def test_chain_lightning_damaged_creatures_controller_may_decline():
    opp = ScriptedAgent(yes=False)
    state = new_game(ScriptedAgent(), opp)
    lands(state, 0, "Mountain", 1)
    lands(state, 1, "Mountain", 2)
    kavu = put(state, "Flametongue Kavu", controller=1)
    state.players[0].agent.prefer = [kavu.id]
    cast(state, 0, to_hand(state, "Chain Lightning"))
    resolve(state)
    assert kavu in state.players[1].graveyard
    assert state.stack == []
    assert opp.prompts and "{R}{R}" in opp.prompts[0]


def test_chain_copy_fizzles_on_an_illegal_target():
    state = new_game()
    eff = cube("Chain Lightning").spell_effect
    eff.resolve(state, 0, (("creature", 42),))
    assert any("fizzles" in line for line in state.log)
    eff.resolve(state, 0, ())
    assert "copy this spell" in eff.describe()


def test_chain_copy_outside_spell_resolution_just_deals_damage():
    state = new_game()
    lands(state, 1, "Mountain", 2)
    cube("Chain Lightning").spell_effect.resolve(state, 0, (("player", 1),))
    assert state.players[1].life == 17 and state.stack == []


def test_countered_spell_copy_ceases_to_exist():
    state = new_game(ScriptedAgent(prefer=[("player", 1)]))
    copy = push_spell_copy(state, cube("Lightning Bolt"), 0, (("player", 1),))
    state.stack[-1].countered = True
    resolve(state)
    assert copy not in state.players[0].graveyard
    assert state.players[1].life == 20


def test_lose_focus_replicate_copies():
    agent = ScriptedAgent(x=1)
    state = new_game(agent, ScriptedAgent(yes=False))
    lands(state, 1, "Mountain", 1)
    bolt = to_hand(state, "Lightning Bolt", owner=1)
    cast(state, 1, bolt)
    lands(state, 0, "Island", 4)
    lose_focus = to_hand(state, "Lose Focus")
    assert lose_focus.printing.replicate_cost == "{U}"
    cast(state, 0, lose_focus)
    # Original + one replicate copy, both targeting the bolt.
    assert len(state.stack) == 3
    assert state.stack[-1].source.is_spell_copy
    assert sum(
        1 for o in state.battlefield if o.tapped and o.controller_id == 0
    ) == 3
    resolve(state)
    assert state.stack[0].countered


def test_replicate_zero_times_when_unaffordable():
    state = new_game(ScriptedAgent(x=5))
    lands(state, 1, "Mountain", 1)
    cast(state, 1, to_hand(state, "Lightning Bolt", owner=1))
    lands(state, 0, "Island", 2)
    cast(state, 0, to_hand(state, "Lose Focus"))
    assert len(state.stack) == 2


def test_replicate_and_chain_grammar():
    assert parse_replicate_line(
        "Replicate {U} (When you cast this spell, copy it ...)",
    ) == "{U}"
    assert parse_replicate_line("Replicate") is None
    assert isinstance(parse_chain_copy_damage(
        "deals 3 damage to any target. Then that player or that "
        "permanent's controller may pay {R}{R}. If the player does, they "
        "may copy this spell and may choose a new target for that copy",
    ), DealDamageThenChainCopy)
    assert parse_chain_copy_damage("deals 3 damage to any target") is None
