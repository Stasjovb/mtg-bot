# NN representation roadmap

Plan for moving the NN's view of game state away from the hand-engineered
fixed-width featurizer and toward a learned structured representation.

**Status:** the four-step committed plan in this doc replaces the earlier
research-style Phase 0/1/2/3 decision tree. We're not running Phase 0 (aux
heads on the current featurizer) as a probe — we're committing directly
to the structured input. We're explicitly not pursuing Phase 3 (MuZero).

**Implementation status (2026-05-17 — verified against `trained_weights/`):**

- **Step 1 (structured per-object input) — LANDED.** The production
  v-chain is `architecture: structured` for **every** registered
  version `v1`–`v10` (`current_best: v5`, per
  `trained_weights/iterate_state.json`). Input is built by
  `mtg_bot.training.state_tokenizer` → `StructuredModel`, **not**
  `features.py`. `v1` was the random-init cold-start; `v2` onward
  were trained on the structured representation.
- **Step 3 (last-N action tokens) — LANDED**, folded into Step 1 as
  designed: the tokenizer emits the filtered, viewer-redacted
  last-32 action history (`structured_config.action_history_n: 32`).
- **Step 2 (offline deck-belief) — NOT landed.** Hidden information
  is still handled by PIMC determinization; the tokenizer
  deliberately emits the opponent hand as anonymous slots
  (`PRINTING_NA`, `public_mask=0`).
- **Step 4 (hand-belief aux head) — NOT landed** (depends on Step 2).
- The legacy 51-dim `features.py` featurizer + flat `_ValuePolicyMLP`
  trunk is the **pre-structured** path; those weights (`v11`–`v16`,
  the 1024-1024-512 trunk) are **archived** at
  `trained_weights/archived_pre_structured/` and are not production.
  The "Current state" section below describes that **superseded
  baseline** — retained for the design rationale (why structured was
  necessary), not as a description of today.
- **Net-scale caveat** (see `docs/BENCHMARKING_FINDINGS.md` §2A): the
  shipped structured trunk is **small** (`emb_dim 128, n_layers 2,
  hidden_dim 256`). "Structured input has landed" ≠ "the trunk is
  large" — trunk capacity/depth-vs-data is an **open** question, not
  closed by Step 1.

## Current state

> **Superseded — pre-structured baseline (historical).** This section
> describes the legacy 51-dim featurizer that motivated the rewrite;
> it is **not** the production input as of 2026-05-17 (see
> "Implementation status" above). Kept for the design rationale.

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

**Skeleton model (landed by `feature/step1-design`):**

A working PyTorch skeleton lives at
`src/mtg_bot/training/structured_model.py`. It implements all six
resolved design decisions above:

- 22-entry action-kind vocab + viewer-relative controller + shared
  printing embedding + token-type-mixed input pipeline (§1).
- Per-token `public_mask` scalar — the viewer-relative encoding is
  filled in by the data pipeline (§2); the model just consumes the
  mask.
- Configurable `action_history_n` (default 32) (§3).
- Cross-attention policy decoder over a fixed
  `ACTION_VOCAB_SIZE × emb_dim` slot-embedding table (§6).
- Learned `[CLS]` summary token + tanh-activated value head (§6).
- Aux-head stub for hand-belief: a `(n_printings, emb_dim)` query
  table that cross-attends to the trunk and emits per-printing
  P(in-hand) logits. Disabled by default; Step 4 will turn it on.

`forward(batch)` accepts a dict of `{token_type_ids, token_emb_ids,
token_scalars, attention_mask, ...}` tensors (no engine dependency)
and returns `{value, policy_logits, hand_belief_logits}`. Tests in
`tests/training/test_structured_model.py` exercise random batched
input, output-shape checks, gradient flow, and variable-length
padding.

**Implementation slices that build on this skeleton:**

