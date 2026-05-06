"""Monte Carlo Tree Search with UCB1/PUCT selection, chance-node sampling,
and evaluator-at-leaf.

Scope: two-player zero-sum games. Chance nodes are expanded but not
optimized over — MCTS samples an outcome by its declared probability
and keeps descending. This matches the canonical "imperfect but
fast" handling of stochastic games in the MCTS literature.

Final-move policy: pick the root's most-visited child. Standard
MCTS — visits track how much confidence we have, which empirically
outperforms picking the highest-value child (prefers robustness
over lucky-eval).

Injectable pieces:

- ``evaluator``        — state → scalar value at leaves.
- ``expansion_policy`` — controls when/what to expand (full
  enumeration by default; swap in progressive widening or a
  prior-driven policy for large action spaces).
- ``budget_factory``   — time or node cap per ``choose()`` call.

Selection: UCB1 by default (``puct=False``), or AlphaZero-style PUCT
with a network-supplied policy prior (``puct=True``). PUCT requires an
evaluator that implements ``evaluate_with_policy(state, player_id) ->
(value, policy_array)``; ``NNEvaluator(with_policy=True)`` is the
intended source. UCB1 stays bit-exact with the pre-PUCT MCTS so old
benchmarks and tests don't drift.
"""

from __future__ import annotations

import math
import random
from typing import Any, Iterator, Optional

import numpy as np

from mtg_bot.search.budget import Budget
from mtg_bot.search.evaluator import Evaluator
from mtg_bot.search.expansion import ExpansionPolicy, FullEnumeration
from mtg_bot.search.protocol import (
    CHANCE_PLAYER, Decision, GameState, PlayerID,
)
from mtg_bot.search.strategy import SearchStrategy


