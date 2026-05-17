# Search and engine limitations / known correctness gaps

This document tracks places where our search or engine deliberately
diverges from optimal play or strict CR conformance, with the
rationale, the failure mode, and the conditions under which it would
matter.

These are NOT bugs to fix on a deadline — they're tracked here so
they don't get rediscovered every few months as "wait, that's broken"
and so we have a clear record of WHY each shortcut was taken.

---

## Headline counts (refreshed 2026-05-15, main `c62935d2`)

- **Active entries:** 27 (1-14 numbered + 13 unnumbered Rust-port /
  combat / Python-Scry entries below). Entries #15 and #16 are now
  CLOSED — #15's supertypes-proxy half closed by round 37
  (`feature/rust-search-basic-land-tapped-supertypes-migration`);
  #16's xorshift64-only-shuffle half closed by
  `feature/effect-rng-threading`.
- **Round-34 audit cycle (2026-05-15):** every entry below was
  spot-checked against `rust/src/cards.rs::Effect` /
  `rust/src/state_ops_resolve.rs` / the cross-engine bridge on main
  `c62935d2` to confirm the divergence still applies.
  - Entry #15 (SearchLibraryForBasicLandTapped supertypes-proxy):
    **CLOSED (round 37).** Round-30 supertypes substrate landed in
    `rust/src/cards.rs:3278` (`feature/rust-supertypes-registry`
    merge `ef8fa004`); the consumer-side migration on the
    `Effect::SearchLibraryForBasicLandTapped` arm in
    `state_ops_resolve.rs:2378` shipped in round 37
    (`feature/rust-search-basic-land-tapped-supertypes-migration`)
    — predicate now reads
    `card_types Land AND supertypes Basic`, bit-equivalent to
    Python's `is_basic_land`. The cross-engine bridge in
    `parity/cross_engine.py::build_rust_state` now stamps the
    `("Basic",)` supertype on Land CardDefs that omit it, mirroring
    the Python builder's existing heuristic — so the predicate's
    extra rigor doesn't break parity probes. See entry-level update
    below.
  - All other entries: divergence pin tests still passing on main
    (each entry's "Pinned by:" reference verified live); the
    documented gap still exists in the cited code.
- **Sibling tracking:** `docs/EOE_PROBE_READINESS_AUDIT.md` rounds
  30-35 closed 7 BLOCKED-RUST-EFFECT entries on the EoE pool
  (stun-counter, double-power, damage-by-artifact-count,
  counters-per-other-permanent, surveil-X-by-artifact-count,
  damage-by-cards-in-hand). None of those substrates introduced new
  SEARCH_LIMITATIONS entries — the round-32+ dynamic-X family ships
  full CR-compliant semantics on both engines, so no deliberate
  divergence to track.

---

## 1. Combat damage assignment is ordered (outdated CR)

**Location**: `src/mtg_bot/combat.py:_resolve_damage_step` (around line 419).

**What we do today**: when an attacker is blocked by multiple blockers,
the engine assigns damage in `attacker.blocked_by` iteration order,
applying lethal-before-next-blocker for all but the last blocker.
The last blocker absorbs all remaining damage (or it goes to the
player if the attacker has trample).

**Why this is wrong under current CR**: modern MTG rules let the
attacking player assign damage across blockers however they want —
no required order, no "must assign lethal before next." The attacker
can split a 5/5's damage as 1+1+3 across three blockers if they
choose.

**Failure mode**: the bot may "trade" creatures suboptimally. A 5/5
attacker into three 2/2 blockers should be able to deal 2+2+1 to kill
two and leave one wounded. Our engine forces 2+3+0 (kill first, dump
rest into second).

**When it matters**: rarely in early-training — neither side is
playing well enough for damage assignment subtlety to matter.
Increasingly important once the model is strong and combat is the
deciding factor in close games.

**Fix scope when prioritized**:
- Replace the in-order assignment with a damage-distribution
  decision per multi-blocker attacker
- Factored search-side decision: per attacker with N blockers,
  expose N-1 "how much to N-th blocker" decisions (the last one is
  forced — assign whatever's left)
- Engine `_resolve_damage_step` honors the assignment instead of
  computing it
- Tests pinning: assigning 1/1/3 across three blockers vs default
  2/3/0; trample interaction; deathtouch (1-damage-counts-as-lethal)
  interaction

**Impact estimate**: ~5-10% strength gain in mid/late training.
Negligible during early training.

---

## 2. Combat blocker assignment is factored (joint-pattern coverage)

**Location**: `src/mtg_bot/search/combat_decisions.py`,
`src/mtg_bot/search/engine_adapter.py` (`expose_combat_decisions=True`).

**What we do today**: declare-blockers is decomposed per-blocker.
Each blocker chooses independently from `[block attacker A, block
attacker B, ..., don't block]`. Search sees a depth-M tree of width
N+1, NOT a single 1296-way decision.

**Why this is sometimes wrong**: per-blocker decisions break the
coupling between blockers. "Block attacker A with blockers B and C
together to safely trade" requires search to discover the joint
pattern through MCTS visits. With a small iteration budget, the
search can prefer locally-good but jointly-bad blocking patterns.

**Failure mode**: example — opp attacks with a 5/5; defender has two
2/3 blockers. Optimal play: chump-block with one (cheaper trade),
take 5 damage to face. Sub-optimal jointly-correct: double-block
with both (use both blockers, kill the 5/5, lose both blockers).
Factored search may pick the joint-bad pattern that splits the
difference (one blocker blocks, other passes — same as chump but
explored sub-optimally because UCB1 picks each independently).

**Mitigation in place**:
- Tree-reuse across choose() calls (commit `5f1a202`) keeps
  block-assignment subtrees warm across decisions
- PUCT prior from the trained policy biases toward typical good
  joint patterns once the model has learned them
- Forced-move shortcut handles trivial cases (only one blocker)

**When it matters**: at very tight per-choose budgets (e.g., samples=1
nodes=50). At our production budget (samples=4 nodes=200 = 800 iters)
combined with PUCT prior, the factored search reaches reasonable
coverage. As model trains, the prior compensates for factoring loss.

**Fix scope if needed**: introduce a "block group" decision type
that lets search bind multiple blockers at once. Big refactor; not
worth it now.

**Impact estimate**: probably <5% strength gain even in late training.
Below the noise floor against the ordered-damage-assignment fix.

---

## 3. Priority auto-pass via capability hash (opp + active player)

**Location**: `MtgGameStateAdapter.legal_decisions` short-circuits to
`[PassPriority()]` when the priority holder's capability set is empty.
Capability checks live in `src/mtg_bot/search/_player_capabilities.py`
(`has_player_capability_to_act` + `player_capability_hash`); the
adapter cache lives at `src/mtg_bot/search/engine_adapter.py:208-228`
(`_opp_cap_cache` 4-tuple keyed on `(player_id, is_active_player,
hash, can_act)`).

Two flavors:

- **Opp side** (priority on the non-active player): instant-speed-only
  capability check — cards in hand castable at instant speed,
  warp-from-graveyard / impulse-from-exile at instant speed.
- **Active side** (priority on the active player): instant-speed
  union plus, when at sorcery-window timing (stack empty + main
  phase + active priority), sorcery-speed castables, land plays with
  drops remaining, sorcery-speed warp / impulse / Lightstall casts,
  activated abilities (sorcery-speed), and spacecraft station crew.
  At pre-combat / declare-attackers steps, eligible-attacker
  presence is a capability too (defensive — the engine_adapter's
  factored combat phase already handles attackers ahead of priority,
  but a future code path that opens a priority window before
  `_combat_phase` is set won't silently auto-pass through what
  should be an attacker declaration).

The capability check is computed once per priority moment and
re-validated by hashing
`(player.hand, player.mana_available,
player.untapped_permanents_with_abilities, gy_flags, exile_flags,
step/turn/stack/priority/active/continuous_effects_count)` plus, for
active player, `(lands_played_this_turn, is_sorcery_window, life)`.
Cache invalidated on every `apply()`.

**Why this is sometimes wrong**: the hash inputs don't capture every
state change that could affect the priority holder's possible
actions. The same documented limitations apply equally to opp and
active-player capability checks (the same hash machinery feeds
both):

| Edge case | Why missed | Bot misbehavior |
|---|---|---|
| Continuous effect grants the priority holder new instant-speed access (Vedalken Orrery, Teferi Mage of Zhalfir grants them flash) | Hash doesn't depend on continuous-effects layer beyond the count | Bot auto-passes when the priority holder could have cast a (now-flash) creature |
| Cost-reduction effect lands mid-turn (Goblin Electromancer ETBs from active player's spell → opp's / active's instants get cheaper) | Hash uses raw mana_available, not effective costs | Bot auto-passes when the priority holder could afford something whose cost just got reduced |
| Continuous effect grants a permanent a new activated ability (rare) | Hash captures id-set count delta, not effective set | Bot auto-passes when the priority holder could activate the granted ability |
| Effect makes spells castable from a new zone (Yawgmoth's Will → graveyard cast; very rare in current pool) | Zone-castable flags watched at coarse granularity | Bot auto-passes when the priority holder could cast from graveyard |
| Mana-cost change via card-type change (e.g., color-changing effect altering hybrid cost availability) | Hash uses face-value cost, not derived | Bot auto-passes if a now-castable cost wasn't recognized |

**Failure mode**: bot passes priority when the priority holder had a
meaningful action available. Note this is conservative-WRONG — the
bot's miss is "didn't take a chance to act" — never "took an illegal
action" or "made an impossible play."

**Engine-contract interaction**: today's `legal_actions` enumerator
returns early at non-sorcery timing BEFORE walking the activated-
ability block (see `legal.py` — `if not _is_sorcery_timing: return
actions` after the hand-cast loop). This means BOTH opp at non-active
priority AND active player during instant-only windows (combat
substeps, upkeep/draw/end with non-empty stack, etc.) never receive
`ActivateAbility` actions from the engine. The capability check
matches that contract: at non-sorcery timing,
`_has_instant_speed_activatable` returns False unconditionally. If
a future engine change DOES start surfacing `ActivateAbility` at
non-sorcery timing, the capability-check function is the place to
extend (the structural hash already covers permanent shape).

**When it matters**: very rare in the current EoE pool + synthetic
G/R deck. Common enough in formats with lots of cost-reduction or
flash-granting effects (Modern, Legacy, Commander) that this would
need to be tightened up before the bot enters those formats.

**Mitigation**: the hash is conservative — it includes more state
than strictly needed. False negatives (capability claimed empty
when it isn't) are the dangerous case; false positives (hash says
"changed" when capability actually didn't) just trigger an
unnecessary recompute. We err toward the latter.

**Acceptable for**: training (bot sees millions of games; rare
mis-plays don't shift the policy gradient).

**NOT acceptable for**: tournament play, real-money matches, "bot
plays one game live" scenarios where every decision matters.

**Fix scope if/when needed**:
- Include continuous-effect "grants the priority holder instant-speed" predicates in the hash
- Track effective costs (cost-reduction-aware mana check) instead of raw mana
- Specifically scan for `ContinuousEffect` types known to affect action availability
- Add a config flag `--no-capability-autopass` for matches where strict play matters

**Impact estimate**: combined opp + active auto-pass currently fires
on **~84% of priority moments** in random-walk RandomAgent self-play
(seed 0, 500 decisions; opp-only was ~45%). Per-game self-play
profile (v12 weights, samples=4 inner_nodes=200, ISMCTS, base_seed=200,
decision_cap=200): clean wall **52.2s → 48.8s (-6.5%)**;
`legal_actions` calls **433,526 → 156,337 (-64%)** on top of the
opp-only baseline. Strength cost in mis-played positions: negligible
at current model strength + EoE-only pool. See
`docs/perf_active_autopass_20260504.md` for the full delta.

---

---

## 4. Floating mana not modeled — no standalone tap-for-mana action

**Location**: `src/mtg_bot/actions.py` (action class registry), `src/mtg_bot/legal.py` (action enumeration). There is no `TapLandForMana` action class. Mana production happens only inside `_pay_mana_cost` during spell/ability cost payment.

**What we do today**: when the player needs to pay a mana cost, the engine auto-taps untapped lands (and consumes floating mana if any from continuous-effect sources) IN ONE ATOMIC OPERATION. Mana enters and leaves the pool inside the cost-payment step. The player never sees "mana is in pool, decide what to do next."

**Why this is wrong under CR**: real MTG lets a player activate a mana ability at any priority moment, generating mana into their mana pool. The mana persists until end of phase/step. Players can stack up mana from multiple sources, then spend it on a single spell or ability.

**Failure mode**: examples where this matters —
- **X-cost spells**: in real MTG, a player can tap several lands first (floating the mana) and THEN cast Fireball X=5. Our engine bundles tap-for-mana INTO the X-cost cast, which is fine in simple cases but breaks when X is supposed to be chosen based on available mana.
- **Cards counting mana spent**: e.g., "spells you cast cost {1} less if you spent {U} this turn" / Storm-style cards that count spells with mana. Mana spent this phase isn't tracked because mana never persists.
- **Mana ability with sacrifice cost** (e.g., "Sacrifice this artifact: Add {3}"): in real MTG you'd activate it, the artifact is gone, then later cast something with the floating {3}. Our engine doesn't expose the option.
- **Mana doublers not interacting correctly**: a player who wants to "tap, double, accumulate, cast big" can't. (Some doublers DO work since they trigger in the cost-payment burst.)
- **Bouncing-and-replaying lands for mana**: niche, doesn't work without floating.

**When it matters**: rare in current EoE pool (no Storm cards, no mana doublers, X-cost spells are simple). Will matter much more in formats with mana acceleration archetypes (Modern, Legacy, Commander).

**Mitigation**: none currently — this is a wholesale "feature not implemented" situation, not a workaround.

**Fix scope**: substantial.
- Add `TapLandForMana` and `ActivateManaAbility` action classes (no stack — mana abilities don't go on the stack per CR 605)
- Track `mana_pool` already exists on Player; just need pool-add semantics + emptying at end of phase/step (CR 106.4)
- `_pay_mana_cost` would consume from pool first before tapping
- `legal_actions` enumerates tap-for-mana actions when pool isn't full or when conserving lands isn't the obvious choice (heuristic to prune the otherwise-large branching factor)
- Tests: X-cost casting from floating mana, mana doubler interactions, mana persistence to end of phase

**Impact estimate**: <1% strength gain in current EoE pool. Substantially more in formats where it matters.

---

## 5. Resolution decisions are NOT exposed in production training (vocab gap)

**Location**: `src/mtg_bot/training/data_gen.py:503` and `src/mtg_bot/training/self_play.py:438` construct `MtgGameStateAdapter(engine, expose_combat_decisions=True)` with the implicit `expose_resolution_decisions=False` default. Production data-gen and self-play therefore route every mid-resolution callback (target picks, sacrifice choice, X-cost, modes, "may" yes/no, surveil keep/mill, directed discard, devour land subset, etc.) through `DefaultTacticalAgent` (`src/mtg_bot/search/tactical.py`).

**What we do today**: at any mid-resolution decision point, the engine asks the controlling player's installed agent — which the adapter has rewritten to `DefaultTacticalAgent`. Defaults: `choose_target → first legal`, `choose_sacrifice → first legal`, `choose_x → upper_bound` (commit-everything), `choose_mode → 0`, `choose_modes → [0]`, `choose_yes_no → True` (opts into ALL "may" effects), `choose_surveil → False` (always keep), `choose_discard → first legal`, `choose_devour_lands → []`. None of these go through search; none of them get policy supervision.

**Why we can't just flip the flag**: the adapter and search infrastructure for `expose_resolution_decisions=True` are fully implemented (`ResolutionChannelAgent`, the pause / rollback / replay harness, the `Resolution*Decision` types, search-side handling in PIMC and ISMCTS). The dedicated tests in `tests/search/test_resolution_integration.py`, `tests/search/test_pimc.py`, `tests/search/test_info_set.py`, and `tests/search/test_engine_adapter_legal_cache.py` exercise the path with the flag on. **What's missing is the policy-head vocab.** `src/mtg_bot/training/action_encoding.py` has zero slots for any `Resolution*Decision` subclass; `ACTION_VOCAB_SIZE = 517` covers PassPriority, PlayLand, CastSpell, UnlockRoomHalf, ActivateAbility, ActivateStation, TurnFaceUp, AttackerDecision, BlockerDecision and nothing else. `encode(d, state, viewer)` raises `EncodingOverflowError` for every Resolution*Decision; `legal_action_mask` silently drops them.

**Failure mode if the flag were flipped without extending the vocab**:
- `data_gen.py` line ~757 inside `_play_one_game_recording`: `slot = encode(d, engine, active)` raises for every resolution-pause visit; the `except EncodingOverflowError: continue` then silently drops them. At a resolution-pause sample point `counted` ends up at zero and the row falls through to `active_policy = zero_policy / zero_mask`. **Every resolution-pause sample is silent no-op policy supervision** — the row trains nothing. This is exactly the "silent no-op pipelines are pipeline bugs" anti-pattern in `feedback_silent_noop_pipelines.md`.
- `legal_action_mask` at a resolution-pause moment returns all-False (every Resolution*Decision is `EncodingOverflowError`-skipped). NN evaluator's `evaluate_with_policy` defensively returns `np.zeros(vocab_size)` when `mask_np.any() == False` — so the NN delivers ZERO prior at every resolution-pause leaf. PIMC / ISMCTS PUCT then has flat priors over Resolution children; tree search still backs Q-values up, but the network contributes nothing.
- `decode(slot_idx, state, viewer)` cannot return any Resolution*Decision because no slot maps to one. If a search loop ever picked a slot from the policy distribution at a resolution-pause moment (e.g., via fallback or a bug), it would deserialize back to a priority action; the adapter's `_apply_resolution_decision` does `isinstance(decision, expected_type)` and would `TypeError` immediately.

**Strength cost of leaving the flag off (today)**: the NN never gets supervision on target picks / X-values / mode choices / surveil keep-vs-mill / "may" triggers / directed discards / sacrifice picks. These are the highest-leverage tactical choices in MTG and they are all locked at `DefaultTacticalAgent`'s deterministic first-legal / commit-everything / always-yes defaults. The bot picks the wrong target, sacrifices the wrong creature, opts into bad mandatory triggers via `choose_yes_no = True`, and always X=max even when smaller X is correct. Estimated strength cost: substantial — meaningfully larger than any single combat-side limitation in this doc.

**Fix scope when prioritized**:
- Extend `action_encoding.py` to add slot ranges for each `Resolution*Decision` subclass:
  - `RESOLUTION_TARGET[target_kind][target_pos_within_kind]` — needs a stable kind enumeration (battlefield-permanent / hand-card / graveyard-card / player-id / decline) and a per-kind position cap. Battlefield-permanent positions are tricky because they reference both controllers' permanents (can't share `bf_own_pos`).
  - `RESOLUTION_DISCARD[hand_pos]` and `RESOLUTION_SACRIFICE[bf_own_pos]` — both reuse existing positional axes.
  - `RESOLUTION_X[x_value in 0..X_VALUE_CAP]` — needs an X cap (observed: 0-7 in current pool; 16 is generous).
  - `RESOLUTION_MODE[mode_index in 0..MODE_INDEX_CAP]` — modal "choose one" for 1-of-N; cap at 4 (longest current modal is 3 modes).
  - `RESOLUTION_SURVEIL[mill in {True, False}]` — 2 slots.
  - `RESOLUTION_SHOCK_LIFE[pay in {True, False}]` — 2 slots.
  - `RESOLUTION_YES_NO[yes in {True, False}]` — 2 slots.
  - `RESOLUTION_CARD_FROM_LIBRARY[lib_pos]` — needs a library-position cap; tutors typically search the whole library, so the cap is the deck size (60 in standard, can blow out the vocab if naively encoded). Alternative: encode by printing-id within the deck pool's vocabulary. Bigger design call.
  - `RESOLUTION_CARD_FROM_OPPONENT_HAND[opp_hand_pos]` — uses opponent hand position; valid because the caster has revealed the hand at this point.
  - `RESOLUTION_DEVOUR_LANDS[subset_size]` — already V1-collapsed to (empty, full); 2 slots.
- Update `encode` / `decode` / `legal_action_mask` / `_enumerate_legal` to handle the resolution-pause adapter phase (analogous to the existing combat phases — `_combat_phase` already returns kind tags from the adapter; add resolution-kind tags too).
- Update `replay_decisions.py` (which already covers resolution decisions for serialization, no change there).
- The NN architecture: extending `ACTION_VOCAB_SIZE` reshapes the policy head's output `Linear(h_last, ACTION_VOCAB_SIZE)`. **Existing trained weights become unusable** — the policy head will need to be re-initialized for the new slot count and trained from scratch. Value head and feature encoder are unchanged.
- Tests pinning: `test_vocab_size_constant_is_fixed` updates to the new `ACTION_VOCAB_SIZE`. New tests for `encode` / `decode` round-trip at each resolution-pause kind. `legal_action_mask` produces non-empty masks at resolution-pause moments. End-to-end test that `_play_one_game_recording` with `expose_resolution_decisions=True` writes non-zero policy-supervision rows for resolution-decision sample points.
- After all of the above lands, flip the flag in `data_gen.py:503` and `self_play.py:438`.

**Bootstrap concern after the flag flip**: the trained NN policy head will be re-initialized (new vocab size). Iter-1 onward will have to learn target-picking / X-choice / mode-choice from scratch, on top of learning everything else. For the first few iters, search at resolution-pause moments will be effectively flat-prior PUCT — strictly weaker than `DefaultTacticalAgent`'s first-legal heuristic in those few iters. Long-term gain is large; short-term may regress one or two iterations.

**Impact estimate**: large (10s of percentage points strength once trained). The cost of leaving it off scales with how often resolution decisions arise — every burn spell, every modal spell, every X-cost cast, every "may" trigger, every Mind-Rot-style discard. Already significant in the current EoE pool; will only grow as more cards come online.

**Why this is doc'd here instead of a code fix**: the fix is a substantial vocab extension + NN-retrain that warrants its own dedicated PR. This entry exists so the gap is tracked rather than rediscovered. See `feature/expose-resolution-decisions` history (closed without code changes; documentation-only update of this entry) for the audit that produced this writeup.

---

## 6. Phase-based active-player priority prune (training heuristic)

**Location** (planned, in `feature/phase-priority-prune` as of 2026-05-04): `MtgGameStateAdapter.legal_decisions` short-circuits to `[PassPriority()]` when ALL of these hold:
- Active player == priority player == viewer
- Stack is empty
- Current step is one of: **upkeep, draw step, beginning of combat, end step**

The check fires BEFORE the capability hash check (it's cheaper). Capability check still runs for opp priority and for the active player in other phases.

**Why this is sometimes wrong** under CR: real MTG allows casting instants at any priority moment. There ARE legitimate plays in these phases:

| Edge case | Phase | Example | Bot misbehavior |
|---|---|---|---|
| Pump spell before upkeep trigger | Upkeep | "At the start of your upkeep, do X" where X depends on creature P/T | Bot doesn't pump first |
| Mana sink at end of own turn | End step | Floating mana about to disappear; cast instant to use it | Mana wasted (also moot until floating mana modeled — see entry #4) |
| Modal spell missed in main | End step | Forgot to cast a flash creature in main phase; end step is last chance | Bot doesn't cast it |
| Combat trick before declaring attackers | BoC | Pump a creature so it can attack profitably; instant removal on opp blockers; tap opp's blockers | Bot misses these |
| Pre-empting opp's response window | Various | Cast a spell now so opp must respond before their planning starts | Bot doesn't pre-empt |
| Triggers requiring response | Any | "Whenever you cast a spell" triggers timed for these phases | Not fired |

**Failure mode**: bot passes priority and misses a legitimate instant-speed play. Conservative-WRONG (never plays an illegal action; just doesn't take a legal one). The miss happens on the active player's side, where the held-back action would have been their own choice — opp's response windows are unaffected.

**Highest-risk phase**: **beginning of combat**. This is where genuine combat tricks live (pump-then-attack, instant removal of blockers). A trained model would value these. v12 (near-random) doesn't know how to use them anyway.

**When it matters**:
- For training: misses < 0.5% of decisions; all in niche cases the lightly-trained NN couldn't exploit anyway. Bot doesn't learn the niche tactics, but the policy gradient isn't measurably affected.
- For tournament play: real loss. Combat tricks matter. End-step plays matter. Bot gives up clear value here.

**Mitigation**: configurable via the `--no-phase-priority-prune` flag. Default ON for training and self-play data_gen; should be set OFF for tournament/eval matches against real opponents (or against alternate-arch baselines where you want fair search behavior).

**Acceptable for**: training (millions of games; rare miss doesn't shift the gradient).

**NOT acceptable for**: live tournament play, "bot plays one game live" mode, any benchmark whose strength comparison depends on subtle combat or end-step decisions.

**Fix scope if/when needed**: the heuristic is intentionally crude. To recover the missed plays without the runtime cost:
- Train the policy to predict "should this priority moment be skipped?" — let the NN decide rather than a hardcoded phase rule
- Or expose phase + stack-empty as a feature to the policy and let it learn
- Or just disable the heuristic for late-stage training/eval

**Impact estimate**: ~15-30% per-game wall reduction during training, on top of capability auto-pass (entry #3). Composes well — capability catches "no castable spells" case; phase prune catches "have castable spells but wrong phase" case.

---

## 7. Forced second-main land drop (training heuristic)

**Location**: `MtgGameStateAdapter.legal_decisions` (`src/mtg_bot/search/engine_adapter.py`) — see `_should_force_landdrop()`. After the full action enumeration, `PassPriority` is filtered OUT of the returned decisions when ALL of these hold:

- `force_landdrop_enabled` is True (default for SelfPlayJobSpec, OFF for EvalJobSpec)
- Active player == priority player
- Stack is empty
- Step is `POSTCOMBAT_MAIN`
- `lands_played_this_turn == 0`
- ≥1 land in active player's hand
- Active player controls fewer than six lands

The player can still cast spells / activate abilities — but cannot end the priority window without playing a land at some point.

**Why this is sometimes wrong** under CR: real MTG allows the active player to skip their land drop. There ARE legitimate reasons to do so:

| Edge case | Example | Bot misbehavior |
|---|---|---|
| Hold land for opp's land-destruction trigger | Strip Mine in opp hand at sorcery speed next turn; better to deploy after | Bot gives up the land too early |
| Reveal-from-hand trigger that scales with lands in hand | "Whenever an opponent reveals X, do Y" — landfall payoff opposite | Bot loses the trigger value |
| Bottom-of-the-pile color screw | Hand has only off-color land; playing it does nothing useful | Bot wastes a turn on a dead land |
| Mulligan-style overcommit | Hand is 6+ lands and you've capped at 5; another land just floods | Mitigated by the 6-land guard, but 5-land overflow still possible |
| Land-cycling to thin the deck | Cycling a fetchland for tempo when no reasonable play exists | Bot doesn't see the option (cycling not modeled either, see entry #4) |

**Failure mode**: bot is forced to play a land when the optimal play is to hold it. Conservative-WRONG in most cases — playing a land when you have <6 in play is correct ~95% of the time on the EoE card pool, and the heuristic explicitly opts out when you're already flooded. The miss is on niche edge cases that the lightly-trained NN couldn't reason about either.

**Why this isn't pure pruning** (and why it's #7 not #6.5): unlike the phase-prune (which short-circuits BEFORE legal_actions), this filter runs AFTER full enumeration and only removes one option (`PassPriority`). It's a play-quality heuristic disguised as a search filter, not a perf optimization.

**When it matters**:
- For training: bot ALWAYS plays its land at second main when conditions match — removes the "lazy NN holds lands forever" failure mode that early-stage policies fall into. Net positive for training signal quality.
- For tournament play: small loss. The held-land cases above are real but rare; expert-level deck-building works around them. Default OFF for eval to be safe.

**Mitigation**: `force_landdrop_enabled=False` on `MtgGameStateAdapter` (or via SelfPlayJobSpec / EvalJobSpec). EvalJobSpec defaults OFF; SelfPlayJobSpec defaults ON.

**Acceptable for**: self-play training (the policy benefits from never seeing the "hold land for no reason" trajectory).

**NOT acceptable for**: tournament play, eval matches against real opponents, any test where land-timing optimality matters.

**Fix scope if/when needed**: trivial to disable per-spec. To replace with something better, add a "should I play this land?" feature to the policy network and let the NN decide. Same shape of fix as the phase-prune (entry #6).

**Impact estimate**: not a perf win (filter runs AFTER legal_actions, no work skipped). The win is play-quality: trained models from runs WITH the filter ON should hit "land every turn through ~5 lands" reliably, which is a learnable pattern but a slow one without the inductive bias.

---

## 8. Lethal-detect alpha-strike heuristic (training optimization)

**Location**: `src/mtg_bot/search/_lethal_detect.py`,
`MtgGameStateAdapter.legal_decisions` is unaffected — the
short-circuit lives upstream in
`ISMCTS.choose_with_visits` (around line 411 with the
`enable_lethal_detect` constructor flag, default True). When the
adapter is at an `AttackerDecision` priority moment AND
`detect_lethal_attack` returns a non-None lethal subset, the search
loop is skipped and `{decision: 1}` for the matching `AttackerDecision`
is returned.

**What this is**: a HEURISTIC, not a CR-correct optimization. It
is NOT a lossless search shortcut; it's a pattern-matched
short-circuit that fires only when ALL of these hold:

- Single opponent.
- Opp has empty hand (no instants / sorceries to react with).
- Opp has no non-mana activated abilities on any permanent.
- Opp has no triggered abilities keyed on combat events
  (`attacks` / `blocks` / `deals_combat_damage` / `dealt_damage`).
- Opp controls no noncreature permanent with a self-animation
  activated ability (manland-style — `BecomeLandCreatureUEOT` on
  `printing.activated_abilities` of a noncreature permanent).
- None of opp's blockers have first/double strike, indestructible,
  hexproof, or shroud.
- With opp greedily blocking the biggest attackers, the smallest
  unblocked attackers' summed power (minus any lifelink lifegain
  from blockers) clears opp's life total.

When fired, the heuristic emits "attack with all eligible attackers"
since sending fewer can only reduce unblocked damage. The full set
short-circuits ALL per-attacker sub-decisions in the same combat
phase (each sub-decision's `choose_with_visits` call independently
recomputes the heuristic against the same engine state and routes
through it).

**Why this is sometimes wrong**: 

| Edge case | Why missed | Bot misbehavior |
|---|---|---|
| Opp could topdeck a sweeper next turn | We don't see the unrevealed library | Heuristic fires; opp clears the board on their turn — but that doesn't matter because we KILLED them this turn anyway. NOT a misbehavior. |
| Opp has prevent / damage-redirection effects | Continuous-effect detection isn't part of the gates | Bot commits to attacks; combat resolves with prevented damage, opp survives. |
| Opp is a player whose loss condition isn't "life ≤ 0" (poison, milling triggers) | Heuristic only checks `opp.life <= 0` after damage | Bot commits to attacks; opp's actual loss path may not trigger. |
| Damage assignment to multiple blockers wouldn't trade favorably | Heuristic doesn't reason about post-block board state | The bot "wins" but if the kill was actually impossible (e.g., damage prevention, blocker abilities trigger before damage), the bot loses. The CR-correct gates above are designed to rule out these cases — if a gate is missing for a real card, the bot loses the game. |
| First strike on OUR side wasn't checked (CR + factor) | We don't model that strike-step damage helps us; the heuristic counts NORMAL damage step | Conservative — first strike on attackers can ONLY help us (more damage chances), so missing it just means false-negatives (some lethals we don't detect). Safe. |
| Non-life-loss kill conditions (mill / commander / poison) | Not supported | Heuristic always uses life-total; bot relies on search for those win paths. |
| Future self-animation effect class (artifact-animator, copy-of-creature animator, etc.) | Animator gate only checks `isinstance(ability.effect, BecomeLandCreatureUEOT)` — the only self-animation Effect class in the engine today | Bot commits to attacks; opp animates a noncreature artifact / token-source into a fresh blocker, soaks the smallest unblocked attacker, we lose. **When adding a new self-animation Effect class, append it to `_SELF_ANIMATION_EFFECT_CLASSES` in `_lethal_detect.py`.** |

**Failure mode**: bot commits to attack-everything (which is what
the heuristic does today). If the math was wrong and the kill
doesn't actually happen, our creatures are tapped, our turn ends,
opp kills us. **Catastrophic when wrong**, hence the conservative
posture in `_lethal_detect.py` — every gate aborts on any potential
disruption.

**Safety contract**: the gates list here MUST stay in sync with
the implementation. Any new combat-disrupting card mechanic
(damage prevention, redirected damage, "creatures attacking gain
shroud", etc.) needs to either:
1. Be detected by an existing gate (e.g. flagged as a
   non-mana activated ability or combat trigger), OR
2. Add a NEW gate that aborts when the mechanic is present.

**When it matters**:

- **Training**: heuristic fires on guaranteed-lethal turns; bypasses
  the per-turn search budget allowing earlier (uncertain) decisions
  to consume more budget. Per-turn wall savings + cleaner
  end-game training signal (value target = +1.0 with confidence;
  policy target concentrated on the lethal play).
- **Tournament play**: same wins, plus opp's plausible
  response is often already captured by the gates (empty hand
  rules out instants; no combat triggers rules out fog effects).
  Disable via `enable_lethal_detect=False` if you want strict
  search-derived recommendations and full visibility into the
  search policy at end-game positions.

**Mitigation in place**:

- Conservative-ABORT posture: false-positive lethal (declaring win
  when we can't actually win) is catastrophic; false-negative (missing
  real lethal, falling through to search) is just a missed
  optimization. Every gate errs toward false-negative.
- Counter `ISMCTS._lethal_detect_fires` exposes firing rate for
  benchmarking; reset via `reset_lethal_detect_count()`.

**Acceptable for**: training, self-play, casual play.

**Caveats for**: tournament play (still safe correctness-wise; just
hides search-based combat reasoning from the policy).

**Fix scope if/when needed**:
- Extend gates to recognize damage-prevention / redirection effects
  (continuous-effect search at the GameState level).
- Optimize the "send minimal subset" decision so the bot doesn't
  always commit ALL eligible attackers (let some stay back for
  opp's potential counter-attack next turn — but if we detected
  lethal, there IS no next turn for opp; this is a dead optimization).
- Add support for non-life-loss kill conditions
  (poison counters, "lose the game" rider abilities).

**Impact estimate**: minor wall savings per game (depends on
end-game frequency); the bigger win is training-signal quality at
the moment-of-truth turn. Expected per-game wall delta: 1-3% (most
games don't reach an alpha-strike-with-tapped-out-opp position; when
they do, the heuristic wipes 5-15 attacker sub-decisions of search).

---

## 9. Skip-empty-combat priority short-circuit (training heuristic)

**Location**: `MtgGameStateAdapter.legal_decisions` (`src/mtg_bot/search/engine_adapter.py`) — see `_should_skip_empty_combat()`. Returns `[PassPriority()]` immediately (no `legal_actions` enumeration) when ALL of these hold:

- `skip_empty_combat_enabled` is True (default for `SelfPlayJobSpec`, OFF for `EvalJobSpec`)
- Not terminal / not resolution-paused / not in a factored combat sub-decision
- Stack is empty
- Step is one of: `DECLARE_ATTACKERS`, `DECLARE_BLOCKERS`, `COMBAT_DAMAGE`, `END_OF_COMBAT`
- No creature on the battlefield is currently attacking

Fires for **both** active and opponent priority windows: with no attackers there's nothing to pump, redirect, or remove with combat tricks, so opp's instant-speed window is also dead.

**Why this is sometimes wrong** under CR: real MTG allows priority during these windows even with no attacks. Edge cases the heuristic skips:

| Edge case | Step | Bot misbehavior |
|---|---|---|
| Cast non-combat instant during empty combat phase | Any of the 4 | Misses end-of-step effects timed to combat (rare) |
| Counterspell setup for next turn | Any of the 4 | Misses pre-emptive instant timing |
| "At end of combat" triggers fire even with no combat | EoC | The trigger still fires (engine handles), but bot can't respond to it with an instant |
| "Whenever a player passes priority during combat..." trigger | Any of the 4 | Hypothetical card mechanic; would need a new gate |
| Sacrifice for end-of-turn benefit timed at EoC | EoC | Better timed at end step proper anyway, so usually OK |

**Failure mode**: bot passes priority during empty combat steps even when an instant could be cast. Conservative-WRONG (never plays an illegal action; just skips windows where instants are *technically* legal but rarely useful with no attackers).

**Why this composes well with phase-prune** (entry #6): phase-prune already covers `BEGINNING_OF_COMBAT` and `END` steps for active player. This entry covers the OTHER combat sub-steps — and crucially fires for opp priority too (phase-prune is active-only). The capability auto-pass (#3) catches "opp has nothing castable" but doesn't fire when opp has castable instants, which is the case this entry adds.

**When it matters**:

- For training: removes ~10 priority moments per affected combat phase from the search tree. Fires reliably turns 1-2 (no creatures yet) + occasional board-wipe turns. Composes with phase-prune for ~15-20% additional wall reduction estimated.
- For tournament play: marginal correctness loss. Empty-combat-instant plays are rare; expert decks rarely need them. Default OFF for eval.

**Mitigation**: `skip_empty_combat_enabled=False` on `MtgGameStateAdapter` (or via the Spec). `EvalJobSpec` defaults OFF; `SelfPlayJobSpec` defaults ON.

**Acceptable for**: training, self-play data_gen.

**NOT acceptable for**: tournament play, eval matches against real opponents, any test where empty-combat-instant timing matters.

**Fix scope if/when needed**: add gates for triggered abilities that depend on combat steps with no attackers, OR train the policy to skip these windows on its own (same shape of fix as phase-prune).

**Impact estimate**: ~15-20% per-game wall reduction during training (estimated; needs measurement). Composes additively with phase-prune (#6) since it covers the combat sub-steps phase-prune misses.

---

## 10. Skip our priority on opponent's POSTCOMBAT_MAIN (training heuristic)

**Location**: `MtgGameStateAdapter.legal_decisions` (`src/mtg_bot/search/engine_adapter.py`) — see `_should_skip_opp_postcombat_main()`. Returns `[PassPriority()]` immediately when ALL of these hold:

- `skip_opp_postcombat_main_enabled` is True (default for `SelfPlayJobSpec`, OFF for `EvalJobSpec`)
- Not terminal / not resolution-paused / not in a factored combat sub-decision
- Stack is empty
- Step is `POSTCOMBAT_MAIN`
- Player with priority is the **non-active** player (we're being asked to act on opp's turn)

**Why this is sometimes wrong**: real MTG allows priority during opp's main 2 with empty stack. Edge cases the heuristic skips:

| Edge case | Bot misbehavior |
|---|---|
| Counterspell on opp's about-to-be-cast spell next turn | Misses the pre-emptive timing (rare; opp would normally respond at end of turn) |
| Cast a flash creature on opp's end of turn | Better timed AT end step itself (entry #6 phase-prune already auto-passes our active end step, but the natural end-of-opp-turn flash window is at OPP'S end step, not their main 2) |
| Activate a "do X this turn" ability before EoT | Same — usually timed at end step proper |
| Trigger that fires during opp's main 2 | Engine handles trigger firing; we just can't respond with an instant |

**Failure mode**: bot passes priority during opp's main 2 even when an instant could be cast. Conservative-WRONG. The natural reactive timing for our instants on opp's turn is usually:
- BEFORE opp's combat (during their precombat main, where capability auto-pass already fires)
- AT opp's end step (where this heuristic doesn't apply)

So the dead window we're skipping is genuinely a low-value priority moment for our instant-speed plays.

**Why this complements capability auto-pass** (entry #3): capability auto-pass fires for the priority holder when they have nothing castable. This entry catches the remaining case: it IS opp's turn, we DO have a castable instant, but acting at opp's main-2 dead window is essentially never optimal. The capability check would let us through; this rule doesn't.

**When it matters**:

- For training: removes 1-2 priority moments per opp turn (we get priority once during opp's main 2; capability check fires when we can't act, this fires when we can but shouldn't). Estimated 5-6% wall delta.
- For tournament play: marginal correctness loss. Pre-emptive instant timing on opp's main 2 is a niche play. Default OFF for eval.

**Mitigation**: `skip_opp_postcombat_main_enabled=False` on `MtgGameStateAdapter` (or via Spec). `EvalJobSpec` defaults OFF; `SelfPlayJobSpec` defaults ON.

**Acceptable for**: training, self-play data_gen.

**NOT acceptable for**: tournament play, eval matches, any test where pre-emptive instant timing matters.

**Fix scope if/when needed**: trivial to disable per-spec. To recover the lost plays, train the policy to value these windows directly (same shape of fix as the other priority short-circuits).

**Impact estimate**: ~5-6% per-game wall reduction during training. Composes additively with capability auto-pass (#3) since it catches the "have castable but pointless" case capability misses.

---

## 11. Skip-dead-main1 priority short-circuit (training heuristic)

**Location**: `MtgGameStateAdapter.legal_decisions` (`src/mtg_bot/search/engine_adapter.py`) — see `_should_skip_dead_main1()`. Returns `[PassPriority()]` immediately when ALL of these hold:

- `skip_dead_main1_enabled` is True (default for `SelfPlayJobSpec`, OFF for `EvalJobSpec`)
- Not terminal / not resolution-paused / not in a factored combat sub-decision
- Stack is empty
- Step is `PRECOMBAT_MAIN`
- Player with priority IS the active player
- Active player controls 0 creatures on the battlefield
- Active player has no card in hand whose printing has the printed `haste` keyword
- Active player controls no noncreature permanent with an activated ability that animates it (currently checks for `BecomeLandCreatureUEOT`; see fragility note below)

The "no creatures + no haste + no animator" conjunction means nothing the player does at main 1 has a different effect from doing it at main 2 — there's no creature to attack with even if a creature gets cast or animated. Auto-passing main 1 is functionally equivalent to playing through it.

**Why the manland exception**: a creature-land like Mishra's Factory in play means the player CAN attack this turn (animate, then attack). Skipping main 1 in that case loses the chance to play extra lands or cast spells before deciding to animate. The check walks the active player's noncreature permanents looking for an `ActivatedAbility` whose `effect` is `BecomeLandCreatureUEOT`. Mana abilities are skipped (`is_mana_ability == True`).

**Fragility — manland detection is conservative-WRONG**: the `isinstance(ability.effect, BecomeLandCreatureUEOT)` check covers the only self-animation Effect class today, but a future card could introduce a NEW Effect class for artifact-self-animation or other animator patterns. If that lands without updating this check, the heuristic would fire when it shouldn't (false-positive), causing the bot to skip main 1 with an animator available. **Mitigation**: when adding a new self-animation Effect class, add it to the isinstance tuple here (and to the related lethal-detect gate in `_lethal_detect.py`).

**Why this is sometimes wrong** (other than the manland fragility):

| Edge case | Bot misbehavior |
|---|---|
| Cast a land-cycling card or ramp spell at main 1 to enable a turn-2 play | Misses if the card itself has no haste keyword |
| Activate a non-mana ability that needs sorcery timing AND must happen before combat | Edge case; usually a planeswalker activation, none in EoE today |
| Play a turn-1 mana ramp / scry / brainstorm-style effect that wants to happen NOW | Effect still happens at main 2; functional difference is small |
| Cast a sorcery whose effect benefits combat (e.g. tutor for removal) | Tutor at main 1 vs main 2 differs only if the tutored card needs to be cast pre-combat — which our heuristic explicitly rules out (no creatures, no haste) |

**Failure mode**: bot passes priority during dead-main-1 turns even when a sorcery COULD be cast. Conservative-WRONG. The miss is on the rare "I have a sorcery that affects combat OR my opp's combat" case which is genuinely rare on turns where I have 0 creatures and no haste.

**When it matters**:

- For training: removes ~2-4 priority moments per affected turn (active main 1 + opp's response window). Fires reliably turns 1-2 (no creatures yet); rarely after that (once you cast a creature, it sticks). Estimated 2-4% wall delta.
- For tournament play: marginal correctness loss. Default OFF for eval.

**Mitigation**: `skip_dead_main1_enabled=False` on `MtgGameStateAdapter` (or via Spec). `EvalJobSpec` defaults OFF; `SelfPlayJobSpec` defaults ON.

**Acceptable for**: training, self-play data_gen.

**NOT acceptable for**: tournament play, eval matches, scenarios with non-mana sorcery-speed activated abilities that matter pre-combat.

**Fix scope if/when needed**: trivial to disable per-spec. To recover the lost plays, train the policy to value these windows directly. To extend the manland gate to new Effect classes, edit the isinstance tuple in `_should_skip_dead_main1`.

**Impact estimate**: ~2-4% per-game wall reduction during training. Smaller than the others on this branch (only fires on the first 1-2 turns); main value is decision-tree simplification for the early-game policy training signal.

---

## 12. Stop-run sentinel fires at stage boundaries, not mid-game (UI cost-of-control)

**Location**:

- `src/mtg_bot/training/stop_signal.py` (the sentinel-file
  primitives)
- `src/mtg_bot/training/data_gen.py:343` (sentinel poll between
  ``imap_unordered`` results in
  ``generate_training_data_parallel``)
- `src/mtg_bot/training/self_play.py:249` (sentinel poll in
  ``run_match_parallel``'s eval pool)
- `scripts/iterate_alphazero.py` cycle loop (sentinel poll between
  self-play / train / eval stages)
- `scripts/serve_setup_scripts.py:queue_take` (sentinel poll on
  every ``/queue/take`` from a remote)

**What we do today**: when the user clicks the Stop-run button in
the training UI, the back-end writes ``training_progress/.STOP_<id>``.
Producers check for that sentinel at *boundaries* — between
completed-game results in a multiprocessing pool, between
``/queue/take`` requests from a remote, between iter stages
(self-play → train → eval). They do NOT check it inside an
in-flight game's per-decision loop.

**Why we ship this v1 anyway**:
- Mid-game responsiveness would require a per-decision sentinel
  poll inside the search hot-path (PIMC / ISMCTS evaluate
  candidate moves several thousand times per game) and would
  measurably slow self-play. The intended use of Stop is
  abort-and-retry, not pause-mid-decision; a few-minute wait at
  production wall budgets is acceptable.
- In-flight game data is preserved when stops fire at imap-yield
  boundaries (the ``indexed`` list is built incrementally; the
  rows already in it land in the .npz). Mid-game termination
  would lose that game's samples to no purpose.

**Failure mode**: user clicks Stop. The UI ack's immediately and
shows "stop pending…". The producer (multiprocessing pool of
self-play games) finishes the in-flight games on its workers
(could be up to ~2 min at production decision budgets) before its
``imap_unordered`` loop reads the sentinel and breaks. The user
sees "running" for ~minutes after clicking.

**Fix scope when prioritized**:
- *Per-decision sentinel poll* — small code change (add the check
  inside ``MtgGameStateAdapter.legal_decisions`` or the search
  driver's per-iteration loop) but adds an mtime-aware filesystem
  poll to the inner search loop. Mitigatable with caching (only
  re-stat every N decisions / every M ms).
- *HTTP control endpoint* — replace the file sentinel with an
  in-process control channel (queue between UI and producer); is
  more invasive (requires the producer to expose a port, requires
  remotes to call it through Tailscale).

**Impact estimate**: pure cost-of-UX, no strength implications.
For now: stop-click latency = remaining wall time of the longest
in-flight game (= ~30s-2min depending on decision budget).
Acceptable for v1.

---

## 13. Shard script exits via ``os._exit`` (process-cleanup workaround)

**Location**: `scripts/run_self_play_shard.py` — `main()`'s
`finally` block calls `os._exit(exit_code)` after stdio flush.

**What we do today**: the shard script's `main()` is wrapped in
`try / except / finally` such that the LAST thing it does is
`os._exit(exit_code)`. This bypasses Python's normal interpreter
shutdown — no `atexit` handlers, no non-daemon thread joins, no
final GC.

**Why it's the lesser evil**:
`run_shard_pull` / `run_shard_eval_pull` use
`concurrent.futures.ProcessPoolExecutor`. We already replaced the
context-manager exit (`shutdown(wait=True)`) with explicit
`shutdown(wait=False)` (commit `b3ebc39`,
`feature/processpool-shutdown-nowait`) so the executor's cleanup
path doesn't block on hung futures. But Python's at-exit machinery
joins non-daemon threads — and `ProcessPoolExecutor` spawns
internal management threads (`_queue_management_thread` and
friends) that are non-daemon by default and stay alive as long as
any worker process is alive. `shutdown(wait=False)` doesn't kill
those threads; it just doesn't WAIT for them. So `main()` returns,
then Python's normal shutdown blocks forever joining them, while
they're blocked joining still-running C-extension worker code.

By the time we reach the `finally` block, every artifact the
orchestrator depends on is already on disk:
- `.npz` chunks written via `_flush()` inside `run_shard_pull`,
- the per-shard progress JSON via `progress.finalize(...)`,
- the `shard_end` event in `events.jsonl`,
- (eval mode) the per-shard `_result.json` written in
  `run_self_play_shard.py:_run` itself.

The only thing `os._exit` skips is process / thread cleanup — and
the OS reaps the orphan worker processes when the parent dies, so
no resource leaks.

**Failure mode**: any code path that registers an `atexit` handler
expecting it to run on shard exit will silently NOT run. If you
need teardown work, do it explicitly before `_run` returns, not
via `atexit.register`. (Today, nothing in the import graph of
`run_self_play_shard.py` registers a teardown that matters; the
worry is hypothetical / future.)

Concrete repro of the underlying hang (2026-05-05): a Mac shard's
`run_self_play_shard.py` process stayed alive 50+ min after
self-play completed; master's SSH session never saw EOF, so the
orchestrator never proceeded to rsync-back. Required manual
`kill` of the remote Python.

**Fix scope when prioritized** (proper fix that doesn't need
`os._exit`): medium — at least ~50 lines across `run_shard_pull` +
`run_shard_eval_pull`. Either:
- Replace `concurrent.futures.ProcessPoolExecutor` with
  `multiprocessing.Pool` (whose `terminate()` actually kills
  workers — same pattern `bench_per_game_wall.py` already uses),
  or
- Subclass `ProcessPoolExecutor` and override `_queue_management_
  thread` creation to mark it daemon (relies on private API; could
  break across Python versions).

The second is fragile; the first is the recommended direction
when someone has time.

**Impact estimate**: removes the orchestrator hang entirely
(was: per-iteration risk of master SSH session hanging until
manual kill, blocking the entire iteration sweep). No strength
implications, no perf cost on the happy path.

---

## 14. Proliferate primitive proliferates every eligible permanent (no controller choice)

**Location**: `rust/src/state_ops_counters.rs::proliferate` (the
`#[pymethods]` block — search for `fn proliferate`).

**What we do today**: `proliferate()` walks both players'
battlefields and, for every permanent with `counters != 0`, ticks
the counter by 1 in the direction it already has (positive →
+1, negative → −1, zero → unchanged). Saturating arithmetic at the
i32 extremes.

**Why this is wrong under CR 701.25a**: real proliferate is a
*controller choice*. The player resolving the effect picks any
number of permanents and players that already have counters and
chooses, for each, whether to put one more counter of an existing
kind on it. Concretely, three behaviors the primitive does not
expose:

1. *Decline to proliferate at all.* Sometimes the controller has no
   beneficial targets (their own creatures are at zero, opp's
   creatures only have +1/+1 counters they don't want to grow) and
   would prefer the effect resolves as a no-op.
2. *Proliferate only some eligible permanents.* The controller can
   skip their opponent's +1/+1 creatures while proliferating their
   own −1/−1-shrunk opp creatures. Today's primitive does both.
3. *Proliferate poison counters on players.* The Rust engine has no
   poison-counter field at all today, so the player-side half of
   proliferate is a silent no-op by absence — a separate divergence
   tracked here for completeness.

**Failure mode**: in any board state where proliferating an
opponent's +1/+1-counter creature is bad for the player resolving
proliferate (e.g. opp has a Hardened Scales creature with +3/+3
counters; auto-proliferating gives them +4/+4 instead of leaving
them at +3/+3), the primitive picks the worse outcome. Symmetric
case: proliferating own −1/−1-counter creatures (Persist'd creature
that will die at zero toughness next SBA) accelerates the
controller's own loss.

**When it matters**: rarely under the engine's current card pool
(Edge of Eternities focus). Proliferate cards in EoE: none in the
spoiled set as of 2026-05-10. The primitive lands as a building
block for Modern Horizons / War of the Spark-style sets if they
ever enter scope; until a card actually wires into this primitive,
the always-add behavior is unobservable.

**Fix scope when prioritized**: medium — the primitive grows a
`targets: Vec<u32>` parameter (or two — permanents + players) and
the resolution-side wiring in `apply_effect` exposes a per-eligible
target choice through `ChoicePoint`. Search-side: factored
per-target binary choice (proliferate-this-or-not), parallel to how
declare-blockers is factored today (see entry #2). For player
poison counters, the `Player` struct grows a `poison_counters: u8`
field and the primitive's poison-side half lights up.

**Impact estimate**: 0% strength cost today (no card uses
proliferate in EoE). Cards-side cost when proliferate cards enter
scope: ~1-3% strength cost in lopsided board states where the
controller would benefit from skipping the auto-target — bounded
by the rarity of "proliferating my opponent makes me lose".

---

## ~~15.~~ CLOSED: SearchLibraryForBasicLandTapped supertypes-proxy filter + xorshift64-only post-search shuffle + Python-side no-shuffle residual + Python summoning_sick

**Closed by** `feature/rust-search-basic-land-tapped-supertypes-migration`
(round 37, 2026-05-15) — the supertypes-proxy half — and
`feature/effect-rng-threading` (entry #16, G19 follow-up) — the
xorshift64-only-shuffle half — and
`feature/fix-search-library-python-shuffle-r54` (round 54) — the
Python-side no-shuffle residual + a second Python `summoning_sick`
bug in the same resolve method. All parts of the original divergence
are now bit-equivalent to Python's `is_basic_land` /
`random.Random.shuffle` shapes; the searched land enters
non-summoning-sick on both engines (CR 302.1). **The ONLY remaining
cross-engine divergence on the Lander-activation path is the
orthogonal Rust token-ceases-to-exist SBA gap (`graveyard_p0` — the
sacrificed token), which is NOT a #15 concern (it is a Rust-lane
token-SBA gap, same root cause as the
`Effect::EachOpponentSacrificesCreature` Rust-port entry) and #15 is
fully closed regardless of it.**

**Round-37 closure (supertypes half):** the round-30 supertypes
substrate (`feature/rust-supertypes-registry` merge `ef8fa004` —
`CardPrinting.supertypes: Vec<String>` field at
`rust/src/cards.rs:3278`, JSON load at `cards.rs:5132-5148`,
pymethod getter at `cards.rs:6278`) landed earlier than its single
remaining consumer. Round 22's filter-dispatch widening flipped the
sibling `Effect::SearchLibraryForCard` arm's `legendary_creature`
predicate to consume the substrate; the
`Effect::SearchLibraryForBasicLandTapped` arm at
`state_ops_resolve.rs:2378` was left on the
`card_types contains "Land"`-only proxy (the in-code "deferred
supertypes work" comment was the residual TODO marker).

Round 37 closes the residue: the predicate now reads
`card_types Land AND supertypes Basic` (CR 205.4a — basic land =
land with the Basic supertype), bit-equivalent to Python's
`is_basic_land = is_land and "Basic" in supertypes`. Parity-side
follow-up: `parity/cross_engine.py::build_rust_state` now stamps
the `("Basic",)` supertype on Land CardDefs that omit it, mirroring
the Python `_build_python_state` builder's existing heuristic — so
the Rust-side predicate's extra rigor doesn't surface as a parity
divergence on the convenience-form Land CardDefs (e.g.
`CardDef(name="Forest", card_type="Land", mana_produced=("G",))`).

**Pin tests added (round 37):**
- `tests_rust/test_resolve.py::test_resolve_search_library_for_basic_land_tapped_requires_basic_supertype`
  — a Land without the Basic supertype (non-basic dual / shock /
  fetch land shape) is rejected by the predicate.
- `tests_rust/test_resolve.py::test_resolve_search_library_for_basic_land_tapped_requires_land_card_type`
  — a non-Land carrying the Basic supertype (degenerate Basic
  Artifact shape) is rejected by the predicate.
- `tests_rust/test_resolve.py::test_resolve_search_library_for_basic_land_tapped_rejects_mistyped_basic_land_compound`
  — a hand-rolled fixture mis-encoding "Basic Land" as a single
  compound `card_types` entry (with empty supertypes) is rejected
  by the predicate's two-AND-ed contains check.
- `tests_rust/test_resolve.py::test_resolve_search_library_for_basic_land_tapped_picks_basic_over_nonbasic`
  — when the library has BOTH a non-basic land at the top and a
  basic Forest beneath it, the search walks past the non-basic and
  lands on the Forest (the supertypes half filters out the top-of-
  library non-basic).

The round-21 regression pins
(`test_resolve_search_library_for_basic_land_tapped_*` count-1 /
count-2 / picks-topmost / no-land-no-op / preserves-controller /
count-zero / shuffle / shuffle-deterministic / external-rng /
controller-routing) all continued to pass on first run after the
migration — the synthetic Forest seed at
`rust/src/state.rs:1791` already carried `supertypes=["Basic"]` on
its CardPrinting (round-30 registry update), so the migration is
behavior-preserving for the existing test surface and the four new
pins above are the direct supertypes-half exercise.

**Entry #16 (xorshift64-only shuffle half) closed earlier** by
`feature/effect-rng-threading` — the
`Effect::SearchLibraryForBasicLandTapped` resolve arm now routes
its post-search Fisher-Yates shuffle through the external rng
substrate when one is installed via
`GameState.set_external_rng(rng)`, producing byte-identical
permutations to `random.Random.shuffle(list)`. See entry #16
(below) for the full closure shape.

**Residual Python-side gap — CLOSED round 54 (Python-lane).** The
original entry flagged that Python's
`SearchLibraryForBasicLandTapped.resolve` did NOT call
`shuffle_library` (Stage-3 simplification). Round-53 N1's genuine
Phase-3a probe real-card-exposed it (the Lander activation became
drivable when the fixed-single-Lander carriers — Galactic Wayfarer
33,469 decks, Beamsaw Prospector 24,310 — were admitted), pinning the
divergence set `{battlefield, graveyard_p0, library_p0}` as a
known-gap (round-39 latent-SBA precedent) hypothesizing all three were
downstream of the Python-no-shuffle gap and would auto-convert
together once Python shuffled.

**Round-54 closure (this round).** Python's
`SearchLibraryForBasicLandTapped.resolve`
(`src/mtg_bot/effects/generic/search.py:130`) now calls
`shuffle_library(state, controller_id)` post-search — on BOTH the
success path AND the no-basic-land early-return path (CR 701.19 /
701.22 — a library search shuffles whether or not a card was found),
matching every sibling library-search Effect in the module and the
Rust arm's always-shuffle behavior. `shuffle_library` calls
`state.rng.shuffle(p.library)`; when the parity harness threads the
SAME `random.Random` instance into `state.rng` (Python) AND via
`GameState.set_external_rng` (Rust — whose post-search Fisher-Yates
reads `_randbelow` draws, **bit-identical to `random.Random.shuffle`**
per entry #16), both engines consume the IDENTICAL `_randbelow` draw
sequence in the identical order, so the post-search library order is
**byte-identical cross-engine**.

**Before/after.** Before: Python skipped the shuffle entirely; after a
Lander search the libraries held the same multiset in *different*
order cross-engine. After: with a shared rng threaded, `library_p0`
is `compare_fields`-clean. Verified by the new pins
`test_r54_cross_engine_search_library_basic_land_byte_equal_shared_rng`
(Python engine resolve byte-equal to Rust engine arm, seeds 1/7/42/
2026), `test_r54_python_search_library_basic_land_post_search_shuffle_
deterministic` (per-seed determinism + seed-sensitivity) and
`test_r54_python_search_library_basic_land_shuffles_on_no_match`
(early-return path also shuffles).

**RNG contract (cross-reference #16).** The byte-equality is NOT
merely "Python shuffles too" — it requires the SAME shared
`random.Random` consumed in the SAME order. Rust's external-rng
Fisher-Yates (`for i in (1..n).rev(): j = rng._randbelow(i+1);
swap(i,j)`) is exactly CPython's `random.shuffle` algorithm; Python's
`shuffle_library` IS `random.Random.shuffle`. They match iff (a)
both engines hold the same rng instance / an instance at the same MT
position, and (b) no intervening RNG draw desyncs the streams between
setup and the search. The parity harness must install the shared rng
on both engines (`py_state.rng = r` + `rust_state.set_external_rng(r)`)
for cross-engine byte-equality — see the round-53 genuine probe's
round-54 threading block. In production (no shared rng installed) the
restored shuffle is simply the CR-correct behavior on `state.rng`'s
own stream.

**The round-53 `{battlefield, graveyard_p0, library_p0}` set was only
PARTLY a #15 consequence — narrowed precisely.** The genuine
end-to-end repro showed:

- `library_p0` — the genuine #15 post-search-shuffle gap. **CLOSED**
  (the shuffle restoration above).
- `battlefield` — **NOT** a shuffle consequence. It was a *second*
  Python bug in the SAME resolve method: the searched land entered
  with stale `summoning_sick=True` (a library `GameObject` defaults
  `summoning_sick=True`; the resolve never cleared it) while the Rust
  arm correctly sets `summoning_sick = false` (CR 302.1 — summoning
  sickness applies only to creatures; a land entering via a search
  has none). **CLOSED round 54** (`land.summoning_sick = False` added
  to the resolve, same slice — once library order matched, both
  engines search the SAME object id so the bf tuple is byte-equal).
- `graveyard_p0` — the sacrificed Lander token. **CLOSED round 55**
  (Rust-agent N2 — the Rust token-cease-to-exist SBA). Python (source
  of truth, CR 111.7) correctly applies the token-ceases-to-exist SBA
  so its graveyard is empty; pre-round-55 Rust left the dead token in
  the graveyard (the Rust runtime had no `is_token` notion). Round 55
  added `RegistryData::is_token` (derived from the Round-30
  `supertypes` Vec — `"Token" in supertypes`, the SAME bit the
  cross-engine bridge already round-trips for token printings via
  `("Token",)`) and a deferred token-cease queue
  (`pending_token_cease`) populated at every bf-exit site
  (`queue_token_cease`, sibling of the LEAVES push) and drained at the
  tail of `drain_pending_leaves_dispatches` + `apply_sbas` — AFTER the
  DIES+LEAVES dispatches so the token is still its own dies/leaves
  observer (Python's by-reference `move_off_battlefield` semantics),
  then removed from whatever non-bf zone it landed in. The genuine
  probe's CONTRACT 2 was **flipped from the precisely-narrowed
  `diverged_fields == ["graveyard_p0"]` known-gap to `compare_fields()
  == []`** — the WHOLE Lander sac-activation is now byte-equal
  cross-engine. The **shared-root `Effect::EachOpponentSacrifices-
  Creature` entry is CLOSED in the same slice** (the resolver's
  `find_map` predicate now gates on `!registry.is_token`).

**Why the Phase-3a admit stays §2-safe.** Unchanged from round 53:
the bench / trajectory walk (`scripts/bench_trajectory_parity.py`)
drives carrier ETBs but **never sac-activates the Lander** (it only
emits `activate_ability` for tapping lands for mana), so the
activation is never driven under the bench's strategy set; the
load-bearing guarantee for the admit is the token *entering*
byte-equal (CONTRACT 1, still passing). Round 54 additionally makes
the *activation* byte-equal for the SEARCH effect's full output
(searched-land identity + post-shuffle library order), leaving only
the orthogonal Rust token-SBA graveyard view.

**ROUND-59 N3 — REAL-GAME VALIDATED (caveat folded → validated).**
The round-53/55 token-cease-to-exist byte-equality was in-test-pinned
only because the bench never sac-activated the Lander (so the SBA
never fired in a real game — round-58 N3 proved it structurally
un-exercisable by the default move set). Round-59 N3 added a
narrowly-scoped, default-off, review-gated Lander `{2},Sac` activation
harness step (`bench_trajectory_parity.py::_try_activate_lander_sac`,
gated behind `--activate-lander-sac`; identical activation driven on
BOTH engines via the shared-RNG round-54 recipe). A 72-game real-game
sweep: on **6/6** token-created games the Lander left the battlefield,
the cease-to-exist SBA fired, and the whole post-sac field view was
**byte-equal cross-engine — 0 FAIL_DIVERGENCE**, no latent bug on the
first real-game exercise of the full sac→search→shuffle→token-cease
path. The token-cease-to-exist SBA + the full Lander sac-activation
are therefore **real-game validated**, not merely synthetic-in-test-
pinned. (The default bench remains byte-for-byte unchanged — the
harness is a validation lever, not a production-self-play behavior
change.)

**Impact estimate:** strength-neutral (the library is hidden
information; the search picks the topmost basic on both engines
regardless of post-search order). The value is pure cross-engine
parity: the 57,779-deck Galactic Wayfarer / Beamsaw Prospector Lander
cluster's `{2},Sac:SearchLibraryForBasicLandTapped` activation is now
byte-equal cross-engine for the search effect's full output.

**Location of the now-CR-compliant code**:
`rust/src/state_ops_resolve.rs::apply_effect` — the
`Effect::SearchLibraryForBasicLandTapped` arm (round-23 effect-
coverage slice; G19 closure post-shuffle; round-37 supertypes
migration). Variant declared in `rust/src/cards.rs`. Cross-engine
bridge supertypes default at
`src/mtg_bot/parity/cross_engine.py::build_rust_state` (round-37
parity follow-up). Python side:
`src/mtg_bot/effects/generic/search.py:130`
`SearchLibraryForBasicLandTapped.resolve` — round-54 post-search
`shuffle_library(state, controller_id)` (success + no-match paths)
and `land.summoning_sick = False`. Cross-engine shared-rng threading
demonstrated in
`tests/test_parity_smoke.py::test_phase3a_genuine_real_eoe_galactic_wayfarer_lander_activation`
(`py_state.rng = r` + `rust_state.set_external_rng(r)`).

---

## Rust token-cease-to-exist SBA (CR 111.7 / 704.5d) — deferred-queue timing note (round 55, NOT a divergence)

**This is NOT a deliberate divergence — it documents a design choice
in a CR-compliant feature so a future maintainer understands the
timing.** Round 55 (agent N2) gave Rust the CR 111.7 / 704.5d
token-cease-to-exist behavior, byte-matching Python.

**Location**: `rust/src/state_ops_zones.rs`
(`RegistryData::is_token`, `queue_token_cease`,
`drain_pending_token_cease`, `mark_left_battlefield_if_nonland`
neighbor); `rust/src/state.rs` (`pending_token_cease` field);
`rust/src/state_ops_resolve.rs` + `state_ops_actions.rs` +
`state_ops_sba.rs` (the `queue_token_cease` sibling at every bf-exit
site; the cease-drain at the tail of
`drain_pending_leaves_dispatches` + `apply_sbas`). Python source of
truth: `src/mtg_bot/turn.py:241-263` (`move_off_battlefield`).

**The design choice**: Python's token cease-to-exist is *eager* — in
`move_off_battlefield` the token is removed from the battlefield and
the `is_token` branch simply never pushes it to graveyard/exile; the
token is in NO zone, yet `_fire_dies_triggers(state, obj)` /
LEAVES still fire with `obj` passed **by reference**. Rust's bf-exit
primitives instead push the object to its destination zone, queue
DIES/LEAVES *by id*, then drain. Rust matches Python's *observable*
result by **deferring** the cease-removal: every bf-exit queues the
leaving id onto `pending_token_cease`; the token stays in its
destination zone through the DIES + LEAVES dispatch (so it is still
findable as its own dies/leaves extra-observer — the by-reference
faithful equivalent), then `drain_pending_token_cease` (run AFTER
both drains) removes it if its printing `is_token`. Final state:
token in no zone — byte-equal to Python.

**Matched Python quirk (intentional, not "more correct")**: Python's
SBA loop (`_state_based_actions_pass`) does **NOT** scrub tokens that
appear in a non-battlefield zone via a non-bf-exit path
(`turn.py:1179-1182` KNOWN GAP: "Token in non-battlefield zone other
than via leave-play: not actively scrubbed"). Rust matches this:
`pending_token_cease` is filled **only on a bf-EXIT**, and
`drain_pending_token_cease` explicitly does **not** scrub the
battlefield (a token re-entering bf via a re-entrant LEAVES trigger
legitimately exists). Rust does not invent a divergent "scrub every
token in every zone every SBA pass" behavior — it mirrors Python's
exact (narrower) trigger surface. No EoE card today moves a token
into a non-bf zone except via leave-play, so the shared quirk is
unobservable in the pool; it is documented for fidelity per §2.

**`is_token` derivation (no new per-printing field)**: token-ness is
`supertypes` contains `"Token"` — identical to Python's
`CardPrinting.is_token`. The cross-engine bridge already round-trips
a token printing's `("Token",)` supertype tuple
(`build_rust_state`'s `printing_dict["supertypes"]` + the
`_seat_token_printings` `supertypes=("Token",)` stamp), so a token
registered cross-engine is `is_token` on BOTH engines with zero new
plumbing. Token-creation arms (`CreateToken` /
`CreateTokenTapped` / `CreateTokenEachPlayer`) reference a
`token_printing_id` registered with that supertype tuple, so
freshly-minted tokens resolve as tokens with no per-object flag.

**Impact**: pure cross-engine parity gain — the 57,779-deck Galactic
Wayfarer / Beamsaw Prospector Lander cluster's
`{2},Sac:SearchLibraryForBasicLandTapped` activation is now FULLY
byte-equal cross-engine (the genuine Phase-3a probe's `graveyard_p0`
residual flipped to `compare_fields() == []`). Perf: one
unconditional `Vec<u32>` push per bf-exit + one post-drain scan over
non-bf zones — negligible (bf-exits are not the hot loop). Pinned by
the `test_r55_*` regression + bridge pins and the genuine real-EoE
probe in `tests/test_parity_smoke.py`.

---

## ~~16.~~ CLOSED: SearchLibraryForBasicLandTapped consumes the external rng via state.rng (G19 follow-up)

**Closed by** `feature/effect-rng-threading`. The
`Effect::SearchLibraryForBasicLandTapped` resolve arm in
`rust/src/state_ops_resolve.rs::apply_effect` now routes its post-
search Fisher-Yates shuffle through the external rng substrate (CE8
Slice 2 / I41) — when the caller installs a Python `random.Random`
via the new `GameState.set_external_rng(rng)` pymethod, the in-Effect
shuffle reads draws via `external_rng::next_below`, producing byte-
identical permutations to `random.Random.shuffle(list)`. When no rng
is installed (production cli / bench callers), the legacy xorshift64
fallback runs unchanged.

Threading shape: per the
[Effect-rng audit](RUST_EFFECT_RNG_AUDIT.md) §4 "Option A"
recommendation, the rng is stashed on `GameState.rng:
Option<Py<PyAny>>` (set via `set_external_rng`, cleared via
`set_external_rng(None)`) rather than threaded as a parameter
through every intervening call site (`apply_effect` /
`resolve_top_of_stack` / `apply_effect_pub` /
`auto_resolve_pending_decisions`). The Effect arm reads the rng via
`state.rng_ref()` before the in-arm Fisher-Yates loop.

**Pinning tests**:
- `tests_rust/test_resolve.py::test_resolve_search_library_for_basic_land_tapped_external_rng_matches_python_shuffle`
  — post-search library matches `random.Random(seed).shuffle` byte-
  for-byte.
- `tests_rust/test_resolve.py::test_resolve_search_library_for_basic_land_tapped_external_rng_none_falls_back_to_xorshift`
  — backward compat: `set_external_rng(None)` is byte-equivalent to
  never setting it.
- `tests_rust/test_resolve.py::test_resolve_search_library_for_basic_land_tapped_external_rng_differs_from_xorshift`
  — sanity check that the two paths produce distinct permutations.
- `tests_rust/test_resolve.py::test_resolve_search_library_for_basic_land_tapped_external_rng_preserved_across_clone`
  — `GameState.clone()` preserves the stashed rng reference (Python
  refcount bump via the manual `Clone` impl).
- `tests_rust/test_resolve.py::test_resolve_search_library_for_basic_land_tapped_external_rng_clone_isolation`
  — pins the shared-rng-across-clones semantic (single instance,
  consecutive draws).
- `tests/test_parity_smoke_edge_cases.py::test_cross_engine_search_library_for_basic_land_tapped_external_rng_matches_python_mt`
  — cross-engine pin: Rust post-resolve library matches Python's
  MT reference under a shared `random.Random`.
- `tests/test_parity_smoke_edge_cases.py::test_cross_engine_search_library_for_basic_land_tapped_shared_rng_walks_clean_for_multiple_seeds`
  — multi-seed robustness companion (seeds 1, 7, 42, 100).

**Closure invariant**: see I43 in `docs/RUST_PARITY_GAPS.md` for the
`GameState.rng` field lifecycle (caller-set via `set_external_rng`,
consumed by `Effect::SearchLibraryForBasicLandTapped`, not serialized
into fingerprint, clone-preserved via the manual `Clone` impl).

**Python-side follow-up — CLOSED round 54.** Python's
`SearchLibraryForBasicLandTapped.resolve` now calls
`shuffle_library(state, controller_id)` post-search (success +
no-match paths — CR 701.19 / 701.22), and a second Python bug in the
same method (searched land entering with stale `summoning_sick=True`)
was fixed (`land.summoning_sick = False`, CR 302.1). With the same
shared `random.Random` threaded into both engines (`state.rng` on
Python, `set_external_rng` on Rust), the post-search library order
AND the searched-land battlefield tuple are byte-identical
cross-engine — see #15 above for the full closure narration. The
only remaining Lander-activation divergence is the orthogonal Rust
token-ceases-to-exist SBA gap (`graveyard_p0`), tracked separately.

---

## Rust port — `legal_decisions` factored combat emission (G1 — CLOSED)

> **CLOSED by `legal_decisions` factored-combat (G1 — the C1-analog
> for the combat axis;
> `feature/rust-legal-decisions-factored-combat`).** This entry
> replaces the two former ACCEPTED divergences ("DeclareAttackers
> powerset emission" + "DeclareBlockers product-space emission"). It
> is the combat-axis sibling of the legal-set mana/target/cost
> closures (C1 Slices 1–3) — the same non-destructive,
> parity-NEUTRAL, subset-preserving, negative-control-verified
> discipline.

**Location**: `rust/src/state_ops_legal.rs:legal_decisions` — the
factored-emission blocks (search for "G1 — factored per-attacker
emission" / "G1 — factored per-blocker emission" + the
factored-emission module-docstring sections); `Action::Attacker
Decision` / `Action::BlockerDecision` in `rust/src/actions.rs`;
their apply arms in `rust/src/state_ops_actions.rs`.

**What we used to do (the divergence, now CLOSED)**: during
`DECLARE_ATTACKERS` Rust emitted a Rust-only **capped `2^n`
powerset** of whole `declare_attackers` actions
(`DECLARE_ATTACKERS_POWERSET_CAP = 4`); during `DECLARE_BLOCKERS` a
Rust-only **capped `(M+1)^N` product** of whole `declare_blockers`
assignments (`DECLARE_BLOCKERS_PRODUCT_CAP = 3`,
`DECLARE_BLOCKERS_MAX_ATTACKERS = 3`). Python's `legal_actions`
emits NEITHER (`engine.py:10-19` — combat declarations "aren't
enumerable ... combinatorial"); Python's search uses a FACTORED
per-creature decomposition (`search/combat_decisions.py`:
`AttackerDecision(attacker_id, attack)` / `BlockerDecision(
blocker_id, attacker_id)`) surfaced by
`MtgGameStateAdapter.legal_decisions` (`engine_adapter.py:808-828`)
and accumulated to a single engine-level `DeclareAttackers` /
`DeclareBlockers` at finalize (`engine_adapter.py:1080-1144`). The
Rust powerset/product set was **neither a superset nor byte-equal**
to that factored set — the G1 flip-blocker
(`docs/NN_RUST_DECISION_SOURCING_WIRING_DESIGN.md` §2.4 G1).

**What we do now (the byte-compatible factored emission)**: Rust
`legal_decisions` emits, for the HEAD pending creature, the SAME
factored per-creature decision shape Python's search seam consumes:
- DECLARE_ATTACKERS → exactly two `{"kind":"attacker_decision",
  "attacker_id":head,"attack":<bool>}` dicts (`attack=true` then
  `false`), `head` = smallest-id eligible (matches the adapter's
  `_pending_attackers = sorted(...)` `engine_adapter.py:1315` + the
  codec's `_pending_attacker_head` `min(...)`
  `action_encoding.py:990-995`), mapping 1:1 to the codec's
  `SLOT_ATTACKER_ATTACK` / `SLOT_ATTACKER_SKIP`.
- DECLARE_BLOCKERS → one `{"kind":"blocker_decision","blocker_id":
  head,"attacker_id":<atk>}` per live attacker (in `self.attackers`
  declaration order) then a final `…,"attacker_id":None` ("don't
  block"); the codec recovers `SLOT_BLOCKER_BASE + atk_pos` from the
  `attacker_id` VALUE via `_attacking_creatures`
  (`action_encoding.py:714-733`) so branch list order is
  slot-irrelevant.
The B3 Python provider (sibling slice — NOT this one) owns the
per-creature accumulation + finalize via the UNCHANGED whole-action
`apply_action({"kind":"declare_attackers"/"declare_blockers",…})`
arm (which keeps the CE16 menace post-validation). For round-trip
completeness `apply_action` also accepts a single
`attacker_decision`/`blocker_decision` dict directly, dispatching
the SAME round-5 `declare_attacker`/`declare_blocker` primitives the
whole-action arms loop over (single source of truth — a factored
sequence applies byte-identically to the accumulated whole;
`attack=false` / `attacker_id=None` are no-ops, mirroring the
adapter's `_apply_*_decision` `engine_adapter.py:1095-1128`).

**Why this is parity-NEUTRAL (the honest argument — C1 §4 shape)**:
every cross-engine harness replays a **Python-derived**
`action_dict` on BOTH engines via `cross_engine.step_both` and
NEVER sources an agent choice from `rust_state.legal_decisions`
(verified `cross_engine.py:10443-10448`). The Python-derived combat
dict is the whole-action `{"kind":"declare_attackers",…}` /
`{"kind":"declare_blockers",…}` (`_dict_to_python_action`,
`cross_engine.py:10155-10173`), and the whole-action `apply_action`
arms are UNCHANGED. So every Python-sourced replayed combat action
still applies byte-identically; the change only swaps a Rust-only
*emission* set no harness agent ever picks. Empirically validated:
every existing trajectory/probe/combat pin is UNCHANGED (a pinned
trajectory shift would be a RED FLAG — none occurred).

**Accepted residuals (honest, bounded — NOT new divergences)**:
- The stateless-Rust / stateful-provider split: Rust emits the HEAD
  pending creature's factored options; the B3 provider owns the
  pending-pop walk (ports `engine_adapter.py:1080-1144` verbatim).
  This is the design's specified shape
  (`NN_RUST_DECISION_SOURCING_WIRING_DESIGN.md` §3.3), not a gap.
- Block-legality keyword filters (flying/reach/protection/skulk)
  remain deferred to the apply-time `declare_blocker` per-pair gate
  (the SEPARATE entry below — unchanged by G1; same silent-skip
  pattern, now per factored decision instead of per product cell).

**Impact estimate**: ZERO on cross-engine trajectory parity (the
parity-neutral proof above; no sentinel-count / Effect / bridge /
`_SAFE_*` move). STRENGTH: strictly POSITIVE vs the pre-G1 caps —
the powerset/product caps collapsed every non-trivial combat board
to "all-or-nothing" / "no-blocks-only"; the factored shape reaches
every attack/block pattern through MCTS depth with a fixed tiny
fan-out (the `combat_decisions.py` design rationale: deep narrow
trees, UCB1 doesn't degrade with depth). The capped-emission
strength cost the two former entries flagged is REMOVED.

---

## Rust port — `legal_decisions` block-legality keywords not filtered at enumeration

**Location**: `rust/src/state_ops_legal.rs:legal_decisions`
DeclareBlockers eligibility loop.

**What we do today**: the eligibility filter checks
`!tapped && is_creature`. It does NOT filter by flying/reach
interaction (CR 702.9 — a creature with flying can only be blocked
by a creature with flying or reach), color protection (CR 702.16),
"can't be blocked" (CR 509.1b), skulk (CR 702.118), or
`can_only_block_creatures_with_flying`. All eligible-by-status
blockers appear in every assignment regardless of whether the
attacker-blocker pair is actually legal; the `declare_blocker`
primitive's per-pair `bool` return silently filters illegal pairs at
apply time.

**Why this diverges from Python**: Python's
`src/mtg_bot/combat.py:can_block` runs the full keyword filter at
enumeration time. The Rust enumerator defers the filter to the
primitive instead — bigger emission count + same final state after
apply, mirroring the same trade-off as the DeclareAttackers
defender-deferral above.

**Failure mode**: search wastes visits on assignments containing
illegal pairs (the apply silently drops them, so the post-apply
state matches what an equivalent "illegal-pair-excluded" assignment
would produce). Visit count is inflated but win-rate impact is
proportional to "fraction of emitted assignments containing illegal
pairs" — which can be substantial on a flying-heavy board.

**When it matters**: any DECLARE_BLOCKERS state where the attacker
has flying / "can't be blocked" effects / color protection and the
defender has non-flying / non-reach / wrong-color blockers. EoE has
plenty of flyers; the impact rises with the pool.

**Fix scope when prioritized**: medium. Add `effective_keywords`
bridge to Rust (or a thinner version of `can_block` keyed only on
the flying / cant-be-blocked / skulk keywords first-slice cares
about), then filter at enumeration. The primitive's apply-time gate
stays as defense-in-depth.

**Impact estimate**: at slice landing, low (synthetic seed has no
flyers); rises with EoE pool coverage.

---

## Rust port — `legal_decisions` defender keyword not filtered at enumeration

**Location**: `rust/src/state_ops_legal.rs:legal_decisions`
DeclareAttackers eligibility loop.

**What we do today**: the eligibility filter checks
`!tapped && is_creature && (!summoning_sick || has_haste)`. It does
NOT filter out creatures with the `defender` keyword (CR 702.3).
A defender creature appears in every emitted subset; the
`declare_attacker` primitive's per-id apply-time gate rejects it
silently (returns `false` for that id, the rest of the subset
still gets declared).

**Why this diverges from Python**: Python's
`src/mtg_bot/combat.py:eligible_attackers` (lines 15-23) filters
defender out at enumeration time. The Rust enumerator defers the
filter to the primitive instead — bigger emission count + same
final state after apply.

**Failure mode**: search wastes visits on subsets that include
defender-keyword creatures (the apply silently drops them, so the
post-apply state matches what an equivalent "defender-excluded"
subset would produce). Visit count is inflated but win-rate impact
is minimal.

**When it matters**: rarely. Most untapped creatures aren't
defenders; defender printings are usually walls that stay tapped.
Pre-token-creation training data has zero defender printings in the
EoE pool.

**Fix scope when prioritized**: add a one-line keyword check to the
eligibility loop:
```rust
if printing.keywords.iter().any(|k| k == "defender") {
    continue;
}
```

**Impact estimate**: negligible. Strictly a small redundant-visit
cost; no strength change.

---

## Rust port — `legal_decisions` ActivateAbility approximated to mana producers

**Location**: `rust/src/state_ops_legal.rs:legal_decisions`
ActivateAbility emission loop.

**What we do today**: emit one `ActivateAbility(source_id,
ability_index=0)` per untapped permanent on the priority player's
battlefield whose printing has `mana_produced.is_some()`. No real
ability iteration — `ability_index` is hardcoded to 0.

**Why this diverges from Python**: Python's
`src/mtg_bot/legal.py:612-829` walks
`effective_activated_abilities(state, obj)` per battlefield permanent
and emits one `ActivateAbility(source_id, idx)` per legal-to-pay
ability. The full activated-ability tree (mana abilities, planeswalker
loyalty abilities, equip-style activations, all the cost-gated
variants the Python source filters between lines 631-826) is missing
because Rust's `CardPrinting` (`rust/src/cards.rs:361-396`) has no
`activated_abilities` field — only `mana_produced`, `card_types`,
`power`/`toughness`, `keywords`. Porting the full
`ActivatedAbility` + `ActivationCost` + per-effect dataclass tree
through PyO3 is a much bigger bridge slice.

**Failure mode**: every non-mana activated ability (planeswalker
loyalty, equip / unearth / cycling / channel / activate-X-tap-mana
abilities on non-land sources, etc.) is silently absent from the
emission. Search never visits decision branches that would activate
those abilities. The mana ones DO emit but the dispatch arm at
`state_ops_actions.rs:271-276` is also a stub (raises ValueError) —
so the wire shape ships but the actual ability resolution is the
parity-smoke retry loop's problem.

**When it matters**: the bigger the activated-ability count in a
state, the more search depth Rust skips. EoE has planeswalkers,
loyalty activations, several creature mana producers (Llanowar Elves
in the synthetic seed has `mana_produced=Some(["G"])` and currently
ALWAYS emits — even when summoning-sick — because the creature-tap
sickness filter isn't ported either).

**Fix scope when prioritized**: medium-large. (1) Port `ActivatedAbility`
+ `ActivationCost` + per-effect dataclass tree through PyO3 into
`cards.rs`. (2) Build `effective_activated_abilities` primitive in
Rust (mirrors `src/mtg_bot/game.py`). (3) Replace the
`mana_produced.is_some()` filter in `state_ops_legal.rs` with a real
ability iteration. (4) Land the `activate_ability` primitive in
`state_ops_*.rs` so dispatch flips from "ValueError stub" to a real
state mutation. Each can ship independently.

**Impact estimate**: at the slice's first commit, the enumerator
covers ~1.9% of Round-20 decisions (per the round-23 ActivateAbility
agent's commit note); without the dispatch primitive, the
parity-smoke retry loop catches and skips. Strength impact is
proportional to "activated-ability-bearing decisions in the trace"
× "average gain from playing them optimally" — non-trivial once
planeswalkers + creature mana sources mature.

---

## Rust port — `Effect::ManifestDread` face-down state + count > 1 deferred

**Location**: `rust/src/state_ops_resolve.rs` `Effect::ManifestDread`
resolve arm; `rust/src/state_ops_decisions.rs`
`resolve_manifest_dread_to_battlefield` helper.

**What we do today**: when a ManifestDread effect resolves, the
controller picks one of the top 2 (or 1 if library has 1 card)
examined cards. The picked card is moved to the controller's
battlefield WITH ITS ORIGINAL PRINTING VISIBLE (name, types, P/T,
abilities, color all visible to both players). The other examined
card goes to graveyard. `count > 1` (multi-iter form) and
`count = 0` (no-op) raise at resolve time with a clear "deferred"
message; `count = 1` is the only supported value in the first-slice.

**Why this diverges from real MTG**: CR 701.34 + 707 specifies that
a manifested permanent enters the battlefield FACE DOWN. While
face down, it has:
* No name, no card types other than "Creature", no subtypes
* Base 2/2 power and toughness (CR 707.2c)
* No abilities (except those that function in any zone or affect
  the face-down permanent itself)
* It is colorless
* Its owner can turn it face up at any time by paying the original
  printing's mana cost (CR 707.4) if it is a creature card

The first-slice Rust port skips ALL of these — the manifested card
is functionally a normal permanent of its printing's type. Python's
`src/mtg_bot/effects/generic/library_lookat.py:ManifestDread`
similarly sets `card.face_down = True` but only the face-down flag
is set; the 2/2 vanilla-creature semantics are not threaded through
the engine's effective-keyword / effective-P/T / effective-card-type
readers (which would require a layer-1 characteristic-replacement
implementation across power/toughness/types/abilities). The Rust
port mirrors the Python state today and additionally drops the
`face_down` flag because GameObject doesn't have one.

**Why this is OK as a first-slice**: ManifestDread's primary
strategic value is "pseudo-card-advantage + body on the
battlefield". Modeling the body as a face-down 2/2 vanilla rather
than the original creature's printed P/T loses some accuracy in
combat — a manifested Bashful Beastie (5/5 with stats baked into
its printing) plays as a 5/5 in this engine but should be a 2/2
face-down. But every model trained on this engine sees consistent
ManifestDread behavior — the bias is in the same direction in both
seats and largely washes out for self-play. Real-MTG correctness
matters more when face-up flip costs become tactically relevant
(deferred).

**For `count > 1`**: only a handful of EoE cards reference "manifest
dread N times" (Slimy Aquarium / Weight Room riders) or "manifest
dread X times" (Valgavoth's Onslaught). The first-slice gate makes
those error out loudly rather than silently produce wrong behavior;
the parse layer accepts any non-negative count so the dict round-
trip is forward-compatible with the multi-iter follow-up slice.

**Failure mode (face-down semantics)**:
1. A manifested creature is destroyed by an Auntie's Hovel-style
   "destroy target X creature" that wouldn't legally target a
   face-down 2/2 (face-down has no subtypes). Real MTG: spell
   fizzles. Engine: spell resolves on the visible printing's
   subtype.
2. A face-down creature attacks. Real MTG: combat-damage assigner
   uses the 2/2 P/T. Engine: uses the printing's P/T.
3. A face-down creature is sacrificed for an effect that requires
   "creature with mana value N or less" (face-down has mana value
   0 per CR 707.2d). Real MTG: any face-down satisfies "MV ≤ 0".
   Engine: uses the printed mana value.
4. The "turn face up by paying the mana cost" activated ability is
   missing entirely — the manifest can never flip up in this engine.

**Failure mode (count > 1 gated at resolve)**:
* Slimy Aquarium's "manifest dread, then put a +1/+1 counter on
  that creature" works (count=1, ManifestDreadThenPutPlusOneCounters
  is a separate Python class — and isn't a count > 1 form).
* Anything that genuinely emits ManifestDread(count=2+) will raise
  a ValueError at stack-resolve time. This is loud-fail by design;
  silent partial would be worse.

**When it matters**: face-down state is a moderate-frequency edge
case once the engine sees real games. count > 1 is a low-frequency
edge case (a handful of EoE cards). Both rise in priority once
ManifestDread cards become common in trained decks.

**Fix scope when prioritized (face-down)**: medium. Either (a) add a
`face_down: bool` field to `GameObject` and bake it into
effective-P/T / effective-keyword / effective-types readers and the
fingerprint (requires rebuilding pinned baselines), or (b) introduce
a "face-down placeholder printing" and have ManifestDread swap the
manifested card's printing_id to that placeholder, threading the
original printing through a sidecar `manifested_from_printing_id`
field so face-up flip can restore it. (a) is more invasive but
cleaner; (b) avoids the fingerprint churn but adds a sidecar field
that also needs CR 400.7 zone-change reset semantics.

**Fix scope when prioritized (count > 1)**: small. Iterate the
resolve arm `count` times, each iteration popping + pushing its own
ManifestDreadChoice; the submit dispatcher loops naturally as each
decision drains. Alternatively, carry `remaining_iters: u32` on the
PendingDecision and re-push on submit. Either approach is ~30 LOC.

**Impact estimate**: strength cost is in the low single digits %
for face-down semantics in a mature deck-pool; near zero for
count > 1 in EoE (a few cards). Perf neutral — the face-down
modeling adds zero hot-path work; the count > 1 path only
matters when those specific cards resolve.

---

## Rust port — warp alt-cost cast pipeline: PHASE 1 + 1.5 + 2 SHIPPED (pure fixed-cost + safe-trigger+warp trio + Timeline Culler life/graveyard riders); full CR-603.7 delayed-trigger modeling remains the only Phase-3 follow-on

**Phase 2 update (Timeline Culler — the life + graveyard-cast
riders).** Phase 2 (`docs/WARP_COST_PHASE2_DESIGN.md`) closes the two
warp riders on **both** engines, admitting **exactly +1** card —
**Timeline Culler ({B} warp, Pay 2 life, graveyard-castable; +8,986
17lands decks)**. It is the ONLY card in the EoE pool carrying either
`warp_additional_life_cost > 0` OR `warp_castable_from_graveyard`
(verified live), so the surgical guardrail widening (delete the two
Phase-2-rider positive-rejection clauses in
`_printing_is_bridge_pure_warp_creature`,
`src/mtg_bot/parity/trajectory.py`) admits EXACTLY it; every other
clause is byte-for-byte unchanged so the 26 multi-gated warp cards
stay declined (static / non-safe-trigger / kicker — verified). Rust
changes: `CardPrinting` gains `warp_additional_life_cost: u8` +
`warp_castable_from_graveyard: bool` (`rust/src/cards.rs`, parsed via
the same back-compat `get_item { Some => .., None => default }`
shape); `cast_creature_warp` (`rust/src/state_ops_cast.rs`) is
extended with a hand→graveyard source-zone cascade (mirrors Python's
`_cast_spell` `if hand: .. elif gy-warp: ..`) + an unconditional life
debit after the mana spend (CR 117.9b — part of the warp alternative
cost, NO decision point); a new `move_from_graveyard_to_battlefield`
sibling of the exile-recast helper; the legal emitter
(`rust/src/state_ops_legal.rs`) gains a `life >
warp_additional_life_cost` gate on the hand warp emit (both
instant/sorcery sites — a verified NO-OP for every Phase-1/1.5 card
since their rider is 0 → `life > 0`, always true in a live game) + a
new SEPARATE graveyard warp loop (mirrors Python `legal.py:447-476`,
sorcery-speed, NO base/free-cast variant). The CardDef bridge
(`src/mtg_bot/parity/cross_engine.py`) gains `warp_life_cost` /
`warp_from_graveyard` round-tripped bidirectionally. **Shortcut =
none** — this is a faithful Python mirror, not a simplification. The
warp end-step exile remains the documented deterministic
PHASE_END_STEP-entry sweep, NOT a CR-603.7 stack-pushed delayed
trigger (UNCHANGED — Timeline Culler has `triggered_abilities=()`, no
LEAVES/DIES observer, and `attack_all` never holds priority at end
step; the delayed-trigger port is the only Phase-3 follow-on and
admits 0 new cards — see the dedicated PHASE_END_STEP-entry sweep
entry below). **Failure mode** = none for the bench-admitted set.
**Fix-scope** = realized. **Impact** = +1 card / +8,986 17lands
decks (a loader/real-game-coverage unlock — Timeline Culler is a
zero-Effect vanilla 2/2, NOT an Effect+bridge POOL_PARITY metric
move; the orchestrator resync should not double-count it, same as
Phase-1's +6,450 / the round-60 shockland dimension).

**Round-65 update (Phase 1.5 — safe-trigger+warp residue trio).**
Phase 1.5 widens `_printing_is_bridge_pure_warp_creature`'s Phase-1
`triggered_abilities == ()` boundary to a safe-trigger gate,
admitting **exactly +3** cards (Germinating Wurm, Knight Luminary,
Starbreach Whale — each warp_cost + one SAFE ETB trigger). NO Rust
change: the landed Phase-1 substrate (`cast_creature_warp` + the
PHASE_END_STEP exile sweep + the exile-recast) fires the ETB
generically via the same `move_from_hand_to_battlefield` →
`drain_pending_etb_dispatches` path as `cast_creature`, so the ETB
fires byte-equal under the warp-cast path (the load-bearing new
assertion, pinned). The §2 teeth are preserved (Timeline Culler,
Codecracker Hound / Mechanozoa, Quantum Riddler all stay declined).
Details + the byte-equal-under-warp-cast pins are in the dedicated
"warp end-step exile is a PHASE_END_STEP-entry sweep" entry below
(Phase 1.5 sub-section). The Phase-1 substrate description below is
unchanged and still accurate.

**Round-63 update (Phase 1 closure for the pure fixed-cost shape).**
Phase 1 (`docs/WARP_COST_PHASE1_DESIGN.md`) shipped the
pure-fixed-`ManaCost` warp path on Rust for **Red Tiger Mechan
({1}{R} warp / {3}{R} normal) + Bygone Colossus ({3} warp / {9}
normal)**. The round-61 SL claim "**NO production code path in Rust
sets the flag**" is now FALSE for the pure-fixed-cost shape: Phase 1
wires the production write at
`rust/src/state_ops_cast.rs::cast_creature_warp` (mirrors Python
`actions.py:1427`). The stale line refs in this pin are corrected
below (`state.rs:758-762`→`state.rs:1102`,
`cards.rs:1855-1898`→`cards.rs:4225-4419`,
`state_ops_actions.rs:245-292`→`:287-352`,
`state_ops_cast.rs:285-355`→`:343-+`). What REMAINS Phase 2+:
Timeline Culler's `warp_additional_life_cost` life payment + the
`warp_castable_from_graveyard` cast-from-graveyard zone arm + the
full CR-603.7 delayed-trigger modeling (Rust uses a deterministic
PHASE_END_STEP-entry sweep instead — see the dedicated SL entry
below).

**Location**: `rust/src/state.rs:1102` (`spell_warped_this_turn`
field), `rust/src/state_ops_resolve.rs` (`Effect::ConditionalIfVoid`
resolver — consumer), `rust/src/state_ops_actions.rs:287-352`
(`Action::CastSpell` arm — Phase 1 routes `use_warp=true` to
`cast_creature_warp`), `rust/src/state_ops_cast.rs:343-+`
(`cast_creature` + the new `cast_creature_warp` / exile-recast
branch), `rust/src/cards.rs:4225-4419` (`CardPrinting` struct — now
HAS `warp_cost: Option<ManaCost>`; `warp_castable_from_graveyard` /
`warp_additional_life_cost` are now BOTH present (Phase 2 — `u8` /
`bool`, parsed via the same back-compat get_item shape), alongside
the new `move_from_graveyard_to_battlefield` helper + the
`cast_creature_warp` graveyard fall-through & life debit
(`state_ops_cast.rs`) + the life-gate & graveyard warp loop
(`state_ops_legal.rs`).

**What we do today (post-Phase-2)**: the
`state.spell_warped_this_turn` field exists on Rust's `GameState`,
is reset on entry to PHASE_CLEANUP, and is read by the
`Effect::ConditionalIfVoid` resolver via `is_void_active` (LTB-half
OR warp-half). Phase 1 ADDED the production write at
`cast_creature_warp` (pure-fixed-cost warp from hand). The
`Action::CastSpell` dispatch arm branches on `use_warp`: `true`
→ `cast_creature_warp` (pays `warp_cost`, sets the flag, stamps the
end-step exile); `false` → `cast_creature` (also serves the
warp-exile recast at normal `mana_cost`). **Phase 2 closed the
remaining riders**: `cast_creature_warp` now also (a) falls through
to the GRAVEYARD when the obj is absent from hand and the printing
is `warp_castable_from_graveyard` (the dispatch site is
byte-identical — the cascade is inside the primitive, mirroring
Python's single `_cast_spell`), and (b) debits
`warp_additional_life_cost` from the caster's life unconditionally
after the mana spend. So Timeline Culler's warp-cast (hand OR
graveyard) NOW sets the flag, pays {B} + 2 life, and is exiled by
the SAME deterministic end-step sweep — it is admitted by
`_printing_is_bridge_pure_warp_creature` (the two former
rider-rejection clauses were removed). No rider gap remains; the
only Phase-3 follow-on is the CR-603.7 delayed-trigger model
(0-card-leverage — see the PHASE_END_STEP-entry sweep entry).

**Why this diverges from Python**: Python's
`src/mtg_bot/actions.py:1426-1436,1457` flips
`state.spell_warped_this_turn = True` at two cast-from-zone sites
(warp-from-hand and warp-from-graveyard for Timeline Culler), each
paying the printing's `warp_cost` instead of `mana_cost` and an
optional `warp_additional_life_cost`. Three Python consumers read
the resulting `is_void_active` predicate:
`mtg_bot.effects.state_predicates` (line 105-107),
`mtg_bot.effects.conditions` (315-317), and
`mtg_bot.effects.combinators` (`ConditionalIfVoid` resolver at
1450-1452, plus `is_void_active` lookup at 183-189). Rust currently
ports only the `ConditionalIfVoid` consumer; the other two
combinators / predicates routes have not been ported. So the
bounded impact of the missing warp-half setter is exactly:
`Effect::ConditionalIfVoid`-bearing spells resolved on a turn when
the controller has cast a warp spell take the `else_effect` /
no-op branch instead of the `then_effect` branch.

**Pool exposure**: 50 EoE cards mention "warp" in their oracle text
(measured 2026-05-12 against `data/edge_of_eternities.json`). Per
the round-29 ConditionalIfVoid slice (commit `de4a578c`), there are
4 EoE "Void —" rider cards whose `then_effect` is gated on
`is_void_active` (Decode Transmissions, Hymn of the Faller, and two
others). On a turn where one player warp-casts a spell and a
ConditionalIfVoid rider resolves AFTER that cast, Rust takes the
wrong branch.

**Failure mode**: silent — `Effect::ConditionalIfVoid` resolves
with `void=false` when only a warp-cast event has occurred this
turn (LTB events on the same turn still flip the void predicate
true via I29's LTB half, masking the divergence when both happen).
The closure is "implement warp cast in Rust → the flag setter
follows trivially at the warp-cast site (mirror Python actions.py:
1427,1457)". Until the cast pipeline routes warp distinctly, the
flag has no production write site to wire up.

**Cross-engine smoke surfacing**: the divergence cannot be surfaced
by the existing `tests/test_parity_smoke.py` cross-engine harness
without a warp-cost card in the deckspec, AND a ConditionalIfVoid
rider that resolves AFTER the warp cast in the same turn. Today's
parity-smoke deckspec has neither — surfacing this would require
seeding warp-castable + Void-rider printings into the synthetic
fixture. Deferred until the warp-cost CardPrinting fields land in
Rust (a much larger slice — see "Fix scope" below).

**Why it's OK for now**: warp casting is a Rust-side cast-pipeline
gap, not a flag-substrate gap. The closure is the whole alt-cost
infrastructure (cost-from-zone primitive + `Effect::Warp` + four
new `CardPrinting` fields for `warp_cost` /
`warp_castable_from_graveyard` / `warp_additional_life_cost` /
`cast_via_warp` end-of-turn-exile rider), not a one-line setter.
Adding a setter today would be dead code with no production write
path to hook it into. The flag substrate lives in Rust because
I29's LTB half consumes it; keeping both halves of the
`is_void_active` predicate on `GameState` matches Python's struct
shape so the eventual warp-cast slice slots a one-line write in
exactly where Python's `actions.py:1427` lives — mechanical
mirroring.

**Fix scope when prioritized**: large (full warp alt-cost cast
pipeline).
1. Add `warp_cost: Option<ManaCost>`,
   `warp_castable_from_graveyard: bool`,
   `warp_additional_life_cost: u8`, and `cast_via_warp: bool`
   (per-GameObject) fields to `CardPrinting` / `GameObject` +
   bridge dict parsing in `cards.rs`.
2. Carve the warp-cast cost-payment + zone-removal from
   `state_ops_cast.rs::cast_creature` into a separate
   `cast_via_warp(obj_id, player_id, zone_source)` primitive that
   reads `warp_cost` instead of `mana_cost`, pays the life rider
   (if any), removes from hand OR graveyard depending on
   `warp_castable_from_graveyard`, and **flips
   `state.spell_warped_this_turn = true` at that site** (the
   one-line mirror of `actions.py:1427`).
3. Flip `Action::CastSpell`'s `use_warp` arm in
   `state_ops_actions.rs:245-292` from "ignore the flag" to "route
   to `cast_via_warp` when `use_warp = true`".
4. Add an end-of-turn exile rider for `cast_via_warp = true`
   permanents (mirrors Python's warp-cast leaves-play behavior).
5. Update I29 in `RUST_PARITY_GAPS.md` to add the warp-half setter
   site to the void-flag-lifecycle setter list (currently I29 only
   documents the LTB half's setters; the warp half is noted as
   "still substrate-only" at line 1382-1385 with this doc-only
   audit as the deferral pin).
6. Regression test in `tests_rust/test_void.py`:
   `test_warp_cast_flips_spell_warped_flag` and
   `test_conditional_if_void_resolves_then_branch_after_warp_cast`,
   mirroring the I29 LTB-half tests' shape.

Each step ships independently; (1)+(2)+(3) are the minimum closure
for the flag setter to have a production write site. (4) is
orthogonal to this divergence (it's a separate spell-behavior gap).

**Impact estimate**: bounded to ConditionalIfVoid + warp + same-
turn ordering. Zero impact on any state where (a) no warp spell is
cast that turn, OR (b) no ConditionalIfVoid rider resolves AFTER
the warp cast on that turn, OR (c) a nonland LTB on the same turn
already flipped the void predicate true (the LTB half masks the
warp-half divergence — common in mid-game). The strength cost is
proportional to "warp-cast turns with a ConditionalIfVoid rider
resolving after but no concurrent LTB" — a tiny slice of the
gameplay surface. Perf neutral.

---

## Rust port — warp end-step exile is a PHASE_END_STEP-entry sweep, NOT a CR-603.7 delayed trigger (Phase 1, round-63; Phase 1.5, round-65; Phase 2 — Timeline Culler)

**Phase 2 (Timeline Culler) — the graveyard-warp-cast permanent is
exiled by the SAME deterministic sweep.** Phase 2 admits Timeline
Culler (the life + graveyard-cast riders). A Timeline Culler
warp-cast from the GRAVEYARD (the new `cast_creature_warp` graveyard
fall-through) stamps `warp_exile_pending = true` on the just-arrived
permanent IDENTICALLY to the hand arm (Python schedules the SAME
`WarpExileSelf` for both branches — `actions.py:1550-1559` runs for
any `use_warp`), so the SAME deterministic PHASE_END_STEP-entry sweep
exiles it and it then becomes re-castable from EXILE at the NORMAL
`{B}{B}` cost (NOT re-warpable from the graveyard a second time — the
exile object is in the exile zone, not the graveyard, so it never
re-enters the graveyard-warp loop; the Phase-1 exile-recast path pays
`mana_cost` unchanged). **Phase 2 does NOT port the CR-603.7
delayed-trigger model** — the no-response-to-the-warp-exile claim
below is UNCHANGED: Timeline Culler carries `triggered_abilities=()`,
no LEAVES/DIES observer, and `attack_all` never holds priority at end
step, so the `WarpExileSelf`-as-stack-object response window is
unreachable for it (as for every Phase-1/1.5 card). The
delayed-trigger port remains the only Phase-3 follow-on and admits
**0 new cards** (it only changes the response-window semantics for a
scenario no EoE card reaches; correctness-completeness work, not
leverage work). The Phase-2 graveyard-warp lifecycle is pinned by
`tests/test_parity_smoke.py::
test_cross_engine_real_eoe_warp_phase2_timeline_culler_hand_then_graveyard_byte_equal`
+ the Rust regression pins in
`tests/test_cross_engine_etb_triggers.py` (the `test_r72_warp_phase2_*`
family).

**Phase 1.5 (round-65) — the safe-trigger+warp residue trio
admitted.** Phase 1's `_printing_is_bridge_pure_warp_creature`
guardrail was deliberately tightened to `triggered_abilities == ()`
to exclude **Germinating Wurm** ({1}{G} warp; ENTERS/IsSelf/GainLife
2), **Knight Luminary** ({1}{W} warp; ENTERS/IsSelf/CreateToken Human
Soldier 1/1), and **Starbreach Whale** ({1}{U} warp, Flying;
ENTERS/IsSelf/Surveil 2) — NOT because their trigger was wrong, but
because admitting them was a Phase-1-boundary expansion the round-62
scout had not cost/pinned and warp-cast was a NEW cast path the ETB
had never fired through. Phase 1.5 widens the guardrail's
`triggered_abilities == ()` hard-reject to a **safe-trigger gate**
(every TA must round-trip `_python_ta_to_safe_dict` — IDENTICAL to
`_printing_is_bridge_simple_creature`'s gate), threads
`triggered_abilities` through the CardDef warp arm, and admits
**exactly the +3 trio**. No Rust change: the landed Phase-1 substrate
fires the ETB generically — Rust's `cast_creature_warp` routes the
freshly-arrived permanent through the SAME
`move_from_hand_to_battlefield` → `drain_pending_etb_dispatches`
ENTERS dispatch as `cast_creature`, so the ETB fires byte-equal under
the warp-cast path. The §2 teeth are PRESERVED: Timeline Culler
(Phase-2 life/gy riders), Codecracker Hound / Mechanozoa (NON-safe
trigger), and **Quantum Riddler** ({1}{U} warp, safe ETB DrawCards 1
but a `HandSizeAtMost(1)` draw-replacement **static**) all stay
correctly DECLINED — the guardrail is NOT widened beyond the 3 (a
safe trigger is necessary but not sufficient; a static / non-safe gate
still declines). The ETB-fires-byte-equal-under-warp-cast assertion
(the load-bearing new pin) is pinned by
`tests/test_cross_engine_etb_triggers.py::
test_r65_warp_p15_trio_etb_fires_byte_equal_under_warp_cast` and the
genuine real-EoE probe
`tests/test_parity_smoke.py::
test_cross_engine_real_eoe_warp_phase15_trio_lifecycle_byte_equal`
(the actual parsed Germinating Wurm / Starbreach Whale printing
driven through warp-cast → ETB byte-equal → END-step exile →
normal-cost recast → ETB fires again byte-equal). The trio's triggers
are all `ENTERS` (not `LEAVES`/`DIES`), so the no-response-to-the-
warp-exile claim below is UNCHANGED — the ETB resolves at cast time,
not at the warp-exile.

**Location**:
`rust/src/state_ops_steps.rs::warp_exile_sweep_on_end_step`
(the new `PHASE_END_STEP`-entry hook wired in `advance_phase`,
mirroring the `PHASE_CLEANUP`-entry hook shape) +
`src/mtg_bot/parity/cross_engine.py::advance_phase_python`
(the harness mirror, `Step.END` branch).

**Shortcut**: Python schedules the warp permanent's exile as a
CR-603.7 **delayed triggered ability** (`WarpExileSelf` appended to
`state.delayed_triggers` at warp-cast time; fired by
`turn.run_delayed_end_step_triggers` (turn.py:773) which pushes it
onto the stack so players can respond before it resolves). Rust's
no-stack cast model has no `delayed_triggers` Vec and fuses
cast→resolve, so Phase 1 exiles every battlefield permanent the
active player controls with `warp_exile_pending` via a
**deterministic mutation on entry to PHASE_END_STEP** — no
stack-pushed trigger, no response window. The CardDef-bridge harness
primitive `advance_phase_python` mirrors the SAME deterministic
sweep (it deliberately restricts itself to Rust's `advance_phase`
composition, exactly as it inlines the CR-514 cleanup hooks rather
than calling `run_cleanup_step`).

**Why it's OK**: bit-equal end state for the bench's `attack_all`
strategy and the Phase-1 + Phase-1.5 card set. No card in the
bridge-admitted EoE pool responds to the warp-exile trigger: the two
Phase-1 cards (Red Tiger Mechan, Bygone Colossus) carry
`triggered_abilities=()`; the Phase-1.5 trio (Germinating Wurm,
Knight Luminary, Starbreach Whale) carry exactly one **`ENTERS`**
trigger each (GainLife / CreateToken / Surveil) which resolves at
**cast time** (under `move_from_hand_to_battlefield` →
`drain_pending_etb_dispatches`), NOT at the warp-exile — none is a
`LEAVES`/`DIES` observer, exile is not a graveyard transit (no DIES
per CR), and `trajectory._SAFE_TRIGGERS` has no
`leaves_battlefield` event. The bench's `attack_all` never holds
priority to cast an instant-speed response at the end step. The full
real Red Tiger Mechan / Bygone Colossus warp lifecycle (cast →
end-step exile → recast-from-exile) is asserted byte-equal across
both engines by the genuine real-EoE probe
`tests/test_parity_smoke.py::
test_cross_engine_real_eoe_warp_phase1_full_lifecycle_byte_equal`;
the Phase-1.5 trio's full lifecycle INCLUDING the ETB firing
byte-equal under BOTH the warp-cast and the normal-cost
exile-recast paths is asserted by
`tests/test_parity_smoke.py::
test_cross_engine_real_eoe_warp_phase15_trio_lifecycle_byte_equal`.

**Failure mode**: a future probe that puts an instant-speed spell
on the stack IN RESPONSE to the warp-exile trigger would see Python
allow the response window (the delayed trigger sits on the stack)
and Rust not (the sweep is an atomic phase-entry mutation). No such
card/scenario exists in the EoE pool's bridge-admitted set today.

**Fix scope**: port Python's `state.delayed_triggers` Vec +
`run_delayed_end_step_triggers` + a stack-pushed `WarpExileSelf`
analog to Rust (a larger follow-on; the cost-mechanic family's
later slices — Phase 2 Timeline Culler — may motivate it).

**Impact estimate**: Phase 1 = +2 cards / +6,450 17lands decks;
Phase 1.5 = **+3 cards** (Germinating Wurm, Knight Luminary,
Starbreach Whale) on top — all admitted with 0 strength cost (the
simplification is bit-equal for every bench-reachable state; the
trio's ETB fires byte-equal under the warp-cast path, pinned). Perf
neutral (one extra phase-entry scan gated on a cheap
`warp_exile_pending` any()-check that short-circuits when no
permanent is warp-pending; the trio adds no new Rust code path —
the ETB dispatch is the same generic
`drain_pending_etb_dispatches`).

---

## Bridge — Artifact-Creature type cosmetically dropped to Creature on both sides; + two pre-existing harness bugs Phase-1 exposed (round-63)

**Location**:
`src/mtg_bot/parity/trajectory.py::_printing_to_card_def`
(the Phase-1 pure-warp arm) +
`src/mtg_bot/parity/cross_engine.py::_dict_to_python_action`
(the `cast_spell` arm) +
`src/mtg_bot/parity/cross_engine.py::advance_phase_python`
(the `Step.END` branch).

**Shortcut 1 — Artifact-Creature → Creature symmetric drop.** Red
Tiger Mechan and Bygone Colossus are `('Artifact','Creature')`. The
CardDef warp arm sets `card_type='Creature'` with no
`extra_card_types`, dropping the Artifact type on BOTH engines
(symmetric — the round-59 non-basic-land symmetric-drop precedent;
bit-equal). Rust's `cast_creature` / `cast_creature_warp`
Creature-gate passes on `('Creature',)` alone. **Why OK**: no
warp/combat behavior keys off the Artifact type for these two
cards; the drop is symmetric so the per-object fingerprint is
byte-equal. **Failure mode**: a future artifact-count / affinity /
artifact-removal probe would undercount these two. **Fix scope**:
thread `extra_card_types=('Artifact',)` (the round-49 token-printing
substrate already supports the field). **Impact**: 0 today.

**Shortcut 2 — two PRE-EXISTING cross-engine-harness bugs Phase 1
is the first to exercise (fixed this slice, recorded for the
audit trail).** No pre-Phase-1 slice drove a non-default
`use_warp` cast or a warp-style delayed-end-step effect through the
`step_both` harness, so two latent harness gaps were dormant:
(a) `_dict_to_python_action`'s `cast_spell` arm passed ONLY
`card_id`, silently dropping the four alt-cost / mode flags Rust's
`parse_action` reads (`use_warp` / `kicked` / `cast_for_free` /
`use_impending` / `cast_room_half`) — a `use_warp=true` dict cast
at NORMAL cost on the Python side while Rust honored the flag;
(b) `advance_phase_python` (the harness phase mirror) did not
mirror Rust's new PHASE_END_STEP warp-exile sweep, so the Python
side kept the warp permanent on the battlefield while Rust exiled
it. Both are HARNESS-side bridge bugs, not production-engine
divergences (production Python's `apply_action` reads the real
`CastSpell` dataclass and `turn.run_delayed_end_step_triggers`
fires `WarpExileSelf` correctly). **Why recorded here**: per the
"document deliberate divergences / workarounds at the time they
land" rule — these were silent harness mistranslations that any
future non-default-flag or delayed-end-step cross-engine slice
would have hit; the fixes are general (all five flags threaded;
the END-step mirror added). **Failure mode if regressed**: every
`use_warp`/`kicked`/`impending`/room-half cross-engine cast would
silently cast at the wrong cost on the Python side. **Fix scope**:
done this slice. **Impact**: unblocks all future alt-cost
cross-engine driving; 0 production impact.

---

## Rust port — `Effect::DealDamageAnyTarget` optional-target empty-bf player-fallback divergence

**Location**:
`rust/src/state_ops_resolve.rs:3893-3979`
(`Effect::DealDamageAnyTarget` resolver),
`src/mtg_bot/effects/generic/damage.py:264-299`
(`DealDamageAnyTarget` Python class with `optional` flag),
`src/mtg_bot/parity/cross_engine.py:233-258`
(`_ta_dict_to_python_effect` `deal_damage_any_target` arm —
documents the `optional` flag's silent-drop on the Rust side and
the bounded equivalence on creature-on-bf scenarios).

Pinned by:
`tests/test_parity_smoke.py::test_cross_engine_real_eoe_pinnacle_kill_ship_etb_damage_optional_empty_bf_divergence_pin`
(the per-engine divergence assertion test landed in
`feature/phase5-ce-bridge-empty-bf-optional-damage-divergence`).

**What we do today**: Rust's `Effect::DealDamageAnyTarget` arm
performs a deterministic at-apply-time target pick: scan the
defender's bf for the first object whose `card_types` contains
"Creature"; if none, **fall back to defender-as-player and
subtract `amount` from defender life**. This fallback is
unconditional — the variant carries no `optional` field on the
Rust side, so even when the bridge dict carries `"optional":
true` the parser silently drops the flag (per the broader
`silent-drop convention; cross_engine.py:250-252) and Rust still
deals damage to defender-player on an empty defender bf.

Python's `DealDamageAnyTarget(optional=True)` flips
`count_min=0` on the targeting slot. With no agent seated (or
an agent that returns `None` from `choose_target`), the trigger
pushes onto the stack with an EMPTY `targets` tuple, and
`DealDamage.resolve` (damage.py:58) hits `if not targets: return`
— a silent fizzle. NO damage is dealt to anyone on Python.

**Why this diverges from CR**: CR 601.2c "up to one target" should
let the controller decline targeting altogether — Python's
behavior matches the rule. Rust's player-fallback is only
correct for the `optional=False` shape (CR 701.4 Lightning-Bolt-
style "any target"); folding the player-fallback into the
optional-shape via the same effect arm conflates the two
semantics.

**Failure mode**: silent damage to defender-player on Rust when
the source's controller would have declined the optional target
on Python. Pool-bounded: today the only EoE consumer of
`deal_damage_any_target` with `optional=True` is **Pinnacle
Kill-Ship** (per `docs/EOE_PROBE_READINESS_AUDIT.md`'s damage-
arm inventory). The rest of the consumers
(Nebula Dragon, Debris Field Crusher) carry `optional=False`,
where Python's `count_min=1` requires a chosen target and the
trigger fizzles altogether on an empty pool — different
divergence shape, not in scope of this entry.

**Cross-engine smoke surfacing**: pinned by the per-engine
assertion in
`test_cross_engine_real_eoe_pinnacle_kill_ship_etb_damage_optional_empty_bf_divergence_pin`.
The probe asserts Rust drops p1 life by 10 AND Python leaves
p1 life unchanged AND the two values are NOT equal. If the
Rust gap closes (or Python's silent-fizzle path changes), the
probe flags the regression immediately.

**Why it's OK for now**: the divergence is observable only on
the empty-defender-bf intersection of `optional=True`
deal-damage-any-target consumers. The single EoE consumer
(Pinnacle Kill-Ship) costs 7 mana and arrives mid-game when the
opponent typically has at least one creature on bf — the
empty-bf case is rare in practice. The bridge arm's docstring
already calls the gap out in code; this entry adds the doc
backstop and the regression pin.

**Fix scope when prioritized**: medium.
1. Add a new Rust effect variant
   `Effect::DealDamageToTargetCreatureOptional { amount: i32 }`
   (or extend `Effect::DealDamageAnyTarget` with an `optional:
   bool` field and gate the player-fallback on `!optional`).
2. The resolver fans out exactly the existing creature-scan
   loop but DROPS the `else` branch (no player-fallback;
   resolve to a no-op when no creature found).
3. Update `cards.rs::parse_effect` to thread the `optional`
   field into the variant rather than dropping it.
4. Update `cross_engine.py::_ta_dict_to_python_effect` to drop
   the "silent drop" comment block (the gap closes).
5. Flip the divergence-pin probe to a cross-engine parity
   assertion (both engines: p1 life unchanged on empty bf;
   delete the per-engine docstring's "this pin documents the
   gap" framing).
6. Remove THIS SEARCH_LIMITATIONS entry.

**Impact estimate**: bounded to the single `optional=True`
EoE consumer × empty-defender-bf scenarios — a tiny slice of
the gameplay surface. Strength cost is the rare case where the
bot's policy would prefer the silent-fizzle outcome (e.g.,
declining the optional target to avoid triggering an opponent's
"whenever a player loses life" shape) but Rust forces the
damage. Perf neutral.

---

## ~~Rust port — `Effect::EachOpponentSacrificesCreature` nontoken-filter shortcut~~ — CLOSED round 55

**Closed by** `feature/rust-token-cease-to-exist-sba-r55` (round-55
agent N2), shared-root with the token-cease-to-exist SBA (#15
`graveyard_p0` residual above). The Rust runtime gained
`RegistryData::is_token` (derived from the Round-30 `supertypes` Vec —
`"Token" in supertypes`, the SAME bit the cross-engine bridge already
round-trips for token printings via `("Token",)`). The
`Effect::EachOpponentSacrificesCreature` resolver
(`rust/src/state_ops_resolve.rs`) now gates its `bf.iter().find_map`
first-creature predicate on `!registry.is_token(...)` so it matches
the printed oracle text ("each opponent sacrifices a NONTOKEN
creature of their choice") and Python’s
`EachOpponentSacrificesCreature.resolve` `not o.printing.is_token`
legal-list filter. On a (token-at-index-0 ∧ nontoken-at-index-1+)
opponent bf both engines now sacrifice the first NONTOKEN identically.

**Pin flipped:**
`tests/test_parity_smoke.py::test_cross_engine_real_eoe_susurian_dirgecraft_etb_each_opp_sac_token_first_divergence_pin`
was flipped from a per-engine divergence pin to a cross-engine
PARITY assertion (both engines: token stays on bf, nontoken
sacrificed, p1 graveyard contents match cross-engine). The probe’s
Rust token dict gained `"supertypes": ["Token"]` so token-ness
round-trips (bridge-correctness, mirrors Python `make_token_creature`).

---

## Rust port — `Effect::PumpCreaturesOpponentsControlUntilCasterNextTurn` cleanup-gate divergence (Mouth of the Storm)

**Location**:
`rust/src/cards.rs` (variant declaration in the `Effect` enum
+ `parse_effect` arm + `effect_to_pydict` arm —
`PumpCreaturesOpponentsControlUntilCasterNextTurn`),
`rust/src/state_ops_resolve.rs` (resolve arm — pushes the SAME
`UeotModifier::PowerToughnessBonus` the bare-EOT sibling pushes
instead of a tagged-lifetime payload),
`rust/src/state.rs:188-226` (`UeotModifier` enum — implicitly
`expires_at = "cleanup"` per the doc-comment at `state.rs:182-187`),
`src/mtg_bot/effects/generic/pump.py:779-891`
(Python's `PumpCreaturesOpponentsControlUntilEOT` with the
`until_caster_next_turn=True` branch that routes through
`grant_pt_pump_until_player_next_turn` — layer-7c registry entry
tagged `expires_at="controller_untap"` /
`expires_at_player_id` = caster).

Pinned by:
`tests/test_parity_smoke.py::test_cross_engine_real_eoe_mouth_of_the_storm_etb_extended_duration_debuff_anthem_parity`
(real-EoE ETB probe — pins the SHARED post-resolve effective-P/T
agreement between the engines; explicitly out-of-scope: the
cross-turn cleanup-gate divergence) plus the four synthetic
regression pins at
`tests_rust/test_ueot.py::test_*pump_creatures_opponents_control_until_caster_next_turn*`.

**What we do today**: Rust's resolve arm for the new
`Effect::PumpCreaturesOpponentsControlUntilCasterNextTurn` variant
(Mouth-of-the-Storm sibling — "creatures your opponents control
get -3/-0 until your next turn") pushes the SAME
`UeotModifier::PowerToughnessBonus` payload the bare-EOT sibling
pushes. The `UeotModifier` enum is implicitly cleanup-step
expiration (drained wholesale by `clear_ueot_modifiers_all` /
`cleanup_step_for_active_player`); there's no per-modifier
lifetime tag yet. So Rust drops the debuff at the casting-turn
cleanup, while Python keeps it through the opponent's full
subsequent turn and only expires it at the start of the source-
controller's NEXT turn.

**Why this is wrong under current CR**: the printed oracle text
on Mouth of the Storm is "until YOUR NEXT TURN", not "until end
of turn". The duration is part of the rules text. Python honors
it via the `until_caster_next_turn=True` branch on the unified
Pump dataclass; Rust's first-slice resolve arm flattens both
durations onto the same cleanup-step lifetime and so terminates
the debuff one full opponent-turn early.

**Why we shipped substrate-only**: extending `UeotModifier` with
a tagged-lifetime field cascades through:
  * the four effective-P/T / effective-keyword readers in
    `rust/src/state.rs`;
  * the two cleanup primitives (`clear_ueot_modifiers_all` and
    `cleanup_step_for_active_player`) — both must learn to
    selectively drain by lifetime;
  * a new untap-step hook in `rust/src/state_ops_steps.rs` that
    expires "until your next turn" modifiers when the source-
    controller's untap step fires;
  * GameState-level bookkeeping for the per-modifier
    `expires_at_player_id` field (today the modifier is fully
    self-contained — adding a player-id forces the cleanup
    primitives to know who's untapping).

That cascade is well beyond a single per-EoE-card slice's budget
(estimated 60-100 LOC across 4 files + new test pins for each
reader). Per the established Option-B precedent (Rounds 12-15 —
Rescue Skiff / Seam Rip / Blooming Stinger), we ship the Effect
variant + bridge arm now so:
  1. Mouth of the Storm routes through the Python engine cleanly
     (the bridge translates Rust's discriminator to Python's
     `until_caster_next_turn=True`).
  2. The Rust-side discriminator is in place — the cleanup-gate
     follow-up slice swaps ONLY the `UeotModifier` push line in
     `state_ops_resolve.rs` for a tagged-lifetime payload; every
     parse arm, every effect_to_pydict round-trip, every test
     pin, every bridge call site already targets the right
     discriminator and won't need to change.

**Failure mode**: when Mouth of the Storm resolves on Rust, the
opponent's creatures lose their -3/-0 debuff at the casting
turn's cleanup. On Python they keep it through their full turn
and lose it at the controller's NEXT untap step. Strength gap:
Rust over-values the opponent's combat strength on the opponent's
following turn (incorrectly thinks the debuff is gone), Python
correctly keeps the debuff applied. The bot trained against Rust
self-play would under-value Mouth of the Storm relative to its
true CR-compliant strength, since the extended-duration upside
(an opponent attack-step where the debuff still applies) is
invisible.

**Cross-engine smoke surfacing**: the real-EoE Mouth of the
Storm probe exercises the post-resolve agreement (both engines
push the modifier; Bait Bears go from 2/2 to (-1)/2 effective
on both engines). The cross-turn divergence is explicitly
documented in the probe docstring and is NOT asserted (asserting
parity there would fail until the cleanup-gate slice lands).

**Why it's OK for now**: the divergence is observable only on
the (Mouth of the Storm in play ∧ at least one round-trip across
the casting-turn cleanup → opponent's turn) intersection. Mouth
of the Storm is a 7-mana uncommon — late-game tempo play, fires
once on entry; the divergent intersection is gameplay-real but
its window opens late and closes at the controller's untap. The
post-resolve substrate (modifier APPLIED, effective P/T pumped /
debuffed) is bit-identical between engines. The cross-engine
probe pins the agreement; the divergence note in the probe
docstring + this entry document the gap.

**Fix scope when prioritized**: medium.
1. Extend `rust/src/state.rs::UeotModifier` with a per-variant
   lifetime tag — either a sibling enum
   `UeotLifetime { Cleanup, UntilPlayerNextUntap { player_id: u8 } }`
   carried as a second field on each `UeotModifier::*`, or split
   the variants into Cleanup-vs-UntilPlayerNextUntap parallel
   families. Pick the variant-shape change that minimizes
   reader-side disruption (the four readers in `state.rs` and
   the two cleanup primitives all do exhaustive matches).
2. Update `clear_ueot_modifiers_all` and
   `cleanup_step_for_active_player` to drain ONLY the cleanup-
   tagged modifiers; survive the until-player-next-untap-tagged
   ones.
3. Add an untap-step hook in `rust/src/state_ops_steps.rs`'s
   `run_untap_step` that drains until-player-next-untap-tagged
   modifiers WHOSE `player_id` matches the active player.
4. Swap the `UeotModifier::PowerToughnessBonus` push in
   `state_ops_resolve.rs`'s
   `Effect::PumpCreaturesOpponentsControlUntilCasterNextTurn`
   resolve arm to the until-player-next-untap-tagged variant
   with `player_id = source_controller`.
5. Flip the cross-turn-divergence note in the probe docstring
   to a parity assertion: both engines, post-opponent-turn,
   debuff still applied; post-controller-untap, debuff cleared.
6. Remove THIS SEARCH_LIMITATIONS entry.

**Impact estimate**: bounded to (Mouth of the Storm + any future
"until your next turn" mass-debuff card) × (cross-cleanup-step
window). Strength cost: small per real-game encounter — Mouth of
the Storm is a one-off 7-mana ETB; the missing extended-duration
window is ~one combat-step's worth of mis-valuation per cast.
Perf cost on the fix: small — the cleanup primitives already
walk every battlefield object; selective drain is ~5 extra LOC
in the inner loop.

---

## Rust port — `Effect::TwoSubjectPumpAndDebuffByArtifactCount` deterministic targeting; real Monoist Circuit-Feeder NOT loader-admitted (round 51)

**Location**:
`rust/src/cards.rs` (variant declaration + `parse_effect` arm +
`effect_to_pydict` arm — `TwoSubjectPumpAndDebuffByArtifactCount`),
`rust/src/state_ops_resolve.rs` (resolve arm — deterministic
source-side + opponent-side first-creature scan, per-side
independent until-EOT `+X/+0` / `+0/-X` apply),
`src/mtg_bot/effects/generic/pump.py`
(`PumpYoursAndDebuffOpponentByArtifactCountUntilEOT` — the
deterministic-pick Python bridge sibling) AND
`PairedTargetPumpDebuffUEOT` (the AGENT-DRIVEN, two-required-target
class the real Monoist Circuit-Feeder printing parses to —
`src/mtg_bot/cards/parser/effects.py:3554-3563`),
`src/mtg_bot/parity/cross_engine.py` (bridge arm forwarding the
unit-variant dict to the deterministic sibling),
`src/mtg_bot/parity/trajectory.py` (the `_SAFE_*` allowlists this
slice deliberately does NOT extend).

Pinned by:
`tests/test_parity_smoke.py::test_rust_monoist_*` (6 synthetic Rust
regression pins),
`tests/test_cross_engine_etb_triggers.py::test_bridge_two_subject_pump_*`
/ `::test_rust_parser_accepts_two_subject_pump_debuff_*` /
`::test_bridge_two_subject_pump_debuff_synthetic_end_to_end_byte_equal`
(4 cross-engine bridge pins), and
`tests/test_parity_smoke.py::test_cross_engine_real_eoe_monoist_circuit_feeder_etb_two_subject_pump_debuff_by_artifact_count_parity`
(the GENUINE real-EoE probe — drives the actual parsed
`PairedTargetPumpDebuffUEOT` printing, shim-constrained).

**What we do today**: this slice ships the Monoist Circuit-Feeder
ETB Effect arm. Rust's resolve arm picks BOTH subjects
deterministically (first creature on the source-controller's bf,
first creature on the opponent's bf) and applies a per-side
independent until-EOT `+X/+0` / `+0/-X` (X = source-controller's
artifact count). The Python deterministic sibling
`PumpYoursAndDebuffOpponentByArtifactCountUntilEOT` mirrors that
shape so the cross-engine bridge round-trips byte-equal. This is
the exact `FightTargetCreatureWithTargetCreature` (deterministic
unit-variant) precedent.

**Deliberate divergence — the real card is NOT production-deck-
loader-admitted.** The real Monoist Circuit-Feeder printing parses
(faithfully) to the AGENT-DRIVEN, two-REQUIRED-target
`PairedTargetPumpDebuffUEOT`: the controller freely picks ANY legal
creature they control + ANY legal creature an opponent controls
(CR 601.2c — both required). Rust's effect (and the deterministic
Python bridge sibling) instead picks the FIRST creature on each
side with no decision callback. Adding Monoist to the
`trajectory.py` `_SAFE_*` allowlists would route the agent-driven
card through the deterministic bridge in production-deck mirror
games — silently degrading free agent target choice to a fixed
first-creature pick whenever either side has more than one
eligible creature.

**Why it's OK (and which scenarios make it not-OK).** This is the
SAME §2 bridge-correctness decision the round-17 Fight slice made:
the deterministic `FightTargetCreatureWithTargetCreature` sibling
is likewise NOT loader-admitted (the only real Fight consumer,
Meltstrider's Resolve, stays deferred). The Effect arm + bridge
arm + GENUINE real-EoE probe still close the real-card residue
*at the cross-engine-bridge level*: the actual parsed printing's
ETB now round-trips byte-equal cross-engine (the probe drives the
real `PairedTargetPumpDebuffUEOT` shim-constrained so the
two-target pick equals Rust's deterministic scan in the single-
creature-each scenario). The scenario where this would be wrong is
a production-deck mirror game where Monoist's controller has ≥2
own creatures or the opponent has ≥2 creatures and an agent would
rationally pick a non-first creature (e.g. pump the biggest
attacker, debuff the biggest blocker) — there the deterministic
bridge's first-creature pick is a strategy divergence, not just a
representational one. That is why the loader admit is declined
rather than forced.

**Failure mode**: none in production today (Monoist stays
drop-filtered by the loader, so it never enters a production-deck
mirror game through the bridge). If a future slice plumbs an
agent-driven two-target cross-engine decision substrate, Monoist
flips admit by adding a `_SAFE_*` entry that routes to the
agent-driven `PairedTargetPumpDebuffUEOT` on BOTH engines (Rust
would need a target-carrying variant + decision callback) — at
which point this deterministic arm becomes the synthetic-probe
substrate only (same trajectory as the Fight Aura follow-up).

**Fix scope estimate**: multi-round. Needs a cross-engine
agent-driven two-required-target decision substrate (Rust
target-carrying variant + per-slot decision callback + bridge
plumbing for the `(my_creature, creature)` slot-kind pair),
shared with the deferred Aura-attachment / Fight follow-ups.

**Impact estimate**: zero strength cost today (real card not
loader-admitted; no production exposure). Real-card-coverage
progress is the cross-engine-bridge closure (the genuine real-EoE
probe is byte-equal), not a production-deck admit. ~14,727 of
129,996 17lands EoE decks run Monoist Circuit-Feeder — the largest
single bridge-correct real-card residue closed this round.

---

## Rust port — `Effect::DestroyTargetNoncreaturePermanent` deterministic targeting; real Extinguisher Battleship NOT loader-admitted, Station-subsystem-gated (round 52)

**Location**:
`rust/src/cards.rs` (variant declaration + `parse_effect` arm +
`effect_to_pydict` arm — `DestroyTargetNoncreaturePermanent`),
`rust/src/state_ops_resolve.rs` (resolve arm — deterministic
first non-Creature, non-indestructible permanent in ETB-timestamp
order across BOTH battlefields, LTB-fanout cloned from the round-24
nonland arm),
`src/mtg_bot/effects/generic/destroy.py`
(`DestroyTargetNoncreaturePermanent` — the AGENT-DRIVEN
`requires_target()` real-card class the genuine Extinguisher
Battleship printing parses to; pre-existed this slice),
`src/mtg_bot/parity/cross_engine.py` (bridge arm forwarding the
unit-variant dict to that class),
`src/mtg_bot/parity/trajectory.py` (the `_SAFE_*` allowlists this
slice deliberately does NOT extend).

Pinned by:
`tests/test_parity_smoke.py::test_rust_extinguisher_*` (6 synthetic
Rust regression pins),
`tests/test_cross_engine_etb_triggers.py::test_bridge_destroy_target_noncreature_permanent_*`
/ `::test_rust_parser_accepts_extinguisher_sequence_in_triggered_ability`
/ `::test_bridge_extinguisher_sequence_synthetic_end_to_end_byte_equal`
(5 cross-engine bridge pins), and
`tests/test_parity_smoke.py::test_cross_engine_real_eoe_extinguisher_battleship_etb_destroy_noncreature_then_aoe_parity`
(the GENUINE real-EoE probe — drives the actual parsed
`Sequence{[DestroyTargetNoncreaturePermanent,
DealNDamageToEachCreature(4)]}` printing, shim-constrained).

**What we do today**: this slice ships the Extinguisher Battleship
ETB *effect half*. The real card parses to
`Sequence{[DestroyTargetNoncreaturePermanent,
DealNDamageToEachCreature(4)]}`. `damage_each_creature` (round 18)
and `sequence` (round 23) were already substrated + bridged; the
new work is the precise `Effect::DestroyTargetNoncreaturePermanent`
Rust variant (parse + to_dict + resolve) + its bridge arm. Rust's
resolve arm picks the destroy target deterministically (FIRST
non-Creature, non-indestructible permanent in ETB-timestamp order
across both battlefields). The full ETB Sequence now round-trips
byte-equal cross-engine (genuine probe asserts: bait noncreature
destroyed, every creature took exactly 4, carrier survives, lives
unchanged).

**Precise filter — NO `nonland≈noncreature` approximation taken.**
The round-50/51 plan offered two options: a ≈15-LOC precise
noncreature-filter Rust arm, OR a documented
`nonland≈noncreature-for-EoE-pool` approximation reusing the
pre-existing round-24 `DestroyTargetNonlandPermanent`
(`~IsLand()`) arm. **We took the precise fix.** The two filters
are genuinely NOT interchangeable: `~IsLand()` admits creatures +
excludes lands; `~IsCreature()` admits lands + excludes creatures —
on a mixed board they pick OPPOSITE candidates (the round-52 pins
`test_rust_extinguisher_creatures_are_not_destroy_targets` and
`test_rust_extinguisher_land_is_a_legal_noncreature_target` pin
both divergence directions). The genuinely-parsed Extinguisher
Battleship printing uses Python's `DestroyTargetNoncreaturePermanent`
(`~IsCreature() & ~IsPlayer()`), so approximating via the nonland
arm would have been a §2 silent target-set mistranslation, not an
exact-for-the-pool shortcut (it is NOT exact — EoE has noncreature
LANDS the nonland filter would wrongly skip and creatures it would
wrongly hit). There is therefore **no approximation entry to
document**: the filter is exact on both engines. (The only
remaining deterministic-vs-agent divergence is the target *choice*,
documented next — identical to the Monoist r51 / Fight r17
precedent.)

**Deliberate divergence — the real card is NOT production-deck-
loader-admitted; Station-subsystem-gated.** Two independent gates,
mirroring the round-51 Monoist split exactly:

1. *Agent-driven destroy target (deterministic-bridge divergence).*
   The real card's `DestroyTargetNoncreaturePermanent` is
   AGENT-DRIVEN (`requires_target() is True` — the controller picks
   ANY legal noncreature permanent, CR 601.2c). Rust's effect picks
   the FIRST one (ETB-timestamp order) with no decision callback.
   This is the SAME §2 decision the round-17 Fight /
   round-51 Monoist slices made: the genuine probe drives the real
   agent-driven Python class shim-constrained
   (`_PickFirstLegalTargetAgent` + a SINGLE staged legal target so
   the pick is forced byte-equal with Rust's deterministic scan).
2. *Station + Spacecraft subsystem (the card-level gate).* The full
   card is `[Artifact — Spacecraft] {8}` with a `Station` activated
   ability ("Tap another creature you control: Put charge counters
   equal to its power on this Spacecraft. Station only as a sorcery.
   It's an artifact creature at 5+.") and a tier line
   (`5+ | Flying, trample`). Neither `Station`, the `Spacecraft`
   artifact type, nor the charge-counter tier-threshold P/T/keyword
   grant is modeled on either engine. The production-deck loader's
   `_SAFE_*` allowlists do NOT admit Station/Spacecraft cards; this
   slice does NOT extend them. The Effect-half closure here is the
   ETB only — the Station subsystem is explicitly out of scope (a
   separate multi-round subsystem, shared with Warmaker Gunship and
   the other Spacecraft residue).

**Why it's OK (and which scenarios make it not-OK).** The Effect
arm + bridge arm + GENUINE real-EoE probe close the real-card
residue *at the cross-engine-bridge level*: the actual parsed
printing's full ETB Sequence now round-trips byte-equal. The
scenario where the deterministic bridge would be wrong is a
production-deck mirror game where the controller has ≥2 legal
noncreature permanents and an agent would rationally pick a
non-first one (e.g. destroy the opponent's best enchantment, not
their first-played mana rock) — there the first-noncreature pick is
a strategy divergence. That is why the loader admit is declined
rather than forced; and independently, the Station/Spacecraft
subsystem is unmodeled so the card cannot legally enter a
production-deck mirror game at all today.

**Failure mode**: none in production today (Extinguisher Battleship
stays drop-filtered by the loader on BOTH the agent-driven-destroy
gate AND the Station/Spacecraft gate, so it never enters a
production-deck mirror game through the bridge). If a future slice
plumbs (a) an agent-driven single-target cross-engine decision
substrate AND (b) the Station/Spacecraft subsystem, Extinguisher
Battleship flips admit; until then this deterministic arm is the
synthetic-probe + genuine-shim-constrained-probe substrate only
(same trajectory as the Fight / Monoist deterministic siblings).

**Fix scope estimate**: multi-round. The destroy-target-choice
substrate is the shared agent-driven cross-engine decision plumbing
(also gating Monoist, Fight-Aura). The Station/Spacecraft subsystem
(charge-counter accrual, sorcery-speed station activation,
tier-threshold becomes-artifact-creature + keyword grant) is its
own multi-round subsystem shared with Warmaker Gunship and the
remaining Spacecraft residue.

**Impact estimate**: zero strength cost today (real card not
loader-admitted on either gate; no production exposure). Real-card-
coverage progress is the cross-engine-bridge closure (the genuine
real-EoE probe is byte-equal). ~6,237 of 129,996 17lands EoE decks
run Extinguisher Battleship — the Effect-half residue closed this
round, loader-drop-filtered by design (Station-subsystem-gated,
same honest split as round-51 Monoist Circuit-Feeder).

---

## Rust port — round-31 `Effect::DoubleTargetCreaturesPowerUEOT` doubled BASE power on counter-bearing targets (real §2 silent mistranslation, FIXED round 53); Mightform Harmonizer still NOT loader-admitted (round 53)

**Location**:
`rust/src/state_ops_resolve.rs` (the round-31
`Effect::DoubleTargetCreaturesPowerUEOT` resolve arm — was
`read_battlefield_creature_power`, round-53 repointed to the NEW
private `read_doubling_power` helper in the same file),
`src/mtg_bot/effects/generic/pump.py:195`
(`DoubleTargetCreaturesPowerUEOT` — the AGENT-DRIVEN real-card class
the genuine Mightform Harmonizer printing parses to; the
source-of-truth `effective_power` snapshot at `pump.py:234`; pre-dates
this slice, unchanged),
`src/mtg_bot/parity/cross_engine.py` (the round-31
`double_target_creatures_power_ueot` bridge arm — unchanged),
`src/mtg_bot/parity/trajectory.py` (the `_SAFE_*` allowlists this
slice deliberately does NOT extend).

Pinned by:
`tests/test_parity_smoke.py::test_rust_mightform31_*` (5 Rust
regression pins incl. the §2
`..._doubles_effective_power_including_plus_one_counters` pin),
`tests/test_cross_engine_etb_triggers.py::test_bridge_double_target_creatures_power_ueot_synthetic_end_to_end_byte_equal`
+ `::test_bridge_double_target_creatures_power_reads_effective_power_with_counters_byte_equal`
(2 new cross-engine pins — the §2 counter-parity pin the original
round-31 translation-only bridge pins missed),
`tests/test_parity_smoke.py::test_cross_engine_real_eoe_mightform_harmonizer_landfall_double_power_with_counters_parity`
(the new GENUINE real-EoE counter probe — drives the actual parsed
Mightform landfall trigger against a +1/+1-counter target), AND the
pre-existing round-31/36
`::test_cross_engine_real_eoe_mightform_harmonizer_landfall_double_power_parity`
(counter-free genuine probe — confirms the fix is non-regressive on
the path it already covered).

**Round-50-plan-staleness correction (read this first).** The
round-50 `docs/RESIDUE_CARD_PLANS.md` entry #3 + the round-53 task
brief asserted Mightform Harmonizer's effect arm
(`Effect::DoubleTargetPowerUntilEOT`) was an UNSHIPPED new-Rust ask
("no Rust arm. Confirmed" — audit §round-19 line 504, §2.6 line 902).
**That was stale.** `Effect::DoubleTargetCreaturesPowerUEOT` shipped
Rust-end-to-end in **round 31** (commit 90bc39ca: variant + parse +
to_dict + resolve + 8 cross-engine bridge pins), and round 31/36
added a GENUINE real-EoE landfall+double-power probe. This is the
SAME staleness class the round-50 plan itself flagged for Mechanozoa
/ Warmaker Gunship; the audit's residue line was never re-checked
post-round-31. Implementing the round-53 slice surfaced this — and,
in doing so, surfaced a REAL latent bug in the shipped round-31 arm
(below). Per the §2 directive ("STOP, report, fix the side that's
wrong — Python is the source of truth"), the round-53 slice pivoted
from "add a duplicate variant" to "fix the round-31 arm's §2 bug +
pin the regression the original round-31 pins missed".

**The bug (FIXED round 53).** Python's source-of-truth
`DoubleTargetCreaturesPowerUEOT.resolve` (`pump.py:234`) snapshots
`snapshot = effective_power(state, obj)` =
`mtg_bot.game._compute_effective_pt`, which FOLDS IN the signed +1/+1
net at `game.py:2251`
(`p += obj.plus_one_counters - obj.minus_one_counters`). The round-31
Rust resolve arm snapshotted via `read_battlefield_creature_power`,
which DELIBERATELY OMITS `obj.counters` (a pinned combat-side
asymmetry — see the comment at `state_ops_combat.rs:551-556`). So on
a target carrying +1/+1 counters the two engines doubled DIFFERENT
power values: on a 3/3 with +2/+2 counters, pre-fix Rust snapshotted
`3` (printed base) and pushed `+3/+0`; Python snapshotted `5`
(effective) and pushed `+5/+0`. The doubling DELTA diverged (3 vs 5)
— a genuine, real-card-exposed §2 silent mistranslation. It stayed
LATENT because the round-31/36 genuine Mightform probe (and every
round-31 bridge pin) staged only counter-free creatures.

**The fix.** Round 53 added a private `read_doubling_power` helper
(`state_ops_resolve.rs`) that composes `base (UEOT-SetBasePT
override / manland / printed) + ueot_power_bonus() + obj.counters`
and repointed the round-31 resolve arm to it. `obj.counters` (signed
i32) is Rust's analogue of Python's `plus_one_counters -
minus_one_counters` (the SBA path at `state_ops_sba.rs:200` uses the
identical `base + obj.counters + ueot_*_bonus()` composition,
confirming the mapping). Post-fix the 3/3+2/+2 doubling delta is `5`
on BOTH engines (was `3` on Rust). The counter-free path is unchanged
(3/3 → 6/3) — the round-31/36 genuine probe still passes.

**Documented residual (the part NOT fixed — and why it's OK).** The
fix folds in +1/+1 counters but NOT layer-7c static anthems or
layer-7e P/T switches (`read_doubling_power` does not walk those, and
neither does the combat-side reader). Two reasons this is acceptable:
(1) no bridge-correct Mightform Harmonizer scenario reaches them —
the card has no anthem/switch rider and the genuine probes stage
none; (2) it matches the established combat-side asymmetry rather
than introducing a new divergence. Separately, Rust's PUBLIC
`effective_power`/`battlefield_creature_power` getter STILL omits
`obj.counters` from its displayed value (the pre-existing pinned
combat-side asymmetry — NOT changed by this slice). Consequence: on a
counter-bearing creature the absolute cross-engine
`effective_power` numbers differ by the counter amount (Rust 3→8,
Python 5→10 in the pin scenario) even though the DOUBLING is now
correct. The §2-load-bearing invariant the pins assert is therefore
the doubling DELTA (`effective_power_after - effective_power_before`),
which is byte-equal (+5) on both engines — NOT the absolute getter.
Closing the combat-side getter asymmetry is a separate, broader slice
(it touches the whole combat/SBA power-read surface, not just this
arm) and is out of scope here.

> **UPDATE (R74-1 / RUST_PARITY_GAPS I23, round-74 Rust slice
> `feature/rust-i23-combat-counters`).** The combat-side getter
> asymmetry referenced above as "a separate, broader slice … out of
> scope here" IS NOW CLOSED. `battlefield_creature_power` /
> `battlefield_creature_toughness` (and the public
> `effective_power` / `effective_toughness` getters that wrap them)
> now fold `obj.counters` byte-equal with Python's
> `_compute_effective_pt` (the round-74 bench sweep empirically
> demanded the documented I23 promotion — Biosynthic Burst). So the
> absolute cross-engine `effective_power` numbers now AGREE on a
> counter-bearing creature (the "Rust 3→8 vs Python 5→10" stale
> consequence above no longer holds — both are 5→10). The doubling
> DELTA invariant the round-53 pins assert is unaffected (still
> byte-equal). NOTE: `read_doubling_power` (this entry's helper) is
> an INDEPENDENT private re-derivation that already folded
> `obj.counters`; the R74-1 slice did not touch it — only the
> combat/SBA-shared `state_ops_combat.rs` readers. The Fight-arm
> `read_battlefield_creature_power` helper remains a distinct,
> still-open documented asymmetry (see its own §2 entry); R74-1 was
> scoped precisely to the bench-demonstrated combat-damage path.

**Deliberate divergence — Mightform Harmonizer is NOT
production-deck-loader-admitted.** Unchanged from the round-31/36
position; restated here for completeness. Two independent gates,
mirroring the round-51 Monoist / round-52 Extinguisher splits:

1. *Agent-driven target (deterministic-bridge divergence).* The real
   card's `DoubleTargetCreaturesPowerUEOT` is AGENT-DRIVEN
   (`requires_target() is True` — the controller picks ANY legal
   creature they control, CR 601.2c). Rust's resolve arm picks the
   FIRST creature on the source-controller's bf with no decision
   callback. Same §2 decision as round-17 Fight / round-51 Monoist:
   the genuine probes drive the real agent-driven class
   shim-constrained (`_PickFirstControlledCreatureAgent` + a single
   staged legal target so the pick is forced byte-equal with Rust's
   deterministic scan). Routing the agent-driven card through the
   deterministic bridge in the production-deck loader would silently
   degrade free target choice in multi-creature board states.
2. *Landfall `Predicate::Subject` substrate + `warp_cost`.* The full
   card's trigger is the landfall compound
   `And(Subject(IsLand()), Controlled(YOU))` on `Event.ENTERS`; the
   real printing also carries `Warp {2}{G}`. The landfall-predicate
   substrate is review-gated (`feature/etb-subject-substrate`); the
   `warp_cost` is a §2-declined cost-mechanic class. The
   production-deck loader's `_SAFE_*` allowlists do NOT admit either;
   this slice does NOT extend them.

**Why it's OK (and which scenarios make it not-OK).** The round-53
fix + the new §2 pins + the new genuine counter probe close the real
§2 mistranslation *at the cross-engine-bridge level*: the actual
parsed Mightform landfall effect now round-trips byte-equal
cross-engine on the doubling delta INCLUDING the counter-bearing
case. The scenario where the deterministic bridge would still be
wrong is a production-deck mirror game where the controller has ≥2
creatures and an agent would rationally pick a non-first one — that
strategy divergence is why the loader admit stays declined; and
independently the landfall-predicate + warp gates keep the card out
of production-deck mirror games entirely today.

**Failure mode**: none in production today (Mightform stays
drop-filtered by the loader on BOTH the agent-driven-target gate AND
the landfall-predicate/warp gate, so it never enters a
production-deck mirror game through the bridge). Pre-round-53 the §2
counter mistranslation was a latent real-card-exposed bug (it would
have surfaced the moment a counter-bearing Mightform target entered
any cross-engine comparison that exercised counters); round 53
closes it. If a future slice plumbs (a) an agent-driven single-target
cross-engine decision substrate AND (b) the landfall predicate
substrate AND (c) `warp_cost`, Mightform flips admit; until then the
deterministic arm is the synthetic-probe + genuine-shim-constrained-
probe substrate only (same trajectory as the Fight / Monoist /
Extinguisher deterministic siblings).

**Fix scope estimate**: the §2 counter bug is FIXED (this slice,
~15 LOC helper + 1-line repoint). The remaining loader-admit gates
are multi-round: the agent-driven single-target decision substrate
(shared with Monoist / Fight-Aura), the landfall `Predicate::Subject`
substrate (review-gated), and the `warp_cost` cost-mechanic. The
combat-side absolute-getter counter-omission asymmetry is a separate
broad slice.

**Impact estimate**: the §2 fix closes a real, real-card-exposed
silent mistranslation on Mightform Harmonizer (~5,759 of 129,996
17lands EoE decks) — zero production strength cost (card not
loader-admitted; the bug had no production exposure path *yet*, but
was a correctness landmine for any future counter-exercising
comparison). Real-card-coverage progress is the cross-engine-bridge
closure of the counter case (the genuine real-EoE counter probe is
byte-equal on the doubling delta), loader-drop-filtered by design.

---

## Rust port — `Effect::FamishedWorldsireLookTopXByPowerPutLandsTapped` deterministic greedy-all land selection; real Famished Worldsire NOT loader-admitted, Ward/Devour-gated (round 54)

**Location**:
`rust/src/cards.rs` (new `Effect::FamishedWorldsireLookTopXByPowerPutLandsTapped`
unit variant + `parse_effect` + `to_dict` arms),
`rust/src/state_ops_resolve.rs` (the new `resolve` arm + the private
`read_famished_source_power` helper — composes
`base + ueot_power_bonus() + obj.counters`, mirroring the round-53
`read_doubling_power` §2 effective-power precedent),
`src/mtg_bot/effects/bespoke.py:94`
(`FamishedWorldsireETBEffect` — the bespoke real-card class the
genuine Famished Worldsire printing parses to; pre-dates this slice,
unchanged — it is the source of truth),
`src/mtg_bot/parity/cross_engine.py` (the new
`famished_worldsire_look_top_x_by_power_put_lands_tapped` bridge arm),
`src/mtg_bot/parity/trajectory.py` (the `_SAFE_*` allowlists this
slice deliberately does NOT extend).

Pinned by:
`tests/test_cross_engine_etb_triggers.py` — 6 bridge/lockstep pins
(`test_bridge_famished_worldsire_*_basic_translation` /
`_extra_keys_ignored` / `_equality_default_constructor` /
`_composable_in_sequence`, `test_rust_parser_accepts_famished_worldsire_in_triggered_ability`,
`test_rust_parser_rejects_famished_worldsire_with_typo`) + 4 Rust
resolve regression pins (`test_rust_famished_worldsire_zero_power_silent_noop`,
`_greedy_all_lands_enter_tapped`, `_nonland_stays_no_shuffle`,
`_cross_controller_source_resolution`);
`tests/test_parity_smoke.py::test_cross_engine_real_eoe_famished_worldsire_etb_look_top_x_by_power_put_lands_tapped_parity`
(the GENUINE real-EoE byte-equal probe — drives the actual parsed
0/0 Famished Worldsire printing's bespoke ETB vs the Rust bridge-dict
unit-variant carrier, with +2/+2 counters so X=2 exercises the §2
counter-fold; deterministic, no RNG).

**Round-50-plan-staleness corrections (read this first).** Two
candidates were live-verified against the live 108-variant Rust
`Effect` enum + the live `_ta_dict_to_python_effect` bridge BEFORE
implementing (per the round-53 verify-first directive):

- **Pulsar Squadron Ace is ALREADY FULLY SHIPPED on both engines —
  a 5th confirmed-stale residue entry** (after Mechanozoa /
  Warmaker r51, Mightform r53). Its exact ETB ("look at the top five
  cards … you may reveal a Spacecraft card … put it into your hand
  … otherwise put a +1/+1 counter on this creature") is
  `Effect::LookAtTopNRevealOrCounter { n, filter_name, max_power,
  counter_on_miss }` (`cards.rs`, round-28/29 substrate; the doc
  comment literally names "Pulsar-Squadron-Ace + Living-Phone
  family"), with Python sibling
  `LookAtTopNRevealOrCounter(n=5, filter_name="spacecraft",
  counter_on_miss=True)` (`effects/generic/library_lookat.py:30` —
  defaults EXACTLY match the oracle), bridge-wired at
  `cross_engine.py:3467`. The round-50 plan's "PARTIAL — needs a
  Spacecraft sub-mode + bottom-random" label is **stale/wrong**: the
  `"spacecraft"` filter IS the sub-mode and it shipped round-28; the
  bridge comment already records the round-19 reclassification
  BLOCKED-RUST-EFFECT → shipped. NOT picked (nothing to do).
- **Famished Worldsire's Effect was GENUINELY UNSHIPPED in Rust**
  (verified absent from all 108 live `Effect` variants + unbridged),
  while the Python source-of-truth `FamishedWorldsireETBEffect`
  (`effects/bespoke.py:94`) already existed (parser literal at
  `cards/parser/effects.py:3724`). This was the real residue to
  close. Picked.

**What we do today**: this slice ships the
`Effect::FamishedWorldsireLookTopXByPowerPutLandsTapped` unit
variant + bridge arm so the real Famished Worldsire ETB round-trips
byte-equal cross-engine. The resolve arm mirrors the Python
source-of-truth step-for-step: source-controller resolution (CR
119.5/608.2 — "your library"), `X = read_famished_source_power` (base
+ UEOT + signed `obj.counters` — Famished is printed **0/0** so X
comes entirely from Devour-land +1/+1 counters; the §2 counter-fold
class the round-53 Mightform fix established), `X <= 0` silent
no-op, examine top `min(X, lib_len)`, greedy-remove every land
top-to-bottom → battlefield tapped + source-controller-stamped, fire
landfall per land top-to-bottom, non-land examined cards stay in
place, then shuffle the whole remaining library via the
`SearchLibraryForBasicLandTapped` external-rng/xorshift dual-path
(byte-identical to Python's `random.Random.shuffle`).

**Deliberate divergence #1 — greedy-all land selection (mirrors the
Python source of truth).** The oracle says "Put **any number** of
land cards … onto the battlefield tapped". Python's
`FamishedWorldsireETBEffect.resolve` (`bespoke.py:121`) deterministically
picks **ALL** land cards in the examined window (no decision
callback) — a documented "any number → greedy-land" simplification,
strictly ramp-positive (taking every available land is never worse
for the controller than taking fewer). The Rust arm mirrors this
greedy-all behavior exactly; **no `PendingDecision` is plumbed on
either engine**, so there is NO §2 silent-mistranslation surface
from the choice itself (both engines make the identical
deterministic choice). This is a strength approximation, not a
cross-engine divergence: a perfect agent could in principle decline
a land (e.g. to keep a specific card for a library-order interaction
that the subsequent shuffle would scramble anyway), but greedy-all
is the established Python behavior and the engines stay byte-equal.

**Deliberate divergence #2 — Famished Worldsire is NOT
production-deck-loader-admitted.** Mirroring the round-51 Monoist /
round-52 Extinguisher / round-53 Mightform Effect-half-closes /
full-card-stays-gated split. The real printing carries (verified
against `data/edge_of_eternities.json` + the parsed printing):

1. *`Ward {3}`* (`real.ward_cost == ManaCost(generic=3)`). `ward_cost`
   is a §2-declined feature class (HANDOFF §1/§2; the round-39
   ward/dynamic-pt decline precedent) — the production-deck loader's
   `_SAFE_*` allowlists do NOT model it; admitting Famished Worldsire
   would silently drop the Ward tax (a §2 silent mistranslation).
2. *`Devour land 3`* (an as-enters replacement: "you may sacrifice
   any number of lands; it enters with three times that many +1/+1
   counters"). Devour is its own enters-replacement subsystem the
   loader does not model; without it the real card's power (and thus
   X) is 0. The genuine probe seeds the counters directly (Rust
   `set_counters`; Python `plus_one_counters`) to exercise the
   downstream ETB at a realistic X, exactly as the round-53 Mightform
   probe seeds counters to exercise the §2 path.

This slice does NOT extend the `_SAFE_*` allowlists; the
loader-admit is declined.

**Why it's OK (and which scenarios make it not-OK).** The Effect
arm + bridge arm + genuine real-EoE probe close the real card's ETB
*at the cross-engine-bridge level*: the actual parsed
`FamishedWorldsireETBEffect` now round-trips byte-equal cross-engine
INCLUDING the §2 counter-fold (the probe stages a 0/0 + 2 counters,
asserts byte-equal library + battlefield). The scenarios that make
the loader-admit not-OK are exactly the two gates above: a
production-deck mirror game would need the Ward tax modeled (cost
mechanic) AND the Devour as-enters replacement modeled — until both
land, the card stays out of production-deck mirror games entirely.
The greedy-all land choice is a shared deterministic approximation
(byte-equal across engines, strength-only), not a divergence.

**Failure mode**: none in production today (Famished Worldsire stays
drop-filtered by the loader on the Ward gate AND the Devour gate, so
it never enters a production-deck mirror game through the bridge). No
latent §2 bug: the counter-fold is handled correctly by
`read_famished_source_power` from the outset (the round-53 Mightform
lesson was applied proactively here — a base-power read would have
been the same class of latent bug, avoided by mirroring the Python
`effective_power` composition in the helper from the start).

**Documented residual (same combat-side asymmetry as round 53).**
`read_famished_source_power` folds in `obj.counters` but NOT
layer-7c static anthems / layer-7e P/T switches (same established
combat-side / round-53 `read_doubling_power` asymmetry). No
bridge-correct Famished Worldsire scenario reaches them — the card
has no anthem/switch rider and the genuine probe stages none. The
xorshift fallback shuffle (when no external Python rng is installed)
uses a deterministic `(turn, active_player, source_obj_id,
library_len)` seed — identical convention to
`SearchLibraryForBasicLandTapped`; the genuine probe is sized to a
<2-card post-resolve library so neither engine shuffles, sidestepping
the rng-path entirely (Python's unconditional 1-card
`random.Random.shuffle` is also a no-op).

**Fix scope estimate**: the Effect-half is CLOSED (this slice — unit
variant + parse/to_dict/resolve + bridge arm + helper, ~3 commits).
The remaining loader-admit gates are multi-round: the `ward_cost`
cost-mechanic (§2-declined class, shared with Mechanozoa et al.) and
the Devour-land as-enters-replacement subsystem (sacrifice-any-number
+ counter-scaling enters replacement). Neither is in scope here.

**Impact estimate**: zero production strength cost (real card not
loader-admitted on either gate; no production exposure path).
Real-card-coverage progress is the cross-engine-bridge closure (the
genuine real-EoE probe is byte-equal on library + battlefield
state, INCLUDING the §2 counter-fold). ~2,324 of 129,996 17lands EoE
decks run Famished Worldsire — the Effect-half residue closed this
round, loader-drop-filtered by design (Ward/Devour-gated, same honest
split as round-51 Monoist / round-52 Extinguisher / round-53
Mightform).

---

## [CLOSED round 56] Rust port — `card_matches_filter` `"spacecraft"` arm checked `card_types` instead of `subtypes`; real Pulsar Squadron Ace reveal-path mistranslation (round-55 find, round-56 Rust-lane fix)

**STATUS: CLOSED (round 56, N1 / sole-Rust agent).** The one-line
predicate swap landed: `card_matches_filter`'s `"spacecraft"` arm now
reads `printing.subtypes.iter().any(|s| s == "Spacecraft")` (matching
Python's `is_spacecraft` and the existing `or_spacecraft` family). The
round-55 N3 genuine real-EoE divergence-pin
(`...reveal_real_spacecraft_card_types_vs_subtypes_divergence_pin`)
was **FLIPPED** from per-engine expected-divergent to a byte-equal
cross-engine parity assertion (both engines: real `Artifact —
Spacecraft` revealed to hand; library empty; Pulsar 0 counters; lives
20) and passes; the byte-equal half-probe
(`...look_top_5_no_spacecraft_counter_on_miss_parity`) still passes.
§2 consumer check: `card_matches_filter` is a private helper with
exactly two call sites, both inside the `LookAtTopNRevealOrCounter`
submit / auto-resolve path; **no other consumer depended on the buggy
`card_types` behavior** (the independent `or_spacecraft` family
already read `subtypes` correctly) — no latent buggy consumer found,
no half-fix. Pulsar's `BLOCKED-PROBE` residual is **discharged**
(reported to the orchestrator for N2's `residue_worklist.json` fold).
Probe-driver note recorded below (the inline `keep_all_on_top`
auto-drain in `resolve_top_of_stack`). The historical analysis is
retained below for provenance.

---

**Location**: `rust/src/state_ops_decisions.rs:663-698`
(`card_matches_filter`, the private helper consumed by
`Effect::LookAtTopNRevealOrCounter`'s submit /
`auto_resolve_pending_decisions` reveal paths). Specifically the
`"spacecraft"` match arm at `state_ops_decisions.rs:674-680`:

```rust
"spacecraft" => {
    printing.card_types.iter().any(|t| t == "Spacecraft")
}
```

**What the shortcut is**: the `"spacecraft"` filter recognizes a
card by checking its **`card_types`** for `"Spacecraft"`. Real EoE
Spacecraft cards are typed **`Artifact — Spacecraft`**:
`card_types == ("Artifact",)`, `subtypes == ("Spacecraft",)`
(Spacecraft is an artifact SUBTYPE, not a card type — verified
against `data/edge_of_eternities.json`: Lumen-Class Frigate, Rescue
Skiff, Wedgelight Rammer, The Seriema, …). So `card_matches_filter`
returns `false` for every real Spacecraft card. Python's source of
truth — `LookAtTopNRevealOrCounter._matches`
(`src/mtg_bot/effects/generic/library_lookat.py:62-65`) →
`printing.is_spacecraft` → `"Spacecraft" in printing.subtypes` —
returns `true`. The helper's own docstring
(`state_ops_decisions.rs:651-662`) self-documents the `card_types`
check as a first-slice approximation ("Rust printings don't yet
track subtypes"); that premise is **stale** — `CardPrinting.subtypes`
exists on the Rust side and the campaign's own `or_spacecraft`
filter family already reads
`printing.subtypes.iter().any(|s| s == "Spacecraft")` correctly
(`rust/src/cards.rs:2014-2027`). `card_matches_filter`'s
`"spacecraft"` arm is simply out of step with that convention.

**Why it's not-OK / failure mode**: this is a genuine cross-engine
**byte-divergence on the real Pulsar Squadron Ace printing's reveal
arm** (Pulsar's whole purpose is to find a Spacecraft). On a real
Spacecraft among the looked-at cards:

- **Python (correct)**: reveals the Spacecraft to hand; because a
  card WAS put into hand, the `counter_on_miss` rider does NOT fire.
- **Rust (wrong)**: `card_matches_filter` rejects the real
  Spacecraft → `reveal_yes` finds no match → falls to the no-reveal
  branch → the Spacecraft stays in the library AND a +1/+1 counter
  is wrongly placed on Pulsar. An explicit
  `submit_look_at_top_n_decision(True, <spacecraft id>)` is rejected
  transactionally with
  `ValueError: chosen card … does not match filter "spacecraft"`.

This was never caught because every prior "closure" of the
`LookAtTopNRevealOrCounter` family used a SYNTHETIC Spacecraft
carrier typed `card_types=["Spacecraft"]` (which coincidentally
satisfies the stale check). Pulsar's `BLOCKED-PROBE` residual
(residue_worklist.json) is therefore **NOT discharged** — the
genuine real-EoE reveal path is mistranslated. The no-reveal /
counter-on-miss half IS byte-equal (verified — see pin below).

**Fix scope estimate**: a one-line predicate swap inside the
existing private `card_matches_filter` helper —
`printing.card_types.iter().any(|t| t == "Spacecraft")` →
`printing.subtypes.iter().any(|s| s == "Spacecraft")` — matching
Python's `is_spacecraft` and the existing `or_spacecraft` family.
No new `Effect` / variant / `PendingDecision` / bridge arm needed
(the Effect substrate, the Python class, and the bridge arm are all
already correct). Round-56 Rust-lane (N2 / sole-Rust agent); a
`.pyd` rebuild is required because it touches Rust. After the fix,
flip the divergence-pin probe (below) to a cross-engine parity
assertion (both engines: Spacecraft to hand; library empty; Pulsar
0 counters).

**Impact estimate**: zero production strength cost (Pulsar Squadron
Ace is not on the production-deck loader's `_SAFE_*` allowlists
today; no production exposure path). The real-card-coverage progress
is the *honest pinning* of the gap so round-56 closes it cleanly
instead of a synthetic-substrate false-closure. ~5,400 17lands EoE
decks run Pulsar Squadron Ace.

**Pinned by**:
`tests/test_parity_smoke.py::test_cross_engine_real_eoe_pulsar_squadron_ace_etb_reveal_real_spacecraft_card_types_vs_subtypes_divergence_pin`
(the GENUINE real-EoE divergence-pin — drives the actual parsed
Pulsar printing's reveal arm against a real-shaped
`Artifact — Spacecraft` card; per-engine expected-divergent
assertions, GREEN today, flips to parity when round-56 lands) and
the byte-equal half
`tests/test_parity_smoke.py::test_cross_engine_real_eoe_pulsar_squadron_ace_etb_look_top_5_no_spacecraft_counter_on_miss_parity`
(proves the look-N / no-reveal / counter-on-miss / library-order
behavior round-trips byte-equal on the real printing — sized to a
1-card library so the "bottom the rest in a random order" rider is
a no-op on both engines, no rng). Picker shim
`tests/parity/_picker_shims.py::_PickFirstLibraryOptionAgent`
(mirrors Rust's `reveal_yes` first-filter-match strategy on the
Python side).

---

## Rust port — `resolve_top_of_stack` auto-drains trigger-queued decisions inline with the `"keep_all_on_top"` strategy (never `"reveal_yes"`)

**Location**: `rust/src/state_ops_resolve.rs` `resolve_top_of_stack`
pymethod, the `StackItemKind::TriggeredAbility` branch
(`auto_resolve_pending(self, "keep_all_on_top")?;` after the trigger
effect applies + the slot is popped). The sibling
`resolve_top_of_stack_pause` deliberately omits this call.

**What the shortcut is**: when a triggered ability's effect queues a
`PendingDecision` (e.g. `Effect::LookAtTopNRevealOrCounter` pushing a
`LookAtTopNRevealOrCounterChoice`), `resolve_top_of_stack`
auto-resolves it *inline* with the fixed `"keep_all_on_top"`
strategy. For the reveal-or-counter choice that strategy maps to the
**no-reveal** arm (`do_reveal_attempt = matches!(strategy,
"reveal_yes")` is false), so a Pulsar-shaped ETB reveal trigger
resolved via `resolve_top_of_stack` ALWAYS takes the no-reveal /
counter-on-miss path regardless of what is in the library. This
mirrors Python's no-agent-seated fallback (the agent-seated check
`if options and p.agent is not None` guards the reveal), so it is the
correct default for a seatless drain.

**Why it's OK / failure mode**: it is the intended no-agent default
and matches Python bit-for-bit when no agent is seated. The failure
mode is purely a **probe-authoring trap**: a cross-engine probe that
wants to exercise the Rust reveal path must drain the trigger via
`resolve_top_of_stack_pause` (which leaves the decision on the queue)
and THEN call `auto_resolve_pending_decisions("reveal_yes")`. Driving
via the non-pause `resolve_top_of_stack` and then calling
`auto_resolve_pending_decisions("reveal_yes")` is a silent no-op (the
queue was already drained no-reveal). This is exactly why round-55
N3's genuine Pulsar divergence-pin could only ever observe Rust's
no-reveal arm — its Rust assertions were no-reveal-shaped — and why
the round-56 flip also swapped the probe's Rust driver to
`resolve_top_of_stack_pause`.

**Fix scope estimate**: none needed (correct default). Documented so
future reveal/scry/choose-mode cross-engine probes use the `_pause`
driver when they need to drive a non-default decision strategy.

**Impact estimate**: zero strength cost (intended seatless default,
Python-parity-correct). Documentation-only — prevents the
silent-no-op probe trap that masked the round-55 Pulsar find for one
round.

**Pinned by**:
`tests/test_parity_smoke.py::test_cross_engine_real_eoe_pulsar_squadron_ace_etb_reveal_real_spacecraft_card_types_vs_subtypes_divergence_pin`
(post-round-56 flip; uses `resolve_top_of_stack_pause` then
`auto_resolve_pending_decisions("reveal_yes")` — the correct driver
pattern for exercising a non-default Rust decision strategy).

---

## Cross-engine token-printing registry — module-global, two-axis safety (round-51 shape cache + round-57 per-game pid-map reset)

**Location**: `src/mtg_bot/parity/cross_engine.py`
(`_TOKEN_PRINTING_BY_PID` module-global pid→`CardPrinting` map;
`register_token_printing` identity-conflict guard at line ~259;
`_TOKEN_PRINTING_CACHE_BY_KEY` round-51 shape cache;
`cached_token_printing`; round-57
`_reset_token_printing_pid_map_for_seating_pass`) +
`src/mtg_bot/parity/trajectory.py` `_seat_token_printings`
(per-game seating call site; calls the round-57 reset at pass entry).

**What the shortcut is**: the `create_token` family bridge arms resolve
Rust's `token_printing_id: u32` to a Python `CardPrinting` via a
**module-global** map (not per-`GameState` — the bridge runs during
`build_python_state`'s printing materialization, before any state
object exists, so there is no per-game context the registry can key
on). A token's pid is its index in **that game's** `card_defs` union,
which varies by archetype AND seed. The map persisting process-wide
across an N-game bench sweep means a later game's pid can collide with
an earlier game's stale registration. The `register_token_printing`
identity-conflict guard (`existing is not py_printing` → `ValueError`)
exists to catch genuine probe collisions (two manual registrations for
DIFFERENT printings at one pid that coexist in one bridge resolution —
a real silent-divergence bug). Two complementary mechanisms keep the
loader path conflict-free on two orthogonal axes WITHOUT deleting that
guard:

- **Same-shape cross-game axis (round-51 N1)**:
  `cached_token_printing(card_def)` keys a `CardPrinting` by token
  SHAPE (name + types + P/T + subtypes/supertypes + keywords +
  triggered/activated-ability tuples), so the SAME logical token
  re-seated across games/seeds resolves to the SAME identity-stable
  object → a repeat `register_token_printing` is identity-idempotent,
  never a false conflict. Covers: one token shape, many games, shifting
  pid.
- **Cross-shape multi-archetype axis (round-57 N1, round-56 N3
  finding)**: `_reset_token_printing_pid_map_for_seating_pass()` clears
  ONLY the pid→printing map at every `_seat_token_printings` pass entry
  (the shape cache is deliberately NOT cleared, so the round-51
  guarantee is preserved). The pid map is a **per-game** artifact;
  resetting it restores that invariant so a DIFFERENT token shape
  (Lander) landing on a pid a prior game's DIFFERENT shape (Robot)
  occupied finds a clean slot instead of the stale-Robot conflict.
  Covers: two different shapes colliding on one pid across archetypes
  in one process (the exact round-56 N3 bench find).

**Why it's OK / failure mode**: within a single game,
`_seat_token_printings` writes the COMPLETE, correct pid→printing map
for that game's union AND rewrites every carrier trigger's
`token_printing_id` to those same pids in the SAME pass from the SAME
`token_pid_by_name` dict; the bridge runs only AFTER the pass
completes, reading a self-consistent map. No within-game lookup can hit
a stale entry (the only stale entries possible are from PRIOR games,
whose pids are either overwritten by this game's seating or never
referenced by this game's trigger dicts) — so the round-57 reset
introduces NO within-game silent mis-resolution. The identity-conflict
guard is UNCHANGED and still fires for genuine probe collisions (manual
`register_token_printing` pairs never route through the seating reset).
The NOT-OK scenario would be a non-loader caller manually registering
two different printings at one pid that DO coexist in one resolution —
that still raises, as intended. No real-card-exposed divergence: the
fix removes a hard blocker (raw multi-archetype bench sweeps of decks
carrying ≥2 distinct token shapes are now unblocked); resolution stays
byte-equal everywhere the path is reachable (round-56 validated 0
FAIL_DIVERGENCE across 210 games with the per-game-clear workaround;
the round-57 in-code reset makes that workaround unnecessary).

**Rejected alternatives** (round-56 N3's three candidates): (a) key the
guard on `(pid, current-game)` — the bridge has no game-identity token
it can see (runs before any state exists); would need new plumbing the
bridge does not carry, and is a STRUCTURAL non-starter, not just more
work; (c) overwrite-allow when the new printing is a different-shape
`cached_token_printing` — weakens the within-resolution
probe-collision detector and is strictly more complex than restoring
the per-game invariant the pid map is supposed to have. Option (b)
(chosen) is the minimal correct fix and the round-56 doc's
recommended approach.

**Fix scope estimate**: closed (round-57 N1, ~25 lines + a dedicated
internal helper; sister of round-51 N1).

**Impact estimate**: zero production strength cost (parity
infrastructure only). Unblocks round-58+ raw multi-archetype bench
validation of any deck carrying ≥2 distinct token shapes (Lander +
Robot) without the per-game `clear_token_printings()` workaround.

**Pinned by**:
`tests/test_trajectory.py::test_r51_seat_token_printings_cross_game_varying_pid_no_conflict`
(round-51 same-shape axis, round-57-extended to assert cross-game
object identity independently of the now-per-game pid map) +
`..._r51_real_gravpack_archetype_multi_game_no_registry_conflict`
(round-51 e2e same-shape) +
`..._r57_unit_cross_shape_distinct_tokens_same_pid_no_conflict`
(round-57 cross-shape unit, no 17lands) +
`..._r57_real_cross_shape_multi_archetype_no_registry_conflict`
(round-57 cross-shape e2e — N3's exact `[(37,s) s0-5]+[(73,s) s0-5]`
order, both shapes resolve correctly per game). The three
collision-axis pins FAIL at the pre-fix baseline with the exact N3
`pid=7 … Robot … Lander` `ValueError`; all PASS with the fix.

---

## Dauntless Scrapbot — `ExileEachOpponentsGraveyard` Effect half shipped byte-equal; full card stays loader-gated (Lander token-registration / Sequence rider)

**Location**: `rust/src/cards.rs`
(`Effect::ExileEachOpponentsGraveyard` unit variant + parse / to_dict
arms) + `rust/src/state_ops_resolve.rs` (resolve arm) + bridge arm
`src/mtg_bot/parity/cross_engine.py` (`exile_each_opponents_graveyard`,
above the `PHASE5_BRIDGE_ARMS` sentinel). Python class
`ExileEachOpponentsGraveyard` (`src/mtg_bot/effects/generic/exile.py:260`)
+ parser recognizer `_EXILE_EACH_OPPONENTS_GRAVEYARD`
(`src/mtg_bot/cards/parser/effects.py:933`).

**What the shortcut is**: Dauntless Scrapbot (~18,378 17lands decks)
prints "When this creature enters, exile each opponent's graveyard.
Create a Lander token. (…)". The genuine parsed printing's ETB is a
`Sequence([ExileEachOpponentsGraveyard(), CreateToken(Lander)])`.
Round 56 shipped the **first Sequence leaf** end-to-end byte-equal on
both engines (Rust `Effect::ExileEachOpponentsGraveyard`, a structural
twin of `Effect::EachOpponentMillsCards`: same source-controller
finder + 2-player opponent loop; inner op is the opponent's whole
graveyard → that opponent's own exile zone, CR 406 / 400.7). The
**second Sequence leaf**, `CreateToken(Lander)`, is **NOT** closed:
the cross-engine `create_token` bridge raises unless a Python
`CardPrinting` is pre-registered for the Rust `token_printing_id`
(`register_token_printing`), and the production-deck loader's
`_SAFE_*` allowlists do not model the Lander token-creation /
Sequence-rider feature class. The full Dauntless Scrapbot card is
therefore **NOT added to the production-deck loader allowlist** (no
loader admit) — only the bridge/probe-level Effect half closes.

**Why it's OK / failure mode**: this is the honest
Effect-half-closes / full-card-stays-gated split established by r51
(Monoist), r52 (Extinguisher), r53 (Mightform), r54 (Famished
Worldsire). The closed exile half round-trips byte-equal (genuine
real-EoE probe drives the ACTUAL parsed printing's ETB Sequence first
arm cross-engine and asserts byte-equality on the exile-half
observable: opponent graveyard emptied → opponent exile, in graveyard
order; controller's own graveyard untouched; lives unchanged). The
NOT-OK scenario is admitting the full card to the bench loader, which
would silently drop the Lander Sequence leaf (a §2
silent-mistranslation) — explicitly declined. No real-card-exposed
divergence (the card is not on any `_SAFE_*` allowlist; no production
path drives it today).

**Fix scope estimate**: the remaining half needs the token-
registration substrate for `create_token` rider variants (the
round-49 N1 token-registration lane) + Sequence-rider bridging — a
multi-round subsystem, deferred. The Effect half is complete.

**Impact estimate**: zero production strength cost (Dauntless
Scrapbot not on the loader allowlist; no production exposure). The
real-card-coverage progress is the honest closure of the closeable
Effect half + honest pinning of the loader-gated remainder.

**Pinned by**: 4 cross-engine bridge pins
(`tests/test_cross_engine_etb_triggers.py::test_bridge_exile_each_opponents_graveyard_translates_to_python`
+ `..._etb_resolve_parity` + `..._controllers_own_gy_untouched` +
`..._empty_gy_noop`); 5 Rust regression pins
(`tests/test_parity_smoke.py::test_r56_rust_exile_each_opponents_graveyard_*`);
1 genuine real-EoE cross-engine probe
(`tests/test_parity_smoke.py::test_cross_engine_real_eoe_dauntless_scrapbot_etb_exile_each_opponents_graveyard_parity`
— drives the actual parsed Dauntless Scrapbot printing's ETB Sequence
first arm; byte-equal on the exile-half observable, Lander leaf
intentionally NOT cross-asserted).

---

## Faller's Faithful — `DestroyTargetCreatureThenDrawIfUndamaged` Effect half shipped byte-equal; full card stays loader-gated (damaged-this-turn ledger)

**Location**: `rust/src/cards.rs`
(`Effect::DestroyTargetCreatureThenDrawIfUndamaged { draw_amount: i32 }`
variant + `parse_effect` arm `destroy_target_creature_then_draw_if_undamaged`
+ `effect_to_pydict` arm) + `rust/src/state_ops_resolve.rs`
(module-private helper
`destroy_first_defender_creature_then_draw_if_undamaged` + the resolve
match arm). Bridge arm
`src/mtg_bot/parity/cross_engine.py`
(`destroy_target_creature_then_draw_if_undamaged`, immediately above
the `PHASE5_BRIDGE_ARMS` sentinel). Python class (pre-existing, NOT
new): `DestroyTargetCreature`
(`src/mtg_bot/effects/generic/destroy.py:94`) — the exact class the
genuine Faller's Faithful printing already parses to.

**What the shortcut is**: Faller's Faithful (~14,108 17lands decks)
prints "When this creature enters, destroy up to one other target
creature. If that creature wasn't dealt damage this turn, its
controller draws two cards." The genuine parsed printing's ETB is
`DestroyTargetCreature(draw_if_undamaged_amount=2, optional=True,
exclude_self=True)`. Round 57 shipped the destroy-then-conditional-draw
Effect end-to-end: the Rust resolve helper is a structural sibling of
the `DestroyTarget { AnyCreature }` arm (same `defender = 1 -
controller` bf[0] first-slice deterministic target pick, same
indestructible-suppress gate CR 702.12, same zone-change reset CR
400.7, same Void LTB nonland flag, same LTB fan-out via
`pending_leaves_dispatches` + `queue_token_cease`), plus a pre-destroy
"was undamaged" snapshot and a post-destroy conditional draw to the
**destroyed creature's controller** (CR 121.1 — the printed text gives
the draw to the victim's controller, NOT the spell's controller). The
**deliberate divergence**: the "wasn't dealt damage this turn" check
reads **`obj.damage == 0`** on the Rust side — Rust's per-object
marked-damage field — whereas Python maintains a dedicated per-object
`damaged_this_turn` boolean (`effects/base.py:300`,
`effects/generic/damage.py:1175`, cleared on zone moves). The two
reads are **byte-equal for the realistic Faller's Faithful ETB**
(instant-speed destroy with no prior damage marked on the target this
turn: no marked damage ⇔ `not damaged_this_turn`). They **diverge in
exactly one corner**: a creature damaged *then healed to 0* (or whose
marked damage was otherwise cleared) within the same turn — Python's
`damaged_this_turn` stays `True` (no draw) while Rust's `obj.damage`
reads 0 (would draw). The full general damaged-this-turn ledger is NOT
modeled on the Rust side; the **full Faller's Faithful card is NOT
added to the production-deck loader `_SAFE_*` allowlist** (no loader
admit) — only the bridge/probe-level Effect half closes.

**Why it's OK / which scenarios make it not-OK / failure mode**: this
is the honest Effect-half-closes / full-card-stays-gated split
established by r51 (Monoist), r52 (Extinguisher), r53 (Mightform), r54
(Famished Worldsire), r56 (Dauntless Scrapbot). The closed half
round-trips byte-equal — the genuine real-EoE probe drives the ACTUAL
parsed Faller's Faithful printing's ETB cross-engine and asserts
byte-equality on the full destroy-then-draw observable (victim →
opponent graveyard; the victim's controller draws 2; the spell
controller does NOT draw; lives unchanged) in the realistic
no-prior-damage scenario. The NOT-OK scenario is admitting the full
card to the bench loader, which would silently mistranslate the
damaged-then-healed-this-turn corner (a §2 silent-mistranslation:
Rust would draw where Python would not) — explicitly declined. No
real-card-exposed divergence (the card is not on any `_SAFE_*`
allowlist; no production path drives it today). Note the round-53
counter-fold lesson is honored: the destroy half reads the
*effective* board state (defender bf[0], indestructible from the live
printing keywords), and the undamaged snapshot is captured BEFORE the
destroy mutates anything (leaving the battlefield resets
`obj.damage` — mirrors Python's `was_undamaged` capture before
`destroy()` in `DestroyTargetCreature.resolve`).

**Fix scope estimate**: closing the remaining corner needs a
general per-object damaged-this-turn ledger on the Rust side (a
boolean set wherever damage is dealt, cleared on cleanup AND on
zone change, surviving a heal-to-0 — distinct from the existing
marked-damage `obj.damage` which clears at cleanup and on
heal-to-0) plus its bridge — a multi-round subsystem, deferred. The
Effect half (destroy + first-slice target + indestructible gate +
LTB fan-out + conditional victim-controller draw) is complete.

**Impact estimate**: zero production strength cost (Faller's Faithful
not on the loader allowlist; no production exposure). The
real-card-coverage progress is the honest closure of the closeable
Effect half + honest pinning of the loader-gated damaged-this-turn
remainder.

**Pinned by**: 4 cross-engine bridge pins
(`tests/test_cross_engine_etb_triggers.py::test_bridge_destroy_target_creature_then_draw_if_undamaged_translates`
+ `..._ff_destroy_then_draw_undamaged_parity` +
`..._ff_destroy_then_draw_predamaged_no_draw_parity` +
`..._ff_destroy_then_draw_zero_amount_parity`); 5 Rust regression pins
(`tests/test_parity_smoke.py::test_r57_rust_ff_*` — undamaged
destroys+draws-to-victim-controller; predamaged destroys-no-draw;
zero-draw-amount destroys-only; empty-defender-bf silent-fizzle
no-draw; indestructible-victim CR 702.12 suppressed no-draw); 1
genuine real-EoE cross-engine probe
(`tests/test_parity_smoke.py::test_cross_engine_real_eoe_fallers_faithful_etb_destroy_then_draw_if_undamaged_parity`
— drives the actual parsed Faller's Faithful printing's ETB
cross-engine; byte-equal on the destroy-then-draw observable in the
realistic no-prior-damage scenario; the damaged-then-healed corner
intentionally NOT cross-asserted).

---

## BECOMES_TAPPED event bridge SHIPPED (round 58) + landfall+put_plus_one_counter_on_self SHIPPED (round 59) — Seedship Agrarian FULLY CLOSED: both triggers byte-equal, whole card admittable

**Status**: this is NOT a divergence — it is a **closed campaign
landmine** that is now **FULLY RESOLVED** as of round 59. Round 58
bridged the BECOMES_TAPPED event (trigger-1) and narrowed Seedship's
residual to the orthogonal landfall+1/+1 leaf; **round 59 N1 closed
that sole remaining leaf** (`put_plus_one_counter_on_self` added to
the landfall safe set). Seedship Agrarian's WHOLE card is now
byte-equal-admittable — both triggers round-trip and a genuine
real-EoE probe drives the actual parsed printing through BOTH
triggers byte-equal. Documented here per the "document deliberate
scope boundaries at the time they land" rule; retained as a closed-
landmine narrative (no remaining scope boundary for this card).

**What shipped (round 58 N1).** `Event::BECOMES_TAPPED` is now a
fully-bridged cross-engine event, round-tripping the SAME way
ENTERS / DIES / ATTACKS do:

- **Rust** (`rust/src/cards.rs`): new `Event::BecomesTapped` enum
  variant + `"becomes_tapped"` parser arm; admitted in
  `state_ops_resolve::dispatch_event`. A centralized chokepoint
  `state_ops_resolve::tap_permanent_and_dispatch` (the Rust analogue
  of Python's `turn.tap_permanent`: flip + dispatch iff the state
  actually changed, no-op-if-already-tapped) is invoked at every
  production tap site that mirrors a Python `tap_permanent` caller:
  attack-tap (`state_ops_combat.rs` — placed BEFORE the per-attacker
  `Event::Attacks` dispatch so the stack-push order is byte-equal to
  Python's `combat.py:104` tap → `combat.py:115` ATTACKS), the
  `Effect::TapTarget` / `TapTargetArtifactOrCreature` /
  `TapEnchantedPermanent` / `TapAnotherTargetCreature` arms, and (via
  an inline dispatch where mana-credit / cost-pay ordering forces an
  already-committed flip) tap-for-mana (`state_ops_mana.rs`) and the
  `{T}` `tap_self` activated-ability cost (`state_ops_actions.rs`).
  `TapTargetOpponentPermanentAndStunIt` snapshots `was_tapped` and
  dispatches conditionally (Python adds the stun counter
  UNCONDITIONALLY but fires BECOMES_TAPPED only on the
  untapped→tapped transition, tap.py:237-256).
- **Bridge** (`src/mtg_bot/parity/cross_engine.py`):
  `_ta_dict_to_python_triggered_ability` maps `"becomes_tapped"` →
  `Event.BECOMES_TAPPED` (string passthrough, no Cast/IS_CAST-style
  spelling skew).
- **Loader** (`src/mtg_bot/parity/trajectory.py`):
  `("becomes_tapped","source_is_self","create_token")` added to
  `_SAFE_TRIGGERS`; the recognizer event-gate widened to admit
  `Event.BECOMES_TAPPED` with a dedicated narrow leaf set
  (`create_token` only).

**Firing-set parity (the §2 source of truth — CR 701.21a).** Python
fires `Event.BECOMES_TAPPED` ONLY through `turn.tap_permanent`
(`src/mtg_bot/turn.py:542-571`), the no-op-if-already-tapped
chokepoint, called from: tap-for-mana
(`actions.py:auto_tap_for_cost`), the `{T}` `tap_self` activated
cost (`actions.py:_activate_ability`),
`tap_permanent_you_control` activated cost, convoke, crew, attack-tap
of a non-vigilance attacker (`combat.py:104`, fired BEFORE the
per-attacker ATTACKS dispatch at `combat.py:115`), and the
tapper-effect family (`effects/generic/tap.py`,
`effects/combinators.py:163`, `effects/bespoke.py:496`). Python
deliberately does NOT fire it for permanents entering tapped
(`_play_land`'s `card.tapped = True`, search-land-tapped,
reanimate-tapped, token-created-tapped) nor for regeneration's
replacement tap (`turn.py:1268`) — those are direct
`obj.tapped = True` assignments, NOT `tap_permanent` calls (CR
701.21a: a permanent entering tapped never "becomes tapped"). Rust's
emission set matches this EXACTLY: the entering-tapped (Search
LibraryForBasicLandTapped, land-enters-tapped effect) and
regeneration / stun-only (`PutStunCounterOnTappedCreature`) Rust
sites stay raw `obj.tapped = true` with no dispatch.

**§2 scope: combinations admitted vs declined under BECOMES_TAPPED.**
- ADMIT: `source_is_self` (→ `IsSelf()`) + `create_token`
  (→ `CreateToken`) — the ONLY combo with a real EoE consumer
  (Seedship Agrarian) and both bridge arms are event-agnostic +
  already byte-equal-proven under ENTERS/DIES.
- DECLINE (no `_SAFE_TRIGGERS` entry; falls through the recognizer):
  * `IsHost()` predicate (Cryoshatter-shape "enchanted permanent
    becomes tapped", `enchantment_builder.py:497`) — Rust's predicate
    substrate has no `SourceIsHost` arm (only `SourceIsSelf`);
    admitting it would silently mistranslate the host relationship.
    Separate predicate-substrate slice.
  * Any non-`create_token` effect under BECOMES_TAPPED — no EoE
    consumer carries those today; admitting would be
    preventative-only and widen the bench-admit surface without a
    real signal source. Future slice ships the single new entry +
    one-line recognizer widen (same pattern as the
    ENTERS/DIES/ATTACKS leaf-set extensions).
  * Crew / `ActivateStation` and `tap_permanent_you_control` Rust
    tap: NO Rust tap-resolution substrate exists (`ActivateStation`
    raises not-implemented) — wiring an emission with no tap would
    be a divergent invention. Honest §2 decline; will be wired
    when/if the Rust crew/station substrate lands.

**Seedship Agrarian — FULLY CLOSED (round 59 N1).**
The `docs/residue_worklist.json` `SeedshipAgrarian-landfall-composer`
entry's `non_effect_blocker` was originally
*"Event.BECOMES_TAPPED unbridged (§2-declined, no cross_engine.py
bridge arm) + Lander token-registration substrate"*. Round 58
discharged the FIRST half entirely (BECOMES_TAPPED bridged) and a
verify-first re-walk showed the SECOND half was mis-stated (the
existing round-49/53 create_token + `_seat_token_printings`
machinery already handles the Lander token); the round-58 resync
narrowed the residual to the sole orthogonal trigger-2 leaf
`ENTERS / land_enters_controlled_by_you / PutPlusOneCounterOnSelf`
(`put_plus_one_counter_on_self` was NOT in the landfall safe-leaf
set: gain_life / pump_self_until_eot / draw_cards / mill).

**Round 59 N1 closes that sole remaining leaf.** Exactly the same
one-line-widen shape as the round-48 `landfall+mill` slice:
- `("enters","land_enters_controlled_by_you",
  "put_plus_one_counter_on_self")` added to `_SAFE_TRIGGERS`
  (`src/mtg_bot/parity/trajectory.py`).
- `_SAFE_EFFECT_KEYS` gains `"put_plus_one_counter_on_self" →
  {kind, amount}` (bare; mirrors Rust's
  `Effect::PutPlusOneCounterOnSelf { amount: i32 }` to_dict at
  `cards.rs:7179-7181` — the `amount` field name is IDENTICAL on
  both sides, NO rider the bridge drops).
- `_python_ta_to_safe_dict` recognizes `PutPlusOneCounterOnSelf` and
  widens the landfall `safe_effect_kinds` tuple to include it.

§2 bridge-correctness: `put_plus_one_counter_on_self` is event-
agnostic, has a live Rust variant + a wired bridge arm shipped
round-22 (`cross_engine.py:3899`), and was byte-equal-proven under
ATTACKS/ENTERS/DIES; the recipient is always the ability's source
("this creature") — no target picker, single in-place counter add,
no scalar/keyword/zone rider. It round-trips IDENTICALLY under the
landfall ENTERS-on-land predicate (the predicate axis is orthogonal
to the effect resolve — same predicate path round-36 gain_life /
round-37 pump_self / round-48 mill validated bit-equal).

**Both Seedship triggers now round-trip byte-equal → the WHOLE card
is byte-equal-admittable.** `_printing_is_bridge_simple_creature`
returns True for the genuine parsed printing; the production-deck
loader admits all copies + auto-seats both triggers + the Lander
token CardDef. A genuine real-EoE probe
(`tests/test_parity_smoke.py::test_cross_engine_real_eoe_seedship_agrarian_both_triggers_full_card_parity`)
drives the ACTUAL parsed printing through BOTH triggers
(trigger-1 tap→Lander; trigger-2 land-play→+1/+1 counter) and
asserts byte-equal whole-card cross-engine state (bf delta +3,
counter count == 1, effective P/T 4/4, Lander untapped controller-0,
life unchanged) up to the documented Lander token-registration
boundary. **For orchestrator fold:** `SeedshipAgrarian-landfall-
composer` moves from `blocked_non_effect` to **closed/admitted** —
both Effects shipped+bridged AND the card's blocking non-Effect
safe-leaf gap is now closed (the residual is fully discharged; there
is no remaining non-Effect gate).

**Pinned by**: 6 Rust regression pins
(`tests/test_cross_engine_etb_triggers.py::test_r58_becomes_tapped_*`
— fires on attack-tap; pushed-before-ATTACKS ordering; fires on
tap-for-mana; fires on TapTarget effect; does NOT fire on vigilance
attacker; does NOT fire on already-tapped re-tap); 3 cross-engine
bridge pins (`..._bridge_round_trips_source_is_self_draw` +
`..._bridge_round_trips_create_token` +
`..._safe_trigger_dict_admits_seedship_shape`); 1 genuine real-EoE
cross-engine probe
(`tests/test_parity_smoke.py::test_cross_engine_real_eoe_seedship_agrarian_becomes_tapped_create_lander_parity`
— drives the actual parsed Seedship Agrarian printing's BECOMES_TAPPED
trigger cross-engine; byte-equal on the Lander-spawn observable up to
the token-registration boundary). **Latent-bug pin inverted**
(round-39/53/56 precedent): the pre-existing
`tests/test_trajectory.py::test_phase3a_lander_cluster_residue_stays_declined`
asserted Seedship's Lander trigger must NOT round-trip — it was
pinning the bug (no bridge arm existed); now inverted to assert it
round-trips byte-equal with the full-card decline re-pointed to the
orthogonal landfall leaf.

**Round 59 N1 adds** (closing the landfall leaf): 9 trajectory-level
pins (`tests/test_trajectory.py` — `_SAFE_TRIGGERS` /
`_SAFE_EFFECT_KEYS` membership, `_is_safe_trigger_dict` admit +
reject [under-DIES / under-ENTERS+source_is_self / extra-payload-key],
`_python_ta_to_safe_dict` landfall round-trip + non-default-amount
fidelity, real-EoE Seedship Agrarian end-to-end filter-admit asserting
BOTH triggers round-trip → `_printing_is_bridge_simple_creature`
True, `_printing_to_card_def` both-triggers carry-through); 4
cross-engine bridge pins
(`tests/test_cross_engine_etb_triggers.py::test_bridge_ta_landfall_put_plus_one_counter_*`
— full triggered-ability round-trip of the landfall-composed
combination, genuine-parser byte-equality, amount-default-to-1,
non-default-amount preserved); 1 genuine real-EoE whole-card probe
(`tests/test_parity_smoke.py::test_cross_engine_real_eoe_seedship_agrarian_both_triggers_full_card_parity`
— drives the ACTUAL parsed printing through BOTH triggers byte-equal,
proving the whole card admittable; supersedes the round-58 trigger-1-
only probe in coverage scope, both retained).

---

## Tracked but not in this doc

Things tracked elsewhere that you might also want to know about:

- **PIMC's visit-aggregation bug** (workaround in writer-side filter,
  permanent fix is ISMCTS migration which is mostly done)
- **CoW `_fork_if_shared` historical issues** (fixed by the cleanup-
  step fork added in `feature/cast-not-castable-rootcause`)
- **Engine "hangs" turned out to be slow-tail games** (see
  `docs/hang_triage_2026_05_03.md`)
- **EventPattern.subject_filters originally not hashable** (fixed by
  `feature/event-pattern-hashable`)
- **belief-weighted determinizer needs trained policy to be useful**
  (shelved until model is trained enough — see worklog 2026-05-04)
- **Coverage gate at 95.10%** with main typically running 95.15-95.20%

---

## Rust port — `Effect::FightTargetCreatureWithTargetCreature` first-slice scope (Aura-shape Fight deferred)

**Location**:
`rust/src/cards.rs` (variant declaration + `parse_effect` arm +
`effect_to_pydict` arm — `FightTargetCreatureWithTargetCreature`),
`rust/src/state_ops_resolve.rs` (resolve arm — deterministic
caster-side + opponent-side first-creature scan, both fighters'
effective power computed BEFORE either deal_damage call per CR
701.12 simultaneous-damage event),
`src/mtg_bot/effects/generic/damage.py`
(Python `FightTargetCreatureWithTargetCreature` sibling — same
deterministic-pick shape),
`src/mtg_bot/parity/cross_engine.py` (bridge arm forwarding the
unit-variant dict shape),
`src/mtg_bot/effects/bespoke.py:507`
(`EnchantedCreatureFightsTargetEffect` — the Aura-shape sibling
this slice does NOT touch).

Pinned by:
`tests/test_parity_smoke.py::test_rust_fight_target_creature_*` (5
synthetic Rust regression pins) and
`tests/test_parity_smoke.py::test_cross_engine_fight_target_creature_synthetic_etb_parity`
(synthetic cross-engine ETB end-to-end probe).

**What we do today**: this slice ships the bare bilateral-fight
shape ("target creature you control fights target creature an
opponent controls", CR 701.12). Rust's resolve arm picks BOTH
fighters deterministically — first creature on the source-
controller's bf, first creature on the opponent's bf — and
applies the simultaneous damage exchange. The Python sibling
`FightTargetCreatureWithTargetCreature` mirrors that shape
exactly so the cross-engine bridge round-trips cleanly.

**What's NOT in this slice (deferred follow-ups)**:

  1. **Aura-shape Fight (Meltstrider's Resolve specifically).**
     The only EoE Fight consumer (`Meltstrider's Resolve`,
     `data/edge_of_eternities.json:25820`) is an Aura whose ETB
     reads "When this Aura enters, enchanted creature fights up to
     one target creature an opponent controls." The source-side
     fighter is the Aura's enchanted creature
     (`aura.attached_to`), NOT a player-chosen friendly creature
     from a generic bf scan. Python carries this shape on
     `EnchantedCreatureFightsTargetEffect` in `bespoke.py:507`;
     Rust has NO sibling variant today because the Aura ETB-
     trigger substrate doesn't yet route `attached_to` through
     to the resolve arm end-to-end (Rust's `attached_to` field
     exists on `GameObject` but only the cleanup path reads it —
     `state_ops_resolve.rs:977,1143,1235,1486,1656,1838,...`
     all set it to `None` on Aura-leaves; no resolve arm reads
     it as a target source). Adding the Aura-fight variant
     needs (a) a new `Effect::EnchantedCreatureFightsTarget`
     Rust variant, (b) a resolve arm that reads
     `state.players[*].battlefield[i].attached_to` to derive
     the source-side fighter, (c) a bridge arm forwarding to
     `EnchantedCreatureFightsTargetEffect`, AND (d) the
     end-to-end Aura-attachment substrate audit (whether
     `attached_to` is set correctly when an Aura enters bf via
     `register_and_inject_object` — currently unverified).

  2. **"Up to one target" optional-target shape.** Several Fight
     variants (Meltstrider's Resolve included) read "fights up to
     one target" — the spell can resolve with zero targets and
     not fizzle. Rust's first slice arm always fizzles silently
     when either fighter is missing, which observably collapses
     to the no-op the optional shape produces in the no-target
     case. Probes that would distinguish the two need a
     `requires_target` flag through the dict shape; deferred.

  3. **With-trample / with-deathtouch composers.** Cards like
     "fights and gains trample / deathtouch UEOT" compose via
     `Sequence` once the keyword-grant Effect arms are extended
     to fold into combat-style damage in the Rust arm (today's
     Fight arm uses `apply_damage_marker` directly; trample
     would need to spill excess to the defender's life total,
     which combat damage doesn't do — and the apply_damage_marker
     helper in this slice doesn't drive any of that).

  4. **"Fights twice" (rare).** Would need a counter or a
     duplicated Sequence of two FightTarget arms. No EoE
     consumer; deferred until one appears.

**Why it's OK (today)**:

  * The bare bilateral-fight shape ships for the substrate it
    enables (real future cards matching Pounce / Prey Upon /
    Rabid Bite oracle text drop in cleanly without further Rust
    changes; today's EoE pool happens to have zero of those, but
    the cards exist in adjacent sets and the Phase 6 trajectory
    pool may grow to include them).
  * Meltstrider's Resolve (the only EoE Aura-fight consumer)
    today routes through the Python engine end-to-end via the
    `EnchantedCreatureFightsTargetEffect` bespoke class. The
    cross-engine probe gap is observable — a probe that drives
    Meltstrider's Resolve cross-engine would diverge because
    Rust has no Aura-fight variant — but no probe today drives
    it (the audit doc acknowledges the gap).
  * The bridge dict shape `fight_target_creature_with_target_creature`
    is RESERVED for the bare bilateral form. The Aura-fight
    follow-up will add a SEPARATE
    `enchanted_creature_fights_target_creature` dict kind +
    Rust variant + bridge arm; the two shapes will not alias,
    and adding the Aura-fight slice will not require renaming
    or restructuring this slice's variant.

**Failure mode**:

  * Synthetic-only end-to-end coverage: the slice ships zero
    real-EoE consumers, so the trajectory-replay self-play sweep
    never exercises this arm in a real game today. A regression
    that subtly broke the resolve arm (e.g. swapped which side
    is caster vs opponent) would NOT show up in the parity gate
    until a real-EoE Aura-fight probe lands — when the Aura-shape
    follow-up ships, that probe transitively pins the bare-shape
    arm too because they share the same simultaneous-damage
    `apply_damage_marker` helper.
  * Cross-controller routing pin (`test_rust_fight_target_creature_cross_controller_routing_p1_source_on_p0_turn`)
    catches the most likely regression mode (reading active_player
    instead of scanning zones for source-controller); other
    regressions surface in the basic / asymmetric-power /
    missing-fighter pins.

**Fix scope estimate** (Aura-shape follow-up, the next slice):
medium — ~150-200 LOC of Rust (new variant + resolve arm reading
`attached_to` + parse / to_dict arms), ~50 LOC of Python (no new
class needed; `EnchantedCreatureFightsTargetEffect` already exists),
~30 LOC of bridge (one new arm in `cross_engine.py`), ~100 LOC of
tests (3-4 synthetic Rust regression pins + bridge translator pin
+ cross-engine end-to-end Meltstrider's Resolve real-EoE probe).
The Aura-attachment substrate audit (does
`register_and_inject_object` set `attached_to` correctly on
Aura-typed printings) is the unknown-cost prerequisite — could be
zero work (already correct) or a 100-LOC subsidiary slice if the
Aura-attachment path needs rework.

**Impact estimate**: zero today — no real-EoE consumer of the
bare shape and the only Aura-shape consumer (Meltstrider's
Resolve) routes through Python only, so neither self-play nor
trajectory-replay see the missing-Rust-variant divergence. When
the Aura-shape follow-up lands, the trajectory-replay sweep gains
parity coverage for Meltstrider's Resolve — currently the card is
implicitly excluded from cross-engine probes (the audit doc
flagged it BLOCKED-RUST-EFFECT and it stays blocked until that
slice ships).

---

## Combat — double-strike regular damage spills past dead blocker (no trample required) — RESOLVED

**Status**: RESOLVED on
`feature/rust-fix-double-strike-spillover` (commit `edf67e20`
Python; commit `3952d841` Rust). Round-18 entry kept here as a
historical record of the closure.

**Location**: combat damage resolution on both engines —
`src/mtg_bot/combat.py::_resolve_damage_step` and
`rust/src/state_ops_combat.rs::deal_combat_damage`.

**The bug** (round-18): when a double-strike attacker killed its
blocker in the first-strike substep, the regular-damage substep
treated the attacker as UNBLOCKED — its regular damage spilled to
the defending player. Per CR 510.1c, a blocked attacker stays
blocked even when all blockers leave the battlefield; only
**trample** (CR 702.19b) lets damage spill past dead blockers.
Both engines agreed byte-for-byte on the wrong answer.

**The fix**:
- Python: gate the unblocked-path branch on
  `was_blocked = len(attacker.blocked_by) > 0` instead of on the
  live `blockers` list. `attacker.blocked_by` is NOT cleared when
  individual blockers die (only when the attacker itself leaves
  combat), so it correctly records "was this attacker blocked at
  declare-blockers time". Trample still spills the remaining
  power when no live blockers absorbed it.
- Rust: gate the CE18 pass-2 "dead blocker → defender" redirect
  on `attacker_has_trample`. Without trample, the entry is
  dropped (assignment lands on the dead blocker as a no-op). With
  trample, the redirect remains so trample's spill semantics hold.

**Verification**:
- `tests/test_trajectory_parity.py::test_double_strike_combat_damage_doubles_parity`:
  expected `life_p1` flipped from `pre_combat_life_p1 - 2` (18)
  to `pre_combat_life_p1` (20). The byte-equal cross-engine
  assertion (`compare_fields == []`) still holds — both engines
  deliver the CR-correct value byte-for-byte.
- Existing 1059-test gate passes — no regressions on
  `test_parity_smoke` + `test_cross_engine_etb_triggers` +
  `test_trajectory_parity` + `test_trajectory`.

**Scope of the fix**: only the 1-attacker / 1-blocker / dead-
blocker case was explicitly probed. The same gate covers
N-blocker variants where ALL blockers die — `attacker.blocked_by`
remains non-empty even after every blocker is removed from the
battlefield. Trample remains the sole spillover keyword. First-
strike + trample combined preserves the existing trample-on-
first-strike spillover via the same gate (`attacker_has_trample`
TRUE → redirect on the FS pass too, when the trampler killed all
blockers).

---

## Python `Effect.Scry` first-slice keep-on-top deterministic shortcut

**Location**: `src/mtg_bot/effects/generic/library_lookat.py` (the new
`Scry` dataclass, sister to `Surveil`). Bridge arm at
`src/mtg_bot/parity/cross_engine.py` `_ta_dict_to_python_effect` under
`kind == "scry_n"`.

**What the shortcut is**: Python's new `Scry` primitive (and the Rust
`Effect::ScryN` resolve arm at `state_ops_resolve.rs:1777-1792` it
mirrors) implements the CR 701.18 scry as the deterministic
"keep all observed cards on top of the library in their original
order" branch — no decision callback for "which cards go to the
bottom". The library is not mutated; only the log is updated. CR
701.18d's "if there aren't enough cards in your library, look at
all the cards" clamp is honored silently (count clamps to library
size). Negative count raises loudly.

**Why it's OK today**: matches Rust's already-shipped first-slice
shortcut byte-for-byte, so the cross-engine bridge stays bit-equal
on observable state. The Rust side intentionally deferred the "which
to bottom" decision substrate to a future slice (analogous to how
Surveil queues a `PendingDecision::SurveilChoice` and calls
`auto_resolve_pending_decisions("keep_all_on_top")` at the trigger
terminal); Python's Scry mirrors the same default. No EoE card today
exercises the choose-a-card-to-bottom path — the only consumers are
ETB triggers that benefit from the CR 122.6 "scry happened"
information delta, not the bottoming decision itself.

**Failure mode**: a future EoE printing whose oracle text rewards
bottoming a specific card (e.g. "scry 2; if you scried a creature
card, draw a card") would observe the shortcut as a strength
regression — the bot would never bottom the wrong-shape card and
would lose the conditional rider. None today.

**Fix scope estimate**: medium-small. Add a `choose_scry_to_bottom`
agent callback (sister to `choose_surveil`) on the `Agent` base +
`DefaultTacticalAgent` + `InteractiveAgent`. Update `Scry.resolve`
to walk the top-N cards through the callback and partition into
keep-on-top / put-on-bottom lists; mirror the same on the Rust side
by replacing the inlined keep-on-top branch with a
`PendingDecision::ScryChoice` queue + `submit_scry_decision` /
`auto_resolve_pending_decisions("keep_all_on_top")` symmetric to
Surveil. Roughly mirrors the work already done for Surveil.

**Impact estimate**: zero strength cost today (no consumer exercises
the bottoming choice). Once the first scry-rewards-bottoming card
lands, strength cost grows from "shortcut equals Surveil's default"
levels — i.e. small, but a real signal-loss in self-play data on the
affected printings.

---

## Sequence(Surveil, DrawCards) PendingDecision-vs-inline ordering (Rust vs Python) — RESOLVED (round-36)

**Status**: RESOLVED in round-36 by commit `fed30c5e` on
`feature/rust-fix-sequence-pending-decision-ordering`. The fix moves
the PendingDecision drain INTO `Effect::Sequence`'s inner loop:
after each leaf effect resolves, `auto_resolve_pending(state,
"keep_all_on_top")` runs BEFORE the next leaf effect. Rust now
matches Python's no-agent Surveil flow, so `Sequence(Surveil(X=...),
DrawCards(N))` reads from the same library top on both engines.
The historical-context body below is preserved for git-blame
continuity.

**Pinned by (now PASSES)**:
`tests/test_parity_smoke.py::test_cross_engine_cerebral_download_real_eoe_cast_xfails_on_sequence_surveil_then_draw`
— flipped from xfail to direct cross-engine equality assertion in
the round-36 fix commit.

**Follow-up (sister composers)** — round-37 status:

- **`IfYouDoChoice` — RESOLVED.** Same "drain pending between
  child resolutions" treatment landed in
  `rust/src/state_ops_decisions.rs` (the IfYouDoChoice arm —
  `auto_resolve_pending(state, "keep_all_on_top")` between
  `do_action` and `then_action`). Round-37 commit on
  `feature/rust-fix-ifyoudo-pending-decision-ordering`.
  Preventative — no real-EoE printing exercises the
  IfYouDo(MayDo(pending-emitting-leaf), zone-reading-leaf) shape
  today, but the fix removes the latent gap so future probes and
  any future printing in that shape can't re-surface it.
- **`MayDoChoice` / `ChooseModeChoice` / `OptionalManaCostChoice`
  — NO FIX NEEDED.** Each applies a SINGLE inner effect in its
  resolution arm, so there is no intra-resolve ordering window to
  mis-order — the outer `auto_resolve_pending` drain loop handles
  the tail correctly.
- **`ChooseModes`** — does not exist as an Effect arm in Rust today
  (only the single-mode `ChooseOneMode` is wired). When a multi-mode
  variant lands, apply the same drain-between-children treatment if
  it sequentially applies more than one mode's effect.

---

### Historical context (pre-round-36 divergence trace)

**Location**: `rust/src/state_ops_resolve.rs:8434-8514`
(`resolve_top_of_stack`'s effect-fan-out loop) + the
`Effect::SurveilXEqualToArtifactCount` resolve at
`rust/src/state_ops_resolve.rs:4901-4980` + `Effect::Sequence` at
`rust/src/state_ops_resolve.rs:5111-5115` + the
`auto_resolve_pending(self, "keep_all_on_top")` terminal at
`rust/src/state_ops_resolve.rs:8514`. Python sister at
`src/mtg_bot/effects/generic/library_lookat.py:591-614`
(`Surveil.resolve` no-agent shortcut).

**What we did pre-fix**: when a single spell's effects composed
`Sequence([Surveil(...), DrawCards(...)])`, the two engines diverged
on observable post-resolve hand + library contents. Python's
`Surveil.resolve` short-circuits to keep-all-on-top via the
`p.agent is None` branch — the library is NEVER mutated, and the
following `DrawCards` draws the same cards Surveil "examined". Rust's
`Effect::SurveilXEqualToArtifactCount` instead popped X cards off the
library top into a `PendingDecision::SurveilChoice`; the Sequence's
inner `for child in effects` loop then ran `DrawCards` IMMEDIATELY,
drawing from the post-pop top (i.e. DIFFERENT cards). Only AFTER the
spell's full effect-fan-out loop completed did
`auto_resolve_pending(state, "keep_all_on_top")` re-insert the
surveiled cards at `lib[0]`.

**Why it was OK pre-fix**: Cerebral Download was the only EoE
consumer of `Sequence(Surveil(use_artifact_count=True),
DrawCards(3))`. Both engines' invariants stayed self-consistent (each
engine's draw + library contents agreed with its own surveil
semantics); the divergence only surfaced when the SAME spell was
driven through both engines and the hand contents were compared.
Production self-play does not run both engines simultaneously.

---

## CardDef bridge filter drops creatures with `dynamic_pt_formula` / `ward_cost`

**Where**: `src/mtg_bot/parity/trajectory.py:_printing_is_bridge_simple_creature`
(the two `if getattr(printing, ...) is not None: return False` lines
guarding `dynamic_pt_formula` and `ward_cost`).

**What the shortcut is**: the trajectory-parity loader filters out
every EoE creature that carries a `dynamic_pt_formula`
(`*`-based P/T cards: Harmonious Grovestrider, Cosmogoyf, Emissary
Escort) or a `ward_cost` (Harmonious Grovestrider, Mouth of the
Storm, Famished Worldsire, Lionheart Glimmer). These creatures do
NOT round-trip through the CardDef bridge today — the bridge's
`CardDef` shape carries the printing's raw `power` / `toughness`
ints (which the parser encodes as 0-placeholders for `*` cards —
see `cards/parser/printing_keywords.py:478-480`) and has no field
for either `dynamic_pt_formula` or `ward_cost`. Loading them
across the bridge silently produces a 0/0 (or 0/1, 0/4) vanilla
no-ward creature, which then disagrees cross-engine the moment
SBAs check or a Ward trigger would have fired.

**Why it's OK**: each card has a real engine-side implementation
(Python's `game._dynamic_base_pt(formula)` + Python's full Ward
substrate; Rust's matching shapes for the keyword side) — they
play correctly in production. The only context where the
mistranslation surfaced is the production-deck trajectory-parity
bench, where both engines are driven off the same CardDef
registry. Dropping these cards at filter time keeps the bench
honest. Extending CardDef to carry `dynamic_pt_formula` and
`ward_cost` is the proper fix; it's a CardDef-schema slice on its
own (Rust's `parse_printing` would need matching arms, plus the
layer-7 CDA computation on both sides has to read the formula at
P/T-query time).

**Failure mode (pre-fix)**: round-38 bench surfaced
`cast_spell::graveyard_p0,battlefield` for Harmonious
Grovestrider (2/5 of 18-game smoke failures). Python's SBA sent
the 0/0 creature to graveyard on resolve; Rust kept it on the
battlefield. The 0/0-SBA cross-engine asymmetry is its own
latent bridge gap but doesn't affect any real CR-correct
printing — no real card resolves as a literal 0/0 at ETB.

**Fix-scope estimate**: ~4 hours for the proper fix (CardDef
schema extension + Rust parser arm + bridge translators on
both sides) + ~1 hour parity test for Grovestrider/Cosmogoyf/
Emissary Escort actually playing cross-engine.

**Impact estimate**: 3 EoE creatures + 4 EoE Ward-bearers
unfilterable from the trajectory-parity coverage today. Reduces
divergence noise from the bench (cast_spell::graveyard_p0,
battlefield divergence count drops to 0 — verified round-39).

---

## 5 EoE pay-life shocklands admitted as plain untapped dual lands — `enters_tapped` / `pay-2-life` replacement dropped on BOTH engines (round-60 phase 1; activated-mana-ability cross-engine divergence CLOSED round-62)

**Where**: `src/mtg_bot/parity/trajectory.py:_printing_is_bridge_nonbasic_mana_land`
(the new predicate, wired into `_filter_deck_to_bridge_supported` +
`_printing_to_card_def`). Spec:
`docs/NONBASIC_LAND_SUBSTRATE_PLAN.md` §2/§3 (round-59 N2).

**What the shortcut is**: the production-deck trajectory-parity
loader now admits the 5 EoE pay-life shocklands — **Breeding Pool,
Watery Grave, Stomping Ground, Godless Shrine, Sacred Foundry** — as
plain untapped dual-mana lands (a `CardDef(card_type="Land",
mana_produced=<sorted dual>)`, the exact shape the basic-land arm
emits, minus the `"Basic"` supertype gate). The real Magic card
carries the replacement "As this land enters, you may pay 2 life. If
you don't, it enters tapped." The live `OracleParserCardSource`
**never structures that replacement at all** — it flattens each
shockland to `produces={c1,c2}` + `enters_tapped=False` + zero
abilities (verified round-60 against the live parser). The CardDef
bridge has no `enters_tapped` field and Rust's `register_printing`
has no land tapped-entry path, so the rider is dropped a SECOND time
symmetrically. Net: the shockland is modeled as a vanilla untapped
dual on BOTH engines — no pay-life decision, no tapped-entry, ever.

**Why it's OK**: the drop is **symmetric** — the parser flattens the
printing identically before either engine sees it, so Python and Rust
materialize the *same* untapped dual and round-trip **byte-equal**.
Pinned at two levels: (1) static — 3 cross-engine bridge pins build
the real Stomping Ground / Watery Grave / Breeding Pool CardDefs and
assert `compare_fields() == []`; (2) **activated** (round-62 N1, the
level round-61 N3 showed was missing) — an activated-mana-ability
cross-engine pin drives `activate_ability` for EACH color index of
all 5 real shocklands on BOTH engines and asserts a byte-equal pool
(see the ✅ CLOSED round-62 block below); plus 1 genuine real-EoE
probe drives real 17lands archetype 30 (Stomping Ground + Watery
Grave) through `attack_all` divergence-free. The bench's `attack_all`
strategy never makes the pay-life choice and never reads a land's
tapped-state for a decision, so the *replacement* simplification is
inert under the coverage it unlocks. This is the **round-39 Ward
precedent** exactly (`CardDef bridge filter drops creatures with
dynamic_pt_formula / ward_cost`, this doc above): a rider the bridge
drops symmetrically, bit-equal under the bench play strategy, shipped
blocked-at-fidelity rather than as a latent inter-engine divergence.
(The activated-mana-ability path itself was a real latent divergence
until round-62 fixed it — see the CLOSED block below.)

> **✅ CLOSED round-62 (N1) — the activated-mana-ability path is
> now BYTE-EQUAL-validated; the shockland admit no longer ships a
> latent cross-engine divergence.** Round-61 N3 found the round-60
> admit was NOT byte-equal on the activated mana-ability path: its
> byte-equality evidence was only a STATIC `compare_fields()`
> CardDef compare + an `attack_all` probe that never activated a
> 2-color land's mana ability deep enough to expose it. N3's
> post-admit production sweep (112 games) found **4 FAIL_DIVERGENCE**
> of one shape: the two `mana_produced` mana-ability bridges
> disagreed for a multi-color land — Python's
> `_card_def_to_python_printing` builds **one mana ability per
> color** (idx0=Add c1, idx1=Add c2); Rust's
> `apply_mana_produced_bridge` (`rust/src/cards.rs`) built **one
> ability adding ALL colors** (`Sequence(Add c1, Add c2)`), so
> `activate_ability(land, 0)` made Python add 1 color while Rust
> added BOTH → a spurious extra mana in the Rust pool. Invisible
> before round-60 because every basic is single-color (the bridges
> agreed) and the round-60 pins were static-CardDef-compare only.
>
> **Round-62 N1 fix**: rewrote `apply_mana_produced_bridge`
> (`rust/src/cards.rs`) to emit **one `is_mana_ability`
> `ActivatedAbility` per produced color**, in the SAME input order
> Python iterates `mana_produced` (for shocklands that is the
> `tuple(sorted(printing.produces))` alphabetical order
> `trajectory._printing_to_card_def` builds), so
> `activate_ability(land, k)` adds exactly the k-th color on BOTH
> engines (CR-correct — the player chooses the color via the
> ability index; Python was already correct). Single-color lands
> (every basic) stay bit-identical (one ability, one color).
>
> **Validation (round-62 N1)**: round-61 N3's exact Sweep A
> (arch 30,37,43,46,54,57,58,61,62,63,67,69,86,88 ×s0-3 = 56 games,
> `attack_all`, max-turns 22) re-run post-fix → **4 → 0
> FAIL_DIVERGENCE** (31 PASS / 0 DIV / 25 FAIL_TIMEOUT; the 3
> ex-divergent Sweep-A games arch 37/s3, 46/s0, 69/s0 converted
> DIV→PASS; the timeouts are the standing creatureless-mirror
> limitation, unchanged — not a regression). Pinned by an
> **activated-mana-ability cross-engine byte-equal pin**
> (`tests/test_parity_smoke.py::test_r62_shockland_activate_ability_per_color_byte_equal_both_engines`,
> parametrized over all 5 shocklands — drives `activate_ability`
> for EACH color index on both engines and asserts byte-equal pool
> + exactly the k-th single color, no spurious second color) plus a
> direct byte-diff regression
> (`test_r62_shockland_activate_idx0_no_spurious_second_color_rust`)
> and 5 Rust per-color-shape regression pins
> (`tests/test_cross_engine_etb_triggers.py::test_r62_rust_bridge_*`).
> The shockland admit's activated-mana-ability path is therefore now
> byte-equal-validated at scale. (The pay-life / tapped-entry
> *replacement* drop remains a separate, symmetric shared
> CR-incompleteness — see "Failure mode" / "Fix-scope" below, still
> deferred to the Phase-3 `enters_tapped` substrate; the round-62
> fix closes the cross-engine divergence, not the CR-fidelity gap.)
> See `docs/bench_trajectory_parity_smoke.md` round-61 entry for the
> original precise capture.

The guardrail predicate POSITIVELY asserts the parser-flattened
mana-only profile (non-basic Land, 1-2 produce colors, NO
activated/triggered/static abilities, NO `enters_tapped`, NO
`enters_tapped_unless_any_player_life_at_most`, NO clone) so it
admits ONLY these 5 and DECLINES the other 18 non-basic-land-gated
cards (the 5 Planet lands' real `enters_tapped` inter-engine
divergence + Station/AA; the 10 conditional painlands' structured
conditional-tapped; Secluded Starforge's manaless activated
abilities; Cathedral of War's tapped+Exalted; Echoing Deeps' clone
replacement) — admitting any of THOSE would be a real silent
mistranslation, which is why the predicate's negative set is pinned
exhaustively (`tests/test_trajectory.py::test_r60_*`).

NOTE on the conditional-tapped guard: the live
`CardPrinting.enters_tapped_unless_any_player_life_at_most` is an
`int` whose disabled sentinel is `0` (`cards/base.py:733` — "0
disables"), NOT `None`. The round-59 spec text wrote that guard as
`... is not None`; applied literally to the live `int`-`0` field
that would reject all 5 shocklands (`0 is not None` is True) and
ship a +0-card no-op. The intent-preserving translation of the spec
to the live field is a falsy check (0/absent ⇒ admit; the painlands'
positive `13` ⇒ reject), which honors the spec's stated design
(+5 cards / +18,065 decks).

**Failure mode**: a future probe (or a smarter bench strategy) that
DRIVES a shockland's pay-life / tapped-entry decision would observe
Python and Rust **agree with each other** (both skip the choice and
play it untapped) but **disagree with the Comprehensive Rules** (a
real shockland can enter tapped or cost its controller 2 life,
affecting life totals and same-turn tempo). It is a shared
CR-incompleteness, NOT a cross-engine divergence — the bench cannot
surface it because neither engine models it and the strategy never
exercises it. The honest risk is that this masks the *absence* of
the `enters_tapped` substrate, not that it produces a wrong
cross-engine comparison.

**Fix-scope estimate**: deferred to the Phase-3 `enters_tapped`
substrate (spec §3 Phase 3): a `CardDef.enters_tapped: bool` +
`enters_tapped_unless_any_player_life_at_most: int` field, Rust
`register_printing` land-tapped path (`rust/src/cards.rs` + the
state-builder land materialization — a Rust slice requiring
`maturin develop --release`), bridge round-trip arms, then widen
this predicate. The pay-life *replacement choice* (a real agent
decision) is a further substrate beyond even Phase 3. Estimate:
~4-6h for the Rust `enters_tapped` slice; the pay-life-choice
modeling is a larger separate effort. Per spec §3 the Phase-3
real-bench yield is ~0 (the 9 Duskmourn painlands have 0 EoE decks;
B/E stay §2-blocked on Station/Exalted) so it is NOT a recommended
near-term round.

**Impact estimate**: **+5 cards / +18,065 cumulative 17lands decks**
(Breeding Pool 4,712 + Watery Grave 4,226 + Stomping Ground 3,859 +
Godless Shrine 2,937 + Sacred Foundry 2,331) unblocked into the
production-deck bench, **0 strength cost** (no engine behavior
changes; this is a bench-coverage admit, not a rules change). This
is the entire *clean* realizable yield of the non-basic-land lever;
the roadmap's remaining ~16,510-deck tail (the other 18) is gated
behind the deferred Station / activated-ability / static / clone
subsystems, not behind this substrate.

---

## Perigee Beckoner — `PumpTargetCreatureUntilEotGrantDiesReturnTapped` Effect half shipped byte-equal; full card stays loader-gated (general nested-trigger-grant subsystem + warp_cost)

**Location**: `rust/src/state.rs`
(`UeotModifier::GrantedDiesReturnTapped` marker variant + no-op arms
in the two exhaustive `ueot_power_bonus` / `ueot_toughness_bonus`
accessors) + `rust/src/cards.rs`
(`Effect::PumpTargetCreatureUntilEotGrantDiesReturnTapped {
power_bonus, toughness_bonus }` variant + `parse_effect` arm
`pump_target_creature_until_eot_grant_dies_return_tapped` +
`effect_to_pydict` arm) + `rust/src/state_ops_resolve.rs`
(module-private helper `perigee_pick_another_own_creature` + the
resolve match arm) + `rust/src/state_ops_sba.rs` (module-private
helper `perigee_return_tapped_if_marked` + the post-DIES/LEAVES-drain
return call in `apply_sbas`). Bridge arm
`src/mtg_bot/parity/cross_engine.py`
(`pump_target_creature_until_eot_grant_dies_return_tapped`,
immediately above the `PHASE5_BRIDGE_ARMS` sentinel). Python class
(pre-existing, NOT new): `PumpTargetCreatureUntilEOT`
(`src/mtg_bot/effects/generic/pump.py:258`) carrying the existing
`granted_triggered_ability` / `exclude_self` / `you_control_only`
fields + the pre-existing bespoke
`PerigeeBeckonerDiesReturnTappedEffect`
(`src/mtg_bot/effects/bespoke.py:2107`) — the exact class+params the
genuine Perigee Beckoner printing already parses to.

**What the shortcut is**: Perigee Beckoner (~21,131 17lands decks)
prints "When this creature enters, until end of turn, another target
creature you control gets +2/+0 and gains 'When this creature dies,
return it to the battlefield tapped under its owner's control.' Warp
{1}{B} ...". The genuine parsed printing's ETB is
`PumpTargetCreatureUntilEOT(power_bonus=2, you_control_only=True,
exclude_self=True, granted_triggered_ability=TriggeredAbility(
effect=PerigeeBeckonerDiesReturnTappedEffect(), event=Event.DIES,
predicate=IsSelf()))`. The **bare** `PumpTargetCreatureUntilEOT` Rust
arm (round 28) is shipped + bridged but its own doc-comment ("Schema
simplification vs Python") explicitly **deferred the
`granted_triggered_ability` rider to a follow-up slice**. Round 60
ships that rider for the Perigee shape: a dedicated Effect variant
that pushes BOTH a `UeotModifier::PowerToughnessBonus` AND a
payload-free `UeotModifier::GrantedDiesReturnTapped` marker onto the
first OTHER creature on the source-controller's bf (CR 115.4
"another"); the SBA destroy path, AFTER the DIES/LEAVES dispatches,
returns a marked carrier to its OWNER's battlefield TAPPED. The
**deliberate divergence is NOT in the closed Effect half** (which is
byte-equal — see below) but in the **scope**: Rust has **no general
layer-6 grant-triggered-ability registry** (Python's
`continuous_effects` `grant_triggered_ability` /
`game.effective_triggered_abilities`). Rather than building that whole
subsystem, the marker variant models **exactly the fixed Perigee
shape** ("dies → return tapped under owner's control"). Any OTHER
card that grants a *different* nested triggered ability via a pump
rider is **not** covered. The **full Perigee Beckoner card is NOT
added to the production-deck loader `_SAFE_*` allowlist** (no loader
admit) — only the bridge/probe-level Effect half closes; `warp_cost`
(a §2-declined cost-mechanic) gates the loader independently anyway.

**Round-53 effective-state lesson applied (subtle, load-bearing)**:
Python's `PerigeeBeckonerDiesReturnTappedEffect` RE-USES the same
`GameObject` (`put_into_battlefield(state, source, ...)`), and
`put_into_battlefield` does NOT reset the per-object
`temp_power_bonus`. So Python's returned creature **keeps the +2/+0
pump** (verified: effective power stays 4 after the return; loses only
the layer-6 grant so a 2nd death does not re-return). A naive "clean
CR-400.7 new-object: clear all UEOT modifiers on return" would make
Rust read the returned creature as 2/2 vs Python's 4/2 — a real §2
silent divergence. Per the round-53 directive (Python is the source
of truth; resolve parity failures by matching it, not by copying a
textbook rule the source engine does not implement), Rust's
`perigee_return_tapped_if_marked` drops **only** the
`GrantedDiesReturnTapped` marker and **keeps** the
`PowerToughnessBonus`. This is a documented deviation from a clean CR
400.7 new-object reading, deliberately taken to stay byte-equal with
the Python source of truth.

**Why it's OK / which scenarios make it not-OK / failure mode**: this
is the honest Effect-half-closes / full-card-stays-gated split
established by r51 (Monoist), r52 (Extinguisher), r53 (Mightform), r54
(Famished Worldsire), r56 (Dauntless Scrapbot), r57 (Faller's
Faithful). The closed half round-trips byte-equal — the genuine
real-EoE probe drives the ACTUAL parsed Perigee Beckoner printing's
ETB cross-engine and asserts byte-equality across the full lifecycle:
the "another" ally is pumped +2/+0 on BOTH (the source itself is NOT
self-pumped — "another"); after the ally is destroyed it returns to
its OWNER's battlefield TAPPED on BOTH, graveyard empty on BOTH,
keeping the +2/+0 (effective power byte-equal at 4) on BOTH; a second
death does not re-return on BOTH. The NOT-OK scenario is admitting the
full card to the bench loader, which would (a) silently mistranslate
ANY future card whose pump rider grants a *different* nested
triggered ability (the general nested-trigger-grant subsystem is
unmodeled in Rust), and (b) require the §2-declined `warp_cost`
cost-mechanic — both explicitly declined. No real-card-exposed
divergence (the card is not on any `_SAFE_*` allowlist; no production
path drives it today).

**Fix scope estimate**: closing the remaining half needs a general
Rust layer-6 grant-triggered-ability registry (a per-object granted-
ability list the DIES/ENTERS/… dispatch reads alongside the
printing's `triggered_abilities`, with CR-613 timestamp ordering and
EndOfTurn expiry) + its bridge, PLUS the `warp_cost` cost-mechanic —
a multi-round subsystem, deferred. The Effect half (pump + the fixed
Perigee dies-return-tapped rider + the round-53 power-retention
parity) is complete.

**Impact estimate**: zero production strength cost (Perigee Beckoner
not on the loader allowlist; no production exposure). The
real-card-coverage progress is the honest closure of the closeable
Effect half + honest pinning of the loader-gated
nested-trigger-grant/warp remainder.

**Pinned by**: 4 cross-engine bridge pins
(`tests/test_cross_engine_etb_triggers.py::test_bridge_perigee_pump_grant_dies_return_tapped_translates`
+ `..._defaults_zero` + `..._etb_pump_parity` +
`..._dies_return_parity`); 6 Rust regression pins
(`tests/test_parity_smoke.py::test_r60_rust_perigee_*` — pumps
another own creature / source excluded; dies-return-tapped keeps
+2/+0; second-death no re-return; no-other-creature silent fizzle;
non-creature other not targeted; first-other-creature deterministic
pick); 1 genuine real-EoE cross-engine probe
(`tests/test_parity_smoke.py::test_cross_engine_real_eoe_perigee_beckoner_etb_pump_grant_dies_return_tapped_parity`
— drives the actual parsed Perigee Beckoner printing's full
pump→dies→return-tapped lifecycle cross-engine; byte-equal at every
step incl. the round-53 effective-state power-retention corner; the
general nested-trigger-grant subsystem intentionally NOT exercised).

---

## Radiant Strike — `DestroyTargetArtifactOrTappedCreature` Effect half shipped byte-equal; full Instant stays loader-gated (no spell-card bench-admit path)

**Location**: `rust/src/cards.rs`
(`Effect::DestroyTargetArtifactOrTappedCreature` field-free unit
variant + `parse_effect` arm
`destroy_target_artifact_or_tapped_creature` +
`effect_to_pydict` arm) + `rust/src/state_ops_resolve.rs` (the
resolve match arm beside `Effect::DestroyTargetArtifact` — clones the
artifact arm's body verbatim, widening only the `find_map` predicate
from `card_types.contains("Artifact")` to
`is_artifact || (is_creature && obj.tapped)`; identical
indestructible-skip / `Arc::make_mut` remove→graveyard /
`mark_left_battlefield_if_nonland` / `pending_leaves_dispatches` /
`queue_token_cease` tail). Bridge arm
`src/mtg_bot/parity/cross_engine.py`
(`destroy_target_artifact_or_tapped_creature`, immediately above the
`PHASE5_BRIDGE_ARMS` sentinel). Python class (pre-existing, NOT new):
`DestroyTargetArtifactOrTappedCreature`
(`src/mtg_bot/effects/generic/destroy.py:475`) — a `Destroy` subclass
whose `__post_init__` sets `targets = (TargetSpec(IsArtifact() |
(IsCreature() & IsTapped())),)`; the exact class the genuine Radiant
Strike printing's inner `Sequence` leg already parses to.

**What the shortcut is**: Radiant Strike (~17,744 17lands decks) is an
`[Instant] {3}{W}` printing "Destroy target artifact or tapped
creature. You gain 3 life." The genuine parsed printing's
`spell_effect` is
`Sequence((DestroyTargetArtifactOrTappedCreature(targets=(TargetSpec(
ObjectOr(IsArtifact(), ObjectAnd(IsCreature(), IsTapped()))),)),
GainLife(amount=3)))`. The `Sequence` combinator AND `GainLife{3}`
were already live Rust variants + bridge arms; the **only**
genuinely-new surface this slice ships is the inner typed-OR destroy
filter (`DestroyTargetArtifactOrTappedCreature`), a sibling of the
shipped `DestroyTargetArtifact` / `DestroyTargetNoncreaturePermanent`
arms with the scan predicate widened to admit artifacts OR *tapped*
creatures. The `obj.tapped` term is read off the scanned live
`GameObject` (the round-53 effective-state lesson — the engine has no
continuous-effect tap-state layer, so `obj.tapped` IS the effective
tapped state both engines agree on; an untapped non-artifact creature
is NOT a legal pick — the OR-filter teeth, re-verified at resolution
per CR 608.2b on both engines). The **deliberate divergence is NOT in
the closed Effect half** (byte-equal — see below) but in the
**scope**: the **full Radiant Strike Instant is NOT added to the
production-deck loader `_SAFE_*` allowlist** (no loader admit). There
is no Instant/Sorcery bench-admit path at all — `CardDef.card_type` ∈
{Land, Creature} and `_printing_is_bridge_simple_creature` positively
rejects `spell_effect is not None`. Every Effect-uncovered Tier-A card
is an Instant/Sorcery carrying a `spell_effect`, so none is
bench-admissible until the separate shared spell-card-bridge lever (a
`CardDef` spell shape + a `_printing_is_bridge_spell` predicate) is
built.

**Why it's OK / which scenarios make it not-OK / failure mode**: this
is the honest Effect-half-closes / full-card-stays-gated split
established by r51 (Monoist), r52 (Extinguisher), r53 (Mightform), r54
(Famished Worldsire), r56 (Dauntless Scrapbot), r57 (Faller's
Faithful), r60 (Perigee Beckoner). The closed half round-trips
byte-equal — the genuine real-EoE probe drives the ACTUAL parsed
Radiant Strike printing's `spell_effect` (the real `Sequence`) on the
Python side via a `StackItem` with the chosen object target, vs the
bridged `{"kind":"sequence","effects":[{"kind":
"destroy_target_artifact_or_tapped_creature"},{"kind":"gain_life",
"amount":3}]}` synthetic Instant on Rust, and asserts byte-equality on
two arms: (POSITIVE) a tapped creature is destroyed → p1 graveyard on
BOTH and the caster gains 3 life on BOTH; (NEGATIVE) an untapped
non-artifact creature is NOT a legal pick → the destroy no-ops on
BOTH but the unconditional +3-life Sequence leg STILL resolves on
BOTH. The NOT-OK scenario is admitting the full Instant to the bench
loader, which is structurally impossible today (no spell-card admit
path) — i.e. there is **no real-card-exposed divergence**: the card is
not on any `_SAFE_*` allowlist and no production path drives it.

**Fix scope estimate**: the Effect half (the typed-OR destroy filter +
its composition inside the already-live Sequence + GainLife shell) is
**complete**. Flipping the full Radiant Strike Instant into the
production-deck bench needs the separate shared spell-card-bridge
lever (a `CardDef` spell shape + a `_printing_is_bridge_spell`
predicate) — one shared ~1-2-round substrate that unblocks ALL ~31
Effect-uncovered Tier-A cards' bench admit at once (the
Station-subsystem analogue), recommended to be sequenced after 3-5
Tier-A Effects are closed. Deferred to that lever; not this slice.

**Impact estimate**: zero production strength cost (Radiant Strike not
on the loader allowlist; no production exposure). The
real-card-coverage progress is the honest closure of the closeable
Effect half (Radiant Strike leaves the Effect-uncovered Tier-A
bucket — its emitted classes
`DestroyTargetArtifactOrTappedCreature` / `Sequence` / `GainLife`
become a subset of the covered set) + honest pinning of the
loader-gated spell-card-bridge remainder.

**Pinned by**: 5 cross-engine bridge pins
(`tests/test_cross_engine_etb_triggers.py::test_bridge_destroy_target_artifact_or_tapped_creature_basic_translation`
+ `..._dtaotc_targets_set_to_artifact_or_tapped_creature` +
`..._dtaotc_extra_keys_silently_ignored` +
`..._dtaotc_equality_with_default_constructor` +
`..._dtaotc_composable_in_radiant_strike_sequence`); 6 Rust regression
pins (`tests/test_parity_smoke.py::test_rust_dtaotc_*` — destroys an
artifact; destroys a tapped creature; an untapped creature is NOT
destroyed (the OR-filter teeth); an indestructible artifact survives;
the full `Sequence([destroy, gain_life{3}])` resolves
destroy-then-+3-life in order; a destroyed artifact token ceases to
exist); 1 genuine real-EoE cross-engine probe
(`tests/test_parity_smoke.py::test_cross_engine_real_eoe_radiant_strike_destroy_or_gain_parity`
— drives the actual parsed Radiant Strike printing's `spell_effect`
cross-engine, POSITIVE tapped-creature-destroyed + NEGATIVE
untapped-creature-survives arms, byte-equal incl. the unconditional
+3-life leg on the fizzle path; the spell-card bench-admit lever
intentionally NOT exercised).

---

## Pull Through the Weft — second-clause ("lands to battlefield tapped") parse-drop

**Location**: `src/mtg_bot/cards/parser/effects.py:1746-1782` (the
`_RETURN_UP_TO_N_NONLAND_PERMANENT_GY_TO_HAND_THEN_LANDS_BF_TAPPED`
recognizer and its docstring) → emits
`ReturnUpToNNonlandPermanentCardsFromGraveyardToHand`
(`src/mtg_bot/effects/generic/bounce.py`, the class docstring states
the drop verbatim: *"the second 'lands to battlefield tapped' clause
is dropped at parse time — no engine primitive yet"*).

**What the shortcut is**: Pull Through the Weft's printed oracle text
is the compound sentence "Return up to two target nonland permanent
cards from your graveyard to your hand, **then return up to two target
land cards from your graveyard to the battlefield tapped**." The parser
matches the FULL unsplit sentence with a single recognizer and
**deliberately drops the entire second clause** (the "lands to
battlefield tapped" half) as an unimplemented rider — no
"return-up-to-N-land-cards-from-graveyard-to-battlefield-tapped" engine
primitive exists. The parsed Python `spell_effect` is therefore
*only* the first clause:
`ReturnUpToNNonlandPermanentCardsFromGraveyardToHand(max_n=2,
min_n=0)`. The recognizer captures both "up to N" counts as regex
parameters (the first drives the primitive; the second is consumed but
its effect is not modeled) so the regex matches the full oracle
surface — but the second clause's *behavior* is absent.

This is a **pre-existing parser-side simplification, NOT introduced by
this campaign** — it predates the Effect-uncovered triage work. It is
recorded here now because it becomes **load-bearing the moment the B8
graveyard-multi-select Rust substrate
(`docs/EFFECT_UNCOVERED_TIERA_MINISPECS_BATCH3.md` §3) is implemented
and Pull Through the Weft's Effect is bridged + cross-engine probed**:
the Rust close MUST mirror the **parsed (single-clause) Python
effect**, NOT the printed oracle text. The Python parsed effect is the
source of truth (`feedback_parity_new_code_is_right.md`); a future
round must NOT "fix" Rust to over-implement the dropped land-return
clause, because that would make the two engines diverge (Rust doing
the land return, Python silently not) — the exact inverse of the usual
"new code is right" direction, here because the *parser* already
decided the simplification.

**Why it's OK (and the NOT-OK scenario)**: OK because (a) the
simplification is on the Python source-of-truth side, so both engines
will agree once Rust mirrors the parsed effect (cross-engine parity is
preserved — the campaign's actual invariant); (b) it is strictly MORE
faithful than the prior static-registry entry, which returned a bare
`ReturnCreatureFromYourGraveyardToHand()` dropping BOTH the "up to two"
count AND the "nonland permanent" widening AND the second clause — the
per-clause grammar preserves the multi-target count and the
nonland-permanent scope (the parser CLAUDE.md "faithful to oracle
text" rule is partially honored: the first clause is exact). NOT-OK
when: an AI must reason about Pull Through the Weft's *full* printed
value (it will under-value the card by the land-return half — a
strength cost on decks that run it, ~2,235 17lands decks) OR a future
round implements the land-graveyard-to-battlefield-tapped primitive
and "fixes" only one engine, silently desyncing them.

**Failure mode**: the bot under-values Pull Through the Weft (sees a
2-card nonland-permanent graveyard return, not the additional 2-land
ramp-from-graveyard) — a play-strength approximation, not a
correctness crash. The cross-engine divergence failure mode is latent
and only triggered by an asymmetric "fix" of the dropped clause.

**Fix scope estimate**: implementing the dropped clause correctly is a
*new engine primitive* ("return up to N target land cards from your
graveyard to the battlefield tapped") on BOTH engines + the parser
recognizer emitting a composite of the two clauses + a cross-engine
bridge arm + parity pins — roughly a 1-2-round substrate of its own
(the `ReturnToBattlefieldTapped`-land variant of the B8
graveyard-multi-select primitive). NOT in scope of the B8 close; B8
mirrors the parsed single-clause effect only.

**Impact estimate**: zero cross-engine parity cost as long as Rust
mirrors the parsed Python effect (the B8 implement-time requirement —
pin it). Play-strength cost: a modest under-valuation of Pull Through
the Weft on the ~2,235 17lands decks that run it (the engine resolves
the higher-value first clause faithfully; only the secondary
land-ramp-from-graveyard rider is missing).

**Pinned by**: (to be added at B8 implement time) the B8 genuine
real-EoE probe
`test_cross_engine_real_eoe_pull_through_the_weft_multiselect_parity`
must assert byte-equal hand contents for the *first clause only* with
a land card in the graveyard explicitly NOT returned to the
battlefield (the parsed-effect-is-SoT pin — confirming Rust does NOT
over-implement the dropped clause). Until B8 lands this entry is the
record of the pre-existing parser drop; no Rust consumer exercises it
yet (Pull Through the Weft stays loader-gated on the spell-card-bridge
lever).

---

## Seedship Impact — `SeedshipImpactEffect { token_printing_id }` Effect half shipped byte-equal; full Instant stays loader-gated (no spell-card bench-admit path)

**Location**: `rust/src/cards.rs`
(`Effect::SeedshipImpactEffect { token_printing_id: u32 }`
single-field payload variant + `parse_effect` arm
`seedship_impact_effect` + `effect_to_pydict` arm) +
`rust/src/state_ops_resolve.rs` (the resolve match arm beside
`Effect::DestroyTargetArtifactOrTappedCreature` — destroy-half clones
the shipped `DestroyTargetArtifact` body with the filter swapped to
Artifact-OR-Enchantment; the conditional Lander-create block is
re-derived privately from the `Effect::CreateToken` arm:
registry-bounds check, fresh-id allocator, source-controller seat,
fresh `etb_timestamp`, ENTERS-dispatch queue). Bridge arm
`src/mtg_bot/parity/cross_engine.py` (`seedship_impact_effect`,
immediately above the `PHASE5_BRIDGE_ARMS` sentinel). Python class
(pre-existing, NOT new): `SeedshipImpactEffect`
(`src/mtg_bot/effects/bespoke.py:1219`) — a field-free `Effect`
subclass whose `resolve` picks the first artifact/enchantment, reads
`obj.printing.mana_cost.total` BEFORE `destroy(state, obj)`, and
creates `TOKEN_PRINTINGS["Lander"]` for `controller_id` iff `mv ≤ 2`.

**What the shortcut is**: Seedship Impact (~13,908 17lands decks) is
an `[Instant] {1}{G}` printing "Destroy target artifact or
enchantment. If its mana value was 2 or less, create a Lander token."
The genuine parsed printing's `spell_effect` is the field-free
`SeedshipImpactEffect()`. The shipped Rust variant carries a
`token_printing_id: u32` — its Rust `Registry` index for the Lander
token. **This is a deliberate deviation from the mini-spec's
field-free-unit-variant sketch, taken because it is the only
bridge-correct option**: Rust's registry has NO intrinsic Lander
concept (`RegistryData::is_token` is purely supertype-derived;
`cards.rs:4584`), so a bespoke token-minting arm MUST carry the pid
exactly as `Effect::CreateToken { count, token_printing_id }` does
(the round-49/56 `TOKEN_PRINTING_SUBSTRATE`). The pid is a Rust-side
registry-index carrier ONLY; the bridge **drops** it and constructs
the bare field-free Python `SeedshipImpactEffect()` (Python mints the
Lander intrinsically from `TOKEN_PRINTINGS["Lander"]`, no registry).
Both engines therefore seat the SAME "Lander" printing (Rust via the
registered pid, Python via `TOKEN_PRINTINGS`); the name-keyed field
view (`_zone_signature` keys on `printing.name`, not registry pid)
makes the created token byte-equal. The **deliberate divergence is
NOT in the closed Effect half** (byte-equal — see below) but in the
**scope**: the **full Seedship Impact Instant is NOT added to the
production-deck loader `_SAFE_*` allowlist** (no loader admit). There
is no Instant/Sorcery bench-admit path at all (`CardDef.card_type` ∈
{Land, Creature}; `_printing_is_bridge_simple_creature` rejects
`spell_effect is not None`).

**Indestructible parity nuance (§2, load-bearing)**: Python's
`SeedshipImpactEffect.legal_targets` includes indestructible
artifacts/enchantments, but at resolve `destroy(state, obj)` returns
`False` for indestructible → early-return with **no Lander
consolation**. The Rust scan SKIPS indestructible permanents (the
shipped `DestroyTargetArtifact` precedent). For a single-legal-target
board these reach the SAME observable on both engines
(indestructible-only → no destroy, no Lander). The pins/probe
deliberately use single-legal-target boards so the
deterministic-first pick is unambiguous; a mixed
indestructible+destroyable board (where Python's agent could pick the
indestructible target while Rust's scan picks the destroyable one) is
out of probe scope, identical to the Radiant Strike precedent's
documented scoping. The indestructible-keyword read also uses
`printing.keywords` (printed) vs Python `effective_keywords` — the
same effective-state reasoning as the shipped `DestroyTargetArtifact`
arm (no keyword-granting interaction in a synthetic probe → byte-
equal). The printed mana value is read from `ManaCost`'s
generic+colored sum (Rust has no hybrid/x field — the registry
flattens hybrid at parse time, the existing documented simplification,
matching Python `mana_cost.total` for non-hybrid costs).

**Why it's OK / which scenarios make it not-OK / failure mode**: this
is the honest Effect-half-closes / full-card-stays-gated split
established by r51..r65 (Monoist..Radiant Strike). The closed half
round-trips byte-equal — the genuine real-EoE probe drives the
ACTUAL parsed Seedship Impact printing's `spell_effect` (the field-
free `SeedshipImpactEffect`) on Python via a `StackItem` with the
chosen `("permanent", id)` target, vs the bridged synthetic Instant
carrying the registered Lander pid on Rust, and asserts the WHOLE
field view byte-equal on TWO arms: (POSITIVE) an mv-2 artifact is
destroyed → p1 graveyard AND a Lander is created under p0 on BOTH;
(NEGATIVE) an mv-3 artifact is destroyed but NO Lander on BOTH (mv 3
> 2). The NOT-OK scenario is admitting the full Instant to the bench
loader, which is structurally impossible today (no spell-card admit
path) — i.e. there is **no real-card-exposed divergence**: the card
is not on any `_SAFE_*` allowlist and no production path drives it.

**Fix scope estimate**: the Effect half (the Artifact-OR-Enchantment
destroy + the printed-mv-≤2 conditional Lander rider, re-derived from
the shipped CreateToken Lander block) is **complete**. Flipping the
full Seedship Impact Instant into the production-deck bench needs the
separate shared spell-card-bridge lever (a `CardDef` spell shape + a
`_printing_is_bridge_spell` predicate) — the same ~1-2-round shared
substrate that unblocks ALL ~30 remaining Effect-uncovered Tier-A
cards' bench admit at once. Deferred to that lever; not this slice.

**Impact estimate**: zero production strength cost (Seedship Impact
not on the loader allowlist; no production exposure). The
real-card-coverage progress is the honest closure of the closeable
Effect half (Seedship Impact leaves the Effect-uncovered Tier-A
bucket — its emitted class `SeedshipImpactEffect` becomes a subset of
the covered set) + honest pinning of the loader-gated
spell-card-bridge remainder.

**Pinned by**: 4 cross-engine bridge pins
(`tests/test_cross_engine_etb_triggers.py::test_bridge_seedship_impact_effect_basic_translation`
+ `..._pid_dropped_equality` + `..._extra_keys_silently_ignored` +
`..._composable_in_sequence`); 6 Rust regression pins
(`tests/test_parity_smoke.py::test_rust_seedship_*` — destroy
artifact mv1 → Lander; destroy enchantment mv2 → Lander; destroy
artifact mv3 → NO Lander; indestructible target skipped → no destroy
no Lander; no legal target → silent no-op; Lander under
source-controller not active_player); 1 genuine real-EoE
cross-engine probe
(`tests/test_parity_smoke.py::test_cross_engine_real_eoe_seedship_impact_destroy_then_conditional_lander_parity`
— drives the actual parsed Seedship Impact printing's `spell_effect`
cross-engine, POSITIVE mv-2-destroy+Lander + NEGATIVE
mv-3-destroy-no-Lander arms, the WHOLE field view byte-equal on BOTH;
the spell-card bench-admit lever intentionally NOT exercised).

---

## Orbital Plunge — `DealDamageToTargetCreatureWithExcessLanderRider { amount, token_printing_id }` Effect half shipped byte-equal; full Sorcery stays loader-gated (no spell-card bench-admit path)

**Location**: `rust/src/cards.rs`
(`Effect::DealDamageToTargetCreatureWithExcessLanderRider { amount:
i32, token_printing_id: u32 }` two-field payload variant +
`parse_effect` arm
`deal_damage_to_target_creature_with_excess_lander_rider` +
`effect_to_pydict` arm) + `rust/src/state_ops_resolve.rs` (the
resolve match arm beside the `SeedshipImpactEffect` arm — first-
creature scan over BOTH bfs in ETB-timestamp order; the
counters-inclusive remaining-lethal computation BEFORE damage; the
`obj.damage.saturating_add` damage-apply from the shipped
`DealDamageAnyTarget` shape; the conditional Lander-create block
re-derived privately from `Effect::CreateToken`). Bridge arm
`src/mtg_bot/parity/cross_engine.py`
(`deal_damage_to_target_creature_with_excess_lander_rider`,
immediately above the `PHASE5_BRIDGE_ARMS` sentinel). Python class
(pre-existing, NOT new):
`DealDamageToTargetCreatureWithExcessLanderRider`
(`src/mtg_bot/effects/generic/damage.py:327`).

**What the shortcut is**: Orbital Plunge (~28,629 17lands decks) is
a `[Sorcery] {3}{R}` printing "Orbital Plunge deals 6 damage to
target creature. If excess damage was dealt this way, create a
Lander token." The genuine parsed printing's `spell_effect` is
`DealDamageToTargetCreatureWithExcessLanderRider(amount=6,
targets=(TargetSpec(IsCreature()),))`. Python's `resolve` computes
`remaining = max(0, effective_toughness(state, obj) - obj.damage)`
then `excess = max(0, self.amount - remaining)` BEFORE applying the
damage, applies `amount`, and creates a Lander iff `excess > 0`. The
shipped Rust variant carries `amount` (the damage; rides through to
Python) + the Lander's Rust-registry `token_printing_id` — the SAME
pid-carrier deviation as `SeedshipImpactEffect` (Rust has no
intrinsic Lander; Python's class mints from
`TOKEN_PRINTINGS["Lander"]`; the bridge DROPS the pid). The
**deliberate divergence is NOT in the closed Effect half** but in
the **scope**: the **full Orbital Plunge Sorcery is NOT added to the
production-deck loader `_SAFE_*` allowlist** (no Instant/Sorcery
bench-admit path).

**§2 counters-asymmetry (load-bearing, the mini-spec risk)**:
Python's `effective_toughness` (`game._compute_effective_pt`) folds
`+1/+1` counters (CR 613 layer 7d). Rust's *combat-side*
`effective_toughness` getter deliberately does NOT fold counters
(the documented `state_ops_combat.rs` asymmetry), but the *SBA-side*
lethal check (`state_ops_sba.rs::collect_sba_victims`) DOES via
`base_toughness + obj.counters + obj.ueot_toughness_bonus()`. To
stay byte-equal with the Python source of truth, the Orbital Plunge
arm computes the remaining-lethal denominator with the
counters-INCLUSIVE formula re-derived privately (file-isolation) —
`base = ueot_base_pt_override().t OR printed_toughness`, plus
`obj.counters`, plus `obj.ueot_toughness_bonus()` — NOT the
combat-side getter. This is the mandatory mini-spec pin: a
counters-omitting impl would silently diverge the excess (and hence
the Lander) on a counter'd target. Pinned both directions (a
−counters creature whose effective toughness shrinks → excess
appears → Lander; a +counters creature whose effective toughness
grows → excess vanishes → NO Lander) on the Rust side, and via the
genuine real-EoE probe's NEGATIVE-counters arm (printed toughness 8,
<!-- R74-1 note: the parenthetical "Rust's combat-side
effective_toughness getter does NOT fold counters" above is now
STALE — the round-74 R74-1/I23 slice closed that combat-side
asymmetry (the getter folds counters byte-equal with Python). This
arm's PRIVATE file-isolated re-derivation is unaffected and stays
correct (it never called the getter); per-arm file-isolation
remains the right pattern. See the RUST_PARITY_GAPS I23 closure. -->

−4 counters → effective 4 → excess 2 → Lander on BOTH; a
counters-omitting bug → no Lander → divergence). Lifelink/deathtouch
are NOT modeled on either side (the documented Python parity
simplification — CR 120.3e is not implemented; comparing amount to
remaining toughness is the model).

**Comparator counters-blindness — CLOSED (round-r70).** This entry
formerly noted a comparator limitation: the cross-engine field-view
comparator's `_zone_signature` read `getattr(obj, "counters", 0)`,
but a Python `GameObject` has no `counters` attribute (it carries
separate `plus_one_counters`/`minus_one_counters` ints) — so the
comparator's counters slot was structurally `0` for every Python
object while Rust emitted the real signed net. Both engines preserve
net counters on a creature that dies (CR 400.7 carve-out), so the
ENGINES always agreed; the comparator merely could not read Python's
split counter fields, producing a spurious `graveyard_p*` counters
diff for a counter'd-then-dead creature, which the Orbital Plunge
probe worked around with a targeted-delta `_is_known_counters_blind
_gy_diff` filter (weakening divergence detection on the whole
graveyard zone). **Round-r70 fixed the comparator** (`scripts/
parity_smoke.py` `_net_counters`): `_zone_signature` slot 4 now
derives the signed net counter (`plus_one_counters −
minus_one_counters`, with an explicit `counters` attr winning when
present for the Rust dict-shim path) — byte-aligned with Rust's
`GameObject.counters`. The targeted-delta filter was deleted; the
Orbital Plunge probe now asserts the **full `compare_fields == []`**
across the WHOLE field view including the dead counter'd creature's
preserved net counters. The Lander-count §2 pin stays as
belt-and-suspenders. No engine divergence ever lived behind the
filter (verified by the now-strict probe passing). Pinned vanilla
fingerprint baselines are byte-unchanged (vanilla objects net 0
either way).

**Why it's OK / which scenarios make it not-OK / failure mode**: the
honest Effect-half-closes / full-card-stays-gated split established
by r51..r65 (Monoist..Seedship Impact). The closed half round-trips
byte-equal — the genuine real-EoE probe drives the ACTUAL parsed
Orbital Plunge printing's `spell_effect` cross-engine over three arms
(POSITIVE excess → Lander; NEGATIVE-counters excess → Lander, the §2
pin; NO-excess → NO Lander), each WHOLE-field byte-equal with a strict
`compare_fields == []` (the r70 `_net_counters` comparator fix closed
the former counters-blindness — no targeted-delta carve-out). The
NOT-OK scenario is
admitting the full Sorcery to the bench loader — structurally
impossible today (no spell-card admit path); no real-card-exposed
divergence.

**Fix scope estimate**: the Effect half (the first-creature damage +
the counters-inclusive at-resolve excess computation + the
conditional Lander rider) is **complete**. Flipping the full Sorcery
into the bench needs the separate shared spell-card-bridge lever (a
`CardDef` spell shape + a `_printing_is_bridge_spell` predicate) —
the same ~1-2-round shared substrate unblocking ALL remaining
Effect-uncovered Tier-A cards. Deferred to that lever.

**Impact estimate**: zero production strength cost (Orbital Plunge
not on the loader allowlist; no production exposure). The
real-card-coverage progress is the honest closure of the closeable
Effect half (Orbital Plunge leaves the Effect-uncovered Tier-A
bucket — its emitted class becomes a subset of the covered set) +
honest pinning of the loader-gated spell-card-bridge remainder.

**Pinned by**: 4 cross-engine bridge pins
(`tests/test_cross_engine_etb_triggers.py::test_bridge_orbital_plunge_basic_translation_amount_6`
+ `..._amount_rides_through` + `..._pid_dropped_equality` +
`..._composable_in_sequence`); 6 Rust regression pins
(`tests/test_parity_smoke.py::test_rust_orbital_*` — 2/2 → excess
4 → Lander; toughness-6 → excess 0 → NO Lander;
negative-counters-shrink-toughness → excess → Lander (§2);
positive-counters-grow-toughness → no excess → NO Lander (§2);
no-creature-anywhere via spell-push → silent no-op; Lander under
source-controller not active_player); 1 genuine real-EoE
cross-engine probe
(`tests/test_parity_smoke.py::test_cross_engine_real_eoe_orbital_plunge_excess_conditional_lander_parity`
— drives the actual parsed Orbital Plunge `spell_effect`
cross-engine, POSITIVE excess + NEGATIVE-counters excess (the §2
pin) + NO-excess arms, WHOLE field byte-equal with a strict
`compare_fields == []` (the r70 `_net_counters` comparator fix
closed the former counters-blindness — no targeted-delta carve-out;
verified live: the `_is_known_counters_blind_gy_diff` filter is
deleted and the probe asserts strict `compare_fields == []`); the
spell-card bench-admit lever intentionally NOT exercised).

---

## Depressurize — `DepressurizeEffect { power_penalty }` Effect half shipped byte-equal; full Instant stays loader-gated (no spell-card bench-admit path)

**Location**: `rust/src/cards.rs`
(`Effect::DepressurizeEffect { power_penalty: i32 }` single-field
payload variant + `parse_effect` arm `depressurize_effect` +
`effect_to_pydict` arm) + `rust/src/state_ops_resolve.rs` (the
resolve match arm beside the Orbital Plunge arm — any-creature scan
over BOTH bfs in ETB-timestamp order; the
`UeotModifier::PowerToughnessBonus { power: -pp, toughness: 0 }`
push; the counters-inclusive post-UEOT effective-power read; the
indestructible-respecting destroy tail). Bridge arm
`src/mtg_bot/parity/cross_engine.py` (`depressurize_effect`,
immediately above the `PHASE5_BRIDGE_ARMS` sentinel). Python class
(pre-existing, NOT new): `DepressurizeEffect`
(`src/mtg_bot/effects/bespoke.py:1531`).

**What the shortcut is**: Depressurize (~28,346 17lands decks) is an
`[Instant] {1}{B}` printing "Target creature gets -3/-0 until end of
turn. Then if that creature's power is 0 or less, destroy it." The
genuine parsed printing's `spell_effect` is
`DepressurizeEffect(power_penalty=3)`. Python's `resolve` does
`grant_pt_pump_ueot(power=-power_penalty, toughness=0)` then `if
effective_power(state, obj) <= 0: destroy(state, obj)`. The shipped
Rust variant carries `power_penalty` (rides through to Python; no
token pid — this arm mints nothing). The **deliberate divergence is
NOT in the closed Effect half** but in the **scope**: the **full
Depressurize Instant is NOT added to the production-deck loader
`_SAFE_*` allowlist** (no Instant/Sorcery bench-admit path).

**Verified deviation from `PumpTargetCreatureUntilEOT` (pinned)**:
Python's `DepressurizeEffect.legal_targets` is *any creature*
(`is_creature`, NO controller restriction —
`effects/bespoke.py:1545-1552`), unlike the bare
`PumpTargetCreatureUntilEOT` arm which is controller-restricted. The
Depressurize arm therefore scans BOTH battlefields in ETB-timestamp
order (the centralized `state.battlefield` walk + the
deterministic-first convention). Pinned by a Rust regression that
confirms the source's OWN creature (the carrier) is a legal target.

**§2 counters-asymmetry (load-bearing, the mini-spec risk)**:
the conditional reads POST-UEOT EFFECTIVE power. Python's
`effective_power` (`game._compute_effective_pt`) folds the
just-pushed UEOT bonus AND `+1/+1` counters (CR 613 layer 7c+7d).
Rust's combat-side `effective_power` getter folds the UEOT bonus but
NOT counters.
<!-- R74-1 note: the "Rust's combat-side effective_power getter folds
UEOT but NOT counters" premise is now STALE — the round-74 R74-1/I23
slice closed the combat-side getter asymmetry (it folds counters
byte-equal with Python). This arm's PRIVATE file-isolated
re-derivation below is unaffected and stays correct; per-arm
file-isolation remains the right pattern. See RUST_PARITY_GAPS I23. -->
To stay byte-equal with the Python SoT, this arm
computes the effective power with the counters-INCLUSIVE formula
re-derived privately (file-isolation) — `base =
ueot_base_pt_override().p OR printed_power`, plus `obj.counters`,
plus `obj.ueot_power_bonus()` (which already includes the −pp just
pushed) — NOT the combat-side getter. A counters-omitting impl would
silently flip the destroy condition on a counter'd target. Pinned
both directions: a printed 2/2 with +2 counters → post-UEOT power
2+2−3 = 1 > 0 → SURVIVES (a combat-getter read would compute 2−3 =
−1 and wrongly destroy); a printed 4/4 with −2 counters → 4−2−3 =
−1 ≤ 0 → destroyed (a combat-getter read would compute 4−3 = 1 and
wrongly survive). The genuine real-EoE probe's COUNTERS arm pins the
+2-counter SURVIVAL cross-engine.

**Indestructible (CR 702.12, pinned)**: Python's `turn.destroy`
suppresses the destroy for an indestructible creature (the pump
still applies). The Rust arm checks
`printing.keywords.contains("indestructible") ||
obj.ueot_has_keyword("indestructible")` before the conditional
destroy — the creature is debuffed but survives. Pinned by a Rust
regression (indestructible 1/1 → eff power −2 ≤ 0 → pumped, NOT
destroyed).

**Comparator counters-blindness — CLOSED (round-r70).** This entry
formerly noted the same comparator limitation as Orbital Plunge,
generalized: `_zone_signature` read `getattr(obj, "counters", 0)`
(structurally `0` for every Python `GameObject`, which carries split
`plus_one_counters`/`minus_one_counters` ints) while Rust emitted the
real signed net — so a counter'd object spuriously diffed in ANY zone
(the Depressurize +2-counter SURVIVAL arm on the **battlefield**, a
living counter'd creature, exactly as Orbital Plunge on the
**graveyard**, a dead one). The probe worked around it with the
broadest targeted-delta filter in the suite (`_known_blind`, stripping
counters-only diffs across battlefield/graveyard/hand/library/exile),
weakening divergence detection across every zone. **Round-r70 fixed
the comparator** (`scripts/parity_smoke.py` `_net_counters`): slot 4
now derives the signed net counter, byte-aligned with Rust's
`GameObject.counters`. The `_known_blind` filter was deleted; the
Depressurize probe now asserts the **full `compare_fields == []`**
across the WHOLE field view including the surviving +2-counter
creature on the battlefield. The SURVIVAL/DESTROY §2 pin stays as
belt-and-suspenders. No engine divergence ever lived behind the
filter (verified by the now-strict probe passing).

**Why it's OK / which scenarios make it not-OK / failure mode**: the
honest Effect-half-closes / full-card-stays-gated split established
by r51..r65 (Monoist..Orbital Plunge). The closed half round-trips
byte-equal — the genuine real-EoE probe drives the ACTUAL parsed
Depressurize printing's `spell_effect` cross-engine over two arms
(PLAIN 2/2 → eff power −1 → destroyed; +2-counter → eff power 1 →
SURVIVES, the §2 pin), each WHOLE-field byte-equal with a strict
`compare_fields == []` (the r70 `_net_counters` comparator fix closed
the former counters-blindness — no targeted-delta carve-out). The
NOT-OK scenario is
admitting the full Instant to the bench loader — structurally
impossible today (no spell-card admit path); no real-card-exposed
divergence.

**Fix scope estimate**: the Effect half (the any-creature UEOT
−pp/−0 debuff + the counters-inclusive post-UEOT
conditional-destroy, indestructible-respecting) is **complete**.
Flipping the full Instant into the bench needs the separate shared
spell-card-bridge lever — the same ~1-2-round shared substrate
unblocking ALL remaining Effect-uncovered Tier-A cards. Deferred.

**Impact estimate**: zero production strength cost (Depressurize not
on the loader allowlist; no production exposure). The
real-card-coverage progress is the honest closure of the closeable
Effect half (Depressurize leaves the Effect-uncovered Tier-A
bucket) + honest pinning of the loader-gated spell-card-bridge
remainder.

**Pinned by**: 4 cross-engine bridge pins
(`tests/test_cross_engine_etb_triggers.py::test_bridge_depressurize_basic_translation_pp3`
+ `..._power_penalty_rides_through` + `..._default_pp_when_absent` +
`..._composable_in_sequence`); 7 Rust regression pins
(`tests/test_parity_smoke.py::test_rust_depressurize_*` — 2/2 →
destroyed; 5/5 → survives with UEOT mod; +2-counter → survives (§2);
−2-counter → destroyed (§2); indestructible → pumped not destroyed
(CR 702.12); ANY-creature scan reaches the source's own creature
(the verified non-controller-restricted deviation); no-creature
silent no-op via spell-push); 1 genuine real-EoE cross-engine probe
(`tests/test_parity_smoke.py::test_cross_engine_real_eoe_depressurize_debuff_then_conditional_destroy_parity`
— drives the actual parsed Depressurize `spell_effect`
cross-engine, PLAIN-destroy + +2-counter-SURVIVES (the §2 pin)
arms, WHOLE field byte-equal with a strict `compare_fields == []`
(r70 `_net_counters` comparator fix — no targeted-delta carve-out);
the spell-card bench-admit lever intentionally NOT exercised).

---

## Biosynthic Burst — `BiosynthicBurstEffect` (unit) Effect half shipped byte-equal; full Instant AUTO-JOINS the spell-card-bridge admit set; counter-doubling / Terrasymbiosis fan-out NOT replicated (mirrors the proven `PutPlusOneCounterOnCreatureYouControl` sibling)

**Location**: `rust/src/cards.rs`
(`Effect::BiosynthicBurstEffect` field-free UNIT variant +
`parse_effect` arm `biosynthic_burst_effect` + `effect_to_pydict`
arm) + `rust/src/state_ops_resolve.rs` (the resolve match arm beside
the Depressurize arm — controller-restricted first-creature scan;
`obj.counters.saturating_add(1)`; the
`UeotModifier::GrantKeyword { keyword }` push for
{reach, trample, indestructible}; `obj.tapped = false`). Bridge arm
`src/mtg_bot/parity/cross_engine.py` (`biosynthic_burst_effect`,
immediately above the `PHASE5_BRIDGE_ARMS` sentinel). Python→dict
reverse-serializer leaf
`src/mtg_bot/parity/trajectory.py` (`_python_spell_effect_to_dict`
`_leaf`). Python class (pre-existing, NOT new):
`BiosynthicBurstEffect` (`src/mtg_bot/effects/bespoke.py:1466`).

**What the shortcut is**: Biosynthic Burst (~22,799 17lands decks)
is an `[Instant] {1}{G}` printing "Put a +1/+1 counter on target
creature you control. It gains reach, trample, and indestructible
until end of turn. Untap it." The genuine parsed printing's
`spell_effect` is `BiosynthicBurstEffect()` (field-free). Python's
`resolve` does `add_plus_one_counters(state, obj, 1)` then
`ApplyEffect(GrantKeywords({reach,trample,indestructible}),
EndOfTurn()).resolve(...)` then `obj.tapped = False`. The shipped
Rust unit variant fuses the three on one own target. The Effect
half closes byte-equal; UNLIKE Depressurize (which stayed
loader-gated), the **full Biosynthic Burst Instant AUTO-JOINS the
spell-card-bridge bench-admit set** — the lever's
`_printing_is_bridge_simple_spell` guardrail queries the LIVE
covered set + round-trips the reverse serializer, so adding the
Effect + bridge + the reverse-serializer leaf flips the printing in
(no hardcoded card list — the §2 auto-grow teeth).

**Verified deviation from Depressurize (pinned)**: Python's
`BiosynthicBurstEffect.legal_targets` IS controller-restricted
(`o.controller_id == controller_id`,
`effects/bespoke.py:1483-1485`) — UNLIKE `DepressurizeEffect` whose
`legal_targets` is ANY creature. So the Rust arm walks ONLY the
source-controller's battlefield (the same controller-only
first-creature scan `PutPlusOneCounterOnCreatureYouControl`
`:7721` and `GrantKeywordsToTargetCreatureUntilEOT` `:10509` use),
NOT both bfs via `bf_iter_etb_sorted`. Pinned by a Rust regression
that confirms an opponent's creature is NOT a legal pick (silent
no-op).

**§2 simplification — counter-doubling / Terrasymbiosis NOT
replicated (mirrors the already-cross-engine-proven sibling, NOT
new debt)**: Python's `add_plus_one_counters`
(`src/mtg_bot/game.py:2023`) (1) applies counter-doubling
replacement effects via `_counter_doubling_factor` and (2) fires
`fire_counters_added_to_your_creature_triggers` (Terrasymbiosis
"whenever you put one or more +1/+1 counters on a creature you
control" observer triggers). The Rust arm — EXACTLY like its
already-cross-engine-proven sibling
`PutPlusOneCounterOnCreatureYouControl`
(`rust/src/state_ops_resolve.rs:7780`, plain
`obj.counters.saturating_add(delta)`) — does a plain
`saturating_add(1)` only, replicating neither. **Why it's OK**: no
counter-doubling replacement permanent and no "counters added to
your creature" observer trigger exists in the EoE pool, so on the
real pool the simplification is bit-equal Python↔Rust (the proven
sibling arm ships under exactly this rationale). The Python
`obj.plus_one_counters` ↔ Rust signed-scalar `obj.counters` mapping
is the established byte-equal cross-engine relation
(`cross_engine.py` ~:1276). **Failure mode**: if a future
EoE-superset pool ever adds a +1/+1-counter doubler or a
counters-added trigger, this arm (and the sibling) would underwrite
counters / skip the observer trigger vs Python — a divergence.
**Fix-scope**: port `_counter_doubling_factor` +
`fire_counters_added_to_your_creature_triggers` into the Rust
counter-add path (shared with the sibling — one change covers both
arms); ~1 Rust round. **Impact estimate**: zero production strength
cost (no doubler / no counters-added trigger in EoE; identical to
the long-shipped sibling's accepted scope).

**Honest split (§2)**: the Effect half closes + is genuinely probed
(counter + 3-keyword-UEOT + untap composite, byte-equal incl. the
cleanup-step UEOT keyword expiry — the round-39 SBA-on-0/0 class).
The full `{1}{G}` Instant auto-joins the spell-card-bridge admit set
(pinned). Mirrors the r51..r73 Effect-half precedent + the round-73
spell-card-bridge auto-grow precedent.

**Pinned by**: 5 Rust regression pins
(`tests/test_parity_smoke.py::test_rust_biosynthic_burst_*` —
counter+keywords+untap composite; keywords expire at cleanup while
the +1/+1 counter is permanent (UEOT-drain / round-39 SBA-on-0/0
class); controller-restricted scan (opponent creature NOT picked,
the verified deviation); no-own-creature silent no-op) + 1 admit-set
auto-grow pin
(`test_biosynthic_burst_auto_joins_spell_card_bridge_admit_set` —
covered+bridged + reverse-serializer round-trip ⇒
`_printing_is_bridge_simple_spell` True, no hardcoded list) + 1
genuine real-EoE cross-engine probe
(`test_cross_engine_real_eoe_biosynthic_burst_counter_kw_untap_parity`
— drives the actual parsed Biosynthic Burst `spell_effect`
cross-engine on a tapped own 2/2 + an untouched opponent 5/5, WHOLE
field byte-equal with a strict `compare_fields == []` both
post-resolve AND after the cleanup-step UEOT drain — no
targeted-delta carve-out).

---

## Focus Fire — `FocusFireEffect { base }` Effect half shipped byte-equal (the FIRST effect-resolve arm to READ combat-declaration state); full Instant AUTO-JOINS the spell-card-bridge admit set; combat predicate byte-equal-by-construction via the proven declare-attacker/blocker primitives

**Location**: `rust/src/cards.rs`
(`Effect::FocusFireEffect { base: i32 }` single-int-field variant +
`parse_effect` arm `focus_fire_effect` + `effect_to_pydict` arm) +
`rust/src/state_ops_resolve.rs` (the resolve match arm beside the
Biosynthic Burst / Depressurize Tier-A arms — 5-zone source-
controller resolution; the set-union denominator single-bf-pass;
the `state.attackers` / `state.blockers` combat predicate; the
`bf_iter_etb_sorted` deterministic-first ANY-creature target scan;
`obj.damage.saturating_add`). Bridge arm
`src/mtg_bot/parity/cross_engine.py` (`focus_fire_effect`,
immediately above the `PHASE5_BRIDGE_ARMS` sentinel). Python→dict
reverse-serializer leaf `src/mtg_bot/parity/trajectory.py`
(`_python_spell_effect_to_dict` `_leaf`). Python class
(pre-existing, NOT new): `FocusFireEffect`
(`src/mtg_bot/effects/bespoke.py:1753`).

**What the shortcut is**: Focus Fire (~23,211 17lands decks) is an
`[Instant] {W}` printing "Focus Fire deals X damage to target
attacking or blocking creature, where X is 2 plus the number of
creatures and/or Spacecraft you control." The genuine parsed
printing's `spell_effect` is `FocusFireEffect(base=2)`. Python's
`_amount` is `base + sum(1 for o in state.battlefield if
o.controller_id == controller_id and (o.printing.is_creature or
o.printing.is_spacecraft))`; `resolve` re-checks
`_slot_target_still_legal` (CR 608.2b) then `_apply_damage`. The
shipped Rust arm is the FIRST effect-resolve arm to READ
combat-declaration state. The Effect half closes byte-equal; like
Biosynthic Burst (and unlike Depressurize) the **full Focus Fire
Instant AUTO-JOINS the spell-card-bridge bench-admit set** — the
lever's `_printing_is_bridge_simple_spell` guardrail queries the
LIVE covered set + round-trips the reverse serializer, so adding
the Effect + bridge + the reverse-serializer leaf flips the
printing in (no hardcoded card list — the §2 auto-grow teeth).

**The set-union denominator (the §2 subtle-divergence pin, NOT a
shortcut — a correctness invariant)**: the denominator is computed
as a SINGLE pass over the source-controller's battlefield, +1 per
object whose `card_types` contains "Creature" OR "Spacecraft". A
dual-typed Artifact Creature Spacecraft is ONE Vec element →
counts ONCE (the `||` is on the object), bit-for-bit Python's `sum`
with the `or` on `o.printing`. A two-scan creature-count +
spacecraft-count sum would silently over-count a dual-typed
permanent; the Rust arm deliberately does NOT do that. Pinned by
`test_rust_focus_fire_dual_typed_counts_once_set_union`.

**The combat predicate — byte-equal BY CONSTRUCTION (verify-first
confirmed)**: a creature is attacking iff its id is in
`state.attackers` (`Vec<u32>`); blocking iff its id appears as a
`blocker_id` in `state.blockers` (`Vec<(attacker_id,
blocker_id)>`). This is the EXACT pair the `declare_attacker`
(`state_ops_combat.rs:681`) / `declare_blocker` (`:772`)
primitives push — the SAME primitives the cross-engine
`step_both` `declare_attackers` / `declare_blockers` path drives,
proven byte-equal vs Python's `obj.attacking` /
`obj.blocking is not None` by the long-standing multi-blocker
cross-engine probes (`multi_blocker_deckspec` /
`multi_block_combat_selector`). The genuine real-EoE probe DRIVES
that real multi-blocker combat (steps 0..195, zero divergences)
and casts the actual Focus Fire while combat is live, so the
predicate's equivalence is genuinely exercised end-to-end, not
asserted. **Why it's OK**: no engine-side combat-state divergence
exists (the multi-blocker probes are the standing evidence; this
slice adds a direct mid-combat cast that re-proves it for the
Focus Fire path). **Failure mode**: if a future change made
Python's `obj.attacking`/`obj.blocking` and Rust's
`attackers`/`blockers` diverge, the multi-blocker probes AND the
Focus Fire genuine probe would BOTH fail loudly (no silent
masking). **Fix-scope / impact**: n/a — no divergence; this is a
correctness-preserving reuse of an already-proven byte-equal pair.

**Target scan is NOT controller-restricted (verified, the
Depressurize shape NOT the Biosynthic Burst shape)**: Python's
`FocusFireEffect` target filter is `IsCreature ∧ (IsAttacking ∨
IsBlocking)` — ANY creature, NOT `o.controller_id ==
controller_id`. So the Rust arm scans BOTH bfs via
`bf_iter_etb_sorted` (the `DepressurizeEffect` ANY-creature
deterministic-first shape), NOT the controller-only Biosynthic
Burst scan. The spell-card-bridge `_PickFirstLegalTargetAgent` /
Python's centralized `state.battlefield` walk pick the SAME
deterministic-first attacking-or-blocking creature — the
established convention, pinned by the genuine probe (target = the
first att/blk creature in centralized bf order on BOTH engines).
No-attacking-or-blocking-creature → silent fizzle (CR 608.2b;
Python's `_slot_target_still_legal` early return), pinned by
`test_rust_focus_fire_no_attacker_or_blocker_silent_fizzle`.

**Honest split (§2)**: the Effect half closes + is genuinely
probed (a real combat phase is DRIVEN — attackers/blockers
declared byte-equal via the multi-blocker-proven path — then the
actual parsed Focus Fire is cast + resolved, WHOLE field
`compare_fields == []`). The full `{W}` Instant auto-joins the
spell-card-bridge admit set (pinned). Mirrors the r51..r74
Effect-half precedent + the round-73/74 spell-card-bridge
auto-grow precedent.

**Pinned by**: 6 Rust regression pins
(`tests/test_parity_smoke.py::test_rust_focus_fire_*` —
base+count lethal-to-attacker; the dual-typed set-union pin;
targets a blocking creature; no-attacker/blocker silent fizzle;
base offset present with zero creatures; denominator is the
source-controller's board not the active player's) + 4 bridge
pins (`tests/test_cross_engine_etb_triggers.py::test_bridge_focus_
fire_*` — basic translation; base defaults to 2 when elided;
Sequence-composable; bidirectional reverse-serializer round-trip)
+ 1 admit-set auto-grow pin
(`test_focus_fire_auto_joins_spell_card_bridge_admit_set`) + 1
genuine real-EoE cross-engine probe
(`test_cross_engine_real_eoe_focus_fire_drives_combat_then_casts_parity`
— drives the real multi-blocker combat to a LIVE
attackers=[5]/blockers=[(5,11),(5,9)] state byte-equal, casts the
actual parsed Focus Fire `spell_effect` mid-combat, WHOLE field
`compare_fields == []` post-resolve incl. the lethal SBA on the
targeted blocking Bears — no targeted-delta carve-out).

---

## Diplomatic Relations — `DiplomaticRelationsEffect` (unit) Effect half shipped byte-equal; full Instant AUTO-JOINS the spell-card-bridge admit set via the Phase-2 2-slot grammar; vigilance-via-UEOT-keyword + counters-inclusive effective-power mirror the proven siblings (NO static-anthem / switch_pt fold — bridge-pool-empty by construction)

**Location**: `rust/src/cards.rs`
(`Effect::DiplomaticRelationsEffect` field-free unit variant +
`parse_effect` arm `diplomatic_relations_effect` + `effect_to_dict`
arm) + `rust/src/state_ops_resolve.rs` (the resolve match arm beside
the Focus Fire / Biosynthic Burst / Depressurize Tier-A arms —
5-zone source-controller resolution; the 2-slot payload-target reads
off `current_resolve_payload_target_id` /
`current_resolve_payload_target_id_2`; the `PowerToughnessBonus
{+1,0}` + `GrantKeyword{"vigilance"}` UEOT pushes; the
`DepressurizeEffect` counters-inclusive effective-power re-derivation;
`obj.damage.saturating_add`). 2-slot StackItem substrate
`rust/src/state.rs` (`StackItem.target_obj_id_2` +
`new_spell_with_targets`); 2-slot cast-time bind
`rust/src/state_ops_cast.rs` (`cast_spell_noncreature`). Bridge arm
`src/mtg_bot/parity/cross_engine.py` (`diplomatic_relations_effect`,
immediately above the `PHASE5_BRIDGE_ARMS` sentinel). Python→dict
reverse-serializer leaf `src/mtg_bot/parity/trajectory.py`
(`_python_spell_effect_to_dict` `_leaf`). Python class
(pre-existing, NOT new): `DiplomaticRelationsEffect`
(`src/mtg_bot/effects/bespoke.py:1884`).

**What the shortcut is**: Diplomatic Relations (~29,818 17lands
decks) is a `[Instant] {2}{G}` printing "Target creature you control
gets +1/+0 and gains vigilance until end of turn. It deals damage
equal to its power to target creature an opponent controls." — the
SOLE 2-slot heterogeneous-target Tier-A spell
(`target_count_range()==(2,2)`,
`target_slot_kinds()==('my_creature','creature')`). The genuine
parsed `spell_effect` is `DiplomaticRelationsEffect()` (field-free).
Python's `resolve` pumps slot-0 +1/+0 + grants vigilance via
`ApplyEffect(GrantKeywords({'vigilance'}), EndOfTurn())`, then deals
`effective_power(state, slot0)` (post-pump) damage to slot-1 via
`_apply_damage`. The Effect half closes byte-equal; like Biosynthic
Burst / Focus Fire the **full Diplomatic Relations Instant
AUTO-JOINS the spell-card-bridge bench-admit set** — the lever's
`_printing_is_bridge_simple_spell` guardrail queries the LIVE
covered set + round-trips the reverse serializer + (Phase 2) the
surgical 2-slot widening, so adding the Effect + bridge + the
reverse-serializer leaf + the guardrail widening flips the printing
in (admit set 6→7; no hardcoded list — the §2 auto-grow teeth).

**§2 simplification (mirrors the proven siblings, NOT new debt)**:
two simplifications, each already cross-engine-proven byte-equal on
the real bridge-admitted pool:

1. **Vigilance via `UeotModifier::GrantKeyword` (lowercase)** instead
   of Python's `ApplyEffect(GrantKeywords, EndOfTurn())`
   continuous-effect path — the EXACT push shape the
   already-cross-engine-proven `BiosynthicBurstEffect` /
   `GrantKeywordsToTargetCreatureUntilEOT` arms use; their
   continuous-effect↔ueot_modifiers equivalence is pinned byte-equal,
   and both drain at the cleanup step on both engines.
2. **Post-pump effective power read as the `DepressurizeEffect`
   counters-inclusive formula** (`base = ueot_base_pt_override().p
   OR printed_power`, `+ obj.counters`, `+ obj.ueot_power_bonus()`)
   rather than Python's full `_compute_effective_pt` layer-7 walk.
   Identical to the Depressurize arm's already-proven conditional
   read. This omits layer-7c static anthems + 7e `switch_pt` — but
   the spell-card-bridge bench loader admits ONLY basic lands +
   simple creatures + the bridged spells, so NO static anthem / no
   switch_pt continuous effect can be on the battlefield in any
   bench game (the exact assumption the Depressurize arm relies on,
   cross-engine-proven byte-equal). Python's `effective_power` is
   NOT clamped to 0, so the damage is applied UNCONDITIONALLY (no
   `amount > 0` gate) to byte-mirror Python's `obj.damage += amount`.

**Why it's OK**: each simplification is the EXACT shape of an
already-cross-engine-proven sibling on the same admitted pool;
neither introduces a path the other engine models differently. The
2-slot binding uses the same no-callback first-legal convention as
Phase 1 (slot 0 = first caster creature, slot 1 = first non-caster
creature, in `bf_iter_etb_sorted` order = Python's
`_select_spell_targets` per-slot-kind first-legal). Target
re-validation at resolve (CR 608.2b) mirrors Python exactly: slot-0
illegal → WHOLE effect fizzles (no pump, no damage); slot-1 illegal
→ pump applied, damage skipped.

**Failure mode**: a bench game with a static power-anthem OR a
`switch_pt` continuous effect on the slot-0 creature would diverge
(Rust's counters-inclusive read omits layers 7c-static / 7e) — but
such a permanent is structurally impossible in the spell-card-bridge
bench (loader admits only basic lands + simple creatures + bridged
spells; same as Depressurize). A future probe that needs a
non-first target on either slot would diverge (the agent has no say
— shared with the Phase-1 deterministic-first entry).

**Fix scope estimate**: fold the static-anthem / switch_pt layers
into the Rust effective-power read IF the bench loader ever admits a
static-pump permanent (a shared follow-on with Depressurize, same
formula site). Thread an agent target decision for the 2 slots for
the non-first-target case.

**Impact estimate**: +1 Tier-A card (Diplomatic Relations) flips
loader-drop → bench-admit; ~29,818 17lands decks. The admit set
grows 6→7. Effect-half is genuinely probed (a 2-slot real
cast→resolve is DRIVEN byte-equal incl. the lethal SBA on the
damaged slot-1 creature — no targeted-delta carve-out).

---

## Cross-engine probe harness — `_zone_signature` counters-blindness FIXED + the symmetric-filler pattern for full `compare_fields` (round-r70)

**Location**: `scripts/parity_smoke.py` `_zone_signature` /
`_net_counters` (the new helper); the cross-engine field-view
comparator `compare_fields` reads it via
`cross_engine.build_python_field_view`. Probe-side pattern in
`tests/test_parity_smoke.py` (Orbital Plunge / Depressurize / both
Seedship Agrarian genuine probes).

**What the limitation was / what changed**: the cross-engine
field-view comparator's per-object 8-tuple slot 4 (`counters`) read
`getattr(obj, "counters", 0)`. A Python `GameObject` carries NO
`counters` attribute — it tracks split
`plus_one_counters`/`minus_one_counters` ints — so the slot was
**structurally `0` for every Python object** while Rust emits the
real signed net (`GameObject.counters: i32`). This blinded BOTH the
cross-engine `compare_fields` AND the `hash_state` fingerprint to ANY
counter divergence on a counter'd permanent in ANY zone. Genuine
probes that put a counter'd creature in play (Orbital Plunge's dead
−4-counter creature; Depressurize's surviving +2-counter creature)
had to strip the spurious counters-only diffs with hand-rolled
targeted-delta filters (`_is_known_counters_blind_gy_diff`,
`_known_blind`) — which weakened divergence detection across whole
zones (the audit-flagged "targeted-delta instead of full
`compare_fields`" signal-quality degradation). **Round-r70 derives
the signed net** in `_net_counters` (`plus_one_counters −
minus_one_counters`, with an explicit `counters` attr winning when
present for the Rust dict-shim / future-unified path), byte-aligned
with Rust. The targeted-delta filters were deleted; those probes now
assert strict `compare_fields == []`.

**The filler-injection object-id-skew pattern (deprecate for new
probes)**: `register_and_inject_object(dict, controller, zone)` is a
Rust-only pymethod — it appends a printing to the *Rust* registry
(`printing_id = reg.printings.len()`) and allocates an object id as
`1 + max(obj.id across all zones)`. A probe that builds states from
an empty/seeded `DeckSpec` and then injects a token-printing **filler
into the Rust library only** (the `register_and_inject_object(
token_dict, 1, 1)` idiom) leaves Python without the matching object
→ a `library_p1` shape diff + a shifted Rust `next_id` allocator
(every later object id off-by-one) → full `compare_fields` cannot be
asserted, forcing targeted-delta probes. The clean primitives, in
order of preference:
1. **The `_seat_token_printings` `DeckSpec` path** (loader-seated
   token CardDef registered symmetrically on BOTH engines via
   `setup_matched_game` / `build_matched_states`) — zero skew, full
   `compare_fields == []`. Use this for new token-creation probes
   (Gravpack Monoist / the audit `create_token_tapped` probe are the
   reference shape).
2. **Symmetric mirror**: if a probe must use
   `register_and_inject_object`, mirror EVERY Rust inject on the
   Python side in the SAME order with `py_state.new_object(...)` so
   the id sequences stay in lockstep — and match Rust's documented
   per-zone insertion convention (LIBRARY = `insert(0, ...)` /
   library TOP per `state_ops_resolve.rs:11522`, not tail
   `append`; HAND/BATTLEFIELD/GRAVEYARD = tail). Force
   `summoning_sick=False` on injected objects (Rust seats False;
   Python `new_object` defaults True). Both Seedship Agrarian genuine
   probes were migrated to this and now assert full
   `compare_fields == []`.

**Why it's OK / failure mode**: this is a pure comparator-correctness
improvement — it can only make the cross-engine / fingerprint signal
STRONGER (it never masks; it un-masks). Pinned vanilla fingerprint
baselines are byte-unchanged (vanilla objects have net 0 either way).
A probe still on the targeted-delta pattern (the many Galactic
Wayfarer / Beamsaw-class create-Lander probes that stop at the
documented Rust-lane token-registration boundary) is NOT a
regression — it is correctly narrowed where a genuine Rust-lane gap
remains; converting those needs the Rust token-registration follow-up
(out of scope here), not a comparator change. New probes MUST prefer
the clean primitives above; do NOT add new filler-skew targeted-delta
probes.

**Fix scope estimate**: comparator fix COMPLETE (one helper); the
audit-named token-injection probes migrated (4: Orbital Plunge,
Depressurize, Seedship Agrarian ×2). Remaining create-token
targeted-delta probes convert as the Rust token-registration boundary
closes (Rust-agent follow-up).

**Impact estimate**: zero production strength cost (probe-harness
only). Strictly increases parity-signal QUALITY campaign-wide — every
migrated probe now catches a real divergence ANYWHERE in the field
view, not just inside a narrow asserted window.

---

## Spell-card-bridge lever Phase 1 — bench-admit is single-required-target-only

**Round-76 update (Phase 2 — Diplomatic Relations, the 2-slot
heterogeneous-target grammar).** Phase 2 widens
`_printing_is_bridge_simple_spell` to ALSO admit EXACTLY the one
2-slot shape `(2,2)` / `('my_creature','creature')` (Diplomatic
Relations) — the surgical widening, NOT a blanket "any 2-target"
widen (a synthetic `(2,2)` with a different slot-kind tuple stays
positively declined; pin #12's negative control). The admit set grew
**6→7** (the +1 is Diplomatic Relations). The single-target-only
framing below remains true for every OTHER multi-slot shape (3+
slots, other 2-slot kind-tuples, "any number of targets") and for
modal / X / kicker / warp / additional-cost. Close Encounter STAYS
Tier-C (covered-set gate). Read this sub-section first; the Phase-1
description below is preserved verbatim for the single-target lane.

**Location**: `src/mtg_bot/parity/trajectory.py`
(`_printing_is_bridge_simple_spell` + its OR-chain entry in
`_filter_deck_to_bridge_supported` + its `_printing_to_card_def`
arm).

**What the shortcut is**: the spell-card-bridge lever (round-70,
spec `docs/SPELL_CARD_BRIDGE_PHASE1_DESIGN.md`) admits ONLY a pure
single-required-target (`target_count_range()==(1,1)`),
homogeneous-slot (`target_slot_kinds()==()`), single-mode
Instant/Sorcery whose bespoke Effect close has landed
(covered+bridged) AND whose effect round-trips the
`_python_spell_effect_to_dict` reverse serializer. Multi-slot
(Diplomatic Relations — `(2,2)`/heterogeneous slots), modal
(`ModalChooseOne`), X-cost (`mana_cost.x_pips>0`), kicker/impending,
warp-entangled (`warp_cost is not None`), additional-cost-choice
(Close Encounter) spells stay filtered.

**Why it's OK**: each declined sub-shape is a separate
phase/substrate and is *positively rejected* (no silent
mistranslation — the round-38-E5 / count-chasing anti-pattern this
discipline exists to prevent). Diplomatic Relations is Phase 2 of
this lever (the 2-slot grammar). Close Encounter stays Tier-C
(`CloseEncounterEffect` not covered+bridged — the robust decline;
note its live `warp_cost is None` at the implement HEAD, so the spec
ADDENDUM's "warp_cost is not None" Close-Encounter reason is stale —
the covered-set gate is the load-bearing teeth, verify-first
corrected).

**Failure mode**: none today — the rejected cards never enter the
bench (they are stripped by the loader filter exactly as every
non-bridge-supported card is). A future probe needing a declined
shape on the bench would simply not find it admitted.

**Fix scope estimate**: Phase 2 (the 2-slot grammar for Diplomatic
Relations — extend `StackItem.target_obj_id` to a 2-slot payload) +
later phases for modal / X / additional-cost-choice.

**Impact estimate**: the lever flips the covered+bridged pid-free
single-target Tier-A spells from loader-drop -> bench-admit (at the
implement HEAD: Radiant Strike + Depressurize; the set auto-grows as
Focus Fire / Biosynthic Burst close, and as a Lander-spell-token-
seating sub-substrate admits Seedship Impact / Orbital Plunge — see
the dedicated entry below).

---

## Spell-card-bridge lever Phase 1 — Rust spell-target binding via deterministic-first on the spell StackItem

**Round-76 update (Phase 2 — 2-slot deterministic-first binding).**
For the 2-slot grammar (Diplomatic Relations) `cast_spell_
noncreature` binds slot 0 = first caster-controlled creature + slot
1 = first non-caster-controlled creature off the SAME
`bf_iter_etb_sorted` scan, mirroring Python's `_select_spell_targets`
per-`slot_kinds` first-legal pick (slot 0 from the `my_creature`
pool, slot 1 from the `creature` pool — both in `state.battlefield`
order, the cross-engine-proven equivalent of `bf_iter_etb_sorted`).
Same no-callback first-legal shortcut, generalized to two slots; the
agent still has no say. Failure mode / fix-scope identical (a probe
needing a non-first target on either slot would diverge; the fix is
the agent target-decision follow-on). Impact 0 today.

**Location**: `rust/src/state_ops_cast.rs`
(`cast_spell_noncreature` — the cast-time `bf_iter_etb_sorted`
first-creature scan bound onto `StackItem.target_obj_id`, plus the
Phase-2 2-slot partition onto `target_obj_id` + `target_obj_id_2`) +
`rust/src/state_ops_resolve.rs` (the `current_resolve_payload_
target_id` [+ Phase-2 `_2`] swap for `StackItemKind::Spell` in BOTH
`resolve_top_of_stack` and `resolve_top_of_stack_pause`).

**What the shortcut is**: Rust binds a single-target spell's target
via the no-callback deterministic-first scan at cast time (no agent
`choose_target` decision for spells), mirroring the campaign-wide
first-legal-target convention the harness drives (the ~30
trigger/activated probes + the `_PickFirst*` shims; Python's
`_select_spell_targets` coerces a `None`/declined agent pick to the
first legal pool entry, and the bench installs
`_PickFirstLegalTargetAgent`). The closed Tier-A spell Effect arms
(`DepressurizeEffect` etc.) self-scan the battlefield first-creature
and IGNORE `current_resolve_payload_target_id` — the swap is a
correct no-op for them; it is the forward substrate for arms that
opt into the payload-target convention (today only
`EquipToTargetCreatureYouControl`).

**Why it's OK**: the bench strategy + the cross-engine harness both
use first-legal; Python's `legal_targets[0]` == Rust's
`bf_iter_etb_sorted` first-creature is the EXACT equivalence the
closed Tier-A real-EoE probes already proved byte-equal (they drive
the actual parsed `spell_effect`). The save/restore bracketing of
the swap (mirroring the existing `saved_ctrl` controller swap)
prevents any leak across resolution boundaries.

**Failure mode**: a future probe needing a NON-first target on a
spell would diverge (the agent has no say in the spell's target).

**Fix scope estimate**: thread an agent target decision for spells
(a larger follow-on, same shape as the trigger target decision /
the Phase-2 2-slot grammar).

**Impact estimate**: 0 today (every Phase-1 card + the bench /
cross-engine harness use first-legal).

---

## Tier-C target-seating sub-substrate — deterministic no-agent push-time target seat for SAFE targeted triggered abilities (lever-a: Sunset Saboteur + Exosuit Savior)

**Location**: `rust/src/state_ops_resolve.rs`
(`first_legal_trigger_target` next to `push_triggered_ability` — the
gated push-time first-legal seat into the EXISTING
`TriggerPayload.target_id` via `new_trigger_with_target`; the
`Effect::PutPlusOneCounterOnOpponentsCreature` and
`Effect::ReturnTargetPermanentYouControlToOwnersHand` resolve arms
reading `current_resolve_payload_target_id` with a CR 608.2b
re-legality check; `lever_trigger_requires_target` distinguishes the
`count_min>=1` skip-push-fizzle (Sunset Saboteur) from the
`count_min==0` push-with-no-target no-op (Exosuit Savior)) +
`src/mtg_bot/actions.py` (`_put_triggered_ability_on_stack` — the
`controller.agent is None` branch's gated `pool[0]` seat) +
`src/mtg_bot/parity/trajectory.py`
(`_is_target_seated_safe_trigger` — the surgical gate).

**What the shortcut is**: real MTG picks a triggered ability's
target when it is put on the stack (CR 603.3d) by the ability's
controller's *choice*. The substrate replaces that choice with a
deterministic first-legal pick (no agent): the smallest-bf-index
object that passes the slot filter, scanning `state.players` in
ascending seat index then each player's `battlefield` Vec in
insertion order (Python's `Effect._enumerate_for_filter` order; the
`_PickFirstLegalTargetAgent` shim's pick). For Sunset Saboteur
(`ATTACKS / IsSelf / PutPlusOneCounterOnOpponentsCreature`,
`count_min=1`) that is the first creature an opponent of the
source's controller controls; no eligible target ⇒ the trigger
fizzles (CR 603.3c — not pushed) byte-equal on both engines. For
Exosuit Savior (`ENTERS / IsSelf /
ReturnTargetPermanentYouControlToOwnersHand`, `count_min=0` — the
optional-bounce edge) that is the first non-source permanent the
source's controller controls; no eligible permanent ⇒ the trigger
is pushed with NO target and the optional resolves as a no-op
(byte-equal with Python's `targets=()` `Bounce.resolve`
early-return — the optional is *declined*, NOT fizzled, the distinct
`count_min==0` semantics). The seat is **gated**
(`_is_target_seated_safe_trigger` / `first_legal_trigger_target`'s
per-variant match) so it fires ONLY for the lever-admitted targeted
safe triggers — every existing untargeted safe trigger and every
non-lever targeted trigger keeps its prior behavior
byte-identically.

**Why it's OK**: this is the SAME deliberate divergence the campaign
already documents for every `_PickFirst*`-driven probe, the Rust
first-eligible resolve arms, and the spell-card-bridge Phase-1
cast-time seat (the entry directly above) — the campaign-wide
"no-callback first-legal-target convention". Both engines pick the
SAME object by construction (the cross-engine harness keeps bf
insertion order + object ids in lockstep), so the post-resolve
`counters` fingerprint is byte-equal — which is the property the
bench measures. The production-deck bench loader has no strategic
agent at all (the convention is bench/parity context only).

**Failure mode**: a strategically *better* target is never chosen
(irrelevant to parity; a non-first legal target is never reachable
in the bench / cross-engine harness — no agent is seated there).

**Fix scope estimate**: seat a real strategic agent in the bench
loader (a much larger, separate effort — the same fix-scope as the
spell-target / resolution-decision-vocab entries).

**Impact estimate**: parity-positive, zero strength claim. Flips
**both** Tier-C target-seating consumers from Effect-uncovered /
bench-dropped to byte-equal bench-admittable: Sunset Saboteur
(6,375 17lands decks, the `count_min=1` mandatory-counter card) +
Exosuit Savior (12,480 decks, the `count_min=0` optional-bounce
edge) = **2 cards / 18,855 17lands decks** — the complete honest
Tier-C target-seating payoff (NOT ~39k: Terrapact / Genemorph /
Boilerbilges each carry a SECOND blocking substrate and are honest
exclusions, per the design's §5.3/§6 honest-shrinkage). No further
target-seating consumers remain.

---

## Spell-card-bridge lever Phase 1 — spell StackItem carries a deterministic target slot (new substrate, not a shortcut)

**Round-76 update (Phase 2 — the 2-slot substrate generalization).**
Phase 2 added a SECOND target slot:
`StackItem.target_obj_id_2: Option<u32>` (defaults `None`; only the
2-slot `cast_spell_noncreature` path sets it) +
`GameState.current_resolve_payload_target_id_2` (the second
resolve-time swap field, same transient/not-fingerprinted discipline
as its sibling) + the second save→set→restore swap mirrored into
BOTH resolve entry points. The single-slot `new_spell_with_target`
constructor was REMOVED (subsumed by the unified
`new_spell_with_targets(.., target, target_2)` — a single-target
push passes `target_2=None`, byte-identical; the no-fallback-hybrid
/ clean-replacement discipline, NOT a dead zombie kept alongside the
superset). Still genuinely-new substrate, NOT a divergence. Back-
compat by construction (both fields default `None`; the closed
Phase-1 single-target arms self-scan and ignore BOTH). The
spell→graveyard move is STILL free (`post_resolve_destination`
UNCHANGED — Phase 2 adds ZERO graveyard-move code).

**Location**: `rust/src/state.rs` (`StackItem.target_obj_id:
Option<u32>` + `target_obj_id_2: Option<u32>` + the unified
`new_spell_with_targets` constructor) +
`GameState.current_resolve_payload_target_id` +
`current_resolve_payload_target_id_2` + the resolve-time double swap
for `StackItemKind::Spell` in both `resolve_top_of_stack` and
`resolve_top_of_stack_pause` (`rust/src/state_ops_resolve.rs`).

**What it is**: a new `StackItem` field (defaults `None`; every
pre-lever `new_spell` push stays untargeted — the discriminant-plus-
optional pattern the struct doc comment already establishes) plus
the resolve-time swap into `current_resolve_payload_target_id`,
mirroring the existing `TriggeredAbility` `trigger_payload.target_id`
swap. This is genuinely-new Rust substrate, NOT a deliberate
divergence — recorded here per the spec §3.7 requirement so a future
reader sees the field's intent.

**Why it's OK**: back-compat by construction (the field defaults
`None`; only `cast_spell_noncreature` sets it). The swap is
save/restore-bracketed exactly like the controller swap. The
spell->graveyard post-resolve move is NOT a shortcut and needs no
entry: `move_source_post_resolve` / `post_resolve_destination`
(`state_ops_resolve.rs:251-256`, UNCHANGED) already implement CR
608.2m correctly for Instant/Sorcery — Phase 1 adds ZERO
graveyard-move code (noted explicitly so a future reader does not
re-derive it).

**Failure mode**: none today.

**Fix scope estimate**: none (this IS the substrate; Phase 2 widens
it to a 2-slot payload).

**Impact estimate**: enables all single-target Tier-A bench-admit
(the carrier the per-card Effect closes ride into the bench).

---

## Lander-spell-token-seating sub-substrate (round-73) — Seedship Impact / Orbital Plunge now SEATED + bench-admitted (was DECLINED at the round-70 Phase-1 landing)

> **Status flip (round-73).** This entry previously documented
> Seedship Impact / Orbital Plunge as *positively DECLINED* (the
> spell-card-bridge Phase-1 round-trip-or-bail tooth — the loader's
> spell path had no Lander-token-seating pass). The
> Lander-spell-token-seating sub-substrate now SHIPS that pass; both
> cards are SEATED + bench-admitted byte-equal. The decline tooth is
> NOT removed — it still positively declines any genuinely-unseatable
> shape (see "What the round-trip-or-bail tooth STILL declines").

**Location**: `src/mtg_bot/parity/trajectory.py`
(`_canonical_lander_token_card_def` — the canonical Lander CardDef
via the EXISTING `_token_with_safe_activated_ability_card_def`;
`_python_spell_effect_to_dict` — the reverse serializer now emits a
symbolic `_token_card_def` for `SeedshipImpactEffect` /
`DealDamageToTargetCreatureWithExcessLanderRider`;
`_seat_token_printings` — `_carrier_spell_token_ref` + the
spell-axis branch of the rewrite loop, mirroring the
`triggered_abilities` `create_token` machinery on the `spell_effect`
axis) + `src/mtg_bot/parity/cross_engine.py`
(`resolve_top_of_stack_rust` — the SBA-symmetry fix) +
`tests/parity/_picker_shims.py`
(`_PickFirstLegalTargetAgent.choose_surveil` — the keep-on-top
byte-equal default).

**What the deliberate simplifications are**: the *seating* itself is
genuinely-new loader substrate (NOT a shortcut — it is the exact
`triggered_abilities` `_seat_token_printings` machinery applied to
the `spell_effect` axis: walk for a symbolic `_token_card_def`, seat
the Lander CardDef at a deterministic pid, rewrite to the numeric
`token_printing_id`, `register_token_printing` the matching Python
printing). The deliberate divergences it *carries* (recorded per
project policy):

1. **The bridge drops the Lander pid (pre-existing, unchanged).**
   Rust's `parse_effect` `require("token_printing_id")` for the
   Lander; the dict→Python bridge arms (`cross_engine.py`
   `seedship_impact_effect` /
   `deal_damage_to_target_creature_with_excess_lander_rider`)
   construct the FIELD-FREE Python class (Python mints the Lander
   intrinsically from `TOKEN_PRINTINGS["Lander"]`). Both engines seat
   the SAME logical "Lander" printing (Rust via the loader-assigned
   pid, Python intrinsic) so the created token is byte-equal in the
   name-keyed field view — the SAME pid-carrier deviation already
   documented in the Seedship-Impact / Orbital-Plunge Effect-half
   entries above. The loader uses the EXACT helper the triggered
   path uses (`_token_with_safe_activated_ability_card_def`) so the
   seated Lander's registered Python printing is byte-identical to
   the intrinsic one.

2. **The spell rewrite preserves the Rust arm's exact field set.**
   Unlike the `triggered_abilities` `create_token` rewrite (which
   reconstructs a fixed `{kind,count,token_printing_id}` dict), the
   spell rewrite copies the whole `spell_effect` dict, drops
   `_token_card_def`, adds the numeric `token_printing_id`, and
   injects NO `count` (Rust's `seedship_impact_effect` arm requires
   ONLY `token_printing_id`; the Orbital Plunge arm requires
   `amount` + `token_printing_id` — a spurious `count` would be the
   silent-mistranslation class the §2 teeth exist to prevent).

3. **`resolve_top_of_stack_rust` SBA symmetry (pre-existing latent
   gap, surfaced + fixed).** The harness's Rust cast-mirror drain
   ran `resolve_top_of_stack()` per item but (unlike its Python
   sibling, which runs `state_based_actions`) did NOT run
   `apply_sbas()`. Pre-round-73 every admitted cast-path Effect
   mutated state inside resolve (e.g. `DepressurizeEffect` calls
   `destroy()`), so the gap was unobservable. Orbital Plunge deals
   DAMAGE and relies on the lethal-damage SBA; the missing
   `apply_sbas()` left Rust's damaged creature on the battlefield = a
   HARNESS false-positive (the engines agree). Fixed by mirroring the
   Python sibling's SBA call — apples-to-apples, the exact pattern
   every Effect-half probe runs by hand.

4. **`_PickFirstLegalTargetAgent.choose_surveil` keep-on-top
   (pre-existing latent gap, surfaced + fixed).** The bench installs
   this agent on both Python players whenever a spell may be cast.
   It lacked `choose_surveil` (base `Agent` raises
   `NotImplementedError`); no real bench game cast a spell AND lived
   long enough to fire a surveil ETB (e.g. Thawbringer's
   enters→surveil 1) until Seedship/Orbital extended such games past
   the trigger. Fixed to `return False` (keep on top) — the BYTE-
   EQUAL mirror of Rust's terminal
   `auto_resolve_pending(self, "keep_all_on_top")` + Python's
   `p.agent is None` keep-on-top short-circuit (returning `True`
   would mill and DIVERGE from Rust's no-mill default).

**Why it's OK**: this is the no-fallback-hybrid discipline applied
positively — the symbolic Lander ref is emitted ONLY because the
seating pass that resolves it now exists; the two pre-existing latent
harness gaps were fixed BYTE-EQUAL (not papered over, not relaxed in
the r72 fixture test). Genuinely probed: the two real-EoE
loader-admit + cross-engine cast→resolve byte-equality probes
(`test_cross_engine_real_eoe_{seedship_impact,orbital_plunge}_loader_admit_and_cast_resolve_parity`)
drive the GENUINE production loader path end-to-end (loader-drop →
admit flip + the destroy/damage + conditional-Lander observable
byte-equal on BOTH engines, BOTH translation directions); bridge pin
#14 pins the bidirectional seated round-trip; pins #12b/#13 flipped
DECLINE→SEATED (new-code-is-right).

**What the round-trip-or-bail tooth STILL declines (the
necessary-but-not-sufficient card)**: the tooth is NOT weakened into
a fallback hybrid. `_python_spell_effect_to_dict` still returns
`None` for any genuinely-unseatable shape — a `Sequence` with one
unrecognized child; any token-pid Effect whose token is not the
bridge-correct Lander (`_canonical_lander_token_card_def` returns
`None` if the authored Lander ever drifts out of the
`_token_with_safe_activated_ability_card_def` §2 shape). And
complementary to this serializer, the covered-set gate still
positively declines **Close Encounter** — the concrete
necessary-but-not-sufficient card (`CloseEncounterEffect` is NOT in
`covered_python_class_set()`: no additional-cost-choice substrate
ships it; live `Close Encounter.warp_cost is None` so the spec
ADDENDUM's warp reason is stale — the covered-set gate is the robust
teeth, pinned #11). **Diplomatic Relations** also stays declined
(2-slot grammar — Phase 2; pinned #12).

**Failure mode**: none today. The risk guarded against: a future
spell-effect token-pid Effect whose token is NOT the Lander would
need its own `_canonical_*_token_card_def` + serializer arm — the
generic spell-axis seating only seats the symbolic ref the
serializer emits, so an un-served shape stays declined (no
parse-raise / mistranslation).

**Fix scope estimate**: SHIPPED (round-73). One focused Python-lane
slice (loader plumbing — the Rust `parse_effect` + bridge arms
already existed); +2 small pre-existing harness-gap fixes (SBA
symmetry, keep-on-top surveil).

**Impact estimate**: +2 single-target Tier-A bench-admits — Seedship
Impact (~13,908 17lands decks) + Orbital Plunge (~28,629) = ~42,537
decks flip loader-drop → bench-admit. The spell-card-bridge admit set
is now {Depressurize, Orbital Plunge, Radiant Strike, Seedship
Impact}; it auto-grows further as Focus Fire / Biosynthic Burst
close. Zero production strength cost (parity-instrumentation only).

## Bench deck-out-aware early terminator — DECLINED (honest-no-ship): no parity-PROVABLE predicate covers the population, and the sound one is dominated by the already-shipped blanket cap-120

**Location**: `scripts/bench_trajectory_parity.py` (the
`while not _game_over(py_state)` driver loop, `drive_one_game`). This
entry documents a deliberately **NOT-taken** optimization (the
round-70 forward flag, `docs/bench_trajectory_parity_smoke.md` round
70 / round 72) — recorded here because declining a flagged
optimization on parity-soundness grounds is itself a load-bearing
search-correctness decision the next agent must inherit (so the
forward flag is not re-attempted blind).

**What the optimization would have been**: round-70 flagged a
"deck-out-aware early terminator" — detect that a game is a pure
deck-out race whose winner is already determined, and short-circuit
to that exact verdict instead of playing out the ~50 remaining empty
turns the blanket `--max-turns 120` (round-72, `7c7d5eeb`) currently
runs.

**Why it is DECLINED (verify-first per-game evidence)**: the canonical
broad grid's 15 cap-60 FAIL_TIMEOUT games (archetypes 0-29 × seeds
0-1; the round-70 residual population) were each driven to natural
termination and snapshotted. Findings:

- The only **parity-PROVABLE** early-terminal predicate is the strict
  conjunction *"both libraries contain ONLY lands AND both hands
  contain ONLY lands AND zero nonland permanents on the battlefield
  AND empty stack AND no poison"*. Under it the remaining trajectory
  is provably deterministic and damage-free (nothing castable, no
  creature can ever enter, no SBA but deck-out can fire), so the
  winner is computable now from library sizes + draw cadence and is
  byte-identical to play-it-out. It is engine-agnostic (both engines
  model zone contents identically — `step_both` byte-equality holds
  the whole game) and sound (any non-land card anywhere → predicate
  fails → play it out unchanged; a game that *could* still diverge is
  never short-circuited).
- That sound predicate fires on **only ~2 of the 15** games
  (arch 6, arch 29 — the pure all-lands mirrors; predicate true from
  turn 1, deck-out turn 108, winner 0). The **majority**
  (arch 19/26/27/28, deck-out turn 108) carry non-land cards
  persistently in hand/library that the bridge filter declines and
  the deterministic driver never plays — the sound predicate
  correctly NEVER fires there. arch 24/25 seed 1 are **not deck-out
  at all** (combat-damage `life total <= 0` ~turn 72 — the round-70
  lone-1/1 slow clock); a deck-out terminator must never fire there
  and correctly does not. arch 20 seed 1 has an active surveil effect
  (non-frozen) and is likewise correctly excluded.
- A *looser* predicate broad enough to cover arch 19/26/27/28 would
  have to prove those specific non-land cards can never be
  cast / never deal damage across ~50 remaining turns — i.e.
  effectively simulate the game. That is exactly the
  "short-circuit a game that could still diverge" hazard the forward
  flag's own parity-safety bar forbids; it is **not soundly
  provable** without the simulation it is meant to avoid.

**Why it's OK to decline (the honest-no-ship math)**: the round-72
blanket `--max-turns 120` already eliminates the FAIL_TIMEOUT floor
(23.3% → 0.0% on the canonical grid) at a measured cost of **+3s over
the entire 60-game cap-60 sweep** (round-70 real-bench cross-check;
the bench parallelizes the slow deck-out tail). The sound predicate's
2/15 coverage would shave ~107 frozen turns off two games inside a
sweep whose total slow-tail cost is already +3s parallelized — a
**zero-meaningful-wall** gain — while the predicate broad enough to
matter is not parity-provable. Per `feedback_no_fallback_hybrids` /
`feedback_parity_new_code_is_right` and the forward flag's own
"honest-no-ship if equivalence unprovable" bar: ship nothing. The
blanket cap-120 is the correct, already-landed, fully parity-safe
mitigation; the early terminator is dominated and is **closed, not
deferred**.

**Failure mode**: none — nothing is shipped; the bench is byte-for-
byte unchanged (the round-72 cap-120 + its `test_r72_...` pin remain
the live, pinned state). The risk this entry guards against is a
future agent re-attempting the forward flag and either (a)
re-deriving the same negative result (wasted cycles) or (b) shipping
the unsound broad predicate and silently corrupting parity verdicts
on the arch-19/26/27/28-shaped population.

**Fix scope estimate**: N/A — declined by design. If a future bench
ever drops the blanket cap (making the wall cost non-negligible), the
*sound* strict-lands-only predicate could be revisited as a
**supplement** to (never a replacement for) a finite cap, gated by
the exact conjunction above plus a per-game pin asserting
early-terminal verdict == play-it-out verdict on the arch-6/29 shape.
It would still only cover the all-lands sub-population; the
arch-19/26/27/28 shape stays unprovable and must keep playing out.

**Impact estimate**: zero (nothing shipped). The characterization
itself is the deliverable — it converts the round-70 forward flag
from "open future lever" to "closed, dominated, with the soundness
boundary and per-game evidence on record".

---

## Cross-engine legal-decision-set mana-payability asymmetry (LIVE-SURFACE CLOSED — mana axis Slice 1, target axis Slice 2, additional-cost axis Slice 3; residual = the non-live alt-cost axes only, no Rust emission site)

**Status**: **LIVE-SURFACE CLOSED.** All THREE Python prune axes —
mana-payability, target-satisfiability, and additional-cost — are now
CLOSED on the 6 live Rust CastSpell emission sites; the ONLY residual
is the non-live alt-cost axes (kicker / impending / granted-warp /
Room-half / X), which Rust does not emit AT ALL yet (the separate
`state_ops_legal.rs:90-101` "Deferred alt-cost flags" surface — there
is no Rust emission site for them, so there is no SET asymmetry on
the live cast surface). On the live cast surface `RustCastSpellSet
== PythonCastSpellSet`. The **mana-payability axis is CLOSED** by
legal_decisions mana-awareness Slice 1 (2026-05-17,
`feature/rust-legal-decisions-mana-slice1`;
`docs/RUST_LEGAL_DECISIONS_MANA_AWARENESS_DESIGN.md`): the
non-destructive `state_ops_mana::can_pay_cost` predicate (composing
the already-byte-equal-pinned `pool_can_cover` +
`auto_tap_headroom_pool`, co-located with the destructive
`pay_mana_cost` twin) now gates ALL of Rust's live CastSpell
emission sites — base hand instant/sorcery, their warp variants, the
warp-from-graveyard loop, and the warp exile-recast. **The
target-satisfiability axis on the live CastSpell sites is ALSO
CLOSED** by legal_decisions mana-awareness Slice 2 (2026-05-17,
`feature/rust-legal-decisions-target-satisf`): the non-destructive
`state_ops_legal::spell_targets_satisfiable` predicate — the Rust
analog of Python `_targets_are_satisfiable` (CR 601.2c) — gates the
SAME 6 live CastSpell emission sites; for each live bridge-admitted
targeted `Effect` variant (`DepressurizeEffect`, `FocusFireEffect`,
`DestroyTargetArtifactOrTappedCreature`, `SeedshipImpactEffect`,
`DealDamageToTargetCreatureWithExcessLanderRider`,
`BiosynthicBurstEffect`, `DiplomaticRelationsEffect`) it scans for ≥1
legal target using the SAME `bf_iter_etb_sorted` object filter the
matching `state_ops_resolve.rs` resolve arm uses (single source of
truth), so Rust no longer emits a `cast_spell` for a spell whose
targeted effect has zero legal targets. On the live cast surface
`RustCastSpellSet == PythonCastSpellSet` for BOTH the mana and the
target axes. **The additional-cost axis on the live CastSpell sites
is ALSO CLOSED** by legal_decisions mana-awareness Slice 3
(2026-05-17, `feature/rust-legal-decisions-addcost`): the 3
`additional_cost_*` flags (`..._sacrifice_creature_or_artifact` /
`..._creature_or_enchantment` / `..._choose_your_creature`) are
added to the Rust `CardPrinting` (parsed from the registry dict with
the same back-compat `match get_item { Some => extract, None =>
false }` shape as `warp_castable_from_graveyard`), and the
non-destructive `state_ops_legal::additional_costs_payable`
predicate — the Rust analog of Python `_additional_costs_payable`
(`legal.py:117-165`, CR 601.2f/601.2h) — gates the SAME 6 live
CastSpell emission sites. **Verified-zero live incidence (the design
§5 prediction realized):** all 4 EoE printings carrying any
additional-cost flag (Embrace Oblivion, Scrounge for Eternity, Final
Vengeance, Close Encounter) are bridge-DECLINED by BOTH
`_printing_is_bridge_simple_spell` and
`_printing_is_bridge_simple_creature`, so the predicate is `true`
for every live-surface card — it NEVER prunes a live emission ⇒
parity-NEUTRAL by construction. The full predicate is implemented
anyway (NOT a stub) so it is the faithful Python mirror AND the
single named extension point that fires correctly the instant an
additional-cost card becomes bridge-admitted. All three changes
are parity-NEUTRAL under the current single-script-replay harness
(design-doc §4 proof: each predicate is at-least-as-permissive as its
Python twin — Slice 1 via the same `auto_tap_headroom_pool`, Slice 2
via the same resolve-arm object filter, Slice 3 via the
zero-live-incidence conservative-true property — so every
Python-sourced replayed action is still emitted by post-fix Rust).
**Residual divergence (still ACCEPTED, the separate deferred
surface):** ONLY the non-live alt-cost axes (kicker / impending /
granted-warp / Room-half / X — the separate
`state_ops_legal.rs:90-101` "Deferred alt-cost flags" surface; Rust
emits NONE of these dicts AT ALL, so there is no live SET asymmetry —
when those axes become Rust emission sites the Slice-1/2/3 predicates
already compose via the designed `can_pay_cost` extension points,
design doc §2.4/§2.5). The earlier history: this entry originally
existed because `rust/src/state_ops_legal.rs:77-88` *claimed* the
divergence was "Documented in `docs/SEARCH_LIMITATIONS.md`" with no
such entry; the characterization + canonicalization pin landed
2026-05-17 (`feature/cross-engine-legal-set-asymmetry`), Slice 1
closed the mana axis it characterized, and Slice 2 closed the
target-satisfiability axis.

**Location**:
- Python (source of truth): `src/mtg_bot/legal.py` —
  `_can_cast` (`:60-76`) → `mtg_bot.cards.can_pay_cost`, called at
  every CastSpell site (`:252-254` instant-speed, `:383-385`
  sorcery-speed, plus the kicker/warp/impending/granted-warp/
  Room-half variants `:256-301` / `:387-460`) and every
  ActivateAbility site (`:631-657`). Also gates target
  satisfiability (`_targets_are_satisfiable`, `:79-114`) and
  additional non-mana costs (`_additional_costs_payable`,
  `:117-165`).
- Rust: `rust/src/state_ops_legal.rs:legal_decisions` — the
  CastSpell emission loop (~`:1040-1099`); module docstring
  `:77-88` ("Deferred mana-affordability check") + `:90-101`
  ("Deferred alt-cost flags"). The ActivateAbility approximation is
  separately tracked in the "`legal_decisions` ActivateAbility
  approximated to mana producers" entry above.

**What the asymmetry was, and what remains (CORRECTED — verify-first,
the stale ActivateAbility clause struck)**: Python `legal_actions`
is **mana-aware** — it never enumerates a CastSpell / ActivateAbility
whose cost the player cannot currently pay (it calls the
non-destructive `can_pay_cost` predicate, which auto-taps available
lands/mana creatures hypothetically). **The ActivateAbility surface
is ALREADY mana-aware on the Rust side too** — `state_ops_legal.rs`
gates the ability emission loop on
`pool_can_cover(&auto_tap_headroom_pool(self, idx), &ability.cost.mana)`
(pins I50; the original "and the activated-ability surface" clause
here was STALE and is struck — verify-first correction per the
design doc §1.4). **The CastSpell mana axis is now CLOSED too**
(Slice 1, above): `state_ops_legal.rs:legal_decisions` gates every
live CastSpell emission site on `state_ops_mana::can_pay_cost`, so it
no longer emits a `cast_spell` dict for an un-payable card. **The
CastSpell target-satisfiability axis is now CLOSED too** (Slice 2,
above): `state_ops_legal.rs:legal_decisions` gates every live
CastSpell emission site on `spell_targets_satisfiable`, so it no
longer emits a `cast_spell` dict for a spell whose targeted effect
has 0 legal targets (CR 601.2c). **The CastSpell additional-cost
axis is now CLOSED too** (Slice 3, above):
`state_ops_legal.rs:legal_decisions` gates every live CastSpell
emission site on `additional_costs_payable` (reading the 3 new
`CardPrinting.additional_cost_*` fields), so it no longer emits a
`cast_spell` dict for a spell whose cast-time additional non-mana
cost is unpayable (CR 601.2f/601.2h). **What remains a divergence**
(the residual, still ACCEPTED): ONLY the non-live alt-cost axes
(kicker / impending / granted-warp / Room-half / X) — Rust emits
NONE of these dicts AT ALL yet (the separate "Deferred alt-cost
flags" surface), so there is no SET asymmetry for them on the live
cast surface (you cannot over-emit a dict you never emit). All three
Python prune axes that DO have a live Rust emission site
(mana-payability, target-satisfiability, additional-cost) are CLOSED.
(Rust filters every structural axis Python does at enumeration — the
post-CE17 defender keyword, the mana axis, the target-satisfiability
axis, and the additional-cost axis — so the residual is specifically
the *non-live-alt-cost* axes, not "Rust never prunes".)

**Why it's OK (parity-benign by construction — the
canonicalization)**: every cross-engine harness uses the
**observation-driven single-script-replay** contract. The action is
computed from the **Python** state (the source of truth) — e.g. a
deterministic agent reading Python's hand/board, or
`RealGameCombatAgent`, or the bench's `_try_cast_one_creature`
which does its own Python-side mana counting — and the SAME
`action_dict` is then applied to BOTH engines via
`cross_engine.step_both`. **No cross-engine code path calls
`rust_state.legal_decisions(pid)` to source an agent choice, and no
field-view divergence check ever compares the two emission sets**
(`step_both` / `walk_both` compare post-step *field views*, never
emission sets; the harness docstring at
`cross_engine.py:~10135` states PassPriority is the only
enumeration-parity-free action and that emission differences are
"the next slice's parity surface" — i.e. deliberately out of the
compared view). Because the Python (pruned) set is the SOLE script
source, the Rust-only structural superset is **unreachable as an
agent choice in any cross-engine context**. The warp-admitted
probe's development-time `py=[True] vs rs=[False,True]`
observation was an *un-masked direct-probe* of the two enumerators
(not a trajectory divergence — every `step_both` there was
byte-equal); it was resolved idiom-faithfully by ramping mana so
both enumerators agree, and that masking is exactly what the
negative-control test below reproduces.

**Failure mode**: NONE for cross-engine trajectory parity (proven
by construction + the regression pins). The only way this becomes
observable is if a future change wires a Rust-side
`legal_decisions`-enumerated agent into a cross-engine
choice/compare path (instead of the Python-derived replay). In that
hypothetical, an agent could pick the Rust-only structural cast and
the engines would then be asked to apply an action Python's engine
considers illegal — `step_both` would raise on the Python side (its
`apply_action` invariants are stricter), surfacing loudly rather
than silently diverging. The regression module FAILS LOUDLY if (a)
Python's mana-aware prune regresses (it would start offering the
un-payable cast), (b) Rust's structural emission regresses (the
asymmetry would vanish — at which point this entry must be
RETIRED), or (c) the single-script-replay canonicalization breaks
(replayed PassPriority would no longer be byte-equal). Single-engine
search is unaffected: Python's MCTS uses Python `legal_actions`;
Rust's `legal_decisions` superset is a documented search-side
over-enumeration tracked in the sibling Rust-port entries (e.g. the
ActivateAbility-approximation entry) — that is a *strength* concern
within the Rust engine, NOT a cross-engine parity concern, and is
out of scope of this entry.

**Regression pin**:
- `tests/test_cross_engine_legal_set_asymmetry.py` — 3 tests on a
  minimal real-EoE state (the genuine `Slavering Branchsnapper`
  {4}{G}{G} 7/6 printing in p0's hand at turn-1 PRECOMBAT_MAIN),
  **re-anchored to the CLOSED contract by Slice 1**:
  (1) `..._mana_payability_closed_both_omit_unpayable` — with 0 mana,
  **BOTH** Python and Rust now omit the un-payable CastSpell (was:
  Python omit / Rust structural-emit; FLIPPED by Slice 1 — LOUD on a
  Rust mana-gate regression); (2)
  `..._closed_replay_stays_byte_equal` — the same zero-mana point
  driven by the Python-derived single-script replay stays byte-equal
  every step AND the now-equal sets persist (the §4
  parity-neutrality tripwire — an over-prune would diverge here);
  (3) `..._closed_negative_control_both_emit_when_affordable` — the
  over-prune guard: with 6 G sources BOTH engines emit exactly the
  base cast (proves Slice 1's predicate is at-least-as-permissive as
  Python's — `auto_tap_headroom_pool`, not a pool-only check).
- `tests/test_cross_engine_legal_set_target_satisf.py` — 3 tests on
  a minimal real-EoE synthetic state (the genuine `Depressurize`
  {1}{B} `DepressurizeEffect` instant in p0's hand, 2 untapped
  mono-B lands on p0's bf so the Slice-1 mana gate PASSES — the
  target axis is the only pruner), **the CLOSED target-axis
  contract**: (1) `..._closed_both_omit_untargetable` — with 0
  creatures on the bf, **BOTH** Python and Rust now omit the
  target-unsatisfiable CastSpell (NEGATIVE-CONTROL-VERIFIED: against
  a pre-Slice-2 engine this test FAILS at exactly the documented
  divergence — Rust emits the un-targetable `cast_spell`, Python
  omits; LOUD on a Rust target-gate regression); (2)
  `..._negative_control_both_emit` — over-prune guard: with a legal
  Depressurize target (a vanilla creature) seated, BOTH engines emit
  exactly the base cast (proves `spell_targets_satisfiable` is
  at-least-as-permissive as `_targets_are_satisfiable`); (3)
  `..._only_axis_under_test` — isolation guard: asserts Python's
  `can_pay_cost` says {1}{B} IS payable in the closed-contract
  state, so that test prunes on the TARGET axis, not a coincidental
  mana-unaffordability.
- `tests/test_cross_engine_legal_set_addcost.py` — 3 tests on a
  minimal synthetic state (a {0}-cost no-target Instant FLAGGED
  `additional_cost_sacrifice_creature_or_artifact` in p0's hand —
  {0} cost so the Slice-1 mana gate trivially passes, no
  spell_effect so the Slice-2 target gate trivially passes — the
  additional-cost axis is the only pruner), **the CLOSED
  additional-cost contract**: (1)
  `..._closed_both_omit_unpayable` — with NO sacrificeable
  creature/artifact the caster controls, **BOTH** Python and Rust
  now omit the additional-cost-unpayable CastSpell
  (NEGATIVE-CONTROL-VERIFIED: against a pre-Slice-3 engine this test
  FAILS at exactly the documented divergence — Rust modeled no
  additional-cost flag so emitted the un-payable `cast_spell`,
  Python omitted; LOUD on a Rust additional-cost-gate / field-parse
  regression); (2) `..._negative_control_both_emit` — over-prune
  guard: with a sacrificeable creature seated, BOTH engines emit
  exactly the base cast (proves `additional_costs_payable` is
  at-least-as-permissive as `_additional_costs_payable`); (3)
  `..._only_axis_under_test` — isolation guard: asserts the {0}
  cost is payable AND the spell has no spell_effect, so the
  closed-contract test prunes on the ADDITIONAL-COST axis, not a
  coincidental mana- or target-unsatisfiability.

**Fix scope estimate**: the mana axis (Slice 1), the
target-satisfiability axis (Slice 2), AND the additional-cost axis
(Slice 3) are **ALL DONE** — every Python prune axis with a live
Rust CastSpell emission site is CLOSED. The ONLY residual is the
non-live alt-cost axes (kicker/impending/granted-warp/Room-half/X/
restricted-coin/convoke) — there is no Rust emission site for them
yet (the separate "Deferred alt-cost flags" surface), so there is no
live SET asymmetry; the Slice-1/2/3 predicates already compose via
the designed `can_pay_cost` extension points (design doc §2.4/§2.5)
when those axes become emission sites. The C1 SoT-flip keystone (the
legal-decision-set correctness gate, design doc §6) is satisfied at
the live-cast-surface level: Slices 1–3 are all green. This entry is
RETIRED outright only when the alt-cost surface ALSO becomes a Rust
emission site AND is gated (at which point there is zero residual);
until then it stays as the LIVE-SURFACE-CLOSED record + the
forward-extension-point contract.

**Impact estimate**: zero on cross-engine trajectory parity
(parity-NEUTRAL by the §4 single-script-replay proof — the existing
gate + probe modules stay byte-equal; the deliverable is the
flip-readiness correctness fix). Within the Rust engine the mana-gate
(Slice 1) + target-satisfiability-gate (Slice 2) +
additional-cost-gate (Slice 3) tighten `legal_decisions` (fewer
wasted search visits on un-payable / un-targetable /
additional-cost-unpayable casts — a strength gain) and, critically,
make Rust's enumeration *correct* for when it becomes the
authoritative decision source at the SoT flip (the policy head no
longer scores / PUCT no longer expands illegal-by-mana NOR
target-unsatisfiable NOR additional-cost-unpayable actions). No
Effect / bridge / `_SAFE_*` change; no `cards.rs` touch; bench-admit
set + POOL_PARITY/PROBED headline untouched.

**Identity-seam sub-simplifications (deliberate, live-surface,
parity-safe — recorded per the §3.1/§2.2/§2.3 design):**
- **`eff(c) = c`** (the cost-reduction seam, `state_ops_legal.rs`):
  Rust's `cards.rs` has no `cost_reductions` /
  `external_cost_reductions` on the live bridge-admitted cast
  surface (the bridge declines cost-reduction cards;
  `COST_REDUCTION_PHASE1` is realizable-0), so the effective cost IS
  the printed cost. The identity wrapper is the single named
  insertion point for a future cost-reduction slice (it does not
  re-touch the gate sites). A pin would over-prune ONLY if a
  cost-reduction card became bridge-admitted (then Python reduces +
  finds payable, Rust wouldn't) — mitigated by the bridge declining
  them today + the named seam.
- **`SpellKind::Any` (restricted-coin)**: the Rust `ManaPool` is a
  bare count struct with no per-coin spend-restriction model; no
  live admitted CastSpell card exercises a restricted-coin context
  (Treasure/Eldrazi/artifact-spend idioms off the cast surface).
  `spell_kind` is carried in `can_pay_cost`'s signature for
  forward-composition but ignored — equivalent to Python's behavior
  when no coin carries a restriction (the dominant real case), and
  it can only keep Rust a SUPERSET of Python in the restricted
  corner (preserves the `Rust ⊇ Python` direction the replay
  contract needs). Restricted-coin port bundled with the alt-cost
  slice.
- **`convoke` / `sac_for_mana` omitted**: Python's upper-bound
  wideners ("only ever make a spell cheaper"); no live admitted axis
  card has convoke and sac-for-mana is the Treasure idiom — both off
  the live cast surface. Adding them later is a pure widening (never
  narrows the emitted set) so it lands without re-pinning.

---

## Loader-admit gate is a reduced-card-universe boundary (DOCUMENTED + ENFORCEABLE — C6 pin landed)

**Location.** `src/mtg_bot/parity/trajectory.py`:
`_filter_deck_to_bridge_supported` (the 5-disjunct admit chokepoint)
+ `_production_deck_to_deckspec_core` (the Forest-pad). Public
surface: `production_deck_to_deckspec` (silent-drop default,
parity-required) / `production_deck_to_deckspec_instrumented` (the C6
observable + fail-loud wrapper) / `LoaderAdmitPolicy` /
`NonAdmittedCardError` / `LoaderAdmitReport`.

**What the shortcut is.** The parity loader admits a card-name only if
it passes one of 5 bridge-support disjuncts (`basic_land`,
`nonbasic_mana_land`, `pure_warp_creature`, `simple_creature`,
`simple_spell`); any other name is dropped and the deck is
Forest-padded to size. Per `docs/LOADER_ADMIT_COMPLETENESS_ANALYSIS.md`
(re-measured `4704ca3e`): pool admit 10.95%, mean non-land deck-slot
admit ~19.7%, **0 / 129,996 real decks fully admittable**. The bench
therefore plays the *admitted residue of real decks, Forest-padded* —
a deliberately reduced card universe.

**Why it's OK.** This is the accepted staged-flip fence
(`docs/SOT_FLIP_CUTOVER_PLAN.md` C5/C6/§7-OQ3). While Python is the
source of truth (single-script-replay), the silent drop is benign:
both engines replay the SAME action-dict, so a Forest-padded reduced
deck is still a faithful cross-engine parity probe. The byte-equal
campaign metric is honest *over the admitted population*, which is
exactly what the bench exercises.

**Failure mode (and the C6 closure).** At/after the SoT flip the
silent drop would become a *silent correctness hole* — a Rust-sourced
bot would quietly play a different (reduced, Forest-padded) deck than
intended, with no signal. C6 closes this: the boundary is now
**observable** (`LoaderAdmitReport` names every dropped slot +
Forest-pad count, with multiplicity) and **fail-loud-enforceable**
(`LoaderAdmitPolicy.RAISE` raises `NonAdmittedCardError` instead of
silently degrading — the post-flip Rust-sourced path sets this). The
default `production_deck_to_deckspec` path is **bit-identical** to the
pre-C6 behavior (parity-neutral; the silent drop stays the
Python-SoT default). **Pinned by:**
`tests/test_c6_loader_admit_boundary.py` (observable not silent,
fail-loud RAISE, parity-neutral default-path-bit-identical).

**Fix scope.** Not a "fix" — it is the deliberate, now-enforced
soundness boundary. Growing the admitted universe is C1 / the
substrate slices' job (orchestrator-sequenced, multi-round); it is
explicitly NOT C6's job. C6 is the boundary pin only.

**Impact.** No strength/perf cost on the parity path (observe-only on
the default). Post-flip the RAISE policy converts a silent
correctness hole into a loud, debuggable, deck-named failure — the
load-bearing soundness improvement for the staged flip.

---

## Adding a new entry

When you take a deliberate shortcut (heuristic, approximation,
incomplete CR conformance), add a section here with:
- Where in the code (file:line)
- What the shortcut is
- Why it's OK (or which scenarios make it not-OK)
- Failure mode
- Fix scope estimate
- Impact estimate (perf gain or strength cost)