1. **Dataset-format conversion** (separate slice): rewrite
   `data_gen.py` to emit per-token features instead of the 51-dim
   flat featurizer. Builds per-viewer action streams (§2 redaction
   rules), applies the §3 filter, packs to the skeleton's batch
   format.
2. **Training-loop integration** (separate slice): update
   `trainer.py` to consume the new batch shape; same masked-CE +
   value-MSE loss, just routed through `structured_model.forward`.
3. **SHM eval server compat path** (separate slice): the existing
   shared-tensor pool assumes fixed-dim per slot; allocate for the
   max sequence length and propagate the attention mask. See the
   "Implementation hurdles" bullet above.
4. **Cache-key migration** (small slice): switch
   `mcts._cache_key` to drop the slot_fp suffix once the new trunk
   is wired in (§5).
5. **Lineage / v-chain naming** (separate slice; explicitly
   deferred): pick the version label once the trunk passes its
   smoke and the v-chain break is imminent.

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

## Resolved design decisions

Each entry below pins a concrete recommendation grounded in the current
codebase. The skeleton model at `src/mtg_bot/training/structured_model.py`
implements these decisions; subsequent implementation slices build on
it without re-litigating.

### 1. What is an "action"? — fixed-shape per-action token

The engine surfaces actions across three call sites:

- **Priority actions** (`src/mtg_bot/actions.py`): the nine
  `Action` subclasses — `PassPriority`, `PlayLand`, `CastSpell`,
  `UnlockRoomHalf`, `ActivateAbility`, `ActivateStation`,
  `TurnFaceUp`, `DeclareAttackers`, `DeclareBlockers`.
- **Factored combat decisions** (`src/mtg_bot/search/combat_decisions.py`):
  `AttackerDecision`, `BlockerDecision` — emitted per pending creature
  when the adapter has `expose_combat_decisions=True`.
- **Resolution decisions** (`src/mtg_bot/search/resolution_decisions.py`):
  11 `Resolution*Decision` types — `Target`, `Discard`, `Mode`,
  `Sacrifice`, `X`, `Surveil`, `ShockLife`, `CardFromLibrary`,
  `CardFromOpponentHand`, `YesNo`, `DevourLands`. Surfaced
  mid-resolution when `expose_resolution_decisions=True`.

The action token is a fixed-length feature tuple, with each field
rendered as a learned embedding (small int-coded categoricals) or
a normalized scalar (continuous fields):

| Field | Encoding | Notes |
|---|---|---|
| `action_kind` | embedding | 22-entry vocab: 9 priority + 2 combat + 11 resolution kinds (see `ACTION_KIND_VOCAB` in `structured_model.py`). One-hot rejected (no parameter sharing). |
| `controller` | embedding | 3-entry vocab: viewer, opponent, NA (resolution YesNo from a non-controller, etc.). Viewer-relative — same physical action gets a different controller code per viewer. |
| `source_printing` | embedding | Looks up `printing.name` against the same printing-embedding table state tokens use. NA-token (id 0) for actions with no source (pass priority, mode/yes-no without a tied source). Shared table is the whole point of the goal section's "card-2-vec clusters." |
| `target_printing` | embedding | Same printing-embedding table; NA when no target. Multi-target spells emit multiple tokens (one per target) — keeps the per-token shape fixed. |
| `target_kind` | embedding | 6-entry vocab: none, player, permanent, stack-item, hand-card, exile-card. Disambiguates `target_printing`. |
| `variant` | embedding | 8-entry vocab covering the cast-variant + room-half + ability-index axis (`normal` / `kicked` / `warp` / `cast_for_free` / `impending` / `room_half_0` / `room_half_1` / `private_choice`). Mirrors `action_encoding.py`'s slot taxonomy. |
| `turn` | scalar | `(turn_at_action − current_turn)` clamped to `[−16, 0]` then divided by 16. Negative = how many turns ago. Recency rather than absolute turn — temporal gap matters, absolute turn shouldn't. |
| `step` | embedding | 12-entry vocab matching `features.py`'s step-index 0..11. |
| `mana_cost_paid` | scalar | CMC of mana actually spent on this action, divided by 10. Captures "this was a 4-drop" vs "this was a free trigger." 0 for non-cast actions. |
| `public_mask` | scalar | 0/1 indicator (see §2). 1 = token fully observable to the viewer; 0 = some field has been redacted. Lets the trunk learn "I have less information about this event." |

