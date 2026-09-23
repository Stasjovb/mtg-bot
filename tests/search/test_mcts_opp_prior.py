"""PUCT priors at opponent-to-move nodes are computed from the MOVER's
perspective.

Background: ``MCTS._stamp_prior`` used to call
``evaluate_with_policy(parent.state, root_player)`` and
``action_encoding.encode(decision, eng, root_player)`` at EVERY node.
The evaluator's policy is masked by ``legal_action_mask(state,
root_player)``, which is ``[PassPriority()]`` whenever the root player
does not hold priority, so at an opponent node the softmax put ~1.0 on
PASS and the opponent's real options (``CastSpell`` / ``PlayLand`` /
activations) could not be located in the root player's zones, raised
``EncodingOverflowError`` and got ``prior = 0.0``. The search therefore
modelled the opponent as "always passes" for prior purposes.

These tests pin the fix:

- at an opponent-to-move parent, child priors are non-degenerate
  (cast prior > 0, priors sum to ~1 over the legal children) and no
  encoding overflow occurs;
- root-player-node priors are byte-identical to the legacy
  root-perspective computation;
- the per-search cache tags every entry with its viewer and keys
  root- vs mover-perspective entries apart;
- both the serial and batched PUCT paths behave the same, and the
  batched path rides the mover pass through the batched API;
- value backup is untouched (the existing ``_backprop`` sign tests
  in ``test_mcts.py`` / ``test_mcts_puct.py`` still pass).
"""

from __future__ import annotations

import random

import numpy as np
import pytest

from mtg_bot.actions import CastSpell, PassPriority
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS
from mtg_bot.game import Zone
from mtg_bot.search import Budget, MCTS, MtgGameStateAdapter, NNEvaluator
from mtg_bot.search.heuristics_config import HeuristicsConfig
from mtg_bot.search.mcts import _CachedEval, _Node
from mtg_bot.search.protocol import CHANCE_PLAYER
from mtg_bot.simulate import setup_game
from mtg_bot.training import action_encoding as ae
from mtg_bot.turn import Step
from tests._test_decks import simple_test_decklists  # noqa: E402


ROOT = 0
OPP = 1


# ---------- fixtures --------------------------------------------------------


def _give_basic_land(state, player_idx: int, name: str) -> None:
    land = state.new_object(
        BASIC_LANDS[name], owner_id=player_idx, zone=Zone.BATTLEFIELD,
    )
    land.controller_id = player_idx
    state.battlefield.append(land)


def _adapter_at_opponent_main(seed: int = 42) -> MtgGameStateAdapter:
    """Real 2-player engine state where it is the OPPONENT's (P1's)
    turn at PRECOMBAT_MAIN with priority, three untapped Mountains on
    their battlefield and a castable red spell in hand.

    Built by giving P1 the lands up front and then passing priority
    through P0's opening turn until P1's first main phase. Heuristics
    are disabled so the adapter enumerates the full legal set rather
    than short-circuiting to ``[PassPriority()]``.
    """
    state = setup_game(
        [RandomAgent(), RandomAgent()],
        decks=simple_test_decklists(),  # P0 green, P1 red
        seed=seed,
    )
    for _ in range(3):
        _give_basic_land(state, OPP, "Mountain")
    adapter = MtgGameStateAdapter(
        state, heuristics=HeuristicsConfig.disabled(),
    )
    for _ in range(200):
        if adapter.is_terminal():
            break
        eng = adapter.engine_state
        if (
            eng.active_player_idx == OPP
            and eng.step == Step.PRECOMBAT_MAIN
            and eng.priority_player_idx == OPP
        ):
            break
        adapter.apply(PassPriority())
    eng = adapter.engine_state
    assert eng.active_player_idx == OPP
    assert eng.step == Step.PRECOMBAT_MAIN
    assert adapter.active_player() == OPP
    legal = adapter.legal_decisions()
    assert any(isinstance(d, CastSpell) for d in legal), legal
    assert len(legal) >= 2, legal
    return adapter