class _Node:
    """Internal MCTS tree node.

    ``state`` is an independent clone held for expansion/rollouts.
    ``decision`` is the move taken at ``parent`` to reach this node
    (None at the root). ``total_value`` sums values from the
    perspective of the *parent's* active player, which is the player
    who chose to come here — matches UCB1's expected interpretation.

    ``pending_decisions`` is a lazy iterator of decisions that haven't
    been expanded yet at this node. The iterator is built by the
    ``ExpansionPolicy`` and may be truncated — progressive widening
    only pulls it when the policy says a new child is warranted.

    Implemented as a plain ``__slots__`` class (not ``@dataclass``)
    because CPython 3.13's specializing interpreter had a
    reproducible bug against the dataclass-mutation pattern in our
    backprop hot loop (intermittent ``NameError``/``AttributeError``
    crashes). Plain class instances with fixed slots avoid the
    specializer's buggy fast path.
    """

    __slots__ = (
        "state", "parent", "decision", "children",
        "pending_decisions", "visits", "total_value", "virtual_loss",
        "prior", "_policy_cache", "leaf_nn_value",
    )

    def __init__(
        self,
        state: GameState,
        parent: Optional["_Node"] = None,
        decision: Optional[Decision] = None,
        pending_decisions: Optional[Iterator[Decision]] = None,
    ) -> None:
        self.state = state
        self.parent = parent
        self.decision = decision
        self.children: list["_Node"] = []
        self.pending_decisions: Iterator[Decision] = (
            pending_decisions if pending_decisions is not None
            else iter(())
        )
        self.visits: int = 0
        self.total_value: float = 0.0
        # Virtual loss for batched leaf evaluation (B1). Zero when no
        # batched evaluation is in flight through this node.
        # ``_apply_virtual_loss`` increments along the leaf→root path
        # before queuing a leaf for the NN batch; ``_revert_virtual_loss``
        # decrements when the real value comes back. ``ucb1`` and
        # ``mean_value`` consult the *augmented* stats (visits +
        # virtual_loss, total_value - virtual_loss), treating each
        # in-flight evaluation as a worst-case -1 contribution. This
        # discourages other selections in the same batch from
        # converging on the same path. With ``batch_size=1`` (the
        # default), no virtual loss is ever applied — augmented stats
        # equal real stats, and behavior is bit-exact with the
        # pre-batched MCTS.
        self.virtual_loss: int = 0
        # PUCT prior P(s, a): the network's predicted probability that
        # ``self.decision`` is the best move at the parent. Used by
        # ``puct_score``; unused under UCB1. Populated by
        # ``MCTS._make_child`` when ``puct=True`` from the parent's
        # cached policy distribution. 0.0 is the safe default — under
        # UCB1 it's never read, and under PUCT a child whose decision
        # somehow can't be encoded falls through to the small constant
        # exploration the formula provides at large parent-visit
        # counts (better than crashing mid-search).
        self.prior: float = 0.0
        # Cached policy distribution from
        # ``evaluator.evaluate_with_policy(state, root_player)``. Stays
        # ``None`` under UCB1; populated lazily in PUCT mode the first
        # time the node either gets expanded or evaluated as a leaf
        # (whichever happens first). Reused across all subsequent child
        # expansions from this node so the network sees one forward pass
        # per node, not one per child.
        self._policy_cache: Optional[np.ndarray] = None
        # Raw NN value at *this state* the first time it was evaluated
        # as a leaf. Stays ``None`` until the first leaf evaluation
        # backs a value through here. Captured for the search-annotation
        # hook (replay viewer's decision-detail panel) so the user
        # can see what the network thought of each root-child
        # position before MCTS averaged in the rollouts. Always-on:
        # populated regardless of UCB1 vs PUCT; the field is just
        # ignored when the annotator isn't asking. PUCT mode passes
        # through ``evaluate_with_policy`` (value head + cached
        # policy); UCB1 mode passes through ``evaluate`` (value
        # only). Either way the per-node "first leaf value" is the
        # same scalar.
        self.leaf_nn_value: Optional[float] = None

    def is_leaf(self) -> bool:
        return self.state.is_terminal()

    def mean_value(self) -> float:
        n = self.visits + self.virtual_loss
        return (self.total_value - self.virtual_loss) / n if n else 0.0

    def ucb1(self, parent_visits: int, c: float) -> float:
        n = self.visits + self.virtual_loss
        if n == 0:
            return math.inf
        exploit = (self.total_value - self.virtual_loss) / n
        explore = c * math.sqrt(math.log(parent_visits) / n)
        return exploit + explore

    def puct_score(self, parent_visits: int, c: float) -> float:
        """AlphaZero-style PUCT score:

            Q + c · P(s,a) · √N_parent / (1 + N_child)

        where ``Q`` is the running mean value (from the parent's
        perspective, matching ``ucb1``), ``P(s,a)`` is this child's
        prior from the parent's cached policy, and the +1 in the
        denominator keeps the formula finite when ``N_child == 0``.

        At ``N_child == 0`` the exploit term is undefined (no value
        backed up yet); we fall through to pure-prior exploration:
        ``c · P · √N_parent`` (which is exactly the explore term with
        ``1 + N_child = 1``). Differs from UCB1 here, where unvisited
        children return ``+inf`` to force-pick first. PUCT *wants* to
        weight unvisited children by prior — that's the whole point.
        """
        n = self.visits + self.virtual_loss
        explore = c * self.prior * math.sqrt(parent_visits) / (1 + n)
        if n == 0:
            return explore
        exploit = (self.total_value - self.virtual_loss) / n
        return exploit + explore


