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

PUCT support is wired up in this phase (per the design doc question
2 walkthrough). The leaf-state-relative legal mask used by
``evaluator.evaluate_with_policy`` works correctly for a determinized
leaf — verified in the design doc — so the existing ``NNEvaluator``
plugs in without modification. Per-iteration masking is what we use
here; the union-mask refinement (mask = OR of masks across
determinizations) is left as a TODO for a later iteration since it
requires extra bookkeeping that isn't on the critical path for
Phase 2's correctness.
"""

# TODO(phase-2-followup): per-iteration legal mask is leaf-state-
# relative. Cowling §4 suggests a union mask over consistent worlds
# would be slightly more accurate (children get a non-zero prior even
# in iterations where they're momentarily masked off). Worth
# revisiting after Phase 4's eval-gate numbers come in; the simpler
# per-iteration mask is fine for correctness and matches the existing
# PUCT contract.

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
        "virtual_loss", "prior", "_policy_cache",
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
        # parent's cached policy distribution. 0.0 default; under
        # UCB1 it's never read.
        self.prior: float = 0.0
        # Cached policy distribution from
        # ``evaluator.evaluate_with_policy(state, root_player)`` for
        # *this* node's leaf state at the iteration where the policy
        # was first queried. Reused across all subsequent expansions
        # from this node so the network sees one forward pass per
        # node, not one per child. The leaf state used for the
        # forward pass is the per-iteration determinized state — the
        # mask is leaf-state-relative per the
        # ``evaluate_with_policy`` contract, and that matches how the
        # MCTS path already works.
        self._policy_cache: Optional[np.ndarray] = None


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
        evaluator must expose ``evaluate_with_policy``; we validate
        that here. ``puct=False`` falls back to UCB1-with-
        availability — useful for unit tests that don't want a
        policy-capable evaluator.
        """
        if batch_size < 1:
            raise ValueError(
                f"batch_size must be >= 1, got {batch_size!r}"
            )
        if puct:
            policy_fn = getattr(evaluator, "evaluate_with_policy", None)
            if not callable(policy_fn):
                raise ValueError(
                    "puct=True requires an evaluator with "
                    "evaluate_with_policy(state, player_id); got "
                    f"{type(evaluator).__name__} which does not."
                )
            if batch_size > 1:
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
        self._determinize = determinize_fn
        self.rng = rng or random.Random()
        self.c_puct = c_puct
        self.batch_size = batch_size
        self.puct = puct

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

        budget = self.budget_factory()
        budget.start()
        if self.batch_size == 1:
            self._search_serial(
                state, player_id, root, tree, budget,
            )
        else:
            self._search_batched(
                state, player_id, root, tree, budget,
                self.batch_size,
            )

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
            value = self._evaluate_leaf(leaf, sub, viewer)
            self._backprop(path, value)
            budget.consume_node()

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

            if pending:
                states = [s for _, _, s in pending]
                if self.puct:
                    pairs = self.evaluator.batch_evaluate_with_policy(
                        states, viewer,
                    )
                    for (leaf, path, _), (value, policy) in zip(
                        pending, pairs,
                    ):
                        if leaf._policy_cache is None:
                            leaf._policy_cache = policy
                        self._revert_virtual_loss(path)
                        self._backprop(path, value)
                else:
                    values = self.evaluator.batch_evaluate(
                        states, viewer,
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
        """Set ``child.prior`` from the parent's cached policy
        distribution.

        ``pre_apply_sub`` is the adapter BEFORE ``decision`` was
        applied — needed because ``action_encoding.encode`` is
        positional and reads zone indices from the pre-apply state.
        It's also where the policy gets queried on first touch:
        when ``parent._policy_cache`` is None we call
        ``evaluator.evaluate_with_policy`` on the pre-apply adapter
        and cache the result on the parent. Subsequent expansions
        from this parent reuse the cached distribution.

        Encoding errors are tolerated (same as MCTS): an unencodable
        decision leaves ``prior=0.0``.
        """
        if parent._policy_cache is None:
            # Lazy-populate the parent's policy cache from the pre-
            # apply state. This mirrors MCTS's first-touch caching
            # in _stamp_prior.
            _, policy = self.evaluator.evaluate_with_policy(
                pre_apply_sub, viewer,
            )
            parent._policy_cache = policy
        from mtg_bot.training import action_encoding as ae
        try:
            slot = ae.encode(
                decision, pre_apply_sub.engine_state, viewer,
            )
        except ae.EncodingOverflowError:
            return
        except Exception:
            return
        try:
            child.prior = float(parent._policy_cache[slot])
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
        ``evaluate_with_policy`` and stash the policy on the leaf
        for use by future expansions from this node.
        """
        if self.puct and not sub.is_terminal():
            value, policy = self.evaluator.evaluate_with_policy(
                sub, viewer,
            )
            if leaf._policy_cache is None:
                leaf._policy_cache = policy
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
