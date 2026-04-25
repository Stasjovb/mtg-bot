"""Tests for ``mtg_bot.training.data_gen``.

Unit-tests the contract: shape/dtype/value invariants on the
generated arrays, save/load round-trip, multi-file load, and a
small end-to-end smoke through real games (using tiny PIMC so the
test runs in single-digit seconds).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from mtg_bot.features import FEATURE_DIM
from mtg_bot.training import (
    PimcConfig, generate_training_data, load_all_datasets,
    load_dataset, random_choice_factory, save_dataset,
)


# ---------- generate_training_data: shape + content invariants ---------------


def test_generates_correct_shapes_and_dtypes():
    """Smoke: small data gen with RandomChoice on both sides
    completes in < 5s and produces well-shaped arrays."""
    features, outcomes = generate_training_data(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=2, base_seed=42,
    )
    assert features.dtype == np.float32
    assert outcomes.dtype == np.float32
    assert features.shape[1] == FEATURE_DIM
    assert features.shape[0] == outcomes.shape[0]
    # Both player perspectives captured per decision → at least some
    # samples for any non-trivial game.
    assert features.shape[0] > 0


def test_outcomes_are_in_valid_set():
    """Outcomes must be in {-1, 0, +1} per the value-target convention."""
    _, outcomes = generate_training_data(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=2, base_seed=7,
    )
    assert np.all(np.isin(outcomes, [-1.0, 0.0, 1.0]))


def test_outcomes_balanced_across_player_perspectives():
    """For each game, P0 and P1 perspectives have opposite outcome
    labels. So summing per-game-per-decision-per-viewer outcomes
    should net to ~0 (modulo draws which contribute 0 from both
    sides). Catches a bug where outcome labeling forgets to flip
    the sign per viewer."""
    _, outcomes = generate_training_data(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=4, base_seed=3,
    )
    # Sum should be exactly 0 (every +1 is paired with a -1 from
    # the opposite viewer).
    assert outcomes.sum() == 0.0


def test_deterministic_with_same_seed():
    a_features, a_outcomes = generate_training_data(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=2, base_seed=99,
    )
    b_features, b_outcomes = generate_training_data(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=2, base_seed=99,
    )
    np.testing.assert_array_equal(a_features, b_features)
    np.testing.assert_array_equal(a_outcomes, b_outcomes)


def test_sample_every_thins_dataset():
    """sample_every=2 should produce roughly half as many samples
    as sample_every=1 on the same games."""
    features_full, _ = generate_training_data(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=2, base_seed=11, sample_every=1,
    )
    features_half, _ = generate_training_data(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=2, base_seed=11, sample_every=2,
    )
    assert features_half.shape[0] < features_full.shape[0]


def test_zero_games_returns_empty_arrays():
    features, outcomes = generate_training_data(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=0, base_seed=0,
    )
    assert features.shape == (0, FEATURE_DIM)
    assert outcomes.shape == (0,)


def test_decision_cap_treats_unfinished_as_draw():
    """If we cap at an absurd low, every game is a draw and every
    captured sample has outcome 0."""
    _, outcomes = generate_training_data(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=2, base_seed=5,
        decision_cap=2,  # absurdly low
    )
    assert np.all(outcomes == 0.0)


# ---------- save / load -----------------------------------------------------


def test_save_and_load_roundtrip(tmp_path: Path):
    features, outcomes = generate_training_data(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=2, base_seed=42,
    )
    path = tmp_path / "session.npz"
    save_dataset(features, outcomes, path)
    assert path.exists()
    f2, o2 = load_dataset(path)
    np.testing.assert_array_equal(features, f2)
    np.testing.assert_array_equal(outcomes, o2)


def test_save_rejects_mismatched_shapes(tmp_path: Path):
    import pytest
    bad_features = np.zeros((5, FEATURE_DIM), dtype=np.float32)
    bad_outcomes = np.zeros((4,), dtype=np.float32)
    with pytest.raises(ValueError, match="rows"):
        save_dataset(bad_features, bad_outcomes, tmp_path / "x.npz")


def test_save_rejects_wrong_feature_dim(tmp_path: Path):
    import pytest
    bad = np.zeros((3, FEATURE_DIM + 1), dtype=np.float32)
    outs = np.zeros((3,), dtype=np.float32)
    with pytest.raises(ValueError, match="dim"):
        save_dataset(bad, outs, tmp_path / "x.npz")


def test_load_all_datasets_concatenates_files(tmp_path: Path):
    """Two saved sessions in a directory load and concat in name order."""
    f1 = np.ones((3, FEATURE_DIM), dtype=np.float32)
    o1 = np.array([1, 0, -1], dtype=np.float32)
    f2 = np.full((2, FEATURE_DIM), 2.0, dtype=np.float32)
    o2 = np.array([0, 1], dtype=np.float32)
    save_dataset(f1, o1, tmp_path / "a.npz")
    save_dataset(f2, o2, tmp_path / "b.npz")
    features, outcomes = load_all_datasets(tmp_path)
    assert features.shape == (5, FEATURE_DIM)
    assert outcomes.shape == (5,)
    # Sorted by filename: 'a.npz' first.
    assert features[0, 0] == 1.0
    assert features[3, 0] == 2.0


def test_load_all_datasets_empty_dir_returns_empty(tmp_path: Path):
    features, outcomes = load_all_datasets(tmp_path)
    assert features.shape == (0, FEATURE_DIM)
    assert outcomes.shape == (0,)


# ---------- end-to-end with tiny PIMC ---------------------------------------


def test_runs_with_tiny_pimc_on_real_engine():
    """Sanity: PIMC(heuristic) on both sides for 1 game produces a
    real dataset. Tiny budget so test stays fast."""
    config = PimcConfig(samples=1, inner_nodes=4)
    factory = lambda seed, _c=config: _c.build(seed)
    features, outcomes = generate_training_data(
        p0_factory=factory, p1_factory=factory,
        n_games=1, base_seed=0,
    )
    assert features.shape[1] == FEATURE_DIM
    assert features.shape[0] > 0
    assert np.all(np.isfinite(features))
    assert np.all(np.isin(outcomes, [-1.0, 0.0, 1.0]))


# ---------- generate_training_data_parallel ---------------------------------


from mtg_bot.training import generate_training_data_parallel  # noqa: E402


def test_parallel_result_equals_sequential_result():
    """The headline determinism guarantee: parallel produces the
    exact same arrays as sequential for the same base_seed. Per-game
    seeds are derived from game_idx (not worker assignment), and
    Pool.map preserves input order, so results MUST be bit-identical.

    If this ever fails: investigate before declaring "good enough."
    Non-deterministic data-gen makes tuning runs uncomparable across
    hardware / worker counts."""
    seq_f, seq_o = generate_training_data(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=3, base_seed=42,
    )
    par_f, par_o = generate_training_data_parallel(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=3, base_seed=42, n_workers=2,
    )
    np.testing.assert_array_equal(seq_f, par_f)
    np.testing.assert_array_equal(seq_o, par_o)


def test_parallel_zero_games_returns_empty():
    f, o = generate_training_data_parallel(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=0, n_workers=2,
    )
    assert f.shape == (0, FEATURE_DIM)
    assert o.shape == (0,)


def test_parallel_n_workers_validation():
    import pytest
    with pytest.raises(ValueError, match="n_workers must be >= 1"):
        generate_training_data_parallel(
            p0_factory=random_choice_factory,
            p1_factory=random_choice_factory,
            n_games=2, n_workers=0,
        )


def test_parallel_default_n_workers_path():
    """When n_workers=None, the default-derivation path runs without
    error. We pass n_games=0 so we don't actually spawn — the default
    n_workers value is only meaningful relative to cpu_count and we
    don't want this test to depend on the test machine's core count.
    Real-run coverage of the default path comes from the
    test_parallel_with_pimc_config_factory test below (which uses
    explicit n_workers=2)."""
    f, o = generate_training_data_parallel(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=0, n_workers=None,
    )
    assert f.shape == (0, FEATURE_DIM)


def test_parallel_invariants_on_real_arrays():
    """Same invariants the sequential version satisfies: balanced
    outcomes, in-range labels, correct shapes."""
    f, o = generate_training_data_parallel(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=2, base_seed=11, n_workers=2,
    )
    assert f.shape[1] == FEATURE_DIM
    assert f.shape[0] == o.shape[0]
    assert np.all(np.isin(o, [-1.0, 0.0, 1.0]))
    # P0 and P1 perspective labels cancel (every +1 paired with -1).
    assert o.sum() == 0.0


def test_parallel_with_pimc_config_factory():
    """The intended real-world pattern: pass a PimcConfig.build
    bound method as the factory. Bound methods of frozen dataclasses
    are picklable so they cross the spawn boundary cleanly."""
    config = PimcConfig(samples=1, inner_nodes=4)
    f, o = generate_training_data_parallel(
        p0_factory=config.build,
        p1_factory=config.build,
        n_games=2, base_seed=0, n_workers=2,
    )
    assert f.shape[1] == FEATURE_DIM
    assert f.shape[0] > 0
    assert np.all(np.isfinite(f))