class MCTS(SearchStrategy):
    """Budget-bounded MCTS with pluggable expansion.

    Call ``choose(state, player_id)`` once per decision. A fresh tree
    is built each call — we don't reuse across decisions yet (would
    need tree pruning and state-identity equality, both deferred).
    """

    def __init__(
        self,
        evaluator: Evaluator,
        budget_factory,
        rng: random.Random | None = None,
        exploration_c: float = math.sqrt(2),
        expansion_policy: Optional[ExpansionPolicy] = None,
        batch_size: int = 1,
        puct: bool = False,
    ) -> None:
        """
        ``evaluator`` scores leaves from ``player_id``'s perspective
        (in ``[-1, 1]``; terminals short-circuit to ±1/0).

        ``budget_factory`` is a zero-arg callable that returns a new
        ``Budget`` — one per ``choose`` call.

        ``exploration_c`` is UCB1's exploration constant. ``√2`` is
        the theoretical default for values in ``[-1, 1]``. Under PUCT
        the same constant scales the prior-weighted explore term;
        AlphaZero's published value is ~1.25–4. ``√2`` is fine as a
        starting point and lets a single MCTS share the constant
        across the two selection rules.

        ``expansion_policy`` controls tree growth. Defaults to
        ``FullEnumeration`` — preserves classic MCTS behavior.
        Swap in ``ProgressiveWidening`` (optionally with a prior)
        for large action spaces.

        ``batch_size`` controls the batched-leaf-evaluation path
        (B1). With ``batch_size=1`` (default), the search iterates
        leaves serially — bit-exact with the pre-batched MCTS, no
        virtual loss applied. With ``batch_size > 1``, the search
        collects up to ``batch_size`` leaves at a time, applies
        virtual loss along each leaf→root path so subsequent
        selections fan out, calls ``evaluator.batch_evaluate`` once
        per batch, then reverts virtual loss and backprops each
        real value. The win shows up when the evaluator has real
        batched compute (NN inference): one ``(B, D)`` forward pass
        is ~5–25× faster than ``B`` single-state forward passes
        because Python↔C overhead amortizes across the batch.
        Heuristic and rollout evaluators see no win from batching
        and should leave ``batch_size=1``.

        ``puct`` switches selection from UCB1 to AlphaZero PUCT:
        ``Q + c · P(s,a) · √N_parent / (1 + N_child)`` where
        ``P(s,a)`` is the network's policy at the parent. Requires
        an evaluator that exposes ``evaluate_with_policy(state,
        player_id) -> (value, np.ndarray)``; we validate that here
        rather than waiting for the first search call to fail.
        ``puct=False`` (default) preserves the classic UCB1 path
        bit-exact — same selection, same backprop, same
        deterministic outcome under a seeded RNG.

        Combination ``puct=True`` + ``batch_size > 1`` is supported:
        ``_search_batched`` routes through
        ``evaluator.batch_evaluate_with_policy`` and stashes each
        leaf's policy on its ``_policy_cache`` so subsequent
        expansions from that node reuse the cached distribution.
        Requires the evaluator to also expose
        ``batch_evaluate_with_policy``; we validate that here too.
        """
        if batch_size < 1:
            raise ValueError(
                f"batch_size must be >= 1, got {batch_size!r}"
            )
        if puct:
            # Construction-time validation: PUCT needs a policy head.
            # ``NNEvaluator(with_policy=True)`` is the canonical
            # source; anything else must duck-type the same method.
            policy_fn = getattr(evaluator, "evaluate_with_policy", None)
            if not callable(policy_fn):
                raise ValueError(
                    "puct=True requires an evaluator with "
                    "evaluate_with_policy(state, player_id); got "
                    f"{type(evaluator).__name__} which does not."
                )
            if batch_size > 1:
                # The batched PUCT path also needs the batched-
                # with-policy entry point. ``NNEvaluator(with_policy
                # =True)`` provides it; anything else must duck-type
                # it. We don't fall back to N single-state calls
                # because the whole point of batch_size>1 is one
                # forward pass per batch — silent fallback would
                # erase the perf win without telling the caller.
                batched_policy_fn = getattr(
                    evaluator, "batch_evaluate_with_policy", None,
                )
                if not callable(batched_policy_fn):
                    raise ValueError(
                        "puct=True with batch_size>1 requires an "
                        "evaluator with batch_evaluate_with_policy("
                        "states, player_id); got "
                        f"{type(evaluator).__name__} which does not."
                    )
        self.evaluator = evaluator
        self.budget_factory = budget_factory
        self.rng = rng or random.Random()
        self.exploration_c = exploration_c
        self.expansion_policy: ExpansionPolicy = (
            expansion_policy if expansion_policy is not None
            else FullEnumeration()
        )
        self.batch_size = batch_size
        self.puct = puct

    def choose(
        self, state: GameState, player_id: PlayerID
    ) -> Decision:
        visits = self.choose_with_visits(state, player_id)
        if not visits:
            # Budget too small to expand even once. Fall back to a
            # random legal decision so the caller still gets an answer.
            return self.rng.choice(list(state.legal_decisions()))
        # Standard MCTS final-move policy: pick the most-visited child.
        return max(visits.items(), key=lambda kv: kv[1])[0]

    def choose_with_full_stats(
        self, state: GameState, player_id: PlayerID,
    ) -> tuple[
        Optional[Decision],
        list[dict[str, Any]],
    ]:
        """Run a search and return the chosen decision plus per-root-
        child stats for the search-annotation hook.

        Returns ``(chosen_decision_or_None, candidates)``. Each
        candidate dict carries ``decision`` (the action), ``visits``
        (int), ``q`` (Q from the root's perspective — the parent's
        active-player view, matching ``mean_value`` semantics — None
        when ``visits == 0``), ``prior`` (PUCT prior; None outside
        PUCT mode), and ``leaf_value`` (the raw NN value at the
        child's state on its first leaf evaluation; None when the
        child was never expanded as a leaf, e.g. budget too small,
        or when the evaluator doesn't expose a usable per-state
        scalar).

        ``chosen_decision`` is the most-visited root child (matches
        ``choose``); ``None`` when no children were expanded (budget
        too small) so callers can fall back to a legal default.

        Forced moves: when only one legal decision exists, returns
        ``(decision, [{"decision": d, "visits": 1, "q": None,
        "prior": None, "leaf_value": None}])``. The synthetic shape
        keeps the annotation present (so the viewer panel still
        renders) even though no tree was built.
        """
        legal = list(state.legal_decisions())
        if len(legal) == 1:
            decision = legal[0]
            return (
                decision,
                [
                    {
                        "decision": decision,
                        "visits": 1,
                        "q": None,
                        "prior": None,
                        "leaf_value": None,
                    }
                ],
            )

        root = _Node(
            state=state.clone(),
            pending_decisions=self.expansion_policy.make_decision_iterator(
                state
            ),
        )

        budget = self.budget_factory()
        budget.start()
        if self.batch_size == 1:
            self._search_serial(root, player_id, budget)
        else:
            self._search_batched(
                root, player_id, budget, self.batch_size,
            )

        candidates = [
            {
                "decision": child.decision,
                "visits": child.visits,
                "q": child.mean_value() if child.visits > 0 else None,
                "prior": child.prior if self.puct else None,
                "leaf_value": child.leaf_nn_value,
            }
            for child in root.children
        ]
        if not candidates:
            return (None, [])
        chosen = max(
            root.children, key=lambda c: c.visits,
        ).decision
        return (chosen, candidates)

    def choose_with_visits(
        self, state: GameState, player_id: PlayerID
    ) -> dict[Decision, int]:
        """Run a search and return ``{decision: visit_count}`` over the
        root's expanded children.

        Used by ensemble wrappers (PIMC) that need to aggregate visits
        across multiple independent searches before picking a final
        move. Returns an empty dict when the budget was too small to
        expand any child — callers should fall back to a legal default.

        Forced moves (exactly one legal decision) short-circuit the
        search and report a synthetic ``{decision: 1}``. The "1" is a
        placeholder so caller aggregation doesn't need a special case;
        nothing should compare a forced-move count against a real
        search's count.
        """
        # Forced-move shortcut: if there's exactly one legal decision,
        # take it. Computed eagerly up front because it's cheap and
        # lets us skip the whole tree build for trivial priority
        # moments (MTG has lots of these — "only PassPriority legal"
        # is the common case during upkeep/draw/combat).
        legal = list(state.legal_decisions())
        if len(legal) == 1:
            return {legal[0]: 1}

        root = _Node(
            state=state.clone(),
            pending_decisions=self.expansion_policy.make_decision_iterator(
                state
            ),
        )

        budget = self.budget_factory()
        budget.start()
        if self.batch_size == 1:
            self._search_serial(root, player_id, budget)
        else:
            self._search_batched(
                root, player_id, budget, self.batch_size,
            )

        return {c.decision: c.visits for c in root.children}

    def _search_serial(
        self, root: _Node, player_id: PlayerID, budget,
    ) -> None:
        """Today's iteration loop, factored out for symmetry with
        ``_search_batched``. Bit-exact with the pre-batching MCTS
        — no virtual loss is applied along the way.

        ``player_id`` is also the *root player* in PUCT mode and gets
        threaded down to ``_select_and_expand`` / ``_evaluate_leaf``
        so the policy head sees the search from the same viewer
        perspective at every node."""
        while not budget.exhausted():
            leaf = self._select_and_expand(root, player_id)
            value = self._evaluate_leaf(leaf, player_id)
            self._backprop(leaf, value, player_id)
            budget.consume_node()

    def _search_batched(
        self, root: _Node, player_id: PlayerID, budget,
        batch_size: int,
    ) -> None:
        """Collect up to ``batch_size`` leaves with virtual loss,
        evaluate them in one ``batch_evaluate`` call, revert virtual
        loss, and backprop each real value. See ``__init__`` for
        the design rationale. Terminal leaves short-circuit to the
        evaluator's terminal handling and are backpropped
        immediately without entering the batch (no NN value to
        wait on).

        Under PUCT (``self.puct=True``), the batched evaluator is
        ``batch_evaluate_with_policy`` rather than ``batch_evaluate``
        — one forward pass yields both heads for every leaf. Each
        leaf's policy gets stashed on ``_Node._policy_cache`` so
        when the leaf later becomes an interior node and starts
        expanding children, ``_stamp_prior`` reads the cached
        distribution rather than triggering a second forward pass.
        That preserves the "exactly one policy query per node"
        invariant that the serial PUCT path enforces via
        ``_evaluate_leaf``.

        Cache invariant under batching: a pending leaf has no
        ``_policy_cache`` yet (it's queued for the upcoming batch
        call). If the next ``_select_and_expand`` would descend
        through a still-pending leaf and try to expand a grandchild,
        ``_stamp_prior`` would have to fire a synchronous single-
        state forward pass — defeating the cache. We avoid this by
        flushing the batch early: if the descent is about to enter
        a pending leaf, we break out of inner-loop collection,
        fire ``batch_evaluate_with_policy``, populate the leaves'
        caches, and then resume collecting. The effective batch
        size is bounded by both ``batch_size`` and the tree's
        breadth at the current frontier.
        """
        while not budget.exhausted():
            pending: list[_Node] = []
            pending_set: set[int] = set()
            terminal_results: list[tuple[_Node, float]] = []
            # Collect a batch worth of leaves. Each non-terminal
            # leaf gets virtual loss applied so the next selection
            # in this batch sees a degraded UCB1 score on the path
            # we're already evaluating.
            for _ in range(batch_size):
                if budget.exhausted():
                    break
                # The pending_blockers set is consulted only in the
                # PUCT path (see _select_and_expand) to keep the cache
                # invariant. Under UCB1 it's harmlessly ignored — the
                # set is cheap to build either way.
                leaf = self._select_and_expand(
                    root, player_id, pending_blockers=pending_set,
                )
                if leaf is None:
                    # ``_select_and_expand`` aborted because it would
                    # have descended into a still-pending leaf. Fire
                    # the batch we've collected so far, populate the
                    # caches, then restart the outer loop to continue
                    # collecting from a fresh state.
                    break
                budget.consume_node()
                if leaf.is_leaf():
                    # Terminal — evaluator short-circuits to ±1/0
                    # without touching the network. Backprop
                    # immediately; no virtual loss needed because
                    # nothing's pending on this leaf.
                    value = self._evaluate_leaf(leaf, player_id)
                    terminal_results.append((leaf, value))
                else:
                    self._apply_virtual_loss(leaf)
                    pending.append(leaf)
                    pending_set.add(id(leaf))

            # Backprop terminal leaves first — they have real
            # values immediately. Order doesn't affect correctness.
            for leaf, value in terminal_results:
                self._backprop(leaf, value, player_id)

            # Batch-evaluate the non-terminal leaves and backprop.
            if pending:
                states = [leaf.state for leaf in pending]
                if self.puct:
                    # One forward pass, both heads. Each (value,
                    # policy) pair lines up with the matching leaf
                    # by index. Stash the policy on the leaf so
                    # subsequent expansions from that node read the
                    # cached distribution and don't trigger a
                    # second forward pass.
                    pairs = self.evaluator.batch_evaluate_with_policy(
                        states, player_id,
                    )
                    for leaf, (value, policy) in zip(pending, pairs):
                        if leaf._policy_cache is None:
                            leaf._policy_cache = policy
                        if leaf.leaf_nn_value is None:
                            leaf.leaf_nn_value = float(value)
                        self._revert_virtual_loss(leaf)
                        self._backprop(leaf, value, player_id)
                else:
                    values = self.evaluator.batch_evaluate(
                        states, player_id,
                    )
                    for leaf, value in zip(pending, values):
                        if leaf.leaf_nn_value is None:
                            leaf.leaf_nn_value = float(value)
                        self._revert_virtual_loss(leaf)
                        self._backprop(leaf, value, player_id)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _select_and_expand(
        self, root: _Node, root_player: PlayerID,
        pending_blockers: Optional[set[int]] = None,
    ) -> Optional[_Node]:
        """Walk down the tree until we find a node to score.

        - At chance nodes, sample an outcome by its probability and
          descend (creating a new child if needed).
        - At real-player nodes, ask the ``ExpansionPolicy`` whether
          to add a new child. If yes and the pending-iterator has
          more decisions, expand and return the new child.
        - Otherwise, descend into the UCB1-best existing child
          (or PUCT-best when ``self.puct``).
        - At terminals, return as-is.

        ``root_player`` flows through to ``_make_child`` so PUCT
        priors are computed from the root viewer's perspective
        regardless of whose turn it is at the descent node — the
        policy head's "what does it think *I* should do" is more
        useful than per-active-player priors that flip every node.

        ``pending_blockers`` (PUCT-only) is the id-set of leaves
        currently in the in-flight batch. If a descent would land
        on (or pass through) one of these nodes, expansion of its
        children would require a not-yet-populated policy cache —
        breaking the "no double evaluation" invariant. Returning
        ``None`` signals the caller to flush the current batch
        before continuing. Under UCB1 the set is ignored.
        """
        node = root
        while not node.is_leaf():
            if node.state.active_player() == CHANCE_PLAYER:
                node = self._descend_chance(node, root_player)
                continue

            expanded = self._try_expand(node, root_player)
            if expanded is not None:
                return expanded

            if not node.children:
                # No children to descend into and policy refused to
                # expand — dead end. Return this node as the leaf
                # so evaluation still happens. (Shouldn't arise
                # under FullEnumeration; a badly-tuned
                # ProgressiveWidening could get here if it caps
                # children at 0.)
                return node
            # Fully widened (per policy) — UCB1 / PUCT descent.
            # Parent visits is the augmented count (real +
            # virtual_loss) so the exploration term reflects
            # pending in-flight evaluations during batched search;
            # identical to today when virtual_loss is zero
            # everywhere.
            parent_n = node.visits + node.virtual_loss
            if self.puct:
                node = max(
                    node.children,
                    key=lambda c: c.puct_score(
                        parent_n, self.exploration_c,
                    ),
                )
                # Cache-invariant guard: if we're about to descend
                # into a leaf that's still queued for the in-flight
                # batch, its ``_policy_cache`` is empty. Expanding
                # one of its grandchildren would force ``_stamp_prior``
                # to fire a synchronous single-state forward pass
                # — exactly the duplicate eval the caller is trying
                # to prevent. Signal "flush the batch first".
                if (
                    pending_blockers is not None
                    and id(node) in pending_blockers
                ):
                    return None
            else:
                node = max(
                    node.children,
                    key=lambda c: c.ucb1(parent_n, self.exploration_c),
                )
        return node

    def _try_expand(
        self, node: _Node, root_player: PlayerID,
    ) -> Optional[_Node]:
        """If the policy permits and the pending iterator has more,
        expand a new child and return it. Otherwise return None."""
        if not self.expansion_policy.should_expand(node):
            return None
        try:
            decision = next(node.pending_decisions)
        except StopIteration:
            return None
        return self._make_child(node, decision, root_player)

    def _make_child(
        self,
        parent: _Node,
        decision: Decision,
        root_player: PlayerID,
    ) -> _Node:
        """Build and attach a new child for ``decision`` at
        ``parent``. The child's pending-decisions iterator is
        freshly built from the expansion policy.

        Under PUCT, also stamp the child's ``prior`` from the
        parent's cached policy distribution (computing the
        distribution on first call). Encoding errors are tolerated:
        an unencodable decision (an action-vocab gap or a decision
        that legality enumerated but the codec doesn't know how to
        place) leaves ``prior=0.0``, which means PUCT treats it as
        no-prior — explore by visit-count alone. That's a soft
        failure rather than a crash because legality and
        encodability can drift slightly under engine evolution and
        we'd rather lose a little selection signal than abort the
        search.
        """
        child_state = parent.state.clone()
        child_state.apply(decision)
        pending = (
            self.expansion_policy.make_decision_iterator(child_state)
            if not child_state.is_terminal() else iter(())
        )
        child = _Node(
            state=child_state,
            parent=parent,
            decision=decision,
            pending_decisions=pending,
        )
        if self.puct:
            self._stamp_prior(parent, child, decision, root_player)
        parent.children.append(child)
        return child

    def _stamp_prior(
        self,
        parent: _Node,
        child: _Node,
        decision: Decision,
        root_player: PlayerID,
    ) -> None:
        """Set ``child.prior`` from ``parent._policy_cache[encode(d)]``,
        populating the cache on first call.

        Lazy-imported codec because ``mtg_bot.training`` pulls in
        ``mtg_bot.search`` at package init — importing at module load
        would create a cycle. By the time any search runs the cycle
        has resolved.
        """
        if parent._policy_cache is None:
            _, policy = self.evaluator.evaluate_with_policy(
                parent.state, root_player,
            )
            parent._policy_cache = policy
        from mtg_bot.training import action_encoding as ae
        eng = getattr(parent.state, "engine_state", parent.state)
        try:
            slot = ae.encode(decision, eng, root_player)
        except ae.EncodingOverflowError:
            # Decision didn't fit in the fixed vocab. Leave prior 0;
            # PUCT will explore by visit-count alone for this child.
            return
        child.prior = float(parent._policy_cache[slot])

    def _descend_chance(
        self, node: _Node, root_player: PlayerID,
    ) -> _Node:
        """Sample a chance outcome, either picking the existing
        child for that outcome or creating one."""
        outcomes = node.state.chance_outcomes()
        decisions = [d for d, _ in outcomes]
        weights = [w for _, w in outcomes]
        decision = self.rng.choices(decisions, weights=weights, k=1)[0]
        for child in node.children:
            if child.decision == decision:
                return child
        # First time we sampled this outcome — create the child.
        # Chance nodes don't have a meaningful policy prior (they
        # aren't a real player's choice), so PUCT priors at chance
        # children stay 0.0. They never get UCB-selected anyway —
        # they're sampled by weight.
        return self._make_child(node, decision, root_player)

    def _evaluate_leaf(
        self, leaf: _Node, root_player: PlayerID
    ) -> float:
        """Return the leaf's value from ``root_player``'s perspective,
        in ``[-1, 1]``. The evaluator handles terminal vs non-terminal
        internally.

        Under PUCT we route through ``evaluate_with_policy`` so the
        single forward pass produces both heads at once; the policy
        gets cached on the leaf for any future expansion from this
        node, avoiding a second forward pass when the leaf later
        becomes an interior node. Terminal leaves still go through
        the value-only path because the policy head is undefined
        there (no legal action; ``evaluate_with_policy`` returns the
        all-zeros vector for terminals, which we don't bother
        caching — a terminal never gets expanded).
        """
        if self.puct and not leaf.is_leaf():
            value, policy = self.evaluator.evaluate_with_policy(
                leaf.state, root_player,
            )
            if leaf._policy_cache is None:
                leaf._policy_cache = policy
            if leaf.leaf_nn_value is None:
                leaf.leaf_nn_value = float(value)
            return value
        value = self.evaluator.evaluate(leaf.state, root_player)
        if leaf.leaf_nn_value is None:
            leaf.leaf_nn_value = float(value)
        return value

    def _backprop(
        self, leaf: _Node, value_for_root: float,
        root_player: PlayerID,
    ) -> None:
        """Walk from leaf to root, updating visits and total_value.

        ``total_value`` is stored from the perspective of the parent's
        active player (the one who chose to move to this child). In a
        two-player zero-sum game the perspectives differ only by sign.
        """
        node: _Node | None = leaf
        while node is not None:
            node.visits += 1
            if node.parent is not None:
                parent_player = node.parent.state.active_player()
                if parent_player == root_player:
                    node.total_value += value_for_root
                elif parent_player == CHANCE_PLAYER:
                    # Chance parents don't have a "mover perspective" —
                    # total_value is unused for their children (we
                    # sample rather than UCB-select). Leave it zero.
                    pass
                else:
                    node.total_value += -value_for_root
            node = node.parent

    def _apply_virtual_loss(self, leaf: _Node) -> None:
        """Add a worst-case -1 contribution along the leaf→root path
        so subsequent selections in the same batch see a degraded
        UCB1 score on this path and fan out to other branches.
        Reverted by ``_revert_virtual_loss`` when the real value
        comes back from ``batch_evaluate``."""
        node: _Node | None = leaf
        while node is not None:
            node.virtual_loss += 1
            node = node.parent

    def _revert_virtual_loss(self, leaf: _Node) -> None:
        """Undo a single ``_apply_virtual_loss`` along the leaf→root
        path. Called once per batched leaf right before its real
        value gets backpropped."""
        node: _Node | None = leaf
        while node is not None:
            node.virtual_loss -= 1
            node = node.parent
