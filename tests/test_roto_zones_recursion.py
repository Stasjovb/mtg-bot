"""Vintage Roto P2, F13 recursion and reanimation: Recurring Nightmare,
Takenuma, Cling to Dust, Deathrite Shaman, Noxious Revival, Persist,
Pre-War Formalwear, Reveillark and Sevinne's Reclamation."""

from __future__ import annotations

from mtg_bot import apply, legal_moves
from mtg_bot.actions import (
    ActivateAbility,
    CastSpell,
    drain_stack,
    put_into_battlefield,
)
from mtg_bot.cards import BASIC_LANDS, make_creature
from mtg_bot.cards.base import make_planeswalker, make_sorcery
from mtg_bot.cards.parser.roto_zones import (
    parse_roto_zones_cost_piece,
    parse_roto_zones_effect,
)
from mtg_bot.effects.generic import DrawCards, GainLife
from mtg_bot.effects.generic.roto_zones import (
    CopyIfCastFromGraveyard,
    ExileTargetGraveyardCardThen,
    MillThenReturnCardFromGraveyardToHand,
    PutTargetGraveyardCardOnTopOfLibrary,
    ReturnSelfToOwnersHandCost,
    ReturnTargetsFromYourGraveyardToBattlefield,
)
from mtg_bot.game import Zone, effective_power, effective_toughness
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
OGRE = make_creature("Test Ogre", "{2}{R}", 3, 3)
ELF = make_creature("Test Elf", "{G}", 1, 1)
LEGEND = make_creature("Test Legend", "{1}{B}", 2, 2, legendary=True)
WALKER = make_planeswalker("Test Walker", "{3}", 3, "Test")
BOLT = make_sorcery("Test Bolt", "{R}", DrawCards(amount=1))


def _enter(state, pr, controller=0):
    obj = state.new_object(pr, owner_id=controller, zone=Zone.STACK)
    put_into_battlefield(state, obj, controller)
    return obj


def _activate(state, obj, idx=0, pid=0):
    apply(state, ActivateAbility(source_id=obj.id, ability_index=idx), pid)
    drain_stack(state)


# --- Recurring Nightmare --------------------------------------------------------

def test_recurring_nightmare_sacrifices_and_returns_itself():
    state = arena()
    nightmare = put(state, printing("Recurring Nightmare"))
    fodder = put(state, ELF)
    target = to_graveyard(state, OGRE)
    agent(state).targets = [("card_in_graveyard", target.id)]
    _activate(state, nightmare)
    assert fodder in state.players[0].graveyard
    assert nightmare in state.players[0].hand
    assert target in state.battlefield


def test_recurring_nightmare_needs_a_creature_and_sorcery_timing():
    state = arena()
    nightmare = put(state, printing("Recurring Nightmare"))
    to_graveyard(state, OGRE)
    acts = [a for a in legal_moves(state, 0)
            if isinstance(a, ActivateAbility) and a.source_id == nightmare.id]
    assert acts == []
    put(state, ELF)
    acts = [a for a in legal_moves(state, 0)
            if isinstance(a, ActivateAbility) and a.source_id == nightmare.id]
    assert acts
    assert printing("Recurring Nightmare").activated_abilities[0].sorcery_speed


def test_return_self_cost_atom():
    atom = parse_roto_zones_cost_piece("Return this enchantment to its owner's hand")
    assert atom == ReturnSelfToOwnersHandCost()
    assert parse_roto_zones_cost_piece("Return a land you control") is None
    state = arena()
    assert not atom.payable(state, 0, None)
    assert "owner's hand" in atom.describe()


# --- Takenuma, Abandoned Mire ------------------------------------------------------

def test_takenuma_channel_mills_then_returns_a_creature():
    state = arena()
    for land in ("Swamp", "Swamp", "Swamp"):
        put(state, BASIC_LANDS[land])
    put(state, LEGEND)            # {1} less: {2}{B}
    ogre = to_library(state, OGRE)
    to_library(state, BOLT)
    to_library(state, BASIC_LANDS["Forest"])
    to_library(state, ELF)
    takenuma = to_hand(state, printing("Takenuma, Abandoned Mire"))
    agent(state).library_pick = ogre.id
    acts = [a for a in legal_moves(state, 0)
            if isinstance(a, ActivateAbility) and a.source_id == takenuma.id]
    assert acts
    apply(state, acts[0], 0)
    drain_stack(state)
    p = state.players[0]
    assert takenuma in p.graveyard
    assert ogre in p.hand
    assert [c.printing.name for c in p.library] == ["Test Elf"]


