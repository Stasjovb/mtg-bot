"""Vintage Roto P2, F18 library-search hooks: Opposition Agent, Wan Shi
Tong, Librarian and Archive Trap -- against the base's own searches
(fetch lands, Demonic Tutor, Entomb) and P2's."""

from __future__ import annotations

from mtg_bot import apply, legal_moves
from mtg_bot.actions import (
    ActivateAbility,
    CastSpell,
    PlayLand,
    drain_stack,
    put_into_battlefield,
)
from mtg_bot.cards import BASIC_LANDS, make_creature
from mtg_bot.cards.parser.roto_zones import (
    parse_roto_zones_creature_line,
    parse_roto_zones_effect,
    roto_zones_casting_keyword_fields,
)
from mtg_bot.effects.generic.roto_search import (
    ControlSearchingOpponents,
    ExileFoundCardsForYou,
    OpponentSearchedLibrary,
    OpponentSearchedLibraryThisTurn,
    _ControlledSearchAgent,
    run_library_search,
    searched_card_taken,
)
from mtg_bot.effects.generic.roto_zones import (
    DoomsdayPile,
    PutXCountersOnSelfThenDrawHalfX,
)
from mtg_bot.game import Zone, counter_count

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
OGRE = make_creature("Test Ogre", "{2}{R}", 3, 3)


def _names(zone):
    return [c.printing.name for c in zone]


def _crack(state, obj, pid, idx=0):
    apply(state, ActivateAbility(source_id=obj.id, ability_index=idx), pid)
    drain_stack(state)


def _cast(state, pr, lands, pid):
    for land in lands:
        put(state, BASIC_LANDS[land], pid)
    card = to_hand(state, pr, owner=pid)
    apply(state, CastSpell(card_id=card.id), pid)
    drain_stack(state)
    return card


# --- Opposition Agent --------------------------------------------------------------

def test_opposition_agent_parses_both_statics():
    pr = printing("Opposition Agent")
    assert pr.zone_abilities == (ControlSearchingOpponents(), ExileFoundCardsForYou())
    assert "flash" in pr.keywords
    assert "searching" in ControlSearchingOpponents().describe()
    assert "play them" in ExileFoundCardsForYou().describe()


def test_fetch_land_into_opposition_agent_exiles_the_land_for_the_agent():
    state = arena(active=1)
    put(state, printing("Opposition Agent"), 0)
    delta = put(state, printing("Polluted Delta"), 1)
    island = to_library(state, BASIC_LANDS["Island"], owner=1)
    to_library(state, BASIC_LANDS["Swamp"], owner=1)
    agent(state, 0).library_pick = island.id
    _crack(state, delta, 1)
    assert island in state.players[1].exile
    assert island not in state.battlefield
    assert island.exile_play_permission.player_id == 0
    assert state.players[1].library_searched_turn == state.turn_number
    # The agent's controller may play it on their own turn.
    state.active_player_idx = 0
    state.priority_player_idx = 0
    assert any(
        isinstance(a, PlayLand) and a.card_id == island.id
        for a in legal_moves(state, 0)
    )


def test_opposition_agent_controls_the_search():
    state = arena(active=1)
    put(state, printing("Opposition Agent"), 0)
    to_library(state, OGRE, owner=1)
    bear = to_library(state, BEAR, owner=1)
    agent(state, 1).library_pick = "first"          # would take the Ogre
    agent(state, 0).library_pick = bear.id           # the agent picks
    _cast(state, printing("Demonic Tutor"), ["Swamp", "Swamp"], 1)
    assert bear in state.players[1].exile
    assert _names(state.players[1].library) == ["Test Ogre"]
    assert state.players[1].hand == []


def test_found_cards_may_be_cast_with_any_color_mana():
    state = arena(active=1)
    put(state, printing("Opposition Agent"), 0)
    bear = to_library(state, BEAR, owner=1)
    agent(state, 0).library_pick = bear.id
    _cast(state, printing("Demonic Tutor"), ["Swamp", "Swamp"], 1)
    state.active_player_idx = 0
    state.priority_player_idx = 0
    put(state, BASIC_LANDS["Mountain"], 0)
    put(state, BASIC_LANDS["Mountain"], 0)
    assert CastSpell(card_id=bear.id) in legal_moves(state, 0)
    apply(state, CastSpell(card_id=bear.id), 0)
    drain_stack(state)
    assert bear in state.battlefield and bear.controller_id == 0


def test_own_searches_and_entomb_destination():
    state = arena()
    put(state, printing("Opposition Agent"), 0)
    bear = to_library(state, BEAR, owner=0)
    _cast(state, printing("Demonic Tutor"), ["Swamp", "Swamp"], 0)
    assert bear in state.players[0].hand          # its controller's own search
    state = arena(active=1)
    put(state, printing("Opposition Agent"), 0)
    ogre = to_library(state, OGRE, owner=1)
    agent(state, 0).library_pick = ogre.id
    _cast(state, printing("Entomb"), ["Swamp"], 1)
    assert ogre in state.players[1].exile
    assert _names(state.players[1].graveyard) == ["Entomb"]


