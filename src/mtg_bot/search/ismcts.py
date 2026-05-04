"""Single-Observer Information Set Monte Carlo Tree Search (SO-ISMCTS).

Phase 2 of the ISMCTS migration plan in ``docs/ISMCTS_MIGRATION.md``.

Mirrors the public surface of ``mtg_bot.search.mcts.MCTS`` but with two
structural changes:

- **Node identity** is the information-set digest produced by
  ``mtg_bot.search.info_set.info_set_key`` rather than a concrete
  cloned ``GameState``. Two iterations whose determinizations land at
  observably-equivalent decision points (same public history, same
  viewer-known cards, same phase / step / combat / pause state) end
  up in the *same* tree node and accumulate visits there. This is
  exactly the cross-determinization sharing PIMC lacks.

- **Per-iteration determinization during selection.** Each iteration
  draws one fresh determinization at the root via the ``determinize_fn``
  callback (default = uniform sampler from
  ``mtg_bot.search.determinize``). Descent is constrained to children
  whose action is *legal in this iteration's adapter*. UCB-with-
  availability (Cowling et al. §4) keeps the bonus honest by counting
  only iterations where the child was selectable.

The ``determinize_fn`` callback is the seam where Phase 6 (belief-
weighted determinization) hooks in later — Phase 2 wires it as a
parameter and uses the uniform sampler. Nothing else in this module
changes when Phase 6 lands.

PUCT support uses a *union* mask for the policy prior (Phase 3 of
the migration plan). At any ISMCTS node the policy distribution is
computed from the network's raw logits + the OR of every
``legal_action_mask`` seen at that node across iterations.
Children whose action is legal in some determinizations but not the
current one therefore get a non-zero prior — matching the
information-set semantics of the trained policy head, which
represents ``P(action | information set)``.

The union mask grows monotonically (False → True only). Logits are
fetched once per node from ``evaluator.evaluate_logits`` and cached;
re-masking + re-softmaxing on the host is cheap (one ndarray of
length ACTION_VOCAB_SIZE per stamp) so we don't bother caching the
post-softmax distribution. Value comes from the per-iteration
determinized leaf state via the standard
``evaluate_with_policy`` / ``evaluate_logits`` value head — that's
the right thing to evaluate (a specific world), no aggregation
needed across worlds.
"""

from __future__ import annotations

import math
import random
from typing import Callable, Optional, Sequence

import numpy as np

from mtg_bot.search.budget import Budget
from mtg_bot.search.determinize import determinize as _default_determinize
from mtg_bot.search.engine_adapter import MtgGameStateAdapter
from mtg_bot.search.evaluator import Evaluator
from mtg_bot.search.info_set import info_set_key
from mtg_bot.search.protocol import Decision, GameState, PlayerID
from mtg_bot.search.strategy import SearchStrategy


class _Node:
    """An ISMCTS tree node.

    Identity: ``key`` is the ``info_set_key`` of the state at this
    decision point. Children are looked up by the action label taken
    from this node — each ``(key, decision)`` pair maps to a child
    node which itself has its own info-set key (the post-action
    state's key).

    ``children`` is a dict {decision: _Node}. Decisions are hashable
    so dict lookup is O(1) and we can use it as both an "is this
    expanded already?" check and a "descend by action" map.

    Per-child stats live on the child node (``visits``,
    ``total_value``). The Cowling-style "availability count" lives
    here too: ``availability`` increments each iteration where this
    node was in some parent's compatible-children subset. Used by
    UCB-with-availability so children that are rarely-but-strongly
    legal don't get over-weighted.
    """

    __slots__ = (
        "key", "children", "visits", "total_value", "availability",
        "virtual_loss", "prior", "_policy_logits", "_union_mask",
    )

    def __init__(self, key: bytes) -> None:
        self.key = key
        self.children: dict[Decision, "_Node"] = {}
        self.visits: int = 0
        self.total_value: float = 0.0
        self.availability: int = 0
        self.virtual_loss: int = 0
        # PUCT prior P(parent_info_set, decision-to-this-child).
        # Stamped at expansion time when ``puct=True`` from the
        # parent's cached raw logits + union mask. 0.0 default;
        # under UCB1 it's never read.
        self.prior: float = 0.0
        # Cached RAW policy logits (no mask, no softmax) from
        # ``evaluator.evaluate_logits`` for this node. Populated lazily
        # on first use. Re-used across every expansion from this node;
        # the host re-applies whatever mask is current to convert
        # logits → distribution. Storing logits instead of post-
        # softmax means a growing union mask doesn't force a fresh
        # network call.
        self._policy_logits: Optional[np.ndarray] = None
        # OR of every ``legal_action_mask`` observed at this node
        # across iterations. Bool array of shape
        # ``(ACTION_VOCAB_SIZE,)``. Lazy-initialized on first descent
        # touch (None until then). The mask grows monotonically —
        # a slot only ever flips False → True, never the reverse —
        # so any prior we stamped against an earlier (narrower) mask
        # remains semantically valid; the only bug it could mask is
        # a child seeing a slightly-too-narrow distribution between
        # the time it was stamped and the next descent's growth.
        self._union_mask: Optional[np.ndarray] = None


