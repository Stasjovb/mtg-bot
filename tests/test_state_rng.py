"""Tests for the canonical state.rng — reproducibility across runs.

The engine used to seed ephemeral RNGs with ``hash((...))`` at roughly
eight sites. Python's string-hash randomisation (PYTHONHASHSEED) made
those non-reproducible across processes. Routing every in-engine
shuffle / random choice through ``state.rng`` fixes that; this module
pins down the behaviour.
"""

from __future__ import annotations

import random

from mtg_bot.agents import RandomAgent
from mtg_bot.game import GameState
from mtg_bot.simulate import simulate_game
from tests._test_decks import simple_test_decklists  # noqa: E402


def test_state_rng_shuffle_is_reproducible() -> None:
    """Seeding state.rng to a known value gives identical output."""
    state_a = GameState()
    state_a.rng.seed(12345)
    deck_a = list(range(20))
    state_a.rng.shuffle(deck_a)

    state_b = GameState()
    state_b.rng.seed(12345)
    deck_b = list(range(20))
    state_b.rng.shuffle(deck_b)

    assert deck_a == deck_b
    assert deck_a != list(range(20))  # actually shuffled


def test_state_rng_choice_is_reproducible() -> None:
    state_a = GameState()
    state_a.rng.seed(777)
    state_b = GameState()
    state_b.rng.seed(777)

    picks_a = [state_a.rng.choice(["a", "b", "c", "d"]) for _ in range(25)]
    picks_b = [state_b.rng.choice(["a", "b", "c", "d"]) for _ in range(25)]

    assert picks_a == picks_b


def test_simulate_game_deterministic_with_same_seeds() -> None:
    """Two games with identical setup-seed and identical agent RNGs
    should produce identical log contents, life totals, and winner.
    """
    def run_once() -> GameState:
        agents = [
            RandomAgent(name="a0", rng=random.Random(111)),
            RandomAgent(name="a1", rng=random.Random(222)),
        ]
        return simulate_game(
            agents=agents, decks=simple_test_decklists(), seed=42, max_turns=30,
        )

    left = run_once()
    right = run_once()

    assert list(left.log) == list(right.log)
    assert [p.life for p in left.players] == [
        p.life for p in right.players
    ]
    assert left.winner_id == right.winner_id
    assert left.is_draw == right.is_draw


def test_simulate_game_diverges_with_different_seed() -> None:
    """Sanity check — flipping the seed changes something."""
    def run_once(seed: int) -> list[str]:
        agents = [
            RandomAgent(name="a0", rng=random.Random(111)),
            RandomAgent(name="a1", rng=random.Random(222)),
        ]
        state = simulate_game(
            agents=agents, decks=simple_test_decklists(), seed=seed, max_turns=30,
        )
        return list(state.log)

    assert run_once(42) != run_once(43)
