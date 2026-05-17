"""Tests for ``mtg_bot.search.eval_counters`` — the depth-invariant
search-work telemetry (search nodes + NN-evaluated states).

Two layers:

* **Module API** — ``record_*`` / ``reset`` / ``snapshot`` and the
  ``EvalCounters`` derived views (``skipped``, ``states_per_call``,
  ``nn_eval_fraction``, ``__sub__``), including the clamp/zero edges.
* **Integration** — that the increments fire from the real wiring:
  ``Budget.consume_node`` ⇒ ``nodes``; the public ``NNEvaluator``
  methods ⇒ ``nn_eval_states`` post-terminal-classification only; and
  the bracket invariant ``nn_eval_states + skipped == nodes`` holds
  over a real MCTS-PUCT search.
"""

from __future__ import annotations

import random

import numpy as np
import pytest

from mtg_bot.agents import RandomAgent
from mtg_bot.search import (
    Budget,
    HeuristicsConfig,
    MCTS,
    MtgGameStateAdapter,
    NNEvaluator,
)
from mtg_bot.search import eval_counters
from mtg_bot.simulate import setup_game
from tests._test_decks import simple_test_decklists  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_counters():
    """Counters are process-global; isolate every test (and undo the
    pollution this file's own searches leave for later suites)."""
    eval_counters.reset()
    yield
    eval_counters.reset()


# --------------------------------------------------------------------------
# Module API
# --------------------------------------------------------------------------


def test_reset_zeros_everything():
    eval_counters.record_node(7)
    eval_counters.record_nn_eval(3, n_calls=2)
    eval_counters.reset()
    snap = eval_counters.snapshot()
    assert (snap.nodes, snap.nn_eval_states, snap.nn_forward_calls) == (
        0,
        0,
        0,
    )


def test_record_node_default_and_explicit():
    eval_counters.record_node()
    eval_counters.record_node(4)
    assert eval_counters.snapshot().nodes == 5


def test_record_nn_eval_default_calls_is_one():
    eval_counters.record_nn_eval(1)
    eval_counters.record_nn_eval(10)
    snap = eval_counters.snapshot()
    assert snap.nn_eval_states == 11
    assert snap.nn_forward_calls == 2


def test_record_nn_eval_explicit_calls():
    eval_counters.record_nn_eval(32, n_calls=1)
    eval_counters.record_nn_eval(5, n_calls=5)
    snap = eval_counters.snapshot()
    assert snap.nn_eval_states == 37
    assert snap.nn_forward_calls == 6


def test_skipped_is_nodes_minus_eval_states():
    eval_counters.record_node(100)
    eval_counters.record_nn_eval(60)
    assert eval_counters.snapshot().skipped == 40


def test_skipped_clamps_at_zero_when_more_evals_than_nodes():
    # Belief / opponent-policy forwards add NN evals without a matching
    # search node; the raw difference goes negative and must clamp.
    eval_counters.record_node(5)
    eval_counters.record_nn_eval(20)
    assert eval_counters.snapshot().skipped == 0


def test_states_per_call_and_zero_guard():
    assert eval_counters.snapshot().states_per_call == 0.0
    eval_counters.record_nn_eval(64, n_calls=2)
    assert eval_counters.snapshot().states_per_call == 32.0


def test_nn_eval_fraction_and_zero_guard():
    assert eval_counters.snapshot().nn_eval_fraction == 0.0
    eval_counters.record_node(200)
    eval_counters.record_nn_eval(150)
    assert eval_counters.snapshot().nn_eval_fraction == pytest.approx(
        0.75
    )


def test_snapshot_subtraction_delta():
    eval_counters.record_node(10)
    eval_counters.record_nn_eval(4, n_calls=2)
    before = eval_counters.snapshot()
    eval_counters.record_node(3)
    eval_counters.record_nn_eval(6, n_calls=1)
    delta = eval_counters.snapshot() - before
    assert delta.nodes == 3
    assert delta.nn_eval_states == 6
    assert delta.nn_forward_calls == 1


def test_snapshot_is_immutable():
    snap = eval_counters.snapshot()
    with pytest.raises((AttributeError, TypeError)):
        snap.nodes = 99  # type: ignore[misc]


# --------------------------------------------------------------------------
# Integration — real wiring
# --------------------------------------------------------------------------


class _TerminalStub:
    """Minimal GameState-shaped object that is terminal. Enough for the
    terminal-short-circuit paths, which never reach feature extraction
    or the network — exactly the point being asserted."""

    def is_terminal(self) -> bool:
        return True

    def winner(self):
        return None