class ISMCTS(SearchStrategy):
    """SO-ISMCTS over an ``MtgGameStateAdapter``.

    Same shape as ``MCTS`` (``choose``, ``choose_with_visits``) so
    the AlphaZero-style data-gen pipeline and the recommendation
    panel can drop it in via the same ``Strategy`` surface.

    ``state`` arguments must be ``MtgGameStateAdapter`` instances.
    The info-set key needs adapter context (combat phase, resolution
    pause) and the determinizer operates on the wrapped engine
    state — same constraints as PIMC.
    """

    def __init__(
        self,
        evaluator: Evaluator,
        budget_factory: Callable[[], Budget],
        determinize_fn: Callable = _default_determinize,
        rng: Optional[random.Random] = None,
        c_puct: float = 1.0,
        batch_size: int = 1,
        puct: bool = True,
    ) -> None:
        """``evaluator`` scores leaves from ``player_id``'s perspective.

        ``budget_factory`` is a zero-arg callable producing a fresh
        ``Budget`` per ``choose`` call.

        ``determinize_fn`` is called once per iteration at the root
        and must accept ``(engine_state, viewer_id, rng,
        in_place=True)``. Defaults to the uniform sampler in
        ``mtg_bot.search.determinize``. Phase 6 swaps in a belief-
        weighted variant; the rest of the search is identical.

        ``c_puct`` is the exploration constant for both UCB-with-
        availability and PUCT — naming it ``c_puct`` matches the
        AlphaZero literature; the same scalar drives the bonus term
        in either selection rule.

        ``batch_size`` controls the batched-leaf-evaluation path
        (mirrored from ``MCTS``). With ``batch_size=1`` (default)
        leaves are evaluated serially. With ``batch_size>1``,
        leaves accumulate with virtual loss applied along their
        descended paths and get evaluated in one batch call.

        ``puct=True`` (default for ISMCTS) routes selection through
        the AlphaZero PUCT formula with a network policy prior. The
        evaluator must expose ``evaluate_logits`` (and
        ``batch_evaluate_logits`` for ``batch_size>1``); the
        union-mask prior path masks + softmaxes the raw logits on
        the host. ``puct=False`` falls back to UCB1-with-
        availability — useful for unit tests that don't want a
        policy-capable evaluator.
        """
        if batch_size < 1:
            raise ValueError(
                f"batch_size must be >= 1, got {batch_size!r}"
            )
        if puct:
            logits_fn = getattr(evaluator, "evaluate_logits", None)
            if not callable(logits_fn):
                raise ValueError(
                    "puct=True requires an evaluator with "
                    "evaluate_logits(state, player_id) for union-mask "
                    "priors; got "
                    f"{type(evaluator).__name__} which does not."
                )
            if batch_size > 1:
                batched_logits_fn = getattr(
                    evaluator, "batch_evaluate_logits", None,
                )
                if not callable(batched_logits_fn):
                    raise ValueError(
                        "puct=True with batch_size>1 requires an "
                        "evaluator with batch_evaluate_logits("
                        "states, player_id) for union-mask priors; "
                        f"got {type(evaluator).__name__} which does "
                        "not."
                    )
        self.evaluator = evaluator
        self.budget_factory = budget_factory
        self._determinize = determinize_fn
        self.rng = rng or random.Random()
        self.c_puct = c_puct
        self.batch_size = batch_size
        self.puct = puct
        # Per-search deferred-prior queue. Re-initialized at the top
        # of every ``choose_with_visits`` call (and reset in its
        # ``finally``); also initialized here so direct callers of
        # ``_search_serial`` / ``_search_batched`` (e.g. test spies
        # that drive the search machinery without going through
        # ``choose_with_visits``) don't trip on a missing attribute.
        # See ``_stamp_prior`` for the per-search semantics.
        self._pending_prior_states: list[
            tuple[_Node, MtgGameStateAdapter]
        ] = []
        self._pending_prior_set: set[int] = set()

    # ------------------------------------------------------------------
    # SearchStrategy surface
    # ------------------------------------------------------------------

    def choose(
        self, state: GameState, player_id: PlayerID
    ) -> Decision:
        visits = self.choose_with_visits(state, player_id)
        if not visits:
            return self.rng.choice(list(state.legal_decisions()))
        return max(visits.items(), key=lambda kv: kv[1])[0]

    def observe_action(
        self,
        state: GameState,
        decision: Decision,
        actor: PlayerID,
    ) -> None:
        """Record a priority-moment observation for belief tracking.

        Called by the game loop once after every ``adapter.apply`` —
        regardless of whose turn it was — so the strategy's
        determinizer can accumulate the opponent action history that
        belief-weighted determinization conditions on.

        ``state`` must be the pre-apply adapter (or its underlying
        engine state); ``decision`` is the action that was just
        applied; ``actor`` is the player who held priority. The
        ``BeliefWeightedDeterminizer`` filters ``actor != viewer`` at
        score time, so all observed actions are recorded
        unconditionally — opponent identity is determined per-search-
        call by the viewer passed to ``choose``.

        No-op when ``self._determinize`` is the uniform sampler (or
        anything other than a ``BeliefWeightedDeterminizer``); under
        plain ISMCTS the call is silent overhead and game-loop sites
        don't have to branch.
        """
        # Local import to avoid a top-level cycle: belief.py imports
        # from search.determinize, which is a peer of this module.
        # Keeping the dependency on belief lazy means the plain-ISMCTS
        # path has no knowledge of belief.py at all.
        from mtg_bot.search.belief import (
            BeliefWeightedDeterminizer, PriorityMoment,
        )
        determinizer = self._determinize
        if not isinstance(determinizer, BeliefWeightedDeterminizer):
            return
        # The determinizer's particle-filter machinery clones the
        # snapshot per-iteration before re-determinizing, so we
        # capture an engine-state clone here so subsequent in-place
        # mutations to ``state`` (the live adapter the game loop
        # reuses) don't corrupt the recorded moment.
        if isinstance(state, MtgGameStateAdapter):
            engine_state = state.engine_state.clone()
        else:
            engine_state = state.clone()
        moment = PriorityMoment(
            state=engine_state, decision=decision, actor=actor,
        )
        determinizer.played_history = (
            *determinizer.played_history, moment,
        )

    def choose_with_visits(
        self, state: GameState, player_id: PlayerID
    ) -> dict[Decision, int]:
        """Return ``{decision: visit_count}`` over the root's children
        after running ISMCTS to budget.

        Forced-move shortcut and terminal-state convention match
        ``MCTS.choose_with_visits``: exactly one legal decision
        returns ``{decision: 1}`` without spinning up the tree;
        an already-terminal state returns ``{}``.
        """
        if not isinstance(state, MtgGameStateAdapter):
            raise TypeError(
                "ISMCTS requires an MtgGameStateAdapter (state must "
                f"wrap a real engine GameState); got "
                f"{type(state).__name__}."
            )
        if state.is_terminal():
            return {}

        legal = list(state.legal_decisions())
        if len(legal) == 1:
            return {legal[0]: 1}

        root_key = info_set_key(state, player_id)
        tree: dict[bytes, _Node] = {root_key: _Node(root_key)}
        root = tree[root_key]

        # Per-search queue of parents whose policy logits haven't been
        # fetched yet. Strategy A (see module docstring + commit msg):
        # ``_stamp_prior`` enqueues new (parent, pre_apply_sub) tuples
        # here when ``parent._policy_logits is None`` instead of
        # invoking ``evaluate_logits`` synchronously, and the batched
        # search loop flushes the queue alongside the leaf batch in a
        # single ``batch_evaluate_logits`` call. Parents already in the
        # queue (re-encountered before the next flush) are deduped via
        # ``_pending_prior_set``. Stored as a list so order is stable
        # for the batched call. Initialized fresh per search so cached
        # state can't leak between ``choose_with_visits`` invocations.
        self._pending_prior_states: list[
            tuple[_Node, MtgGameStateAdapter]
        ] = []
        self._pending_prior_set: set[int] = set()

        budget = self.budget_factory()
        budget.start()
        try:
            if self.batch_size == 1:
                self._search_serial(
                    state, player_id, root, tree, budget,
                )
            else:
                self._search_batched(
                    state, player_id, root, tree, budget,
                    self.batch_size,
                )
        finally:
            # Drop the queue references so the cloned adapters don't
            # outlive the search call.
            self._pending_prior_states = []
            self._pending_prior_set = set()

        return {d: c.visits for d, c in root.children.items()}

    # ------------------------------------------------------------------
    # Search loops
    # ------------------------------------------------------------------

    def _search_serial(
        self,
        source: MtgGameStateAdapter,
        viewer: PlayerID,
        root: _Node,
        tree: dict[bytes, _Node],
        budget: Budget,
    ) -> None:
        while not budget.exhausted():
            sub = self._fresh_determinization(source, viewer)
            leaf, path = self._select_and_expand(
                sub, root, tree, viewer,
            )
            # Flush any deferred prior-stamp requests created during
            # selection. With ``batch_size=1`` there is no leaf-batch
            # to amortize against, so we issue a single call per
            # iteration when the queue is non-empty. This still
            # batches when one iteration enqueues multiple parents
            # (rare under serial selection, common under root-touch),
            # and keeps the serial path's behavior aligned with the
            # batched path: ``_stamp_prior`` defers uniformly, the
            # search loop flushes uniformly.
            self._flush_pending_priors(viewer)
            value = self._evaluate_leaf(leaf, sub, viewer)
            self._backprop(path, value)
            budget.consume_node()

    def _flush_pending_priors(self, viewer: PlayerID) -> None:
        """Issue ``batch_evaluate_logits`` on every queued (parent,
        pre_apply_sub) tuple, cache the resulting logits on each
        parent, and re-stamp existing children's priors. Used by
        the serial search path; the batched path inlines the same
        work into the leaf-batch flush for a single fused network
        call.
        """
        if not self._pending_prior_states:
            return
        pending = self._pending_prior_states
        self._pending_prior_states = []
        self._pending_prior_set = set()
        states = [s for _, s in pending]
        pairs = self.evaluator.batch_evaluate_logits(states, viewer)
        for (parent, pre_apply_sub), (_value, logits) in zip(
            pending, pairs,
        ):
            if parent._policy_logits is None:
                parent._policy_logits = logits
            for child_decision, child_node in parent.children.items():
                self._stamp_child_prior(
                    parent, child_node, child_decision,
                    pre_apply_sub, viewer,
                )

    def _search_batched(
        self,
        source: MtgGameStateAdapter,
        viewer: PlayerID,
        root: _Node,
        tree: dict[bytes, _Node],
        budget: Budget,
        batch_size: int,
    ) -> None:
        """Mirror of ``MCTS._search_batched``: collect a batch of
        non-terminal leaves with virtual loss applied along each
        path, evaluate the batch in one call, revert virtual loss,
        and backprop.

        ISMCTS-specific wrinkle: each leaf in the batch comes from
        its OWN per-iteration determinization. The leaves are
        independent ``MtgGameStateAdapter`` instances, which is what
        ``batch_evaluate`` expects — same as in ``MCTS``.

        Prior-batching wrinkle: when ``puct=True`` the leaf batch
        also carries any parents queued by ``_stamp_prior`` for
        deferred policy-prior stamping. The queue
        (``_pending_prior_states``) is filled during selection
        whenever ``_stamp_prior`` hits a parent with no cached
        logits; the flush below runs ``batch_evaluate_logits`` on
        ``leaves + parents`` as a single concatenated batch, then
        distributes leaf logits to leaves and parent logits to
        parents — re-stamping every already-expanded child of each
        flushed parent so children whose ``prior=0`` got recorded
        on first expansion are upgraded to the real prior in time
        for the next batch.
        """
        while not budget.exhausted():
            pending: list[tuple[_Node, list[_Node], MtgGameStateAdapter]] = []
            terminal_results: list[tuple[list[_Node], float]] = []
            for _ in range(batch_size):
                if budget.exhausted():
                    break
                sub = self._fresh_determinization(source, viewer)
                leaf, path = self._select_and_expand(
                    sub, root, tree, viewer,
                )
                budget.consume_node()
                if sub.is_terminal():
                    value = self._evaluate_leaf(leaf, sub, viewer)
                    terminal_results.append((path, value))
                else:
                    self._apply_virtual_loss(path)
                    pending.append((leaf, path, sub))

            for path, value in terminal_results:
                self._backprop(path, value)

            # Snapshot the deferred-prior queue and reset it BEFORE
            # we issue the network call, so any side effects of the
            # backprop / re-stamp paths can't accidentally feed back
            # into this flush.
            pending_priors = self._pending_prior_states
            self._pending_prior_states = []
            self._pending_prior_set = set()

            if pending or pending_priors:
                if self.puct:
                    leaf_states = [s for _, _, s in pending]
                    parent_states = [s for _, s in pending_priors]
                    # Concatenated batch: leaves first, parents
                    # second. The split index lets us slice the
                    # response into leaf logits and parent logits
                    # without zipping past the boundary.
                    combined = leaf_states + parent_states
                    pairs = self.evaluator.batch_evaluate_logits(
                        combined, viewer,
                    )
                    leaf_pairs = pairs[: len(leaf_states)]
                    parent_pairs = pairs[len(leaf_states):]
                    for (leaf, path, _), (value, logits) in zip(
                        pending, leaf_pairs,
                    ):
                        if leaf._policy_logits is None:
                            leaf._policy_logits = logits
                        self._revert_virtual_loss(path)
                        self._backprop(path, value)
                    # Distribute parent logits and re-stamp all
                    # already-expanded children's priors. The value
                    # head's output for parents is unused (parents
                    # are not leaves of any path here).
                    for (parent, pre_apply_sub), (_value, logits) in zip(
                        pending_priors, parent_pairs,
                    ):
                        if parent._policy_logits is None:
                            parent._policy_logits = logits
                        # Re-stamp every expanded child — this is
                        # cheap (np softmax on a length-
                        # ACTION_VOCAB_SIZE row, plus one ae.encode
                        # per child) and reverses the prior=0
                        # placeholder set during deferred expansion.
                        for child_decision, child_node in (
                            parent.children.items()
                        ):
                            self._stamp_child_prior(
                                parent, child_node, child_decision,
                                pre_apply_sub, viewer,
                            )
                else:
                    # Non-PUCT path: only leaves go through
                    # ``batch_evaluate``; the prior-defer queue is
                    # never populated (``_stamp_prior`` is gated on
                    # ``self.puct`` at the call site), so
                    # ``pending_priors`` is empty here by construction.
                    leaf_states = [s for _, _, s in pending]
                    values = self.evaluator.batch_evaluate(
                        leaf_states, viewer,
                    )
                    for (_, path, _), value in zip(pending, values):
                        self._revert_virtual_loss(path)
                        self._backprop(path, value)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _fresh_determinization(
        self,
        source: MtgGameStateAdapter,
        viewer: PlayerID,
    ) -> MtgGameStateAdapter:
        """Clone the source adapter and determinize its engine state
        in place. Same pattern PIMC uses — cloning preserves
        ``_step_entered`` / ``_pass_count`` / combat-phase /
        resolution-pause bookkeeping; in-place determinization
        permutes hidden-zone printings without re-running step entry.
        """
        sub = source.clone()
        # Independent rng per iteration so iterations are reproducible
        # from the outer rng alone.
        sub_seed = self.rng.randrange(1 << 62)
        self._determinize(
            sub.engine_state, viewer, random.Random(sub_seed),
            in_place=True,
        )
        return sub

    def _grow_union_mask(
        self,
        node: _Node,
        sub: MtgGameStateAdapter,
        viewer: PlayerID,
    ) -> None:
        """OR this iteration's ``legal_action_mask`` into
        ``node._union_mask``. Called at every descent step that lands
        at ``node``. The mask is computed from the per-iteration
        adapter ``sub`` — by construction the per-iteration mask is a
        subset of the union mask after this call.

        Lazy-allocates ``_union_mask`` on first touch so untouched
        nodes (e.g. nodes the search never visited under PUCT) don't
        carry the bool array.
        """
        from mtg_bot.training import action_encoding as ae
        iter_mask = ae.legal_action_mask(sub, viewer)
        if node._union_mask is None:
            node._union_mask = iter_mask.copy()
        else:
            np.logical_or(node._union_mask, iter_mask, out=node._union_mask)

    def _select_and_expand(
        self,
        sub: MtgGameStateAdapter,
        root: _Node,
        tree: dict[bytes, _Node],
        viewer: PlayerID,
    ) -> tuple[_Node, list[_Node]]:
        """Walk the tree under the per-iteration determinization
        ``sub``, descending into the best UCB-with-availability /
        PUCT child among the *compatible* subset (children whose
        action is currently legal in ``sub``).

        Returns ``(leaf_node, path)`` where ``path`` is the list of
        nodes from root to leaf inclusive. The path is what backprop
        walks; we capture it during descent rather than reconstruct
        from parent pointers because ISMCTS nodes have no parent
        pointer (a node can have many parents — it's an information
        set, not a state).

        Side effects on ``sub``: each step of the descent applies
        the chosen decision to ``sub`` so ``sub`` ends up at the
        leaf state. That mirrors how MCTS uses node.state — for
        ISMCTS the state lives in the descended adapter, not on the
        node.
        """
        node = root
        path: list[_Node] = [root]
        while not sub.is_terminal():
            legal_now = sub.legal_decisions()
            if not legal_now:
                # Defensive: should coincide with terminal but
                # legal_decisions could in principle return [] in a
                # transient adapter state.
                break
            legal_set = set(legal_now)

            # PUCT prior accuracy: OR this iteration's
            # legal_action_mask into the node's union mask before any
            # stamping happens. The union mask grows monotonically;
            # priors stamped on subsequent expansions reflect the
            # widest set of legal actions ever seen at this
            # information set, not just the per-iteration narrower
            # subset.
            if self.puct:
                self._grow_union_mask(node, sub, viewer)

            # Bookkeeping: every child of ``node`` whose action is
            # legal in this iteration's determinization gets its
            # availability count incremented. This is the Cowling-
            # style availability counter — incremented whenever the
            # child was *selectable*, not just selected.
            for d, child in node.children.items():
                if d in legal_set:
                    child.availability += 1

            # Expansion: pick a legal action that has no child yet.
            unexpanded = [d for d in legal_now if d not in node.children]
            if unexpanded:
                # Pick the first unexpanded action (matches MCTS's
                # pending-decisions iterator order, which itself is
                # legal_decisions order). Deterministic given the
                # adapter's stable enumeration order.
                decision = unexpanded[0]
                # Snapshot the pre-apply adapter for prior stamping —
                # action_encoding.encode is positional and reads zone
                # indices from the pre-apply state, and we may also
                # need to query the policy on the pre-apply state if
                # the parent's cache isn't populated yet.
                pre_apply_sub = sub.clone() if self.puct else None
                # Apply to the iteration's adapter so the child's
                # node is identified by the post-action info-set.
                sub.apply(decision)
                child_key = info_set_key(sub, viewer)
                child = tree.get(child_key)
                if child is None:
                    child = _Node(child_key)
                    tree[child_key] = child
                # Hook the child up under this decision label.
                # Transposition merging: if a previously-expanded
                # sibling (different decision label) ended up at the
                # *same* info-set key, the child node we look up
                # here is shared — its visits and value continue to
                # accumulate from both reachings. The dict-of-dicts
                # children layout means each parent gets its own
                # action-label entry pointing into the shared node.
                node.children[decision] = child
                if self.puct and pre_apply_sub is not None:
                    self._stamp_prior(
                        node, child, decision, pre_apply_sub, viewer,
                    )
                child.availability += 1
                path.append(child)
                return child, path

            # All legal children already expanded — descend into the
            # best one among the compatible subset.
            compatible = [
                (d, c) for d, c in node.children.items()
                if d in legal_set
            ]
            if not compatible:
                # No legal action has a child — this happens when
                # legal_decisions changed between iterations and
                # everything we expanded earlier is illegal here.
                # Treat the current node as the leaf for this
                # iteration. Rare; cleaner than trying to expand
                # something we can't represent.
                break

            parent_n = node.visits + node.virtual_loss
            if self.puct:
                best_decision, best_child = max(
                    compatible,
                    key=lambda dc: _puct_score(
                        dc[1], parent_n, self.c_puct,
                    ),
                )
            else:
                best_decision, best_child = max(
                    compatible,
                    key=lambda dc: _ucb_with_availability(
                        dc[1], self.c_puct,
                    ),
                )
            sub.apply(best_decision)
            node = best_child
            path.append(node)
            # Loop will check terminality of the new ``sub`` state.
        return node, path

    def _stamp_prior(
        self,
        parent: _Node,
        child: _Node,
        decision: Decision,
        pre_apply_sub: MtgGameStateAdapter,
        viewer: PlayerID,
    ) -> None:
        """Set ``child.prior`` from the parent's cached raw logits +
        union mask.

        ``pre_apply_sub`` is the adapter BEFORE ``decision`` was
        applied — needed because ``action_encoding.encode`` is
        positional and reads zone indices from the pre-apply state.

        First-touch (``parent._policy_logits is None``) is *deferred*
        rather than synchronous: instead of calling
        ``evaluate_logits`` here on a single state — which dominated
        ISMCTS wall time per the 2026-05-04 profile, ~74% of
        ``choose_with_visits`` was spent in 213 single-state forwards
        of the 1024×1024×512 dual-head MLP — we leave ``child.prior``
        at its 0.0 default, queue ``(parent, pre_apply_sub)`` on
        ``_pending_prior_states``, and let the next batched flush in
        ``_search_batched`` populate ``parent._policy_logits`` via
        ``batch_evaluate_logits`` alongside the leaf batch. The flush
        path then re-stamps every existing child from the freshly-
        cached logits, so a child whose prior was 0 on its first
        expansion gets its real prior on the next flush boundary.

        PUCT exploration with ``prior=0.0`` collapses the explore
        bonus to zero (``c * 0 * sqrt(A) / (1+N) == 0``); on a fresh
        unvisited child with no Q yet, the score is 0 — same as every
        other unvisited child whose prior hasn't landed yet. The
        ``max`` tiebreak is deterministic (insertion order in
        ``children``), so the first unvisited child in legality
        order wins selection on those iterations. That's the
        Monte Carlo noise the deferred-stamp path trades for the
        ~50× wall-time win — acceptable because the profile shows
        only ~213 first-touches across 800 iterations and even those
        iterations continue to update the tree once the real prior
        lands.

        On subsequent expansions from a parent whose logits are
        already cached, this method works exactly as before: encode
        the decision, mask + softmax via ``_apply_policy_mask``,
        and write the slot probability to ``child.prior``. Encoding
        errors leave ``prior=0.0``.

        Subsequent expansions from this parent re-use the cached
        logits + the (possibly wider) current union mask, never
        re-querying the network.
        """
        if parent._policy_logits is None:
            # Deferred path: queue this parent for the next batched
            # flush. Dedupe by parent identity so a parent that
            # spawns multiple new children before a flush only goes
            # on the queue once. The bound state is the very first
            # ``pre_apply_sub`` we saw at this parent — it's the
            # right state to query the network on (the parent's
            # info-set state); subsequent ``pre_apply_sub`` clones
            # at the same parent are observably equivalent for the
            # network's purposes (same info-set, same features).
            parent_id = id(parent)
            if parent_id not in self._pending_prior_set:
                self._pending_prior_set.add(parent_id)
                self._pending_prior_states.append(
                    (parent, pre_apply_sub),
                )
            return
        # Logits already cached on the parent — stamp inline as
        # before. This is the steady-state hot path (called on
        # every newly-expanded child at every iteration after the
        # parent's first touch was flushed).
        self._stamp_child_prior(
            parent, child, decision, pre_apply_sub, viewer,
        )

    def _stamp_child_prior(
        self,
        parent: _Node,
        child: _Node,
        decision: Decision,
        pre_apply_sub: MtgGameStateAdapter,
        viewer: PlayerID,
    ) -> None:
        """Inner helper: with ``parent._policy_logits`` populated,
        encode ``decision`` against ``pre_apply_sub`` and write the
        masked-softmax slot probability to ``child.prior``. Shared by
        ``_stamp_prior`` (steady-state) and the deferred-flush path
        in ``_search_batched`` (re-stamp after logits arrive).
        """
        from mtg_bot.training import action_encoding as ae
        try:
            slot = ae.encode(
                decision, pre_apply_sub.engine_state, viewer,
            )
        except ae.EncodingOverflowError:
            return
        except Exception:
            return
        distribution = _apply_policy_mask(
            parent._policy_logits, parent._union_mask,
        )
        if distribution is None:
            return
        try:
            child.prior = float(distribution[slot])
        except (IndexError, ValueError):
            return

    def _evaluate_leaf(
        self,
        leaf: _Node,
        sub: MtgGameStateAdapter,
        viewer: PlayerID,
    ) -> float:
        """Evaluate the leaf state under this iteration's
        determinization. Mirrors ``MCTS._evaluate_leaf`` semantics:
        terminal states short-circuit through the evaluator's
        terminal handling; non-terminal PUCT leaves call
        ``evaluate_logits`` and stash the raw logits on the leaf for
        use by future expansions from this node. The value comes
        from the same forward pass; per-iteration determinization is
        the right state for the value head (we want the value of
        this concrete world, not an average over consistent worlds).
        """
        if self.puct and not sub.is_terminal():
            value, logits = self.evaluator.evaluate_logits(
                sub, viewer,
            )
            if leaf._policy_logits is None:
                leaf._policy_logits = logits
            return value
        return self.evaluator.evaluate(sub, viewer)

    def _backprop(
        self, path: list[_Node], value_for_root: float,
    ) -> None:
        """Walk root→leaf in ``path`` updating visits and
        total_value.

        ISMCTS-specific note on perspectives: in MCTS, ``total_value``
        is stored from the perspective of the parent's active player
        because that's the player who chose to move to the child. In
        an info-set tree, the "active player" of a node is fixed by
        the info-set key (the key encodes priority / combat phase /
        resolution-pause player). For SO-ISMCTS — single-observer,
        from the root viewer's perspective — the value flowing up
        is always for ``viewer`` (the agent we're searching for).
        Each node's mean is then the average value of its decision-
        path FROM the viewer's perspective. The opponent's nodes
        still want to maximize ``-value_for_root`` from their POV,
        but at decision time we only ever read the root's children
        (the viewer's actions); the structure of the values along
        the rest of the path doesn't drive the final policy.
        Storing from the viewer's perspective uniformly is the
        SO-ISMCTS canonical choice (Cowling §4.1) and avoids the
        sign-flip dance MCTS does at every parent_player check.
        """
        for node in path:
            node.visits += 1
            node.total_value += value_for_root

    def _apply_virtual_loss(self, path: list[_Node]) -> None:
        for node in path:
            node.virtual_loss += 1

    def _revert_virtual_loss(self, path: list[_Node]) -> None:
        for node in path:
            node.virtual_loss -= 1


