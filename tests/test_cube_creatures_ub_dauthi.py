"""Dauthi Voidwalker: the opponent-graveyard exile-with-void-counter
replacement (battlefield deaths, spells leaving the stack, the SBA
catch-all for discards / mills) and the sacrifice ability that lets
you play a void-countered card for free."""

from __future__ import annotations

from mtg_bot.actions import (
    ActivateAbility,
    CastSpell,
    apply_action,
    drain_stack,
    put_into_battlefield,
)
from mtg_bot.cards.parser.cube_creatures_ub import parse_ub_creature_line, parse_ub_effect
from mtg_bot.effects.generic.card_flow import discard_card
from mtg_bot.effects.generic.cube_creatures_ub import (
    ChooseOpponentsExiledCardWithCounterMayPlayFree,
)
from mtg_bot.game import Zone, named_counter_count, void_exile_replacement_active
from mtg_bot.legal import legal_actions
from mtg_bot.turn import move_off_battlefield, state_based_actions
from tests._spells_b_helpers import PRINTINGS, ScriptedAgent, add, add_lands, make_state


def _names(zone):
    return [c.printing.name for c in zone]


def _with_dauthi(state, controller=0):
    dauthi = state.new_object(PRINTINGS["Dauthi Voidwalker"], controller, Zone.HAND)
    put_into_battlefield(state, dauthi, controller)
    drain_stack(state)
    return dauthi


def test_void_lines_parse():
    assert parse_ub_creature_line(
        "If a card would be put into an opponent's graveyard from anywhere, "
        "instead exile it with a void counter on it.", "X",
    ).fields == {"void_exile_replacement": True}
    eff = parse_ub_effect(
        "choose an exiled card an opponent owns with a void counter on it. "
        "You may play it this turn without paying its mana cost"
    )
    assert eff == ChooseOpponentsExiledCardWithCounterMayPlayFree(counter="void")
    assert "void counter" in eff.describe()
    printing = PRINTINGS["Dauthi Voidwalker"]
    assert printing.void_exile_replacement and "shadow" in printing.keywords


def test_opponents_creatures_are_exiled_instead_of_dying():
    state = make_state()
    _with_dauthi(state)
    victim = add(state, 1, "Dark Confidant", Zone.BATTLEFIELD)
    mine = add(state, 0, "Psychic Frog", Zone.BATTLEFIELD)
    move_off_battlefield(state, victim, "graveyard")
    move_off_battlefield(state, mine, "graveyard")
    assert state.players[1].graveyard == []
    assert victim in state.players[1].exile
    assert named_counter_count(victim, "void") == 1
    assert _names(state.players[0].graveyard) == ["Psychic Frog"]


def test_opponents_spells_and_discards_are_exiled():
    state = make_state()
    _with_dauthi(state)
    add_lands(state, 1, "Mountain", 1)
    bolt = add(state, 1, "Lightning Bolt", Zone.HAND)
    state.players[1].agent.scripts["target"] = [("player", 0)]
    apply_action(state, 1, CastSpell(bolt.id))
    drain_stack(state)
    assert bolt in state.players[1].exile
    card = add(state, 1, "Island", Zone.HAND)
    discard_card(state, state.players[1], card)
    assert card in state.players[1].graveyard     # until SBAs
    state_based_actions(state)
    assert card in state.players[1].exile
    assert named_counter_count(card, "void") == 1


def test_cards_already_in_the_graveyard_stay():
    state = make_state()
    old = add(state, 1, "Island", Zone.GRAVEYARD)
    _with_dauthi(state)
    state_based_actions(state)
    assert old in state.players[1].graveyard


def test_replacement_needs_the_source_to_keep_its_abilities():
    state = make_state()
    dauthi = _with_dauthi(state)
    assert void_exile_replacement_active(state, 1)
    assert not void_exile_replacement_active(state, 0)
    state.add_continuous_effect(
        source_id=dauthi.id, layer=6, kind="lose_all_abilities",
        target_id=dauthi.id,
    )
    assert not void_exile_replacement_active(state, 1)


def test_sacrifice_lets_you_play_a_void_card_for_free():
    state = make_state()
    dauthi = _with_dauthi(state)
    dauthi.summoning_sick = False
    victim = add(state, 1, "Dark Confidant", Zone.BATTLEFIELD)
    move_off_battlefield(state, victim, "graveyard")
    act = ActivateAbility(source_id=dauthi.id, ability_index=0)
    assert act in legal_actions(state, 0)
    apply_action(state, 0, act)
    drain_stack(state)
    assert dauthi not in state.battlefield
    assert victim.may_play_by == 0 and victim.may_play_free
    assert CastSpell(victim.id, cast_for_free=True) in legal_actions(state, 0)
    apply_action(state, 0, CastSpell(victim.id, cast_for_free=True))
    drain_stack(state)
    assert victim in state.battlefield and victim.controller_id == 0


def test_choose_void_card_edge_cases():
    eff = ChooseOpponentsExiledCardWithCounterMayPlayFree()
    state = make_state(agent0=ScriptedAgent(library=[None]))
    eff.resolve(state, 0, ())   # nothing exiled
    card = add(state, 1, "Island", Zone.EXILE)
    card.named_counters = (("void", 1),)
    eff.resolve(state, 0, ())   # the agent declines
    assert card.may_play_by is None
