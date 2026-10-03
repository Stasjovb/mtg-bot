"""Roto P6: Start your engines! / speed (CR 702.179) and Momentum Breaker
("each opponent sacrifices a creature or Vehicle ...; each opponent who
can't discards a card", "you gain life equal to your speed")."""

from __future__ import annotations

from mtg_bot.actions import ActivateAbility, apply_action, resolve_top_of_stack
from mtg_bot.cards.base import make_artifact, make_creature
from mtg_bot.cards.parser.roto_keywords import parse_p6_effect
from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.roto_keywords import (
    MAX_SPEED,
    START_YOUR_ENGINES,
    EachOpponentSacrificesOrDiscards,
    GainLifeEqualToYourSpeed,
    update_speed,
)
from mtg_bot.turn import note_life_losses, state_based_actions
from tests._roto_helpers import agent, arena, printing, put, to_hand

BREAKER = "Momentum Breaker"
BEAR = make_creature("Test Bear", "{1}{G}", 2, 2)


def _default(name):
    return get_active_source().get_printings()[name]


def test_momentum_breaker_parse():
    p = printing(BREAKER)
    assert p.is_enchantment and START_YOUR_ENGINES in p.keywords
    (etb,) = p.triggered_abilities
    assert isinstance(etb.effect, EachOpponentSacrificesOrDiscards)
    assert "who can't discards" in etb.effect.describe()
    (ability,) = p.activated_abilities
    assert ability.cost.sacrifice_self and ability.cost.mana_str == "{2}"
    assert ability.effect == GainLifeEqualToYourSpeed()
    assert ability.effect.describe() == "you gain life equal to your speed"
    assert parse_p6_effect(
        "each opponent sacrifices a creature or goblin wizard of their choice. "
        "Each opponent who can't discards a card"
    ) is None


def test_start_your_engines_gives_speed_one():
    s = arena()
    assert s.players[0].speed == 0
    put(s, printing(BREAKER), 0)
    state_based_actions(s)
    assert s.players[0].speed == 1 and s.players[1].speed == 0


def test_speed_increases_once_each_of_your_turns_when_an_opponent_loses_life():
    s = arena()
    put(s, printing(BREAKER), 0)
    state_based_actions(s)
    s.players[1].life -= 2
    note_life_losses(s)
    assert s.players[0].speed == 2
    s.players[1].life -= 2  # again this turn: no further increase
    note_life_losses(s)
    assert s.players[0].speed == 2
    # Next turn (still P0's, for the test) it can increase again...
    s.turn_number += 1
    s.players[1].lost_life_this_turn = False
    note_life_losses(s)
    assert s.players[0].speed == 2  # ...only after an opponent loses life
    s.players[1].life -= 1
    note_life_losses(s)
    assert s.players[0].speed == 3


def test_speed_needs_your_turn_and_caps_at_four():
    s = arena(active=1)
    put(s, printing(BREAKER), 0)
    s.players[1].life -= 3  # P1 loses life on P1's own turn
    state_based_actions(s)
    assert s.players[0].speed == 1
    s = arena()
    s.players[0].speed = MAX_SPEED
    s.players[1].lost_life_this_turn = True
    update_speed(s)
    assert s.players[0].speed == MAX_SPEED
    # No speed at all: nothing increases.
    s = arena()
    s.players[1].lost_life_this_turn = True
    update_speed(s)
    assert s.players[0].speed == 0


def test_breaker_etb_sacrifice_or_discard():
    s = arena()
    vehicle = put(s, make_artifact("Test Vehicle", "{2}", subtype="Vehicle"), 1)
    to_hand(s, BEAR, 1)
    eff = printing(BREAKER).triggered_abilities[0].effect
    eff.resolve(s, 0)
    assert vehicle in s.players[1].graveyard and len(s.players[1].hand) == 1
    # Nothing to sacrifice: discard instead.
    eff.resolve(s, 0)
    assert s.players[1].hand == [] and len(s.players[1].graveyard) == 2
    # Nothing at all: nothing happens.
    eff.resolve(s, 0)
    assert len(s.players[1].graveyard) == 2


def test_breaker_sacrifice_gains_life_equal_to_speed():
    s = arena()
    breaker = put(s, printing(BREAKER), 0)
    put(s, _default("Swamp"), 0)
    put(s, _default("Swamp"), 0)
    s.players[0].speed = 3
    apply_action(s, 0, ActivateAbility(source_id=breaker.id, ability_index=0))
    assert breaker in s.players[0].graveyard
    resolve_top_of_stack(s)
    assert s.players[0].life == 23
    # Speed 0: no life.
    GainLifeEqualToYourSpeed().resolve(s, 1)
    assert s.players[1].life == 20


def test_speed_survives_clone():
    s = arena()
    s.players[0].speed = 2
    assert s.clone().players[0].speed == 2
