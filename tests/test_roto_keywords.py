"""Roto P6 keyword mechanics (``cards/parser/roto_keywords.py`` +
``effects/generic/roto_keywords.py``): the parse and in-game behavior of
each keyword the package models."""

from __future__ import annotations

from mtg_bot.actions import ActivateAbility, apply_action, resolve_top_of_stack
from mtg_bot.cards.parser.roto_keywords import parse_hand_keyword_line
from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.card_flow import SearchLibrary
from mtg_bot.effects.generic.roto_keywords import ManaValueCardFilter
from mtg_bot.game import Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step
from tests._roto_helpers import arena, printing, put, to_hand, to_library

MUDDLE = "Muddle the Mixture"
TOLARIA_WEST = "Tolaria West"


def _default(name):
    return get_active_source().get_printings()[name]


def _hand_ability_actions(state, card, player_id=0):
    return [
        a for a in legal_actions(state, player_id)
        if isinstance(a, ActivateAbility) and a.source_id == card.id
    ]


# -------------------------------------------------------------- Transmute


def test_transmute_parse():
    (ability,) = printing(MUDDLE).hand_activated_abilities
    assert ability.sorcery_speed and ability.cost.discard_self
    assert ability.cost.mana_str == "{1}{U}{U}"
    assert ability.effect == SearchLibrary(
        card_filter=ManaValueCardFilter(mana_value=2),
        destination="hand", reveal=True,
    )
    # Tolaria West is a land: mana value 0.
    (west,) = printing(TOLARIA_WEST).hand_activated_abilities
    assert west.effect.card_filter.mana_value == 0
    # The rest of each card still parses.
    assert printing(MUDDLE).spell_effect is not None
    assert printing(TOLARIA_WEST).produces == frozenset({"U"})


def test_transmute_line_grammar():
    card = {"name": "X", "mana_cost": "{X}{3}{B}"}
    ability = parse_hand_keyword_line("Transmute {1}{B}{B}", card)
    assert ability.effect.card_filter.mana_value == 4  # X is 0
    assert parse_hand_keyword_line("Transmute", card) is None
    assert parse_hand_keyword_line("Cycling {2}", card) is None


def test_mana_value_filter():
    f = ManaValueCardFilter(mana_value=1)
    assert f.has_quality
    assert f.matches(_default("Lightning Bolt"))
    assert not f.matches(_default("Counterspell"))
    assert "mana value 1" in f.describe()


def _transmute_arena(card_name):
    s = arena()
    for _ in range(3):
        put(s, _default("Island"), 0)
    card = to_hand(s, printing(card_name), 0)
    return s, card


def test_transmute_finds_a_card_with_the_same_mana_value():
    s, muddle = _transmute_arena(MUDDLE)
    bolt = to_library(s, _default("Lightning Bolt"), 0)
    spell = to_library(s, _default("Counterspell"), 0)
    (action,) = _hand_ability_actions(s, muddle)
    apply_action(s, 0, action)
    assert muddle in s.players[0].graveyard  # discarded as the cost
    assert all(o.tapped for o in s.battlefield)  # paid {1}{U}{U}
    resolve_top_of_stack(s)
    assert spell in s.players[0].hand and spell.zone is Zone.HAND
    assert spell.publicly_known_to == frozenset({0, 1})  # revealed
    assert bolt in s.players[0].library


def test_transmute_can_find_nothing():
    s, muddle = _transmute_arena(MUDDLE)
    to_library(s, _default("Lightning Bolt"), 0)
    apply_action(s, 0, _hand_ability_actions(s, muddle)[0])
    resolve_top_of_stack(s)
    assert len(s.players[0].hand) == 0
    assert len(s.players[0].library) == 1


def test_tolaria_west_transmutes_for_mana_value_zero():
    s, west = _transmute_arena(TOLARIA_WEST)
    to_library(s, _default("Lightning Bolt"), 0)
    island = to_library(s, _default("Island"), 0)
    apply_action(s, 0, _hand_ability_actions(s, west)[0])
    resolve_top_of_stack(s)
    assert island in s.players[0].hand


def test_transmute_only_as_a_sorcery():
    s, muddle = _transmute_arena(MUDDLE)
    s.step = Step.UPKEEP
    assert _hand_ability_actions(s, muddle) == []
    # Not on the opponent's turn either.
    s, muddle = _transmute_arena(MUDDLE)
    s.active_player_idx = 1
    assert _hand_ability_actions(s, muddle) == []

