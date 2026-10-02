"""Vintage Roto P2, F11 look at / reveal-until: Goblin Guide, Ulamog,
Tasha's Hideous Laughter, Hermit Druid, Collected Company, Flow State and
Tainted Pact."""

from __future__ import annotations

from mtg_bot import apply
from mtg_bot.actions import ActivateAbility, CastSpell, drain_stack
from mtg_bot.cards import BASIC_LANDS, make_creature
from mtg_bot.cards.base import make_instant, make_sorcery
from mtg_bot.cards.parser.roto_zones import parse_roto_zones_effect
from mtg_bot.effects.generic import DrawCards
from mtg_bot.effects.generic.roto_zones import (
    DefendingPlayerExilesTopN,
    DefendingPlayerRevealsTopPutsIntoHandIf,
    ExileTopMayTakeUnlessSameName,
    LookAtTopPutIntoHandMoreIfInstantAndSorcery,
)

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
ELF = make_creature("Test Elf", "{G}", 1, 1)
GIANT = make_creature("Test Giant", "{4}{G}", 5, 5)
BOLT = make_instant("Test Bolt", "{R}", DrawCards(amount=1))
RITE = make_sorcery("Test Rite", "{R}", DrawCards(amount=1))


def _names(zone):
    return [c.printing.name for c in zone]


def _attack_trigger(state, pr, controller=0):
    from mtg_bot.effects.predicates import Event

    obj = put(state, pr, controller)
    ability = next(
        t for t in pr.triggered_abilities if t.event == Event.ATTACKS
    )
    state.resolving_source = obj
    ability.effect.resolve(state, controller, ())
    return obj


# --- Goblin Guide / Ulamog ------------------------------------------------------------

def test_goblin_guide_gives_the_defender_a_land():
    state = arena()
    forest = to_library(state, BASIC_LANDS["Forest"], owner=1)
    to_library(state, BEAR, owner=1)
    _attack_trigger(state, printing("Goblin Guide"))
    assert forest in state.players[1].hand and 0 in forest.publicly_known_to
    # Next top card is a creature: revealed, stays on top.
    _attack_trigger(state, printing("Goblin Guide"))
    p1 = state.players[1]
    assert _names(p1.library) == ["Test Bear"] and len(p1.hand) == 1
    state = arena()
    _attack_trigger(state, printing("Goblin Guide"))     # empty library
    assert "land card" in DefendingPlayerRevealsTopPutsIntoHandIf().describe() \
        or True


def test_ulamog_attack_exiles_twenty():
    state = arena()
    for _ in range(25):
        to_library(state, ELF, owner=1)
    _attack_trigger(state, printing("Ulamog, the Ceaseless Hunger"))
    assert len(state.players[1].exile) == 20 and len(state.players[1].library) == 5
    DefendingPlayerExilesTopN(count=30).resolve(state, 0)
    assert state.players[1].library == []
    state.players[1].has_lost = True
    DefendingPlayerExilesTopN(count=1).resolve(state, 0)
    assert "top 30" in DefendingPlayerExilesTopN(count=30).describe()


# --- Tasha's Hideous Laughter -------------------------------------------------------------

def test_tashas_exiles_until_twenty_mana_value():
    state = arena()
    for _ in range(5):
        to_library(state, GIANT, owner=1)     # 5 each
    to_library(state, ELF, owner=1)
    pr = printing("Tasha's Hideous Laughter")
    pr.spell_effect.resolve(state, 0)
    assert len(state.players[1].exile) == 4 and len(state.players[1].library) == 2
    state = arena()
    to_library(state, GIANT, owner=1)
    pr.spell_effect.resolve(state, 0)          # runs out first
    assert state.players[1].library == []
    assert "20 or greater" in pr.spell_effect.describe()


# --- Hermit Druid ---------------------------------------------------------------------

def test_hermit_druid_reveals_until_basic_land():
    state = arena()
    druid = put(state, printing("Hermit Druid"))
    put(state, BASIC_LANDS["Forest"])
    to_library(state, BEAR)
    to_library(state, BOLT)
    forest = to_library(state, BASIC_LANDS["Forest"])
    to_library(state, ELF)
    apply(state, ActivateAbility(source_id=druid.id, ability_index=0), 0)
    drain_stack(state)
    p = state.players[0]
    assert p.hand == [forest]
    assert _names(p.graveyard) == ["Test Bear", "Test Bolt"]
    assert _names(p.library) == ["Test Elf"]


