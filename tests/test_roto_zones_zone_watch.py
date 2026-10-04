"""Vintage Roto P2, F14 graveyard zone watch: Narcomoeba, Slogurk, the
Overslime, Kishla Skimmer and Gau, Feral Youth."""

from __future__ import annotations

from mtg_bot import apply
from mtg_bot.actions import ActivateAbility, CastSpell, drain_stack
from mtg_bot.cards import BASIC_LANDS, make_creature
from mtg_bot.cards.parser.roto_zones import _parse_zone_watch_line
from mtg_bot.effects.generic import DiscardSelf
from mtg_bot.effects.generic.roto_zones import (
    CardLeftYourGraveyardDuringYourTurn,
    CardLeftYourGraveyardThisTurn,
    LandCardPutIntoYourGraveyard,
    PutIntoYourGraveyardFromYourLibrary,
    ReturnSourceToOwnersHand,
    SelfDealsDamageEqualToPowerToEachOpponent,
    sweep_graveyard_zone_watch,
    zone_watch_active,
)
from mtg_bot.game import Zone, counter_count
from mtg_bot.turn import (
    draw_card,
    run_beginning_of_end_step_triggers,
    state_based_actions,
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


def _mill(state, pid, n):
    p = state.players[pid]
    for _ in range(n):
        c = p.library.pop(0)
        c.zone = Zone.GRAVEYARD
        p.graveyard.append(c)


def _settle(state):
    state_based_actions(state)
    drain_stack(state)
    state_based_actions(state)


# --- Narcomoeba ------------------------------------------------------------------------

def test_narcomoeba_milled_from_the_library_enters():
    state = arena()
    narco = to_library(state, printing("Narcomoeba"))
    to_library(state, ELF)
    state_based_actions(state)                 # baseline snapshot
    _mill(state, 0, 2)
    _settle(state)
    assert narco in state.battlefield


def test_narcomoeba_declined_or_drawn_and_discarded():
    state = arena()
    narco = to_library(state, printing("Narcomoeba"))
    agent(state).yes = False
    state_based_actions(state)
    _mill(state, 0, 1)
    _settle(state)
    assert narco in state.players[0].graveyard
    # Drawn, then discarded in the same resolution: not from the library.
    state = arena()
    narco = to_library(state, printing("Narcomoeba"))
    state_based_actions(state)
    draw_card(state, 0)
    DiscardSelf().resolve(state, 0)
    _settle(state)
    assert narco in state.players[0].graveyard


def test_narcomoeba_entombed_enters():
    state = arena()
    narco = to_library(state, printing("Narcomoeba"))
    state_based_actions(state)
    put(state, BASIC_LANDS["Swamp"])
    agent(state).library_pick = narco.id
    entomb = to_hand(state, printing("Entomb"))
    apply(state, CastSpell(card_id=entomb.id), 0)
    drain_stack(state)
    _settle(state)
    assert narco in state.battlefield


# --- Slogurk ----------------------------------------------------------------------------

def test_slogurk_grows_when_lands_hit_your_graveyard():
    state = arena()
    slogurk = put(state, printing("Slogurk, the Overslime"))
    state_based_actions(state)
    to_hand(state, BASIC_LANDS["Forest"])
    DiscardSelf().resolve(state, 0)
    _settle(state)
    assert counter_count(slogurk, "+1/+1") == 1
    # An opponent's land or a nonland card doesn't count.
    to_hand(state, BASIC_LANDS["Forest"], owner=1)
    DiscardSelf().resolve(state, 1)
    to_hand(state, ELF)
    DiscardSelf().resolve(state, 0)
    _settle(state)
    assert counter_count(slogurk, "+1/+1") == 1


def test_slogurk_returns_to_hand_for_three_counters():
    state = arena()
    slogurk = put(state, printing("Slogurk, the Overslime"))
    from mtg_bot.game import add_counters

    add_counters(state, slogurk, "+1/+1", 3)
    apply(state, ActivateAbility(source_id=slogurk.id, ability_index=0), 0)
    drain_stack(state)
    assert slogurk in state.players[0].hand
    ReturnSourceToOwnersHand().resolve(state, 0)      # source gone: no-op
    assert "owner's hand" in ReturnSourceToOwnersHand().describe()


# --- Kishla Skimmer ------------------------------------------------------------------------

def test_kishla_draws_once_per_turn_when_cards_leave_your_graveyard():
    state = arena()
    put(state, printing("Kishla Skimmer"))
    a = to_graveyard(state, ELF)
    b = to_graveyard(state, BEAR)
    for _ in range(3):
        to_library(state, ELF)
    state_based_actions(state)
    p = state.players[0]
    for card in (a, b):
        p.graveyard.remove(card)
        card.zone = Zone.EXILE
        p.exile.append(card)
        _settle(state)
    assert len(p.hand) == 1                  # only once each turn


def test_kishla_not_on_opponents_turn():
    state = arena(active=1)
    put(state, printing("Kishla Skimmer"))
    a = to_graveyard(state, ELF)
    to_library(state, ELF)
    state_based_actions(state)
    p = state.players[0]
    p.graveyard.remove(a)
    p.exile.append(a)
    _settle(state)
    assert p.hand == []
    assert p.card_left_graveyard_turn == state.turn_number


# --- Gau, Feral Youth -------------------------------------------------------------------------

def test_gau_end_step_burns_if_a_card_left_your_graveyard():
    pr = printing("Gau, Feral Youth")
    state = arena()
    gau = put(state, pr)
    run_beginning_of_end_step_triggers(state)
    drain_stack(state)
    assert state.players[1].life == 20
    a = to_graveyard(state, ELF)
    state_based_actions(state)
    p = state.players[0]
    p.graveyard.remove(a)
    p.exile.append(a)
    state_based_actions(state)
    run_beginning_of_end_step_triggers(state)
    drain_stack(state)
    assert state.players[1].life == 18
    assert gau in state.battlefield


def test_gau_rage_counter_and_effect_edges():
    pr = printing("Gau, Feral Youth")
    from mtg_bot.effects.predicates import Event

    attack = next(t for t in pr.triggered_abilities if t.event == Event.ATTACKS)
    state = arena()
    gau = put(state, pr)
    state.resolving_source = gau
    attack.effect.resolve(state, 0)
    assert counter_count(gau, "+1/+1") == 1
    state.resolving_source = None
    SelfDealsDamageEqualToPowerToEachOpponent().resolve(state, 0)
    assert "equal to its power" in (
        SelfDealsDamageEqualToPowerToEachOpponent().describe())


# --- watch plumbing ---------------------------------------------------------------------------

def test_zone_watch_is_off_without_watchers():
    state = arena()
    to_library(state, ELF)
    assert zone_watch_active(state) is False
    assert sweep_graveyard_zone_watch(state) is False
    assert state.players[0].zone_watch == ()


def test_watch_predicates_and_grammar():
    for cls in (PutIntoYourGraveyardFromYourLibrary, LandCardPutIntoYourGraveyard,
                CardLeftYourGraveyardDuringYourTurn):
        m = cls()
        assert m == cls() and not m.matches(None, {}, None)
        assert hash(m) == hash(cls.__name__) and cls.__name__ in repr(m)
    c = CardLeftYourGraveyardThisTurn()
    assert c == CardLeftYourGraveyardThisTurn() and not c.matches(None, {}, None)
    assert hash(c) and "ThisTurn" in repr(c)
    assert _parse_zone_watch_line(
        "Whenever a land card is put into your graveyard from anywhere, "
        "frobnicate.") is None
    assert _parse_zone_watch_line("Flying") is None
    assert _parse_zone_watch_line(
        "Frob: Return it to its owner's hand.") is None
