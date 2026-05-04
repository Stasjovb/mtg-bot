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

### Phase 6: belief-weighted determinization (opponent modeling)

Plain ISMCTS uniform-samples determinizations from the deck-list-
consistent unknown pool. Real Magic players don't reason that way:
"opponent passed in a spot where any version of their hand with
removal would have used it; therefore P(removal) decreased". We
should be doing the same — sampling determinizations from a
posterior that conditions on the opponent's observed action history.

**Bayesian formulation.** Let *H* be a possible hand for the
opponent (consistent with the public history — discards, exiles,
mulligans, hand-size cap), and let *A* be the sequence of actions
they actually took. We want the posterior

    P(H | A) ∝ P(A | H) · P(H)

- P(H) — the prior — is what `determinize.py` already samples from
  uniformly. Stays uniform here (we don't have card-frequency priors
  beyond the deck list).
- P(A | H) — the likelihood — is the opponent's policy given that
  they actually held *H*. We have a model for this: the trained NN
  policy head. For each step in *A* where the opponent had priority,
  reconstruct the engine state with hand *H*, query the NN's policy
  distribution, and read off the probability of the action they
  actually took. Multiply across the sequence.
- Reweighted sampling: instead of uniform sampling K determinizations,
  sample-and-importance-weight (or run a particle filter): generate
  a pool of M candidate determinizations (M >> K), score each with
  the likelihood, normalize, then sample K from the reweighted
  distribution.

**What this fixes.** The "opponent probably doesn't have a removal
spell" reasoning falls out automatically. In any candidate world
where the opponent had removal, P(A | H) drops — they would have
used it in the spots where it was a strong play, and they didn't.
Worlds without removal get a higher likelihood and dominate the
posterior. ISMCTS then sees a non-uniform mix of worlds and its
visit counts naturally weight toward the "no removal" interpretation.

**Where it hooks in.** This sits cleanly on top of plain ISMCTS
from Phase 2. The ISMCTS search loop's `self.determinize_fn(state,
viewer, rng=...)` callback is the only seam that changes — point
it at a `belief_weighted_determinize` function instead of the
plain one. The rest of the search is identical. The Phase 1
information-set keying isn't affected (still keyed by viewer-
visible state); only the per-iteration sampling distribution shifts.

**Complications worth flagging now**:

- **Action history length × policy queries**. Computing P(A | H)
  for an N-action history requires N policy-head forward passes per
  candidate determinization. With M candidates and N=20 turns × 5
  actions/turn = 100 actions, that's 100 × M NN queries per
  reweight. Cache aggressively (the same hand evaluated across
  successive reweights overlaps heavily; an LRU keyed on the
  hand's printing tuple should kill 80% of the cost).
- **Self-play vs opponent-policy mismatch**. We're using *our* NN
  to model the opponent. That's correct *if* the opponent is the
  same NN (true in self-play and in eval-gate matches). For real
  opponents (humans, off-policy bots) it's a strong simplification
  — the opponent might play a strategy our model doesn't reflect.
  In an iterate-loop context where every game is bot-vs-bot,
  this isn't a problem.
- **Numerical underflow**. Likelihoods multiply across actions and
  go to zero fast. Compute log-likelihoods, normalize via
  log-sum-exp before re-exponentiating to weights. Standard
  particle-filter hygiene.
- **First-move bias**. At turn 0 there's no observed action history
  → posterior = prior → uniform. The first few decisions of an
  iter or game contribute uniform-sampled determinizations and
  Phase 6 reduces to Phase 2 there. That's correct, just worth
  expecting.
- **Forward-simulating the opponent's decisions**. To compute P(A
  | H) at each opponent decision point, you need to reconstruct
  the engine state *as it was at that moment*, not just at the
  current root. Either (a) record opponent-decision-point snapshots
  during the played-game-so-far (cheap; replay machinery already
  records priority moments), or (b) replay the action history
  forward from the initial state with the candidate hand each
  time (expensive). (a) is the right answer; the replay system
  was already designed around the priority-moment snapshot pattern.

**Concrete implementation steps**:

1. New module `mtg_bot/search/belief.py` exposing
   `belief_weighted_determinize(state, viewer, rng, *, opponent_policy,
   action_history, m_candidates=64)`. Returns one sampled state.
2. Particle-filter mechanics: generate m_candidate uniform
   determinizations, score each with the opponent NN against the
   recorded priority-moment snapshots, normalize weights, resample
   one (or maintain a running particle set across game-state
   updates if we want to track belief over the whole game — this
   is a nicer architecture but more invasive).
3. Wire as the `determinize_fn` for ISMCTS via NNPimcConfig
   replacement; keep uniform determinization available behind a
   flag for A/B comparison.
4. Eval against plain ISMCTS on a held-out seed set. Belief-
   weighted should be at least as strong on hand-info-sensitive
   matchups (decks with removal, counters, situational cards);
   neutral or slightly worse on aggro mirrors (less hidden info to
   reason about).

**Effort estimate**: ~3-5 days, on top of Phases 1-5. Most of the
code is straightforward (sample + score + resample), but caching
strategy + the priority-moment snapshot wiring need careful
engineering. Phase 6 is *additive* over plain ISMCTS — ship Phases
1-5 first, then layer this on; don't try to build it all at once.

**Variants worth considering after the basic version works**:

- **Sequential particle filter with persistent state**. Instead of
  re-scoring from scratch every search call, maintain a particle
  set across the whole game. Update by reweighting each time the
  opponent acts. Cheaper and more accurate (particles get
  progressively concentrated as info accumulates).
- **POMCP-style integrated belief MCTS**. Move belief-tracking
  inside the search rather than at root sampling. ISMCTS already
  does this implicitly through its information-set tree; POMCP
  formalizes it as a particle distribution at each node. Heavy
  reformulation; only worth it if particle-filter ISMCTS proves
  insufficient.

References:

- Russell & Norvig 4th ed. §17.6 (POMDPs and belief states — the
  textbook framework).
- Silver & Veness 2010, "Monte-Carlo Planning in Large POMDPs"
  (POMCP — the canonical particle-filter MCTS).
- Cowling, Whitehouse, Powley 2015 (referenced for ISMCTS variants
  in card games — they explicitly discuss bluffing and inference
  in Phantom Bridge, which is the same problem class).

## Effort estimate

Phases 1-5 (plain ISMCTS): best case 1 week, worst case 2-3.
Phase 6 (belief-weighted determinization): additional 3-5 days,
shipped after 1-5 are validated.

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
- Phase 6 (belief-weighted determinization): ~3-5 days. Particle
  filter + NN-policy-as-likelihood + priority-moment snapshot
  wiring + caching. Layered cleanly on top of plain ISMCTS via the
  `determinize_fn` callback; don't co-develop with Phases 1-5.

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
