"""Tests for ``mtg_bot.training.data_gen``.

Unit-tests the contract: shape/dtype/value invariants on the
generated arrays, save/load round-trip, multi-file load, and a
small end-to-end smoke through real games (using tiny PIMC so the
test runs in single-digit seconds).
"""

from __future__ import annotations

import random
from pathlib import Path

import numpy as np

from mtg_bot.agents import RandomAgent
from mtg_bot.features import FEATURE_DIM
from mtg_bot.search.engine_adapter import MtgGameStateAdapter
from mtg_bot.simulate import setup_game
from mtg_bot.training import (
    PimcConfig, generate_training_data, load_all_datasets,
    load_dataset, random_choice_factory, save_dataset,
)
from mtg_bot.training.data_gen import _play_one_game_recording


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


# ---------- A2.3: policy supervision in the npz schema ---------------------


def test_save_and_load_with_policy_roundtrip(tmp_path: Path):
    """Save a dataset with policy_targets + action_masks; load it
    back with ``with_policy=True``; arrays compare equal."""
    from mtg_bot.training.action_encoding import ACTION_VOCAB_SIZE
    n = 4
    features = np.random.rand(n, FEATURE_DIM).astype(np.float32)
    outcomes = np.array([1, -1, 0, 1], dtype=np.float32)
    policy_targets = np.zeros(
        (n, ACTION_VOCAB_SIZE), dtype=np.float32,
    )
    policy_targets[0, 0] = 1.0
    policy_targets[1, 5] = 0.7
    policy_targets[1, 12] = 0.3
    action_masks = np.zeros((n, ACTION_VOCAB_SIZE), dtype=np.bool_)
    action_masks[0, 0] = True
    action_masks[1, [5, 12]] = True
    path = tmp_path / "session.npz"
    save_dataset(
        features, outcomes, path,
        policy_targets=policy_targets, action_masks=action_masks,
    )
    f2, o2, p2, m2 = load_dataset(path, with_policy=True)
    np.testing.assert_array_equal(features, f2)
    np.testing.assert_array_equal(outcomes, o2)
    np.testing.assert_array_equal(policy_targets, p2)
    np.testing.assert_array_equal(action_masks, m2)


def test_load_dataset_old_format_returns_none_for_policy(tmp_path: Path):
    """An old value-only file (no policy_targets key) loads cleanly
    with ``with_policy=True`` — policy/mask come back as ``None``
    so callers can synthesize zero arrays."""
    features = np.zeros((3, FEATURE_DIM), dtype=np.float32)
    outcomes = np.zeros((3,), dtype=np.float32)
    path = tmp_path / "old.npz"
    save_dataset(features, outcomes, path)  # no policy args
    f, o, pols, masks = load_dataset(path, with_policy=True)
    assert pols is None
    assert masks is None


def test_save_dataset_rejects_lonely_policy_arg(tmp_path: Path):
    """``policy_targets`` and ``action_masks`` must come together
    or both omitted — half-supplied is a programming error."""
    import pytest
    from mtg_bot.training.action_encoding import ACTION_VOCAB_SIZE
    f = np.zeros((2, FEATURE_DIM), dtype=np.float32)
    o = np.zeros((2,), dtype=np.float32)
    p = np.zeros((2, ACTION_VOCAB_SIZE), dtype=np.float32)
    with pytest.raises(ValueError, match="must be provided together"):
        save_dataset(
            f, o, tmp_path / "x.npz", policy_targets=p,
        )
    with pytest.raises(ValueError, match="must be provided together"):
        save_dataset(
            f, o, tmp_path / "y.npz",
            action_masks=p.astype(np.bool_),
        )


