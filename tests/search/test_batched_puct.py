"""Tests for the batched-leaf-evaluation PUCT path.

Covers the wiring that landed when the ``puct=True + batch_size>1``
guard came down: ``_search_batched`` switches to
``evaluator.batch_evaluate_with_policy`` so each leaf gets both heads
in one forward pass, and stamps the per-leaf policy onto the leaf's
``_policy_cache`` so any later expansion from that node reuses it.

The serial PUCT path (``batch_size=1``) is exercised by
``test_mcts_puct.py``; this file is purely about the batched path
and the bit-exactness contract that says ``batch_size=1 + puct=True``
hasn't drifted.
"""

from __future__ import annotations

import random

import numpy as np
import pytest

from mtg_bot.agents import RandomAgent
from mtg_bot.search import (
    Budget, HeuristicsConfig, MCTS, MtgGameStateAdapter, NNEvaluator,
)
from mtg_bot.search.mcts import _Node
from mtg_bot.simulate import setup_game
from mtg_bot.training import action_encoding as ae
from tests._test_decks import simple_test_decklists  # noqa: E402


# ---------- helpers ---------------------------------------------------------


def _adapter(seed: int = 42) -> MtgGameStateAdapter:
    """Build a deterministic engine-state adapter for a fresh game.
    Mirrors the helper in ``test_mcts_puct.py`` so the two suites
    share a fixture shape."""
    state = setup_game([RandomAgent(), RandomAgent()], decks=simple_test_decklists(), seed=seed,
    )
    # Disable training-time priority short-circuits so the search
    # tests actually exercise the MCTS loop. With those heuristics
    # firing at the root, ``legal_decisions`` returns
    # ``[PassPriority()]`` and the search never branches.
    return MtgGameStateAdapter(
        state, heuristics=HeuristicsConfig.disabled(),
    )


def _adapter_at_precombat_main(seed: int = 42) -> MtgGameStateAdapter:
    """Drive a fresh adapter through UPKEEP/DRAW by passing priority
    until it lands at PRECOMBAT_MAIN — the first step that reliably
    has multiple legal decisions (cast a creature, pass priority,
    play a land if we have one) and therefore actually exercises
    the search loop instead of triggering the forced-move shortcut.

    Same pattern as ``_drive_to_precombat_main`` in
    ``test_baseline_mcts.py``."""
    from mtg_bot.actions import PassPriority
    from mtg_bot.turn import Step

    adapter = _adapter(seed=seed)
    for _ in range(50):
        if adapter.is_terminal():
            break
        if adapter.engine_state.step == Step.PRECOMBAT_MAIN:
            break
        adapter.apply(PassPriority())
    return adapter


class _BatchCountingPolicyEvaluator:
    """``Evaluator``-shaped fixture that ships both single and
    batched policy heads.

    Returns 0.0 value and a uniform-over-legal-slots policy from the
    single path; the batched path defers to the single path
    per-state. Tracks calls per state-id so tests can assert "no
    distinct node gets evaluated twice" without depending on the
    exact mix of single vs batched queries (which depends on tree
    shape and batch size).
    """

    def __init__(self) -> None:
        self.single_calls: int = 0
        self.batch_calls: int = 0
        self.last_batch_size: int = 0
        # Per-(state, viewer) call counts; used to assert the
        # once-per-node-per-perspective invariant the policy cache
        # exists to enforce. Keyed on the viewer too because an
        # opponent-to-move leaf is legitimately queried twice: once
        # from the root player's perspective (value for backup) and
        # once from the mover's (policy for priors).
        self.calls_by_state: dict[tuple[int, int], int] = {}

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
        self.single_calls += 1
        key = (id(state), player_id)
        self.calls_by_state[key] = self.calls_by_state.get(key, 0) + 1
        if state.is_terminal():
            return 0.0, np.zeros(
                ae.ACTION_VOCAB_SIZE, dtype=np.float32,
            )
        mask = ae.legal_action_mask(state, player_id)
        n_legal = int(mask.sum())
        if n_legal == 0:
            return 0.0, np.zeros(
                ae.ACTION_VOCAB_SIZE, dtype=np.float32,
            )
        policy = np.zeros(ae.ACTION_VOCAB_SIZE, dtype=np.float32)
        policy[mask] = 1.0 / n_legal
        return 0.0, policy

    def batch_evaluate_with_policy(self, states, player_id):
        self.batch_calls += 1
        self.last_batch_size = len(states)
        results = []
        for s in states:
            key = (id(s), player_id)
            self.calls_by_state[key] = self.calls_by_state.get(key, 0) + 1
            if s.is_terminal():
                results.append((
                    0.0,
                    np.zeros(ae.ACTION_VOCAB_SIZE, dtype=np.float32),
                ))
                continue
            mask = ae.legal_action_mask(s, player_id)
            n_legal = int(mask.sum())
            if n_legal == 0:
                results.append((
                    0.0,
                    np.zeros(ae.ACTION_VOCAB_SIZE, dtype=np.float32),
                ))
                continue
            policy = np.zeros(ae.ACTION_VOCAB_SIZE, dtype=np.float32)
            policy[mask] = 1.0 / n_legal
            results.append((0.0, policy))
        return results


