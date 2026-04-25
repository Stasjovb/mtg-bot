"""Tests for ``mtg_bot.training.self_play.run_match``.

Validates the harness-level contract: deterministic seeding,
correct stat aggregation, the decision-cap safety net, and that
results add up to ``n_games``. Uses RandomChoice on both sides
so each test case finishes in single-digit seconds.
"""

from __future__ import annotations

from mtg_bot.training import (
    MatchStats, random_choice_factory, run_match,
)


def test_run_match_returns_stats_with_correct_total():
    stats = run_match(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=4,
        base_seed=42,
    )
    assert isinstance(stats, MatchStats)
    assert stats.games == 4
    assert stats.wins[0] + stats.wins[1] + stats.draws == 4


def test_run_match_is_deterministic_in_base_seed():
    """Same base_seed → same MatchStats. Critical for tuning loops
    that compare configs across runs."""
    a = run_match(
        random_choice_factory, random_choice_factory,
        n_games=3, base_seed=99,
    )
    b = run_match(
        random_choice_factory, random_choice_factory,
        n_games=3, base_seed=99,
    )
    assert a == b


def test_run_match_different_seeds_can_produce_different_results():
    """Sanity: not every seed produces the same outcome — we want
    real seed sensitivity so tuning data isn't all one trace."""
    seen = set()
    for seed in range(8):
        stats = run_match(
            random_choice_factory, random_choice_factory,
            n_games=2, base_seed=seed,
        )
        seen.add((stats.wins[0], stats.wins[1], stats.draws))
    assert len(seen) > 1


def test_run_match_win_rate_helper():
    stats = run_match(
        random_choice_factory, random_choice_factory,
        n_games=5, base_seed=0,
    )
    expected = stats.wins[0] / 5
    assert stats.win_rate(0) == expected
    assert stats.win_rate(1) == stats.wins[1] / 5


def test_run_match_zero_games_returns_zero_stats():
    """Edge case: n_games=0 shouldn't crash."""
    stats = run_match(
        random_choice_factory, random_choice_factory,
        n_games=0, base_seed=0,
    )
    assert stats.games == 0
    assert stats.wins == {0: 0, 1: 0}
    assert stats.draws == 0
    assert stats.avg_decisions == 0.0
    assert stats.win_rate(0) == 0.0


def test_run_match_records_avg_decisions():
    """avg_decisions should reflect actual game lengths — at least
    > 0 for any non-trivial game."""
    stats = run_match(
        random_choice_factory, random_choice_factory,
        n_games=3, base_seed=11,
    )
    assert stats.avg_decisions > 0


def test_run_match_decision_cap_treats_unfinished_as_draw():
    """If we set the cap absurdly low, every game hits it and is
    counted as a draw. Verifies the cap actually caps and the draw
    accounting works."""
    stats = run_match(
        random_choice_factory, random_choice_factory,
        n_games=3, base_seed=0,
        decision_cap=2,  # absurdly low
    )
    assert stats.draws == 3
    assert stats.wins == {0: 0, 1: 0}
    assert stats.avg_decisions == 2  # every game stopped at cap
