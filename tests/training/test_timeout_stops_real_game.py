"""Integration test for the cooperative per-game stop.

The unit tests in ``test_timeout.py`` prove the machinery works on a
synthetic workload. This file proves the thing that actually broke in
production: a *real* MTG game driven through
``self_play._play_capped_game`` — which is the exact call the
2026-09-23 faulthandler dumps showed running twice at once in one
worker process — really unwinds when its wall budget expires, instead
of running on and racing the next game.

Kept deliberately cheap (tiny node budgets, heuristic evaluator, no
torch) so it costs a fraction of a second and adds no NN dependency.
"""

from __future__ import annotations

import random
import threading
import time

import pytest

from mtg_bot.agents import RandomAgent
from mtg_bot.cancellation import current_token
from mtg_bot.search import (
    Budget,
    MCTS,
    MtgGameStateAdapter,
    MtgHeuristicEvaluator,
)
from mtg_bot.simulate import setup_game
from mtg_bot.training._timeout import run_with_timeout
from mtg_bot.training.self_play import _play_capped_game
from tests._test_decks import simple_test_decklists


def _adapter(seed: int = 7) -> MtgGameStateAdapter:
    state = setup_game(
        [RandomAgent(), RandomAgent()],
        decks=simple_test_decklists(),
        seed=seed,
    )
    return MtgGameStateAdapter(state, expose_combat_decisions=True)


def _slow_mcts(seed: int = 0) -> MCTS:
    """Deep enough per decision that the game can't finish inside the
    test's wall budget, so the timeout path is the one exercised."""
    return MCTS(
        evaluator=MtgHeuristicEvaluator(),
        budget_factory=lambda: Budget(max_nodes=400),
        rng=random.Random(seed),
    )


def test_real_game_under_timeout_unwinds_instead_of_zombieing():
    adapter = _adapter()
    strategies = {0: _slow_mcts(1), 1: _slow_mcts(2)}
    rng = random.Random(99)

    threads_before = threading.active_count()
    with pytest.raises(TimeoutError) as excinfo:
        run_with_timeout(
            _play_capped_game,
            (adapter, strategies, rng, 4000, None, None),
            0.5,
            stop_grace_sec=20.0,
        )

    assert "stopped cleanly" in str(excinfo.value), (
        "the abandoned game thread did not honour the cooperative "
        "stop — it would race the next game in this worker"
    )

    # Give the OS a beat to reap the finished thread, then assert we
    # aren't leaking one per timed-out game (the pre-fix behavior).
    deadline = time.perf_counter() + 5.0
    while (
        threading.active_count() > threads_before + 1
        and time.perf_counter() < deadline
    ):
        time.sleep(0.05)
    assert threading.active_count() <= threads_before + 1


def test_game_completing_inside_budget_is_unaffected():
    """Regression guard: the cancellation checks must not disturb a
    game that finishes normally. Same call, generous budget."""
    adapter = _adapter(seed=11)
    strategies = {
        0: MCTS(
            evaluator=MtgHeuristicEvaluator(),
            budget_factory=lambda: Budget(max_nodes=2),
            rng=random.Random(1),
        ),
        1: MCTS(
            evaluator=MtgHeuristicEvaluator(),
            budget_factory=lambda: Budget(max_nodes=2),
            rng=random.Random(2),
        ),
    }
    winner, decisions = run_with_timeout(
        _play_capped_game,
        (adapter, strategies, random.Random(5), 40, None, None),
        120.0,
    )
    assert decisions > 0
    assert winner in (None, 0, 1)
    # The token must not survive into the caller's thread.
    assert current_token() is None