Total per-token raw shape: 7 embedding ids + 3 scalars = a
`(seq_len, 7)` long tensor plus a `(seq_len, 3)` float tensor.
Padded entries get a boolean attention mask (Step 1's input is
variable-length).

**Scalar schema v2 (landed 2026-09-22).** The 3-scalar row above is
*scalar schema 1*. It gave the trunk no life totals and no board
state (a permanent token was printing + controller + step only).
Schema 2 keeps those three slots at indices 0..2 and appends 26
slots (`N_SCALAR_FIELDS_V2 = 29`; constants in
`structured_model.py`): per-permanent `tapped`, `is_creature`,
`power/8`, `toughness/8` (engine `effective_*`, layer-aware),
`damage/8`, net `+1/+1` counters/4, other counters/4,
`summoning_sick`, `attacking`, `blocking`; and on the `[GLOBAL]`
token viewer/opp `life/20`, `poison/10`, `library/40`, `hand/7`,
`turn/20`, untapped lands/8, lands/8, `stack/4`, `is_viewer_turn`,
`viewer_has_priority`. Hand / graveyard / exile / stack / action
tokens leave the new slots at zero. The version is recorded per
checkpoint (`ModelMetadata.scalar_schema_version`; absent = 1) and
sizes `scalar_proj`, so v1..v14 / v13s keep loading with their
3-wide projection; `StructuredModelConfig` and `tokenize_state`
default to 2 for new training (`mtg_bot train
--scalar-schema-version`). The trainer refuses a dataset / model
width mismatch. Switching schema is a v-chain break (fresh init).

**Value-estimate-at-time-of-action: NOT included in v1.** Capturing
the bot's MCTS posterior value at every priority moment would plumb
through `data_gen.py` and bloat per-game logs. The skeleton reserves
room for it as a future `aux_scalar` field; the data-pipeline slice
can add it without an architectural change.

### 2. Action visibility per player — viewer-relative tokens

Per-viewer encoding rules. Each token is rendered TWICE during
data-gen — once per seat — so the dataset has both perspectives of
every state.

- **Public actions** (cast spell, play land, attack, block, activate
  visible ability, pass priority): all token fields identical across
  viewers except `controller` (viewer-relative).
