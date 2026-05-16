# Phase 6 — Full-game trajectory parity

This is the entry doc for the Phase 6 trajectory-parity workstream, the
follow-on to Phase 5's per-event ETB-trigger probes
(see `PHASE5_PARALLEL_AGENT_PLAYBOOK.md`). Phase 5 verified the
cross-engine bridge agrees on hand-rolled single-event probes; Phase 6
verifies the bridge agrees across **multi-turn real-game trajectories**
— opening hands, turn structure, zone movement, eventually combat.

## Seed scaffold (round-12)

The seed file is `tests/test_trajectory_parity.py`. It:

- Builds a 60-card mirror-match `DeckSpec` (24 Forest + 36 Grizzly Bears
  per side) using the existing `mtg_bot.parity.cross_engine.DeckSpec`
  with `shared_rng_seed=42` so both engines shuffle to the same
  permutation.
- Deals seven-card opening hands on both engines via a side-channel
  `_draw_opening_hand` helper that wraps Python's `turn.draw_card` and
  Rust's `state.draw_card` pymethod.
- Walks turn 1's eleven phases + the CLEANUP -> turn 2 UNTAP wrap using
  `cross_engine.advance_phase_python` (Phase 5's harness primitive) +
  `rust_state.advance_phase()`.
- Asserts byte-equal field views on every step plus strong invariants
  (life=20/20, hands=7/7 across turn 1, battlefield empty).
- Extends to turn-2 DRAW (hand 7 -> 8 on the new active player) and
  turn-2 PRECOMBAT_MAIN (play a Forest, assert two-permanent
  battlefield with correct controller_ids).

## Trajectory module + extended tests (round-13, this slice)

Closed by `feature/phase6-parity-trajectory-module`:

- **New module `mtg_bot.parity.trajectory`** ships
  `setup_matched_game(decks, seed, mulligans=False, opening_hand_size=7)`,
  the canonical `(decks, seed) -> (py_state, rust_state)` entrypoint that
  wraps `cross_engine.build_matched_states` plus the side-channel
  opening-draw mirror behind a single call. Closes infrastructure
  gap #1.
- **Test 5 in `tests/test_trajectory_parity.py`** drops its xfail and
  now positively asserts the helper exists, returns parity-clean
  states, and rejects `mulligans=True` until the follow-up slice lands.
- **New tests for turns 3-7**:
  - `test_play_land_each_turn_3_through_5_parity` — drives lands on
    turns 1, 2, 3, 4, 5; asserts per-step parity through five-deep bf.
  - `test_cast_creature_at_turn_5_parity` — earliest viable cast turn
    for the on-the-play side; tap two unsick Forests + cast Bears.
  - `test_attack_at_turn_7_parity` — declare Bears as attacker after
    summoning sickness clears at turn-7 UNTAP; empty declare_blockers.
  - `test_combat_damage_at_turn_7_parity` — Bears deals 2 unblocked,
    p1 life 20 -> 18 on both engines, post-damage SBA pass clean.
- **New unit-test module `tests/test_trajectory.py`** covers the
  `setup_matched_game` helper itself (seed-precedence, validation,
  mulligan-not-implemented gate, no-shuffle path).

All four extended trajectory tests pass without surfacing any new
cross-engine divergence; combat damage / declare-attackers / cast / land
plays are byte-equal across all 7 turns of the trajectory. Gate is
**346 passing** on Phase 5 + Phase 6 (was 332 + 1 xfail).

## Divergences surfaced

**None on the extended turn-1-through-7 trajectory.** A 60-card vanilla
mirror match drives:

- Opening hand setup (`setup_matched_game`).
- Turn 1 no-op walk + turn 2 land + turns 3-5 lands.
- Turn 5 cast Grizzly Bears (with two mana-ability activations).
- Turn 7 declare attackers + empty declare blockers + combat damage.

Every step's field-view compare is byte-equal. This extends round-12's
no-op-prefix finding: the cross-engine bridge is parity-clean across
the **real-game cast-and-attack flow** that Phase 5's selectors only
covered on synthetic 7-card decks. The CE3/CE4/CE5/CE8/CE10 closures
plus the existing `cast_bears_selector` / `combat_selector` per-step
discipline (mana-pool empty on phase exit, ETB-timestamp on every new
permanent, summoning-sick clear on UNTAP, post-damage SBA pass) compose
correctly under the real opening-prefix shape.

The Phase 5 surface is **stronger** than the Phase 6 trajectory tests
need it to be on the vanilla deck shape — Phase 5 already forced the
cast/attack/damage plumbing to converge. The trajectory tests' value is
thus in the **regression-pin** dimension: any future change to Rust's
`state_ops_setup` / `state_ops_steps` / `state_ops_combat` that breaks
the real-game flow will surface here even if the synthetic Phase 5
selectors keep passing.

## Mulligan parity (round-14, this slice)

Closed by `feature/phase6-mulligan-parity`:

- **`MulliganDeterministicAgent`** — frozen-dataclass agent that
  produces byte-identical mulligan/keep + bottom-pick decisions on
  both engines. Configured by `target_hand_size` (0..7); target=7
  is the default no-mulligan keep, target=N for N<7 means "mulligan
  exactly 7-N times then keep, bottom 7-N cards". Bottom strategy
  is `"first"` (positional, hand[:n]); the only currently-supported
  option, mirrors Rust's `bottom_cards_from_hand(n)` orientation.
- **`setup_matched_game(mulligans=True, mulligan_agent=..., mulligan_seed=...)`**
  — drops the `NotImplementedError`. Drives a deterministic London-
  mulligan loop on both engines using paired `random.Random(iter_seed)`
  instances per (player, mulls_taken) iteration. Each engine's
  in-mulligan Fisher-Yates consumes the same `_randbelow` sequence
  (MT determinism for identical seeds); post-shuffle libraries are
  bit-identical across engines.
- **Mulligan loop construction**: per-iteration uses Rust's
  `mulligan_to_n(7)` (shuffle+redraw, no bottom) plus a
  Python-side helper `_python_mulligan_iteration` that mirrors the
  same drain → shuffle → redraw shape consuming the shared rng.
  Final keep applies `bottom_cards_from_hand(n)` on Rust + the
  positional `_python_bottom_cards` on Python. Splitting shuffle
  from bottom mirrors Python's `simulate.setup_game` mulligan-loop
  shape; using `mulligan_atomic` would require progressively-larger
  bottom sets per intermediate iteration, which is meaningless
  because only the final iteration's bottom is preserved.
- **Test surface**: 5 new tests in `tests/test_trajectory_parity.py`
  — default-agent no-op keep, `target_hand_size=6` (one mull each
  side then walk turn 1), `target_hand_size=5` (two mulls each side),
  reproducibility (same seed → identical state), differentiation
  (different seed → different state). Plus 5 new defensive tests in
  `tests/test_trajectory.py` for the agent's validation surface.

## Divergences surfaced in round-14

Two real cross-engine quirks turned up while wiring this:

1. **Hand-drain order in mulligan**: Python's `simulate.setup_game`
   uses `p.hand.pop()` (LIFO — hand[6] returned first); Rust's
   `mulligan_atomic` / `mulligan_to_n` uses `hand.drain(..)` (FIFO —
   hand[0] returned first). Pre-shuffle library tail order would
   diverge if the parity helper used Python's LIFO drain. The
   round-14 helper uses FIFO to match Rust. The Python production
   `setup_game` is unchanged (its LIFO drain is fine because Python
   alone shuffles right after — only the cross-engine harness needs
   the orientation match).
2. **Per-instance flag reset on bottom**: Rust's
   `bottom_cards_from_hand` resets `tapped`, `summoning_sick`,
   `damage`, `counters`, `attached_to`, `exiled_with_source` on each
   bottomed object. Python's bottom step (in `simulate.setup_game`)
   does NOT — but on Python a hand card carries the GameObject default
   `summoning_sick=True`, which would persist into the library and
   surface as a per-object field divergence on the bottomed cards.
   The round-14 helper's `_python_bottom_cards` mirrors Rust's reset
   to keep the post-bottom field views byte-equal. The Python
   production `setup_game` is again unchanged.

Both quirks are *parity-harness specific*: production Python code
is correct on its own terms; the harness must mirror Rust's exact
choices to produce byte-equal field views, even where Python and
Rust each independently produce semantically-equivalent results.

## Infrastructure gaps blocking Phase 6 progress

1. ~~**No shared `setup_game` mirror.**~~ **CLOSED** by
   `feature/phase6-parity-trajectory-module` —
   `mtg_bot.parity.trajectory.setup_matched_game` is now the
   single entrypoint.
2. ~~**No mulligan parity.**~~ **CLOSED** by
   `feature/phase6-mulligan-parity` (round-14, this slice). See
   "Mulligan parity (round-14, this slice)" section above for the
   full ship summary. Residual API gaps that would unblock richer
   mulligan strategies (out of scope for this slice):
   - **Non-positional bottom strategies** would require either Rust
     hand-reordering (no API today — would need
     `reorder_hand(player_id, ids)`) or extending
     `bottom_cards_from_hand` to take explicit ids rather than count.
     Currently only `bottom_strategy="first"` is supported because
     it lines up trivially with Rust's positional default.
   - **State-conditional mulligan agents** (e.g., the heuristic
     `Agent.choose_mulligan` from `mtg_bot.mulligan`) need a way to
     read the post-shuffle hand on Rust before deciding. Today's
     deterministic agent sidesteps this by deciding solely on
     `mulls_taken`. A Rust-side `peek_hand(player_id) -> list[dict]`
     pymethod (or extending the existing `hand_snapshot`) plus a
     bridge that drives both engines with a single Python decision
     would close this. The round-14 deterministic agent is enough
     for trajectory tests; state-conditional agents are a follow-up
     when production-shape mulligan probes are needed.
3. ~~**No real-game combat-decision selector.**~~ **CLOSED** by
   `feature/phase6-real-game-combat-selector` (round-16, this slice).
   See "Real-game combat agent (round-16, this slice)" section below
   for the full ship summary.
4. ~~**Inconsistent action-dict vocabulary.**~~ **CLOSED** by
   `feature/phase6-action-dict-vocab` (round-15, this slice). See
   "Action-dict vocabulary normalization (round-15, this slice)"
   section below for the full ship summary.

## Action-dict vocabulary normalization (round-15, this slice)

Closed by `feature/phase6-action-dict-vocab`:

The action-dict id-key vocabulary is per-kind asymmetric — `card_id`
for `play_land` / `cast_spell` (and `turn_face_up` /
`unlock_room_half`); `source_id` for `activate_ability`;
`spacecraft_id` for `activate_station`. **The asymmetry is consistent
on both Python AND Rust** — Python's dataclass field names
(`PlayLand.card_id`, `ActivateAbility.source_id`, ...) match Rust's
enum variant fields (`Action::PlayLand { card_id }`,
`Action::ActivateAbility { source_id }`, ...). This is intentional
and captures real semantic distinction:

- `card_id` reads naturally for "the card in hand I'm playing /
  casting / flipping / unlocking".
- `source_id` reads naturally for "the permanent on the battlefield
  whose ability is firing" — could be a creature, an artifact, an
  enchantment, a land, never just "a card".

**Decision rationale: Option C (dual-honor + canonical builder
helper).** The brief offered three options:

- Option A (standardize on `card_id` everywhere): would force a
  Python dataclass field rename (`ActivateAbility.source_id` →
  `card_id`) AND a Rust enum field rename, with cascading
  search-loop + bridge changes. Loses the "permanent vs card"
  semantic. Big blast radius.
- Option B (standardize on `source_id` everywhere): same blast
  radius, opposite direction. Loses the "card I'm playing"
  semantic.
- **Option C (dual-honor + canonical builder)** — picked. The
  asymmetry is *correct* on both engines; the only real pain is
  programmatic builders memorizing the per-kind shape. A canonical
  builder helper + dual-honor on the Python bridge solves the
  ergonomic gap without touching either engine's data model. Zero
  Rust-side coupling cost (avoids conflict with parallel Rust
  slices).

Slice contents:

- **`_CANONICAL_ACTION_ID_KEY` table** in
  `mtg_bot.parity.cross_engine` — single source of truth for the
  per-kind canonical id-key vocabulary. Documents the mapping
  (play_land/cast_spell/turn_face_up/unlock_room_half →
  `card_id`; activate_ability → `source_id`; activate_station →
  `spacecraft_id`).
- **`_canonical_action_dict(kind, **kwargs)`** — programmatic-builder
  helper that accepts the GameObject id under the friendly alias
  `id` and routes it to the kind's canonical key. Validates kind
  membership; rejects no-id kinds passing `id`; rejects id-required
  kinds omitting `id`. Other kwargs pass through (e.g., kicker /
  warp / impending flags on cast_spell).
- **`_resolve_id_with_alias(action_dict, kind)`** — bridge-side
  resolver that reads the primary id honoring both the canonical
  key AND the cross-vocabulary alias (`source_id` on
  play_land/cast_spell, `card_id` on activate_ability).
- **`_dict_to_python_action`** updated to use
  `_resolve_id_with_alias` on play_land / cast_spell /
  activate_ability. Soft-deprecation transition aid: hand-rolled
  Python-side dicts that pick the "wrong" key still resolve. Rust
  stays strict (canonical key only) — documented in the function
  docstring. Always prefer `_canonical_action_dict` for dicts that
  cross both engines.
- **Test surface** (15 new tests):
  - `tests/test_parity_smoke.py` — 13 tests covering the builder's
    happy paths (play_land, cast_spell, activate_ability, no-id
    kinds), validation (unknown kinds, bad id pairings),
    dual-honor (alias acceptance for both directions,
    canonical-takes-precedence when both present, missing-id
    KeyError contract preserved), and a drift-detection test that
    pins the per-kind canonical-key table.
  - `tests/test_trajectory_parity.py` — 2 tests:
    - `test_activate_ability_trajectory_via_canonical_builder` —
      end-to-end real-game trajectory using
      `_canonical_action_dict` for every action (lands across
      turns 1/3/5, two Forest mana activations, cast Bears). Pins
      cross-engine parity on the builder-emitted dicts.
    - `test_activate_ability_trajectory_alias_dict_python_only` —
      Python-bridge-only contract: an alias-keyed activate_ability
      dict (`card_id` instead of `source_id`) still taps the
      Forest on the Python side. Documented to NOT cross the Rust
      boundary.

Gate: **379 passing** (was 364; +15 net). No divergences surfaced.

## Divergences surfaced in round-15

**None.** The activate_ability trajectory test runs cleanly across
the full real-game prefix (opening hand, three land plays, two
mana activations, cast Bears) with byte-equal field views on every
step. This extends the round-13 finding: the cross-engine bridge is
parity-clean on the activate_ability path the same way it is on
play_land / cast_spell / declare_attackers.

The trajectory test's value is two-fold:

1. **Builder regression-pin** — any future change to
   `_canonical_action_dict`'s per-kind routing (e.g., emitting
   `card_id` for `activate_ability` by mistake) would surface
   immediately as a Rust-side parse error since Rust is strict on
   the canonical key.
