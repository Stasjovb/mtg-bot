# NN representation roadmap

Plan for moving the NN's view of game state away from the hand-engineered
fixed-width featurizer and toward a learned structured representation.

**Status:** the four-step committed plan in this doc replaces the earlier
research-style Phase 0/1/2/3 decision tree. We're not running Phase 0 (aux
heads on the current featurizer) as a probe — we're committing directly
to the structured input. We're explicitly not pursuing Phase 3 (MuZero).

## Current state

The NN evaluator's input today is a fixed 51-dim float vector produced
by `src/mtg_bot/features.py`. Layout (see `features.py:48-104` for the
authoritative index constants):

| Block | Indices | Contents |
|---|---|---|
| viewer per-side | 0-15 | life, poison, hand / library / graveyard / exile sizes, lands, untapped lands, creatures, other permanents, total power, total toughness, max threat P/T, tapped permanents, lands played this turn, spells cast this turn |
| opponent per-side | 16-31 | same shape, opponent perspective |
| viewer keyword counts | 32-39 | flying, first strike, double strike, deathtouch, lifelink, trample, vigilance, reach |
| opponent keyword counts | 40-47 | same |
| global | 48-50 | stack size, is-viewer's-turn, step index 0-11 |

Documented limitations from the module docstring (`features.py:6-30`):

> **No card-identity awareness.** Features are aggregates (counts, sums,
> max). A "good 4/3" and a "bad 4/3" look identical here. That's the
> documented ceiling of this representation; per-card embeddings are a
> Phase E ambition.

That ceiling is the immediate bottleneck. The NN cannot distinguish:

- "5 untapped lands" that produce WUBR from "5 untapped lands" that all
  produce R (mana base composition is invisible).
- "Atomic Microsizer in hand" from "Phantasmal Dreadmaw in hand"
  (card identity is invisible).
- "Counterspell on top of stack" from "Lightning Bolt on top of stack"
  (stack contents collapse to one scalar).
- "Opponent has had 5 turns of UU mana open and never countered anything"
  (game history is not in the input — at all).
- "8 turns of board pressure remaining" from "lethal next turn" (no
  turn / clock encoding).

Hand-engineering more aggregate features (mana-by-color, hand cost
histograms, etc.) buys local wins but does not break the
no-card-identity ceiling or the no-history ceiling.

## Goal

Feed the NN the entire engine state — every card, every permanent,
every counter, every relationship, plus the recent history of public
actions — without information loss, and let the trunk learn its own
abstractions.

## What "lossless input" actually requires

The engine's `GameState` is fundamentally **variable-shape**:

- 0..N permanents per battlefield (each with full attribute set).
- 0..N cards per hand / graveyard / exile / library.
- 0..N items on the stack (each with controller, targets, mode
  selections).
- Variable per-turn history (spells cast this turn, lands played,
  damage dealt, etc.).
- Variable game history (sequence of public actions taken).

A flat fixed-size vector cannot represent this without truncating or
aggregating — which is exactly where the current 51-dim featurizer
loses information. So **"lossless" does not mean a much bigger flat
vector**; it means changing the input shape from a flat vector to a
structured set of per-object tokens, then aggregating with an
architecture that handles variable-length input.

Two canonical architecture choices:

1. **Self-attention transformer over a set of per-object tokens.** Each
   permanent, hand card, graveyard card, stack item, recent action gets
   its own token. Attention sees all of them. Pool to a fixed vector for
   the value / policy heads. This is the AlphaStar / OpenAI Five
   entity-attention pattern.
2. **Graph neural net over `GameObject`s with relation edges**
   (`attached_to`, `attacking`, `blocking`, `targeting`,
   `controlled_by`). More expressive for the inherently relational
   structure of MTG (auras, equipment, attackers vs blockers), but more
   complex to train.

Each token would carry:

- A **learned printing embedding** (~8-16 dim per printing, ~287 EoE
  cards = ~4,600 trainable params total). Embeddings trained jointly
  with the rest of the network — the model discovers card2vec-style
  clusters from how cards correlate with winning.