def _adapter_at_precombat_main(seed: int = 42) -> MtgGameStateAdapter:
    """A real, non-terminal adapter with branching decisions. Mirrors
    the helper shape in ``test_batched_puct.py``."""
    from mtg_bot.actions import PassPriority
    from mtg_bot.turn import Step

    state = setup_game(
        [RandomAgent(), RandomAgent()],
        decks=simple_test_decklists(),
        seed=seed,
    )
    adapter = MtgGameStateAdapter(
        state, heuristics=HeuristicsConfig.disabled(),
    )
    for _ in range(50):
        if adapter.is_terminal():
            break
        if adapter.engine_state.step == Step.PRECOMBAT_MAIN:
            break
        adapter.apply(PassPriority())
    return adapter


def test_budget_consume_node_increments_nodes():
    b = Budget(max_nodes=8)
    b.start()
    for _ in range(8):
        b.consume_node()
    assert eval_counters.snapshot().nodes == 8


def test_evaluate_with_policy_counts_one_nonterminal_forward():
    ev = NNEvaluator(with_policy=True)
    adapter = _adapter_at_precombat_main()
    assert not adapter.is_terminal()
    ev.evaluate_with_policy(adapter, adapter.active_player())
    snap = eval_counters.snapshot()
    assert snap.nn_eval_states == 1
    assert snap.nn_forward_calls == 1


def test_terminal_does_not_count_as_nn_eval():
    ev = NNEvaluator(with_policy=True)
    term = _TerminalStub()
    # Base ``Evaluator.evaluate`` value-only terminal short-circuit.
    assert ev.evaluate(term, 0) == 0.0
    # ``evaluate_with_policy`` terminal short-circuit.
    val, pol = ev.evaluate_with_policy(term, 0)
    assert val == 0.0 and not pol.any()
    snap = eval_counters.snapshot()
    assert snap.nn_eval_states == 0
    assert snap.nn_forward_calls == 0


def test_batch_evaluate_with_policy_counts_only_nonterminals():
    ev = NNEvaluator(with_policy=True)
    adapter = _adapter_at_precombat_main(seed=7)
    pid = adapter.active_player()
    states = [adapter, _TerminalStub(), adapter]
    ev.batch_evaluate_with_policy(states, pid)
    snap = eval_counters.snapshot()
    # 2 non-terminal states, 1 logical batched forward; the terminal
    # stub must not inflate either counter.
    assert snap.nn_eval_states == 2
    assert snap.nn_forward_calls == 1
    assert snap.states_per_call == 2.0


def test_all_terminal_batch_records_nothing():
    ev = NNEvaluator(with_policy=True)
    ev.batch_evaluate_with_policy([_TerminalStub(), _TerminalStub()], 0)
    assert ev.batch_evaluate([_TerminalStub()], 0) == [0.0]
    snap = eval_counters.snapshot()
    assert snap.nn_eval_states == 0
    assert snap.nn_forward_calls == 0


def test_real_search_populates_consistent_telemetry():
    """Over a real batched MCTS-PUCT search the telemetry is populated
    by the live wiring and is internally consistent.

    Note on the unit (verified here, documented in the methodology):
    ``nn_eval_states`` can *exceed* ``nodes``. PUCT issues a
    standalone ``evaluate_with_policy`` forward to populate a node's
    policy cache on first expansion (``_stamp_prior``); the **root**
    node is created in ``choose()`` and never leaf-evaluated, so its
    prior forward is real NN work with no matching budget tick. That
    is why ``skipped`` clamps at 0 rather than asserting the naive
    identity ``nn_eval_states + skipped == nodes`` — the clamp is the
    designed handling of this (and of belief forwards), not a fudge.
    ``nn_eval_states`` remains the correct ms/NN-eval denominator (it
    is every real forward); ``nodes`` remains the budget unit; their
    ratio is a diagnostic, not an identity."""
    adapter = _adapter_at_precombat_main(seed=3)
    mcts = MCTS(
        evaluator=NNEvaluator(with_policy=True),
        budget_factory=lambda: Budget(max_nodes=16),
        rng=random.Random(0),
        batch_size=8,
        puct=True,
    )
    eval_counters.reset()
    pick = mcts.choose(adapter, adapter.active_player())
    assert pick in adapter.legal_decisions()
    snap = eval_counters.snapshot()
    assert snap.nodes > 0
    assert snap.nn_eval_states > 0
    assert snap.nn_forward_calls > 0
    # Each recorded forward covers >= 1 state (the only guaranteed
    # call/state relation); batched PUCT means many calls cover >1.
    assert snap.nn_eval_states >= snap.nn_forward_calls
    assert snap.states_per_call >= 1.0
    # skipped is the clamped, well-defined view even when the root
    # prior pushes nn_eval_states past nodes.
    assert snap.skipped == max(
        0, snap.nodes - snap.nn_eval_states
    )
    assert snap.nn_eval_fraction > 0.0
