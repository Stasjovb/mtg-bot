"""Vintage Roto P2, F10 tutors: Imperial Recruiter, Recruiter of the
Guard, Unmarked Grave, Gamble, Fabled Passage, Ghost Quarter, Protean
Hulk, Academy Rector, Arena Rector -- each played in a game through
the parser-built printing."""

from __future__ import annotations

import pytest

from mtg_bot import apply
from mtg_bot.actions import (
    ActivateAbility,
    CastSpell,
    drain_stack,
    put_into_battlefield,
)
from mtg_bot.cards import BASIC_LANDS, make_creature
from mtg_bot.cards.base import make_enchantment, make_planeswalker
from mtg_bot.cards.parser.roto_zones import (
    parse_roto_descriptor,
    parse_roto_zones_effect,
)
from mtg_bot.effects.generic.card_flow import SearchLibrary
from mtg_bot.effects.generic.roto_zones import (
    ExileSourceCardFromGraveyard,
    RotoCardFilter,
    search_pick,
)
from mtg_bot.game import Zone
from mtg_bot.turn import move_off_battlefield

from tests._roto_helpers import (
    agent,
    arena,
    printing,
    put,
    to_graveyard,
    to_hand,
    to_library,
)


BEAR = make_creature("Test Bear", "{1}{G}", 2, 2)
OGRE = make_creature("Test Ogre", "{2}{R}", 3, 2)
WALL = make_creature("Test Wall", "{1}{W}", 0, 4)
ELF = make_creature("Test Elf", "{G}", 1, 1)
GIANT = make_creature("Test Giant", "{4}{G}", 5, 5)
LEGEND = make_creature("Test Legend", "{1}{B}", 2, 2, legendary=True)


def _names(zone):
    return sorted(c.printing.name for c in zone)


def _enter(state, pr, controller=0):
    obj = state.new_object(pr, owner_id=controller, zone=Zone.STACK)
    put_into_battlefield(state, obj, controller)
    return obj


def _cast(state, pr, lands, pid=0):
    for land in lands:
        put(state, BASIC_LANDS[land], pid)
    card = to_hand(state, pr, owner=pid)
    apply(state, CastSpell(card_id=card.id), pid)
    drain_stack(state)
    return card


# --- descriptor grammar ------------------------------------------------------

def test_roto_descriptor_words():
    f = parse_roto_descriptor("a nonlegendary card")
    assert f.excluded_supertypes == ("Legendary",) and f.has_quality
    assert f.describe() == "nonlegendary card"
    assert not f.matches(LEGEND) and f.matches(BEAR)
    f = parse_roto_descriptor("a creature card with power 2 or less")
    assert f.max_power == 2 and f.matches(BEAR) and not f.matches(OGRE)
    assert "with power 2 or less" in f.describe()
    f = parse_roto_descriptor("a creature card with toughness 2 or less")
    assert f.matches(OGRE) and not f.matches(WALL)
    assert "with toughness 2 or less" in f.describe()
    f = parse_roto_descriptor("a basic land card")
    assert f.supertype == "Basic" and f.matches(BASIC_LANDS["Forest"])
    assert parse_roto_descriptor("a basic legendary land card") is None
    assert parse_roto_descriptor("a frobnicated card") is None
    # A noncreature card has no printed power: it counts as 0.
    assert RotoCardFilter(max_power=0).matches(BASIC_LANDS["Forest"])
    assert not RotoCardFilter().has_quality


def test_tutor_grammar_rejects_unknown_shapes():
    assert parse_roto_zones_effect(
        "search your library for a frobnicated card, put it into your hand, "
        "then shuffle"
    ) is None
    assert parse_roto_zones_effect(
        "search your library for a card, put it into your hand tapped, then "
        "shuffle"
    ) is None
    for phrase in (
        "search your library for a frob card, put that card into your hand, "
        "discard a card at random, then shuffle",
        "search your library for a frob card, put it onto the battlefield "
        "tapped, then shuffle. Then if you control four or more lands, untap "
        "that land",
        "search your library for any number of frob cards with total mana "
        "value 6 or less, put them onto the battlefield, then shuffle",
        "destroy target land. Its controller may search their library for a "
        "frob card, put it onto the battlefield, then shuffle",
        "destroy target frob. Its controller may search their library for a "
        "basic land card, put it onto the battlefield, then shuffle",
        "you may exile it. If you do, search your library for a frob card",
    ):
        assert parse_roto_zones_effect(phrase) is None, phrase