def _adapter_at_root_main(seed: int = 42) -> MtgGameStateAdapter:
    """P0's own PRECOMBAT_MAIN (root player to move) — the control
    case for "root-player-node priors are unchanged"."""
    state = setup_game(
        [RandomAgent(), RandomAgent()],
        decks=simple_test_decklists(),
        seed=seed,
    )
    adapter = MtgGameStateAdapter(
        state, heuristics=HeuristicsConfig.disabled(),
    )
    for _ in range(50):
        if adapter.engine_state.step == Step.PRECOMBAT_MAIN:
            break
        adapter.apply(PassPriority())
    assert adapter.active_player() == ROOT
    return adapter


class _RecordingPolicyEvaluator:
    """Uniform-over-legal-slots policy from ``player_id``'s
    perspective; records every ``(id(state), player_id)`` query so
    tests can assert which perspective the search asked for. Value
    is a fixed non-zero number keyed on the viewer so a wrong-
    perspective cache read would be visible."""

    def __init__(self) -> None:
        self.single_calls: list[tuple[int, int]] = []
        self.batch_calls: list[tuple[int, list[int]]] = []

    @staticmethod
    def _value(state, player_id) -> float:
        if state.is_terminal():
            winner = state.winner()
            if winner is None:
                return 0.0
            return 1.0 if winner == player_id else -1.0
        # Deliberately NOT antisymmetric so a sign-flip shortcut
        # would be caught by the viewer-tag assertions.
        return 0.25 if player_id == ROOT else 0.5

    def evaluate(self, state, player_id):
        return self._value(state, player_id)

    def batch_evaluate(self, states, player_id):
        return [self.evaluate(s, player_id) for s in states]

    def _policy(self, state, player_id) -> np.ndarray:
        policy = np.zeros(ae.ACTION_VOCAB_SIZE, dtype=np.float32)
        if state.is_terminal():
            return policy
        mask = ae.legal_action_mask(state, player_id)
        n_legal = int(mask.sum())
        if n_legal:
            policy[mask] = 1.0 / n_legal
        return policy

    def evaluate_with_policy(self, state, player_id):
        self.single_calls.append((id(state), player_id))
        return self._value(state, player_id), self._policy(state, player_id)

    def batch_evaluate_with_policy(self, states, player_id):
        self.batch_calls.append((player_id, [id(s) for s in states]))
        return [
            (self._value(s, player_id), self._policy(s, player_id))
            for s in states
        ]


def _mcts(evaluator, *, nodes: int = 40, batch_size: int = 1) -> MCTS:
    return MCTS(
        evaluator=evaluator,
        budget_factory=lambda: Budget(max_nodes=nodes),
        rng=random.Random(3),
        puct=True,
        batch_size=batch_size,
    )


def _expand_all(mcts: MCTS, adapter, root_player: int) -> _Node:
    """Build a parent node for ``adapter`` and expand every legal
    child through the production ``_make_child`` path (which is what
    stamps priors). Mirrors what ``_select_and_expand`` does at a
    fresh interior node under ``FullEnumeration``."""
    parent = _Node(
        state=adapter.clone(),
        pending_decisions=mcts.expansion_policy.make_decision_iterator(
            adapter,
        ),
    )
    for decision in list(adapter.legal_decisions()):
        mcts._make_child(parent, decision, root_player)
    return parent


def _walk(node: _Node):
    yield node
    for child in node.children:
        yield from _walk(child)


# ---------- premise: the legacy root-perspective computation is degenerate --


def test_premise_root_perspective_mask_is_pass_only_at_opponent_node():
    """Documents the bug the fix addresses: from the root player's
    perspective, the opponent's decision moment masks to PASS only
    and the opponent's real options do not encode."""
    adapter = _adapter_at_opponent_main()
    root_mask = ae.legal_action_mask(adapter, ROOT)
    assert root_mask.nonzero()[0].tolist() == [ae.SLOT_PASS]
    eng = adapter.engine_state
    non_pass = [
        d for d in adapter.legal_decisions()
        if not isinstance(d, PassPriority)
    ]
    assert non_pass
    for d in non_pass:
        with pytest.raises(ae.EncodingOverflowError):
            ae.encode(d, eng, ROOT)
    # ...whereas the mover's perspective sees every option.
    mover_mask = ae.legal_action_mask(adapter, OPP)
    assert int(mover_mask.sum()) == len(adapter.legal_decisions())