def test_doomsday_under_opposition_agent_exiles_the_pile():
    state = arena(active=1)
    put(state, printing("Opposition Agent"), 0)
    for _ in range(6):
        to_library(state, ELF, owner=1)
    to_graveyard(state, BEAR, owner=1)
    DoomsdayPile(count=5).resolve(state, 1)
    p1 = state.players[1]
    assert p1.library == [] and p1.graveyard == [] and len(p1.exile) == 7
    assert sum(c.exile_play_permission is not None for c in p1.exile) == 5


def test_search_hooks_edges():
    state = arena()
    card = to_library(state, BEAR, owner=1)
    assert searched_card_taken(state, 1, card) is False
    assert run_library_search(state, 0, lambda: 7) == 7
    proxy = _ControlledSearchAgent(agent(state, 1), agent(state, 0), 0)
    agent(state, 0).library_pick = card.id
    assert proxy.choose_card_from_library(state, 1, [card.id]) == card.id
    assert proxy.yes is True                       # delegated attribute
    # A wiped Opposition Agent does nothing.
    oa = put(state, printing("Opposition Agent"), 0)
    state.add_continuous_effect(
        source_id=oa.id, layer=6, kind="lose_all_abilities", target_id=oa.id,
    )
    assert searched_card_taken(state, 1, card) is False


# --- Wan Shi Tong, Librarian -----------------------------------------------------------

def test_wan_shi_tong_grows_when_an_opponent_searches():
    state = arena(active=1)
    wst = put(state, printing("Wan Shi Tong, Librarian"), 0)
    to_library(state, ELF, owner=0)
    to_library(state, BEAR, owner=1)
    _cast(state, printing("Demonic Tutor"), ["Swamp", "Swamp"], 1)
    assert counter_count(wst, "+1/+1") == 1
    assert _names(state.players[0].hand) == ["Test Elf"]
    # Its controller's own search doesn't trigger it.
    state.active_player_idx = 0
    to_library(state, OGRE, owner=0)
    _cast(state, printing("Demonic Tutor"), ["Swamp", "Swamp"], 0)
    assert counter_count(wst, "+1/+1") == 1


def test_wan_shi_tong_enters_with_x_counters_and_draws_half():
    state = arena()
    for _ in range(3):
        to_library(state, ELF)
    wst = state.new_object(printing("Wan Shi Tong, Librarian"), owner_id=0,
                           zone=Zone.STACK)
    state.resolving_spell = wst
    state.resolving_x_value = 5
    put_into_battlefield(state, wst, 0)
    state.resolving_spell = None
    drain_stack(state)
    assert counter_count(wst, "+1/+1") == 5
    assert len(state.players[0].hand) == 2
    state.resolving_source = None
    PutXCountersOnSelfThenDrawHalfX().resolve(state, 0)
    assert "half X" in PutXCountersOnSelfThenDrawHalfX().describe()


def test_search_trigger_marker_and_grammar():
    assert not OpponentSearchedLibrary().matches(None, {}, None)
    assert OpponentSearchedLibrary() == OpponentSearchedLibrary()
    assert hash(OpponentSearchedLibrary()) == hash("OpponentSearchedLibrary")
    assert "OpponentSearchedLibrary" in repr(OpponentSearchedLibrary())
    assert parse_roto_zones_creature_line(
        "Whenever an opponent searches their library, frobnicate.",
        {"name": "X"},
    ) is None


# --- Archive Trap ---------------------------------------------------------------------

def test_archive_trap_is_free_after_an_opponent_searched():
    pr = printing("Archive Trap")
    assert pr.free_cast_condition == OpponentSearchedLibraryThisTurn()
    state = arena()
    for _ in range(15):
        to_library(state, ELF, owner=1)
    cond = OpponentSearchedLibraryThisTurn()
    assert not cond.matches(state, 0)
    state.players[1].library_searched_turn = state.turn_number
    assert cond.matches(state, 0)
    trap = to_hand(state, pr)
    free = CastSpell(card_id=trap.id, cast_for_free=True)
    assert free in legal_moves(state, 0)
    agent(state).targets = [("player", 1)]
    apply(state, free, 0)
    drain_stack(state)
    assert len(state.players[1].graveyard) == 13
    state.turn_number += 1
    assert not cond.matches(state, 0)


def test_archive_trap_grammar_edges():
    assert roto_zones_casting_keyword_fields(
        "If an opponent drew a card this turn, you may pay {0} rather than "
        "pay this spell's mana cost."
    ) is None
    # Digit counts are the base mill grammar's; P2 only spells them out.
    assert parse_roto_zones_effect("target opponent mills 13 cards") is None
    assert parse_roto_zones_effect("target opponent mills many cards") is None