def test_load_all_datasets_mixed_old_and_new(tmp_path: Path):
    """A directory with one old-format and one new-format file
    loads cleanly with ``include_policy=True``: old rows get
    zero-padded policy supervision so the concatenated arrays
    align row-for-row."""
    from mtg_bot.training.action_encoding import ACTION_VOCAB_SIZE
    # Old-format file (value-only).
    f_old = np.ones((2, FEATURE_DIM), dtype=np.float32)
    o_old = np.array([1, -1], dtype=np.float32)
    save_dataset(f_old, o_old, tmp_path / "a_old.npz")
    # New-format file (with policy).
    f_new = np.full((3, FEATURE_DIM), 2.0, dtype=np.float32)
    o_new = np.array([0, 1, -1], dtype=np.float32)
    p_new = np.zeros((3, ACTION_VOCAB_SIZE), dtype=np.float32)
    p_new[0, 7] = 1.0
    p_new[2, 11] = 1.0
    m_new = np.zeros((3, ACTION_VOCAB_SIZE), dtype=np.bool_)
    m_new[0, [3, 7]] = True
    m_new[2, [11, 99]] = True
    save_dataset(
        f_new, o_new, tmp_path / "b_new.npz",
        policy_targets=p_new, action_masks=m_new,
    )
    f, o, p, m = load_all_datasets(tmp_path, include_policy=True)
    assert f.shape == (5, FEATURE_DIM)
    assert o.shape == (5,)
    assert p.shape == (5, ACTION_VOCAB_SIZE)
    assert m.shape == (5, ACTION_VOCAB_SIZE)
    # First 2 rows from the old file have zero-padded policy supervision.
    assert p[0:2].sum() == 0.0
    assert not m[0:2].any()
    # Last 3 rows have the synthesized policy.
    assert p[2, 7] == 1.0
    assert p[4, 11] == 1.0
    assert m[2, 3]
    assert m[4, 99]


def test_load_all_datasets_default_drops_policy(tmp_path: Path):
    """Default ``include_policy=False`` returns only (features,
    outcomes) even when files contain policy data — backward compat
    with pre-A2.3 callers."""
    from mtg_bot.training.action_encoding import ACTION_VOCAB_SIZE
    f = np.zeros((2, FEATURE_DIM), dtype=np.float32)
    o = np.zeros((2,), dtype=np.float32)
    p = np.zeros((2, ACTION_VOCAB_SIZE), dtype=np.float32)
    m = np.zeros((2, ACTION_VOCAB_SIZE), dtype=np.bool_)
    save_dataset(
        f, o, tmp_path / "x.npz",
        policy_targets=p, action_masks=m,
    )
    out = load_all_datasets(tmp_path)
    assert len(out) == 2
    assert out[0].shape == (2, FEATURE_DIM)
    assert out[1].shape == (2,)


def test_generate_training_data_with_policy_returns_4tuple():
    """``with_policy=True`` produces the 4-tuple schema. Random
    strategies don't have visit counts, so the policy_targets are
    all-zero — but the array still has the right shape."""
    from mtg_bot.training.action_encoding import ACTION_VOCAB_SIZE
    f, o, p, m = generate_training_data(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=2, base_seed=42, with_policy=True,
    )
    n = f.shape[0]
    assert f.shape == (n, FEATURE_DIM)
    assert o.shape == (n,)
    assert p.shape == (n, ACTION_VOCAB_SIZE)
    assert m.shape == (n, ACTION_VOCAB_SIZE)
    # RandomChoice has no visits → all rows are value-only.
    assert p.sum() == 0.0
    assert not m.any()


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


# ---------- deck_pool path --------------------------------------------------


import pytest  # noqa: E402

from mtg_bot.cards.source import get_active_source  # noqa: E402
from mtg_bot.decks import Deck  # noqa: E402
from mtg_bot.training.data_gen import _sample_decks_for_game  # noqa: E402


def build_mono_color_deck(color: str, seed: int | None = None) -> list[str]:
    return get_active_source().build_mono_color_deck(color, seed=seed)


def _two_player_pool() -> list[Deck]:
    """A small pool of distinct mono-color synthetic decks. Cheap
    to build; uses cards we know are in our printing registry."""
    return [
        Deck(draft_id="g_deck", build_index=0,
             cards=build_mono_color_deck("G", seed=1)),
        Deck(draft_id="r_deck", build_index=0,
             cards=build_mono_color_deck("R", seed=2)),
        Deck(draft_id="w_deck", build_index=0,
             cards=build_mono_color_deck("W", seed=3)),
    ]


