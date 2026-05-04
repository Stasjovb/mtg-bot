# ISMCTS migration plan

Replace PIMC with Information Set Monte Carlo Tree Search.

## What's wrong with PIMC today

Current setup (`src/mtg_bot/search/pimc.py`):

- Caller asks PIMC for a move at a decision point.
- PIMC samples K determinized worlds (each consistent with the
  viewer's information; see `mtg_bot/search/determinize.py`).
- For each world, PIMC builds an *independent* MCTS tree rooted at
  that world's state and runs the inner search to budget.
- After all K searches, PIMC aggregates: `visit_totals[d] =
  sum_over_worlds(visits_of_d_in_that_world)`.
- The argmax of `visit_totals` is the chosen move.

This is the standard "tree-per-determinization" PIMC. It has known
failure modes:

1. **Strategy fusion**. The aggregated visit policy is a mixture of
   K policies, each optimal in its own world. The mixture can be
   optimal in *no* world. The classic example: a player who must
   choose action A in world X and action B in world Y; if the
   viewer can't distinguish X from Y at decision time, the optimal
   *information-set* policy is a single committed action that
   averages well. PIMC's mixture happily plays "A 60% of the time,
   B 40%" because that's what the visit aggregation says — but
   that splits the win-rate between two strategies neither of which
   is best on average.
2. **Non-locality**. Two information-set-equivalent decision points
   (same observable history, same legal actions, same viewer
   state) appear as *different* nodes in different sub-trees. The
   search can't share visits between them and learns each one from
   scratch.
3. **Visits on actions illegal at the root**. Some actions' legality
   depends on hidden info (concretely in mtg-bot: exile-zone casts
   whose legality is gated by battlefield-granted warp filters or
   similar). After determinization, a card-in-hand printing changes;
   that flips a "warp grant" condition; an exile cast becomes legal
   in *that* world. PIMC happily votes on it. The aggregated
   `visits` dict then contains decisions never actually legal at
   the root, breaking any caller that maps visits onto root-legal
   slots — most notably the policy-target builder in
   `data_gen.py`, which had a 10K-magnitude masked-CE explosion
   from these phantom votes (8-17 affected rows per 200K-row
   iter, all exile-zone actions).

The current `feature/policy-target-filter` branch added a writer-side
filter to symptomatically clean the training data. That fix is fine
for what it does. **It doesn't address (1) or (2), and its handling
of (3) is post-hoc.**

## What ISMCTS does differently

Information Set Monte Carlo Tree Search (Cowling, Powley & Whitehouse
2012, "Information Set Monte Carlo Tree Search").

- Single tree. Nodes represent **information sets** (decision points
  as the viewer sees them), not concrete game states. Children are
  actions legal at that information set.
- One inner search loop:
  - Sample one determinization at the root (cheap — same sampler we
    have today, called once per iteration instead of once per K-tree
    batch).
  - Descend through the existing tree, but only consider children
    whose actions are *currently legal in this iteration's
    determinization*. This is the "consistent move" subset.
  - When the descent reaches an unexpanded child, expand it and
    rollout / NN-evaluate.
  - Backprop value up the descended path.
- After total budget, the action policy is the visit distribution
  at the root. By construction, a child is only visited when its
  action was legal in some sampled determinization, but every
  child's action was deemed legal at the *information set* level
  (the union of legal actions across worlds the viewer can't
  distinguish from the actual world).
- Strategy fusion: gone. The tree shares structure across
  determinizations, so values backprop into the same node from
  whichever world the iteration sampled. The action chosen is the
  one whose visit count is highest under the *mixture distribution
  the viewer faces*, not the one that's the argmax of K independent
  searches.
- Non-locality: gone. Two iterations that determinize to states the
  viewer can't tell apart land at the same node and accumulate
  visits there.
- Visits on root-illegal actions: gone. Children at the root are
  by construction actions legal in at least one determinization
  consistent with the viewer's information — i.e. legal at the
  information set. The policy target maps cleanly onto the action
  mask, no filtering needed.

There's a Single-Observer ISMCTS variant ("SO-ISMCTS") and a
Multiple-Observer ("MO-ISMCTS"). MTG decision-making is from the
acting player's POV (we sample at root using only that player's
information), so SO-ISMCTS is the right starting point. Cowling et
al. report SO-ISMCTS as a strict improvement over PIMC at the same
budget on Lord of the Rings: The Confrontation and a hidden-info
variant of Phantom Bridge — both with information structure broadly
similar to MTG's per-card hidden-zone model.

## Concrete implementation plan

### Phase 1: information-set node identity

The current `_Node` in `mtg_bot/search/mcts.py` is keyed by `state`.
ISMCTS keys nodes by **information-set hash** — a hash of the
public game state plus the viewer's known cards. Two states the
viewer can't distinguish hash to the same node.

- Add `info_set_key(state, viewer)` in
  `mtg_bot/search/info_set.py`. Hash should incorporate:
  - Public-zone contents in canonical order (battlefield, graveyard,
    exile, stack — printings are public).
  - Per-zone counts for hidden zones.
  - The viewer's own hand contents (printings — viewer knows these).
  - Phase, step, priority holder, life totals, mana pools.
  - Combat state (attackers declared, etc.).
