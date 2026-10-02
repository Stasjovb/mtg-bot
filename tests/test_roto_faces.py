"""Roto P6 face-changing cards: Delver of Secrets' upkeep look / may
reveal / transform."""

from __future__ import annotations

from mtg_bot.actions import resolve_top_of_stack
from mtg_bot.cards.parser.roto_keywords import parse_p6_effect
from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.card_flow import CardFilter
from mtg_bot.effects.generic.layout_effects import TransformSource
from mtg_bot.effects.generic.roto_keywords import LookAtTopMayRevealIfMatches
from mtg_bot.effects.predicates import Event
from mtg_bot.turn import run_beginning_of_upkeep_triggers
from tests._roto_helpers import agent, arena, printing, put, roto_card, to_hand, to_library

DELVER = "Delver of Secrets // Insectile Aberration"


def _default(name):
    return get_active_source().get_printings()[name]


def test_delver_parse():
    p = printing(DELVER)
    (trig,) = p.triggered_abilities
    assert trig.event == Event.BEGINNING_OF_UPKEEP
    assert trig.effect == LookAtTopMayRevealIfMatches(
        card_filter=CardFilter(any_types=("Instant", "Sorcery")),
        then=TransformSource(),
    )
    back = p.transform_back_face
    assert back.name == "Insectile Aberration"
    assert "flying" in back.keywords and (back.power, back.toughness) == (3, 2)
    assert "look at the top card" in trig.effect.describe()


def test_look_may_reveal_grammar():
    phrase = (
        "look at the top card of your library. You may reveal that card. "
        "If a creature card is revealed this way, draw a card"
    )
    eff = parse_p6_effect(phrase)
    assert eff.card_filter == CardFilter(any_types=("Creature",))
    assert parse_p6_effect(phrase.replace("creature", "goblin")) is None
    assert parse_p6_effect(phrase.replace("draw a card", "frobnicate")) is None
    assert parse_p6_effect(
        phrase.replace("draw a card", "destroy target creature")
    ) is None
    assert parse_p6_effect("draw a card") is None


def _delver_upkeep(top_name, *, yes=True, library=True):
    s = arena()
    delver = put(s, printing(DELVER), 0)
    if library:
        top = to_library(s, _default(top_name), 0)
        to_library(s, _default("Island"), 0)
    else:
        top = None
    agent(s, 0).yes = yes
    run_beginning_of_upkeep_triggers(s)
    resolve_top_of_stack(s)
    return s, delver, top


def test_delver_transforms_on_a_revealed_instant():
    s, delver, top = _delver_upkeep("Lightning Bolt")
    assert delver.printing.name == "Insectile Aberration"
    assert top.publicly_known_to == frozenset({0, 1})
    assert s.players[0].library[0] is top  # the card stays on top


def test_delver_may_decline_to_reveal():
    s, delver, top = _delver_upkeep("Lightning Bolt", yes=False)
    assert delver.printing.name == DELVER
    assert top.publicly_known_to == frozenset({0})  # looked at only


def test_delver_stays_on_a_land():
    s, delver, top = _delver_upkeep("Island")
    assert delver.printing.name == DELVER
    assert top.publicly_known_to == frozenset({0})


def test_delver_with_an_empty_library():
    s, delver, _ = _delver_upkeep(None, library=False)
    assert delver.printing.name == DELVER


def test_delver_only_on_its_controllers_upkeep():
    s = arena(active=1)
    put(s, printing(DELVER), 0)
    run_beginning_of_upkeep_triggers(s)
    assert s.stack == []


# ------------------------------------------------- Erayo (flip layout)

ERAYO = "Erayo, Soratami Ascendant // Erayo's Essence"


def _erayo_arena(active=1):
    s = arena(active=active)
    erayo = put(s, printing(ERAYO), 0)
    return s, erayo


def _cast_bolt(s, player_id, target):
    from mtg_bot.actions import CastSpell, apply_action

    put(s, _default("Mountain"), player_id)
    bolt = to_hand(s, _default("Lightning Bolt"), player_id)
    agent(s, player_id).targets = [target]
    s.priority_player_idx = player_id
    apply_action(s, player_id, CastSpell(bolt.id))
    return bolt


def test_erayo_parse():
    from mtg_bot.effects.generic.roto_keywords import FlipSource, NthSpellOfTurn

    p = printing(ERAYO)
    assert p.is_creature and p.is_legendary and "flying" in p.keywords
    (trig,) = p.triggered_abilities
    assert trig.event == Event.IS_CAST and trig.predicate == NthSpellOfTurn(4)
    assert isinstance(trig.effect, FlipSource)
    essence = trig.effect.flipped
    assert essence.name == "Erayo's Essence"
    assert essence.is_enchantment and not essence.is_creature
    assert essence.mana_cost_str == "{1}{U}"  # the card's own cost
    assert trig.effect.describe() == "flip this permanent"
    # Outside a flip card the phrase means nothing.
    assert parse_p6_effect("flip this creature") is None


def test_erayo_flips_on_the_fourth_spell_of_the_turn():
    s, erayo = _erayo_arena()
    s.players[0].spells_cast_this_turn = 2
    s.players[1].spells_cast_this_turn = 1
    _cast_bolt(s, 1, ("player", 0))  # the turn's fourth spell
    assert len(s.stack) == 2
    resolve_top_of_stack(s)  # the flip trigger
    assert erayo.printing.name == "Erayo's Essence"
    assert not erayo.printing.is_creature


