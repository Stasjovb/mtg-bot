"""Unsubstantiate (Forgetful Fish): "Return target spell or creature to
its owner's hand." -- Venser's "spell or permanent" bounce with a
creature filter."""

from __future__ import annotations

from mtg_bot.actions import CastSpell, apply_action, resolve_top_of_stack
from mtg_bot.cards.parser.roto_stack import parse_roto_stack_effect
from mtg_bot.effects.generic.roto_stack import ReturnTargetSpellOrPermanentToHand
from mtg_bot.effects.object_predicates import IsCreature
from mtg_bot.legal import legal_actions

from tests._fish_helpers import printing
from tests._roto_helpers import agent, arena, put, to_hand


def _lands(state, n, pid=0):
    for _ in range(n):
        put(state, printing("Island"), pid)


def _cast(state, pid, card):
    action = CastSpell(card.id)
    assert action in legal_actions(state, pid)
    apply_action(state, pid, action)


def _drain(state):
    while state.stack:
        resolve_top_of_stack(state)


def test_parses_with_a_creature_filter():
    eff = printing("Unsubstantiate").spell_effect
    assert eff == ReturnTargetSpellOrPermanentToHand(
        permanent_filter=IsCreature(), noun="creature",
    )
    assert eff.describe() == "return target spell or creature to its owner's hand"
    assert parse_roto_stack_effect(
        "return target spell or gizmo to its owner's hand"
    ) is None


def test_targets_creatures_not_other_permanents():
    state = arena()
    fish = put(state, printing("Dandân"), 1)
    land = put(state, printing("Island"), 1)
    targets = printing("Unsubstantiate").spell_effect.legal_targets(state, 0)
    assert ("creature", fish.id) in targets
    assert all(tid != land.id for _, tid in targets)


def test_returns_a_creature_to_its_owners_hand():
    state = arena()
    fish = put(state, printing("Dandân"), 1)
    put(state, printing("Island"), 1)
    spell = to_hand(state, printing("Unsubstantiate"))
    _lands(state, 2)
    agent(state, 0).targets = [("creature", fish.id)]
    _cast(state, 0, spell)
    _drain(state)
    assert fish in state.players[1].hand


def test_returns_a_spell_to_its_owners_hand():
    state = arena(active=1)
    knowledge = to_hand(state, printing("Accumulated Knowledge"), 1)
    _lands(state, 2, 1)
    _cast(state, 1, knowledge)
    spell = to_hand(state, printing("Unsubstantiate"))
    _lands(state, 2)
    state.priority_player_idx = 0  # player 1 passed with the spell on the stack
    agent(state, 0).targets = [("stack", 0)]
    _cast(state, 0, spell)
    _drain(state)
    assert knowledge in state.players[1].hand
    assert len(state.players[1].hand) == 1  # it never resolved


def test_a_target_that_stopped_being_a_creature_is_illegal():
    state = arena()
    land = put(state, printing("Island"), 1)
    eff = printing("Unsubstantiate").spell_effect
    eff.resolve(state, 0, (("permanent", land.id),))
    assert land in state.battlefield
