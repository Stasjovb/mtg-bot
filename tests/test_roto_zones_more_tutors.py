"""Vintage Roto P2: Beseech the Mirror (bargain), Birthing Pod, Oswald
Fiddlebender, Survival of the Fittest, Scapeshift, Finale of Devastation,
Gifts Ungiven, Doomsday, Show and Tell, Eureka and Stronghold Gambit."""

from __future__ import annotations

from mtg_bot import apply, legal_moves
from mtg_bot.actions import ActivateAbility, CastSpell, drain_stack
from mtg_bot.cards import BASIC_LANDS, make_creature
from mtg_bot.cards.base import make_artifact, make_enchantment, make_sorcery
from mtg_bot.cards.parser.roto_zones import (
    _type_list_filter,
    parse_roto_zones_cost_piece,
    parse_roto_zones_effect,
)
from mtg_bot.cards.tokens import TOKEN_PRINTINGS
from mtg_bot.effects.generic import DrawCards
from mtg_bot.effects.generic.roto_zones import (
    Bargain,
    DiscardCardCost,
    DoomsdayPile,
    EachPlayerChoosesLowestCreatureEnters,
    EachPlayerMayPutFromHand,
    EurekaLoop,
    SacrificeLandsSearchThatMany,
    SearchDifferentNamesOpponentSplits,
    SearchExileFaceDownCastFreeIfBargained,
    SearchLibraryAndOrGraveyardXThenPump,
    SearchManaValueOnePlusSacrificed,
)
from mtg_bot.game import Zone, effective_power

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
GIANT = make_creature("Test Giant", "{4}{G}", 5, 5)
RELIC = make_artifact("Test Relic", "{1}")
ORB = make_artifact("Test Orb", "{2}")
AURA = make_enchantment("Test Aura", "{1}")
DIG = make_sorcery("Test Dig", "{1}", DrawCards(amount=2))


def _names(zone):
    return [c.printing.name for c in zone]


def _cast(state, pr, lands, pid=0, **kw):
    for land in lands:
        put(state, BASIC_LANDS[land], pid)
    card = to_hand(state, pr, owner=pid)
    apply(state, CastSpell(card_id=card.id, **kw), pid)
    drain_stack(state)
    return card


# --- Beseech the Mirror (bargain) ----------------------------------------------------

def test_beseech_bargained_casts_a_cheap_card_free():
    state = arena()
    relic = put(state, RELIC)
    dig = to_library(state, DIG)
    to_library(state, ELF)
    to_library(state, ELF)
    agent(state).library_pick = dig.id
    beseech = _cast(state, printing("Beseech the Mirror"), ["Swamp"] * 4)
    assert relic in state.players[0].graveyard        # bargained
    assert beseech in state.players[0].graveyard
    assert dig in state.players[0].graveyard          # cast free, resolved
    assert len(state.players[0].hand) == 2            # Test Dig drew two


def test_beseech_unbargained_puts_the_card_into_hand():
    state = arena()
    relic = put(state, RELIC)
    dig = to_library(state, DIG)
    agent(state).library_pick = dig.id
    agent(state).yes = False
    _cast(state, printing("Beseech the Mirror"), ["Swamp"] * 4)
    assert relic in state.battlefield
    assert dig in state.players[0].hand


def test_beseech_bargained_but_too_expensive_or_land():
    state = arena()
    tok = state.new_object(TOKEN_PRINTINGS["Treasure"], owner_id=0,
                           zone=Zone.BATTLEFIELD)
    state.battlefield.append(tok)
    giant = to_library(state, GIANT)
    agent(state).library_pick = giant.id
    _cast(state, printing("Beseech the Mirror"), ["Swamp"] * 4)
    assert tok not in state.battlefield
    assert giant in state.players[0].hand
    # No bargain fodder: nothing to sacrifice, the card goes to hand.
    state = arena()
    forest = to_library(state, BASIC_LANDS["Forest"])
    _cast(state, printing("Beseech the Mirror"), ["Swamp"] * 4)
    assert forest in state.players[0].hand


def test_bargain_options_and_effect_edges():
    state = arena()
    put(state, AURA)
    put(state, BEAR)
    assert _names(Bargain().options(state, 0)) == ["Test Aura"]
    assert Bargain().describe() == "bargain"
    eff = SearchExileFaceDownCastFreeIfBargained(max_mv=4)
    eff.resolve(state, 0)                       # empty library
    assert "bargained" in eff.describe()


# --- Birthing Pod / Oswald ----------------------------------------------------------------

def test_birthing_pod_fetches_mana_value_plus_one():
    state = arena()
    pod = put(state, printing("Birthing Pod"))
    for _ in range(2):
        put(state, BASIC_LANDS["Forest"])
    bear = put(state, BEAR)                       # MV 2
    ogre = to_library(state, OGRE)                # MV 3
    to_library(state, GIANT)
    apply(state, ActivateAbility(source_id=pod.id, ability_index=0), 0)
    drain_stack(state)
    assert bear in state.players[0].graveyard and ogre in state.battlefield


