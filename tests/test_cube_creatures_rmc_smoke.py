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
    "Bloodtithe Harvester", "Carnage Interpreter", "Generous Plunderer",
    "Goblin Engineer", "Ivora, Insatiable Heir", "Magda, Brazen Outlaw",
    "Otharri, Suns' Glory", "Pyrogoyf", "Screaming Nemesis",
    "Seasoned Pyromancer", "Territorial Kavu", "Tersa Lightshatter",
    "Thor, God of Thunder", "Dragon's Rage Channeler",
    "Spider-Woman, Stunning Savior", "Painter's Servant",
    "Raph & Mikey, Troublemakers", "Atraxa, Grand Unifier",
    "Witherbloom Apprentice", "Wolverine, Fierce Fighter", "Chaos Defiler",
    "Figure of Destiny", "Blightsteel Colossus", "Emrakul, the Aeons Torn",
    "Alpha Deathclaw", "Robber of the Rich", "Raffine, Scheming Seer",
    "Gut, True Soul Zealot", "Zirda, the Dawnwaker", "Lurrus of the Dream-Den",
    "Cogwork Librarian", "Leovold, Emissary of Trest", "Nadu, Winged Wisdom",
    "Lutri, the Spellchaser", "Goblin Welder", "Inti, Seneschal of the Sun",
    "Batroc the Leaper", "\"Name Sticker\" Goblin", "Laelia, the Blade Reforged",
]
BASICS = ["Mountain", "Forest", "Plains", "Island", "Swamp"]


def _deck(offset: int) -> list[str]:
    spells = [BUCKET_CARDS[(i + offset) % len(BUCKET_CARDS)] for i in range(20)]
    lands = [BASICS[i % len(BASICS)] for i in range(20)]
    return spells + lands


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 6])
def test_random_games_with_bucket_cards_run_to_completion(seed):
    state = simulate_game(
        agents=[RandomAgent(rng=random.Random(seed)), RandomAgent(rng=random.Random(seed + 100))],
        decks=[_deck(0), _deck(7)],
        seed=seed,
        max_turns=25,
    )
    assert state.turn_number >= 1


def test_pimc_search_game_with_bucket_cards_completes():
    """PIMC (clone / determinize / action-encoding paths) vs random with
    the bucket's cards: every decision the search returns is legal and
    the capped game terminates."""
    from mtg_bot.search import (
        Budget, MCTS, MtgGameStateAdapter, PIMC, RandomChoice,
    )
    from mtg_bot.search.heuristic_evaluator import MtgHeuristicEvaluator
    from mtg_bot.search.protocol import CHANCE_PLAYER
    from mtg_bot.simulate import setup_game

    seed = 5
    state = MtgGameStateAdapter(setup_game(
        [RandomAgent(rng=random.Random(1)), RandomAgent(rng=random.Random(2))],
        decks=[_deck(0), _deck(11)], seed=seed,
    ))
    pimc = PIMC(
        inner_factory=lambda: MCTS(
            evaluator=MtgHeuristicEvaluator(),
            budget_factory=lambda: Budget(max_nodes=12),
            rng=random.Random(seed + 100),
        ),
        samples=1,
        rng=random.Random(seed + 200),
    )
    strategies = {0: pimc, 1: RandomChoice(rng=random.Random(7))}
    rng = random.Random(3)
    decisions = 0
    while not state.is_terminal() and decisions < 1500:
        active = state.active_player()
        if active == CHANCE_PLAYER:
            outcomes = state.chance_outcomes()
            decision = rng.choices(
                [d for d, _ in outcomes], weights=[w for _, w in outcomes], k=1,
            )[0]
        else:
            decision = strategies[active].choose(state, active)
            assert decision in state.legal_decisions()
        state.apply(decision)
        decisions += 1
    assert decisions > 0
