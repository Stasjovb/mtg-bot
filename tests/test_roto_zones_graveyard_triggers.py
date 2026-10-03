"""Vintage Roto P2: Bridge from Below (abilities that function in the
graveyard), Triumph of Saint Katherine, Scroll Rack, Winota, Joiner of
Forces and Deem Inferior."""

from __future__ import annotations

from mtg_bot import apply, legal_moves
from mtg_bot.actions import ActivateAbility, CastSpell, drain_stack
from mtg_bot.cards import BASIC_LANDS, make_creature
from mtg_bot.cards.base import make_sorcery
from mtg_bot.cards.parser.roto_zones import (
    _parse_graveyard_trigger_line,
    parse_roto_zones_creature_line,
    roto_zones_per_each_condition,
)
from mtg_bot.effects.generic import DrawCards
from mtg_bot.effects.generic.roto_zones import (
    AttackerYouControlWithoutSubtype,
    CreaturePutIntoGraveyardOf,
    ExileSelfAndTopNShuffleOnTop,
    IfSourceInGraveyard,
    PerCardDrawnThisTurn,
    ScrollRackSwap,
    SelfPutIntoYourGraveyard,
)
from mtg_bot.game import effective_keywords
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
ELF = make_creature("Test Elf", "{G}", 1, 1)
SOLDIER = make_creature("Test Soldier", "{W}", 1, 1)
DIG = make_sorcery("Test Dig", "{1}", DrawCards(amount=2))


def _names(zone):
    return [c.printing.name for c in zone]


def _zombies(state, pid=0):
    return [o for o in state.battlefield
            if o.printing.name == "Zombie" and o.controller_id == pid]


# --- Bridge from Below --------------------------------------------------------------

def test_bridge_makes_zombies_from_the_graveyard():
    state = arena()
    to_graveyard(state, printing("Bridge from Below"))
    bear = put(state, BEAR)
    move_off_battlefield(state, bear, "graveyard")
    drain_stack(state)
    assert len(_zombies(state)) == 1
    # Tokens dying don't count.
    move_off_battlefield(state, _zombies(state)[0], "graveyard")
    drain_stack(state)
    assert _zombies(state) == []


def test_bridge_exiles_itself_when_an_opponents_creature_dies():
    state = arena()
    bridge = to_graveyard(state, printing("Bridge from Below"))
    theirs = put(state, ELF, 1)
    move_off_battlefield(state, theirs, "graveyard")
    drain_stack(state)
    assert bridge in state.players[0].exile


def test_bridge_does_nothing_on_the_battlefield_or_after_leaving():
    state = arena()
    put(state, printing("Bridge from Below"))
    bear = put(state, BEAR)
    move_off_battlefield(state, bear, "graveyard")
    drain_stack(state)
    assert _zombies(state) == []
    state = arena()
    bridge = to_graveyard(state, printing("Bridge from Below"))
    bear = put(state, BEAR)
    move_off_battlefield(state, bear, "graveyard")
    p = state.players[0]
    p.graveyard.remove(bridge)
    p.exile.append(bridge)          # gone before the trigger resolves
    drain_stack(state)
    assert _zombies(state) == []


def test_creature_owned_by_you_but_controlled_by_them_feeds_your_bridge():
    state = arena()
    to_graveyard(state, printing("Bridge from Below"))
    stolen = put(state, BEAR, 1)
    stolen.owner_id = 0
    move_off_battlefield(state, stolen, "graveyard")
    drain_stack(state)
    assert len(_zombies(state)) == 1


def test_graveyard_trigger_predicates_and_grammar():
    pred = CreaturePutIntoGraveyardOf("yours", True)
    assert pred == CreaturePutIntoGraveyardOf("yours", True)
    assert hash(pred) == hash(("CreaturePutIntoGraveyardOf", "yours", True))
    assert "yours" in repr(pred)
    assert not pred.matches(None, {}, None)
    assert _parse_graveyard_trigger_line(
        "Whenever a creature is put into your graveyard from the battlefield, "
        "if this card is in your graveyard, frobnicate.") is None
    assert IfSourceInGraveyard(inner=DrawCards(amount=1)).describe().startswith(
        "if this card")


# --- Triumph of Saint Katherine -------------------------------------------------------

def test_triumph_shuffles_itself_into_the_top_seven():
    state = arena()
    lib = [to_library(state, ELF) for _ in range(8)]
    triumph = put(state, printing("Triumph of Saint Katherine"))
    move_off_battlefield(state, triumph, "graveyard")
    drain_stack(state)
    p = state.players[0]
    assert triumph in p.library[:7]
    assert set(c.id for c in p.library[:7]) == {triumph.id} | {
        c.id for c in lib[:6]}
    assert p.library[7:] == lib[6:]