def test_oswald_swaps_artifacts():
    state = arena()
    oswald = put(state, printing("Oswald Fiddlebender"))
    put(state, BASIC_LANDS["Plains"])
    relic = put(state, RELIC)                     # MV 1
    orb = to_library(state, ORB)                  # MV 2
    apply(state, ActivateAbility(source_id=oswald.id, ability_index=0), 0)
    drain_stack(state)
    assert relic in state.players[0].graveyard and orb in state.battlefield


def test_mv_plus_sacrificed_without_paid_object_and_grammar():
    state = arena()
    to_library(state, ELF)
    eff = printing("Birthing Pod").activated_abilities[0].effect
    state.resolving_cost_paid_objects = ()
    eff.resolve(state, 0)                         # looks for MV 1
    assert any(o.printing.name == "Test Elf" for o in state.battlefield)
    assert "plus the sacrificed" in eff.describe()
    assert parse_roto_zones_effect(
        "search your library for a creature card with mana value equal to 1 "
        "plus the sacrificed artifact's mana value, put it onto the "
        "battlefield, then shuffle"
    ) is None


# --- Survival of the Fittest -------------------------------------------------------

def test_survival_discards_a_creature_to_tutor_one():
    state = arena()
    survival = put(state, printing("Survival of the Fittest"))
    put(state, BASIC_LANDS["Forest"])
    elf = to_hand(state, ELF)
    to_hand(state, DIG)
    giant = to_library(state, GIANT)
    apply(state, ActivateAbility(source_id=survival.id, ability_index=0), 0)
    drain_stack(state)
    p = state.players[0]
    assert elf in p.graveyard and giant in p.hand


def test_discard_card_cost_atom():
    atom = parse_roto_zones_cost_piece("Discard a creature card")
    assert isinstance(atom, DiscardCardCost)
    assert parse_roto_zones_cost_piece("Discard a card") is None
    assert parse_roto_zones_cost_piece("Discard a frob card") is None
    state = arena()
    to_hand(state, DIG)
    assert not atom.payable(state, 0, None)
    assert atom.describe() == "Discard a creature card"
    elf = to_hand(state, ELF)
    state.players[0].agent = None
    assert atom.pay(state, 0, None) == [elf]


# --- Scapeshift --------------------------------------------------------------------

def test_scapeshift_trades_lands():
    state = arena()
    lands = [put(state, BASIC_LANDS["Forest"]) for _ in range(4)]
    for _ in range(3):
        to_library(state, BASIC_LANDS["Mountain"])
    agent(state).x_value = 2
    _cast(state, printing("Scapeshift"), [])
    # Paid {2}{G}{G} with the four Forests (tapped), then sacrificed two.
    assert sum(l in state.battlefield for l in lands) == 2
    mountains = [o for o in state.battlefield if o.printing.name == "Mountain"]
    assert len(mountains) == 2 and all(m.tapped for m in mountains)


def test_scapeshift_with_no_lands():
    state = arena()
    SacrificeLandsSearchThatMany().resolve(state, 0)
    assert "any number of lands" in SacrificeLandsSearchThatMany().describe()


# --- Finale of Devastation -----------------------------------------------------------

def test_finale_finds_in_graveyard_without_searching_library():
    eff = printing("Finale of Devastation").spell_effect
    state = arena()
    ogre = to_graveyard(state, OGRE)
    to_library(state, BEAR)
    order = list(state.players[0].library)
    agent(state).yes = False
    state.resolving_x_value = 3
    eff.resolve(state, 0)
    assert ogre in state.battlefield
    assert state.players[0].library == order


def test_finale_big_x_pumps_and_hastes():
    eff = printing("Finale of Devastation").spell_effect
    state = arena()
    giant = to_library(state, GIANT)
    state.resolving_x_value = 10
    eff.resolve(state, 0)
    assert giant in state.battlefield
    assert effective_power(state, giant) == 15
    assert "+X/+X" in eff.describe()


# --- Gifts Ungiven -----------------------------------------------------------------

def test_gifts_ungiven_opponent_picks_two_for_the_graveyard():
    state = arena()
    cards = [to_library(state, pr) for pr in (BEAR, ELF, OGRE, GIANT)]
    to_library(state, BEAR)
    agent(state, 1).library_pick = "first"
    eff = printing("Gifts Ungiven").spell_effect
    eff.resolve(state, 0, (("player", 1),))
    p = state.players[0]
    assert len(p.graveyard) == 2 and len(p.hand) == 2
    assert {c.printing.name for c in p.graveyard + p.hand} == {
        c.printing.name for c in cards}
    assert eff.legal_targets(state, 0) == [("player", 1)]


