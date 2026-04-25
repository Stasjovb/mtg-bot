"""Tests for ``mtg_bot.search.pimc.PIMC``.

Strategy: most tests use a fake inner search that returns scripted
visit-count dicts so the wiring (determinize → wrap → inner search →
aggregate) is easy to assert against. Two end-to-end smoke tests
plug real MCTS in to confirm the abstraction holds when something
real runs through it.
"""

from __future__ import annotations

import random

from mtg_bot.agents import RandomAgent
from mtg_bot.game import GameState as EngineGameState, Zone
from mtg_bot.search import (
    PIMC, MCTS, Budget, MtgGameStateAdapter, RandomChoice,
    RandomRolloutEvaluator,
)
from mtg_bot.simulate import setup_game


# ---------- fakes ------------------------------------------------------------


class _ScriptedInner:
    """Inner search whose ``choose_with_visits`` returns a scripted
    dict per call. Records every (state, player_id) it was asked to
    score so tests can assert on the per-world inputs."""

    def __init__(self, visits_per_call: list[dict]) -> None:
        self.scripts = list(visits_per_call)
        self.calls: list[tuple] = []

    def choose_with_visits(self, state, player_id):
        self.calls.append((state, player_id))
        if not self.scripts:
            return {}
        return self.scripts.pop(0)


class _RecordingDeterminizer:
    """Stand-in for ``determinize`` that records its inputs and
    returns a clone of the engine state unchanged. Lets tests verify
    that PIMC calls determinize K times with the right viewer_id and
    independent rngs."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def __call__(self, engine_state, viewer_id, rng):
        self.calls.append((engine_state, viewer_id, rng))
        return engine_state.clone()


# ---------- fixtures ---------------------------------------------------------


def _fresh_adapter(seed: int = 42, **kwargs) -> MtgGameStateAdapter:
    state = setup_game(
        [RandomAgent(), RandomAgent()], ["G", "R"], seed=seed,
    )
    return MtgGameStateAdapter(state, **kwargs)


# ---------- __init__ + input validation -------------------------------------


def test_pimc_rejects_zero_or_negative_samples():
    import pytest
    with pytest.raises(ValueError, match="samples must be >= 1"):
        PIMC(inner_factory=lambda: _ScriptedInner([]), samples=0)
    with pytest.raises(ValueError, match="samples must be >= 1"):
        PIMC(inner_factory=lambda: _ScriptedInner([]), samples=-3)


def test_pimc_rejects_non_adapter_state():
    import pytest
    pimc = PIMC(inner_factory=lambda: _ScriptedInner([{"x": 1}]))

    class NotAnAdapter:
        def legal_decisions(self):
            return ["x"]

    with pytest.raises(TypeError, match="MtgGameStateAdapter"):
        pimc.choose(NotAnAdapter(), player_id=0)


# ---------- forced-move shortcut --------------------------------------------


def test_pimc_forced_move_skips_inner_search():
    """When only one decision is legal, PIMC returns it without
    spinning up any sub-searches. Verified by giving the inner an
    empty script — if it were called, choose() would return the
    fallback first-legal, which happens to coincide here, so we
    additionally assert via the inner's call log."""
    adapter = _fresh_adapter()
    # On a fresh state at UPKEEP, only PassPriority is legal (forced
    # move). Confirm precondition.
    assert len(adapter.legal_decisions()) == 1
    inner = _ScriptedInner([])
    pimc = PIMC(inner_factory=lambda: inner, samples=4)
    decision = pimc.choose(adapter, adapter.active_player())
    assert decision == adapter.legal_decisions()[0]
    assert inner.calls == [], "inner search must not be invoked on forced move"


# ---------- K=1: single sample ----------------------------------------------


def test_pimc_k_equals_1_returns_inner_argmax():
    adapter = _fresh_adapter()
    # Use a stub state where there are multiple legal decisions —
    # advance past the forced upkeep pass.
    while len(adapter.legal_decisions()) == 1 and not adapter.is_terminal():
        adapter.apply(adapter.legal_decisions()[0])
    if adapter.is_terminal():
        return  # state ran to completion before we found a multi-action moment
    legal = adapter.legal_decisions()
    # Script the inner: the second legal decision dominates.
    scripted = {legal[0]: 5, legal[1]: 50, **{d: 1 for d in legal[2:]}}
    inner = _ScriptedInner([scripted])
    pimc = PIMC(
        inner_factory=lambda: inner,
        samples=1,
        rng=random.Random(0),
    )
    pick = pimc.choose(adapter, adapter.active_player())
    assert pick == legal[1]


# ---------- K>1: aggregation across worlds ----------------------------------


