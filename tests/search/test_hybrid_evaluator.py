"""Tests for ``mtg_bot.search.hybrid_evaluator`` (head-isolation agents)."""
from __future__ import annotations

import pickle
from dataclasses import dataclass

import numpy as np
import pytest

from mtg_bot.search.evaluator import Evaluator
from mtg_bot.search.hybrid_evaluator import (
    HeuristicValueNNPolicyEvaluator, HybridPimcConfig,
)


class _State:
    """Minimal duck-typed state: terminal flag + winner."""

    def __init__(self, terminal=False, winner=None):
        self._terminal, self._winner = terminal, winner

    def is_terminal(self):
        return self._terminal

    def winner(self):
        return self._winner


class _ConstValue(Evaluator):
    def __init__(self, v):
        self.v = v
        self.calls = 0

    def _evaluate_nonterminal(self, state, player_id):
        self.calls += 1
        return self.v


class _StubPolicyNet:
    """Looks like ``NNEvaluator(with_policy=True)`` to the hybrid."""

    action_encoding_version = "canonical_v2"
    with_policy = True

    def __init__(self):
        self.calls = 0

    def evaluate_with_policy(self, state, player_id):
        self.calls += 1
        pol = np.zeros(4, dtype=np.float32)
        pol[1] = 1.0
        return -0.9, pol  # NN value must be IGNORED by the hybrid

    def batch_evaluate_with_policy(self, states, player_id):
        return [self.evaluate_with_policy(s, player_id) for s in states]


def test_value_comes_from_value_evaluator_policy_from_net():
    val, net = _ConstValue(0.25), _StubPolicyNet()
    h = HeuristicValueNNPolicyEvaluator(val, net)
    s = _State()
    assert h.evaluate(s, 0) == 0.25
    v, p = h.evaluate_with_policy(s, 0)
    assert v == 0.25 and p[1] == 1.0 and p.sum() == 1.0
    assert h.action_encoding_version == "canonical_v2"
    assert h.with_policy is True
    assert net.calls == 1 and val.calls == 2


def test_terminal_short_circuits_value_but_still_returns_policy_vector():
    h = HeuristicValueNNPolicyEvaluator(_ConstValue(0.5), _StubPolicyNet())
    won = _State(terminal=True, winner=0)
    assert h.evaluate(won, 0) == 1.0
    assert h.evaluate(won, 1) == -1.0
    v, p = h.evaluate_with_policy(won, 1)
    assert v == -1.0 and p.shape == (4,)


def test_batch_paths_pair_values_with_policies():
    h = HeuristicValueNNPolicyEvaluator(_ConstValue(0.1), _StubPolicyNet())
    states = [_State(), _State(terminal=True, winner=0), _State()]
    assert h.batch_evaluate(states, 0) == [0.1, 1.0, 0.1]
    pairs = h.batch_evaluate_with_policy(states, 0)
    assert [v for v, _ in pairs] == [0.1, 1.0, 0.1]
    assert all(p[1] == 1.0 for _, p in pairs)


def test_rejects_policy_evaluator_without_policy_method():
    with pytest.raises(ValueError, match="evaluate_with_policy"):
        HeuristicValueNNPolicyEvaluator(_ConstValue(0.0), _ConstValue(0.0))


@dataclass
class _FakeNNCfg:
    with_policy: bool = True
    batch_size: int = 1
    built: int = 0

    def build(self, seed=0):
        from mtg_bot.search.pimc import PIMC

        class _Inner:
            evaluator = _StubPolicyNet()

        return PIMC(inner_factory=lambda: _Inner(), samples=1)

    def to_dict(self):
        return {"with_policy": self.with_policy, "batch_size": self.batch_size}


def test_hybrid_config_requires_policy_capable_nn():
    with pytest.raises(ValueError, match="with_policy=True"):
        HybridPimcConfig(nn=_FakeNNCfg(with_policy=False))


def test_hybrid_config_builds_puct_pimc_and_is_picklable():
    from mtg_bot.search.pimc import PIMC
    cfg = HybridPimcConfig(nn=_FakeNNCfg(), samples=3, inner_nodes=7)
    d = cfg.to_dict()
    assert d["kind"] == "hybrid_heur_value_nn_policy"
    assert d["samples"] == 3 and d["inner_nodes"] == 7 and d["heuristic"] is None
    build = pickle.loads(pickle.dumps(cfg.build))
    strat = build(5)
    assert isinstance(strat, PIMC) and strat.samples == 3
    inner = strat.inner_factory()
    assert inner.puct is True
    assert isinstance(inner.evaluator, HeuristicValueNNPolicyEvaluator)
    assert inner.evaluator.action_encoding_version == "canonical_v2"
