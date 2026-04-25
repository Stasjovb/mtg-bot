"""Tests for ``mtg_bot.training.grid``.

Validates the grid-iteration contract: every config gets played
the right number of games, results are sorted by P0 win rate, the
weight-grid generator produces valid configs that sum to 1.0, and
the progress callback fires once per config.
"""

from __future__ import annotations

from mtg_bot.training import (
    HeuristicConfig, PimcConfig, grid_search,
    heuristic_weight_grid, random_choice_factory,
)


def test_heuristic_weight_grid_sums_to_one():
    grid = heuristic_weight_grid(step=0.1)
    assert grid, "grid must not be empty"
    for cfg in grid:
        h = cfg.heuristic
        total = h.life_weight + h.board_weight + h.card_weight
        assert abs(total - 1.0) < 1e-9, (
            f"weights {h} sum to {total}, expected 1.0"
        )


def test_heuristic_weight_grid_respects_min_max():
    grid = heuristic_weight_grid(
        step=0.1, min_weight=0.2, max_weight=0.6,
    )
    for cfg in grid:
        h = cfg.heuristic
        for w in (h.life_weight, h.board_weight, h.card_weight):
            assert 0.2 - 1e-9 <= w <= 0.6 + 1e-9


def test_heuristic_weight_grid_propagates_pimc_knobs():
    grid = heuristic_weight_grid(samples=7, inner_nodes=33)
    for cfg in grid:
        assert cfg.samples == 7
        assert cfg.inner_nodes == 33


def test_grid_search_runs_each_config_against_opponent():
    grid = [
        PimcConfig(samples=1, inner_nodes=4,
                   heuristic=HeuristicConfig(0.5, 0.3, 0.2)),
        PimcConfig(samples=1, inner_nodes=4,
                   heuristic=HeuristicConfig(0.3, 0.5, 0.2)),
    ]
    results = grid_search(
        grid=grid,
        opponent_factory=random_choice_factory,
        n_games=2,
        base_seed=0,
    )
    assert len(results) == 2
    for cfg, stats in results:
        assert stats.games == 2
        assert cfg in grid


def test_grid_search_results_sorted_by_win_rate_descending():
    """Sort contract: best config first. Doesn't assert which config
    is best (that's noise-dependent at small N) — just the order."""
    grid = list(heuristic_weight_grid(
        step=0.2, min_weight=0.2, max_weight=0.6,
        samples=1, inner_nodes=4,
    ))
    results = grid_search(
        grid=grid,
        opponent_factory=random_choice_factory,
        n_games=2,
        base_seed=0,
    )
    win_rates = [stats.win_rate(0) for _, stats in results]
    assert win_rates == sorted(win_rates, reverse=True)


def test_grid_search_progress_callback_fires_per_config():
    grid = list(heuristic_weight_grid(
        step=0.2, min_weight=0.2, max_weight=0.6,
        samples=1, inner_nodes=4,
    ))
    calls: list[tuple] = []

    def cb(idx, total, config, stats):
        calls.append((idx, total, config, stats.games))

    grid_search(
        grid=grid,
        opponent_factory=random_choice_factory,
        n_games=2,
        base_seed=0,
        progress_callback=cb,
    )
    assert len(calls) == len(grid)
    # idx is 0-based and total is the same for every call.
    for i, (idx, total, _, games) in enumerate(calls):
        assert idx == i
        assert total == len(grid)
        assert games == 2


def test_grid_search_silent_when_no_callback():
    """No callback → no exception, just runs through."""
    grid = [PimcConfig(samples=1, inner_nodes=4)]
    results = grid_search(
        grid=grid, opponent_factory=random_choice_factory,
        n_games=1, base_seed=0,
    )
    assert len(results) == 1