- Structural attributes: P/T modifiers, counters of each kind, tapped
  state, summoning sick, damage marked, position in zone, controller,
  zone identity (encoded as a token-type embedding).

The stack becomes another set of tokens. Recent actions become tokens.
Triggered-ability state, delayed effects, continuous effects all become
per-token features of the appropriate object.

Nothing the engine tracks has to be aggregated or lost — it just has
to be expressible as per-object features plus relational edges.

## Data-cost analysis

The naive expectation is: more parameters → more data. The real picture
is more nuanced because the structured input dramatically improves
**generalization per parameter**.

**Current featurizer**: every 4/3 looks identical to the NN. The model
has to relearn "creatures of shape X are valuable in board state Y"
independently for every game state. Generalization across cards is
zero at the input layer.

**With printing embeddings**: learning that a particular card is good in
graveyard decks generalizes to every state featuring that card. The
model's effective sample efficiency goes up because each training
example teaches it something about more states.

Empirical rule of thumb from entity-attention game-playing nets
(AlphaStar, OpenAI Five, transformer-based chess engines): roughly
**5-10× more samples per training pass** vs the equivalent flat MLP.
Not 100×, not 1000× — well within the cluster's ability to scale by
running more iters and / or buying a couple more workers.

Mitigating factors that further reduce data hunger:

- **Auxiliary supervision** (Step 4 below) multiplies effective
  gradient signal per state.
- **Data augmentation is free** — features are viewer-relative so every
  state can train at both perspectives.
- **Replay buffers with prioritization** focus learning on high-loss
  states.
- **Already-existing self-play scale**: ~800K samples per iter, ~5M+
  accumulated. Scaling to 10M samples is "run more iters," not a
  fundamental data problem.

**The real cost is the version-chain break.** Every weight produced
under the current featurizer (v23, v24, v25, ...) becomes incompatible
the moment the input shape changes. Training has to restart from a
fresh init. That's a real cost in wall-clock time and compute, but it's
a one-shot cost, not an ongoing constraint.

## Why we're not pursuing MuZero

MuZero replaces "hand-engineer the features OR hand-engineer the
structured input" with "learn the entire state representation." It
trains three jointly-optimized heads:

- `representation(observation) → z` — encode the observable state into a
  latent vector `z`.
- `dynamics(z, action) → (z', reward)` — predict the next latent state
  given an action.
- `prediction(z) → (value, policy)` — predict value and policy from
  the latent.

MCTS runs in **latent space** using the learned dynamics, so search
becomes pure NN forward passes — no engine clones, no game-tree
expansion through the rules engine.

**Why MuZero is hard for MtG specifically:**

1. **MtG's rules are Turing-complete-ish.** For chess, dynamics is
   "apply move → new board." For MtG, the dynamics model has to learn
   replacement effects, layers, triggered abilities, stack
   interactions, copy effects. Atari MuZero gets away with this because
   Atari dynamics are pixel-level deterministic functions; MtG has
   long-range causal chains.
2. **The dynamics model has to be accurate over the planning horizon.**
   Errors compound. Training the dynamics model to be that accurate is
   a major research problem on its own.
3. **You still need the real engine** for training (real outcomes) and
   actual play. MuZero only avoids the engine **during MCTS**.
4. **Debugging is much harder** — three jointly-trained heads vs two,
   and the latent space is opaque.

**Verdict:** the gap between AlphaZero with structured input (the
committed plan in this doc) and MuZero is enormous. The structured-input
path captures the bulk of the representation-learning win at a fraction
of the complexity. MuZero remains the conceptual endpoint of the
unsupervised-features path, but we're not pursuing it. Revisit only if
the structured-input path plateaus *and* engine-clone cost during MCTS
becomes the dominant bottleneck.

## The committed plan

Four steps. Step 2 is independent of the rest and runs in parallel.
Step 3 is folded into Step 1 architecturally — they're one rewrite, not
two. Step 4 depends on 1, 2, 3 all being in place.

### Step 1 — Structured per-object input (consolidated)

The "lossless input" architecture, INCLUDING last-N action tokens from
the start. Single architectural rewrite, single version-chain break.

**What lands together in this step:**