- Properties:
  - Two states the viewer can't distinguish must produce equal
    keys. Pin in tests using `determinize` to generate equivalent
    states from a single source.
  - States the viewer *can* distinguish must produce different keys.
  - The hash is reasonably collision-resistant (use blake2b or
    similar; collisions silently merge information sets, which
    *underweights* the agent's knowledge — bad).

This is the most subtle part of the migration. Get the equivalence
relation wrong and the search either over-merges (acts like the
viewer is *more* uncertain than they are) or under-merges (loses
the cross-determinization sharing benefit).

### Phase 2: ISMCTS search loop

New file `mtg_bot/search/ismcts.py`. Mirrors `mcts.py`'s shape
(``choose``, ``choose_with_visits``, batched vs serial) but with
one inner loop:

```
def choose_with_visits(self, state, viewer):
    root_key = info_set_key(state, viewer)
    # _Node is now keyed by info_set_key, not state. Children are
    # actions legal at the info set (union over consistent worlds).
    root = self._tree.get_or_create(root_key, action_pool=...)
    while not budget.exhausted():
        determinization = self.determinize_fn(state, viewer, rng=...)
        leaf = self._select_and_expand(root, determinization)
        value = self._evaluate_leaf(leaf, determinization)
        self._backprop(leaf, value)
        budget.consume_node()
    return {child.action: child.visits for child in root.children}
```

Selection rule: at each node, only consider children whose action is
*currently legal in this iteration's determinization*. Use a UCB
variant adjusted for the per-iteration availability count (visits
divided by *availability* — see Cowling §3 for the exact formula);
this prevents over-weighting actions that are rarely-but-strongly
legal.

Expansion: pick an action from the action pool that's legal in this
determinization but not yet a child of the current node. Create
the child node keyed by the resulting info-set.

Reuse most of the existing PUCT / batched / virtual-loss machinery
from `mcts.py` — the structural change is in node identity and
selection, not in the value-evaluation pipeline.

### Phase 3: PUCT prior for ISMCTS

The existing NN policy head outputs a distribution over the action
vocabulary (`ACTION_VOCAB_SIZE`). At an ISMCTS node, only some
slots are legal (union over consistent worlds). Apply the same
masked-renormalize step that PUCT already does in `mcts.py`.

The trained policy head represents `P(action | information set)`.
That's exactly what the prior should be. No semantic shift needed —
just retarget the masking from "legal in *this* state" to "legal in
the information set" (which is the union — sometimes wider).

### Phase 4: replace PIMC at the call sites

`pimc.py` exposes `Strategy`-shape API. Build an `ISMCTSStrategy`
with the same shape (``choose``, ``choose_with_visits``, factory
that NNPimcConfig calls). Cut over:

1. `NNPimcConfig` → emit ISMCTSStrategy when configured for it.
   Keep PIMC available behind a flag for A/B comparison.
2. `data_gen.py`'s policy-target builder: simplify. The
   writer-side filter from `feature/policy-target-filter` becomes
   a no-op (every visit is on a slot in the union mask, and we
   already mask to information-set-legal slots before training).
   We can keep the filter as defense-in-depth or remove.

Re-baseline self-play and eval against PIMC on the existing v6
weights with matched budget. ISMCTS should be at least as strong;
the literature suggests measurable gains.

### Phase 5: what to delete

- `pimc.py` (after a few iters confirming ISMCTS is at least as
  strong).
- The writer-side filter in `data_gen.py` (subsumed; was a bandaid).
- Any test that pinned PIMC-specific behavior.

## Effort estimate

Best case 1 week, worst case 2-3. The phases that take time:

- Phase 1 (info-set identity): ~2 days. Subtle equivalence-relation
  bugs are hard to spot. Heavy reliance on property tests
  (determinize → must hash equally; mutate viewer-visible state →
  must hash differently).
- Phase 2 (search loop): ~2 days. Mostly mechanical port of
  `mcts.py` with the determinization-during-selection change. The
  batched / virtual-loss path is the trickiest carry-over.
- Phase 3 (PUCT prior): ~half a day. The current PUCT mask-and-
  renorm is reusable; only the mask source changes.
- Phase 4 (cut over + benchmark): ~2 days. A/B against PIMC on a
  fixed seed set, eval-gate iter loop end-to-end, smooth out edge
  cases.
- Phase 5 (deletion): few hours.

## Open questions to resolve before starting

- **Does the existing `determinize` produce information-set-
  equivalent samples cheaply enough?** ISMCTS calls it per
  iteration (at root only). PIMC calls it K times total. ISMCTS's
  per-call cost is the iteration count — at 200 nodes/iter, 200
  determinizations vs PIMC's K=4-8. The determinizer is currently
  O(hidden_zone_size); should be fast enough but worth measuring.
- **NN evaluator shape**. Does the existing `nn_evaluator.py`
  support evaluation of the determinization-specific leaf state,
  or does it implicitly assume the root-state action set? Spot-
  check before phase 2.
- **Replay capture**. The replay system today snapshots the
  concrete engine state at each priority moment. ISMCTS doesn't
  change that — replays continue to capture the actual played
  state, not the information set. Should be transparent.
- **Recommendation panel**. The training UI's recommendation panel
  uses `choose_with_visits` to surface a ranked list of "what
  would the bot do here?" — same API works for ISMCTS. Visit
  counts have slightly different semantics (per information set
  rather than per state) but the consumer doesn't care.

## References

- Cowling, Powley, Whitehouse. *Information Set Monte Carlo Tree
  Search*. IEEE Trans. on Computational Intelligence and AI in
  Games, 2012.
- Cowling, Whitehouse, Powley. *Emergent Bluffing and Inference
  with Monte Carlo Tree Search*. CIG 2015. (extends ISMCTS to
  card-game contexts more like MTG)
- Russell & Norvig, AIMA 4th ed. §17.6 (PIMC discussion + strategy
  fusion failure mode).
