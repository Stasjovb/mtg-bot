# Search and engine limitations / known correctness gaps

This document tracks places where our search or engine deliberately
diverges from optimal play or strict CR conformance, with the
rationale, the failure mode, and the conditions under which it would
matter.

These are NOT bugs to fix on a deadline — they're tracked here so
they don't get rediscovered every few months as "wait, that's broken"
and so we have a clear record of WHY each shortcut was taken.

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

## Adding a new entry

When you take a deliberate shortcut (heuristic, approximation,
incomplete CR conformance), add a section here with:
- Where in the code (file:line)
- What the shortcut is
- Why it's OK (or which scenarios make it not-OK)
- Failure mode
- Fix scope estimate
- Impact estimate (perf gain or strength cost)