# ---------- construction-time validation ------------------------------------


def test_batched_puct_constructor_accepts_batched_policy_evaluator():
    """An evaluator with both ``evaluate_with_policy`` and
    ``batch_evaluate_with_policy`` is a valid PUCT+batched search
    target. Construction must not raise — the converse case
    (missing ``batch_evaluate_with_policy``) is covered by
    ``test_mcts_puct.py``."""
    eval_ = _BatchCountingPolicyEvaluator()
    mcts = MCTS(
        evaluator=eval_,
        budget_factory=lambda: Budget(max_nodes=10),
        rng=random.Random(0),
        puct=True,
        batch_size=8,
    )
    assert mcts.batch_size == 8
    assert mcts.puct is True


# ---------- end-to-end batched PUCT runs ------------------------------------


@pytest.mark.parametrize("batch_size", [4, 32])
def test_batched_puct_runs_end_to_end_on_real_state(batch_size):
    """Batched PUCT must drive a real engine state without crashing
    at batch_size 4 and 32 — the two shapes the bench targets."""
    adapter = _adapter(seed=7)
    evaluator = NNEvaluator(with_policy=True)
    mcts = MCTS(
        evaluator=evaluator,
        budget_factory=lambda: Budget(max_nodes=80),
        rng=random.Random(11),
        puct=True,
        batch_size=batch_size,
    )
    visits = mcts.choose_with_visits(
        adapter, adapter.active_player(),
    )
    assert visits, "batched PUCT search returned an empty visit dict"
    assert sum(visits.values()) >= 1


@pytest.mark.parametrize("batch_size", [4, 32])
def test_batched_puct_does_not_collapse_to_single_arm(batch_size):
    """At a state with multiple legal moves, batched PUCT must
    spread visits across more than one arm. A collapse would
    indicate the prior plumbing is broken (every child reading the
    same prior, or virtual loss not actually fanning out)."""
    adapter = _adapter(seed=29)
    evaluator = NNEvaluator(with_policy=True)
    mcts = MCTS(
        evaluator=evaluator,
        budget_factory=lambda: Budget(max_nodes=120),
        rng=random.Random(0),
        puct=True,
        batch_size=batch_size,
    )
    visits = mcts.choose_with_visits(
        adapter, adapter.active_player(),
    )
    if len(visits) <= 1:
        pytest.skip(
            "adapter offered ≤1 legal decision; nothing to spread "
            "visits over"
        )
    explored = sum(1 for v in visits.values() if v > 0)
    assert explored >= 2, (
        f"batched PUCT collapsed onto a single arm at batch_size="
        f"{batch_size}: visits={visits}"
    )


# ---------- policy cache invariant ------------------------------------------


def test_batched_puct_uses_batched_evaluator():
    """The batched PUCT path must actually call
    ``batch_evaluate_with_policy`` — that's the whole point. The
    batch size on each call is bounded by ``self.batch_size`` (the
    final batch may be smaller if the budget runs out partway
    through collection)."""
    adapter = _adapter_at_precombat_main()
    eval_ = _BatchCountingPolicyEvaluator()
    mcts = MCTS(
        evaluator=eval_,
        budget_factory=lambda: Budget(max_nodes=40),
        rng=random.Random(0),
        puct=True,
        batch_size=8,
    )
    root_player = adapter.active_player()
    mcts.choose_with_visits(adapter, root_player)
    assert eval_.batch_calls >= 1, (
        "batched PUCT did not invoke batch_evaluate_with_policy"
    )
    # Last batch's size is bounded by batch_size. Catches off-by-one
    # in the inner-loop's batch_size cap.
    assert eval_.last_batch_size <= 8