def test_erayo_ignores_other_spell_counts():
    s, erayo = _erayo_arena()
    s.players[1].spells_cast_this_turn = 1
    _cast_bolt(s, 1, ("player", 0))  # the second spell
    assert len(s.stack) == 1
    assert erayo.printing.name == ERAYO


def test_erayos_essence_counters_each_opponents_first_spell():
    s, erayo = _erayo_arena()
    from mtg_bot.effects.generic.roto_keywords import FlipSource

    s.resolving_source = erayo
    FlipSource(flipped=printing(ERAYO).triggered_abilities[0].effect.flipped).resolve(s, 0)
    s.resolving_source = None
    # Flipping twice does nothing more.
    s.resolving_source = erayo
    printing(ERAYO).triggered_abilities[0].effect.resolve(s, 0)
    s.resolving_source = None
    bolt = _cast_bolt(s, 1, ("player", 0))
    assert len(s.stack) == 2
    resolve_top_of_stack(s)  # counter that spell
    assert s.stack[-1].source is bolt and s.stack[-1].countered
    resolve_top_of_stack(s)
    assert s.players[0].life == 20
    # Their second spell this turn resolves.
    _cast_bolt(s, 1, ("player", 0))
    assert len(s.stack) == 1
    resolve_top_of_stack(s)
    assert s.players[0].life == 17


def test_erayos_essence_spares_its_controllers_spells_and_uncounterable_ones():
    from dataclasses import replace

    from mtg_bot.actions import CastSpell, apply_action
    from mtg_bot.effects.generic.roto_keywords import CounterThatSpell, FlipSource

    s, erayo = _erayo_arena(active=0)
    s.resolving_source = erayo
    FlipSource(flipped=printing(ERAYO).triggered_abilities[0].effect.flipped).resolve(s, 0)
    s.resolving_source = None
    _cast_bolt(s, 0, ("player", 1))
    assert len(s.stack) == 1
    # An opponent's uncounterable first spell isn't countered.
    s2, erayo2 = _erayo_arena()
    s2.resolving_source = erayo2
    FlipSource(flipped=printing(ERAYO).triggered_abilities[0].effect.flipped).resolve(s2, 0)
    s2.resolving_source = None
    put(s2, _default("Mountain"), 1)
    tough = to_hand(s2, replace(_default("Lightning Bolt"), spell_is_uncounterable=True), 1)
    agent(s2, 1).targets = [("player", 0)]
    apply_action(s2, 1, CastSpell(tough.id))
    resolve_top_of_stack(s2)
    assert not s2.stack[-1].countered
    # Nothing to counter: a no-op.
    s3 = arena()
    s3.resolving_event_subject_id = 12345
    CounterThatSpell().resolve(s3, 0)
    assert CounterThatSpell().event_subject_id({}) == -1


def test_flipped_erayo_unflips_when_it_leaves_the_battlefield():
    import pytest

    from mtg_bot.effects.generic.roto_keywords import FlipSource
    from mtg_bot.turn import move_off_battlefield

    s, erayo = _erayo_arena()
    s.resolving_source = erayo
    printing(ERAYO).triggered_abilities[0].effect.resolve(s, 0)
    s.resolving_source = None
    assert erayo.printing.name == "Erayo's Essence"
    move_off_battlefield(s, erayo, destination="graveyard")
    assert erayo.printing.name == ERAYO
    with pytest.raises(ValueError):
        FlipSource().resolve(s, 0)
    # A flip whose source has left does nothing.
    s.resolving_source = erayo
    printing(ERAYO).triggered_abilities[0].effect.resolve(s, 0)
    assert erayo.printing.name == ERAYO


def test_flip_builder_edges():
    from mtg_bot.cards.parser.flip_builder import _build_flip_printing

    base = dict(roto_card(ERAYO))
    top, bottom = base["card_faces"]
    # Not a flip card / wrong face count.
    assert _build_flip_printing(dict(base, layout="transform")) is None
    assert _build_flip_printing(dict(base, card_faces=[top])) is None
    # Both halves must be permanents (CR 710.1).
    sorcery = dict(bottom, type_line="Sorcery")
    assert _build_flip_printing(dict(base, card_faces=[top, sorcery])) is None
    # An unparseable line on either half leaves the card unclaimed.
    bad = dict(bottom, oracle_text="Frobnicate the widgets.")
    assert _build_flip_printing(dict(base, card_faces=[top, bad])) is None
    bad_top = dict(top, oracle_text=top["oracle_text"] + "\nFrobnicate.")
    assert _build_flip_printing(dict(base, card_faces=[bad_top, bottom])) is None
    # A creature bottom half builds through the regular face dispatch.
    creature = dict(
        bottom, name="Test Flipped", type_line="Legendary Creature — Spirit",
        oracle_text="Flying", power="3", toughness="3",
    )
    p = _build_flip_printing(dict(base, card_faces=[top, creature]))
    flipped = p.triggered_abilities[0].effect.flipped
    assert flipped.is_creature and flipped.mana_cost_str == "{1}{U}"