def test_search_pick_falls_back_only_for_a_plain_card():
    state = arena()
    p = state.players[0]
    a = to_library(state, BEAR)
    agent(state).library_pick = None
    assert search_pick(state, p, [a], may_fail=True) is None
    assert search_pick(state, p, [a], may_fail=False) is a
    assert search_pick(state, p, [], may_fail=False) is None
    p.agent = None
    assert search_pick(state, p, [a], may_fail=True) is None


# --- Imperial Recruiter / Recruiter of the Guard ----------------------------

def test_imperial_recruiter_finds_power_two_or_less_creature():
    state = arena()
    to_library(state, OGRE)
    bear = to_library(state, BEAR)
    _enter(state, printing("Imperial Recruiter"))
    drain_stack(state)
    hand = state.players[0].hand
    assert hand == [bear]
    assert 1 in bear.publicly_known_to      # revealed
    assert _names(state.players[0].library) == ["Test Ogre"]


def test_recruiter_of_the_guard_is_optional_and_toughness_bounded():
    eff = printing("Recruiter of the Guard").triggered_abilities[0].effect
    inner = eff.inner
    assert isinstance(inner, SearchLibrary) and inner.reveal
    state = arena()
    to_library(state, WALL)
    ogre = to_library(state, OGRE)
    _enter(state, printing("Recruiter of the Guard"))
    drain_stack(state)
    assert state.players[0].hand == [ogre]
    state = arena()
    to_library(state, OGRE)
    agent(state).yes = False
    _enter(state, printing("Recruiter of the Guard"))
    drain_stack(state)
    assert state.players[0].hand == []


# --- Unmarked Grave ----------------------------------------------------------

def test_unmarked_grave_puts_nonlegendary_card_into_graveyard():
    state = arena()
    to_library(state, LEGEND)
    bear = to_library(state, BEAR)
    _cast(state, printing("Unmarked Grave"), ["Swamp", "Swamp"])
    gy = state.players[0].graveyard
    assert bear in gy and bear.zone == Zone.GRAVEYARD
    assert _names(state.players[0].library) == ["Test Legend"]


# --- Gamble -------------------------------------------------------------------

def test_gamble_tutors_then_discards_at_random():
    state = arena(seed=3)
    target = to_library(state, GIANT)
    for _ in range(3):
        to_library(state, ELF)
    agent(state).library_pick = target.id
    keep = to_hand(state, BEAR)
    _cast(state, printing("Gamble"), ["Mountain"])
    p = state.players[0]
    # Two cards were in hand (the Bear and the found Giant): one stays,
    # one is discarded (with Gamble itself in the graveyard too).
    assert len(p.hand) == 1 and p.hand[0] in (keep, target)
    discarded = keep if p.hand[0] is target else target
    assert discarded in p.graveyard
    assert len(p.library) == 3


def test_gamble_with_empty_library_still_discards():
    state = arena()
    keep = to_hand(state, BEAR)
    _cast(state, printing("Gamble"), ["Mountain"])
    assert keep in state.players[0].graveyard


# --- Fabled Passage -----------------------------------------------------------

def _crack(state, land_obj, pid=0, idx=0):
    apply(state, ActivateAbility(source_id=land_obj.id, ability_index=idx), pid)
    drain_stack(state)


@pytest.mark.parametrize("other_lands, untapped", [(2, False), (3, True)])
def test_fabled_passage_untaps_with_four_lands(other_lands, untapped):
    state = arena()
    for _ in range(other_lands):
        put(state, BASIC_LANDS["Plains"])
    forest = to_library(state, BASIC_LANDS["Forest"])
    to_library(state, BEAR)
    passage = put(state, printing("Fabled Passage"))
    _crack(state, passage)
    assert passage not in state.battlefield
    assert forest in state.battlefield
    assert forest.tapped is (not untapped)


def test_fabled_passage_finds_nothing():
    state = arena()
    to_library(state, BEAR)
    passage = put(state, printing("Fabled Passage"))
    _crack(state, passage)
    assert _names(state.players[0].library) == ["Test Bear"]


# --- Ghost Quarter ------------------------------------------------------------

def test_ghost_quarter_destroys_and_controller_may_fetch_untapped():
    state = arena()
    target = put(state, BASIC_LANDS["Island"], 1)
    swamp = to_library(state, BASIC_LANDS["Swamp"], owner=1)
    quarter = put(state, printing("Ghost Quarter"))
    agent(state).targets = [("permanent", target.id)]
    _crack(state, quarter, idx=1)
    assert target not in state.battlefield and quarter not in state.battlefield
    assert swamp in state.battlefield and not swamp.tapped
    assert swamp.controller_id == 1


