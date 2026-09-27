"""Random-agent smoke games with the cube creatures (R / multicolor /
colorless) bucket's claimed cards: every new legality / payment / cast
path gets exercised end-to-end by the real turn loop."""

from __future__ import annotations

import random

import pytest

from mtg_bot.agents import RandomAgent
from mtg_bot.simulate import simulate_game

# Bucket cards claimed on this branch (the deck is padded with basics).
BUCKET_CARDS = [
    "Walking Ballista", "Simian Spirit Guide", "Orcish Lumberjack",
    "Loot, the Pathfinder", "Hexing Squelcher", "Golos, Tireless Pilgrim",
    "Ragavan, Nimble Pilferer", "Broadside Bombardiers",
    "Bloodbraid Challenger", "Phlage, Titan of Fire's Fury",
    "Uro, Titan of Nature's Wrath", "Aragorn, King of Gondor",
    "Headliner Scarlett", "Caves of Chaos Adventurer",
]
BASICS = ["Mountain", "Forest", "Plains", "Island", "Swamp"]


def _deck(offset: int) -> list[str]:
    spells = [BUCKET_CARDS[(i + offset) % len(BUCKET_CARDS)] for i in range(20)]
    lands = [BASICS[i % len(BASICS)] for i in range(20)]
    return spells + lands


@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_random_games_with_bucket_cards_run_to_completion(seed):
    state = simulate_game(
        agents=[RandomAgent(rng=random.Random(seed)), RandomAgent(rng=random.Random(seed + 100))],
        decks=[_deck(0), _deck(7)],
        seed=seed,
        max_turns=25,
    )
    assert state.turn_number >= 1
