"""Roto P6 split second (CR 702.61) and Legolas's Quick Reflexes: the
legal-actions filter while a split-second spell is on the stack, the
untap + until-end-of-turn grant, and the granted "becomes tapped"
trigger."""

from __future__ import annotations

from mtg_bot.actions import (
    ActivateAbility,
    ActivateStation,
    CastSpell,
    PassPriority,
    TurnFaceUp,
    apply_action,
    resolve_top_of_stack,
)
from mtg_bot.cards.base import ActivatedAbility, ActivationCost, make_creature
from mtg_bot.cards.parser.roto_keywords import parse_p6_effect
from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.mana import AddManaToPool
from mtg_bot.effects.generic.roto_keywords import (
    SourceDealsDamageEqualToItsPowerToTarget,
    UntapTargetThenGrantUntilEndOfTurn,
    filter_split_second,
    split_second_on_stack,
)
from mtg_bot.effects.predicates import Event
from mtg_bot.game import effective_keywords
from mtg_bot.legal import legal_actions
from mtg_bot.turn import tap_permanent
from tests._roto_helpers import agent, arena, printing, put, to_hand

LEGOLAS = "Legolas's Quick Reflexes"
WRAITH = "Street Wraith"
OGRE = make_creature("Test Ogre", "{2}{R}", 3, 3)
BEAR = make_creature("Test Bear", "{1}{G}", 2, 2)


def _default(name):
    return get_active_source().get_printings()[name]


def _cast_legolas(s, target):
    put(s, _default("Forest"), 0)
    legolas = to_hand(s, printing(LEGOLAS), 0)
    agent(s, 0).targets = [("creature", target.id)]
    apply_action(s, 0, CastSpell(legolas.id))
    return legolas


# ------------------------------------------------------------------ parse


def test_legolas_parse():
    p = printing(LEGOLAS)
    assert p.is_instant and "split second" in p.keywords
    eff = p.spell_effect
    assert isinstance(eff, UntapTargetThenGrantUntilEndOfTurn)
    assert eff.keywords == frozenset({"reach", "hexproof"})
    trig = eff.granted_trigger
    assert trig.event == Event.BECOMES_TAPPED
    assert isinstance(trig.effect, SourceDealsDamageEqualToItsPowerToTarget)
    assert trig.effect.targets[0].count_min == 0  # "up to one"
    assert "untap" in eff.describe() and "its power" in trig.effect.describe()


def test_untap_then_grant_grammar():
    assert isinstance(
        parse_p6_effect(
            "untap target creature. Until end of turn, it gains reach and hexproof"
        ),
        UntapTargetThenGrantUntilEndOfTurn,
    )
    for bad in (
        "untap target creature. Until end of turn, it gains reach, frobs",
        "untap target goblin wizard. Until end of turn, it gains reach",
        'untap target creature. Until end of turn, it gains reach, and '
        '"Whenever this creature attacks, draw a card."',
        'untap target creature. Until end of turn, it gains reach, and '
        '"Whenever this creature becomes tapped, it deals damage equal to '
        'its power to target goblin wizard."',
    ):
        assert parse_p6_effect(bad) is None, bad


# ---------------------------------------------------------- split second


def test_split_second_shuts_off_casting_and_nonmana_abilities():
    s = arena()
    target = put(s, OGRE, 0)
    _cast_legolas(s, target)
    assert split_second_on_stack(s)
    put(s, _default("Mountain"), 1)
    to_hand(s, _default("Lightning Bolt"), 1)
    to_hand(s, printing(WRAITH), 1)  # cycling: a non-mana hand ability
    s.priority_player_idx = 1
    assert legal_actions(s, 1) == [PassPriority()]
    # Without the split-second spell the same player may respond.
    s.stack.clear()
    actions = legal_actions(s, 1)
    assert any(isinstance(a, CastSpell) for a in actions)
    assert any(isinstance(a, ActivateAbility) for a in actions)


