# Phase 6 snapshot-machinery audit

Pre-flight, research-only audit for Phase 6 of the ISMCTS migration
(belief-weighted determinization via particle filter). Scope: does the
existing replay snapshot system carry enough information to reconstruct
each historic opponent priority moment for the
`P(opponent's observed action | candidate hand)` likelihood, or do we
need to extend the snapshot schema?

**Verdict**: replay snapshots are *very close* — they capture all the
public game state Phase 6 needs to compute features at a historic
priority moment. **One critical gap** and **two notable gaps** must be
filled before the particle-filter pipeline can run end-to-end. The
critical gap is that the replay does not record the actual decision
taken at each priority moment, only the resulting post-state. The two
notable gaps are around lossy serialization of engine bookkeeping that
`evaluate_with_policy` indirectly depends on (legal-action enumeration
needs extra continuous-effects state) and `extract_features`'s use of
layered effective P/T (which the snapshot serializes correctly).

## 1. Snapshot schema today

### Replay file format (`src/mtg_bot/replay.py`)

```
Replay
├── format_version: int (== REPLAY_FORMAT_VERSION = 1)
├── metadata: dict[str, Any]
└── snapshots: list[dict[str, Any]]
```

The `Replay` dataclass is gzipped-JSON serialized. Probed file size: 81
snapshots, ~404 KB JSON / ~5 KB gzipped for an 81-decision random-vs-
random vanilla-creature game.

### Metadata, as written by `_generate_one_game_data`

Confirmed via probe (`scripts/probe_replay_format.py`):

```
game_idx, base_seed, engine_seed, winner,
n_decisions, captured_at, annotated_with_nn_version
```

Notably **absent**: deck identities (`p0_deck`, `p1_deck`), the
sampled deck pool entries, the action sequence (`actions` /
`decision_history`), strategy configs (`p0_config`, `p1_config`), or
any agent-side RNG seed. The `engine_seed` is recorded but not
sufficient to deterministically replay the agents’ choices because the
strategy RNGs are seeded separately from `base_seed + 100*game_idx`.

### Per-snapshot fields (top level)

Confirmed via probe — produced by `serialize_state`
(`src/mtg_bot/serialize.py`) plus `ReplayRecorder` annotators:

| Field | Type | Source |
| --- | --- | --- |
| `turn_number` | int | `state.turn_number` |
| `active_player_idx` | int | `state.active_player_idx` |
| `priority_player_idx` | int | `state.priority_player_idx` |
| `step` | str (e.g. `"upkeep"`, `"declare_attackers"`) | `state.step.value` |
| `void_active` | bool | derived |
| `permanent_left_battlefield_this_turn` | bool | engine flag |
| `spell_warped_this_turn` | bool | engine flag |
| `players` | list[dict] | per player, see below |
| `stack` | list[dict] | per stack item, see below |
| `log` | list[str] | engine log buffer |
| `winner_id` | int \| null | terminal info |
| `is_draw` | bool | terminal info |
| `is_over` | bool | terminal info |
| `heuristic_eval` | `{p0: float, p1: float}` | annotator (always on) |
| `nn_eval` | `{p0, p1, version}` | annotator (only when capture launched with `--annotate-with-nn-version`) |

### Per-player (`players[i]`)

```
id, life, hand_size, hand: list[hand_card],
library_size, graveyard: list[hand_card], graveyard_size,
exile: list[hand_card], exile_size,
has_lost, lost_reason, lands_played_this_turn,
poison_counters, mana_pool: list[{color, spend_restriction}],
battlefield: list[permanent]   (filtered to controller_id == player_id)
```

Hand cards (`serialize_hand_card`) carry: `id`, `name`, `mana_cost`,
`warp_cost`, `type_line`, `power`, `toughness`, `keywords`,
`abilities` (descriptions), `warped`.

Permanents (`serialize_permanent`) carry: `id`, `name`, `type_line`,
`mana_cost`, base + effective P/T, type predicates
(`is_creature`/`is_creature_now`/`is_land`/`is_token`/`is_spacecraft`/
`is_planeswalker`), `is_stationed`, `station_threshold`,
`charge_counters`, `loyalty_counters`, `stun_counters`, `attached_to`,
`keywords`, `abilities`, `static_abilities`, `warp_cost`, `tapped`,
`damage`, `summoning_sick`, `attacking`, `attacking_defender`,
`blocking`, `blocked_by`, `plus_one_counters`.

Stack items: `id`, `name`, `mana_cost`, `controller_id`, `is_ability`,
`ability_description`, `targets`, `x_value`, `kicked`, `countered`.

