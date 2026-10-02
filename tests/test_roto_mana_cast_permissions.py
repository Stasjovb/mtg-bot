"""Vintage Roto P3: cast permissions and free casts (Dreadhorde
Arcanist, ...)."""

from __future__ import annotations

from mtg_bot.actions import DeclareAttackers, apply_action, drain_stack
from mtg_bot.cards.base import make_creature
from mtg_bot.cards.parser.roto_mana import parse_roto_mana_effect
from mtg_bot.effects.generic import roto_mana as rm
from mtg_bot.game import Zone
from mtg_bot.turn import Step

from tests._roto_helpers import (
    arena,
    printing,
    put,
    to_graveyard,
    to_hand,
    to_library,
)

BEAR = make_creature("Bear", "{1}{G}", 2, 2)


def _attack(state, pid, ids):
    state.step = Step.DECLARE_ATTACKERS
    apply_action(state, pid, DeclareAttackers(attacker_ids=frozenset(ids)))


# ---------------------------------------------------------------------------
# Dreadhorde Arcanist
# ---------------------------------------------------------------------------


def _arcanist_arena():
    s = arena()
    arc = put(s, printing("Dreadhorde Arcanist"), 0)
    return s, arc


def test_arcanist_casts_a_cheap_instant_free_and_exiles_it():
    s, arc = _arcanist_arena()
    bolt = to_graveyard(s, printing("Lightning Bolt"), 0)
    to_graveyard(s, printing("Counterspell"), 0)  # mana value 2 > power 1
    s.players[0].agent.targets = [("graveyard_card", bolt.id), ("player", 1)]
    _attack(s, 0, [arc.id])
    trig = s.stack[-1]
    assert trig.targets == (("graveyard_card", bolt.id),)
    drain_stack(s)
    assert s.players[1].life == 17
    assert bolt in s.players[0].exile
    assert bolt not in s.players[0].graveyard


def test_arcanist_power_bounds_the_mana_value():
    s, arc = _arcanist_arena()
    to_graveyard(s, printing("Counterspell"), 0)
    eff = arc.printing.triggered_abilities[0].effect
    s.resolving_source = arc
    assert eff.legal_targets(s, 0) == []
    arc.plus_one_counters = 1
    assert eff.legal_targets(s, 0) != []


def test_arcanist_may_decline_and_the_card_stays():
    s, arc = _arcanist_arena()
    bolt = to_graveyard(s, printing("Lightning Bolt"), 0)
    s.players[0].agent.yes = False
    _attack(s, 0, [arc.id])
    drain_stack(s)
    assert bolt in s.players[0].graveyard
    assert not bolt.exile_if_put_into_graveyard_from_stack


def test_arcanist_fizzles_when_the_target_left_the_graveyard():
    s, arc = _arcanist_arena()
    bolt = to_graveyard(s, printing("Lightning Bolt"), 0)
    _attack(s, 0, [arc.id])
    s.players[0].graveyard.remove(bolt)
    bolt.zone = Zone.EXILE
    s.players[0].exile.append(bolt)
    drain_stack(s)
    assert s.players[1].life == 20


def test_graveyard_cast_effect_guards_and_description():
    eff = parse_roto_mana_effect(
        "you may cast target instant card from your graveyard without "
        "paying its mana cost. If that spell would be put into your "
        "graveyard, exile it instead"
    )
    assert isinstance(eff, rm.MayCastTargetGraveyardCardFree)
    assert not eff.mv_at_most_source_power
    assert "graveyard" in eff.describe()
    s = arena()
    eff.resolve(s, 0, ())
    eff.resolve(s, 0, (("player", 1),))
    assert parse_roto_mana_effect(
        "you may cast target frobnicate card from your graveyard without "
        "paying its mana cost. If that spell would be put into your "
        "graveyard, exile it instead"
    ) is None


# ---------------------------------------------------------------------------
# Mystic Forge
# ---------------------------------------------------------------------------


def _forge_arena(top):
    from mtg_bot.cards.base import make_basic_land

    s = arena()
    put(s, printing("Mystic Forge"), 0)
    for _ in range(3):
        put(s, make_basic_land("Mountain", "R"), 0)
    to_library(s, BEAR, 0)  # below the top
    card = s.new_object(top, owner_id=0, zone=Zone.LIBRARY)
    s.players[0].library.insert(0, card)
    return s, card


def test_mystic_forge_casts_artifacts_and_colorless_spells_from_the_top():
    from mtg_bot.actions import CastSpell, resolve_top_of_stack
    from mtg_bot.legal import legal_actions

    s, ring = _forge_arena(printing("Sol Ring"))
    assert CastSpell(ring.id) in legal_actions(s, 0)
    apply_action(s, 0, CastSpell(ring.id))
    resolve_top_of_stack(s)
    assert ring in s.battlefield
    colorless = make_creature("Matter Shaper", "{2}", 3, 2)
    s2, shaper = _forge_arena(colorless)
    assert CastSpell(shaper.id) in legal_actions(s2, 0)


