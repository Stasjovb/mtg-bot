"""Smoke games with the Vintage Roto P2 cards (library, graveyard &
hand): random-agent games through the real turn loop and one PIMC
search game (clone / determinize / resolution-channel paths), so every
new cast, cost, replacement and sweep path runs end to end."""

from __future__ import annotations

import random

import pytest

from mtg_bot.agents import RandomAgent
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.cards.source import get_active_source, set_active_source

P2_CARDS = [
    "Beseech the Mirror", "Fabled Passage", "Gamble", "Ghost Quarter",
    "Imperial Recruiter", "Protean Hulk", "Unmarked Grave", "Academy Rector",
    "Arena Rector", "Birthing Pod", "Doomsday", "Finale of Devastation",
    "Gifts Ungiven", "Oswald Fiddlebender", "Recruiter of the Guard",
    "Scapeshift", "Survival of the Fittest", "Cabal Therapy",
    "Kitesail Freebooter", "Smallpox", "Vendilion Clique", "Cabal Therapist",
    "Dreams of Steel and Oil", "Kroxa, Titan of Death's Hunger", "Pox",
    "Sire of Insanity", "Bojuka Bog", "Rest in Peace", "Sanctifier en-Vec",
    "Recurring Nightmare", "Takenuma, Abandoned Mire", "Cling to Dust",
    "Deathrite Shaman", "Dread Return", "Noxious Revival", "Persist",
    "Pre-War Formalwear", "Reveillark", "Sevinne's Reclamation",
    "Chains of Mephistopheles", "Stinkweed Imp", "Life from the Loam",
    "Goblin Guide", "Collected Company", "Deem Inferior", "Flow State",
    "Hermit Druid", "Scroll Rack", "Tainted Pact", "Tasha's Hideous Laughter",
    "Triumph of Saint Katherine", "Ulamog, the Ceaseless Hunger",
    "Winota, Joiner of Forces", "Opposition Agent", "Archive Trap",
    "Wan Shi Tong, Librarian", "Bridge from Below", "Kishla Skimmer",
    "Narcomoeba", "Slogurk, the Overslime", "Gau, Feral Youth", "Eureka",
    "Show and Tell", "Stronghold Gambit",
]
BASICS = ["Swamp", "Forest", "Plains", "Island", "Mountain"]


@pytest.fixture(scope="module")
def roto_source():
    prior = get_active_source()
    set_active_source(OracleParserCardSource(pool="roto"))
    try:
        yield
    finally:
        set_active_source(prior)


def _deck(offset: int) -> list[str]:
    spells = [P2_CARDS[(i + offset) % len(P2_CARDS)] for i in range(24)]
    return spells + [BASICS[i % len(BASICS)] for i in range(16)]


def test_every_listed_card_is_claimed():
    claimed = set(OracleParserCardSource(pool="roto").claimed_names)
    assert [c for c in P2_CARDS if c not in claimed] == []


@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_random_games_with_p2_cards_run_to_completion(roto_source, seed):
    from mtg_bot.simulate import simulate_game

    state = simulate_game(
        agents=[RandomAgent(rng=random.Random(seed)),
                RandomAgent(rng=random.Random(seed + 100))],
        decks=[_deck(seed * 3), _deck(seed * 5 + 11)],
        seed=seed, max_turns=25,
    )
    assert state.turn_number >= 1
    names = {o.printing.name for o in state.battlefield} | {
        c.printing.name for p in state.players
        for c in list(p.library) + p.hand + list(p.graveyard) + list(p.exile)
    }
    assert names & set(P2_CARDS)


def test_pimc_search_game_with_p2_cards_completes(roto_source):
    from mtg_bot.search import (
        Budget, MCTS, MtgGameStateAdapter, PIMC, RandomChoice,
    )
    from mtg_bot.search.heuristic_evaluator import MtgHeuristicEvaluator
    from mtg_bot.search.protocol import CHANCE_PLAYER
    from mtg_bot.simulate import setup_game

    seed = 2
    state = MtgGameStateAdapter(setup_game(
        [RandomAgent(rng=random.Random(1)), RandomAgent(rng=random.Random(2))],
        decks=[_deck(seed), _deck(seed + 17)], seed=seed,
    ))
    pimc = PIMC(
        inner_factory=lambda: MCTS(
            evaluator=MtgHeuristicEvaluator(),
            budget_factory=lambda: Budget(max_nodes=12),
            rng=random.Random(seed + 100),
        ),
        samples=1, rng=random.Random(seed + 200),
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
