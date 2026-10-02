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
from tests._roto_helpers import agent, arena, printing, put, to_library

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