- Replace the 51-dim flat featurizer with a sequence of per-object
  tokens: permanents, hand cards, graveyard cards, exile cards, stack
  items, **recent action events**, and a small set of global tokens
  (turn count, phase, priority).
- Each token carries a learned printing embedding (8-16 dim per
  printing, ~287 EoE cards × 16 dim = ~4,600 embedding params) plus
  structural attribute vectors.
- Trunk = self-attention transformer (2-4 attention layers, hidden dim
  ~256-512) over the token set. Optional: relational edges as GNN if
  attention isn't enough.
- Value / policy heads take the pooled trunk output.
- Configurable `N` for the recent-action window in input (default
  probably 16-32 strategically-relevant actions filtered from raw
  priority passes — see "Open design questions" below).

**Cost:**

- ~3-5 weeks eng: model code (PyTorch transformer/GNN), dataset
  format change (variable-length per-state), `data_gen.py` rewrite
  for the new format, training loop tweaks.
- ~2-4 weeks of compute for hyperparameter sweep.
- **Version chain breaks.** v25 → vN fresh init. All existing weights
  incompatible.
- ~3-5× more total parameters than today's MLP trunk (mostly in the
  transformer layers and embedding tables).
- ~5-10× more samples needed. Scale the cluster, run more iters.

**Implementation hurdles:**

- Variable-length input: padding + attention masks are the standard
  approach.
- The MCTS NN-eval cache key (`mcts._cache_key`) currently assumes a
  fixed-shape featurization. Rebuild around the structured input
  (likely via the canonical-state hash that already exists in
  `canonical_state.py`).
- The SHM eval server's shared-tensor pool assumes fixed-dim per slot.
  Allocate for the max sequence length and use attention masks.

**What folding action history into this step buys:**

Doing the lossless-input rewrite and adding last-N action tokens as
separate steps would mean two architectural rewrites, two version-chain
breaks, and two periods where the trunk is unstable. Doing them together
means the trunk is built for the full input shape from day one — same
eng cost as Step 1 alone for the trunk work (adding another token type
is cheap), with one v-chain break instead of two.

### Step 2 — Deck-belief model (offline, parallel)

A standalone supervised model trained on 17lands data with no
dependency on the main NN. Runs in parallel with Step 1.

**What:**

Given a multi-hot vector of cards the opponent has revealed (played,
cast, discarded), predict a probability distribution over which other
cards are in their deck.

**Why it works as a fully offline problem:**

The opponent's deck doesn't change during the game — it's a fixed
property of the player, and what changes is our knowledge of it. Each
revealed card is a sample drawn from the (private) deck. This is
Bayesian posterior tracking over an unknown decklist given observations
— same structure as poker range tracking. The training data is just
17lands decklists with sampled prefixes:

```
training tuple = (revealed_cards: multi-hot[287], rest_of_deck: multi-hot[287])
```

Generated by walking each decklist in `data/17lands/eoe_decks.json.gz`
and randomly choosing prefixes of varying sizes. For ~5,000 EoE decks
× ~40 cards × ~10 prefix sizes each, ~2M training rows.

**Cost:** ~1-2 days eng. Tiny model (input ~287, output ~287, hidden
128-256, or even a co-occurrence matrix with Bayesian smoothing as a
baseline). Trains in minutes on a 5090.

**Standalone value before Step 4 lands:**

Even before integration with the hand-belief head, the deck-belief
model can bias PIMC determinizations directly — instead of sampling K=8
opponent decks uniformly, sample weighted by the deck-belief
distribution. This is importance sampling for hidden-info search and
should improve search quality at fixed K.

### Step 3 — Last-N action tokens in NN input

**Folded into Step 1.** Not a separate step in execution. The
structured-input rewrite includes recent-action tokens from day one.
Documented separately here because the design choices (action
representation, filtering, N defaults) are distinct concerns even
though they share an architecture with Step 1.

### Step 4 — Probability-over-hand head

Bolts onto Step 1's trunk, conditioned on Step 2's deck-belief.

**Architecture:**

```
trunk_z = trunk(state_tokens)                                     # from Step 1
deck_belief = deck_model(opponent_revealed_cards)                 # from Step 2
hand_belief = hand_head(trunk_z, deck_belief.detach())            # new in Step 4
```

