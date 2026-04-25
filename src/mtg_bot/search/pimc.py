"""Perfect Information Monte Carlo (PIMC) for MTG.

Wraps an inner ``MCTS`` (or any strategy that exposes a
``choose_with_visits`` method). Each ``choose()`` call:

1. Pulls the underlying engine ``GameState`` from the
   ``MtgGameStateAdapter`` it was handed.
2. Samples ``K`` determinized worlds — each one is a clone of the
   engine state with every card the viewer doesn't know re-permuted
   within its owner's hand+library pool. See
   ``mtg_bot.search.determinize`` for the sampler.
3. Wraps each world in a fresh adapter and runs the inner search,
   collecting per-decision visit counts.
4. Aggregates visits across worlds; returns the most-visited decision.

Why this is the integration shape: the determinizer operates on the
engine state (printings live there), but the search runs against the
search-protocol adapter. PIMC bridges them — pulling the engine state
out, determinizing, wrapping back up, then handing each world to a
separate inner search. The inner search itself stays MTG-ignorant.

Soundness vs. running raw MCTS on the god-view state:
- Each sub-search sees a viewer-consistent world. No more cheating on
  top-of-library or opponent hand contents.
- Visit-count aggregation (vs. ensemble vote on the chosen decision)
  weights heavily-explored decisions more, matching the standard PIMC
  literature. A move that wins 30 games out of 1,000 visits in one
  world doesn't outweigh a move that wins 200 out of 800 in another.

Known limitations (canonical PIMC issues; both fixable by upgrading
to Information-Set MCTS later):
- "Strategy fusion": each sub-search picks its strategy assuming it
  knows the world. PIMC doesn't model "I'd play differently if I
  learned X."
- "Non-locality": PIMC over-trusts moves that look great in the few
  worlds where opponent's hand happens to be cooperative. Larger K
  reduces (but doesn't eliminate) the bias.
"""

from __future__ import annotations

import random
from typing import Callable, Optional, Protocol

from mtg_bot.search.determinize import determinize as _default_determinize
from mtg_bot.search.engine_adapter import MtgGameStateAdapter
from mtg_bot.search.protocol import Decision, GameState, PlayerID
from mtg_bot.search.strategy import SearchStrategy


class _VisitsProducer(Protocol):
    """The slice of MCTS PIMC actually needs: produce a per-decision
    visit-count distribution at the root. Anything implementing this
    can be plugged in as ``inner_factory``."""

    def choose_with_visits(
        self, state: GameState, player_id: PlayerID
    ) -> dict[Decision, int]:
        ...


class PIMC(SearchStrategy):
    """Determinize K times, run an inner search per world, aggregate
    visit counts, pick argmax.

    ``inner_factory`` is a zero-arg callable returning a fresh inner
    search per world. Producing fresh ones (rather than reusing one)
    matters because MCTS holds its tree across the call's lifetime —
    sharing would entangle worlds.

    ``samples`` is K. K=1 is the cheapest sound option (one
    determinized world, no aggregation). K=8–16 is the standard PIMC
    range; higher K trades sub-search depth for sample diversity.
    Pick K from harness numbers, not gut.
    """

    def __init__(
        self,
        inner_factory: Callable[[], _VisitsProducer],
        samples: int = 8,
        rng: Optional[random.Random] = None,
        determinize_fn: Callable = _default_determinize,
    ) -> None:
        if samples < 1:
            raise ValueError(f"samples must be >= 1, got {samples}")
        self.inner_factory = inner_factory
        self.samples = samples
        self.rng = rng or random.Random()
        self._determinize = determinize_fn

    def choose(
        self, state: GameState, player_id: PlayerID
    ) -> Decision:
        visits = self.choose_with_visits(state, player_id)
        if not visits:
            # Every sub-search bottomed out (likely budget too small).
            # Fall back to a legal default rather than raising.
            return list(state.legal_decisions())[0]
        return max(visits.items(), key=lambda kv: kv[1])[0]

    def choose_with_visits(
        self, state: GameState, player_id: PlayerID
    ) -> dict[Decision, int]:
        """Run PIMC and return aggregated visit counts per decision,
        summed across all K sub-searches.

        Used by the recommendation panel to produce a ranked list of
        actions with relative scores (each decision's share of total
        visits is its score). ``choose()`` is just the argmax wrapper
        around this. Returns an empty dict only if every sub-search
        bottomed out — callers should fall back to a legal default.

        Forced-move shortcut: when only one legal decision exists,
        returns ``{decision: 1}`` without spinning up sub-searches.
        The synthetic count is a placeholder so callers' aggregation
        logic doesn't need a special case.
        """
        if not isinstance(state, MtgGameStateAdapter):
            raise TypeError(
                "PIMC requires an MtgGameStateAdapter (state must wrap "
                f"a real engine GameState); got {type(state).__name__}. "
                "Use MCTS directly for non-MTG game states."
            )
        # Forced-move shortcut at the PIMC layer too. Avoids spinning
        # up K sub-searches when there's only one legal action.
        legal = list(state.legal_decisions())
        if len(legal) == 1:
            return {legal[0]: 1}

        visit_totals: dict[Decision, int] = {}
        for _ in range(self.samples):
            # Independent rng per sub-search so each sub-tree is
            # reproducible from the outer seed alone.
            sub_seed = self.rng.randrange(1 << 62)
            adapter = self._build_sub_adapter(state, player_id, sub_seed)
            inner = self.inner_factory()
            for decision, visits in inner.choose_with_visits(
                adapter, player_id
            ).items():
                visit_totals[decision] = (
                    visit_totals.get(decision, 0) + visits
                )
        return visit_totals

    def _build_sub_adapter(
        self, source: MtgGameStateAdapter, viewer_id: PlayerID, sub_seed: int,
    ) -> MtgGameStateAdapter:
        """Make a fresh sub-search adapter for one PIMC sample.

        Crucially: ``source.clone()`` (not ``MtgGameStateAdapter(...)``)
        because the latter's ``__init__`` calls ``_advance_to_next_decision``
        which re-runs the current step's pre-priority logic — re-firing
        upkeep triggers, re-drawing the active player's card at DRAW,
        re-firing beginning-of-end-step warp-exile, etc. Cloning
        preserves the source's ``_step_entered``, ``_pass_count``, and
        combat-phase bookkeeping so the sub-search starts from exactly
        the state the source was at (modulo determinization).

        After cloning, we determinize the cloned engine state in place
        — re-cloning would be wasteful and the clone() already paid
        for one.
        """
        sub = source.clone()
        self._determinize(
            sub.engine_state, viewer_id, random.Random(sub_seed),
            in_place=True,
        )
        return sub
