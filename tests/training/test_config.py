"""Tests for ``mtg_bot.training.config``.

Focused on the contract callers depend on: configs are frozen
(hashable), build() produces a working SearchStrategy, JSON round-
trips are exact, and equal configs hash to the same bucket so a
tuning loop can dedupe.
"""

from __future__ import annotations

import pytest

from mtg_bot.search import PIMC, RandomChoice
from mtg_bot.search.heuristic_evaluator import MtgHeuristicEvaluator
from mtg_bot.training.config import (
    HeuristicConfig,
    PimcConfig,
    random_choice_factory,
)


# ---------- HeuristicConfig --------------------------------------------------


def test_heuristic_config_defaults_match_evaluator_defaults():
    cfg = HeuristicConfig()
    assert cfg.life_weight == 0.4
    assert cfg.board_weight == 0.4
    assert cfg.card_weight == 0.15
    assert cfg.mana_dev_weight == 0.05


def test_heuristic_config_is_frozen_and_hashable():
    cfg = HeuristicConfig(life_weight=0.5, board_weight=0.3, card_weight=0.2)
    with pytest.raises(Exception):
        cfg.life_weight = 0.9  # type: ignore[misc]
    # Hashable → usable as dict key.
    bucket: dict = {cfg: "x"}
    assert bucket[
        HeuristicConfig(life_weight=0.5, board_weight=0.3, card_weight=0.2)
    ] == "x"


def test_heuristic_config_build_returns_evaluator_with_normalized_weights():
    cfg = HeuristicConfig(
        life_weight=2.0, board_weight=2.0, card_weight=1.0,
        mana_dev_weight=0.0,
    )
    evaluator = cfg.build()
    assert isinstance(evaluator, MtgHeuristicEvaluator)
    # Evaluator renormalizes — 2/2/1/0 → 0.4/0.4/0.2/0.0 internally.
    assert evaluator.life_weight == pytest.approx(0.4)
    assert evaluator.board_weight == pytest.approx(0.4)
    assert evaluator.card_weight == pytest.approx(0.2)
    assert evaluator.mana_dev_weight == pytest.approx(0.0)


def test_heuristic_config_json_round_trip():
    cfg = HeuristicConfig(life_weight=0.3, board_weight=0.5, card_weight=0.2)
    assert HeuristicConfig.from_dict(cfg.to_dict()) == cfg


# ---------- PimcConfig -------------------------------------------------------


def test_pimc_config_defaults_match_recommend_defaults():
    cfg = PimcConfig()
    assert cfg.samples == 4
    assert cfg.inner_nodes == 200
    assert cfg.heuristic == HeuristicConfig()


def test_pimc_config_build_returns_pimc_strategy():
    cfg = PimcConfig(samples=2, inner_nodes=20)
    strategy = cfg.build(seed=42)
    assert isinstance(strategy, PIMC)
    assert strategy.samples == 2


def test_pimc_config_build_is_deterministic_in_seed():
    """Same config + same seed → produces same RNG state. Two calls
    with seed=42 are independent objects (each new build) but the
    first decision they'd produce must match given the same input."""
    cfg = PimcConfig(samples=1, inner_nodes=8)
    s1 = cfg.build(seed=42)
    s2 = cfg.build(seed=42)
    # Different objects, but their internal RNGs were seeded
    # identically — first random draw must match.
    assert s1.rng.random() == s2.rng.random()


def test_pimc_config_is_frozen_and_hashable():
    cfg = PimcConfig(samples=2, inner_nodes=20)
    with pytest.raises(Exception):
        cfg.samples = 99  # type: ignore[misc]
    bucket: dict = {cfg: "x"}
    assert bucket[PimcConfig(samples=2, inner_nodes=20)] == "x"


def test_pimc_config_json_round_trip():
    cfg = PimcConfig(
        samples=3, inner_nodes=75,
        heuristic=HeuristicConfig(
            life_weight=0.5, board_weight=0.3, card_weight=0.2,
        ),
    )
    assert PimcConfig.from_dict(cfg.to_dict()) == cfg


# ---------- random_choice_factory -------------------------------------------


def test_random_choice_factory_returns_random_choice():
    strategy = random_choice_factory(seed=7)
    assert isinstance(strategy, RandomChoice)


def test_random_choice_factory_seeded():
    s1 = random_choice_factory(seed=7)
    s2 = random_choice_factory(seed=7)
    # Same seed → same RNG draw.
    assert s1.rng.random() == s2.rng.random()