def test_pimc_choose_with_visits_returns_aggregated_dict():
    """choose_with_visits should expose the per-decision visit totals
    summed across all K sub-searches (rather than collapsing to the
    single argmax that choose() returns). The recommendation panel
    relies on this to rank and score multiple options."""
    adapter = _fresh_adapter()
    while len(adapter.legal_decisions()) == 1 and not adapter.is_terminal():
        adapter.apply(adapter.legal_decisions()[0])
    if adapter.is_terminal():
        return
    legal = adapter.legal_decisions()
    a, b = legal[0], legal[1]

    def factory():
        return _ScriptedInner([{a: 5, b: 7}])

    pimc = PIMC(
        inner_factory=factory,
        samples=3,
        rng=random.Random(0),
    )
    visits = pimc.choose_with_visits(adapter, adapter.active_player())
    # 3 sub-searches × {a:5, b:7} = {a:15, b:21}.
    assert visits[a] == 15
    assert visits[b] == 21


def test_pimc_choose_with_visits_forced_move_returns_singleton():
    adapter = _fresh_adapter()
    # Fresh state at UPKEEP — only PassPriority is legal.
    assert len(adapter.legal_decisions()) == 1
    inner = _ScriptedInner([])
    pimc = PIMC(inner_factory=lambda: inner, samples=4)
    visits = pimc.choose_with_visits(adapter, adapter.active_player())
    only = adapter.legal_decisions()[0]
    assert visits == {only: 1}
    assert inner.calls == []  # forced-move skipped sub-searches


def test_pimc_aggregates_visit_counts_across_worlds():
    adapter = _fresh_adapter()
    while len(adapter.legal_decisions()) == 1 and not adapter.is_terminal():
        adapter.apply(adapter.legal_decisions()[0])
    if adapter.is_terminal():
        return
    legal = adapter.legal_decisions()
    a, b = legal[0], legal[1]
    # World 1: a=10, b=5  (a wins this world)
    # World 2: a=10, b=5  (a wins this world)
    # World 3: a=10, b=5  (a wins this world)
    # World 4: a=0,  b=100 (b dominates this world)
    # Aggregated: a=30, b=115 → PIMC picks b.
    inner_calls = []

    def factory():
        scripts = [
            {a: 10, b: 5},
            {a: 10, b: 5},
            {a: 10, b: 5},
            {a: 0, b: 100},
        ]
        idx = len(inner_calls)
        s = _ScriptedInner([scripts[idx]])
        inner_calls.append(s)
        return s

    pimc = PIMC(
        inner_factory=factory,
        samples=4,
        rng=random.Random(0),
    )
    pick = pimc.choose(adapter, adapter.active_player())
    assert pick == b
    # K=4 sub-searches were spun up.
    assert len(inner_calls) == 4
    # Each sub-search was called exactly once.
    for s in inner_calls:
        assert len(s.calls) == 1


# ---------- determinize plumbing --------------------------------------------


def test_pimc_calls_determinize_k_times_with_viewer_id():
    adapter = _fresh_adapter()
    while len(adapter.legal_decisions()) == 1 and not adapter.is_terminal():
        adapter.apply(adapter.legal_decisions()[0])
    if adapter.is_terminal():
        return
    legal = adapter.legal_decisions()
    determinizer = _RecordingDeterminizer()
    inner = _ScriptedInner([{legal[0]: 1}] * 3)
    pimc = PIMC(
        inner_factory=lambda: inner,
        samples=3,
        rng=random.Random(0),
        determinize_fn=determinizer,
    )
    pimc.choose(adapter, player_id=0)
    assert len(determinizer.calls) == 3
    for engine_state, viewer_id, _ in determinizer.calls:
        assert engine_state is adapter.engine_state
        assert viewer_id == 0


def test_pimc_uses_independent_rngs_per_sub_search():
    """Each sub-search must get a freshly-seeded ``random.Random`` so
    a single outer RNG fans out into independent sub-tree expansions.
    We assert the rngs PIMC handed to determinize are distinct
    objects (not the same shared rng)."""
    adapter = _fresh_adapter()
    while len(adapter.legal_decisions()) == 1 and not adapter.is_terminal():
        adapter.apply(adapter.legal_decisions()[0])
    if adapter.is_terminal():
        return
    legal = adapter.legal_decisions()
    determinizer = _RecordingDeterminizer()
    inner = _ScriptedInner([{legal[0]: 1}] * 5)
    pimc = PIMC(
        inner_factory=lambda: inner,
        samples=5,
        rng=random.Random(0),
        determinize_fn=determinizer,
    )
    pimc.choose(adapter, player_id=0)
    rngs = [rng for _, _, rng in determinizer.calls]
    # Distinct identities.
    assert len({id(r) for r in rngs}) == 5


# ---------- adapter wrapping passthrough ------------------------------------


