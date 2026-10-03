"""Vintage Roto P3: alternative costs (Fireblast, Gush, Invigorate)."""

from __future__ import annotations

from mtg_bot.actions import CastSpell, apply_action, drain_stack
from mtg_bot.cards.base import make_basic_land, make_creature
from mtg_bot.cards.parser.spell_cost_lines import parse_alternative_cost_line
from mtg_bot.cards.spell_costs import AlternativeCost
from mtg_bot.legal import legal_actions

from tests._roto_helpers import arena, printing, put, to_hand, to_library

MOUNTAIN = make_basic_land("Mountain", "R")
ISLAND = make_basic_land("Island", "U")
FOREST = make_basic_land("Forest", "G")


def test_alt_cost_grammar_counts_and_gate_first_order():
    assert parse_alternative_cost_line(
        "You may sacrifice two Mountains rather than pay this spell's mana "
        "cost."
    ) == AlternativeCost(sacrifice_subtype="Mountain", sacrifice_count=2)
    assert parse_alternative_cost_line(
        "You may return two Islands you control to their owner's hand "
        "rather than pay this spell's mana cost."
    ) == AlternativeCost(return_subtype="Island", return_count=2)
    assert parse_alternative_cost_line(
        "If you control a Forest, rather than pay this spell's mana cost, "
        "you may have an opponent gain 3 life."
    ) == AlternativeCost(
        requires_control_subtype="Forest", opponent_gains_life=3,
    )
    # Daze keeps its single-permanent shape.
    assert parse_alternative_cost_line(
        "You may return an Island you control to its owner's hand rather "
        "than pay this spell's mana cost."
    ) == AlternativeCost(return_subtype="Island")


def test_fireblast_sacrifices_two_mountains():
    s = arena()
    m1, m2 = put(s, MOUNTAIN, 0), put(s, MOUNTAIN, 0)
    blast = to_hand(s, printing("Fireblast"), 0)
    s.players[0].agent.targets = [("player", 1)]
    act = CastSpell(blast.id, cast_for_free=True)
    assert act in legal_actions(s, 0)
    apply_action(s, 0, act)
    assert m1 not in s.battlefield and m2 not in s.battlefield
    drain_stack(s)
    assert s.players[1].life == 16


def test_fireblast_needs_two_mountains():
    s = arena()
    put(s, MOUNTAIN, 0)
    blast = to_hand(s, printing("Fireblast"), 0)
    assert CastSpell(blast.id, cast_for_free=True) not in legal_actions(s, 0)


def test_gush_returns_two_islands_and_draws_two():
    s = arena()
    i1, i2 = put(s, ISLAND, 0), put(s, ISLAND, 0)
    for _ in range(2):
        to_library(s, ISLAND, 0)
    gush = to_hand(s, printing("Gush"), 0)
    apply_action(s, 0, CastSpell(gush.id, cast_for_free=True))
    assert i1 in s.players[0].hand and i2 in s.players[0].hand
    drain_stack(s)
    assert len(s.players[0].hand) == 4


def test_invigorate_needs_a_forest_and_feeds_the_opponent():
    s = arena()
    bear = put(s, make_creature("Bear", "{1}{G}", 2, 2), 0)
    inv = to_hand(s, printing("Invigorate"), 0)
    act = CastSpell(inv.id, cast_for_free=True)
    assert act not in legal_actions(s, 0)
    put(s, FOREST, 0, tapped=True)
    assert act in legal_actions(s, 0)
    s.players[0].agent.targets = [("creature", bear.id)]
    apply_action(s, 0, act)
    assert s.players[1].life == 23
    drain_stack(s)
    from mtg_bot.game import effective_power

    assert effective_power(s, bear) == 6


def test_alt_cost_descriptions():
    assert "two" not in AlternativeCost(return_subtype="Island").describe()
    assert AlternativeCost(
        sacrifice_subtype="Mountain", sacrifice_count=2,
    ).describe() == "sacrifice 2 Mountains"
    assert "their owner's hand" in AlternativeCost(
        return_subtype="Island", return_count=2,
    ).describe()
    assert "gains 3 life" in AlternativeCost(opponent_gains_life=3).describe()
