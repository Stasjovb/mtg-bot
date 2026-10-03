"""Vintage Roto P3: extra land plays (Exploration, Azusa, Lost but
Seeking) through the parameterized additional-lands static."""

from __future__ import annotations

from mtg_bot.actions import PlayLand, apply_action
from mtg_bot.cards.base import make_basic_land
from mtg_bot.cards.parser.printing_keywords import (
    _parse_additional_land_per_turn_line,
    parse_additional_lands_per_turn,
)
from mtg_bot.legal import legal_actions

from tests._roto_helpers import arena, printing, put, to_hand

FOREST = make_basic_land("Forest", "G")


def _plays_left(state, pid=0) -> int:
    n = 0
    while True:
        land = next((c for c in state.players[pid].hand), None)
        if land is None or PlayLand(land.id) not in legal_actions(state, pid):
            return n
        apply_action(state, pid, PlayLand(land.id))
        n += 1


def test_additional_lands_grammar_counts():
    assert parse_additional_lands_per_turn(
        "You may play an additional land on each of your turns."
    ) == 1
    assert parse_additional_lands_per_turn(
        "You may play two additional lands on each of your turns."
    ) == 2
    assert parse_additional_lands_per_turn("You may play lands.") is None
    assert not _parse_additional_land_per_turn_line("Draw a card.")


def test_exploration_allows_two_land_drops():
    s = arena()
    assert printing("Exploration").grants_additional_land_per_turn == 1
    put(s, printing("Exploration"), 0)
    for _ in range(4):
        to_hand(s, FOREST, 0)
    assert _plays_left(s) == 2


def test_azusa_allows_three_land_drops():
    s = arena()
    assert printing("Azusa, Lost but Seeking").grants_additional_land_per_turn == 2
    put(s, printing("Azusa, Lost but Seeking"), 0)
    for _ in range(5):
        to_hand(s, FOREST, 0)
    assert _plays_left(s) == 3


def test_extra_land_plays_only_for_the_controller():
    s = arena()
    put(s, printing("Exploration"), 1)
    for _ in range(3):
        to_hand(s, FOREST, 0)
    assert _plays_left(s) == 1