## 2. Phase 6's reconstruction needs

To compute `P(A_t | H)` at historic priority moment `t`:

1. **Build an `EngineGameState` equivalent to the engine's state at
   moment `t`**, but with the opponent's hand replaced by the
   candidate-hand printings.
2. **Identify the player who held priority at moment `t`** (the
   opponent).
3. **Identify the action `A_t` they took** so we can encode it via
   `action_encoding.encode(decision, state, viewer)` and read off its
   probability from the policy distribution.
4. **Run `NNEvaluator.evaluate_with_policy(state, opponent)`** over the
   reconstructed state. Internally this calls
   `extract_features(state, opponent)` and
   `legal_action_mask(state, opponent)`, both of which need a real
   `EngineGameState` (not a dict).

So the minimum information set is:

- Public-zone contents at moment `t` (battlefield with all per-object
  state, graveyards, exiles, stack with all stack-item state).
- The opponent's hand zone shape (count, ids), to be filled with
  candidate-hand printings.
- The viewer's own hand zone state (preserved unchanged).
- Library zone shapes (counts) — feature vector reads these as sizes
  only, so the actual order is not needed for the policy query but the
  *count* is.
- Mana pools, life totals, poison, lands-played-this-turn, all the
  per-player counters that gate legal actions.
- Phase / step, active player, priority holder, turn number.
- Engine flags that gate legal actions: `void_active` derivative,
  `permanent_left_battlefield_this_turn`, `spell_warped_this_turn`,
  `pending_end_of_combat_sacrifices`, etc. — anything legal-action
  enumeration consults via `legal_actions(state)`.
- The continuous-effects registry plus delayed-trigger queue — anything
  that materially changes the legal-action set or P/T at the moment.
- Identity of the action `A_t` (slot index or full `Decision` object).

## 3. Gaps — what's needed but not currently captured

### CRITICAL: the action taken at each priority moment is not recorded

Each call to `ReplayRecorder.record(state)` runs *after*
`adapter.apply(decision)` (see `data_gen.py:767-769` and
`self_play.py:584-587`). The snapshot is therefore the *post-action*
state. The action itself (`decision`) is discarded immediately and never
written to disk. The `Replay` carries an unbroken sequence of states
but no edges between them.

**Why Phase 6 needs it.** Phase 6's likelihood is
`P(A_t | H, state_t)` — it explicitly needs the action `A_t` to
look its slot up in the NN's policy distribution. Inferring `A_t` from
`state_{t-1} → state_t` is in principle possible (diff zones, look at
what moved, infer what the action must have been) but it is fragile
and ambiguous in many cases — for example a `PassPriority` decision
that triggered an empty-stack auto-resolution leaves a multi-step diff
that mixes the priority pass with the engine's resulting cleanup; a
`DeclareAttackers` decision encodes which creatures were declared via
`AttackerDecision(attacker_id=…, attack=True)` per-creature, but the
post-state only shows the union of attackers; an `ActivateAbility`
might leave no zone change at all (mana-ability tap that's then
consumed before the next snapshot).

**What to add.** A single field per snapshot:

```python
# In ReplayRecorder.record(state, decision=None):
snap["decision"] = encode_decision_for_replay(decision, state, …)
# e.g. {"kind": "CastSpell", "card_id": 56, "viewer": 1, "extras": {…}}
```

The cleanest representation is to store the `Decision` repr in a
JSON-serializable form *together with the slot index it would encode
to* (so consumers don't have to re-encode at read time and risk a
positional-encoding mismatch if zones reorder). Slot index is the
likelihood lookup key; the `Decision` repr is for debugging /
fallback.