2. **Activate_ability trajectory regression-pin** — any future
   Rust-side change to the mana-ability primitive that breaks the
   Forest tap-for-mana flow surfaces here.

## Real-game combat agent (round-16, this slice)

Closed by `feature/phase6-real-game-combat-selector`:

- **`RealGameCombatAgent`** — frozen-dataclass cross-engine combat
  policy with three configurable strategies:
  - `"attack_all"`: every unsick + untapped Creature controlled by
    the active player attacks; defender doesn't block.
  - `"attack_all_block_smallest"`: same attacker selection;
    defender blocks each attacker with their smallest available
    creature, sorted by `(power, toughness, id)`. One blocker per
    attacker; if attackers > blockers, lower-id attackers get
    blocked first.
  - `"no_attack"`: emit empty attacker + empty blocker sets. Combat
    becomes a no-op; useful for tests that need to drive multiple
    turns without combat damage.
- **`drive_combat_phase(py, rust, agent)`** — composes the standard
  DECLARE_ATTACKERS -> DECLARE_BLOCKERS -> COMBAT_DAMAGE ->
  END_OF_COMBAT walk with per-step parity asserts. Pre-condition:
  step==DECLARE_ATTACKERS. Post-condition: step==END_OF_COMBAT
  with combat state cleared on both engines. Replaces the
  round-13/14/15 inline scripts that each test had to spell out.
