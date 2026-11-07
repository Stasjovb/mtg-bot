"""Forgetful Fish self-play data: a deck pool whose decks carry
``game_format="forgetful_fish"`` makes data_gen / self-play set up one
shared library (``formats.setup_args_for_decks``)."""

from __future__ import annotations

import numpy as np
import pytest

from mtg_bot.decks import Deck
from mtg_bot.formats import FORGETFUL_FISH, STANDARD, setup_args_for_decks
from mtg_bot.training import generate_training_data, random_choice_factory

FISH_LIKE = ["Island"] * 40 + ["Brainstorm"] * 20 + ["Memory Lapse"] * 20


def _deck(cards, fmt=None, i=0):
    return Deck(draft_id=f"d{i}", build_index=0, cards=list(cards), game_format=fmt)


def test_fish_decks_make_one_shared_library():
    a = _deck(FISH_LIKE, "forgetful_fish")
    decks, fmt = setup_args_for_decks(a, a)
    assert fmt is FORGETFUL_FISH and decks == [FISH_LIKE]


def test_untagged_decks_are_the_normal_game():
    a, b = _deck(["Island"] * 40), _deck(["Forest"] * 40, i=1)
    decks, fmt = setup_args_for_decks(a, b)
    assert fmt is STANDARD and decks == [a.cards, b.cards]


def test_mixed_formats_are_refused():
    with pytest.raises(ValueError, match="different formats"):
        setup_args_for_decks(_deck(FISH_LIKE, "forgetful_fish"), _deck(FISH_LIKE))


def test_game_format_round_trips_through_json_dicts():
    d = _deck(FISH_LIKE, "forgetful_fish")
    assert Deck.from_dict(d.to_dict()).game_format == "forgetful_fish"
    assert Deck.from_dict({"draft_id": "x", "build_index": 0}).game_format is None


def test_data_gen_plays_fish_games():
    features, outcomes = generate_training_data(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=2, base_seed=5,
        deck_pool=[_deck(FISH_LIKE, "forgetful_fish")],
    )
    assert features.shape[0] == outcomes.shape[0] > 0
    assert np.all(np.isin(outcomes, [-1.0, 0.0, 1.0]))
