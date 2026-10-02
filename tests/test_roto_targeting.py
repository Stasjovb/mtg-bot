"""Roto P6 "becomes the target" triggers with spell-vs-ability and
controller qualifiers (Loki, God of Mischief; Venerated Rotpriest) and
Toxic N."""

from __future__ import annotations

from mtg_bot.actions import (
    ActivateAbility,
    CastSpell,
    DeclareAttackers,
    apply_action,
    resolve_top_of_stack,
)
from mtg_bot.cards.base import make_creature
from mtg_bot.cards.parser.roto_keywords import parse_p6_effect, parse_p6_trigger_phrase
from mtg_bot.cards.source import get_active_source
from mtg_bot.combat import resolve_combat_damage
from mtg_bot.effects.generic.roto_keywords import (
    TargetIsPlayerOrPermanent,
    TargetingIs,
    TargetOpponentGetsPoisonCounters,
    apply_toxic,
    toxic_amount,
)
from mtg_bot.effects.predicates import OPPONENT, YOU, Controlled, Event
from mtg_bot.turn import Step
from tests._roto_helpers import agent, arena, printing, put, to_hand, to_library

LOKI = "Loki, God of Mischief"
ROTPRIEST = "Venerated Rotpriest"
NOMADS = "Nomads en-Kor"

BEAR = make_creature("Test Bear", "{1}{G}", 2, 2)


def _default(name):
    return get_active_source().get_printings()[name]


def _nomads_shield(s, nomads, recipient, player_id=0):
    agent(s, player_id).targets = [("creature", recipient.id)]
    apply_action(
        s, player_id, ActivateAbility(source_id=nomads.id, ability_index=0),
    )


def _bolt(s, target, player_id=0):
    put(s, _default("Mountain"), player_id)
    bolt = to_hand(s, _default("Lightning Bolt"), player_id)
    agent(s, player_id).targets = [target]
    apply_action(s, player_id, CastSpell(bolt.id))


# ------------------------------------------------------------------ parse


def test_becomes_target_trigger_grammar():
    ev, pred = parse_p6_trigger_phrase(
        "a player or permanent becomes the target of an ability you control"
    )
    assert ev == Event.BECOMES_TARGET
    assert pred == (
        TargetIsPlayerOrPermanent() & TargetingIs("ability")
        & Controlled(YOU, subject="controller")
    )
    _, pred = parse_p6_trigger_phrase(
        "this creature becomes the target of a spell an opponent controls"
    )
    assert pred.right == Controlled(OPPONENT, subject="controller")
    assert parse_p6_trigger_phrase("a goblin becomes the target of a spell") is None


def test_loki_and_rotpriest_parse():
    (loki_trig,) = printing(LOKI).triggered_abilities
    assert loki_trig.once_per_turn
    priest = printing(ROTPRIEST)
    assert "toxic 1" in priest.keywords
    (trig,) = priest.triggered_abilities
    assert isinstance(trig.effect, TargetOpponentGetsPoisonCounters)
    assert trig.effect.describe() == "target opponent gets 1 poison counter(s)"
    assert parse_p6_effect("target opponent gets lots poison counters") is None


# ------------------------------------------------------------------ Loki


def test_loki_draws_when_your_ability_targets_once_each_turn():
    s = arena()
    put(s, printing(LOKI), 0)
    nomads = put(s, printing(NOMADS), 0)
    bear = put(s, BEAR, 0)
    for _ in range(3):
        to_library(s, BEAR, 0)
    _nomads_shield(s, nomads, bear)
    assert len(s.stack) == 2  # the ability + Loki's trigger
    resolve_top_of_stack(s)
    assert len(s.players[0].hand) == 1
    resolve_top_of_stack(s)
    # Once each turn.
    _nomads_shield(s, nomads, bear)
    assert len(s.stack) == 1


def test_loki_ignores_spells_and_opponents_abilities():
    s = arena()
    put(s, printing(LOKI), 0)
    bear = put(s, BEAR, 1)
    _bolt(s, ("creature", bear.id))
    assert len(s.stack) == 1  # the Bolt alone
    s2 = arena()
    put(s2, printing(LOKI), 0)
    their_nomads = put(s2, printing(NOMADS), 1)
    their_bear = put(s2, BEAR, 1)
    _nomads_shield(s2, their_nomads, their_bear, player_id=1)
    assert len(s2.stack) == 1


# ------------------------------------------------------- Venerated Rotpriest


def test_rotpriest_poisons_when_a_spell_targets_your_creature():
    s = arena()
    priest = put(s, printing(ROTPRIEST), 0)
    _bolt(s, ("creature", priest.id))
    assert len(s.stack) == 2
    resolve_top_of_stack(s)  # the trigger: target opponent
    assert s.players[1].poison_counters == 1
    # An opponent's spell targeting your creature counts too.
    s2 = arena(active=1)
    priest2 = put(s2, printing(ROTPRIEST), 0)
    _bolt(s2, ("creature", priest2.id), player_id=1)
    assert len(s2.stack) == 2
    resolve_top_of_stack(s2)
    assert s2.players[1].poison_counters == 1


def test_rotpriest_ignores_abilities_and_other_players_creatures():
    s = arena()
    put(s, printing(ROTPRIEST), 0)
    nomads = put(s, printing(NOMADS), 0)
    bear = put(s, BEAR, 0)
    _nomads_shield(s, nomads, bear)
    assert len(s.stack) == 1
    s2 = arena()
    put(s2, printing(ROTPRIEST), 0)
    their_bear = put(s2, BEAR, 1)
    _bolt(s2, ("creature", their_bear.id))
    assert len(s2.stack) == 1


def test_poison_trigger_fizzles_without_a_legal_opponent():
    eff = printing(ROTPRIEST).triggered_abilities[0].effect
    s = arena()
    eff.resolve(s, 0, ())
    s.players[1].has_lost = True
    eff.resolve(s, 0, (("player", 1),))
    assert s.players[1].poison_counters == 0


# ------------------------------------------------------------------ toxic


def test_toxic_adds_poison_with_combat_damage_to_a_player():
    s = arena()
    priest = put(s, printing(ROTPRIEST), 0)
    assert toxic_amount(s, priest) == 1
    s.step = Step.DECLARE_ATTACKERS
    apply_action(s, 0, DeclareAttackers(attacker_ids=frozenset({priest.id})))
    s.step = Step.COMBAT_DAMAGE
    resolve_combat_damage(s, defending_player_id=1)
    assert s.players[1].life == 19 and s.players[1].poison_counters == 1


def test_toxic_needs_damage_dealt():
    s = arena()
    priest = put(s, printing(ROTPRIEST), 0)
    apply_toxic(s, [(priest.id, 1, 0), (9999, 1, 2)])
    assert s.players[1].poison_counters == 0
    assert toxic_amount(s, put(s, BEAR, 0)) == 0
