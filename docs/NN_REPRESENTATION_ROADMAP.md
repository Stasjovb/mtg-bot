# NN representation roadmap

Forward-looking plan for moving the NN's view of game state away from the
hand-engineered fixed-width featurizer and toward a learned structured
representation. Captures the architectural reasoning, data-cost analysis,
and a phased path that doesn't bet the project on a single big-bang
rewrite.

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
- "8 turns of board pressure remaining" from "lethal next turn" (no
  turn / clock encoding).

Hand-engineering more aggregate features (mana-by-color, hand cost
histograms, etc.) buys local wins but does not break the
no-card-identity ceiling.

## Goal

Feed the NN the entire engine state — every card, every permanent,
every counter, every relationship — without information loss, and let
the trunk learn its own abstractions.

## What "lossless input" actually requires

The engine's `GameState` is fundamentally **variable-shape**:

- 0..N permanents per battlefield (each with full attribute set).
- 0..N cards per hand / graveyard / exile / library.
- 0..N items on the stack (each with controller, targets, mode
  selections).
- Variable per-turn history (spells cast this turn, lands played,
  damage dealt, etc.).

A flat fixed-size vector cannot represent this without truncating or
aggregating — which is exactly where the current 51-dim featurizer
loses information. So **"lossless" does not mean a much bigger flat
vector**; it means changing the input shape from a flat vector to a
structured set of per-object tokens, then aggregating with an
architecture that handles variable-length input.

Two canonical architecture choices:

1. **Self-attention transformer over a set of per-object tokens.** Each
   permanent, hand card, graveyard card, stack item gets its own token.
   Attention sees all of them. Pool to a fixed vector for the value /
   policy heads. This is the AlphaStar / OpenAI Five entity-attention
   pattern.
2. **Graph neural net over `GameObject`s with relation edges**
   (`attached_to`, `attacking`, `blocking`, `targeting`,
   `controlled_by`). More expressive for the inherently relational
   structure of MTG (auras, equipment, attackers vs blockers), but more
   complex to train.

Each token would carry:

- A **learned printing embedding** (~8-16 dim per printing, ~287 EoE
  cards = ~4,600 trainable params total — see "Phase 1" below).
- Structural attributes: P/T modifiers, counters of each kind, tapped
  state, summoning sick, damage marked, position in zone, controller,
  zone identity (encoded as a token-type embedding).

The stack becomes another set of tokens. Triggered-ability state,
delayed effects, continuous effects all become per-token features of
the appropriate object.

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

- **Auxiliary supervision** (see Phase 0 below) multiplies effective
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

## What MuZero would give vs cost

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

The latent `z` is whatever the optimizer finds most useful for
predicting future returns and future latent states under the dynamics
model. It is, in the most direct sense possible, **unsupervised
representation learning for the game state**.

### Why MuZero is appealing for MtG specifically

1. **The MtG engine is expensive to clone.** Cloning a `GameState`
   during MCTS is non-trivial even with the Rust port. A learned
   dynamics model is just a NN forward pass — potentially 10-100×
   faster than engine simulation, **if** the dynamics model is
   accurate enough.
2. **The MtG engine is complex.** Layers, replacement effects,
   triggered abilities, stack interactions, copy effects — a correct
   dynamics model has to implicitly learn all of this. A learned model
   bypasses the rules engine entirely during search (still needed for
   training and actual play).

### Why MuZero is hard / risky for MtG specifically

1. **MtG's rules are Turing-complete-ish.** For chess, dynamics is
   "apply move → new board." For MtG, the dynamics model has to learn
   the entire engine. Atari MuZero gets away with this because Atari
   dynamics are pixel-level deterministic functions; MtG has long-range
   causal chains and complex rule interactions.
2. **The dynamics model has to be accurate over the planning horizon.**
   If MuZero plans 10 moves deep, the dynamics model has to be roughly
   accurate over 10 steps. Errors compound. Training the dynamics model
   to be that accurate is a major research problem on its own.
