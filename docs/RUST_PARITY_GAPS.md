# Rust engine parity gaps and invariants

This document consolidates every parity-load-bearing divergence, parity
invariant, and pinned regression baseline that the Rust port test
suite has discovered through the r25 edge-case wave. It is intended
to be the checklist that the eventual 1000-game cross-engine smoke
harness consumes when it sees a Python-vs-Rust state difference.

## What this is for

When the 1000-game smoke runs Python and Rust engines side-by-side
on the same deck + seed + decision script and observes a divergence,
the operator needs to answer one question quickly: *is this a real
parity bug, or an already-known accepted divergence?*

This file is the first lookup. Each entry below is pinned by a test
file in `tests_rust/` so a regression on either side surfaces as a
test failure on that file, not as a mystery smoke divergence.

The companion file `docs/SEARCH_LIMITATIONS.md` documents
search-side / `legal_decisions` shortcuts; this file is broader and
covers engine-state divergences across all primitives.

How the smoke consumes this doc:

1. Smoke run records the first decision index where Python and Rust
   diverge, plus the two fingerprints.
2. Operator opens this doc and scans the "Confirmed gaps" table for
   a description matching the observable symptom (e.g. "mana pool
   non-empty when it shouldn't be", "creature still on the battlefield
   after lethal damage").
3. If found, the entry's "Likely impact" cell tells them whether to
   filter the divergence out of the smoke summary or to escalate it.
4. If not found, it's a NEW divergence and gets escalated to a
   dedicated parity-debug session.

---

## Confirmed gaps

Each entry: short name, pinning test, current Rust behavior, expected
behavior per CR / Python, parity impact, and closeable / accepted.

### G5. `legal_decisions(non_priority_player)` returns the `[pass_priority]` singleton

- **Pinned by**: `tests_rust/test_priority.py::test_legal_decisions_for_non_priority_player_still_emits_pass_priority`;
  also `tests_rust/test_legal.py::test_legal_decisions_priority_off_emits_only_pass_priority`.
- **Rust today**: Asking `legal_decisions(p)` where `p` is NOT the
  current priority player still returns a `[pass_priority]` list, not
  an empty list.
- **CR / Python expected**: This is intended parity with Python's
  `legal.py:180-181` short-circuit — Python returns the same
  singleton.
- **Impact**: none — this is a parity INVARIANT documented here for
  context because the file-name "gap" would be misleading. Listed
  here so a future Rust refactor that wants to change "off-priority
  → no actions" notices this is intentional Python parity.
- **Closeable**: not a gap — it is the deliberate parity contract.
  See invariant I5 for the matching invariant entry.

### G8. `+1/+1` vs `-1/-1` counters cancel as net-i32 at write time, not as separate stacks at SBA

- **Pinned by**: `tests_rust/test_counters.py::test_plus_one_minus_one_cancellation_quirk_net_i32_collapses_pre_sba`.
- **Rust today**: Counters are a single signed `i32` per object.
  Adding +3 then -2 stores net +1 immediately, BEFORE any SBA pass.
- **CR / Python expected**: CR 704.5r / 704.5p — +1/+1 and -1/-1
  counters are distinct counter kinds and cancel pairwise at SBA
  time. Python stores them as distinct stacks and cancels at
  `state_based_actions`.
- **Impact**: low for destruction outcomes (the post-cancellation
  effective P/T matches), but inexpressible queries like "how many
  +1/+1 counters does this creature have?" diverge. Not directly
  observable through the fingerprint or zone-snapshot surface in
  current scope.
- **Closeable**: requires a multi-kind counter map. Future slice.

### G9. No dedicated counter-snapshot getter; per-object scalar is the snapshot

- **Pinned by**: `tests_rust/test_counters.py::test_counters_surface_through_battlefield_snapshot_round_trip`
  (and its docstring note).
- **Rust today**: Counters surface only through the per-object
  `counters` slot in `battlefield_snapshot` dicts. No `counter_snapshot`
  or similar getter exists.
- **CR / Python expected**: not a CR rule — this is a parity-surface
  gap. Python's snapshot shape has the same single-scalar shape today,
  so no actual divergence yet. Listed here as a forward-looking note:
  when Rust grows a multi-kind counter map (G8), it will need a
  matching snapshot getter or the parity surface will desync.
- **Impact**: zero today, high when G8 is closed.
- **Closeable**: bundled with G8.

### G12. Mutual KO model is two sequential `lose_life` calls, not a single Effect

- **Pinned by**: `tests_rust/test_winloss.py::test_mutual_zero_via_sequential_lose_life_is_draw` (docstring note: "the closest cross-feature analog the Rust engine exposes for 'both die in the same event'").
- **Rust today**: There is no single Effect that drops both players
  to 0 atomically. Mutual-KO outcomes have to be reproduced by two
  back-to-back `lose_life(p, n)` calls followed by `apply_sbas_until_quiescent`.
- **CR / Python expected**: Real MTG sees "both players reduced to 0
  simultaneously" via combat damage or symmetric Effects.
  `is_draw == True` is the parity-load-bearing outcome regardless of
  how the state was constructed.
- **Impact**: low — the observable end-state (`is_draw`, `losers
  == [0, 1]`) matches; only the construction shape diverges.
- **Closeable**: deferred until symmetric-Effect machinery lands.

### G13. `apply_sbas_until_quiescent` is a no-op after game-over

- **Pinned by**: `tests_rust/test_winloss.py::test_apply_sbas_until_quiescent_after_game_over_is_noop`.
- **Rust today**: Once the game is decided (one or both players in
  losers), subsequent `apply_sbas_until_quiescent` calls return 0
  passes and leave outcome state stable.
- **CR / Python expected**: parity invariant — Python also stops
  doing SBA work once the game has ended.
- **Impact**: none — this is the parity-load-bearing post-game-over
  no-op contract. Listed here for clarity. See invariant I7.
- **Closeable**: not a gap. Parity invariant.

### G16. `set_phase` does not fire the untap sweep

- **Pinned by**: `tests_rust/test_steps.py::test_set_phase_does_not_fire_untap_sweep`.
- **Rust today**: `set_phase(PHASE_UNTAP)` is a raw assignment — it
  does NOT trigger `untap_all_for_player` or the summoning-sick
  clear hook. Only `advance_phase` composes those side-effects.
- **CR / Python expected**: not directly a CR gap; this is the
  Rust-internal asymmetry between `set_phase` (test setup primitive)
  and `advance_phase` (game-loop primitive). Python has no `set_phase`
  equivalent — its turn loop only advances.
- **Impact**: zero in real play (the smoke harness never uses
  `set_phase`). Listed here so a future consolidation of the two
  entrypoints updates this test deliberately.
- **Closeable**: not a gap — deliberate asymmetry.

### G17. `register_and_inject_object` rejects negative-amount `AddManaToPool` at parse time

- **Pinned by**: `tests_rust/test_mana.py::test_add_mana_to_pool_effect_rejects_negative_amount_at_register_time`.
- **Rust today**: The bridge `parse_effect` enforces `amount >= 0`
  when reading a printing dict's `add_mana_to_pool` entry; an
  ill-formed printing fails REGISTRATION with `ValueError` rather
  than reaching the stack-resolution path.
- **CR / Python expected**: Parity — Python's printing parser is
  similarly strict; no silent no-op path for negative-amount mana.
- **Impact**: none — parity invariant. Listed because the location
  of the check (parse time, not apply time) is non-obvious for
  cross-engine debugging. See invariant I3.
- **Closeable**: not a gap.

### G18. `ActivateAbility` credits the source's controller, not `active_player`

- **Pinned by**: `tests_rust/test_mana.py::test_activate_ability_credits_source_controller_not_active_player`.
- **Rust today**: The mana-ability arm in `state_ops_actions.rs`
  reads the source's battlefield owner and credits THAT player's
  mana pool, NOT `state.active_player`. Activating a Forest on p1's
  battlefield while p0 is active adds {G} to p1's pool.
- **CR / Python expected**: Parity — Python's `ActivateAbility`
  resolves controller from the source object.
- **Impact**: none — parity invariant. Listed because the choice
  of who-gets-credited is non-obvious. See invariant I9.
- **Closeable**: not a gap.

### G19. SearchLibraryForBasicLandTapped does not shuffle (CR 701.19 / 701.22)

- **Pinned by**: `tests_rust/test_library.py::test_effect_search_library_for_basic_land_tapped_enters_tapped`
  (docstring note); also tracked in `docs/SEARCH_LIMITATIONS.md`.
- **Rust today**: The round-23 first slice does NOT shuffle the
  library after the deterministic first-match-from-top search.
- **CR / Python expected**: CR 701.19 / 701.22 — search-then-shuffle
  effects always shuffle, whether or not a card was found.
- **Impact**: medium. Visible whenever a search effect runs; the
  resulting library order will diverge from Python.
- **Closeable**: yes — pending RNG externalization work to seed the
  shuffle deterministically inside `apply_effect`.

### G24. No scry-on-keep step after mulligan-to-7 (Paris rule)

- **Pinned by**: `tests_rust/test_mulligan.py` module docstring (gap 4).
- **Rust today**: Keeping a mulliganed hand does NOT trigger any
  scry. The Paris rule (one scry after each mulligan you kept on
  7) is not modeled.
- **CR / Python expected**: CR 103.4 Paris mulligan — one scry on
  each mulliganed-then-kept hand. Python's flow models this if
  enabled.
- **Impact**: low — only visible if the parity harness exercises
  the post-mulligan scry decision.
- **Closeable**: yes — pending Paris-rule decision-callback slice.

---

## Parity invariants

Behaviors where Rust matches Python by design. Pinned so a future
refactor on either side that breaks the parity surfaces immediately.

### I1. Fingerprint is order-INSENSITIVE for mana pool

- **Pinned by**: `tests_rust/test_fingerprint.py::test_fingerprint_insensitive_to_mana_pool_add_order`.
- **Invariant**: The fingerprint serializes mana pools by sorted
  color-key (Python: `tuple(sorted({"W":w,...}.items()))`; Rust:
  a fixed-order 6-element vec keyed B/C/G/R/U/W). Adding {W} then
  {B} produces the same digest as adding {B} then {W}.

### I2. Fingerprint hashes printing.NAME but NOT card_types or effects-text

- **Pinned by**: `tests_rust/test_deck.py::test_make_state_fingerprint_differs_when_registry_name_differs`
  (positive case — name change moves the digest); the absence of
  card_types / effects-text in the per-object 8-tuple `(printing_name,
  tapped, summoning_sick, damage, counters, attached_to, controller_id, id)`
  is documented in `test_fingerprint.py` module docstring.
- **Invariant**: Two states identical except for the registry's
  `card_types` list or effect-text on the SAME printing_id will
  fingerprint identically. Two states where printing.NAME differs
  produce different fingerprints.

### I3. Negative-amount `AddManaToPool` rejected at `parse_effect`, not at apply time

- **Pinned by**: `tests_rust/test_mana.py::test_add_mana_to_pool_effect_rejects_negative_amount_at_register_time`,
  `test_add_mana_negative_amount_raises`.
- **Invariant**: There is no silent-no-op path for negative-amount
  mana addition anywhere in the engine. Both `add_mana(p, c, -1)`
  and registering a printing with `{"add_mana_to_pool", amount: -1}`
  raise `ValueError`.

### I4. `legal_decisions(priority_holder)` emits `pass_priority` at index 0

- **Pinned by**: `tests_rust/test_priority.py::test_legal_decisions_for_priority_holder_emits_pass_priority`.
- **Invariant**: Whoever currently holds priority always has at least
  one legal decision, and that decision is always `pass_priority` at
  index 0 (mirrors Python `legal.py:178`).

### I5. `legal_decisions(non_priority)` returns the `[pass_priority]` singleton

- **Pinned by**: `tests_rust/test_priority.py::test_legal_decisions_for_non_priority_player_still_emits_pass_priority`,
  `tests_rust/test_legal.py::test_legal_decisions_priority_off_emits_only_pass_priority`.
- **Invariant**: Asking `legal_decisions(p)` where `p` does NOT hold
  priority returns `[pass_priority]`, NOT an empty list. Mirrors
  Python's `legal.py:180-181` short-circuit.

### I6. Fingerprint preserves CoW isolation after mutation

- **Pinned by**: `tests_rust/test_fingerprint.py::test_fingerprint_clone_isolation_after_mutation`,
  `test_fingerprint_clone_isolation_zone_mutation`,
  `test_fingerprint_clone_replay_equality_after_each_mutation`.
- **Invariant**: `state.clone_once().fingerprint() ==
  state.fingerprint()` at every step of an in-place mutation
  sequence; mutating the source does not move the clone's digest.

### I7. `apply_sbas_until_quiescent` after game-over is a no-op

- **Pinned by**: `tests_rust/test_winloss.py::test_apply_sbas_until_quiescent_after_game_over_is_noop`.
- **Invariant**: Once the game is decided, repeated SBA-loop calls
  return 0 passes and the outcome reads are stable.

### I8. Active and priority player are independent

- **Pinned by**: `tests_rust/test_priority.py::test_pass_priority_does_not_affect_active_player`.
- **Invariant**: `pass_priority` moves only `priority_player`;
  `active_player` only changes on `advance_phase`'s CLEANUP -> UNTAP
  wrap.

### I9. `ActivateAbility` credits source.controller (not active_player)

- **Pinned by**: `tests_rust/test_mana.py::test_activate_ability_credits_source_controller_not_active_player`.
- **Invariant**: Mana from a tapped Forest is always credited to the
  Forest's controller, not the current active player.

### I10. Tap and summoning_sick are independent fields

- **Pinned by**: `tests_rust/test_tap.py::test_untap_all_for_player_leaves_summoning_sick_alone`.
- **Invariant**: `untap_all_for_player` flips only `tapped`;
  `summoning_sick` is owned by a separate sweep in
  `state_ops_steps.rs`.

### I11. Fingerprint sensitivity for each top-level GameState field

- **Pinned by**: `tests_rust/test_fingerprint.py::test_fingerprint_sensitive_to_priority_player`,
  `test_fingerprint_sensitive_to_phase`,
  `test_fingerprint_sensitive_to_active_player_and_turn_number`.
- **Invariant**: Mutating any of `priority_player`, `phase`,
  `active_player`, `turn_number` shifts the digest.

### I12. Fingerprint sensitivity for each GameObject field

- **Pinned by**: `tests_rust/test_fingerprint.py::test_fingerprint_sensitive_to_tapped_flag`,
  `test_fingerprint_sensitive_to_damage_stamp`,
  `test_fingerprint_sensitive_to_counters_value`.
- **Invariant**: Mutating any of `tapped`, `damage`, `counters` on a
  battlefield permanent shifts the digest.

### I13. Fingerprint is order-SENSITIVE for library and stack

- **Pinned by**: `tests_rust/test_fingerprint.py::test_fingerprint_sensitive_to_library_order`,
  `test_fingerprint_sensitive_to_stack_order`.
- **Invariant**: Two states with identical library/stack CONTENTS in
  different orders produce different fingerprints. Python's
  `hash_state` walks the same zones in iteration order, so swaps are
  observable on both sides.

### I14. Empty-library mill / search returns 0 / None without raising

- **Pinned by**: `tests_rust/test_library.py::test_mill_target_player_empty_library_returns_zero`,
  `test_search_and_shuffle_empty_library_returns_none`,
  `test_search_library_by_type_empty_library_returns_none`.
- **Invariant**: Mill / search against an empty library is a quiet
  no-op (returns 0 or None) — the loss path only fires on a *draw*
  attempt against an empty library (and even that is currently G10).

### I15. `set_phase` does not trigger the untap sweep

- **Pinned by**: `tests_rust/test_steps.py::test_set_phase_does_not_fire_untap_sweep`.
- **Invariant**: `set_phase` is a raw assignment; `advance_phase` is
  the composition entrypoint. Only the latter fires untap +
  summoning-sick-clear hooks.

### I16. `find_object_zone` after `make_state` agrees with the deck-load zone-stamp

- **Pinned by**: `tests_rust/test_deck.py::test_find_object_zone_after_make_state_agrees_with_setup`.
- **Invariant**: Every library object reads `ZONE_LIBRARY`; every
  hand object reads `ZONE_HAND` immediately after `make_state`.

### I17. Summoning-sick permanents with tap-cost activated abilities are excluded from both dispatch and emission

- **Pinned by**: `tests_rust/test_tap.py::test_activate_ability_on_summoning_sick_creature_with_tap_cost_is_rejected`;
  `tests_rust/test_legal.py::test_legal_decisions_activate_ability_excludes_summoning_sick_creature`.
- **Invariant**: CR 302.1 — a creature with `summoning_sick == true`
  whose activated ability has a tap cost (e.g. `{T}`) cannot pay
  that cost. The Rust port enforces this gate on BOTH sides:
  `apply_action`'s `ActivateAbility` arm in `state_ops_actions.rs`
  raises `ValueError` (no mutation), and the `legal_decisions`
  emitter in `state_ops_legal.rs` does NOT emit an
  `ActivateAbility` dict for the sick source. The general gate is
  `summoning_sick && requires_tap_cost`; the first-slice
  mana-only filter (the only wired ActivateAbility dispatch case
  today, where every printing's mana ability has an implicit
  `{T}`) gates on `summoning_sick` alone. Mirrors Python's
  `legal.py:661-663` and `actions.py:_activate_ability`
  precheck. Closes parity gap G6 (entry removed from "Confirmed
  gaps" above).

### I18. `advance_phase` auto-fires `draw_card` on entry to PHASE_DRAW, gated by CR 103.7c

- **Pinned by**:
  `tests_rust/test_steps.py::test_advance_phase_draws_a_card_on_entering_draw_step`,
  `tests_rust/test_steps.py::test_advance_phase_first_turn_active_player_skips_draw_step`,
  `tests_rust/test_steps.py::test_advance_phase_p1_first_draw_step_does_draw_card`.
- **Invariant**: CR 504.1 — the active player draws one card on
  entering their draw step. `advance_phase` calls `draw_card` for
  the active player whenever the new phase becomes `PHASE_DRAW`,
  gated by the CR 103.7c first-turn skip (`turn_number != 1`).
  Mirrors Python's `simulate.py` gate, which uses the same
  `state.turn_number != 1` shape (rationale: on turn 1 the active
  player IS the starting player, so `turn_number` alone fully
  determines the skip in a two-player game). Closes parity gap G14
  (entry removed from "Confirmed gaps" above).

### I19. Empty-library draw flags the player; `apply_sbas` locks the loss into the sticky `has_lost`

- **Pinned by**:
  `tests_rust/test_library.py::test_drawcards_from_empty_library_marks_player_for_loss_on_next_sba`,
  `test_drawcards_count_larger_than_library_drains_then_loses_on_sba`,
  `tests_rust/test_zones.py::test_draw_card_from_empty_library_returns_none`
  (no-crash + cause-signal side-effect),
  `tests_rust/test_winloss.py::test_explicit_lose_game_marks_player`,
  `test_each_opponent_loses_life_lethal_then_sba_locks_the_loss`.
- **Invariant** (CR 704.5b / CR 104.2 — round-26 G10 + G11 closure):
  - The `draw_card` primitive AND the `Effect::DrawCards`
    resolution arm flip `Player.attempted_draw_on_empty = true`
    when the library pop returns `None`.
  - `losers()` returns a player if **any** of the OR'd-three signals
    are true: `has_lost`, `attempted_draw_on_empty`, or `life <= 0`.
    Read directly (no SBA pass required) so the loss is observable
    eagerly — mirrors Python's `p.has_lost = True` in
    `turn.draw_card`.
  - `apply_sbas` transitions the cause-signals (`attempted_draw_on_empty`
    OR `life <= 0`) into the sticky `Player.has_lost = true`. Once
    `has_lost` is set, no `gain_life` can revive the player. The
    return value of `apply_sbas` remains the count of CREATURES
    destroyed in the pass — the player-loss transition doesn't bump
    it (separate SBA category in CR ordering).
  - The pure-derivation revive semantics on `life <= 0` are preserved
    UNTIL `apply_sbas` runs (so `set_life(0, 0); gain_life(0, 5)`
    without an SBA pass in between still flips the player back out of
    `losers()` — see `test_gain_life_from_zero_revives_player`).
  - The explicit `lose_game(p)` primitive (Phage / Bargain) sets
    `has_lost` directly without going through SBA — useful for
    "you lose the game" cards where life is not the trigger.

### I20. `advance_phase` fully composes phase-boundary side effects (CR 106.4 / 514.1 / 514.2)

- **Pinned by**:
  `tests_rust/test_mana.py::test_mana_pool_empties_on_advance_phase`;
  `tests_rust/test_cleanup.py::test_end_turn_and_start_next_empties_mana_pool`,
  `test_advance_phase_through_cleanup_enforces_hand_size`;
  `tests_rust/test_steps.py::test_advance_phase_empties_both_mana_pools_on_every_tick`,
  `test_advance_phase_empties_mana_pool_across_every_phase_in_lap`,
  `test_advance_phase_into_cleanup_fires_hand_size_discard`,
  `test_advance_phase_into_cleanup_fires_damage_clear`,
  `test_advance_phase_cleanup_hook_targets_old_active_player`,
  `test_advance_phase_cleanup_hook_idempotent_when_hand_at_max`,
  `test_clone_advance_phase_into_cleanup_does_not_affect_original`.
- **Invariant**: Closing the round-26 G1 + G2 gaps. Every
  `advance_phase` tick empties both players' mana pools BEFORE the
  phase counter ticks forward (CR 106.4 — mana pool empties on
  phase exit). Whenever the new phase is `PHASE_CLEANUP`,
  `advance_phase` fires the inline mirror of
  `cleanup_step_for_active_player` on entry: CR 514.1 hand-size
  discard for the active player (max=7, deterministic-end-of-Vec
  pop) followed by CR 514.2 marked-damage clear on both
  battlefields. Combined with the round-2 untap sweep, the
  round-14 summoning-sick clear, and the round-26 G14 auto-draw,
  `advance_phase` now models every phase-entry / phase-exit hook
  the Rust engine carries. The `cleanup_step_for_active_player`
  primitive itself remains layered below CR 106.4 (calling it
  directly does NOT empty mana pools — see
  `test_cleanup.py::test_cleanup_step_does_not_empty_mana_pool_at_primitive_layer`);
  the mana-empty hook is owned exclusively by `advance_phase`.

### I24. `mulligan_atomic` folds shuffle + redraw-7 + bottom-N into one transaction (CR 103.4 London)

- **Pinned by**:
  `tests_rust/test_mulligan.py::test_mulligan_atomic_seventh_call_succeeds_eighth_raises`,
  `test_mulligan_atomic_bottoms_correct_number_for_each_mulligan_count`,
  `test_mulligan_atomic_bottom_count_mismatch_raises`,
  `test_mulligan_atomic_invalid_card_id_raises`,
  `test_mulligan_atomic_hand_size_invariant`,
  `test_mulligan_atomic_library_grows_by_old_hand_minus_bottom`,
  `test_mulligan_atomic_clone_isolation`,
  `test_mulligan_atomic_fingerprint_stable_for_same_seed_and_bottoms`.
- **Invariant** (CR 103.4 / round-27 G21 + G22 closure):
  - `mulligan_atomic(player_id, seed, bottom_card_ids)` is the
    parity-correct entrypoint for the harness. The Nth mulligan
    (per-player `mulligan_count` is N-1 at call time, becomes N
    after the increment) bottoms exactly N cards — the
    `bottom_card_ids.len() == mulligan_count + 1` pre-check fires
    BEFORE the increment / shuffle / bottoming so a wrong-count call
    leaves state byte-identical.
  - Ordering is (1) player_id validation, (2) bottom-count pre-check,
    (3) increment `mulligan_count`, (4) cap check (> 7 raises),
    (5) shuffle library (drain hand + Fisher-Yates with `seed` +
    redraw 7), (6) verify each `bottom_card_id` is in the post-redraw
    hand AND that the list contains no duplicates, (7) remove each
    chosen id from hand and insert at `lib[0]` in REVERSE iteration
    order so the FIRST id supplied lands at the very bottom (matches
    `bottom_cards_from_hand`'s orientation contract).
  - Hand-size invariant: post-call hand size is always
    `7 - mulligan_count` (drew 7, bottomed `mulligan_count`). A caller
    using the atomic primitive can NEVER observe a state with the
    hand still at 7 after the Nth mulligan — closes the G21 / G22
    observable gap.
  - Bottom-count mismatch (`bottom_card_ids.len() !=
    mulligan_count + 1`) raises BEFORE any mutation; the state's
    fingerprint, hand size, library size, and `mulligan_count` are
    all unchanged.
  - Cap shared with the legacy `mulligan` / `mulligan_to_n`: the
    7-call total is per-player and counts atomic calls too. The 8th
    call raises with no zone mutation (the cap check fires before
    the shuffle), though `mulligan_count` itself was bumped (matches
    legacy ordering).
  - Invalid `bottom_card_id` (not in post-redraw hand) OR duplicate
    ids raise AFTER the shuffle has happened — the bottom step is
    skipped but the shuffle has already mutated state. Callers should
    pre-compute valid ids by probing a clone with the same `seed`.
  - The legacy `mulligan`, `mulligan_to_n`, and `bottom_cards_from_hand`
    primitives are KEPT for backwards compatibility; only
    `mulligan_atomic` is the parity-correct entrypoint for new
    callers. Closes parity gaps G21 + G22 (entries removed from
    "Confirmed gaps" above).

### I25. Priority composition layer: `pass_priority` increments a counter, non-pass mutations reset it, `complete_step_via_priority_round` routes between CR 117.4 / 117.5 legs, and `advance_phase` resets priority on the CLEANUP -> UNTAP wrap (CR 117.1a / 117.1c / 117.4)

- **Pinned by** (round-27 G3 + G4 + G15 closure):
  - **Counter increment + reset**: `tests_rust/test_priority.py::test_consecutive_passes_increments_on_each_pass`,
    `test_consecutive_passes_resets_on_non_pass_action`,
    `test_complete_priority_round_resets_consecutive_passes`,
    `test_pass_priority_alone_does_not_advance_step_or_resolve`.
  - **G3 composer (`complete_step_via_priority_round`)**:
    `tests_rust/test_priority.py::test_complete_step_via_priority_round_advances_step_when_stack_empty`,
    `test_complete_step_via_priority_round_resolves_top_when_stack_nonempty`,
    `test_complete_step_via_priority_round_with_multi_item_stack_pops_only_top`,
    `test_complete_step_via_priority_round_resets_priority_to_active_after_resolution`;
    cross-feature: `tests_rust/test_stack.py::test_complete_step_via_priority_round_drains_then_advances`.
  - **G4 (cast / activate reset priority to active)**:
    `tests_rust/test_priority.py::test_cast_spell_resets_priority_to_active`,
    `test_cast_spell_failure_does_not_touch_priority`,
    `test_activate_mana_ability_resets_priority_to_active`.
  - **G15 (advance_phase priority reset on wrap)**:
    `tests_rust/test_priority.py::test_advance_phase_full_lap_resets_priority_to_active_at_wrap`,
    `test_priority_unaffected_by_advance_phase_within_a_turn`;
    `tests_rust/test_steps.py::test_advance_phase_keeps_priority_player_in_sync_with_active`.
- **Invariant** (CR 117.1a / CR 117.1c / CR 117.4 / CR 117.5 / round-27 G3 + G4 + G15 closure):
  - `GameState.consecutive_passes: u8` tracks consecutive `pass_priority`
    calls since the last non-pass mutation. `pass_priority` increments
    it (saturating); every non-pass mutation
    (`cast_creature`, `apply_action` for non-PassPriority arms,
    `advance_phase`, `give_priority_to`, the round-9
    `complete_priority_round` composer, and the new
    `complete_step_via_priority_round` composer's resolution leg)
    resets it to 0.
  - `complete_step_via_priority_round() -> bool` is the harness-facing
    "both players have passed" composer. Internally calls
    `pass_priority` twice, then routes by stack state:
    - **Non-empty stack** → CR 117.4 / 117.5: pop the top, reset
      `priority_player = active_player` (CR 117.1c), reset
      `consecutive_passes`, return `False` (no step advance).
    - **Empty stack** → CR 117.4: call `advance_phase` (which handles
      mana-empty, the per-phase hooks, the CLEANUP -> UNTAP wrap with
      the CR 117.1a priority reset, and the consecutive_passes reset),
      return `True` (step advanced).
    Mirrors Python's `simulate.py:priority_loop` logic (lines
    245-280): when `pass_count >= alive_count()` with `state.stack`
    non-empty, call `resolve_top_of_stack` and reset
    `priority_idx = state.active_player_idx`; with empty stack,
    return (end-of-step). The pop-only stepping-stone shape (no
    effect dispatch) is preserved — real effect dispatch is the
    job of `resolve_top_of_stack` in `state_ops_resolve.rs` per
    the cross-file private-method friction documented on the
    older `complete_priority_round`.
  - `cast_creature` resets `priority_player = active_player` AND
    `consecutive_passes = 0` on a successful cast (CR 117.1c).
    Failure paths (precondition gate, insufficient mana) are a
    no-op on priority — the reset only fires after a successful
    mutation. Mirrors Python's no-stack semantics where the
    primitive fuses push + resolve and "priority returns to AP"
    fires once at the end.
  - `apply_action` resets `priority_player = active_player` AND
    `consecutive_passes = 0` after EVERY non-PassPriority arm
    succeeds (PlayLand / DeclareAttackers / DeclareBlockers /
    CastSpell / ActivateAbility). PassPriority itself flows through
    the underlying `pass_priority` toggle and INCREMENTS the
    counter instead. Mirrors Python's `simulate.py:priority_loop`
    pattern of `priority_idx = state.active_player_idx` after
    every non-pass branch.
  - `advance_phase` resets `priority_player = active_player` on the
    CLEANUP -> UNTAP wrap (CR 117.1a — the new active player gets
    priority at the start of their turn). Within-turn step advances
    do NOT touch priority (the within-step CR 117.1a reset is the
    composer's responsibility, not `advance_phase`'s). Mirrors
    Python's `simulate.py:212-213` which sets
    `state.priority_player_idx = 0` at the start of turn 1.
  - `consecutive_passes` is NOT serialized into the fingerprint —
    like `mulligan_count` (I21), it's a transient bookkeeping
    counter, not part of the gameplay-relevant state digest. Pinned
    fingerprint baselines below are unchanged. Closes parity gaps
    G3, G4, and G15 (entries removed from "Confirmed gaps" above).

### I21. `mulligan` / `mulligan_to_n` raise after 7 calls per player (CR 103.4 cap)

- **Pinned by**:
  `tests_rust/test_mulligan.py::test_mulligan_seven_calls_succeed_eighth_raises`,
  `test_mulligan_to_n_seven_calls_succeed_eighth_raises`,
  `test_mulligan_cap_is_shared_between_mulligan_and_mulligan_to_n`,
  `test_mulligan_cap_is_per_player`,
  `test_mulligan_cap_raise_does_not_mutate_state`,
  `test_mulligan_count_does_not_affect_fingerprint`.
- **Invariant** (CR 103.4 / round-26 G23 closure):
  - `Player.mulligan_count: u32` increments at the START of every
    `mulligan` / `mulligan_to_n` call (shared counter between the
    two variants).
  - If the post-increment count exceeds 7, the call raises
    `PyValueError` BEFORE touching any zone. Pinned baselines after
    7 successful mulligans are unchanged when an 8th call raises.
  - Mirrors Python `simulate.setup_game(max_mulligans=7)` — the
    London-mulligan loop allows up to 7 mulligans per player before
    forcing a keep. An 8th call would draw a hand of -1 cards, which
    is nonsensical.
  - The counter is per-player; capping player 0 does not affect
    player 1.
  - `mulligan_count` is NOT serialized into the fingerprint — it's a
    per-call safety counter, not part of the gameplay-relevant state
    digest. Pinned fingerprint baselines below are unchanged. Closes
    parity gap G23 (entry removed from "Confirmed gaps" above).

### I22. Decision-callback substrate via `pending_decisions` (CR 701.43 Surveil; G20 closure)

- **Pinned by**: every test in
  `tests_rust/test_pending_decisions.py`; the round-23 baselines in
  `tests_rust/test_resolve.py::test_resolve_surveil_*` and
  `tests_rust/test_library.py::test_effect_surveil_first_slice_keeps_library_and_top_id_unchanged`
  still hold via the auto-resolve path.
- **Invariant** (round-27 G20 closure):
  - `GameState.pending_decisions: Vec<PendingDecision>` — a FIFO
    queue of choices the engine is waiting on. The first variant is
    `PendingDecision::SurveilChoice { source_obj_id, controller,
    cards }`. Future variants (G22 `LondonBottomN`, G24
    `ScryOnKeep`, future `ModalChooseOne` / `ManifestDread`) follow
    the same shape.
  - `Effect::Surveil` pops `min(count, library_len)` cards off
    library top and packages them into a `SurveilChoice` — the cards
    live in NEITHER library nor graveyard while the decision is
    pending. The arm short-circuits; nothing else mutates.
  - `state.has_pending_decision()` / `state.pending_decisions()` —
    introspection. `state.submit_surveil_decision(top_ids,
    graveyard_ids)` — the dispatcher: every pending id must appear
    in exactly one list; mismatches raise `ValueError`
    transactionally (no mutation on failure). The dispatcher routes
    `top_ids` back to library top in the submitted order (`top_ids[0]`
    is the topmost card after submission) and `graveyard_ids` into
    the controller's graveyard in the submitted order.
  - `state.auto_resolve_pending_decisions(strategy)` — deterministic
    drain for callers that don't model the choice dimension.
    Strategies: `"keep_all_on_top"` (the round-23 baseline, bit-equal
    to the pre-r27 path) and `"send_all_to_graveyard"` (mirror, for
    surveil-for-graveyard-fill effects). An unknown strategy raises
    `ValueError` transactionally.
  - `resolve_top_of_stack` opts INTO `"keep_all_on_top"` auto-resolve
    at the end so existing baseline tests (round-23 Surveil etc.) are
    bit-equal to the pre-r27 path. The new
    `resolve_top_of_stack_pause` pymethod runs the same flow WITHOUT
    auto-resolving — for callers (tests, MCTS, parity_smoke) that
    want to inspect / submit decisions.
  - The queue participates in `Clone` (cloned with the state) and in
    fingerprint serialization: a state with a pending decision
    hashes differently from one without. The fingerprint serializer
    appends the pending-decisions slot ONLY when non-empty, so
    pre-r27 pinned baselines (every state in `test_fingerprint.py`
    has empty `pending_decisions`) remain bit-equal — no baseline
    shifts in this slice.
  - Mirrors Python's pause-and-resume decision shape in
    `src/mtg_bot/search/resolution_channel.py`
    (`ResolutionSurveilDecision`, the `ResolutionChannelAgent` pause
    / rollback / replay harness).
  - **Round-28 extension — `MayDoChoice` variant.** Decision-callback
    substrate now carries a second variant:
    `PendingDecision::MayDoChoice { source_obj_id, controller,
    inner_effect: Box<Effect> }`, pushed by `Effect::MayDo {
    inner_effect, prompt }` — Python's "you may [inner]" wrapper from
    `effects/generic/may_do.py`. Resolve short-circuits exactly as
    Surveil does; `state.submit_may_do_decision(yes: bool)` consumes
    the head, recursively applying the inner effect on "yes" (with the
    same `source_obj_id` so identity-coupled "if you do" riders retain
    the resolving spell's identity) and dropping it on "no". The auto-
    resolve strategy set grew to include `"may_do_yes"` / `"may_do_no"`
    / `"default"`; `"default"` answers "yes" (mirrors Python's base-
    Agent no-seated-agent default), Surveil falls through to
    `"keep_all_on_top"`. `resolve_top_of_stack` (non-pause) auto-
    resolves with `"keep_all_on_top"` which now also routes MayDo to
    "yes" (fallthrough rule). The fingerprint serializer adds a
    MayDoChoice arm (variant-tag + source/controller + inner-effect
    Debug format) so a pending MayDo participates in canonicalization
    just like Surveil. Pinned by the round-28 MayDo block in
    `tests_rust/test_pending_decisions.py` (13 tests covering parse,
    push-pending, submit yes/no, auto-resolve strategies, dispatcher
    cross-variant rejection, fingerprint divergence, clone isolation).
  - **Round-28 extension — `PickCardFromExaminedChoice` variant.**
    Third variant on the multi-variant substrate, pushed by
    `Effect::LookTopNPutOneInHandRestToGraveyard` (Commune-with-Evil
    family, 4 EoE cards). Payload: `{ source_obj_id, controller,
    cards: Vec<GameObject> }` carrying the examined cards in popped
    order (`cards[0]` = topmost). Dispatcher
    `submit_pick_card_decision(chosen_id)` routes `chosen_id` to
    controller's hand and every other examined card to controller's
    graveyard (popped order); unknown id raises `ValueError`
    transactionally. Auto-resolve gains `"pick_top"` (picks
    `cards[0]`) plus `"default"` fallback (picks `cards[0]`) —
    mirrors Python's no-agent-seated fallback in
    `LookTopNPutOneInHandRestToGraveyard.resolve`. Fingerprint
    serializer carries the per-card object signature (cards live in
    NEITHER library nor graveyard while pending — must participate
    in fingerprint to distinguish a pending state from one where
    routing already completed). Pinned by 16 new tests in
    `tests_rust/test_pending_decisions.py` (parse + default-n +
    negative-n; pop+push; submit by id covering topmost / non-
    topmost / unknown id / empty queue; cross-variant dispatcher
    rejection; auto-resolve `pick_top` / `default`; non-pause
    `resolve_top_of_stack` auto-resolve; zero-count / library-clamp;
    fingerprint divergence; clone isolation).

### I23. UEOT-modifier framework: per-object expiring continuous effects with CR 514.3 cleanup-step expiration

- **Pinned by**:
  `tests_rust/test_ueot.py` (19 tests — full lifecycle including
  effect parsing, effective-P/T accessors, PumpSelfUntilEOT resolve,
  cleanup_step / advance_phase / end_turn_and_start_next clearing,
  CoW preservation across clones);
  `tests_rust/test_combat.py::test_ueot_pumped_attacker_damages_defender_for_effective_power`,
  `test_ueot_pumped_blocker_survives_what_would_have_been_lethal`,
  `test_ueot_pumped_creature_dies_when_ueot_clears`,
  `test_ueot_granted_keyword_via_has_keyword_reader`;
  `tests_rust/test_cleanup.py::test_cleanup_step_no_op_at_initial_state`,
  `test_cleanup_step_returns_summary`,
  `test_clone_then_cleanup_does_not_affect_original`,
  `test_cleanup_is_idempotent_when_already_clean`,
  `test_cleanup_alone_does_not_move_objects_between_zones`
  (each pin the new `ueot_cleared` summary-dict key).
- **Invariant** (CR 613 + CR 514.3 / round-27 G7 closure):
  - `GameObject` carries a `ueot_modifiers: Vec<UeotModifier>` Vec.
    `UeotModifier` is a closed enum with three variants today:
    `PowerToughnessBonus { power, toughness }` (CR 613.7c, pump
    effects), `GrantKeyword { keyword }` (CR 613.6, haste / flying
    / lifelink etc.), and `BecomesLandCreature { power, toughness,
    color_or_subtype }` (CR 613.4 + 7b, manland-animate). Adding a
    new variant is a build-time error in every effective-P/T /
    keyword reader until handled (exhaustiveness via the
    `UeotModifier::… {} => {}` arms in `ueot_power_bonus()` /
    `ueot_toughness_bonus()` / `ueot_has_keyword()`).
  - Adding the Vec costs the struct its `Copy` derive. The empty
    case is a 24-byte null-ptr / zero len/cap (no heap allocation),
    so the per-object footprint grows but stays cheap on the warm
    path. One downstream call site (`state_ops_library.rs`'s
    `find_obj` closure that previously used `*ref` deref) now uses
    `.clone()`.
  - Effective-P/T readers fold UEOT bonuses on top of printed +
    counter contributions: combat's `battlefield_creature_power` /
    `_toughness`, SBA's `collect_sba_victims` /
    `is_lethal`. The public Python-facing getters are
    `effective_power(obj_id)`, `effective_toughness(obj_id)`,
    `has_keyword(obj_id, keyword)` (all on `GameState`,
    Python-callable, mirror Python's `mtg_bot.game.effective_*`).
  - **Intentional asymmetry**: `battlefield_creature_toughness`
    (combat-side) folds UEOT bonus but NOT `obj.counters`; SBA's
    effective_toughness folds BOTH. This mirrors the pre-r27
    asymmetry (combat math sized off printed P/T, SBA's lethal-
    damage / zero-toughness keyed off printed + counters). Future
    slice can promote combat to fold counters once a parity test
    demands it.
  - **CR 514.3 firing point**:
    `cleanup_step_for_active_player` runs CR 514.1 (hand-size
    discard) → CR 514.2 (damage clear) → CR 514.3 (UEOT clear),
    in that order. Its summary dict gains a new `ueot_cleared` key.
    `advance_phase` composes the same UEOT clear via its inline
    mirror `cleanup_step_for_active_player_inline` on entry to
    PHASE_CLEANUP. A new `clear_ueot_modifiers_all` primitive on
    GameState is callable independently for tests that want to
    assert the clear in isolation. Closes parity gap G7 (entry
    removed from "Confirmed gaps" above).
  - **PumpSelfUntilEOT** (12-card EoE pool target) is the proving
    Effect. Parse arm: `pump_self_until_eot` with
    `power_bonus: int = 0`, `toughness_bonus: int = 0` defaults
    (mirrors Python's dataclass shape). Apply arm walks both
    battlefields to find the source by id, pushes a
    `PowerToughnessBonus` modifier onto the source's
    `ueot_modifiers` Vec, no-op if source is not on battlefield.
    Negative bonuses allowed (debuff edge case); 0/0 is a legal
    warm-path no-op (skipped before the Vec push).
  - **UEOT modifiers are NOT serialized into the parity
    fingerprint.** A mid-turn snapshot vs an end-of-turn snapshot
    would naturally differ in raw modifier Vecs but be parity-
    equal at gameplay boundaries (cleanup auto-drains). The 12
    pinned fingerprint baselines below are unchanged — `object_signature`
    in `state_ops_fingerprint.rs` continues to project only
    `(name, tapped, summoning_sick, damage, counters, attached_to,
    controller, id)`. Effective P/T (with bonus) still surfaces
    through the `effective_power` / `effective_toughness` getters
    — that's the gameplay-load-bearing observable, not the raw
    modifier list. A future slice that needs end-of-turn vs mid-
    turn parity at fingerprint level can fold UEOT in and shift
    every baseline; doing so today would bind the smoke harness to
    a Python-side serializer shape that hasn't been pinned.

---

## Pinned fingerprint baselines

Twelve-character lowercase-hex SHA1 digests pinned by the test suite.
Each baseline corresponds to a specific state shape. If any drifts
on the Rust side, either `scripts/parity_smoke.py:hash_state` or the
Rust fingerprint serializer has changed and the matching offline
Python recipe must be updated in lockstep.

### Synthetic states (`engine.make_synthetic_state(...)`)

| Fingerprint    | State shape                                          | Test                                                                 |
| ---            | ---                                                  | ---                                                                  |
| `93ab1bd03f94` | default args: 10 bf / 7 hand / 50 library            | `test_fingerprint.py::test_fingerprint_matches_python_hash_state_default` |
| `e1d70afe6742` | `(2, 3, 5)` — small state                            | `test_fingerprint.py::test_fingerprint_matches_python_hash_state_small`   |
| `3b17024676c6` | `(0, 0, 0)` — empty zones per side                   | `test_fingerprint.py::test_fingerprint_pinned_for_zero_zones`             |
| `56d2910a6ac4` | `(1, 1, 1)` — minimal non-empty                      | `test_fingerprint.py::test_fingerprint_pinned_for_one_each`               |
| `e32afdb188c1` | `(3, 3, 3)` — mid-size symmetric                     | `test_fingerprint.py::test_fingerprint_pinned_for_three_each`             |
| `6ff3d1babb85` | `(10, 10, 10)` — bigger symmetric                    | `test_fingerprint.py::test_fingerprint_pinned_for_ten_each`               |
| `5c67f92a0cb4` | `(0, 5, 0)` — only hands                             | `test_fingerprint.py::test_fingerprint_pinned_for_hand_only`              |
| `f9848ca12e57` | `(5, 0, 0)` — only battlefield                       | `test_fingerprint.py::test_fingerprint_pinned_for_battlefield_only`       |
| `f251f42f8647` | `(0, 0, 5)` — only library                           | `test_fingerprint.py::test_fingerprint_pinned_for_library_only`           |
| `6f067c3988bc` | `(5, 0, 10)` — asymmetric                            | `test_fingerprint.py::test_fingerprint_pinned_for_asymmetric`             |

### Synthetic-state mutation deltas

| Fingerprint    | State + mutation                                       | Test                                                                  |
| ---            | ---                                                    | ---                                                                   |
| `e35e82c9b588` | `(3, 3, 3)` after `tap_object(0)`                      | `test_fingerprint.py::test_fingerprint_pinned_after_tap_mutation`     |
| `d2435eea284f` | `(1, 1, 1)` after `set_life(0, 5)`                     | `test_fingerprint.py::test_fingerprint_pinned_after_life_mutation`    |

### `make_state` canonical baseline

| Fingerprint    | Setup                                                                                       | Test                                                                |
| ---            | ---                                                                                         | ---                                                                 |
| `a1193453edec` | `make_state` with the 2-card Forest+Bears registry, `[0,0,1]` / `[1,1,0]` decks, no hands   | `test_setup.py::test_make_state_canonical_default_fingerprint_pinned` |

---

## Known divergences flagged by cross-engine smoke (xfail-pinned)

Round 27 / Phase 5 — the first cross-engine smoke harness landed in
`scripts/parity_smoke.py --mode cross-engine`. It drives matched
Python and Rust states through N PassPriority decisions on a tiny
synthetic deck (Forest + Grizzly Bears) and reports per-field
divergences with gap-doc lookup. The xfail-pinned tests in
`tests/test_parity_smoke.py` (two as of r27) flag the inaugural
NOVEL divergences — when the underlying gap closes, the xfail flips
to xpass and we either renumber as G<n> below or drop it from this
section.

The inaugural cross-engine NOVEL divergences (NOT yet entered as
proper G-numbered gaps because the closure path may be cosmetic
rather than architectural — TBD by the follow-up slice):

### ~~CE1.~~ CLOSED in round 28: `summoning_sick` default aligned to Python's universal `True`

Closed by the round-28 CE1 slice. Rust's `make_state` (and
`state_ops_deck.rs::set_library_for_player`) now default
`summoning_sick = true` on every freshly-allocated library / hand
GameObject, matching Python's universal default. The field is
gameplay-irrelevant in non-battlefield zones; the cleared-on-untap
semantics still apply on the battlefield. New pymethod
`clear_summoning_sick_for_player(player_id)` exposes the untap-step
sweep so test fixtures that move creatures from hand to battlefield
via `move_object` can mark them as "ready to act" without driving
a full turn loop. Pinned fingerprint baselines shifted: the
`make_state` canonical default digest is now `411d5b757c22` (was
`a1193453edec` in r23). Pin in
`tests_rust/test_setup.py::EXPECTED_MAKE_STATE_CANONICAL_DEFAULT_FP`.
The `make_synthetic_state` test fixture in `state.rs` STAYS at
`summoning_sick=false` for battlefield creatures (test convenience —
synthetic battlefield is "creatures that have been on the
battlefield long enough"). The `register_and_inject_object` test-
injection primitive in `state_ops_resolve.rs` also stays at
`summoning_sick=false` for the same reason. Both are Rust-only test
divergences from Python's default; not load-bearing on the cross-
engine smoke harness which uses `make_state` exclusively.

### CE2. `pass_priority` apply_action behavior differs

- **Pinned by**:
  `tests/test_parity_smoke.py::test_cross_engine_mode_priority_player_unchanged_by_pass_priority`
  (xfail-pinned). This is the cross-engine manifestation of the
  already-documented gap G3 (`pass_priority` is a pure toggle).
- **Today**: Python's `apply_action(PassPriority)` is a no-op —
  priority management is owned by `simulate.priority_loop`, not by
  `apply_action`. Rust's `apply_action({"kind": "pass_priority"})`
  flips `priority_player` to `1 - priority_player`. The cross-
  engine smoke surfaces this as a `priority_player` divergence on
  every odd-numbered PassPriority step.
- **Expected**: same as G3 — the closure is the priority +
  steps + stack composition slice that integrates the round-9
  primitives.
- **Impact**: this is THE most-likely-to-be-hit cross-engine
  divergence; every PassPriority decision the smoke takes will
  flag it. Effectively gates the cross-engine harness's ability
  to exercise multi-step decision scripts with a clean priority
  field. Workaround: the smoke harness drives both engines
  through `apply_action` directly and reports the divergence
  rather than papering over it — honest failure count is the real
  progress signal.
- **Closeable**: yes — bundled with the G3/G4/G15 priority
  composition slice.

(Other smoke-flagged divergences may be added by follow-up Phase 5
slices as the deck pool / decision script grows.)

---

## Maintenance

When a slice closes one of the gaps above, drop the entry from the
"Confirmed gaps" table (or move it to invariants if the closing slice
made it parity-equal). When a slice adds a new pinned divergence,
add an entry following the same shape — short name, pinning test,
Rust today, expected, impact, closeable. The 1000-game smoke harness
parses this doc by section header (`### G<n>` and `### I<n>` are the
stable anchors), so keep the numbering monotonic.

The `### CE<n>` anchors above are the cross-engine-smoke-flagged
entries (round 27 onwards). They follow the same shape as G/I entries
but use a separate prefix to make it obvious which divergences were
detected by the cross-engine harness vs the slice-internal Rust tests.
A future slice that closes a CE<n> entry either upgrades it to a
proper G<n> (with a deeper investigation than the smoke could
provide) or drops it entirely if the closure makes it a parity
invariant.
