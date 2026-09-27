"""PowerLSV cube: Staff of the Storyteller, Currency Converter, Sword of
the Meek, Pentad Prism — plus the creature-token-created batch event,
the card-aware discard event, graveyard-functioning triggers and
Sunburst."""

from __future__ import annotations

import pytest

from mtg_bot import apply, legal_moves
from mtg_bot.actions import (
    ActivateAbility,
    CastSpell,
    drain_stack,
    max_distinct_colors,
    put_into_battlefield,
    resolve_top_of_stack,
)
from mtg_bot.cards import BASIC_LANDS, make_creature
from mtg_bot.cards.base import make_artifact, make_sorcery
from mtg_bot.cards.parser.effects import _parse_effect
from mtg_bot.cards.tokens import TOKEN_PRINTINGS
from mtg_bot.effects.generic import (
    CreateToken,
    DiscardSelf,
    GainLife,
    MayExileThatCardFromYourGraveyard,
    ReturnExiledWithSourceToGraveyardThenToken,
    ReturnThisCardFromGraveyardThenAttachToThatCreature,
)
from mtg_bot.effects.object_predicates import HasPowerToughness
from mtg_bot.game import ManaCoin, Zone, counter_count
from mtg_bot.turn import fire_opponent_discards_triggers

from tests._cube_artifact_helpers import (
    agent,
    arena,
    build_ok,
    put,
    to_graveyard,
    to_hand,
    to_library,
)


def _activate(state, obj, idx, pid=0):
    apply(state, ActivateAbility(source_id=obj.id, ability_index=idx), pid)


def _enter(state, printing, controller=0):
    obj = state.new_object(printing, owner_id=controller, zone=Zone.STACK)
    put_into_battlefield(state, obj, controller)
    return obj


# --- Staff of the Storyteller ---------------------------------------------

def test_staff_counts_token_batches():
    state = arena()
    staff = _enter(state, build_ok("Staff of the Storyteller"))
    drain_stack(state)
    # Its own Spirit token counts.
    assert counter_count(staff, "story") == 1
    spirit = next(o for o in state.battlefield if o.printing.name == "Spirit")
    assert "flying" in spirit.printing.keywords
    # One resolution creating two tokens -> one counter.
    two_bears = make_sorcery(
        "Test Twins", "{0}",
        _parse_effect("create two 2/2 green Bear creature tokens"),
    )
    card = to_hand(state, two_bears)
    apply(state, CastSpell(card_id=card.id), 0)
    drain_stack(state)
    assert counter_count(staff, "story") == 2
    # Noncreature tokens don't count.
    treasure_maker = make_sorcery(
        "Test Treasure", "{0}", CreateToken(TOKEN_PRINTINGS["Treasure"]),
    )
    card = to_hand(state, treasure_maker)
    apply(state, CastSpell(card_id=card.id), 0)
    drain_stack(state)
    assert counter_count(staff, "story") == 2
    # Spend a story counter to draw.
    to_library(state, BASIC_LANDS["Plains"])
    put(state, BASIC_LANDS["Plains"])
    _activate(state, staff, 0)
    resolve_top_of_stack(state)
    assert counter_count(staff, "story") == 1
    assert len(state.players[0].hand) == 1


def test_opponents_tokens_do_not_count():
    state = arena()
    staff = put(state, build_ok("Staff of the Storyteller"))
    theirs = make_sorcery(
        "Test Their Bear", "{0}",
        _parse_effect("create a 2/2 green Bear creature token"),
    )
    card = to_hand(state, theirs, owner=1)
    state.active_player_idx = 1
    state.priority_player_idx = 1
    apply(state, CastSpell(card_id=card.id), 1)
    drain_stack(state)
    assert counter_count(staff, "story") == 0


# --- Currency Converter ---------------------------------------------------