3. **You still need the real engine.** Training requires real
   trajectories (otherwise value targets come from hallucinated
   rollouts). Real play requires the real engine. MuZero only avoids
   the engine **during MCTS** — a smaller fraction of total compute
   than for Atari.
4. **More heads, more data, more debugging complexity.** Pure
   AlphaZero: two heads (value, policy). MuZero: three heads, two of
   which jointly determine the latent space. When the agent plays
   badly: is the dynamics wrong? Is the representation pathological?
   Is the latent space collapsing? Versus AlphaZero where you can
   diagnose each head independently.

### Verdict on MuZero

For MtG specifically, the gap between **AlphaZero with structured
input** (Phase 1 below) and **MuZero** is enormous, and only makes
sense after AlphaZero with structured input has been pushed to its
plateau. Phase 1 captures the bulk of the "lossless input" benefit at
a fraction of the complexity. MuZero is the conceptual endpoint of
this path but should not be the next step.

## Phased plan

The plan is deliberately phased so each step is independently valuable
and each decision point gives empirical signal for whether to continue.

### Phase 0 — Auxiliary heads on the current featurizer

Cheapest empirical check that representation learning has signal in
this domain. No architecture change, no version-chain break.

**What:**

- Add an auxiliary head predicting opponent's hand contents (per-card
  probability over their decklist). Label from engine ground truth.
  Loss = multi-label binary cross-entropy.
- Optionally add a head predicting the next-state feature vector
  (next-step `extract_features(s')` after the chosen action). Loss =
  MSE.
- Mix at low weight (~0.05× of the main value+policy loss).

**Cost:** ~1 week eng. One new tensor per training row in the npz.
One new head, one new loss term in `trainer.py`. No schema break.

**Decision signal:** if value / policy validation loss improves with
the aux head active vs without, representation learning helps in this
domain and Phase 1's bigger investment is justified. If it doesn't,
think harder before Phase 1.

**Bonus path that's not strictly Phase 0 but uses the same head:**
the learned belief distribution over opponent's hand can bias PIMC
determinizations — instead of sampling K=8 uniform-ish worlds, sample
K=8 worlds weighted by what the belief network thinks is plausible.
Same head, double duty (training-signal AND search-time prior). The
existing `--use-belief-weighted` flag on `mtg_bot iterate` may already
have scaffolding for this — worth checking what shape its current
belief is.

### Phase 1 — Per-object transformer / GNN input

The "no nuance missed" architecture. The biggest single representational
upgrade available. Captures probably 80% of the long-term win.

**What:**

- Replace the 51-dim flat featurizer with a sequence of per-object
  tokens (permanents, hand cards, graveyard cards, stack items).
- Learned printing embeddings (8-16 dim per printing, jointly trained
  with rest of network). For EoE pool: ~287 cards × 16 dim = ~4,600
  embedding params.
- Each token = printing_embedding + structural attribute vector (P/T
  mods, counters, tapped, summoning sick, attached_to, controller,
  zone, position-in-zone).
- Trunk = self-attention transformer (or GNN). Maybe 2-4 attention
  layers, hidden dim ~256-512.
- Value / policy heads take the pooled trunk output.

**Cost:**

- ~3-5 weeks eng: model code (PyTorch transformer/GNN), dataset
  format change (variable-length per-state), `data_gen.py` rewrite
  for the new format, training loop tweaks.
- ~2-4 weeks of compute for hyperparameter sweep (number of attention
  layers, embedding dim, training data scale).
- **Version chain breaks.** v25 → v26 fresh init. All existing weights
  incompatible with the new input shape.
- ~3-5× more total parameters than today's MLP trunk (mostly in the
  transformer layers and embedding tables).
- ~5-10× more samples needed to fully exploit the bigger model. Scale
  the cluster, run more iters.

**Implementation hurdles:**

- The input is no longer fixed-shape (variable permanents per board),
  so the training pipeline needs to handle variable-length sequences.
  Padding + attention masks are the standard approach.
- The MCTS NN-eval cache key (`mcts._cache_key`) currently assumes a
  fixed-shape featurization. Needs to be rebuilt around the structured
  input (likely a canonical-state hash already exists in
  `canonical_state.py`).