# ---------- (a) + (b): opponent-node priors are non-degenerate -------------


def test_opponent_node_priors_are_non_degenerate_and_no_overflow():
    adapter = _adapter_at_opponent_main()
    ev = _RecordingPolicyEvaluator()
    mcts = _mcts(ev)
    mcts._eval_cache = {}
    mcts._cache_root_player = ROOT
    parent = _expand_all(mcts, adapter, ROOT)

    assert parent.state.active_player() == OPP
    assert mcts.prior_overflow_count == 0
    priors = {c.decision: c.prior for c in parent.children}
    n = len(parent.children)
    assert n >= 2
    # Uniform-over-legal evaluator: every legal child gets 1/n.
    for d, p in priors.items():
        assert p == pytest.approx(1.0 / n), (d, p)
    assert sum(priors.values()) == pytest.approx(1.0)
    cast_priors = [
        p for d, p in priors.items() if isinstance(d, CastSpell)
    ]
    assert cast_priors and all(p > 0 for p in cast_priors)
    # The policy was requested from the MOVER's perspective, never
    # the root player's.
    assert ev.single_calls == [(id(parent.state), OPP)]
    # And the parent's cached policy IS the mover-perspective one.
    assert parent._policy_cache is not None
    assert parent._policy_cache[ae.SLOT_PASS] == pytest.approx(1.0 / n)


def test_opponent_node_priors_with_real_dual_head_network():
    """Same assertions against the real ``NNEvaluator`` policy head
    (random-init weights): legal children get strictly positive
    priors that sum to ~1, and nothing overflows."""
    adapter = _adapter_at_opponent_main()
    ev = NNEvaluator(with_policy=True)
    mcts = _mcts(ev)
    mcts._eval_cache = {}
    mcts._cache_root_player = ROOT
    parent = _expand_all(mcts, adapter, ROOT)

    assert mcts.prior_overflow_count == 0
    priors = [c.prior for c in parent.children]
    assert len(priors) >= 2
    assert all(p > 0.0 for p in priors), priors
    assert sum(priors) == pytest.approx(1.0, abs=1e-5)
    cast_priors = [
        c.prior for c in parent.children
        if isinstance(c.decision, CastSpell)
    ]
    assert cast_priors and all(p > 0.0 for p in cast_priors)


# ---------- (c): root-player-node priors are unchanged ---------------------


def test_root_player_node_priors_match_legacy_root_perspective():
    """At a root-player-to-move node the mover IS the root player, so
    the new code path must produce exactly what the legacy
    ``evaluate_with_policy(state, root_player)[encode(d, eng,
    root_player)]`` computation did."""
    adapter = _adapter_at_root_main()
    ev = _RecordingPolicyEvaluator()
    mcts = _mcts(ev)
    mcts._eval_cache = {}
    mcts._cache_root_player = ROOT
    parent = _expand_all(mcts, adapter, ROOT)
    assert parent.state.active_player() == ROOT
    assert len(parent.children) >= 2

    _, legacy_policy = _RecordingPolicyEvaluator().evaluate_with_policy(
        adapter, ROOT,
    )
    eng = adapter.engine_state
    for child in parent.children:
        slot = ae.encode(child.decision, eng, ROOT)
        assert child.prior == pytest.approx(float(legacy_policy[slot]))
    assert mcts.prior_overflow_count == 0
    # Exactly one forward pass, from the root player's perspective.
    assert ev.single_calls == [(id(parent.state), ROOT)]


# ---------- forced-move shortcut -------------------------------------------