def test_currency_converter_exiles_discards_and_makes_tokens():
    state = arena()
    conv = put(state, build_ok("Currency Converter"))
    for _ in range(2):
        put(state, BASIC_LANDS["Swamp"])
    to_library(state, BASIC_LANDS["Swamp"])
    land = to_hand(state, BASIC_LANDS["Forest"])
    spell = to_hand(state, make_creature("Guy", "{2}", 2, 2))
    agent(state).discards = [land.id]
    _activate(state, conv, 0)
    resolve_top_of_stack(state)  # draw, then discard the Forest
    drain_stack(state)  # the discard trigger: exile it
    assert land.zone == Zone.EXILE
    assert land.imprinted_on == (conv.id, conv.etb_timestamp)
    conv.tapped = False
    _activate(state, conv, 1)
    resolve_top_of_stack(state)
    assert land.zone == Zone.GRAVEYARD
    assert any(o.printing.name == "Treasure" for o in state.battlefield)
    # A nonland card makes a 2/2 Rogue.
    state.resolving_source = conv
    DiscardSelf(amount=1).resolve(state, 0)
    state.resolving_source = None
    drain_stack(state)
    assert spell.zone == Zone.EXILE
    conv.tapped = False
    _activate(state, conv, 1)
    resolve_top_of_stack(state)
    rogue = next(o for o in state.battlefield if o.printing.name == "Rogue")
    assert (rogue.printing.power, rogue.printing.toughness) == (2, 2)


def test_currency_converter_may_decline_and_opponent_discards_ignored():
    state = arena()
    conv = put(state, build_ok("Currency Converter"))
    card = to_graveyard(state, BASIC_LANDS["Forest"])
    agent(state).yes = False
    fire_opponent_discards_triggers(state, 0, card=card)
    drain_stack(state)
    assert card.zone == Zone.GRAVEYARD
    their = to_graveyard(state, BASIC_LANDS["Forest"], owner=1)
    fire_opponent_discards_triggers(state, 1, card=their)
    assert not state.stack
    # With nothing exiled, the {T} ability does nothing.
    conv.tapped = False
    _activate(state, conv, 1)
    resolve_top_of_stack(state)
    assert not any(o.printing.is_token for o in state.battlefield)


def test_exiled_with_effect_edge_cases():
    state = arena()
    MayExileThatCardFromYourGraveyard().resolve(state, 0, (("player", 1),))
    ReturnExiledWithSourceToGraveyardThenToken(
        GainLife(1), GainLife(2),
    ).resolve(state, 0)
    src = put(state, build_ok("Currency Converter"))
    state.resolving_source = src
    MayExileThatCardFromYourGraveyard().resolve(state, 0, ())
    MayExileThatCardFromYourGraveyard().resolve(
        state, 0, (("card_in_graveyard", 999),),
    )
    a = to_graveyard(state, BASIC_LANDS["Forest"])
    b = to_graveyard(state, make_creature("X", "{1}", 1, 1))
    state.players[0].agent = None
    MayExileThatCardFromYourGraveyard().resolve(
        state, 0, (("card_in_graveyard", a.id),),
    )
    MayExileThatCardFromYourGraveyard().resolve(
        state, 0, (("card_in_graveyard", b.id),),
    )
    eff = ReturnExiledWithSourceToGraveyardThenToken(GainLife(1), GainLife(5))
    state.players[0].agent = agent(state, 1)  # multi-card choice path
    agent(state, 0).library_pick = b.id
    eff.resolve(state, 0)
    assert b.zone == Zone.GRAVEYARD and state.players[0].life == 25
    assert eff.describe() and MayExileThatCardFromYourGraveyard().describe()


def test_currency_converter_bodies_reject_targeted_or_unknown():
    assert _parse_effect(
        "put a card exiled with this artifact into its owner's graveyard. "
        "If it's a land card, frobnicate. If it's a nonland card, draw a card"
    ) is None
    assert _parse_effect(
        "put a card exiled with this artifact into its owner's graveyard. "
        "If it's a land card, destroy target creature. If it's a nonland "
        "card, draw a card"
    ) is None


# --- Sword of the Meek ----------------------------------------------------

def test_sword_of_the_meek_returns_and_attaches_to_a_1_1():
    state = arena()
    sword = to_graveyard(state, build_ok("Sword of the Meek"))
    assert build_ok("Sword of the Meek").has_graveyard_triggers
    token = _parse_effect("create a 1/1 colorless Thopter artifact creature token with flying")
    maker = make_sorcery("Test Thopter", "{0}", token)
    card = to_hand(state, maker)
    apply(state, CastSpell(card_id=card.id), 0)
    drain_stack(state)
    thopter = next(o for o in state.battlefield if o.printing.name == "Thopter")
    assert sword in state.battlefield
    assert sword.attached_to == thopter.id