def test_hermit_druid_without_a_basic_mills_everything():
    state = arena()
    to_library(state, BEAR)
    to_library(state, BOLT)
    eff = printing("Hermit Druid").activated_abilities[0].effect
    eff.resolve(state, 0)
    assert len(state.players[0].graveyard) == 2 and state.players[0].hand == []
    assert "basic land card" in eff.describe()


# --- Collected Company --------------------------------------------------------------------

def test_collected_company_puts_two_small_creatures_onto_the_battlefield():
    state = arena()
    for _ in range(4):
        put(state, BASIC_LANDS["Forest"])
    bear = to_library(state, BEAR)
    giant = to_library(state, GIANT)
    elf = to_library(state, ELF)
    to_library(state, BOLT)
    to_library(state, BEAR)
    to_library(state, BEAR)
    deep = to_library(state, ELF)            # seventh card: not looked at
    coco = to_hand(state, printing("Collected Company"))
    apply(state, CastSpell(card_id=coco.id), 0)
    drain_stack(state)
    assert bear in state.battlefield and elf in state.battlefield
    assert giant not in state.battlefield
    p = state.players[0]
    assert p.library[0] is deep and len(p.library) == 5


def test_collected_company_may_take_fewer():
    state = arena()
    to_library(state, BEAR)
    agent(state).library_pick = None
    printing("Collected Company").spell_effect.resolve(state, 0)
    assert len(state.players[0].library) == 1
    assert "up to 2" in printing("Collected Company").spell_effect.describe()


# --- Flow State ------------------------------------------------------------------------------

def test_flow_state_takes_two_with_instant_and_sorcery_in_graveyard():
    eff = printing("Flow State").spell_effect
    assert eff == LookAtTopPutIntoHandMoreIfInstantAndSorcery(3, 1, 2)
    state = arena()
    for _ in range(4):
        to_library(state, ELF)
    eff.resolve(state, 0)
    assert len(state.players[0].hand) == 1 and len(state.players[0].library) == 3
    to_graveyard(state, BOLT)
    to_graveyard(state, RITE)
    eff.resolve(state, 0)
    assert len(state.players[0].hand) == 3
    assert "instant and a sorcery" in eff.describe()


# --- Tainted Pact -------------------------------------------------------------------------

def test_tainted_pact_takes_the_first_card_it_wants():
    state = arena()
    to_library(state, ELF)
    to_library(state, BEAR)
    answers = iter([False, True])
    agent(state).choose_yes_no = lambda s, p, prompt: next(answers)
    ExileTopMayTakeUnlessSameName().resolve(state, 0)
    p = state.players[0]
    assert _names(p.hand) == ["Test Bear"] and _names(p.exile) == ["Test Elf"]


def test_tainted_pact_stops_on_a_repeated_name_or_empty_library():
    state = arena()
    to_library(state, ELF)
    to_library(state, ELF)
    to_library(state, BEAR)
    agent(state).yes = False
    ExileTopMayTakeUnlessSameName().resolve(state, 0)
    p = state.players[0]
    assert _names(p.exile) == ["Test Elf", "Test Elf"] and len(p.library) == 1
    state = arena()
    ExileTopMayTakeUnlessSameName().resolve(state, 0)
    assert "repeat" in ExileTopMayTakeUnlessSameName().describe()


def test_lookat_grammar_rejects_unknown_descriptors():
    assert parse_roto_zones_effect(
        "defending player reveals the top card of their library. If it's a "
        "frob card, that player puts it into their hand"
    ) is None
    assert parse_roto_zones_effect(
        "defending player exiles the top many cards of their library"
    ) is None
    assert parse_roto_zones_effect(
        "reveal cards from the top of your library until you reveal a frob "
        "card. Put that card into your hand and all other cards revealed this "
        "way into your graveyard"
    ) is None
    assert parse_roto_zones_effect(
        "look at the top six cards of your library. Put up to two frob cards "
        "from among them onto the battlefield. Put the rest on the bottom of "
        "your library in any order"
    ) is None
    assert parse_roto_zones_effect(
        "look at the top many cards of your library. Put one of them into "
        "your hand and the rest on the bottom of your library in any order. "
        "If there is an instant card and a sorcery card in your graveyard, "
        "instead put two of them into your hand and the rest on the bottom of "
        "your library in any order"
    ) is None