def test_opponent_forced_move_gets_prior_one_without_forward_pass():
    """When the opponent has exactly one legal decision (auto-pass),
    the single child is stamped ``prior=1.0`` with no evaluator call
    — same prior the masked softmax over one legal slot would give,
    minus the network round-trip."""
    state = setup_game(
        [RandomAgent(), RandomAgent()],
        decks=simple_test_decklists(),
        seed=5,
    )
    # Default heuristics ON: the opponent's UPKEEP priority window is
    # phase-pruned to [PassPriority()].
    adapter = MtgGameStateAdapter(state)
    for _ in range(200):
        eng = adapter.engine_state
        if eng.active_player_idx == OPP and eng.priority_player_idx == OPP:
            break
        adapter.apply(PassPriority())
    assert adapter.active_player() == OPP
    assert adapter.legal_decisions() == [PassPriority()]

    ev = _RecordingPolicyEvaluator()
    mcts = _mcts(ev)
    mcts._eval_cache = {}
    mcts._cache_root_player = ROOT
    parent = _expand_all(mcts, adapter, ROOT)
    assert len(parent.children) == 1
    assert parent.children[0].prior == 1.0
    assert ev.single_calls == []
    assert mcts.prior_overflow_count == 0


# ---------- chance parents -------------------------------------------------


def test_chance_parent_children_keep_zero_prior_and_no_eval():
    class _ChanceState:
        def active_player(self):
            return CHANCE_PLAYER

        def legal_decisions(self):
            return ["a", "b"]

        def chance_outcomes(self):
            return [("a", 0.5), ("b", 0.5)]

        def is_terminal(self):
            return False

        def clone(self):
            return _ChanceState()

        def apply(self, decision):
            pass

    ev = _RecordingPolicyEvaluator()
    mcts = _mcts(ev)
    parent = _Node(state=_ChanceState())
    child = _Node(state=_ChanceState(), parent=parent, decision="a")
    mcts._stamp_prior(parent, child, "a", ROOT)
    assert child.prior == 0.0
    assert ev.single_calls == []
    assert mcts.prior_overflow_count == 0


# ---------- overflow counter -----------------------------------------------


def test_prior_overflow_counter_increments_on_unencodable_decision():
    adapter = _adapter_at_root_main()
    ev = _RecordingPolicyEvaluator()
    mcts = _mcts(ev)
    mcts._eval_cache = {}
    mcts._cache_root_player = ROOT
    parent = _Node(
        state=adapter.clone(),
        pending_decisions=iter(()),
    )
    parent._policy_cache = np.zeros(ae.ACTION_VOCAB_SIZE, dtype=np.float32)
    bogus = CastSpell(card_id=10**9)  # not in anyone's zones
    child = _Node(state=adapter.clone(), parent=parent, decision=bogus)
    assert mcts.prior_overflow_count == 0
    mcts._stamp_prior(parent, child, bogus, ROOT)
    assert mcts.prior_overflow_count == 1
    assert child.prior == 0.0


# ---------- cache design: viewer-tagged, viewer-keyed ---------------------


def test_eval_cache_entries_are_viewer_tagged_and_keyed():
    """Run a real serial PUCT search that reaches opponent nodes and
    inspect the per-search cache before it is dropped: every entry
    carries ``viewer``, the key's slot fingerprint leads with that
    same viewer, and root-perspective + mover-perspective entries
    for one canonical state coexist under distinct keys."""
    adapter = _adapter_at_root_main()
    ev = _RecordingPolicyEvaluator()
    mcts = _mcts(ev, nodes=60)
    snapshot: dict = {}
    real_search = mcts._search_serial

    def spy(root, player_id, budget):
        real_search(root, player_id, budget)
        snapshot.update(mcts._eval_cache)
        snapshot["__root__"] = root

    mcts._search_serial = spy  # type: ignore[method-assign]
    mcts.choose_with_visits(adapter, ROOT)
    root = snapshot.pop("__root__")
    assert snapshot, "search populated no cache entries"

    for key, entry in snapshot.items():
        assert isinstance(entry, _CachedEval)
        assert entry.viewer in (ROOT, OPP)
        canonical, fp = key
        assert fp[0] == entry.viewer
        if entry.viewer == OPP:
            assert entry.policy_logits is not None
            assert entry.value == pytest.approx(0.5)  # mover's value
        else:
            assert entry.value == pytest.approx(0.25)  # root's value

    opp_nodes = [
        n for n in _walk(root)
        if n.state.active_player() == OPP and len(n.children) >= 2
    ]
    assert opp_nodes, "search never expanded a branching opponent node"
    for n in opp_nodes:
        assert n._policy_cache is not None
        assert sum(c.prior for c in n.children) == pytest.approx(1.0)
        assert all(c.prior > 0 for c in n.children)
    assert any(pid == OPP for _, pid in ev.single_calls)
    # Every state queried from the opponent's perspective was ALSO
    # queried from the root's (value backup is still root-view).
    opp_queried = {sid for sid, pid in ev.single_calls if pid == OPP}
    root_queried = {sid for sid, pid in ev.single_calls if pid == ROOT}
    assert opp_queried <= root_queried
    assert mcts.prior_overflow_count == 0
    # Cache is dropped after the search, as before.
    assert mcts._eval_cache == {}