def test_gifts_with_two_or_fewer_all_go_to_graveyard():
    state = arena()
    to_library(state, BEAR)
    to_library(state, BEAR)              # same name: only one can be found
    eff = SearchDifferentNamesOpponentSplits(count=4, opponent_picks=2)
    eff.resolve(state, 0, (("player", 1),))
    assert _names(state.players[0].graveyard) == ["Test Bear"]
    assert "different names" in eff.describe()


# --- Doomsday --------------------------------------------------------------------

def test_doomsday_builds_a_five_card_library():
    state = arena()
    lib = [to_library(state, ELF) for _ in range(6)]
    gy = [to_graveyard(state, BEAR) for _ in range(2)]
    picks = iter([gy[0].id, lib[3].id, lib[0].id, gy[1].id, lib[5].id])
    agent(state).choose_card_from_library = lambda s, p, ids: next(picks)
    DoomsdayPile(count=5).resolve(state, 0)
    p = state.players[0]
    assert [c.id for c in p.library] == [
        gy[0].id, lib[3].id, lib[0].id, gy[1].id, lib[5].id]
    assert p.graveyard == [] and len(p.exile) == 3
    assert p.life == 10


def test_doomsday_with_few_cards_keeps_them_all():
    state = arena()
    to_library(state, ELF)
    to_graveyard(state, BEAR)
    state.players[0].life = 7
    printing("Doomsday").spell_effect.resolve(state, 0)
    p = state.players[0]
    assert len(p.library) == 2 and p.life == 3
    assert "half your life" in DoomsdayPile().describe()


# --- Show and Tell / Eureka / Stronghold Gambit ---------------------------------------

def test_show_and_tell_each_player_puts_a_permanent():
    state = arena()
    giant = to_hand(state, GIANT)
    relic = to_hand(state, RELIC, owner=1)
    to_hand(state, DIG, owner=1)
    printing("Show and Tell").spell_effect.resolve(state, 0)
    assert giant in state.battlefield and relic in state.battlefield
    assert relic.controller_id == 1


def test_show_and_tell_players_may_decline():
    state = arena()
    to_hand(state, GIANT)
    agent(state).hand_pick = None
    EachPlayerMayPutFromHand(
        card_filter=_type_list_filter("artifact, creature, enchantment, or land"),
    ).resolve(state, 0)
    assert state.battlefield == []
    assert _type_list_filter("frob, or land") is None
    assert "from their hand" in EachPlayerMayPutFromHand().describe()


def test_eureka_repeats_until_nobody_puts():
    state = arena()
    to_hand(state, GIANT)
    to_hand(state, OGRE)
    to_hand(state, ELF, owner=1)
    to_hand(state, DIG, owner=1)
    EurekaLoop().resolve(state, 0)
    assert len(state.battlefield) == 3
    assert _names(state.players[1].hand) == ["Test Dig"]
    assert "repeat" in EurekaLoop().describe()


def test_stronghold_gambit_lowest_creature_enters():
    state = arena()
    elf = to_hand(state, ELF)
    bear = to_hand(state, BEAR, owner=1)
    EachPlayerChoosesLowestCreatureEnters().resolve(state, 0)
    assert elf in state.battlefield and bear in state.players[1].hand
    # Ties all enter; noncreature choices do nothing.
    state = arena()
    a = to_hand(state, BEAR)
    b = to_hand(state, BEAR, owner=1)
    EachPlayerChoosesLowestCreatureEnters().resolve(state, 0)
    assert a in state.battlefield and b in state.battlefield
    state = arena()
    to_hand(state, DIG)
    EachPlayerChoosesLowestCreatureEnters().resolve(state, 0)
    assert state.battlefield == []
    assert "lowest mana value" in EachPlayerChoosesLowestCreatureEnters().describe()


def test_search_and_or_graveyard_grammar_edges():
    assert parse_roto_zones_effect(
        "search your library and/or graveyard for a frob card with mana value "
        "X or less and put it onto the battlefield. If you search your library "
        "this way, shuffle. If X is 10 or more, creatures you control get "
        "+X/+X and gain haste until end of turn"
    ) is None
    assert parse_roto_zones_effect(
        "search your library for up to many cards with different names and "
        "reveal them. Target opponent chooses two of those cards. Put the "
        "chosen cards into your graveyard and the rest into your hand. Then "
        "shuffle"
    ) is None
    assert parse_roto_zones_effect(
        "search your library and graveyard for many cards and exile the rest. "
        "Put the chosen cards on top of your library in any order. You lose "
        "half your life, rounded up"
    ) is None
    assert parse_roto_zones_effect(
        "each player may put a frob card from their hand onto the battlefield"
    ) is None
    assert isinstance(
        SearchLibraryAndOrGraveyardXThenPump().describe(), str)
    assert isinstance(SearchManaValueOnePlusSacrificed().describe(), str)