def test_triumph_needs_six_cards_and_its_card():
    state = arena()
    for _ in range(5):
        to_library(state, ELF)
    triumph = put(state, printing("Triumph of Saint Katherine"))
    move_off_battlefield(state, triumph, "graveyard")
    drain_stack(state)
    assert triumph in state.players[0].graveyard
    ExileSelfAndTopNShuffleOnTop().resolve(state, 0)     # no source
    pred = SelfPutIntoYourGraveyard()
    assert pred == SelfPutIntoYourGraveyard() and "Self" in repr(pred)
    assert hash(pred) == hash("SelfPutIntoYourGraveyard")


def test_triumph_controlled_by_an_opponent_does_not_trigger():
    state = arena()
    for _ in range(6):
        to_library(state, ELF)
    triumph = put(state, printing("Triumph of Saint Katherine"), 1)
    triumph.owner_id = 0
    move_off_battlefield(state, triumph, "graveyard")
    drain_stack(state)
    assert triumph in state.players[0].graveyard


# --- Scroll Rack --------------------------------------------------------------------

def test_scroll_rack_swaps_hand_cards_with_the_top():
    state = arena()
    rack = put(state, printing("Scroll Rack"))
    put(state, BASIC_LANDS["Island"])
    a = to_hand(state, BEAR)
    b = to_hand(state, DIG)
    keep = to_hand(state, SOLDIER)
    tops = [to_library(state, ELF) for _ in range(3)]
    picks = iter([a.id, b.id, None])
    agent(state).choose_card_from_hand = lambda s, p, ids: next(picks)
    order = iter([b.id, a.id])
    agent(state).choose_card_from_library = lambda s, p, ids: next(order)
    apply(state, ActivateAbility(source_id=rack.id, ability_index=0), 0)
    drain_stack(state)
    p = state.players[0]
    assert keep in p.hand and tops[0] in p.hand and tops[1] in p.hand
    assert p.library[:3] == [b, a, tops[2]]


def test_scroll_rack_with_a_short_library():
    state = arena()
    a = to_hand(state, BEAR)
    state.players[0].agent.hand_pick = "first"
    picks = iter([a.id, None])
    agent(state).choose_card_from_hand = lambda s, p, ids: next(picks)
    ScrollRackSwap().resolve(state, 0)
    assert state.players[0].library == [a] and state.players[0].hand == []
    assert "any number" in ScrollRackSwap().describe()


# --- Winota, Joiner of Forces ----------------------------------------------------------

HUMAN = make_creature("Test Human", "{1}{W}", 2, 2, subtypes=("Human", "Soldier"))


def test_winota_puts_a_human_into_play_attacking():
    pr = printing("Winota, Joiner of Forces")
    state = arena()
    winota = put(state, pr)
    elf = put(state, ELF)
    human = to_library(state, HUMAN)
    for _ in range(6):
        to_library(state, BEAR)
    elf.attacking = True
    from mtg_bot.actions import dispatch_event
    from mtg_bot.effects.predicates import Event

    dispatch_event(state, Event.ATTACKS, label="attacks", attacker=elf)
    drain_stack(state)
    assert human in state.battlefield and human.attacking and human.tapped
    assert "indestructible" in effective_keywords(state, human)
    assert len(state.players[0].library) == 6
    # A Human attacking doesn't trigger it.
    pred = AttackerYouControlWithoutSubtype("Human")
    assert not pred.matches(state, {"attacker": human}, winota)
    assert pred == AttackerYouControlWithoutSubtype("Human")
    assert hash(pred) and "Human" in repr(pred)


def test_winota_may_find_nothing():
    pr = printing("Winota, Joiner of Forces")
    eff = pr.triggered_abilities[0].effect
    state = arena()
    for _ in range(3):
        to_library(state, BEAR)
    eff.resolve(state, 0)
    assert len(state.players[0].library) == 3
    assert "tapped and attacking" in eff.describe()
    assert parse_roto_zones_creature_line(
        "Whenever a non-Human creature you control attacks, frobnicate.",
        {"name": "X"},
    ) is None


# --- Deem Inferior ------------------------------------------------------------------

def test_deem_inferior_costs_less_per_card_drawn():
    pr = printing("Deem Inferior")
    state = arena()
    target = put(state, BEAR, 1)
    deem = to_hand(state, pr)
    put(state, BASIC_LANDS["Island"])
    assert CastSpell(card_id=deem.id) not in legal_moves(state, 0)
    state.players[0].cards_drawn_this_turn = 3
    assert CastSpell(card_id=deem.id) in legal_moves(state, 0)
    agent(state).targets = [("permanent", target.id)]
    agent(state, 1).yes = True
    apply(state, CastSpell(card_id=deem.id), 0)
    drain_stack(state)
    assert target in state.players[1].library
    cond = PerCardDrawnThisTurn()
    assert cond.multiplier(state, 0) == 3 and cond.matches(state, 0)
    assert cond.multiplier(state, 99) == 0
    assert roto_zones_per_each_condition("frob you control") is None