def test_mystic_forge_doesnt_offer_colored_nonartifacts_or_lands():
    from mtg_bot.actions import CastSpell
    from mtg_bot.cards.base import make_basic_land
    from mtg_bot.legal import legal_actions

    s, bolt = _forge_arena(printing("Lightning Bolt"))
    assert CastSpell(bolt.id) not in legal_actions(s, 0)
    s2, land = _forge_arena(make_basic_land("Wastes", "C"))
    assert all(
        getattr(a, "card_id", None) != land.id for a in legal_actions(s2, 0)
    )


def test_mystic_forge_respects_timing_and_controller():
    from mtg_bot.actions import CastSpell
    from mtg_bot.legal import legal_actions

    s, ring = _forge_arena(printing("Sol Ring"))
    s.step = Step.UPKEEP  # not a sorcery window: Sol Ring has no flash
    assert CastSpell(ring.id) not in legal_actions(s, 0)
    s.step = Step.PRECOMBAT_MAIN
    forge = next(o for o in s.battlefield if o.printing.name == "Mystic Forge")
    forge.controller_id = 1
    assert not rm.top_of_library_cast_allowed(s, 0, ring)


def test_mystic_forge_exiles_the_top_card_for_one_life():
    from mtg_bot.actions import _activate_ability

    s, ring = _forge_arena(printing("Sol Ring"))
    forge = next(o for o in s.battlefield if o.printing.name == "Mystic Forge")
    idx = next(
        i for i, a in enumerate(forge.printing.activated_abilities)
        if isinstance(a.effect, rm.ExileTopCardsOfYourLibrary)
    )
    _activate_ability(s, 0, forge.id, idx)
    drain_stack(s)
    assert ring in s.players[0].exile
    assert s.players[0].life == 19
    assert forge.printing.grants_look_at_top_of_library


def test_library_top_kinds_grammar():
    from mtg_bot.cards.parser.printing_keywords import (
        _parse_cast_artifact_from_top_line,
        parse_cast_from_top_kinds,
    )

    assert parse_cast_from_top_kinds(
        "You may cast artifact spells from the top of your library."
    ) == ("artifact",)
    assert _parse_cast_artifact_from_top_line(
        "You may cast artifact spells from the top of your library."
    )
    assert not _parse_cast_artifact_from_top_line(
        "You may cast artifact spells and colorless spells from the top of "
        "your library."
    )
    assert parse_cast_from_top_kinds("You may cast spells.") is None
    assert parse_roto_mana_effect("exile the top two cards of your library")
    assert parse_roto_mana_effect(
        "exile the top many cards of your library"
    ) is None


# ---------------------------------------------------------------------------
# Mind's Desire, Hex Magic
# ---------------------------------------------------------------------------


def test_minds_desire_exiles_the_top_card_playable_free_this_turn():
    from mtg_bot.actions import CastSpell, resolve_top_of_stack
    from mtg_bot.cards.base import make_basic_land
    from mtg_bot.legal import legal_actions

    s = arena()
    for _ in range(6):
        put(s, make_basic_land("Island", "U"), 0)
    bolt = to_library(s, printing("Lightning Bolt"), 0)
    desire = to_hand(s, printing("Mind's Desire"), 0)
    assert desire.printing.has_storm
    apply_action(s, 0, CastSpell(desire.id))
    resolve_top_of_stack(s)  # the storm trigger (no copies: first spell)
    resolve_top_of_stack(s)
    assert bolt in s.players[0].exile
    assert bolt.exile_play_permission.free
    assert CastSpell(bolt.id, cast_for_free=True) in legal_actions(s, 0)


def test_hex_magic_exiles_the_hand_draws_that_many_and_plays_them_later():
    from mtg_bot.actions import CastSpell, resolve_top_of_stack
    from mtg_bot.cards.base import make_basic_land
    from mtg_bot.effects.generic.cube_creatures_rmc import (
        UNTIL_END_OF_YOUR_NEXT_TURN,
    )

    s = arena()
    for _ in range(3):
        put(s, make_basic_land("Mountain", "R"), 0)
    hand = [to_hand(s, BEAR, 0) for _ in range(2)]
    for _ in range(3):
        to_library(s, printing("Lightning Bolt"), 0)
    hex_ = to_hand(s, printing("Hex Magic"), 0)
    apply_action(s, 0, CastSpell(hex_.id))
    resolve_top_of_stack(s)
    assert all(c in s.players[0].exile for c in hand)
    assert len(s.players[0].hand) == 2
    perm = hand[0].exile_play_permission
    assert perm.duration == UNTIL_END_OF_YOUR_NEXT_TURN and not perm.free
    assert "exile your hand" in rm.ExileHandDrawThatManyMayPlayThem().describe()
