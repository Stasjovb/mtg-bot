"""Tests for ``mtg_bot.training.self_play.run_match``.

Validates the harness-level contract: deterministic seeding,
correct stat aggregation, the decision-cap safety net, and that
results add up to ``n_games``. Uses RandomChoice on both sides
so each test case finishes in single-digit seconds.
"""

from __future__ import annotations

import json
from pathlib import Path

from mtg_bot.decks import Deck
from mtg_bot.training import (
    EvalProgress, MatchStats, random_choice_factory, run_match,
)
from mtg_bot.training.self_play import run_match_parallel
from tests.training.test_data_gen import build_mono_color_deck


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


def test_run_match_parallel_with_progress_emits_snapshot(tmp_path: Path):
    """The progress-tracked parallel path must produce the same
    MatchStats as the unindexed path AND leave a finalized
    progress JSON on disk. Two-game smoke is enough to exercise
    the imap_unordered → record_game → finalize flow."""
    progress = EvalProgress(
        progress_path=tmp_path / "eval.json",
        run_id="eval",
        n_games_total=4,
        n_workers=2,
        opponent_label="random",
        flush_interval_s=0.0,
    )
    stats = run_match_parallel(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=4,
        base_seed=0,
        n_workers=2,
        progress=progress,
    )
    # Same aggregation as the no-progress path (both call
    # _aggregate_results on equivalent inputs).
    expected = run_match_parallel(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=4,
        base_seed=0,
        n_workers=2,
    )
    assert stats == expected

    payload = json.loads((tmp_path / "eval.json").read_text(encoding="utf-8"))
    assert payload["kind"] == "eval"
    assert payload["status"] == "completed"
    assert payload["n_games_total"] == 4
    assert payload["n_games_done"] == 4
    assert payload["wins_new"] == stats.wins[0]
    assert payload["wins_old"] == stats.wins[1]
    assert payload["draws"] == stats.draws
    assert payload["opponent_label"] == "random"


def test_run_match_parallel_with_deck_pool_uses_pool_decks():
    """When deck_pool is supplied, the parallel match path samples
    from the pool (per-game seed) and the games still aggregate
    into a valid MatchStats. Same accounting invariants as the
    legacy mono-color path."""
    pool = [
        Deck(draft_id="g_deck", build_index=0,
             cards=build_mono_color_deck("G", seed=1)),
        Deck(draft_id="r_deck", build_index=0,
             cards=build_mono_color_deck("R", seed=2)),
    ]
    stats = run_match_parallel(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=2,
        base_seed=42,
        n_workers=2,
        deck_pool=pool,
    )
    assert isinstance(stats, MatchStats)
    assert stats.wins[0] + stats.wins[1] + stats.draws + stats.crashed == 2


def test_run_match_deck_pool_sequential_equals_parallel():
    """Strong invariant mirroring data_gen's: same deck_pool +
    base_seed gives identical MatchStats across sequential and
    parallel paths. Without this, switching workers between runs
    would silently shift evaluation results."""
    pool = [
        Deck(draft_id="g_deck", build_index=0,
             cards=build_mono_color_deck("G", seed=1)),
        Deck(draft_id="r_deck", build_index=0,
             cards=build_mono_color_deck("R", seed=2)),
        Deck(draft_id="w_deck", build_index=0,
             cards=build_mono_color_deck("W", seed=3)),
    ]
    seq = run_match(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=3,
        base_seed=7,
        deck_pool=pool,
    )
    par = run_match_parallel(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=3,
        base_seed=7,
        n_workers=2,
        deck_pool=pool,
    )
    assert seq == par


def test_run_match_parallel_progress_finalizes_on_zero_games(tmp_path: Path):
    """Empty-pool short-circuit still finalizes the tracker — the
    UI shouldn't see a stale 'running' file after a 0-game eval."""
    progress = EvalProgress(
        progress_path=tmp_path / "empty.json",
        run_id="empty",
        n_games_total=0,
        n_workers=1,
    )
    stats = run_match_parallel(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=0,
        n_workers=1,
        progress=progress,
    )
    assert stats.games == 0
    payload = json.loads((tmp_path / "empty.json").read_text(encoding="utf-8"))
    assert payload["status"] == "completed"
    assert payload["ended_at"] is not None
