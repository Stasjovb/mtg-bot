"""Root Dirichlet exploration noise for PUCT (feature/lf-training).

- ``root_dirichlet_alpha=None`` (default) is bit-identical to the
  pre-noise search: no RNG draws, same candidates as a default MCTS.
- With ``alpha`` set the root children's priors move away from the
  raw policy but stay a valid mixture (each in [0, 1], total =
  ``(1-eps)*raw_total + eps``).
- Deterministic under a fixed seed; different seeds → different noise.
- Applied exactly once per search, only at the root, only under PUCT,
  on both the serial and batched search paths.
- ``NNPimcConfig`` carries the knobs (to_dict/from_dict, defaults
  None/0.25) and ``build()`` threads them into every PIMC sub-search.
"""

from __future__ import annotations

import random

import numpy as np
import pytest
import torch

from mtg_bot.agents import RandomAgent
from mtg_bot.search import (
    Budget, MCTS, MtgGameStateAdapter, NNEvaluator, PIMC,
)
from mtg_bot.search.protocol import CHANCE_PLAYER
from mtg_bot.simulate import setup_game
from mtg_bot.training import action_encoding as ae
from mtg_bot.training import config as config_mod
from mtg_bot.training.config import NNPimcConfig
from tests._test_decks import simple_test_decklists


# ---------- helpers ---------------------------------------------------------


class _UniformPolicyEvaluator:
    """Uniform-over-legal-slots policy, zero value. Exposes both the
    single and batched with-policy entry points so the same object
    drives ``batch_size=1`` and ``batch_size>1`` searches."""

    def evaluate(self, state, player_id):
        if state.is_terminal():
            winner = state.winner()
            if winner is None:
                return 0.0
            return 1.0 if winner == player_id else -1.0
        return 0.0

    def batch_evaluate(self, states, player_id):
        return [self.evaluate(s, player_id) for s in states]

    def evaluate_with_policy(self, state, player_id):
        if state.is_terminal():
            return 0.0, np.zeros(ae.ACTION_VOCAB_SIZE, dtype=np.float32)
        mask = ae.legal_action_mask(state, player_id)
        n_legal = int(mask.sum())
        policy = np.zeros(ae.ACTION_VOCAB_SIZE, dtype=np.float32)
        if n_legal:
            policy[mask] = 1.0 / n_legal
        return 0.0, policy

    def batch_evaluate_with_policy(self, states, player_id):
        return [self.evaluate_with_policy(s, player_id) for s in states]


class _CountingRandom(random.Random):
    """``random.Random`` that counts ``gammavariate`` calls so tests
    can assert whether (and how often) the Dirichlet draw fired."""

    def __init__(self, seed):
        super().__init__(seed)
        self.gamma_calls = 0

    def gammavariate(self, alpha, beta):
        self.gamma_calls += 1
        return super().gammavariate(alpha, beta)


def _choice_adapter(seed: int, min_legal: int = 3) -> MtgGameStateAdapter:
    """Advance a fresh game with random play until the active player
    has at least ``min_legal`` legal decisions, so the search builds
    a real multi-child root instead of short-circuiting a forced
    move."""
    engine = setup_game(
        [RandomAgent(), RandomAgent()], decks=simple_test_decklists(),
        seed=seed,
    )
    adapter = MtgGameStateAdapter(engine, expose_combat_decisions=True)
    rng = random.Random(seed)
    for _ in range(600):
        if adapter.is_terminal():
            break
        active = adapter.active_player()
        if active == CHANCE_PLAYER:
            outcomes = adapter.chance_outcomes()
            d = rng.choices(
                [d for d, _ in outcomes], weights=[w for _, w in outcomes],
            )[0]
        else:
            legal = list(adapter.legal_decisions())
            if len(legal) >= min_legal:
                return adapter
            d = rng.choice(legal)
        adapter.apply(d)
    pytest.skip("could not reach a multi-option decision point")


