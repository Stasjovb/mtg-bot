"""Vintage Roto P3: static cast permissions -- Omniscience, Aluren and
Dream Halls' granted alternative cost."""

from __future__ import annotations

from mtg_bot.actions import CastSpell, apply_action, drain_stack
from mtg_bot.cards.base import make_basic_land, make_creature
from mtg_bot.cards.spell_costs import (
    DREAM_HALLS_COST,
    alternative_costs_for,
)
from mtg_bot.effects.generic import roto_mana as rm
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step

from tests._roto_helpers import arena, printing, put, to_hand, to_library

ISLAND = make_basic_land("Island", "U")


def _goblin(cost="{2}{R}"):
    return make_creature("Goblin Smasher", cost, 3, 3)


# ---------------------------------------------------------------------------
# Omniscience
# ---------------------------------------------------------------------------


def test_omniscience_casts_hand_spells_for_free():
    s = arena()
    put(s, printing("Omniscience"), 0)
    big = to_hand(s, make_creature("Colossus", "{8}", 8, 8), 0)
    act = CastSpell(big.id, cast_for_free=True)
    assert act in legal_actions(s, 0)
    apply_action(s, 0, act)
    drain_stack(s)
    assert big in s.battlefield


def test_omniscience_keeps_normal_timing_and_owner():
    s = arena()
    put(s, printing("Omniscience"), 1)  # the opponent's
    big = to_hand(s, make_creature("Colossus", "{8}", 8, 8), 0)
    assert CastSpell(big.id, cast_for_free=True) not in legal_actions(s, 0)
    s2 = arena()
    put(s2, printing("Omniscience"), 0)
    big2 = to_hand(s2, make_creature("Colossus", "{8}", 8, 8), 0)
    s2.step = Step.UPKEEP
    assert CastSpell(big2.id, cast_for_free=True) not in legal_actions(s2, 0)


def test_omniscience_free_cast_skips_printed_alternative_costs():
    """Force of Despair cast through Omniscience exiles nothing."""
    s = arena(active=1)
    s.priority_player_idx = 0
    put(s, printing("Omniscience"), 0)
    force = to_hand(s, printing("Force of Despair"), 0)
    other = to_hand(s, printing("Force of Despair"), 0)
    apply_action(s, 0, CastSpell(force.id, cast_for_free=True))
    assert other in s.players[0].hand


def test_omniscience_casts_lotus_bloom():
    s = arena()
    put(s, printing("Omniscience"), 0)
    bloom = to_hand(s, printing("Lotus Bloom"), 0)
    assert CastSpell(bloom.id, cast_for_free=True) in legal_actions(s, 0)


# ---------------------------------------------------------------------------
# Aluren
# ---------------------------------------------------------------------------


def test_aluren_any_player_casts_small_creatures_free_at_instant_speed():
    s = arena(active=0)
    put(s, printing("Aluren"), 0)
    small = to_hand(s, _goblin(), 1)
    big = to_hand(s, make_creature("Ogre", "{3}{R}", 4, 4), 1)
    s.priority_player_idx = 1  # the opponent, on my turn
    acts = legal_actions(s, 1)
    assert CastSpell(small.id, cast_for_free=True) in acts
    assert CastSpell(big.id, cast_for_free=True) not in acts
    assert rm._aluren_max_mv(s) == 3


def test_aluren_flash_is_only_for_the_free_cast():
    s = arena(active=0)
    put(s, printing("Aluren"), 0)
    for _ in range(3):
        put(s, make_basic_land("Mountain", "R"), 1)
    small = to_hand(s, _goblin(), 1)
    s.priority_player_idx = 1
    acts = legal_actions(s, 1)
    assert CastSpell(small.id) not in acts  # paying its cost: no flash
    apply_action(s, 1, CastSpell(small.id, cast_for_free=True))
    drain_stack(s)
    assert small in s.battlefield


# ---------------------------------------------------------------------------
# Dream Halls
# ---------------------------------------------------------------------------


def test_dream_halls_discards_a_color_sharing_card_instead():
    s = arena()
    put(s, printing("Dream Halls"), 1)  # it works for every player
    for _ in range(3):
        to_library(s, ISLAND, 0)
    recall = to_hand(s, printing("Ancestral Recall"), 0)
    blue = to_hand(s, printing("Brainstorm"), 0)
    to_hand(s, printing("Lightning Bolt"), 0)
    assert alternative_costs_for(s, 0, recall) == (DREAM_HALLS_COST,)
    act = CastSpell(recall.id, cast_for_free=True)
    assert act in legal_actions(s, 0)
    s.players[0].agent.targets = [("player", 0)]
    apply_action(s, 0, act)
    assert blue in s.players[0].graveyard
    drain_stack(s)
    assert len(s.players[0].hand) == 4  # Bolt + three drawn


def test_dream_halls_needs_a_shared_color():
    s = arena()
    put(s, printing("Dream Halls"), 0)
    recall = to_hand(s, printing("Ancestral Recall"), 0)
    to_hand(s, printing("Lightning Bolt"), 0)
    assert CastSpell(recall.id, cast_for_free=True) not in legal_actions(s, 0)
    ring = to_hand(s, printing("Sol Ring"), 0)  # colorless: never
    to_hand(s, printing("Brainstorm"), 0)
    assert CastSpell(ring.id, cast_for_free=True) not in legal_actions(s, 0)


def test_dream_halls_doesnt_count_as_a_printed_alternative_cost():
    """A granted cost doesn't satisfy "if its alternative cost was paid"."""
    s = arena()
    put(s, printing("Dream Halls"), 0)
    recall = to_hand(s, printing("Ancestral Recall"), 0)
    to_hand(s, printing("Brainstorm"), 0)
    apply_action(s, 0, CastSpell(recall.id, cast_for_free=True))
    assert not s.stack[-1].alt_cost_paid
    assert "discard" in DREAM_HALLS_COST.describe()


def test_permission_helpers_without_permissions():
    s = arena()
    card = to_hand(s, _goblin(), 0)
    assert not rm.static_free_cast_permission(s, 0, card)
    assert rm._aluren_max_mv(s) is None
    land = to_hand(s, ISLAND, 0)
    put(s, printing("Omniscience"), 0)
    assert not rm.static_free_cast_permission(s, 0, land)