- **Decision functions** read PYTHON state (`py_state`) for
  emission construction; both engines maintain byte-equal field
  views by Phase 5/6 invariants, so reading from Python and
  applying on both engines via `step_both` produces identical
  post-state. Same shape as Phase 5's `combat_selector`. Agent does
  not touch RNG; combat decisions are pure functions of visible
  state.
- **Test surface** (4 new in `tests/test_trajectory_parity.py`):
  - `test_real_game_combat_attack_all_no_blocks_through_turn_11_parity`
    — drives `attack_all` agent over three combat rounds (turn 7,
    9, 11) on the vanilla 60-card deck. p0's Bears attacks
    unblocked; p1 life 20 -> 18 -> 16 -> 14 with byte-equal field
    views per round.
  - `test_real_game_combat_with_blocks_mutual_destruction_parity`
    — symmetric setup (both p0/p1 cast Bears at turns 5/6); turn
    7 p0 attacks; p1's sick Bears blocks (CR 302.1 — sick
    blocks). Both die in mutual 2/2 KO; both engines produce
    same graveyard state.
  - `test_real_game_combat_no_attack_strategy_parity` — pins the
    no-attack baseline path.
  - `test_real_game_combat_first_strike_parity` — uses
    `cross_engine.first_strike_side_channel` to inject a 2/2
    first-strike creature on p0's bf at turn 7, then drives
    combat via `attack_all_block_smallest`. Pins first-strike
    timing through the agent. xfail-tagged at injection step +
    drive step to surface real divergences as xfails rather than
    hard failures — currently passes byte-equal.