def test_ghost_quarter_controller_may_decline():
    state = arena()
    target = put(state, BASIC_LANDS["Island"], 1)
    to_library(state, BASIC_LANDS["Swamp"], owner=1)
    agent(state, 1).yes = False
    quarter = put(state, printing("Ghost Quarter"))
    agent(state).targets = [("permanent", target.id)]
    _crack(state, quarter, idx=1)
    assert len(state.players[1].library) == 1


def test_ghost_quarter_rider_tapped_variant_and_lost_player():
    eff = parse_roto_zones_effect(
        "exile target land. Its controller may search their library for a "
        "basic land card, put it onto the battlefield tapped, then shuffle"
    )
    assert eff.rider.tapped and "tapped" in eff.describe()
    state = arena()
    target = put(state, BASIC_LANDS["Island"], 1)
    swamp = to_library(state, BASIC_LANDS["Swamp"], owner=1)
    eff.resolve(state, 0, (("permanent", target.id),))
    assert swamp.tapped
    state = arena()
    target = put(state, BASIC_LANDS["Island"], 1)
    to_library(state, BASIC_LANDS["Swamp"], owner=1)
    state.players[1].has_lost = True
    eff.resolve(state, 0, (("permanent", target.id),))
    assert len(state.players[1].library) == 1


# --- Protean Hulk -------------------------------------------------------------

def test_protean_hulk_fetches_creatures_within_total_mana_value():
    state = arena()
    ogre = to_library(state, OGRE)       # 3
    bear = to_library(state, BEAR)       # 2
    elf = to_library(state, ELF)         # 1
    to_library(state, GIANT)             # 5: over budget after the others
    to_library(state, BASIC_LANDS["Forest"])
    hulk = put(state, printing("Protean Hulk"))
    move_off_battlefield(state, hulk, "graveyard")
    drain_stack(state)
    for c in (ogre, bear, elf):
        assert c in state.battlefield
    assert _names(state.players[0].library) == ["Forest", "Test Giant"]


def test_protean_hulk_stops_when_searcher_declines():
    state = arena()
    to_library(state, BEAR)
    agent(state).library_pick = None
    hulk = put(state, printing("Protean Hulk"))
    move_off_battlefield(state, hulk, "graveyard")
    drain_stack(state)
    assert len(state.players[0].library) == 1
    assert "creature cards with total mana value 6" in (
        printing("Protean Hulk").triggered_abilities[0].effect.describe()
    )


# --- Academy Rector / Arena Rector ---------------------------------------------

ORB = make_enchantment("Test Orb", "{3}")
WALKER = make_planeswalker("Test Walker", "{3}", 3, "Test")


@pytest.mark.parametrize("name, card", [
    ("Academy Rector", ORB), ("Arena Rector", WALKER),
])
def test_rector_exiles_itself_to_fetch(name, card):
    state = arena()
    found = to_library(state, card)
    to_library(state, BEAR)
    rector = put(state, printing(name))
    move_off_battlefield(state, rector, "graveyard")
    drain_stack(state)
    assert found in state.battlefield
    assert rector in state.players[0].exile


def test_rector_declined_stays_in_graveyard():
    state = arena()
    to_library(state, ORB)
    agent(state).yes = False
    rector = put(state, printing("Academy Rector"))
    move_off_battlefield(state, rector, "graveyard")
    drain_stack(state)
    assert rector in state.players[0].graveyard
    assert len(state.players[0].library) == 1


def test_rector_that_left_the_graveyard_fetches_nothing():
    state = arena()
    to_library(state, ORB)
    rector = put(state, printing("Academy Rector"))
    move_off_battlefield(state, rector, "graveyard")
    # Gone before the trigger resolves: can't exile it, so no search.
    p = state.players[0]
    p.graveyard.remove(rector)
    rector.zone = Zone.HAND
    p.hand.append(rector)
    drain_stack(state)
    assert len(p.library) == 1


def test_exile_source_card_without_a_source():
    state = arena()
    assert ExileSourceCardFromGraveyard().resolve(state, 0) is False
    assert ExileSourceCardFromGraveyard().describe() == "exile it"
    card = to_graveyard(state, BEAR)
    state.resolving_source = card
    assert ExileSourceCardFromGraveyard().resolve(state, 0) is True
    assert card in state.players[0].exile
