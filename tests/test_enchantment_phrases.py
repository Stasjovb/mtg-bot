"""Phrase recognizers of the cube enchantment bucket
(``cards/parser/enchantment_phrases.py``) and the grammar extensions
they ride on (self-subject damage in activated abilities, the Exhaust
guard, the ``for each`` cost reduction, new trigger phrases)."""

from __future__ import annotations

from mtg_bot.cards.parser.activated import _parse_activated_ability_line
from mtg_bot.cards.parser.clause import _parse_clause
from mtg_bot.cards.parser.cost_reduction import _parse_cost_reduction_line
from mtg_bot.cards.parser.enchantment_phrases import (
    parse_enchantment_phrase,
    parse_reanimation_aura_line,
)
from mtg_bot.effects.conditions import PerBasicLandTypeAmongLandsYouControl
from mtg_bot.effects.generic.enchantment_mechanics import (
    AddOneManaSacrificedLandCouldProduce,
    EachPlayerReturnsCardsExiledWithSource,
    ExileTargetReturnAtNextEndStep,
    ExileTargetUntilSourceLeaves,
    LinkedCreatureControllerSacrifices,
    OathRevealUntilCreature,
    ReanimateAndAttachSource,
)
from mtg_bot.effects.predicates import Always, Event


def test_effect_phrases():
    assert parse_enchantment_phrase(
        "add one mana of any type the sacrificed land could produce"
    ) == AddOneManaSacrificedLandCouldProduce()
    eff = parse_enchantment_phrase(
        "exile up to one target artifact or creature until this "
        "enchantment leaves the battlefield"
    )
    assert isinstance(eff, ExileTargetUntilSourceLeaves)
    assert eff.targets[0].count_min == 0
    eff = parse_enchantment_phrase(
        "exile target creature until this artifact leaves the battlefield"
    )
    assert eff.targets[0].count_min == 1
    eff = parse_enchantment_phrase(
        "exile target artifact or creature. Return it to the battlefield "
        "under its owner's control at the beginning of the next end step"
    )
    assert isinstance(eff, ExileTargetReturnAtNextEndStep)
    assert parse_enchantment_phrase(
        "each player returns to the battlefield all cards they own exiled "
        "with it"
    ) == EachPlayerReturnsCardsExiledWithSource()
    assert parse_enchantment_phrase(
        "that player chooses target player who controls more creatures "
        "than they do and is their opponent. The first player may reveal "
        "cards from the top of their library until they reveal an "
        "artifact card. If the first player does, that player puts that "
        "card onto the battlefield and all other cards revealed this way "
        "into their graveyard"
    ) == OathRevealUntilCreature(card_type="artifact")


def test_effect_phrases_reject_unknown_nouns():
    assert parse_enchantment_phrase(
        "exile target frobnitz until this enchantment leaves the battlefield"
    ) is None
    assert parse_enchantment_phrase(
        "exile target frobnitz. Return it to the battlefield under its "
        "owner's control at the beginning of the next end step"
    ) is None
    assert parse_enchantment_phrase("draw a frobnitz") is None


def test_reanimation_lines():
    animate = (
        "When this Aura enters, if it's on the battlefield, it loses "
        "\"enchant creature card in a graveyard\" and gains \"enchant "
        "creature put onto the battlefield with this Aura.\" Return "
        "enchanted creature card to the battlefield under your control and "
        "attach this Aura to it. When this Aura leaves the battlefield, "
        "that creature's controller sacrifices it."
    )
    triggers, fields = parse_reanimation_aura_line(animate)
    assert fields == {}
    assert triggers[0].event == Event.ENTERS
    assert triggers[0].effect == ReanimateAndAttachSource(from_target=False)
    assert triggers[1].event == Event.LEAVES_BATTLEFIELD
    assert triggers[1].effect == LinkedCreatureControllerSacrifices()
    necro = (
        "When this enchantment enters, if it's on the battlefield, it "
        "becomes an Aura with \"enchant creature put onto the battlefield "
        "with Necromancy.\" Put target creature card from a graveyard onto "
        "the battlefield under your control and attach this enchantment to "
        "it. When this enchantment leaves the battlefield, that creature's "
        "controller sacrifices it."
    )
    triggers, _ = parse_reanimation_aura_line(necro)
    assert triggers[0].effect == ReanimateAndAttachSource(from_target=True)
    # Mixed self-references don't match.
    assert parse_reanimation_aura_line(
        necro.replace("When this enchantment leaves", "When this Aura leaves")
    ) is None
    _, fields = parse_reanimation_aura_line(
        "You may cast this spell as though it had flash. If you cast it any "
        "time a sorcery couldn't have been cast, the controller of the "
        "permanent it becomes sacrifices it at the beginning of the next "
        "cleanup step."
    )
    assert fields["flash"] is True
    assert fields["sacrifice_at_cleanup_if_cast_without_sorcery_timing"]
    assert parse_reanimation_aura_line("Flying") is None


def test_self_subject_damage_in_activated_abilities():
    for noun in ("enchantment", "artifact", "creature", "land"):
        ab = _parse_activated_ability_line(
            f"{{T}}: This {noun} deals 1 damage to any target."
        )
        assert ab is not None and ab.effect.amount == 1


def test_exhaust_is_not_an_ability_word():
    assert _parse_activated_ability_line(
        "Exhaust — {U}, {T}: Draw three cards."
    ) is None
    # Real ability words are still stripped.
    assert _parse_activated_ability_line(
        "Metalcraft — {T}: Draw a card."
    ) is not None


def test_for_each_cost_reduction():
    red = _parse_cost_reduction_line(
        "Domain — This spell costs {1} less to cast for each basic land "
        "type among lands you control."
    )
    assert red.amount == 1
    assert red.condition == PerBasicLandTypeAmongLandsYouControl()
    assert _parse_cost_reduction_line(
        "This spell costs {1} less to cast for each frobnitz you control."
    ) is None


def test_new_trigger_phrases():
    (t,) = _parse_clause(
        "At the beginning of the end step, sacrifice this enchantment.",
    ).triggers
    assert t.event == Event.BEGINNING_OF_END_STEP and t.predicate == Always()
    (t,) = _parse_clause(
        "At the beginning of each player's upkeep, you gain 1 life.",
    ).triggers
    assert t.event == Event.BEGINNING_OF_UPKEEP and t.predicate == Always()
    (t,) = _parse_clause(
        "When this enchantment leaves the battlefield, you gain 1 life.",
    ).triggers
    assert t.event == Event.LEAVES_BATTLEFIELD
    (t,) = _parse_clause(
        "When this Aura leaves the battlefield, you gain 1 life.",
    ).triggers
    assert t.event == Event.LEAVES_BATTLEFIELD
    (t,) = _parse_clause(
        "Whenever you play a land, you gain 1 life.",
    ).triggers
    assert t.event == Event.PLAYS_LAND