- **Unit tests** (7 new in `tests/test_trajectory.py`): validation
  surface (invalid strategy, default strategy, drive_combat_phase
  wrong-step rejection); decision-function shape on synthetic bfs
  (no-attack returns empty, attack_all returns empty blocks);
  block-assignment pairing (smallest-blocker-first, lower-id-
  attacker-first; attackers > blockers fall through unblocked).
- **Helper consolidation**: `_setup_p0_bears_at_turn_5` (existing
  pattern) + new `_setup_both_bears_by_turn_6` (drives both
  players' land plays + casts symmetrically through turn 6).

Gate: **395 passing** (was 384, +11 net). No divergences surfaced.

## Divergences surfaced in round-16

**None.** All four trajectory tests pass byte-equal across the full
multi-turn combat trajectories:

- 3 combat rounds of unblocked Bears attacks (turn 7, 9, 11) —
  byte-equal life total + zone evolution per round.
- Mutual 2/2 vs 2/2 KO — both bears land in their owners'
  graveyards on both engines with matching zone signatures.
- First-strike injection + combat through `attack_all_block_smallest`
  — byte-equal post-injection field view AND byte-equal post-combat
  field view. The first-strike timing path that
  Phase 5's `first_strike_selector` exercises on synthetic 7-card
  decks composes correctly under the real-game prefix.

The trajectory tests' value is in the **regression-pin** dimension —
any future change to Rust's combat ordering, first-strike substep
plumbing, or per-object combat-flag bookkeeping that breaks the
real-game flow will surface here even if Phase 5's synthetic
selectors keep passing.

## Round 17 enhancement work (this slice)

Closed by `feature/phase6-production-decklists`:

The Phase 6 trajectory-parity substrate was feature-complete after
round 16 but useful only on synthetic mono-color vanilla decks.
Round 17 extends the trajectory suite onto **real EoE decks** from
the live 17lands deck pool plus richer combat scenarios.

### Production-shape decklist loader (slice 1 of round 17)

New helpers in `mtg_bot.parity.trajectory`:

- **`load_production_deck(archetype, deck_pool_path=None)`** — reads
  one deck from `data/17lands/eoe_decks.json.gz` (the same pool
  self-play / iterate consume) and returns its 40-card name list.
  Resolves the pool path relative to the worktree's repo root with
  fallback to a sibling `mtg-bot/` main checkout (`data/` is
  gitignored, so a fresh worktree picks up the pool from the main
  checkout per the project's CLAUDE.md convention).
- **`production_deck_to_deckspec(p0_card_names, p1_card_names=None,
  *, shared_rng_seed=None, pad_to_size=60, pad_with="Forest")`** —
  filters a card-name list to the bridge-supported subset (basic
  lands + vanilla creatures), builds the union CardDef registry,
  pads short post-filter libraries with copies of `pad_with` to
  `pad_to_size`. Mirror-match defaults: when `p1_card_names` is
  None, p1 receives p0's filtered library.
- **`setup_matched_game_from_real_decks(...)`** — convenience
  wrapper that composes the loader + DeckSpec converter + matched-
  state setup. Same return contract as `setup_matched_game`.

**Filter rationale.** The CardDef bridge intentionally carries a
minimal cross-engine surface (name / type / mana cost / pt /
mana_produced / triggered_abilities-as-dict / subtypes). It does
NOT carry spell_effect, activated_abilities (other than the auto-
wired `{T}: Add C` for lands), static_abilities, keywords, ETB-
counter triggers, warp/kicker/impending costs, etc. Production EoE
creatures routinely carry rich fields the parser materializes on
Python's CardPrinting via the OracleParserCardSource path; Rust's
`register_printing` accepts only the schema shapes documented in
`cards.rs:parse_printing`. The pragmatic round-17 path: filter the
deck to cards both engines can register without effects /
triggers / keywords / etc. that don't have a matching cross-engine
bridge arm.

What survives the filter on the EoE pool today: basic lands
(Forest/Island/Plains/Mountain/Swamp/Wastes) plus vanilla creatures
(no keywords, no triggered_abilities, no activated_abilities, no
static_abilities, no spell_effect, no warp/kicker/impending). Per
spot-check on the EoE pool: ~5 vanilla creatures total (Emissary
Escort, Harmonious Grovestrider, Cosmogoyf, Magus of the Moon,
Spectral Snatcher) plus the basic lands. Most decks reduce to
"basic lands + 0-2 vanilla creatures" after filter; the loader
pads short decks with extra basics so trajectory tests always have
~60 cards to draw from.

### Three new RealGameCombatAgent strategies (slice 2 of round 17)

Extends the round-16 `RealGameCombatAgent` with three strategies
that exercise richer attacker / blocker logic than
`attack_all` / `attack_all_block_smallest` / `no_attack`:

- **`"attack_with_unblockable_creatures_only"`** — only declares
  attackers carrying an evasion keyword (`flying` / `unblockable` /
  `shadow`). Defender declines blocking. Useful for trajectory
  probes that want a guaranteed-through attack shape (e.g. a
  lifelink probe that needs the attacker to land combat damage on
  the player).
- **`"block_with_largest_able"`** — mirror of
  `"attack_all_block_smallest"` but defender picks the LARGEST
  creature per attacker (sorted by `(power desc, toughness desc,
  id asc)`). Pins the inverted block selector — verifies that the
  agent's block-assignment shape doesn't accidentally hardcode
  "smallest" anywhere.
- **`"optimal_no_loss_attack"`** — only declares attackers the
  defender CAN'T trade up against (no defender creature has
  `power >= attacker.toughness`). Static p/t only — no continuous
  effect / counter / removal modeling. Surfaces a non-trivial
  state-dependent attacker policy without needing to model deeper
  combat math.

### Trajectory tests (slices 3 + 4 of round 17)

- **3 production-deck trajectory tests** — load EoE archetype 0,
  setup matched states (parity-clean), walk turn 1 no-op + play
  turn-1 land (parity-clean per phase boundary).
- **2 new-strategy trajectory tests** — `block_with_largest_able`
  + `optimal_no_loss_attack` driven on the synthetic mutual-Bears
  setup.
- **3 keyword trajectory probes** — `_inject_keyword_creature_on_p0_bf`
  is the round-17 promotion of Phase 5's keyword side-channels
  (parameterized on keyword + printing name); used by:
  - `test_trample_overflow_to_player_parity` — 4/4 trample vs 2/2;
    trample spillover to defender (CR 702.19b).
  - `test_vigilance_attacker_untaps_parity` — vigilance attacker
    stays untapped post-DECLARE_ATTACKERS (CR 702.20). Co-injects
    a non-vigilance Bears so the test pins both the vigilance
    behavior AND the non-vigilance baseline.
  - `test_lifelink_combat_damage_to_self_parity` — 2/2 lifelink
    attacker unblocked; p0 gains 2 life (CR 702.15b).

Each keyword probe xfail-tags both the post-injection compare and
the `drive_combat_phase` call so a real divergence surfaces as an
xfail with a clear pointer rather than a hard failure. **All 3
probes pass byte-equal across both engines today.**

## Divergences surfaced in round-17

**None.** Every new test passes byte-equal across both engines:

- Production-deck setup → matched states with byte-equal field
  views.
- Production-deck turn 1 walk → byte-equal at every phase boundary.
- Production-deck play_land round-trips cleanly.
- The two new combat-strategy paths (block_with_largest,
  optimal_no_loss_attack) round-trip cleanly on the trajectory
  shape.
- Trample, vigilance, and lifelink combat compose correctly with
  the round-16 RealGameCombatAgent on the trajectory shape.

The trajectory tests' value is in the **regression-pin** dimension:
any future change to Rust's combat keyword-handling, basic-land
multi-color registry, or trample/lifelink damage-application that
breaks the real-game flow will surface here even if Phase 5's
synthetic selectors keep passing.

Gate: **424 passing** (was 400, +24 net).

## Round 18 enhancement work (this slice)

Closed by `feature/phase6-keyword-probes-deathtouch-doublestrike-haste`:

Round 18 extends the round-17 keyword-probe family with three more
combat-keyword trajectory probes — deathtouch, double-strike, and
haste — plus a sibling vanilla-creature injector helper for probes
that need a controlled blocker on the defender's bf.

### New helpers

- **`_inject_vanilla_creature_on_bf(py_state, rust_state, *,
  controller_idx, printing_name, power, toughness)`** — sibling of
  round-17's `_inject_keyword_creature_on_p0_bf`; injects a vanilla
  (no-keyword) creature on either player's bf with controlled p/t.
  Required for deathtouch + double-strike probes where the
  block-pairing has to be deterministic (the standard
  `_setup_both_bears_by_turn_6` Bears prefix can't be used because
  block-smallest assignments depend on attacker/blocker id ordering
  that's hard to pin without controlling the defender's exact
  creature inventory).

### Three new keyword trajectory probes

- **`test_deathtouch_combat_damage_kills_blocker_parity`** — 1/1
  deathtouch attacker vs 4/4 vanilla blocker. Per CR 702.2 the 1
  damage is lethal for the 4/4 blocker. Both creatures die; life
  totals unchanged. Passes byte-equal.
- **`test_double_strike_combat_damage_doubles_parity`** — 2/2
  double-strike attacker vs 2/2 vanilla blocker. Both engines agree
  byte-for-byte but BOTH spill double-strike's regular damage to
  the player when the blocker dies in first-strike (life_p1 == 18,
  not 20 per CR 510.1c). The probe pins the OBSERVED cross-engine
  agreement so a future regression on the matched behavior
  surfaces; the CR-vs-engine divergence is documented as a new
  `SEARCH_LIMITATIONS.md` entry ("Combat — double-strike regular
  damage spills past dead blocker (no trample required)").
- **`test_haste_attacker_no_summoning_sickness_parity`** — 2/2
  haste creature injected with summoning_sick=True (using Rust's
  `force_set_summoning_sick` test-helper escape hatch + Python's
  mutable `o.summoning_sick`); attacks unblocked for 2 damage. Pins
  CR 702.10's summoning-sickness bypass.

### Real bug surfaced + fixed

The haste probe surfaced a real gap in
`RealGameCombatAgent.pick_attackers`: the eligibility filter was a
hard `not o.summoning_sick`, silently excluding haste creatures
regardless of keyword. Updated the gate to
`(not o.summoning_sick or "haste" in o.printing.keywords)`. Same
Python-side keyword spelling that `combat.effective_keywords` reads
for the no-modifier case. The fix lives in
`src/mtg_bot/parity/trajectory.py` and is a Python-only change to
the agent's selector; no engine code changed.

## Divergences surfaced in round-18

- **Double-strike regular damage spills to player past a dead
  first-strike-killed blocker** — both engines treat the attacker
  as "unblocked" for the regular-damage substep when its blocker
  dies in first-strike, against CR 510.1c (only trample lets damage
  spill past blockers). Documented in `SEARCH_LIMITATIONS.md`.
  Engines agree byte-for-byte; this is an engine-vs-CR divergence,
  not a cross-engine one.
- **`RealGameCombatAgent` haste eligibility-gate bug** (FIXED in
  this round) — agent's hard `not o.summoning_sick` filter
  excluded haste creatures. Fixed by reading the keyword from
  `o.printing.keywords`.

Gate: **437 passing** (was 434, +3 net — one new probe per keyword).

## Suggested next slice

All four Phase 6 infrastructure gaps (#1 setup_matched_game,
#2 mulligan parity, #3 real-game combat agent, #4 action-dict
vocabulary) are CLOSED. Round 17 adds production-shape decklists,
three new combat strategies, and trample/vigilance/lifelink
trajectory probes on top of that substrate. Round 18 extends the
keyword-probe family with deathtouch / double-strike / haste +
fixes the agent's haste eligibility gate.

Remaining enhancement follow-ons after round 18:

- **Bilateral / asymmetric combat strategies** — current strategies
  are symmetric across both players (both sides apply the same
  attack_all rule on their respective active turns). Asymmetric
  strategies ("p0 attacks, p1 never attacks back") would let
  trajectory tests pin specific defensive patterns without
  needing a second `RealGameCombatAgent` per player. Round-17
  ships the agent shape that could carry per-side config, but the
  strategy enum stays mirror-symmetric for now.
- **Multi-attacker / multi-block combat surface on production
  decks** — round-16's smallest-blocker test only exercises 1
  attacker / 1 blocker. Round-17's `block_with_largest_able` test
  uses the same 1-blocker shape (so smallest and largest coincide).
  A wider production-shape deck with 2+ creatures per side would
  exercise the largest-vs-smallest selector divergence directly.
- **CardDef substrate extensions** — extending `CardDef` + bridge
  to carry keywords / activated_abilities / static_abilities /
  spell_effect would let production decks survive the filter
  with their real-game shape intact (rather than collapsing to
  "lands + vanilla creatures + padding"). Larger surface; would
  unblock real-EoE-decklist trajectory probes that exercise
  real-card combat / abilities.
- **State-conditional mulligan agents** — see gap #2 residuals.
- **Non-positional bottom strategies** — see gap #2 residuals.
- **Other combat-keyword trajectory probes** — round-17 added
  trample / vigilance / lifelink; round-18 added deathtouch /
  double-strike / haste. Menace, defender, indestructible,
  hexproof, flying have Phase 5 synthetic selectors but no
  trajectory probes yet.
- **Engine fix for double-strike + dead blocker spillover** — see
  the new `SEARCH_LIMITATIONS.md` entry. Both engines need to be
  updated in lockstep with this probe's expected value.

The Rust API gaps documented under gap #2's residuals
(non-positional bottom, state-conditional mulligan agents) are
candidate Rust slices for future rounds when production-shape
mulligan probes are needed.

## CardDef triggers substrate (this slice)

Extends the round-34 CardDef.keywords substrate with a parallel
`CardDef.triggered_abilities` propagation path so creatures with
**simple ETB triggers** that BOTH engines model byte-for-byte can
survive the bridge-simple filter.

- `_SAFE_TRIGGERS: frozenset[tuple[str, str|None, str]]` — starter
  allowlist of `(event, predicate_kind, effect_kind)` triples:
  `(enters, source_is_self, draw_cards)`,
  `(enters, source_is_self, gain_life)`,
  `(enters, source_is_self, scry_n)`. Each triple has an existing
  `cross_engine._ta_dict_to_python_effect` arm + a Rust
  `parse_effect` arm pinned by years of cross-engine probes
  (Slice 3 ETB substrate, Round 16 scry, Germinating Wurm probe).
- `_is_safe_trigger_dict(ta_dict)` — dict-shape gate. Validates
  the four-tuple plus an effect-payload key whitelist
  (`_SAFE_EFFECT_KEYS`) so a future schema extension can't slip
  through silently.
- `_python_ta_to_safe_dict(ta)` — Python-side round-trip converter.
  Returns the dict shape the bridge translator consumes, or `None`
  for triggers outside the safe set. The production-deck loader
  uses this as the gate.
- `_printing_is_bridge_simple_creature` admits a creature with
  triggered_abilities whose every entry round-trips cleanly. All
  other guards stay strict.
- `_printing_to_card_def` carries the dict-tuple through to the
  CardDef; the Slice-3 `cross_engine.build_*_state` arms then
  translate them onto each engine.

### Real-EoE consumers (descope)

ZERO at this slice's filter strictness — every candidate fails
on OTHER bridge-simple guards:

- **Germinating Wurm** (5/5 {4}{G}, ENTERS+IsSelf+GainLife(2))
  — Warp {1}{G} blocks via `warp_cost`.
- **Quantum Riddler** (4/6 {3}{U}{U}, ENTERS+IsSelf+DrawCards(1))
  — has a HandSizeAtMost replacement-effect AND Warp {1}{U};
  blocked by `static_abilities` and `warp_cost`.
- **Eumidian Terrabotanist / Tannuk, Memorial Ensign** — landfall
  triggers (predicate is `controlled_by_you` + `subject_is_land`,
  not `source_is_self`) — out of starter set.
- **Selfcraft Mechan** — Sequence-shape effect (sacrifice + counter
  + draw); above the leaf-effect floor.

Per round-34 carddef-substrate's "ship substrate + synthetic"
precedent (commit eec1ff57), this slice ships end-to-end on a
synthetic CardDef (`Carddef ETB Drawer`). Real-EoE consumers
unlock once **either**:

1. The `warp_cost` guard relaxes (would unblock Germinating Wurm
   on a no-warp-cast trajectory shape).
2. A `_SAFE_STATICS` allowlist covers HandSizeAtMost shape
   (would unblock Quantum Riddler).
3. `_SAFE_TRIGGERS` extends to the landfall predicate shape
   `(enters, controlled_by_you + subject_is_land, draw_cards)`
   plus a play-land trigger driver in the trajectory probe
   (would unblock Eumidian Terrabotanist + Tannuk).

### Test surface

- 15 unit tests in `tests/test_trajectory.py` cover the
  `_SAFE_TRIGGERS` allowlist contract, `_is_safe_trigger_dict`
  admit/reject paths (unsafe event/predicate/effect/once_per_turn/
  extra-key), `_python_ta_to_safe_dict` round-trip on all three
  starter effects + rejection paths,
  `_printing_is_bridge_simple_creature` admit/reject on safe vs
  unsafe trigger + mixed-trigger rejection,
  `_printing_to_card_def` propagation, and end-to-end CardDef-
  to-both-engines wiring via `setup_matched_game`.
- 3 trajectory probes in `tests/test_trajectory_parity.py`:
  setup-time field-view compare; 12-phase no-op walk on the same
  DeckSpec; cast-and-fire probe driving the cast on the pre-
  existing drawer in p0's opening hand (shared_rng_seed makes
  it land at hand index 2 on both engines), draining both
  stacks, and asserting hand size unchanged net (-1 cast +1
  drawn) + library shrank by 1 + drawer on bf + post-drain
  field-view byte-equal.

No divergences surfaced — all new tests pass byte-equal across
both engines on first run.