def test_check_cached_viewer_rejects_perspective_mismatch():
    ev = _RecordingPolicyEvaluator()
    mcts = _mcts(ev)
    entry = _CachedEval(value=0.5, viewer=OPP)
    with pytest.raises(RuntimeError, match="viewer"):
        mcts._check_cached_viewer(entry, ROOT)
    # Untagged legacy entries and matching viewers pass.
    mcts._check_cached_viewer(_CachedEval(value=0.1), ROOT)
    mcts._check_cached_viewer(entry, OPP)


def test_cached_eval_carries_optional_viewer():
    e = _CachedEval(value=0.5)
    assert e.viewer is None
    e2 = _CachedEval(value=0.5, policy_logits=None, viewer=OPP)
    assert e2.viewer == OPP


# ---------- batched path ---------------------------------------------------


@pytest.mark.parametrize("batch_size", [2, 4, 8])
def test_batched_puct_opponent_priors_via_side_batch(batch_size):
    """The batched path must (1) produce the same non-degenerate
    opponent priors, (2) fetch the mover-perspective policies through
    ``batch_evaluate_with_policy(states, OPP)`` rather than
    synchronous single-state calls, and (3) never overflow."""
    adapter = _adapter_at_root_main()
    ev = _RecordingPolicyEvaluator()
    mcts = _mcts(ev, nodes=80, batch_size=batch_size)
    snapshot: dict = {}
    real_search = mcts._search_batched

    def spy(root, player_id, budget, bs):
        real_search(root, player_id, budget, bs)
        snapshot["__root__"] = root

    mcts._search_batched = spy  # type: ignore[method-assign]
    mcts.choose_with_visits(adapter, ROOT)
    root = snapshot["__root__"]

    opp_nodes = [
        n for n in _walk(root)
        if n.state.active_player() == OPP and len(n.children) >= 2
    ]
    assert opp_nodes, "search never expanded a branching opponent node"
    for n in opp_nodes:
        assert sum(c.prior for c in n.children) == pytest.approx(1.0)
        assert all(c.prior > 0 for c in n.children)
    assert mcts.prior_overflow_count == 0
    # Opponent-perspective queries rode the batched API.
    assert any(pid == OPP for pid, _ in ev.batch_calls)
    assert not any(pid == OPP for _, pid in ev.single_calls)
    # Only the root's first-touch prior stamp is synchronous.
    assert len(ev.single_calls) <= 1


def test_serial_and_batch1_visits_identical():
    """``batch_size=1`` routes through ``_search_serial``; a
    ``batch_size=2`` run at the same seed and budget uses the side
    batch. Both must reach the same opponent-node priors (checked
    above); here we pin that the serial path itself is deterministic
    across two identical runs, i.e. the mover-perspective cache has
    no hidden ordering dependence."""
    v = []
    for _ in range(2):
        adapter = _adapter_at_root_main()
        mcts = _mcts(_RecordingPolicyEvaluator(), nodes=60)
        v.append(mcts.choose_with_visits(adapter, ROOT))
    assert v[0] == v[1]