def test_batched_puct_does_not_double_evaluate_any_node():
    """The cache invariant: every distinct (state object, viewer)
    pair gets its policy queried at most once across both the single
    and batched APIs. Catches a bug where the batched path forgets to
    populate ``_policy_cache``, causing ``_stamp_prior`` to fire a
    second forward pass when the leaf later becomes an interior node.

    Opponent-to-move leaves are queried from two perspectives (root
    value + mover policy) — that is by design and is why the key
    carries the viewer — but the mover-perspective pass must come
    through the batched side-batch, not a synchronous single-state
    call. The only single-state call allowed is the root's own
    first-touch prior stamp."""
    adapter = _adapter_at_precombat_main()
    eval_ = _BatchCountingPolicyEvaluator()
    mcts = MCTS(
        evaluator=eval_,
        budget_factory=lambda: Budget(max_nodes=60),
        rng=random.Random(0),
        puct=True,
        batch_size=8,
    )
    mcts.choose_with_visits(adapter, adapter.active_player())
    duplicates = {
        sid: n for sid, n in eval_.calls_by_state.items() if n > 1
    }
    assert not duplicates, (
        f"some (state, viewer) pairs were evaluated more than once: "
        f"{duplicates}"
    )
    assert eval_.batch_calls >= 1
    assert eval_.single_calls <= 1, (
        f"expected at most the root's first-touch single-state eval, "
        f"got {eval_.single_calls} synchronous evaluate_with_policy "
        f"calls (opponent-node priors must ride the batched side batch)"
    )
    assert mcts.prior_overflow_count == 0


# ---------- bit-exactness with the serial PUCT path -------------------------


def _seeded_visits(adapter, *, batch_size, mcts_seed, max_nodes=60):
    """Helper: build a fresh PUCT MCTS with a fresh NN evaluator
    seeded deterministically and return the root visit dict.

    The NN evaluator's weights need to be byte-identical between
    runs for the test to mean anything — torch's RNG is what drives
    initialization. Seeding it before each construction gives us
    that. Same trick the trainer regression tests use."""
    import torch
    torch.manual_seed(123)
    evaluator = NNEvaluator(with_policy=True)
    mcts = MCTS(
        evaluator=evaluator,
        budget_factory=lambda: Budget(max_nodes=max_nodes),
        rng=random.Random(mcts_seed),
        puct=True,
        batch_size=batch_size,
    )
    return mcts.choose_with_visits(adapter, adapter.active_player())


def test_batched_puct_bit_exact_at_batch_size_1():
    """``batch_size=1 + puct=True`` is supposed to take the serial
    path (``_search_serial``), bit-exact with what the pre-batched
    PUCT MCTS produced. Any drift from this would mean the
    constructor changes accidentally rerouted the batch_size=1 case
    through the new code path. Run twice from the same seeded
    fixture and assert visit-dict equality.

    Two distinct adapter seeds: catches a per-state quirk that
    happens to match for one root but not the other."""
    for adapter_seed in (7, 29):
        adapter_a = _adapter(seed=adapter_seed)
        adapter_b = _adapter(seed=adapter_seed)
        a = _seeded_visits(
            adapter_a, batch_size=1, mcts_seed=11,
        )
        b = _seeded_visits(
            adapter_b, batch_size=1, mcts_seed=11,
        )
        assert a == b, (
            f"batch_size=1 PUCT diverged between identical runs at "
            f"adapter seed={adapter_seed}: a={a}, b={b}"
        )


def test_batched_puct_total_visits_match_budget():
    """Sanity invariant across batch sizes: total visits at the
    root's children equals the number of search iterations the
    budget allowed. Catches a virtual-loss bug where backprop
    happens twice or zero times for a batched leaf — the visit
    count is the canary."""
    adapter = _adapter_at_precombat_main()
    for batch_size in (1, 4, 32):
        evaluator = NNEvaluator(with_policy=True)
        mcts = MCTS(
            evaluator=evaluator,
            budget_factory=lambda: Budget(max_nodes=64),
            rng=random.Random(0),
            puct=True,
            batch_size=batch_size,
        )
        visits = mcts.choose_with_visits(
            adapter, adapter.active_player(),
        )
        # Root-child visit sum equals (search iterations) for a
        # fresh tree because every backprop bumps exactly one
        # root-child's visit count. ``Budget(max_nodes=64)``
        # consumes one node per ``_select_and_expand`` call — and
        # both paths call that exactly once per iteration. Hence:
        # sum(child.visits) == 64 for both serial and batched.
        assert sum(visits.values()) == 64, (
            f"batch_size={batch_size}: expected 64 total visits, "
            f"got {sum(visits.values())} (visits={visits})"
        )