def _apply_policy_mask(
    raw_logits: np.ndarray, union_mask: Optional[np.ndarray],
) -> Optional[np.ndarray]:
    """Apply ``union_mask`` to ``raw_logits`` and softmax. Returns the
    resulting distribution as a float32 ndarray of length
    ``ACTION_VOCAB_SIZE``; illegal slots are exactly 0.0, legal slots
    sum to 1.0. Returns ``None`` if ``union_mask`` is missing or
    has no True slot — caller treats that as "no prior available"
    and leaves children's priors at 0.0.

    Mirrors what ``NNEvaluator.evaluate_with_policy`` does internally
    but with our chosen mask, not the per-iteration leaf mask.
    """
    if union_mask is None:
        return None
    if not union_mask.any():
        return None
    row = raw_logits.astype(np.float32, copy=True)
    row[~union_mask] = -np.inf
    row -= row.max()  # safe: max is finite (at least one legal slot)
    exp = np.exp(row)
    return (exp / exp.sum()).astype(np.float32, copy=False)


def _ucb_with_availability(child: _Node, c: float) -> float:
    """UCB1-with-availability — the Cowling-et-al. selection rule
    when no policy prior is available.

    .. math::

        \\text{score}(c) = Q(c) + c \\cdot \\sqrt{\\frac{\\ln A(c)}{1 + N(c)}}

    where ``A(c)`` is the availability count (iterations where ``c``
    was selectable) and ``N(c)`` is the visit count. The +1 in the
    denominator keeps the formula finite at zero visits — combined
    with returning +inf when N==0 the unvisited child wins
    selection unconditionally, the standard MCTS first-touch rule.
    """
    n = child.visits + child.virtual_loss
    if n == 0:
        return math.inf
    a = child.availability
    if a <= 0:
        return math.inf
    exploit = (child.total_value - child.virtual_loss) / n
    explore = c * math.sqrt(math.log(a) / (1 + n))
    return exploit + explore


def _puct_score(child: _Node, parent_visits: int, c: float) -> float:
    """PUCT-with-availability:

    .. math::

        \\text{score}(c) = Q(c) + c \\cdot P(c) \\cdot
            \\frac{\\sqrt{A(c)}}{1 + N(c)}

    Where ``A(c)`` is the availability count, replacing
    AlphaZero's ``\\sqrt{N_{parent}}`` term with the per-child
    selectability count. This is the ISMCTS-flavored PUCT — the
    bonus reflects "how much chance this child has had to be
    explored" rather than "how many parent visits there were
    in total." With the prior fixed and ``A(c)`` ≈ parent_visits
    (the steady-state behavior), it converges to AlphaZero's
    formula; the difference shows up early when child legality
    is intermittent.
    """
    n = child.visits + child.virtual_loss
    a = max(child.availability, 1)
    explore = c * child.prior * math.sqrt(a) / (1 + n)
    if n == 0:
        return explore
    exploit = (child.total_value - child.virtual_loss) / n
    return exploit + explore


__all__ = ["ISMCTS"]