def test_sample_decks_picks_two_distinct_decks_when_pool_has_multiple():
    pool = _two_player_pool()
    a, b = _sample_decks_for_game(pool, game_idx=0, base_seed=42)
    assert a is not b
    assert a in pool and b in pool


def test_sample_decks_is_deterministic():
    pool = _two_player_pool()
    a1, b1 = _sample_decks_for_game(pool, game_idx=5, base_seed=42)
    a2, b2 = _sample_decks_for_game(pool, game_idx=5, base_seed=42)
    assert a1 is a2 and b1 is b2


def test_sample_decks_varies_with_game_idx():
    """Different game_idx should usually give different deck pairs."""
    pool = _two_player_pool()
    a0, b0 = _sample_decks_for_game(pool, game_idx=0, base_seed=42)
    saw_different = False
    for game_idx in range(1, 10):
        a, b = _sample_decks_for_game(
            pool, game_idx=game_idx, base_seed=42,
        )
        if (a, b) != (a0, b0):
            saw_different = True
            break
    assert saw_different


def test_sample_decks_single_deck_pool_mirrors():
    """Pool with just one deck → both seats get the same deck (mirror)."""
    pool = [
        Deck(draft_id="only", build_index=0,
             cards=build_mono_color_deck("G", seed=0)),
    ]
    a, b = _sample_decks_for_game(pool, game_idx=0, base_seed=0)
    assert a is b


def test_sample_decks_empty_pool_raises():
    with pytest.raises(ValueError, match="empty"):
        _sample_decks_for_game([], game_idx=0, base_seed=0)


def test_generate_training_data_uses_deck_pool():
    """Smoke: sequential data gen with a deck pool produces well-
    shaped arrays + balanced outcomes."""
    pool = _two_player_pool()
    features, outcomes = generate_training_data(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=2, base_seed=42, deck_pool=pool,
    )
    assert features.shape[1] == FEATURE_DIM
    assert features.shape[0] > 0
    assert outcomes.sum() == 0.0


def test_deck_pool_path_parallel_equals_sequential():
    """Strong invariant: parallel and sequential paths produce
    identical arrays for the same deck_pool + base_seed. Per-game
    seeds for deck sampling derive from base_seed + game_idx (not
    worker assignment)."""
    pool = _two_player_pool()
    seq_f, seq_o = generate_training_data(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=3, base_seed=42, deck_pool=pool,
    )
    par_f, par_o = generate_training_data_parallel(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=3, base_seed=42, n_workers=2, deck_pool=pool,
    )
    np.testing.assert_array_equal(seq_f, par_f)
    np.testing.assert_array_equal(seq_o, par_o)


def test_deck_pool_none_falls_back_to_mono_color():
    """deck_pool=None preserves the existing mono-color path —
    regression guard for the existing pipeline."""
    f1, o1 = generate_training_data(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=1, base_seed=42, deck_pool=None,
    )
    f2, o2 = generate_training_data(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=1, base_seed=42,
    )
    np.testing.assert_array_equal(f1, f2)
    np.testing.assert_array_equal(o1, o2)


def test_deck_pool_with_short_decks_works():
    """Real Limited decks are 40 cards, not 60. Verify the engine
    accepts them via the deck_pool path."""
    short_deck = (
        ["Forest"] * 17
        + build_mono_color_deck("G", seed=0)[:23]
    )
    pool = [
        Deck(draft_id="a", build_index=0, cards=short_deck),
        Deck(draft_id="b", build_index=0, cards=short_deck),
    ]
    f, o = generate_training_data(
        p0_factory=random_choice_factory,
        p1_factory=random_choice_factory,
        n_games=1, base_seed=0, deck_pool=pool,
    )
    assert f.shape[1] == FEATURE_DIM
    assert f.shape[0] > 0


# ---------- A2.1: visits captured at sample points ---------------------------