- **Partially hidden actions** — these are the only ones where any
  field differs between perspectives:
  - **Scry / Surveil**: the chosen `mill` / leave-order is private
    to the scryer. From the non-scryer's perspective, the token's
    `variant` is masked to `private_choice` (vocab id 7) and
    `public_mask=0`.
  - **Discard chosen by controller** (Mind Rot–style "discard a
    card"): the discarded `card_id` is public once it hits
    graveyard, so the token has `target_printing` = that printing
    in both perspectives. Same-turn "look but don't reveal"
    effects (rare in EoE, none confirmed in pool today) would
    mask `target_printing` to NA for non-actor viewers.
  - **CardFromLibrary** (tutor): chosen card is private. From the
    non-tutorer's perspective `target_printing` is masked to NA
    and `public_mask=0`. The tutor itself stays observable
    (source_printing + action_kind).
  - **CardFromOpponentHand** (Thoughtseize-style): both players
    see the picked card under current rules conventions. Token is
    public to both viewers.
- **Pass-priority tokens** are dropped at the filter step (§3), so
  visibility doesn't matter for them.

The data pipeline (a separate slice; see "Implementation slices"
below) materializes per-viewer action streams from a single
self-play game by maintaining one append-only token log per seat
and writing per-token redaction at record time.

### 3. N's default and the within-turn density problem — N=32 with filter

**Filter rule (applied at data-gen, before tokens hit the model):**

Keep only "strategically-relevant" actions:

- `CastSpell` (all variants)
- `PlayLand`
- `UnlockRoomHalf`
- `ActivateAbility` for non-mana abilities only (mana abilities
  drop because the resulting tap is already visible via the next
  state's structural tokens)
- `ActivateStation`
- `TurnFaceUp`
- `DeclareAttackers` (recorded as one token per attacking creature
  for fixed shape)
- `DeclareBlockers` (per-pair token)
- All `Resolution*Decision`s except `ResolutionXDecision` with
  X=0 (no-op signal)

**Drop**:

- `PassPriority` — search artifact, especially in dense combat
  phases; conveys zero strategic info.
- Mana-ability `ActivateAbility` events — `effective_land_produces`
  + next state's tap markings already encode this.

**Default `N=32`.** With pass-priority dropped, a typical EoE game
of ~12-14 turns produces ~120-180 strategic actions. N=32 covers
~2-4 full turn cycles — long enough for "opponent had counter mana
open and didn't act" to manifest, short enough that attention cost
stays bounded. Configurable hyperparameter `action_history_n` on
the model class.

### 4. PIMC integration design — slot into BeliefWeightedDeterminizer

Survey result. `--use-belief-weighted` (introduced in Phase 6 of the
ISMCTS migration; see `docs/ISMCTS_MIGRATION.md`) currently:

- Requires `--use-ismcts=True`; `NNPimcConfig.__post_init__`
  (`src/mtg_bot/training/config.py:241`) rejects the combination
  otherwise. PIMC has no shared search state to bias, so
  belief-weighting is ISMCTS-only.
- Constructs `BeliefWeightedDeterminizer`
  (`src/mtg_bot/search/belief.py:110`) and wires it into ISMCTS as
  the `determinize_fn` callback. The determinizer takes
  `m_candidates=64` uniform draws (via `_uniform_determinize`),
  scores each particle by the log-likelihood that the opponent
  would have taken the historical actions under that hidden hand
  (using the **current main NN's policy logits** as the
  opponent-policy oracle), normalizes via log-sum-exp, and
  resamples one particle for ISMCTS to use.
- The prior `P(H)` is the uniform sampler. The likelihood
  `P(a_t | s_t, H)` is the masked-softmax of the NN policy head at
  each reconstructed historical priority moment.
- Conditionally activates after `min_opponent_moments=3` opponent
  priority moments have been observed; before that, falls back to
  uniform.

**Integration point for Step 2 (deck-belief) and Step 4 (hand-belief):**
all substitution happens inside
`BeliefWeightedDeterminizer.__call__`. Specifically:

- **Step 2 (deck-belief)**: replace the `_uniform_determinize`
  candidate-generation step with a deck-belief–weighted sampler.
  The deck-belief model's output is a `(n_printings,)` posterior
  over rest-of-deck; sampling K hidden-info hypotheses from it
  (instead of uniform over the prior deck pool) is the importance-
  sampling substitution. Same `m_candidates`, same downstream
  scoring loop.
- **Step 4 (hand-belief)**: replace the likelihood function. Today
  it calls the main NN's policy head to score "would opponent have
  done a_t under hand H?" The hand-belief head produces
  `P(card_in_hand | trunk_z, deck_belief)` directly — at score
  time, evaluate each candidate hand against this head's output and
  use the resulting log-probabilities in place of the policy-head
  reconstruction. Candidate generation stays whatever Step 2
  picked.

**Not implemented in this slice.** This section locks the integration
point so the deck-belief and hand-belief slices know exactly where
they're inserting. `BeliefWeightedDeterminizer.__init__` will grow
optional `deck_belief_model` and `hand_belief_model` kwargs; absent
them, current behavior is preserved.

### 5. Cache key for the new trunk — reuse canonical_state_key

Today's MCTS NN-eval cache key
(`src/mtg_bot/search/mcts.py:1030 _cache_key`) is
`(canonical_state_key(state), slot_fp)` where `slot_fp` is a tuple
of the viewer's raw `card.id` orderings — a workaround for the
positional_v1 action-encoding slot drift. For canonical_v2
(the version Step 1 will be built against; already pinned in the
Constraints section), the slot_fp tuple is redundant: v2
canonicalizes zone positions before slot assignment, so two states
sharing a `canonical_state_key` also share their slot mappings.

**Decision.** Step 1's cache key is **just**
`canonical_state_key(state)` — the 32-byte
`blake2b(marshal.dumps(canonical_state_tuple))` digest from
`src/mtg_bot/search/canonical_state.py:628`. The slot_fp suffix is
dropped because:

- The trunk's input is per-token from the engine state directly;
  no fixed-shape featurization for `slot_fp` to defend.
- Action encoding is canonical_v2 throughout Step 1 (Constraints
  section locks this in).
- The hash is already content-addressed (cryptographic blake2b),
  bytes-suitable as a `dict` key, stable across canonically-
  equivalent transpositions (the file's docstring contract).

Verified `canonical_state_key` is appropriate for this use:
accepts either an `MtgGameStateAdapter` or a raw `GameState`
(lines 637-644 of the source docstring), returns 32 bytes, and
its hashing rules cover the entire forward-relevant state (zones,
stack, continuous-effects registry, per-player aggregates,
mid-resolution context). The "equivalent states hash equal,
inequivalent states hash differently with cryptographic confidence"
invariant is exactly what the new trunk needs.

### 6. Pooling strategy — learned [CLS] summary token + per-token policy decoding

**Value head**: prepend a learned `[CLS]` token (one trainable
vector, shape `(emb_dim,)`) to the input sequence. Attention layers
let it attend to and pool from every state/action token. The CLS
output position after the trunk is the pooled summary; the value
head is a 2-layer MLP from `emb_dim` → 1 (tanh-activated for
`[−1, +1]`).

Rationale vs. alternatives:

- **Mean-pool**: simple but loses positional weight. A do-or-die
  counterspell on the stack matters more than a back-rank token;
  mean-pool dilutes both equally.
- **Attention-pool with a fixed learned query**: equivalent to CLS
  in expressiveness but adds a separate pooling layer with its own
  attention; CLS reuses the trunk's attention machinery for free.
- **CLS** (chosen): zero extra layers, learns its own attention
  pattern across trunk layers, and is the standard pattern in BERT
  / ViT / AlphaStar — well-understood failure modes.

**Policy head**: NOT a flat MLP from the CLS pool. Instead a
**cross-attention decoder**:

- Construct a fixed `(ACTION_VOCAB_SIZE, emb_dim)` learned
  embedding table — one slot per action-vocab index (517 today).
- Each action-vocab slot's embedding queries the per-token trunk
  output via cross-attention.
- A small MLP turns the attended representation into a single
  logit per slot.
- Output: `(batch, ACTION_VOCAB_SIZE)` logits, ready for the same
  masked log-softmax + cross-entropy loss the current trainer
  uses.

Rationale: the action vocab is positional in the viewer's zones
(LAND_FROM_HAND[pos=2] = "the 3rd hand card"). Letting the slot
embedding attend back to per-token state representations means slot
[LAND_FROM_HAND, pos=2] can directly read the hand[2] token instead
of reconstructing it from the pooled summary. This is the "policy
decoder attends to per-token representations" pattern called out
in the task description; the literature precedent is the Pointer
Network / AlphaStar's auto-regressive action head, simplified to a
single decoding step because the vocab is small.

Aux-head stub (hand-belief, Step 4) follows the same pattern: a
learned `(n_printings, emb_dim)` query table cross-attends to the
trunk and emits per-printing P(in hand) logits.

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