def test_sword_of_the_meek_ignores_non_1_1_and_battlefield_copy():
    state = arena()
    sword_printing = build_ok("Sword of the Meek")
    on_bf = put(state, sword_printing)
    bear = _enter(state, make_creature("Bear", "{1}", 2, 2))
    drain_stack(state)
    assert on_bf.attached_to is None
    in_gy = to_graveyard(state, sword_printing)
    _enter(state, make_creature("Big", "{3}", 3, 3))
    drain_stack(state)
    assert in_gy.zone == Zone.GRAVEYARD
    agent(state).yes = False
    _enter(state, make_creature("Elf", "{G}", 1, 1))
    drain_stack(state)
    assert in_gy.zone == Zone.GRAVEYARD
    assert bear in state.battlefield


def test_sword_return_edge_cases():
    state = arena()
    eff = ReturnThisCardFromGraveyardThenAttachToThatCreature()
    eff.resolve(state, 0)  # no source
    sword = to_graveyard(state, build_ok("Sword of the Meek"))
    state.resolving_source = sword
    eff.resolve(state, 0, ())  # returns, nothing to attach
    assert sword in state.battlefield and sword.attached_to is None
    eff.resolve(state, 0, ())  # not in graveyard anymore: no-op
    sword2 = to_graveyard(state, build_ok("Sword of the Meek"))
    state.resolving_source = sword2
    eff.resolve(state, 0, (("creature", 999),))
    assert sword2.attached_to is None
    assert eff.describe()
    assert not HasPowerToughness(1, 1).test(state.players[0], state)


# --- Pentad Prism / Sunburst ----------------------------------------------

def test_max_distinct_colors_matching():
    W, U = frozenset({"W"}), frozenset({"U"})
    WU = frozenset({"W", "U"})
    assert max_distinct_colors([]) == 0
    assert max_distinct_colors([W, W]) == 1
    assert max_distinct_colors([WU, W]) == 2
    assert max_distinct_colors([frozenset(), WU]) == 1


def test_pentad_prism_sunburst_counts_colors_spent():
    state = arena()
    prism = to_hand(state, build_ok("Pentad Prism"))
    put(state, BASIC_LANDS["Island"])
    state.players[0].mana_pool.append(ManaCoin(color="R"))
    apply(state, CastSpell(card_id=prism.id), 0)
    drain_stack(state)
    assert prism in state.battlefield
    assert counter_count(prism, "charge") == 2
    agent(state).colors = ["G"]
    _activate(state, prism, 0)
    assert [c.color for c in state.players[0].mana_pool] == ["any"]
    assert counter_count(prism, "charge") == 1


def test_pentad_prism_colorless_mana_gives_no_counters():
    state = arena()
    prism = to_hand(state, build_ok("Pentad Prism"))
    state.players[0].mana_pool.extend([ManaCoin(color="C"), ManaCoin(color="C")])
    apply(state, CastSpell(card_id=prism.id), 0)
    drain_stack(state)
    assert counter_count(prism, "charge") == 0
    assert not any(
        a.source_id == prism.id for a in legal_moves(state, 0)
        if isinstance(a, ActivateAbility)
    )


def test_sunburst_creature_gets_plus_one_counters():
    from dataclasses import replace
    state = arena()
    guy = replace(make_creature("Test Sun Guy", "{1}{W}", 0, 0), sunburst=True)
    card = to_hand(state, guy)
    put(state, BASIC_LANDS["Plains"])
    state.players[0].mana_pool.append(ManaCoin(color="R"))
    apply(state, CastSpell(card_id=card.id), 0)
    drain_stack(state)
    assert card.plus_one_counters == 2  # W from the Plains, R from the pool


def test_sunburst_not_cast_means_no_counters():
    state = arena()
    prism = _enter(state, build_ok("Pentad Prism"))
    assert counter_count(prism, "charge") == 0