The `.detach()` prevents gradients from the hand-belief head from
polluting the deck-belief model's learning. Hand-belief reads
deck-belief as a fixed conditional input.

**Loss:** multi-label binary cross-entropy. Each card in opponent's
decklist gets a P(in hand right now) target from engine ground truth
during self-play training. Weight in the total loss: ~0.05× the main
value+policy losses.

**Why the trunk now has the information to learn the counterspell-not-cast
signal:**

The current featurizer encodes essentially no game history, so a
belief head built on it literally cannot learn "opponent had counter
mana open for 5 turns and didn't act → counterspell unlikely." Step 1's
structured input includes recent action tokens, so the trunk sees
"opp_passed_priority during my high-value spell with N mana open" as
discrete events. The hand-belief head learns the conditional
probabilities over many self-play trajectories.

**Inference use:**

Both deck-belief and hand-belief outputs feed PIMC determinization
sampling — picking opponent worlds weighted by what we currently
believe is plausible. This is the ReBeL / DeepStack pattern in poker
exactly: maintain a belief distribution over opponent's hidden range,
sample from it during search.

## Open design questions to nail down before Step 1 starts

1. **What is an "action"?** Decisions in MtG are heterogeneous: cast
   spell, activate ability, pass priority, choose blocker assignment,
   choose target, scry top of deck. Fixed-shape per-action token shape
   needs to be decided up front. Probable shape:
   `(action_kind, source_object_or_emb, target_object_or_emb,
   mana_cost_paid, controller, turn, step)`. Open: whether to include
   the value the bot estimated at the time the action was taken — a
   strong signal, but requires capturing it at data-gen time.

2. **Action visibility per player.** Some actions are public (cast
   spell, attack), some have private components (scry reveals the top
   card only to the scryer). Featurize from each player's perspective —
   their own private observations + the public history.

3. **N's default and the within-turn density problem.** Last 32 raw
   actions might cover only 2-3 turns in dense combat phases. Last 8
   turns might be 100s of actions. Likely answer: filter to
   strategically-relevant actions (cast / activate / attack / block /
   discard) and drop raw priority passes from the input. Defaults
   probably N=16-32 with the filter applied.

4. **PIMC integration design.** `mtg_bot iterate` already has a
   `--use-belief-weighted` flag — survey what its current
   implementation actually does (uniform? heuristic-weighted?) before
   designing the new pipeline. The integration point for both
   deck-belief (Step 2) and hand-belief (Step 4) is where PIMC picks
   determinizations; replace the current sampler with importance
   sampling from the learned beliefs.

5. **Cache key for the new trunk.** The MCTS NN-eval cache assumes
   fixed-shape input today. Likely answer: hash the canonical-state
   representation (`canonical_state.py` already provides this) rather
   than the raw input tensor.

6. **Pooling strategy for value / policy heads.** Attention output is
   per-token; the value head needs a single scalar and the policy head
   needs a fixed action-vocab distribution. Common pooling choices:
   mean-pool over tokens, attention-pool with a learned query, take a
   `[CLS]`-style summary token. Worth picking before training starts;
   wrong choice can cap performance regardless of trunk quality.

## Validation strategy per step

**Step 1 (structured input):**

- Value / policy loss on a held-out test set, vs the final v25
  baseline.
- Head-to-head match between Step-1 trunk and v25 at matched search
  budget (same nodes, same K). The trunk has to win at the deployment
  configuration to justify the v-chain break.
- Wall-time per game and per training epoch — confirm the larger model
  isn't blowing the per-iter time budget.

**Step 2 (deck-belief):**

- Predict-rest-of-deck accuracy on held-out 17lands decks. Target
  probably 70-85% recall at the right confidence threshold.
- Calibration plot: P(card in deck) vs empirical frequency.
- Standalone PIMC win-rate at fixed K with belief-weighted
  determinizations vs uniform. Even before Step 4, this is the
  standalone measurable value of Step 2.

**Step 4 (hand-belief):**