def _mcts(seed, *, alpha=None, eps=0.25, nodes=40, batch_size=1, puct=True):
    rng = _CountingRandom(seed)
    m = MCTS(
        evaluator=_UniformPolicyEvaluator(),
        budget_factory=lambda: Budget(max_nodes=nodes),
        rng=rng,
        puct=puct,
        batch_size=batch_size,
        root_dirichlet_alpha=alpha,
        root_dirichlet_eps=eps,
    )
    return m, rng


def _candidates(mcts, adapter):
    chosen, cands = mcts.choose_with_full_stats(
        adapter, adapter.active_player(),
    )
    assert cands, "expected a multi-child root"
    return {c["decision"]: (c["visits"], c["prior"]) for c in cands}


# ---------- construction ----------------------------------------------------


def test_defaults_are_off():
    m, _ = _mcts(0)
    assert m.root_dirichlet_alpha is None
    assert m.root_dirichlet_eps == 0.25


@pytest.mark.parametrize("bad_alpha", [0.0, -1.0])
def test_rejects_non_positive_alpha(bad_alpha):
    with pytest.raises(ValueError, match="root_dirichlet_alpha"):
        _mcts(0, alpha=bad_alpha)


@pytest.mark.parametrize("bad_eps", [-0.1, 1.5])
def test_rejects_eps_outside_unit_interval(bad_eps):
    with pytest.raises(ValueError, match="root_dirichlet_eps"):
        _mcts(0, alpha=0.5, eps=bad_eps)


# ---------- behaviour -------------------------------------------------------


def test_alpha_none_is_bit_identical_to_default_and_draws_nothing():
    adapter = _choice_adapter(seed=3)
    m_default = MCTS(
        evaluator=_UniformPolicyEvaluator(),
        budget_factory=lambda: Budget(max_nodes=40),
        rng=random.Random(9), puct=True,
    )
    m_none, rng_none = _mcts(9, alpha=None)
    assert _candidates(m_default, adapter.clone()) == _candidates(
        m_none, adapter.clone(),
    )
    assert rng_none.gamma_calls == 0


def test_noise_perturbs_root_priors_but_keeps_valid_mixture():
    adapter = _choice_adapter(seed=3)
    eps = 0.25
    raw = _candidates(*_mcts(9, alpha=None)[:1], adapter.clone())
    m_noisy, rng_noisy = _mcts(9, alpha=0.3, eps=eps)
    noisy = _candidates(m_noisy, adapter.clone())

    assert set(raw) == set(noisy)
    assert rng_noisy.gamma_calls == len(noisy)
    raw_priors = np.array([raw[d][1] for d in raw])
    noisy_priors = np.array([noisy[d][1] for d in raw])
    assert not np.allclose(raw_priors, noisy_priors)
    assert np.all(noisy_priors >= 0.0) and np.all(noisy_priors <= 1.0)
    # Dirichlet noise sums to 1, so the mixture total is exact.
    expected_total = (1.0 - eps) * raw_priors.sum() + eps
    assert noisy_priors.sum() == pytest.approx(expected_total, abs=1e-6)
    # Each noisy prior is the mixture of its raw prior and a
    # non-negative noise share: never below (1-eps)*raw.
    assert np.all(noisy_priors >= (1.0 - eps) * raw_priors - 1e-9)


def test_noise_is_deterministic_under_fixed_seed():
    adapter = _choice_adapter(seed=5)
    a = _candidates(_mcts(21, alpha=0.5)[0], adapter.clone())
    b = _candidates(_mcts(21, alpha=0.5)[0], adapter.clone())
    c = _candidates(_mcts(22, alpha=0.5)[0], adapter.clone())
    assert a == b
    assert [a[d][1] for d in a] != [c[d][1] for d in a]


