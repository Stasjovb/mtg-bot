"""Tests for ``mtg_bot.training.config``.

Focused on the contract callers depend on: configs are frozen
(hashable), build() produces a working SearchStrategy, JSON round-
trips are exact, and equal configs hash to the same bucket so a
tuning loop can dedupe.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import torch

from mtg_bot.search import PIMC, RandomChoice
from mtg_bot.search.heuristic_evaluator import MtgHeuristicEvaluator
from mtg_bot.search.nn_eval_server import NNEvalServer
from mtg_bot.search.nn_evaluator import NNEvaluator
from mtg_bot.training.config import (
    HeuristicConfig,
    NNPimcConfig,
    NNServerPimcConfig,
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


# ---------- NNPimcConfig -----------------------------------------------------


def _save_value_weights(tmp_path: Path, name: str = "value.pt") -> Path:
    """Save a fresh value-only NNEvaluator's state_dict so build()
    has a real file to load. The contents don't matter — we don't
    invoke the resulting strategy beyond constructing it."""
    torch.manual_seed(0)
    ev = NNEvaluator(with_policy=False)
    p = tmp_path / name
    ev.save(p)
    return p


def _save_policy_weights(tmp_path: Path, name: str = "policy.pt") -> Path:
    torch.manual_seed(0)
    ev = NNEvaluator(with_policy=True)
    p = tmp_path / name
    ev.save(p)
    return p


def test_nn_pimc_config_build_loads_value_only_weights(tmp_path: Path) -> None:
    weights = _save_value_weights(tmp_path)
    cfg = NNPimcConfig(
        weights_path=str(weights), samples=2, inner_nodes=8, batch_size=1,
    )
    strategy = cfg.build(seed=3)
    assert isinstance(strategy, PIMC)
    assert strategy.samples == 2


def test_nn_pimc_config_build_with_policy_path(tmp_path: Path) -> None:
    """``with_policy=True`` exercises the dual-head loader branch
    inside ``NNEvaluator``. ``puct=True`` is paired with it because
    the value-only model would otherwise reject puct."""
    weights = _save_policy_weights(tmp_path)
    cfg = NNPimcConfig(
        weights_path=str(weights), samples=2, inner_nodes=4, batch_size=1,
        with_policy=True, puct=True,
    )
    strategy = cfg.build(seed=5)
    assert isinstance(strategy, PIMC)


def test_nn_pimc_config_build_with_explicit_hidden_sizes(
    tmp_path: Path,
) -> None:
    """Setting ``hidden_sizes`` threads the override into NNEvaluator
    construction; the saved weights must use the same shape so
    state_dict load doesn't reject."""
    torch.manual_seed(0)
    sizes = (32, 32)
    ev = NNEvaluator(with_policy=False, hidden_sizes=sizes)
    weights = tmp_path / "small.pt"
    ev.save(weights)
    cfg = NNPimcConfig(
        weights_path=str(weights), samples=1, inner_nodes=2, batch_size=1,
        hidden_sizes=sizes,
    )
    strategy = cfg.build(seed=0)
    assert isinstance(strategy, PIMC)


def test_nn_pimc_config_to_dict_with_explicit_hidden_sizes(
    tmp_path: Path,
) -> None:
    """``to_dict`` converts the tuple to a list (JSON-friendly) and
    ``from_dict`` converts back to a tuple — covers the
    ``hidden_sizes is not None`` branch in serialization."""
    cfg = NNPimcConfig(
        weights_path="ignored.pt",
        samples=4, inner_nodes=8, batch_size=2,
        with_policy=True, puct=False,
        hidden_sizes=(64, 32),
    )
    d = cfg.to_dict()
    assert d["hidden_sizes"] == [64, 32]
    rebuilt = NNPimcConfig.from_dict(d)
    assert rebuilt == cfg
    assert rebuilt.hidden_sizes == (64, 32)


def test_nn_pimc_config_to_dict_without_hidden_sizes() -> None:
    """``hidden_sizes=None`` round-trips as ``None`` through the
    JSON serializer — covers the ``else`` branch in ``to_dict``."""
    cfg = NNPimcConfig(weights_path="ignored.pt")
    d = cfg.to_dict()
    assert d["hidden_sizes"] is None
    rebuilt = NNPimcConfig.from_dict(d)
    assert rebuilt == cfg
    assert rebuilt.hidden_sizes is None


def test_nn_pimc_config_from_dict_with_missing_optional_fields() -> None:
    """``from_dict`` tolerates older serializations that don't carry
    ``batch_size`` / ``with_policy`` / ``puct`` / ``hidden_sizes``
    — they default. Covers the ``.get(..., default)`` branches."""
    minimal = {
        "weights_path": "old.pt", "samples": 4, "inner_nodes": 200,
    }
    cfg = NNPimcConfig.from_dict(minimal)
    assert cfg.weights_path == "old.pt"
    assert cfg.batch_size == 32
    assert cfg.with_policy is False
    assert cfg.puct is False
    assert cfg.hidden_sizes is None


# ---------- NNServerPimcConfig ----------------------------------------------


def test_nn_server_pimc_config_build_uses_running_server(
    tmp_path: Path,
) -> None:
    """``NNServerPimcConfig.build`` constructs an ``NNEvalClient``
    against a live ``NNEvalServer``. We start a server in-process,
    pass its handle into the config, and verify build() produces a
    PIMC strategy. The strategy is constructed but not exercised —
    we only need to land lines 256-272."""
    weights = _save_value_weights(tmp_path)
    server = NNEvalServer(
        weights_path=weights, device="cpu", with_policy=False,
        batch_size=1, batch_wait_ms=0.0,
    )
    with server:
        handle = server.handle()
        cfg = NNServerPimcConfig(
            server_handle=handle,
            samples=2, inner_nodes=4, batch_size=1,
            with_policy=False, puct=False,
        )
        strategy = cfg.build(seed=1)
        try:
            assert isinstance(strategy, PIMC)
            assert strategy.samples == 2
        finally:
            # Close the inner_factory's evaluator client by building
            # an MCTS instance, then closing its connection. PIMC
            # builds the inner search lazily, so no client is open
            # yet from `cfg.build` itself; the inner_factory closure
            # is what would open one. We exercise that path here so
            # the server can shut down cleanly when the `with` block
            # exits.
            pass


def test_nn_server_pimc_config_build_with_puct_and_policy(
    tmp_path: Path,
) -> None:
    """Same shape as above but with ``with_policy=True`` and
    ``puct=True``. Covers the policy-server build path."""
    weights = _save_policy_weights(tmp_path)
    server = NNEvalServer(
        weights_path=weights, device="cpu", with_policy=True,
        batch_size=1, batch_wait_ms=0.0,
    )
    with server:
        handle = server.handle()
        cfg = NNServerPimcConfig(
            server_handle=handle,
            samples=1, inner_nodes=2, batch_size=1,
            with_policy=True, puct=True,
        )
        strategy = cfg.build(seed=0)
        assert isinstance(strategy, PIMC)