- Predict-hand-contents accuracy on held-out self-play games.
- Calibration plot.
- Effect on PIMC determinization quality (does importance-weighted
  sampling at fixed K beat uniform at fixed K?).
- The decisive signal: head-to-head match with hand-belief PIMC
  weighting vs without, at matched K — does the bot actually play
  better?

## Compute scaling

Step 1's larger model needs ~5-10× more data than today's pipeline.
At the current cluster's ~510 g/h with SHM (Win11 master + macOS + Win10
shards), producing 5M samples per iter takes ~10 hours of self-play per
iter. Manageable but not painless. Realistic paths:

- Accept slower iter cadence (one full iter per day instead of multiple).
- Scale the cluster: add a fourth machine, or enable SHM on the macOS
  shard (currently gate-excluded — separate followup).
- Reduce K in PIMC if Step 2 + Step 4 succeed at giving smarter
  determinizations (importance-sampled K=4 might match uniform K=8).
- Replay buffer + prioritized sampling to extract more gradient signal
  per recorded sample.

## Constraints / what stays fixed during this work

- **Action encoding** (`src/mtg_bot/training/action_encoding.py`) stays
  at canonical_v2. The action space is a separate concern from the
  state representation; changing both at once is too much change at
  once.
- **Self-play / training / eval orchestration** doesn't change. The
  cluster, the iterate loop, the eval gate, the watcher — all still
  work the same way. Only the model architecture, the dataset format,
  and the determinization sampler change.
- **Engine and Rust port** don't change. The engine is the source of
  truth for ground-truth state and for actual play.

## Sequencing summary

| When | What | Why |
|---|---|---|
| Now (parallel) | Start Step 2 (deck-belief model) in its own worktree | Offline, fast, fully decoupled from Step 1 — get it done while Step 1 is still in design |
| Optional, soon | Use Step 2's output as PIMC determinization prior (no main-NN changes needed) | One-week win, plugs into existing PIMC, no v-chain break |
| Major commit | Step 1 — consolidated structured-input rewrite (per-object tokens + learned embeddings + last-N action tokens) | Single architectural rewrite; avoids two v-chain breaks |
| After Step 1 lands | Step 4 — hand-belief head conditioned on Step 2's deck-belief | All substrate is in place; this is the natural integration point |

## What we explicitly rejected from the earlier doc version

- **Phase 0** (aux heads on the current 51-dim featurizer as a probe):
  the current featurizer is too information-poor for aux heads to
  surface their real potential. Phase 0 would underestimate the win,
  and its plumbing work would be partially throwaway when Step 1
  rewrites the dataset format. Skipping straight to Step 1 captures
  the real signal sooner.
- **Phase 3** (MuZero / learned dynamics in latent space): see "Why
  we're not pursuing MuZero" above. The complexity gap to Step 1 +
  Step 4 is enormous, and the marginal upside is small for an
  engine-rich domain like MtG. Revisit only if Step 1 + Step 4
  plateaus and engine-clone cost during MCTS becomes the dominant
  bottleneck.

## References

- Current featurizer: `src/mtg_bot/features.py` (51 dims, layout
  documented in module docstring + index constants).
- Trainer: `src/mtg_bot/training/trainer.py`.
- Belief-weighted MCTS scaffolding: search for `use_belief_weighted`
  in `src/mtg_bot/cli/iterate.py` and `src/mtg_bot/search/`.
- Canonical state hashing (for cache keys):
  `src/mtg_bot/training/canonical_state.py`.
- 17lands deck pool: `data/17lands/eoe_decks.json.gz` (5,000 EoE
  decks; the deck-belief training data source).
- MuZero paper (not the path we're taking): Schrittwieser et al.,
  "Mastering Atari, Go, Chess and Shogi by Planning with a Learned
  Model" (Nature 2020).
- ReBeL / DeepStack (the belief-network pattern Step 4 mirrors):
  Brown et al., "Combining Deep Reinforcement Learning and Search for
  Imperfect-Information Games" (NeurIPS 2020).
- AlphaStar (entity-attention precedent for Step 1):
  Vinyals et al., "Grandmaster level in StarCraft II using multi-agent
  reinforcement learning" (Nature 2019).