def test_noise_applied_exactly_once_per_search(monkeypatch):
    adapter = _choice_adapter(seed=5)
    m, rng = _mcts(4, alpha=0.5, nodes=120)
    calls = []
    real = m._apply_root_dirichlet_noise

    def spy(root):
        calls.append(len(root.children))
        real(root)

    monkeypatch.setattr(m, "_apply_root_dirichlet_noise", spy)
    cands = _candidates(m, adapter.clone())
    assert calls == [len(cands)]
    assert rng.gamma_calls == len(cands)
    # A second search on the same instance re-arms the latch.
    _candidates(m, adapter.clone())
    assert len(calls) == 2


def test_noise_ignored_without_puct():
    adapter = _choice_adapter(seed=5)
    m, rng = _mcts(4, alpha=0.5, puct=False)
    visits = m.choose_with_visits(adapter.clone(), adapter.active_player())
    assert visits
    assert rng.gamma_calls == 0


def test_batched_search_applies_noise_too():
    adapter = _choice_adapter(seed=7)
    raw = _candidates(_mcts(2, alpha=None, batch_size=4)[0], adapter.clone())
    m, rng = _mcts(2, alpha=0.5, batch_size=4)
    noisy = _candidates(m, adapter.clone())
    assert rng.gamma_calls == len(noisy)
    assert set(raw) == set(noisy)
    assert [raw[d][1] for d in raw] != [noisy[d][1] for d in raw]


def test_eps_zero_leaves_priors_unchanged_but_still_draws():
    adapter = _choice_adapter(seed=3)
    raw = _candidates(_mcts(9, alpha=None)[0], adapter.clone())
    m, rng = _mcts(9, alpha=0.5, eps=0.0)
    noisy = _candidates(m, adapter.clone())
    assert rng.gamma_calls == len(noisy)
    assert [raw[d][1] for d in raw] == pytest.approx(
        [noisy[d][1] for d in raw],
    )


# ---------- NNPimcConfig plumbing -------------------------------------------


def test_nn_pimc_config_defaults_and_round_trip():
    cfg = NNPimcConfig(weights_path="w.pt")
    assert cfg.root_dirichlet_alpha is None
    assert cfg.root_dirichlet_eps == 0.25
    d = cfg.to_dict()
    assert d["root_dirichlet_alpha"] is None
    assert d["root_dirichlet_eps"] == 0.25
    cfg2 = NNPimcConfig(
        weights_path="w.pt", root_dirichlet_alpha=0.5, root_dirichlet_eps=0.1,
    )
    assert NNPimcConfig.from_dict(cfg2.to_dict()) == cfg2
    # Older serialisations without the keys default to off.
    legacy = NNPimcConfig.from_dict(
        {"weights_path": "w.pt", "samples": 4, "inner_nodes": 200},
    )
    assert legacy.root_dirichlet_alpha is None
    assert legacy.root_dirichlet_eps == 0.25


def test_nn_pimc_config_build_threads_noise_into_every_sub_search(
    tmp_path, monkeypatch,
):
    torch.manual_seed(0)
    weights = tmp_path / "policy.pt"
    NNEvaluator(with_policy=True).save(weights)
    seen: list[tuple] = []
    real_mcts = config_mod.MCTS

    class _SpyMCTS(real_mcts):
        def __init__(self, *args, **kwargs):
            seen.append((
                kwargs.get("root_dirichlet_alpha"),
                kwargs.get("root_dirichlet_eps"),
            ))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(config_mod, "MCTS", _SpyMCTS)
    cfg = NNPimcConfig(
        weights_path=str(weights), samples=3, inner_nodes=2, batch_size=1,
        with_policy=True, puct=True,
        root_dirichlet_alpha=0.5, root_dirichlet_eps=0.2,
    )
    strategy = cfg.build(seed=0)
    assert isinstance(strategy, PIMC)
    for _ in range(3):
        strategy.inner_factory()
    assert seen == [(0.5, 0.2)] * 3
    # Default config leaves the sub-searches noise-free (eval path).
    seen.clear()
    NNPimcConfig(
        weights_path=str(weights), samples=1, inner_nodes=2, batch_size=1,
        with_policy=True, puct=True,
    ).build(seed=0).inner_factory()
    assert seen == [(None, 0.25)]