- The SHM eval server's shared-tensor pool assumes fixed-dim per slot.
  Will need to allocate for the max sequence length and use attention
  masks for short inputs.

**Decision signal:** if value / policy loss drops meaningfully vs the
final Phase 0 baseline, the structured input was worth it. If not, the
hand-engineered features were closer to information-complete than
expected, and we should rethink.

### Phase 2 — Scale up auxiliary supervision

Once the trunk can represent structured info, push harder on
self-supervised signals that the simple aggregate featurizer couldn't
support.

**What:**

- Belief weighting feeds PIMC determinizations (the bonus path from
  Phase 0, now on the more-expressive trunk).
- Masked-token prediction: mask some objects, predict their attributes
  from context. BERT-style.
- Multi-step dynamics: predict the feature vector N steps ahead. Forces
  the trunk to encode dynamics-relevant state.
- Action-consistency loss: prediction of `V(s')` for the most-visited
  child must agree with `V(s)` minus the action's local effect.

**Cost:** ~2-3 weeks eng + ongoing compute. Aux losses are cheap
(just new heads and loss terms). Bigger cost is the dataset infra to
record the multi-step state windows.

### Phase 3 (optional, ambitious) — MuZero or hybrid

Consider **only** if:

- Phase 1+2 has measurably plateaued.
- The dominant bottleneck is engine clone cost during MCTS (not
  representation quality).
- There's appetite for multi-month research-grade work with a real
  risk of "it doesn't beat AlphaZero with structured input."

**What:** full MuZero — learned representation, learned dynamics,
learned prediction. MCTS in latent space. Engine used only for
training data generation and real play.

**Cost:** months. Possibly research-grade. Most existing infrastructure
for "engine state → features" gets thrown away; instead you have
"engine state → observation tensor" + "learned dynamics."

**Honest take:** Phase 1 captures most of the win. Phase 3 is the
conceptually clean endpoint but the marginal upside over Phase 1+2 is
small relative to the cost. Worth knowing about, not worth prioritizing
unless Phase 1+2 has plateaued.

## Decision points / triggers

- After Phase 0: if aux losses help, commit to Phase 1.
- After Phase 1: if structured input doesn't beat the final 51-dim
  baseline by a meaningful margin, rethink before Phase 2 (maybe the
  bottleneck isn't input, maybe it's the search or the loss
  formulation).
- After Phase 2: revisit MuZero only if (a) the plateau is real and
  (b) engine clone cost during MCTS is the dominant fraction of
  wall-clock.

## Constraints / what stays fixed

- **Action encoding** (`src/mtg_bot/training/action_encoding.py`)
  stays at canonical_v2 for now. The action space is a separate
  concern from the state representation. Changing both at once is too
  much change at once.
- **Self-play / training / eval orchestration** doesn't change. The
  cluster, the iterate loop, the eval gate, the watcher — all still
  work the same way. Only the model architecture and the dataset
  format change.
- **Engine and Rust port** don't change. The engine is the source of
  truth for ground-truth state and for actual play.

## References

- Current featurizer: `src/mtg_bot/features.py` (51 dims, layout
  documented in module docstring + index constants).
- Trainer: `src/mtg_bot/training/trainer.py`.
- Belief-weighted MCTS scaffolding: search for
  `use_belief_weighted` in `src/mtg_bot/cli/iterate.py` and
  `src/mtg_bot/search/`.
- Canonical state hashing (for cache keys): `src/mtg_bot/training/canonical_state.py`.
- MuZero paper: Schrittwieser et al., "Mastering Atari, Go, Chess and
  Shogi by Planning with a Learned Model" (Nature 2020).
- ReBeL / DeepStack (the belief-network pattern this doc references
  for the aux head): Brown et al., "Combining Deep Reinforcement
  Learning and Search for Imperfect-Information Games" (NeurIPS 2020).
- AlphaStar (entity-attention precedent): Vinyals et al., "Grandmaster
  level in StarCraft II using multi-agent reinforcement learning"
  (Nature 2019).
