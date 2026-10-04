"""Vintage Roto P2, F16 hand disruption and symmetric attrition: Cabal
Therapy, Cabal Therapist, Kitesail Freebooter, Vendilion Clique,
Smallpox, Pox, Kroxa, Dreams of Steel and Oil, Sire of Insanity and Dread
Return (flashback paid by sacrifice)."""

from __future__ import annotations

from mtg_bot import apply, legal_moves
from mtg_bot.actions import CastSpell, drain_stack, put_into_battlefield
from mtg_bot.cards import BASIC_LANDS, make_creature
from mtg_bot.cards.base import make_artifact, make_sorcery
from mtg_bot.cards.parser.roto_zones import (
    _attrition_steps,
    parse_roto_zones_effect,
    roto_zones_casting_keyword_fields,
)
from mtg_bot.effects.generic import DrawCards
from mtg_bot.effects.generic.roto_zones import (
    A_THIRD,
    ChooseNameTargetDiscardsAllWithName,
    EachOpponentDiscardsLoseLifeUnlessNonland,
    EachPlayerSequence,
    FlashbackSacrificeCost,
    LookAtHandMayBottomCardThenDraw,
    RevealHandChooseExileUntilSourceLeaves,
    RevealHandChooseFromHandAndGraveyardExile,
    candidate_card_names,
    flashback_extra_costs_payable,
)
from mtg_bot.game import Zone
from mtg_bot.turn import (
    move_off_battlefield,
    run_beginning_of_end_step_triggers,
    run_beginning_of_precombat_main_triggers,
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
BOLT = make_sorcery("Test Bolt", "{R}", DrawCards(amount=1))
RELIC = make_artifact("Test Relic", "{1}")


def _enter(state, pr, controller=0):
    obj = state.new_object(pr, owner_id=controller, zone=Zone.STACK)
    put_into_battlefield(state, obj, controller)
    return obj


def _names(zone):
    return sorted(c.printing.name for c in zone)


def _name_pick(state, pid, name):
    agent(state, pid).choose_mode = lambda s, p, opts: opts.index(name)


# --- Kitesail Freebooter -----------------------------------------------------

def test_freebooter_exiles_noncreature_nonland_until_it_leaves():
    state = arena()
    to_hand(state, BEAR, owner=1)
    to_hand(state, BASIC_LANDS["Island"], owner=1)
    bolt = to_hand(state, BOLT, owner=1)
    agent(state).targets = [("player", 1)]
    boat = _enter(state, printing("Kitesail Freebooter"))
    drain_stack(state)
    assert bolt in state.players[1].exile
    assert all(0 in c.publicly_known_to for c in state.players[1].hand)
    move_off_battlefield(state, boat, "graveyard")
    assert bolt in state.players[1].hand


def test_freebooter_gone_before_resolution_exiles_nothing():
    state = arena()
    bolt = to_hand(state, BOLT, owner=1)
    boat = _enter(state, printing("Kitesail Freebooter"))
    move_off_battlefield(state, boat, "graveyard")
    drain_stack(state)
    assert bolt in state.players[1].hand


def test_freebooter_effect_edges():
    eff = RevealHandChooseExileUntilSourceLeaves()
    state = arena()
    assert eff.legal_targets(state, 0) == [("player", 1)]
    eff.resolve(state, 0, ())                      # no target
    to_hand(state, BASIC_LANDS["Island"], owner=1)
    boat = put(state, printing("Kitesail Freebooter"))
    state.resolving_source = boat
    eff2 = printing("Kitesail Freebooter").triggered_abilities[0].effect
    eff2.resolve(state, 0, (("player", 1),))     # only a land: nothing
    assert len(state.players[1].hand) == 1
    assert "until this creature leaves" in eff2.describe()
    assert "target player" in RevealHandChooseExileUntilSourceLeaves(
        opponent_only=False).describe()


# --- Vendilion Clique ---------------------------------------------------------

def test_clique_bottoms_a_nonland_card_and_they_draw():
    state = arena()
    bolt = to_hand(state, BOLT, owner=1)
    to_hand(state, BASIC_LANDS["Island"], owner=1)
    top = to_library(state, BEAR, owner=1)
    to_library(state, ELF, owner=1)
    agent(state).targets = [("player", 1)]
    _enter(state, printing("Vendilion Clique"))
    drain_stack(state)
    p1 = state.players[1]
    assert p1.library[-1] is bolt and top in p1.hand
    assert 1 in bolt.publicly_known_to and 0 in bolt.publicly_known_to


def test_clique_may_decline_and_needs_a_nonland_card():
    eff = LookAtHandMayBottomCardThenDraw(
        card_filter=printing("Vendilion Clique").triggered_abilities[0]
        .effect.card_filter,
    )
    state = arena()
    to_hand(state, BASIC_LANDS["Island"], owner=1)
    eff.resolve(state, 0, (("player", 1),))
    bolt = to_hand(state, BOLT, owner=1)
    agent(state).yes = False
    eff.resolve(state, 0, (("player", 1),))
    assert bolt in state.players[1].hand
    eff.resolve(state, 0, ())
    assert ("player", 0) in eff.legal_targets(state, 0)


# --- Smallpox / Pox -----------------------------------------------------------

def test_smallpox_each_player_in_order():
    state = arena()
    for pid in (0, 1):
        put(state, BEAR, pid)
        put(state, BASIC_LANDS["Swamp"], pid)
        put(state, BASIC_LANDS["Swamp"], pid)
        to_hand(state, ELF, owner=pid)
        to_hand(state, ELF, owner=pid)
    smallpox = to_hand(state, printing("Smallpox"))
    apply(state, CastSpell(card_id=smallpox.id), 0)
    drain_stack(state)
    for pid in (0, 1):
        p = state.players[pid]
        assert p.life == 19
        assert len(p.hand) == 1
        mine = [o for o in state.battlefield if o.controller_id == pid]
        assert not any(o.printing.name == "Test Bear" for o in mine)
    # P0 paid {B}{B} with its two Swamps, then sacrificed one of them.
    assert sum(o.printing.is_land for o in state.battlefield
               if o.controller_id == 1) == 1


def test_pox_takes_thirds_rounded_up():
    state = arena()
    p1 = state.players[1]
    p1.life = 10
    for _ in range(4):
        to_hand(state, ELF, owner=1)
        put(state, BASIC_LANDS["Swamp"], 1)
    put(state, BEAR, 1)
    EachPlayerSequence(steps=_attrition_steps(
        "loses a third of their life, then discards a third of the cards in "
        "their hand, then sacrifices a third of the creatures they control of "
        "their choice, then sacrifices a third of the lands they control of "
        "their choice"
    )).resolve(state, 0)
    assert p1.life == 6                       # 10 -> lose 4
    assert len(p1.hand) == 2                  # 4 -> discard 2
    assert sum(o.controller_id == 1 and o.printing.is_land
               for o in state.battlefield) == 2   # 4 -> sacrifice 2
    assert not any(o.printing.name == "Test Bear" for o in state.battlefield)


def test_pox_grammar_needs_round_up_sentence():
    pox = parse_roto_zones_effect(
        "each player loses a third of their life, then discards a third of "
        "the cards in their hand. Round up each time"
    )
    assert pox.steps == (("lose_life", A_THIRD), ("discard", A_THIRD))
    assert "a third of" in pox.describe()
    assert parse_roto_zones_effect(
        "each player loses a third of their life"
    ) is None
    assert parse_roto_zones_effect(
        "each player loses 1 life. Round up each time"
    ) is None
    assert _attrition_steps("loses 1 life, juggles") is None


def test_attrition_with_protected_player_and_empty_zones():
    state = arena()
    state.players[1].agent = None
    to_hand(state, ELF, owner=1)
    EachPlayerSequence(steps=(
        ("discard", 2), ("sacrifice_creature", 1), ("sacrifice_land", 1),
    )).resolve(state, 0)
    assert len(state.players[1].hand) == 0
    state.players[1].has_lost = True
    EachPlayerSequence(steps=(("lose_life", 1),)).resolve(state, 0)
    assert state.players[1].life == 20


def test_attrition_stops_when_protected():
    from mtg_bot.cards.base import CardPrinting  # noqa: F401
    import dataclasses

    state = arena()
    shield = dataclasses.replace(
        make_artifact("Test Shield", "{1}"),
        opponents_cant_make_you_discard_or_sacrifice=True,
    )
    put(state, shield, 1)
    put(state, BEAR, 1)
    to_hand(state, ELF, owner=1)
    state.resolving_item_controller_id = 0
    EachPlayerSequence(steps=(
        ("discard", 1), ("sacrifice_creature", 1),
    )).resolve(state, 0)
    assert len(state.players[1].hand) == 1
    assert any(o.printing.name == "Test Bear" for o in state.battlefield)


# --- Kroxa --------------------------------------------------------------------

def test_kroxa_life_loss_depends_on_the_discard():
    eff = EachOpponentDiscardsLoseLifeUnlessNonland(life=3)
    state = arena()
    to_hand(state, BOLT, owner=1)
    eff.resolve(state, 0)
    assert state.players[1].life == 20
    to_hand(state, BASIC_LANDS["Island"], owner=1)
    eff.resolve(state, 0)
    assert state.players[1].life == 17
    eff.resolve(state, 0)                      # empty hand
    assert state.players[1].life == 14
    assert "loses 3 life" in eff.describe()


def test_kroxa_enters_and_triggers():
    pr = printing("Kroxa, Titan of Death's Hunger")
    events = sorted(t.event.name for t in pr.triggered_abilities)
    assert events == ["ATTACKS", "ENTERS", "ENTERS"]


# --- Dreams of Steel and Oil ------------------------------------------------------

def test_dreams_exiles_from_hand_and_graveyard():
    state = arena()
    relic = to_hand(state, RELIC, owner=1)
    to_hand(state, BOLT, owner=1)
    bear = to_graveyard(state, BEAR, owner=1)
    to_graveyard(state, BOLT, owner=1)
    agent(state).targets = [("player", 1)]
    dreams = to_hand(state, printing("Dreams of Steel and Oil"))
    put(state, BASIC_LANDS["Swamp"])
    apply(state, CastSpell(card_id=dreams.id), 0)
    drain_stack(state)
    assert relic in state.players[1].exile and bear in state.players[1].exile
    assert _names(state.players[1].hand) == ["Test Bolt"]


def test_dreams_edges():
    eff = RevealHandChooseFromHandAndGraveyardExile()
    state = arena()
    eff.resolve(state, 0, ())
    assert eff.legal_targets(state, 0) == [("player", 1)]
    assert parse_roto_zones_effect(
        "target opponent reveals their hand. You choose an artifact card from "
        "it, then choose a creature card from their graveyard. Exile the "
        "chosen cards"
    ) is None


# --- Sire of Insanity -------------------------------------------------------------

def test_sire_of_insanity_end_step_discards_every_hand():
    state = arena()
    put(state, printing("Sire of Insanity"))
    to_hand(state, ELF)
    to_hand(state, ELF, owner=1)
    run_beginning_of_end_step_triggers(state)
    drain_stack(state)
    assert state.players[0].hand == [] == state.players[1].hand


# --- Cabal Therapy / Cabal Therapist ------------------------------------------------

def test_cabal_therapy_names_and_discards_all_copies():
    state = arena()
    a = to_hand(state, BOLT, owner=1)
    b = to_hand(state, BOLT, owner=1)
    elf = to_hand(state, ELF, owner=1)
    to_library(state, BEAR, owner=1)
    to_hand(state, BASIC_LANDS["Island"], owner=1)
    _name_pick(state, 0, "Test Bolt")
    agent(state).targets = [("player", 1)]
    therapy = to_hand(state, printing("Cabal Therapy"))
    put(state, BASIC_LANDS["Swamp"])
    apply(state, CastSpell(card_id=therapy.id), 0)
    drain_stack(state)
    assert a in state.players[1].graveyard and b in state.players[1].graveyard
    assert elf in state.players[1].hand
    assert therapy in state.players[0].graveyard


def test_candidate_names_are_nonland_cards_the_player_owns():
    state = arena()
    to_hand(state, BOLT, owner=1)
    to_library(state, BEAR, owner=1)
    to_graveyard(state, ELF, owner=1)
    to_hand(state, BASIC_LANDS["Island"], owner=1)
    to_hand(state, RELIC, owner=0)
    f = printing("Cabal Therapy").spell_effect.card_filter
    assert candidate_card_names(state, state.players[1], f) == [
        "Test Bear", "Test Bolt", "Test Elf",
    ]


def test_named_discard_with_no_names_or_target():
    eff = ChooseNameTargetDiscardsAllWithName()
    state = arena()
    eff.resolve(state, 0, ())
    eff.resolve(state, 0, (("player", 1),))
    assert ("player", 0) in eff.legal_targets(state, 0)
    assert "card name" in eff.describe()


def test_cabal_therapy_flashback_by_sacrificing_a_creature():
    pr = printing("Cabal Therapy")
    assert pr.flashback_cost is not None and pr.flashback_cost.total == 0
    assert pr.zone_abilities[0].count == 1
    state = arena()
    therapy = to_graveyard(state, pr)
    to_hand(state, BOLT, owner=1)
    # No creature: the flashback isn't offered.
    assert not any(
        isinstance(a, CastSpell) and a.use_flashback for a in legal_moves(state, 0)
    )
    bear = put(state, BEAR)
    assert CastSpell(therapy.id, use_flashback=True) in legal_moves(state, 0)
    _name_pick(state, 0, "Test Bolt")
    agent(state).targets = [("player", 1)]
    apply(state, CastSpell(therapy.id, use_flashback=True), 0)
    assert bear in state.players[0].graveyard
    drain_stack(state)
    assert therapy in state.players[0].exile
    assert _names(state.players[1].graveyard) == ["Test Bolt"]


def test_cabal_therapist_sacrifices_at_first_main_phase():
    state = arena()
    therapist = put(state, printing("Cabal Therapist"))
    bear = put(state, BEAR)
    bolt = to_hand(state, BOLT, owner=1)
    agent(state).sacrifices = [bear.id]
    agent(state).targets = [("player", 1)]
    _name_pick(state, 0, "Test Bolt")
    run_beginning_of_precombat_main_triggers(state)
    drain_stack(state)
    assert bear in state.players[0].graveyard and therapist in state.battlefield
    assert bolt in state.players[1].graveyard


# --- Dread Return -------------------------------------------------------------------

def test_dread_return_flashback_sacrifices_three_creatures():
    pr = printing("Dread Return")
    assert pr.zone_abilities == (FlashbackSacrificeCost(
        count=3, card_filter=pr.zone_abilities[0].card_filter),)
    state = arena()
    dread = to_graveyard(state, pr)
    target = to_graveyard(state, make_creature("Test Titan", "{6}", 6, 6))
    fodder = [put(state, ELF) for _ in range(2)]
    assert not flashback_extra_costs_payable(state, 0, dread)
    fodder.append(put(state, ELF))
    assert flashback_extra_costs_payable(state, 0, dread)
    agent(state).targets = [("card", target.id)]
    apply(state, CastSpell(dread.id, use_flashback=True), 0)
    drain_stack(state)
    assert all(f in state.players[0].graveyard for f in fodder)
    assert target in state.battlefield
    assert dread in state.players[0].exile
    assert "sacrifice 3" in pr.zone_abilities[0].describe()


def test_flashback_sacrifice_line_grammar():
    assert roto_zones_casting_keyword_fields("Flashback—Sacrifice two lands.")[
        "zone_abilities"][0].count == 2
    assert roto_zones_casting_keyword_fields(
        "Flashback—Sacrifice two creature.") is None
    assert roto_zones_casting_keyword_fields(
        "Flashback—Sacrifice a frobnicator.") is None
    assert roto_zones_casting_keyword_fields("Flashback {2}{R}") is None