def test_mill_then_return_with_nothing_to_return():
    state = arena()
    to_library(state, BOLT)
    eff = MillThenReturnCardFromGraveyardToHand(
        count=3,
        card_filter=printing("Takenuma, Abandoned Mire")
        .hand_activated_abilities[0].effect.card_filter,
    )
    eff.resolve(state, 0)
    assert state.players[0].hand == []
    walker = to_graveyard(state, WALKER)
    state.players[0].agent = None
    eff.resolve(state, 0)
    assert walker in state.players[0].hand
    assert "planeswalker" in eff.describe()


def test_takenuma_mill_respects_rest_in_peace():
    state = arena()
    put(state, printing("Rest in Peace"))
    ogre = to_library(state, OGRE)
    MillThenReturnCardFromGraveyardToHand(count=1).resolve(state, 0)
    assert ogre in state.players[0].exile


# --- Cling to Dust ---------------------------------------------------------------

def test_cling_to_dust_creature_gains_life_otherwise_draws():
    state = arena()
    ogre = to_graveyard(state, OGRE, owner=1)
    bolt = to_graveyard(state, BOLT, owner=1)
    to_library(state, ELF)
    eff = printing("Cling to Dust").spell_effect
    eff.resolve(state, 0, (("card_in_graveyard", ogre.id),))
    assert ogre in state.players[1].exile and state.players[0].life == 23
    eff.resolve(state, 0, (("card_in_graveyard", bolt.id),))
    assert bolt in state.players[1].exile
    assert len(state.players[0].hand) == 1
    eff.resolve(state, 0, (("card_in_graveyard", bolt.id),))   # gone
    assert state.players[0].life == 23 and len(state.players[0].hand) == 1
    assert "otherwise" in eff.describe()


# --- Deathrite Shaman --------------------------------------------------------------

def test_deathrite_shaman_abilities():
    state = arena()
    shaman = put(state, printing("Deathrite Shaman"))
    land = to_graveyard(state, BASIC_LANDS["Forest"], owner=1)
    agent(state).targets = [("card_in_graveyard", land.id)]
    apply(state, ActivateAbility(source_id=shaman.id, ability_index=0), 0)
    drain_stack(state)
    assert land in state.players[1].exile
    # One mana of any color (the pool's any-color coin).
    assert [c.color for c in state.players[0].mana_pool] == ["any"]
    eff = printing("Deathrite Shaman").activated_abilities[1].effect
    bolt = to_graveyard(state, BOLT, owner=1)
    assert ("card_in_graveyard", bolt.id) in eff.legal_targets(state, 0)
    assert ("card_in_graveyard", land.id) not in eff.legal_targets(state, 0)
    eff.resolve(state, 0, (("card_in_graveyard", bolt.id),))
    assert state.players[1].life == 18
    eff3 = printing("Deathrite Shaman").activated_abilities[2].effect
    ogre = to_graveyard(state, OGRE, owner=1)
    eff3.resolve(state, 0, (("card_in_graveyard", ogre.id),))
    assert state.players[0].life == 22


def test_deathrite_target_gone_means_nothing_happens():
    state = arena()
    eff = printing("Deathrite Shaman").activated_abilities[1].effect
    eff.resolve(state, 0, (("card_in_graveyard", 999),))
    eff.resolve(state, 0, (("permanent", 1),))
    assert state.players[1].life == 20
    assert ExileTargetGraveyardCardThen().describe().startswith("exile target")


def test_deathrite_abilities_are_not_mana_abilities():
    for ab in printing("Deathrite Shaman").activated_abilities:
        assert not ab.is_mana_ability


# --- Noxious Revival -------------------------------------------------------------

def test_noxious_revival_puts_card_on_top_of_owners_library():
    state = arena()
    to_library(state, ELF, owner=1)
    ogre = to_graveyard(state, OGRE, owner=1)
    eff = printing("Noxious Revival").spell_effect
    assert eff == PutTargetGraveyardCardOnTopOfLibrary(card_filter=eff.card_filter)
    eff.resolve(state, 0, (("card_in_graveyard", ogre.id),))
    assert state.players[1].library[0] is ogre
    eff.resolve(state, 0, (("card_in_graveyard", ogre.id),))   # gone: no-op
    assert "on top of its owner's library" in eff.describe()


# --- Persist ------------------------------------------------------------------------

