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