def test_split_second_filter_keeps_mana_abilities_and_special_actions():
    s = arena()
    _cast_legolas(s, put(s, OGRE, 0))
    mana_rock = put(s, printing("Serum Powder"), 1)
    swinger = put(s, printing("Blight Mamba"), 1)
    actions = [
        PassPriority(),
        CastSpell(999),
        CastSpell(998, use_plot=True),
        ActivateAbility(source_id=mana_rock.id, ability_index=0),
        ActivateAbility(source_id=swinger.id, ability_index=0),
        ActivateAbility(source_id=swinger.id, ability_index=7),
        ActivateAbility(source_id=424242, ability_index=0),
        ActivateStation(spacecraft_id=1, crew_id=2),
        TurnFaceUp(card_id=5),
    ]
    kept = filter_split_second(s, actions)
    assert CastSpell(999) not in kept
    assert CastSpell(998, use_plot=True) in kept
    assert ActivateAbility(source_id=mana_rock.id, ability_index=0) in kept
    assert ActivateAbility(source_id=swinger.id, ability_index=0) not in kept
    assert ActivateAbility(source_id=swinger.id, ability_index=7) not in kept
    assert ActivateAbility(source_id=424242, ability_index=0) not in kept
    assert not any(isinstance(a, ActivateStation) for a in kept)
    assert TurnFaceUp(card_id=5) in kept  # a special action


def test_split_second_allows_hand_mana_abilities():
    pitch = make_creature("Test Guide", "{2}{R}", 2, 2)
    from dataclasses import replace

    pitch = replace(pitch, hand_activated_abilities=(
        ActivatedAbility(
            cost=ActivationCost(exile_self=True),
            effect=AddManaToPool(produces=(("R", 1),)),
            is_mana_ability=True,
        ),
    ))
    s = arena()
    _cast_legolas(s, put(s, OGRE, 0))
    guide = to_hand(s, pitch, 1)
    wraith = to_hand(s, printing(WRAITH), 1)
    kept = filter_split_second(s, [
        ActivateAbility(source_id=guide.id, ability_index=0),
        ActivateAbility(source_id=wraith.id, ability_index=0),
    ])
    assert kept == [ActivateAbility(source_id=guide.id, ability_index=0)]


# ------------------------------------------------------ Legolas resolution


def test_legolas_untaps_grants_and_its_creature_bites_when_tapped():
    s = arena()
    archer = put(s, OGRE, 0)
    archer.tapped = True
    victim = put(s, BEAR, 1)
    _cast_legolas(s, archer)
    resolve_top_of_stack(s)
    assert not archer.tapped
    assert {"reach", "hexproof"} <= effective_keywords(s, archer)
    agent(s, 0).targets = [("creature", victim.id)]
    tap_permanent(s, archer)
    assert len(s.stack) == 1  # the granted becomes-tapped trigger
    resolve_top_of_stack(s)
    assert victim.damage == 3
    # Until end of turn.
    s.expire_continuous_effects("cleanup")
    assert "reach" not in effective_keywords(s, archer)
    archer.tapped = False
    tap_permanent(s, archer)
    assert s.stack == []


def test_legolas_fizzles_without_its_target():
    s = arena()
    archer = put(s, OGRE, 0)
    archer.tapped = True
    _cast_legolas(s, archer)
    s.battlefield.remove(archer)
    resolve_top_of_stack(s)
    assert archer.tapped and s.continuous_effects == []


def test_bite_trigger_may_choose_no_target():
    s = arena()
    archer = put(s, OGRE, 0)
    eff = SourceDealsDamageEqualToItsPowerToTarget(
        targets=printing(LEGOLAS).spell_effect.granted_trigger.effect.targets,
    )
    s.resolving_source = archer
    eff.resolve(s, 0, ())
    s.resolving_source = None
    eff.resolve(s, 0, (("creature", archer.id),))
    assert archer.damage == 0