def test_pimc_propagates_adapter_config_to_sub_adapters():
    """When the source adapter is constructed with combat / resolution
    exposure, the sub-search adapters PIMC builds must mirror those
    knobs — otherwise the sub-search would see a different decision
    space than the caller is asking about."""
    adapter = _fresh_adapter(
        expose_combat_decisions=True,
        expose_resolution_decisions=True,
    )
    while len(adapter.legal_decisions()) == 1 and not adapter.is_terminal():
        adapter.apply(adapter.legal_decisions()[0])
    if adapter.is_terminal():
        return
    captured: list[MtgGameStateAdapter] = []

    class Capturing:
        def choose_with_visits(self, state, player_id):
            captured.append(state)
            legal = state.legal_decisions()
            return {legal[0]: 1} if legal else {}

    pimc = PIMC(
        inner_factory=Capturing,
        samples=2,
        rng=random.Random(0),
    )
    pimc.choose(adapter, adapter.active_player())
    assert len(captured) == 2
    for sub in captured:
        assert sub._expose_combat is True
        assert sub._expose_resolution is True
        # And they're fresh adapters, not the source.
        assert sub is not adapter


def test_pimc_sub_search_sees_a_different_engine_state_object():
    """Each sub-search should get its own engine state (the determinized
    clone), not a shared reference to the source. Mutating one sub-
    search's state must not affect the source."""
    adapter = _fresh_adapter()
    while len(adapter.legal_decisions()) == 1 and not adapter.is_terminal():
        adapter.apply(adapter.legal_decisions()[0])
    if adapter.is_terminal():
        return
    captured: list[MtgGameStateAdapter] = []

    class Capturing:
        def choose_with_visits(self, state, player_id):
            captured.append(state)
            legal = state.legal_decisions()
            return {legal[0]: 1} if legal else {}

    pimc = PIMC(
        inner_factory=Capturing,
        samples=3,
        rng=random.Random(0),
    )
    pimc.choose(adapter, adapter.active_player())
    source_engine = adapter.engine_state
    for sub in captured:
        assert sub.engine_state is not source_engine


# ---------- fallback ---------------------------------------------------------


def test_pimc_falls_back_when_all_sub_searches_return_empty():
    adapter = _fresh_adapter()
    while len(adapter.legal_decisions()) == 1 and not adapter.is_terminal():
        adapter.apply(adapter.legal_decisions()[0])
    if adapter.is_terminal():
        return
    legal = adapter.legal_decisions()
    inner = _ScriptedInner([{}, {}, {}])
    pimc = PIMC(
        inner_factory=lambda: inner,
        samples=3,
        rng=random.Random(0),
    )
    pick = pimc.choose(adapter, adapter.active_player())
    # Falls back to the first legal decision rather than raising.
    assert pick == legal[0]


# ---------- end-to-end with real MCTS ---------------------------------------


def test_pimc_with_real_mcts_returns_a_legal_decision():
    """Smoke test: drop a real MCTS into PIMC's inner_factory and
    confirm the whole pipeline yields a legal decision against the
    real MTG engine. K and budget kept tiny to bound test time."""
    adapter = _fresh_adapter(seed=11)
    while len(adapter.legal_decisions()) == 1 and not adapter.is_terminal():
        adapter.apply(adapter.legal_decisions()[0])
    if adapter.is_terminal():
        return
    legal = adapter.legal_decisions()

    def make_mcts():
        return MCTS(
            evaluator=RandomRolloutEvaluator(rng=random.Random(7)),
            budget_factory=lambda: Budget(max_nodes=4),
            rng=random.Random(8),
        )

    pimc = PIMC(
        inner_factory=make_mcts, samples=2, rng=random.Random(0),
    )
    pick = pimc.choose(adapter, adapter.active_player())
    assert pick in legal


def test_pimc_with_real_mcts_does_not_mutate_caller_adapter():
    adapter = _fresh_adapter(seed=11)
    while len(adapter.legal_decisions()) == 1 and not adapter.is_terminal():
        adapter.apply(adapter.legal_decisions()[0])
    if adapter.is_terminal():
        return

    pre_turn = adapter.engine_state.turn_number
    pre_step = adapter.engine_state.step
    pre_hand = [
        [c.id for c in p.hand] for p in adapter.engine_state.players
    ]
    pre_library = [
        [c.id for c in p.library] for p in adapter.engine_state.players
    ]

    def make_mcts():
        return MCTS(
            evaluator=RandomRolloutEvaluator(rng=random.Random(0)),
            budget_factory=lambda: Budget(max_nodes=3),
            rng=random.Random(0),
        )

    pimc = PIMC(
        inner_factory=make_mcts, samples=3, rng=random.Random(0),
    )
    pimc.choose(adapter, adapter.active_player())

    assert adapter.engine_state.turn_number == pre_turn
    assert adapter.engine_state.step == pre_step
    post_hand = [
        [c.id for c in p.hand] for p in adapter.engine_state.players
    ]
    post_library = [
        [c.id for c in p.library] for p in adapter.engine_state.players
    ]
    assert post_hand == pre_hand
    assert post_library == pre_library