**Cost to add.** Trivial in terms of serialization. The two recorder
call sites already have `decision` in scope right before the
`adapter.apply(decision)` line — just thread it into `record()`. The
representation work is the only nontrivial part: `Decision` is a small
sum type (`PlayLand`, `CastSpell`, `ActivateAbility`,
`PassPriority`, `AttackerDecision`, `BlockerDecision`, plus the
resolution-pause decisions). Each is a frozen dataclass and a
to-dict / from-dict pair is mechanical. Bump `REPLAY_FORMAT_VERSION` to
2 and gate the read path so v1 replays load with `decision=None`
(and the audit-time fallback is "skip Phase 6 likelihood for unlabeled
priority moments").

**Locality.** Lives in `src/mtg_bot/training/replay_capture.py`
(`ReplayRecorder.record`) plus a new `decision_to_dict` helper next to
`serialize_state` — or, more naturally, in `actions.py`, alongside the
`Decision` types themselves. Both call sites in `data_gen.py` and
`self_play.py` get a one-line edit.

### NOTABLE: `continuous_effects` and `delayed_triggers` are not in the snapshot

`serialize_state` reads only the per-object effective fields
(`effective_power`, `effective_toughness`, `effective_keywords`) and
not the continuous-effects registry that produced them. It also never
serializes `state.delayed_triggers`, `state.once_per_turn_fired`,
`state.pending_end_of_combat_sacrifices`,
`state.players_who_created_tokens_this_turn`, the resolving-context
mirrors (`resolving_*`), or the layered-cache version.

**Why Phase 6 needs (some of) this.** `evaluate_with_policy` calls
`legal_action_mask` which calls `legal_actions` (`mtg_bot/legal.py`)
which can consult several of these lists — e.g. delayed triggers can
fire as turn-based actions on a future end step but legal-action
enumeration is read at a priority moment and won't see them; static
abilities granted by `continuous_effects` *are* picked up because
`effective_keywords` is a layered walk over the live registry.
However, *reconstructing* the registry from the post-effect P/T and
keywords on each permanent is impossible — and `extract_features`
queries `effective_*` on the live state, so without the registry the
features will be wrong on positions where layered effects matter
(anthems, manlands animated, control-swap auras).

**The snapshot does serialize** the *outputs* of layer walks
(`effective_power`, `effective_toughness`, `keywords` from
`effective_keywords`, `is_creature_now`) — so a *displayer* like the
replay viewer doesn't need the registry. But Phase 6 needs the
*inputs* so it can call `extract_features` / `legal_actions` on a
reconstructed state and get the same outputs.

**What to add.** Either (a) serialize the `continuous_effects` list and
the auxiliary `delayed_triggers` / `once_per_turn_fired` / etc.
fields, OR (b) keep the snapshot lossy as it is today (it's documented
as such in `replay.py:9-13`) and have Phase 6 use a *different*
priority-moment record that retains an `EngineGameState.clone()`
in-memory across the played-game-so-far. Option (b) is cheaper and
cleaner: Phase 6's reconstruction only happens during a search call,
during which the engine is live; the on-disk replay file format is for
human-driven scrubbing and doesn't need to grow. The migration plan
(`docs/ISMCTS_MIGRATION.md` lines 281-287) already says "the replay
machinery already records priority moments" — but reading the actual
code, the replay-capture path only runs when `replay_config` is set
*for data-gen output*, and it serializes through `serialize_state`'s
lossy schema. Phase 6's "priority-moment snapshot" should be a
separate in-memory `list[GameState]` (clone-per-priority-moment) held
by the search loop, *not* a reload of `Replay.snapshots`.

**Cost to add.** Nontrivial if we go with (a) — `ContinuousEffect`
is a frozen dataclass but its fields include callable predicates and
effect handlers, which won't JSON-serialize. The codebase has no
`from_dict` ↔ `to_dict` for these and adding them touches every
effect class. Option (b) is essentially free: hold cloned engine
states in memory across the played-game-so-far, drop them at end of
game.

**Recommendation: pick option (b).** The replay file's lossy
serialization is fit-for-purpose (scrubbing and eval-anomaly
inspection) and shouldn't be inflated to carry full engine state.
Phase 6 lives in `mtg_bot/search/belief.py` and the priority-moment
record lives in the search-call call frame (or a search-side
`PriorityMomentLog` that wraps a `list[GameState]`). This also
sidesteps the JSON-encoding problem for `ContinuousEffect`.

### NOTABLE: deck identities and strategy configs are not in `Replay.metadata`

The metadata stamped at save time only carries `game_idx`,
`base_seed`, `engine_seed`, `winner`, `n_decisions`, `captured_at`,
and `annotated_with_nn_version`. It does **not** carry the seat decks
(printings drawn from `_sample_decks_for_game`), nor the strategy
configs (`p0_config`, `p1_config`).

**Why Phase 6 needs this.** Phase 6 samples candidate hands from "the
deck-list-consistent unknown pool" — meaning the determinizer needs
the opponent's deck list to know what printings are still possible.
Live games access the deck list through `state.players[i].library`
(plus moved-out-of-library zones); historic *replay* analysis would
need to reach back to the original deck list to seed the sampler.

This gap matters less than the action gap because Phase 6 will run
*during a search call mid-game*, not on a finished replay file — so
the deck list is in the live state's library zone, no replay
introspection needed. The replay-file metadata gap only matters if we
later want to *post-hoc* analyze likelihoods in a saved replay viewer
("show me the candidate-hand reweighting at this moment"). That's an
optional UI feature, not a Phase 6 blocker.

**Cost to add.** Small. `_generate_one_game_data` has `deck_p0` and
`deck_p1` in scope at line 463-465; just add them to the metadata
dict at line 549-558. Caveat: `Deck.to_dict` may need to inline
the resolved printings, not just card names, if printing identity is
load-bearing for sampling.

## 4. Recommended changes

The minimal patch to unblock Phase 6 implementation:

1. **Record the decision in each replay snapshot** (the critical
   gap). `ReplayRecorder.record(state, decision)` — one new arg, two
   call sites updated, plus a `decision_to_dict` helper in
   `actions.py`. Bump `REPLAY_FORMAT_VERSION` to 2; v1 replays load
   with `decision=None` per snapshot. Phase 6 can then either consume
   recorded snapshots (file-driven) or — preferably — its own
   in-memory priority-moment log. Even if Phase 6 ends up using
   option (b) below, this addition is cheap and unblocks any future
   replay-driven analysis.
2. **Use option (b) for the per-moment engine-state record.** Phase 6
   maintains its own in-memory `list[EngineGameState.clone()]` across
   the played-game-so-far (one per opponent priority moment, plus the
   action that was taken at each). This sits in `belief.py` or a small
   new module `search/priority_moment_log.py`. It is *not* serialized
   to disk and does *not* go through `serialize_state`. Cost: one
   `state.clone()` per opponent priority moment per game (cheap;
   `clone()` is benchmarked in `scripts/bench_clone.py` and is a few
   hundred microseconds).
3. **Add `p0_deck` / `p1_deck` to replay metadata** (notable, but
   strictly optional for Phase 6). One-line edit in
   `_generate_one_game_data` and `self_play._generate_one_eval_game`.
   Worth doing for general replay-analysis hygiene even if Phase 6
   doesn't strictly need it.

Concrete patch sketch (do not apply — just to bound the work):

```python
# src/mtg_bot/training/replay_capture.py (≈10 lines)
def record(self, state, decision=None):
    snap = serialize_state(state)
    if decision is not None:
        snap["decision"] = decision_to_dict(decision)
    for annotator in self.annotators: ...

# src/mtg_bot/training/data_gen.py (1 line per call site, ×2)
adapter.apply(decision)
if replay_recorder is not None:
    replay_recorder.record(adapter.engine_state, decision=decision)

# src/mtg_bot/actions.py (≈40 lines)
def decision_to_dict(d): ...
def decision_from_dict(d): ...

# src/mtg_bot/replay.py (1 line)
REPLAY_FORMAT_VERSION = 2
# + a v1→v2 reader path that injects decision=None
```

Total estimated effort: 2-3 hours for the recorder change + tests.
Phase 6's own in-memory priority-moment log is part of Phase 6
implementation itself, not the audit's recommended pre-work.

## 5. Open questions

These are things the audit found that warrant a human review before
Phase 6 implementation begins.

1. **Is the replay file actually the intended Phase-6 reference, or is
   it just a coincidence of vocabulary?** The migration plan
   (`ISMCTS_MIGRATION.md` 281-287) says "replay machinery already
   records priority moments." Reading the code, the replay machinery's
   serialization is documented as lossy and deliberately doesn't carry
   resumable engine state (`replay.py:9-13`: "you can SCRUB through a
   replay, you can't run new MCTS searches from it"). I read the
   "priority-moment snapshot" reference as colloquial — it really
   means "the engine already knows where priority moments are; record
   one full state per such moment in memory" — not "load Phase 6's
   inputs from a `.json.gz` replay file." Confirm.

2. **Determinizer reuse on the historic state.** Phase 6 iterates
   "for each step in *A* where the opponent had priority, reconstruct
   the engine state with hand *H*, query NN policy." `H` is sampled
   from the *current* root's hidden pool. The played-game-so-far may
   have moved some of the candidate-hand cards through public zones
   already (cast, discarded, exiled). Does the candidate hand need to
   be *time-rewound* to be consistent with the historic moment, or do
   we sample once at the root and project that hand back through every
   prior moment? The literature is not opinionated; the migration plan
   doesn't say. This affects the priority-moment-log API.

3. **Resolution-pause priority moments.** When a spell pauses for a
   target / discard / X choice, the adapter exposes that as a
   "decision" with the same `apply` interface. Are these counted as
   opponent priority moments for Phase 6 likelihood? The taking
   player has priority for the *cast* at the outer level, but the
   resolution callback is asking for sub-decisions. The NN policy head
   today is trained over the same `ACTION_VOCAB_SIZE` space — but
   resolution decisions are a separate vocab in
   `resolution_decisions.py`, not the 517-slot priority-action vocab.
   Phase 6 can probably skip resolution-pause moments for a v1
   (likelihood = uniform over those steps), but confirm with the
   author of the migration plan.

4. **Recorded post-state vs queried pre-state.** The current snapshot
   is taken *after* `apply(decision)`. Phase 6's likelihood is
   `P(decision | pre-state)`. To match, either Phase 6 reads the
   *previous* snapshot to reconstruct the pre-state (then the recorded
   `decision` says what was taken from there), or the recorder adds a
   pre-state snapshot too. The first is simpler and keeps the snapshot
   list size unchanged. Confirm this is the intended convention before
   wiring.

5. **Snapshot count on the 0th frame.** The recorder captures an
   initial state before any action ("game 0, before any actions
   taken" — `data_gen.py:507-508`). After a 80-decision game the
   replay holds 81 snapshots (probed: confirmed). Phase 6 needs to
   pair `(snapshot[i], decision_at_i)` → `snapshot[i+1]`; with
   decisions added, the 0th snapshot has no decision, the last
   snapshot has no successor. Both edges look right. Just flag that
   the indexing has an off-by-one waiting to happen if the recorder
   ever changes its initial-state convention.

## Appendix A: file pointers

- Replay format: `src/mtg_bot/replay.py` (88 lines)
- Recorder: `src/mtg_bot/training/replay_capture.py` (169 lines)
- Snapshot serializer: `src/mtg_bot/serialize.py` (188 lines)
- Capture call sites:
  - `src/mtg_bot/training/data_gen.py:503-559` (recorder build, init
    snapshot, post-apply record at line 769, replay write at 549-559).
  - `src/mtg_bot/training/self_play.py:454-510, 586-587` (eval-side
    capture loop with the same shape).
- Engine state: `src/mtg_bot/game.py:2493+` (`GameState`).
- NN policy entry point:
  `src/mtg_bot/search/nn_evaluator.py:338`
  (`evaluate_with_policy(state, player_id) → (value, policy)`).
- Action codec:
  `src/mtg_bot/training/action_encoding.py:387` (`encode`),
  `:618` (`decode`),
  `:877` (`legal_action_mask`).
- Determinizer: `src/mtg_bot/search/determinize.py` (Phase 6's prior /
  proposal sampler).
- Migration plan: `docs/ISMCTS_MIGRATION.md` (Phase 6 = lines 206-326).
- Probe script (audit-time only, not committed as production code):
  `scripts/probe_replay_format.py` — generates one captured replay
  and dumps its on-disk schema for cross-checking against the code
  reading.

## Appendix B: probed example

Confirmed via `scripts/probe_replay_format.py` against a freshly
generated replay (random-vs-random, synthetic G/R decks, base_seed=42,
80-decision cap, no NN annotation).

```
=== Replay path: probe_seed42_idx0000.json.gz ===
format_version: 1
metadata keys: ['annotated_with_nn_version', 'base_seed', 'captured_at',
                 'engine_seed', 'game_idx', 'n_decisions', 'winner']
n_snapshots: 81

=== Top-level snapshot[0] keys ===
  active_player_idx, heuristic_eval, is_draw, is_over, log,
  permanent_left_battlefield_this_turn, players, priority_player_idx,
  spell_warped_this_turn, stack, step, turn_number, void_active,
  winner_id

=== players[0] keys ===
  battlefield, exile, exile_size, graveyard, graveyard_size,
  hand, hand_size, has_lost, id, lands_played_this_turn,
  library_size, life, lost_reason, mana_pool, poison_counters

=== Phase 6 absence checks ===
  [ABSENT] snapshot has 'decision' (action taken)         ← critical gap
  [ABSENT] snapshot has 'continuous_effects'              ← option-(b) skips this
  [ABSENT] snapshot has 'delayed_triggers'                ← option-(b) skips this
  [ABSENT] snapshot has 'next_object_id'                  ← option-(b) skips this
  [ABSENT] snapshot has 'rng_state'                       ← option-(b) skips this
  [ABSENT] metadata has 'p0_deck' / 'p1_deck'             ← optional cleanup
```

Sizes: 4,780 bytes gzipped, 403,918 bytes JSON, 81 snapshots.