def test_persist_returns_nonlegendary_with_a_minus_counter():
    state = arena()
    ogre = to_graveyard(state, OGRE)
    legend = to_graveyard(state, LEGEND)
    elf = to_graveyard(state, ELF)
    eff = printing("Persist").spell_effect
    targets = eff.legal_targets(state, 0)
    assert ("card_in_graveyard", legend.id) not in targets
    eff.resolve(state, 0, (("card_in_graveyard", ogre.id),))
    assert ogre in state.battlefield and ogre.minus_one_counters == 1
    assert effective_power(state, ogre) == 2
    # A 1/1 dies to its own counter.
    eff.resolve(state, 0, (("card_in_graveyard", elf.id),))
    from mtg_bot.turn import state_based_actions

    state_based_actions(state)
    assert elf in state.players[0].graveyard
    assert "-1/-1 counter" in eff.describe()


# --- Pre-War Formalwear ----------------------------------------------------------------

def test_pre_war_formalwear_reanimates_and_attaches():
    state = arena()
    ogre = to_graveyard(state, OGRE)
    to_graveyard(state, make_creature("Test Big", "{5}", 5, 5))
    agent(state).targets = [("card_in_graveyard", ogre.id)]
    gear = _enter(state, printing("Pre-War Formalwear"))
    drain_stack(state)
    assert ogre in state.battlefield and gear.attached_to == ogre.id
    assert effective_power(state, ogre) == 5
    assert effective_toughness(state, ogre) == 5


def test_formalwear_gone_does_not_attach():
    state = arena()
    ogre = to_graveyard(state, OGRE)
    eff = printing("Pre-War Formalwear").triggered_abilities[0].effect
    state.resolving_source = None
    eff.resolve(state, 0, (("card_in_graveyard", ogre.id),))
    assert ogre in state.battlefield
    assert "attach" in eff.describe()


# --- Reveillark ---------------------------------------------------------------------

def test_reveillark_returns_up_to_two_small_creatures():
    state = arena()
    bear = to_graveyard(state, BEAR)
    elf = to_graveyard(state, ELF)
    ogre = to_graveyard(state, OGRE)
    eff = printing("Reveillark").triggered_abilities[0].effect
    assert eff.target_count_range() == (0, 2)
    assert ("card_in_graveyard", ogre.id) not in eff.legal_targets(state, 0)
    lark = put(state, printing("Reveillark"))
    agent(state).targets = [
        ("card_in_graveyard", bear.id), ("card_in_graveyard", elf.id),
    ]
    move_off_battlefield(state, lark, "graveyard")
    drain_stack(state)
    assert bear in state.battlefield and elf in state.battlefield
    assert ogre in state.players[0].graveyard
    assert "up to 2" in eff.describe()


def test_return_targets_dedupes_and_caps():
    state = arena()
    bear = to_graveyard(state, BEAR)
    eff = ReturnTargetsFromYourGraveyardToBattlefield(min_n=0, max_n=2)
    eff.resolve(state, 0, (
        ("card_in_graveyard", bear.id), ("card_in_graveyard", bear.id),
        ("permanent", 5),
    ))
    assert bear in state.battlefield
    assert not eff.requires_target()


# --- Sevinne's Reclamation ----------------------------------------------------------

def test_sevinnes_reclamation_copies_only_from_a_graveyard():
    pr = printing("Sevinne's Reclamation")
    assert isinstance(pr.spell_effect, CopyIfCastFromGraveyard)
    state = arena()
    for _ in range(5):
        put(state, BASIC_LANDS["Plains"])
    a = to_graveyard(state, BEAR)
    b = to_graveyard(state, ELF)
    rec = to_hand(state, pr)
    agent(state).targets = [("graveyard_card", a.id)]
    apply(state, CastSpell(card_id=rec.id), 0)
    drain_stack(state)
    assert a in state.battlefield and b in state.players[0].graveyard
    # Flashback from the graveyard: the copy returns the other card.
    agent(state).targets = [("graveyard_card", b.id)]
    apply(state, CastSpell(rec.id, use_flashback=True), 0)
    drain_stack(state)
    assert b in state.battlefield
    assert rec in state.players[0].exile


def test_copy_rider_declined_and_grammar():
    assert parse_roto_zones_effect(
        "draw a card. If this spell was cast from a graveyard, you may copy "
        "this spell and may choose a new target for the copy"
    ) is None
    eff = CopyIfCastFromGraveyard(inner=GainLife(amount=1))
    state = arena()
    eff.resolve(state, 0)       # no resolving spell: just the inner effect
    assert state.players[0].life == 21
    assert "cast from a graveyard" in eff.describe()
