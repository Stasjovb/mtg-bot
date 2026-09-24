"""Tests for the self-play evaluator-kind selector.

Covers the three things that keep a heuristic warm-start corpus from
silently degrading into an NN corpus (or vice-versa):

1. ``normalize_evaluator`` rejects unknown kinds instead of falling
   back to ``"nn"``.
2. ``heuristic_stage_weights()`` is the old-worker interlock: a
   falsy ``weights["p0"]`` is exactly what pre-``evaluator`` worker
   code raises on.
3. ``build_heuristic_pimc_config`` produces the same agent
   ``cli/ladder`` resolves for its ``heuristic`` participant, and
   warns loudly rather than silently no-op'ing when handed a
   Dirichlet alpha it cannot apply.
"""

from __future__ import annotations

import logging

import pytest

from mtg_bot.search.heuristic_evaluator import MtgHeuristicEvaluator
from mtg_bot.search.pimc import PIMC
from mtg_bot.training import HeuristicConfig, PimcConfig
from mtg_bot.training import self_play_evaluator as spe


# ---------------------------------------------------------------------------
# normalize_evaluator / claim_evaluator
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, "nn"),
        ("", "nn"),
        ("nn", "nn"),
        ("NN", "nn"),
        ("heuristic", "heuristic"),
        ("  Heuristic  ", "heuristic"),
    ],
)
def test_normalize_evaluator_accepts_known_kinds(value, expected):
    assert spe.normalize_evaluator(value) == expected


@pytest.mark.parametrize("bad", ["random", "pimc", "nn2", "heuristik"])
def test_normalize_evaluator_rejects_unknown_kind(bad):
    with pytest.raises(ValueError, match="unknown self-play evaluator"):
        spe.normalize_evaluator(bad)


def test_normalize_evaluator_rejects_non_string():
    with pytest.raises(ValueError, match="must be a string"):
        spe.normalize_evaluator(7)


def test_claim_evaluator_defaults_to_nn_for_old_coordinator():
    """A claim from a coordinator that predates the field has no
    ``evaluator`` key at all -> the historical NN behaviour."""
    assert spe.claim_evaluator({"game_idx": 0}) == "nn"
    assert spe.claim_evaluator({"evaluator": None}) == "nn"


def test_claim_evaluator_reads_heuristic():
    assert spe.claim_evaluator({"evaluator": "heuristic"}) == "heuristic"


def test_claim_evaluator_propagates_bad_value():
    with pytest.raises(ValueError):
        spe.claim_evaluator({"evaluator": "nope"})


# ---------------------------------------------------------------------------
# The old-worker interlock
# ---------------------------------------------------------------------------


def test_heuristic_stage_weights_are_falsy_for_both_seats():
    """The weights block must be falsy so an old worker's

        version = weights.get("p0") or weights.get("new")
        if not version: raise RuntimeError(...)

    fires. A placeholder label like "heuristic" would instead send
    the old worker off to fetch /v2/weights/heuristic, and a
    coordinator that happened to have such a dir would run the NN.
    """
    weights = spe.heuristic_stage_weights()
    assert set(weights) == {"p0", "p1"}
    assert not weights["p0"]
    assert not weights["p1"]
    assert not (weights.get("p0") or weights.get("new"))


# ---------------------------------------------------------------------------
# build_heuristic_pimc_config
# ---------------------------------------------------------------------------


def test_build_heuristic_pimc_config_matches_ladder_agent():
    """Same construction ``cli.ladder.resolve_agent('heuristic')``
    uses, so the corpus comes from the agent the ladder measured."""
    cfg = spe.build_heuristic_pimc_config(nodes=100, samples=2)
    assert cfg == PimcConfig(
        samples=2, inner_nodes=100,
        heuristic=HeuristicConfig(), batch_size=1,
    )


def test_build_heuristic_pimc_config_builds_pimc_over_heuristic():
    cfg = spe.build_heuristic_pimc_config(nodes=8, samples=2)
    strategy = cfg.build(seed=3)
    assert isinstance(strategy, PIMC)
    inner = strategy.inner_factory()
    assert isinstance(inner.evaluator, MtgHeuristicEvaluator)


def test_build_heuristic_pimc_config_is_picklable():
    """The bound ``build`` crosses the mp.Pool / PPE boundary."""
    import pickle

    cfg = spe.build_heuristic_pimc_config(nodes=8, samples=2)
    assert pickle.loads(pickle.dumps(cfg.build)) is not None


def test_build_heuristic_pimc_config_carries_dirichlet_knobs():
    cfg = spe.build_heuristic_pimc_config(
        nodes=8, samples=2,
        root_dirichlet_alpha=0.5, root_dirichlet_eps=0.3,
    )
    assert cfg.root_dirichlet_alpha == 0.5
    assert cfg.root_dirichlet_eps == 0.3
    inner = cfg.build(seed=0).inner_factory()
    assert inner.root_dirichlet_alpha == 0.5
    assert inner.root_dirichlet_eps == 0.3
    # ... but UCB1 has no priors to noise, so the knob is inert. This
    # assertion documents that explicitly rather than leaving a
    # silent no-op in the pipeline.
    assert inner.puct is False


def test_build_heuristic_pimc_config_warns_once_about_inert_noise(caplog):
    """Dirichlet noise cannot apply under UCB1; the pipeline says so
    out loud instead of silently dropping it."""
    spe._noise_warned = False
    try:
        with caplog.at_level(logging.WARNING, logger=spe.__name__):
            spe.build_heuristic_pimc_config(
                nodes=8, samples=2, root_dirichlet_alpha=0.5,
            )
            spe.build_heuristic_pimc_config(
                nodes=8, samples=2, root_dirichlet_alpha=0.5,
            )
        warnings = [
            r for r in caplog.records if "root_dirichlet_alpha" in r.message
        ]
        assert len(warnings) == 1, [r.message for r in warnings]
        assert "UCB1" in warnings[0].getMessage()
    finally:
        spe._noise_warned = False


def test_build_heuristic_pimc_config_does_not_warn_without_alpha(caplog):
    spe._noise_warned = False
    try:
        with caplog.at_level(logging.WARNING, logger=spe.__name__):
            spe.build_heuristic_pimc_config(nodes=8, samples=2)
        assert not [
            r for r in caplog.records if "root_dirichlet_alpha" in r.message
        ]
    finally:
        spe._noise_warned = False


def test_build_heuristic_pimc_config_accepts_custom_weights():
    custom = HeuristicConfig(life_weight=0.9, board_weight=0.1)
    cfg = spe.build_heuristic_pimc_config(
        nodes=8, samples=2, heuristic=custom,
    )
    assert cfg.heuristic == custom