class _FakeStrategyWithVisits:
    """Records that ``choose_with_visits`` was called and returns a
    fixed (synthetic) visit dict so the test can verify the dict is
    forwarded into the per-sample tuple unchanged. Picks a legal
    decision via the adapter so the game still progresses."""

    def __init__(self):
        self.visits_calls = 0

    def choose(self, adapter, player_id):
        legal = list(adapter.legal_decisions())
        return legal[0]

    def choose_with_visits(self, adapter, player_id):
        self.visits_calls += 1
        legal = list(adapter.legal_decisions())
        if not legal:
            return {}
        # Synthetic distribution: first legal decision gets 100
        # visits, the rest get 1 each. Realistic shape, easy to
        # distinguish from a uniform fallback.
        visits = {legal[0]: 100}
        for d in legal[1:]:
            visits[d] = 1
        return visits


def test_play_one_game_recording_captures_visits_at_sample_points():
    """The active player's sample at each sample point should
    carry the strategy's visit dict; the non-active player's
    same-state sample (data-doubling row) should carry ``None``.
    Random / no-visits strategies fall through with ``None``."""
    engine = setup_game(
        [
            RandomAgent(rng=random.Random(11)),
            RandomAgent(rng=random.Random(22)),
        ],
        ["G", "R"], seed=42,
    )
    adapter = MtgGameStateAdapter(
        engine, expose_combat_decisions=True,
    )
    p0 = _FakeStrategyWithVisits()
    p1 = _FakeStrategyWithVisits()
    rng = random.Random(7)

    _, samples = _play_one_game_recording(
        adapter, {0: p0, 1: p1}, rng,
        decision_cap=200, sample_every=1,
    )

    assert len(samples) > 0
    # Either p0 or p1 must have been hit for visits at least once.
    assert p0.visits_calls + p1.visits_calls > 0

    # Per-sample-point grouping: each sample point appends two
    # rows (one per viewer). Find a pair where the active viewer's
    # row carries visits.
    found_with_visits = False
    found_none_partner = False
    for feats, viewer, policy_target, action_mask in samples:
        # A2.3: visits are now encoded into a (ACTION_VOCAB_SIZE,)
        # policy_target array. "Has supervision" = sum > 0.5
        # (a normalized distribution sums to 1.0 + float noise).
        if policy_target.sum() > 0.5:
            found_with_visits = True
            # The synthetic dict was {legal[0]: 100, legal[1]: 1, ...},
            # normalized — the favorite slot ends up with the
            # largest fraction. We just check that the policy is
            # non-zero on at least one slot and that the mask is
            # set on at least one slot.
            assert action_mask.any(), (
                "active row has policy supervision but no legal "
                "slot in the action mask — encoder broken"
            )
        else:
            found_none_partner = True
            # Value-only row: policy_target is all-zero, mask
            # all-False.
            assert not action_mask.any()

    assert found_with_visits, (
        "no sample carried visits — _play_one_game_recording "
        "didn't forward choose_with_visits output"
    )
    assert found_none_partner, (
        "no sample had visits=None — non-active viewer's row "
        "should be value-only"
    )


def test_play_one_game_recording_falls_back_when_visits_empty():
    """If the strategy's ``choose_with_visits`` returns ``{}``
    (e.g. RandomChoice's default), the recording loop must still
    pick a legal decision and record value-only samples (visits=
    None on both rows). Catches a regression where the empty-dict
    path tries to argmax over nothing or skips the sample entirely.
    """
    engine = setup_game(
        [
            RandomAgent(rng=random.Random(11)),
            RandomAgent(rng=random.Random(22)),
        ],
        ["G", "R"], seed=42,
    )
    adapter = MtgGameStateAdapter(
        engine, expose_combat_decisions=True,
    )
    # random_choice_factory returns RandomChoice — its default
    # ``choose_with_visits`` returns ``{}``.
    rng = random.Random(7)
    rs0 = random_choice_factory(0)
    rs1 = random_choice_factory(0)

    _, samples = _play_one_game_recording(
        adapter, {0: rs0, 1: rs1}, rng,
        decision_cap=200, sample_every=1,
    )

    assert len(samples) > 0
    for _feats, _viewer, policy_target, action_mask in samples:
        assert policy_target.sum() == 0.0, (
            "RandomChoice has no visit data; policy target "
            "should be all-zero"
        )
        assert not action_mask.any(), (
            "RandomChoice has no visit data; action mask "
            "should be all-False"
        )
