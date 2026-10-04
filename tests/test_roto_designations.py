"""Roto P6 designations: Emberwilde Captain's "Whenever an opponent attacks
you while you're the monarch" punisher."""

from __future__ import annotations

from mtg_bot.actions import DeclareAttackers, apply_action, resolve_top_of_stack
from mtg_bot.cards.base import make_creature
from mtg_bot.cards.parser.roto_keywords import parse_p6_effect, parse_p6_trigger_phrase
from mtg_bot.effects.generic.cube_creatures_ub import BindEventPlayer
from mtg_bot.effects.generic.roto_keywords import DealDamageToPlayerEqualToTheirHandSize
from mtg_bot.effects.predicates import OPPONENT, Controlled, Event
from mtg_bot.turn import Step
from tests._roto_helpers import arena, printing, put, to_hand

CAPTAIN = "Emberwilde Captain"
BEAR = make_creature("Test Bear", "{1}{G}", 2, 2)


def test_emberwilde_captain_parse():
    p = printing(CAPTAIN)
    etb, punisher = p.triggered_abilities
    assert etb.event == Event.ENTERS
    assert punisher.event == Event.YOU_ATTACK
    assert punisher.effect == BindEventPlayer(DealDamageToPlayerEqualToTheirHandSize())
    assert "cards in their hand" in punisher.effect.describe()
    assert parse_p6_trigger_phrase("an opponent attacks you") == (
        Event.YOU_ATTACK, Controlled(OPPONENT, subject="player"),
    )
    assert parse_p6_effect(
        "it deals damage to that player equal to the number of cards in "
        "their hand"
    ) is not None


def _attacked_captain(*, monarch=True, cards=4):
    s = arena(active=1)
    put(s, printing(CAPTAIN), 0)
    s.players[0].is_monarch = monarch
    for _ in range(cards):
        to_hand(s, BEAR, 1)
    attacker = put(s, BEAR, 1)
    s.step = Step.DECLARE_ATTACKERS
    apply_action(s, 1, DeclareAttackers(attacker_ids=frozenset({attacker.id})))
    return s


def test_captain_punishes_an_attack_on_the_monarch():
    s = _attacked_captain(cards=4)
    assert len(s.stack) == 1
    resolve_top_of_stack(s)
    assert s.players[1].life == 16


def test_captain_needs_the_monarch_and_cards_in_hand():
    s = _attacked_captain(monarch=False)
    assert s.stack == []
    s = _attacked_captain(cards=0)
    resolve_top_of_stack(s)
    assert s.players[1].life == 20


def test_captain_ignores_its_controllers_own_attack():
    s = arena()
    put(s, printing(CAPTAIN), 0)
    s.players[0].is_monarch = True
    attacker = put(s, BEAR, 0)
    s.step = Step.DECLARE_ATTACKERS
    apply_action(s, 0, DeclareAttackers(attacker_ids=frozenset({attacker.id})))
    assert s.stack == []


def test_hand_size_damage_needs_a_player():
    s = arena()
    DealDamageToPlayerEqualToTheirHandSize().resolve(s, 0, ())
    DealDamageToPlayerEqualToTheirHandSize().resolve(s, 0, (("creature", 1),))
    assert s.players[1].life == 20
