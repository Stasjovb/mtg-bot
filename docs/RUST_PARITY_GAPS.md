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

### ~~G12.~~ CLOSED: Mutual-KO end-state is parity-load-bearing and matches cross-engine via `apply_sbas_until_quiescent`; the construction-shape divergence is moot

Closed by `feature/g12-audit` (2026-05-12). The G12 audit
(`docs/G12_AUDIT_2026_05_12.md` writeup folded inline here)
established that the underlying substrate gap that motivated the
original entry — "no single Effect that drops both players to 0
atomically on either engine" — is structurally still present, BUT
the observable end-state IS the parity-load-bearing contract, and
that end-state matches bit-for-bit on both engines today.

**What changed since G12 was filed**: nothing on the substrate side
(neither engine ever grew a symmetric two-player `lose_life`
Effect — `LoseLife` hits controller only, `EachOpponentLosesLife`
hits the one opponent, `TargetOpponentLosesLife` hits one chosen
opponent; combat damage is one-directional). What DID change is
the read-side: CE12's sticky-winner closure (invariant I34) made
`winner_id` / `is_over` / `is_draw` SBA-gated on both engines. The
simultaneous-bilateral-kill branch of I34 (both `has_lost` flip in
the SAME SBA pass -> sticky-write skipped -> `winner_id` stays
None, `is_draw` flips True) and the sequential branch (alive=1
SBA pass writes sticky, then alive=0 SBA pass flips `is_draw`,
leaving `winner_id` at the survivor) are BOTH pinned by I34 and
exercised by the 260-step `retaliation_selector` cross-engine
walk that closed CE12.

**Closure-load-bearing fact**: the original G12 entry framed its
"construction shape diverges" worry as a deferred substrate gap,
but mutual-KO outcomes in REAL MTG aren't observably constructed
"in a single atomic step" either — the SBA pass IS the
simultaneous-loss observation point per CR 704.5a (the "check all
state-based actions simultaneously" rule). Both engines hit that
SBA pass in lockstep when fed two `lose_life` calls before
`apply_sbas_until_quiescent`, so the engines' construction shape
matches CR's observation shape AND each other.

**Pinning tests** (`tests_rust/test_winloss.py`):
- `test_mutual_zero_via_sequential_lose_life_is_draw` —
  Rust-side end-state pin (losers=[0,1], winner_id=None,
  is_draw=True after two `lose_life` + `apply_sbas`).
- `test_mutual_zero_cross_engine_end_state_matches_python` —
  cross-engine pin: both engines produce identical losers /
  winner_id / is_draw / is_over after two `lose_life(p, 20)` +
  `apply_sbas_until_quiescent` (simultaneous variant — both
  `has_lost` flip in one SBA pass).
- `test_mutual_zero_cross_engine_sequential_variant_matches_python`
  — cross-engine pin for the sequential variant: alive=1 SBA pass
  first (sticky writes winner_id=1), then alive=0 SBA pass
  (sticky preserved, is_draw flips). End-state on both engines:
  losers=[0,1], winner_id=1, is_draw=True.

The cross-engine `retaliation_selector` walk
(`tests/test_parity_smoke.py::test_cross_engine_retaliation_selector_walks_clean`,
260 decisions, bilateral combat) already exercised the SBA-gated
outcome layer across an end-of-game transition; this G12 closure
adds the synthetic-state focused pin so the contract has a
direct two-line repro in addition to the integration walk.

See invariant I44 below for the closure invariant.

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

### ~~G19.~~ CLOSED: `SearchLibraryForBasicLandTapped` shuffles the library after the search per CR 701.19 / 701.22

Closed by `feature/g19-search-shuffle`. The `Effect::SearchLibraryForBasicLandTapped`
resolve arm in `rust/src/state_ops_resolve.rs` now Fisher-Yates
shuffles the active player's library after all `count` picks have
landed (or after the early-`break` on no-more-basic-lands).
Honors CR 701.19 / 701.22's "always shuffle after search" invariant
regardless of search outcome.

**Shuffle source — xorshift64 fallback only (Effect-rng threading
deferred).** CE8 (Slice 1 + Slice 2) wired all 8 pymethod-surface
gameplay shuffle sites to consume an optional `rng: &Bound<PyAny>`
kwarg, falling through to xorshift64 when `None`.
`Effect::SearchLibraryForBasicLandTapped` resolves inside the
private `apply_effect` function, which does NOT yet thread an
external `rng` through (no `rng` param on `apply_effect`,
`resolve_top_of_stack`, `resolve_top_of_stack_pause`, or any of
the dozens of intervening call sites). G19 closes the
"no shuffle at all" gap via the legacy xorshift64 path; the seed
is derived deterministically from
`(turn_number, active_player, source_obj_id, library_len)` so the
same starting state produces the same post-search library
permutation across reruns.

**Cross-engine MT parity for THIS Effect is deferred** to an
Effect-rng-threading slice (separate from G19). Pinned in
`SEARCH_LIMITATIONS.md` — see the new follow-up entry there.
Implementing this slice requires plumbing an
`Option<&Bound<'_, PyAny>>` rng parameter through `apply_effect`,
`apply_effect_pub`, `resolve_top_of_stack`,
`resolve_top_of_stack_pause`, `auto_resolve_pending_decisions`
(round-28), and every test surface that calls those — large
surface, not justified by G19 alone, but worthwhile when more
search-then-shuffle Effects join the parity smoke under shared rng.

**Effect-rng-threading closure** (`feature/effect-rng-threading`).
The cross-engine MT parity deferral above is now closed via Option
A from `docs/RUST_EFFECT_RNG_AUDIT.md` §4: rather than threading an
rng parameter through every intervening call site, the rng is
stashed on `GameState.rng: Option<Py<PyAny>>` (caller-set via the
new `set_external_rng(rng)` pymethod). The Effect arm reads
`state.rng_ref()` before its Fisher-Yates loop; when `Some(_)`, it
consumes draws via `external_rng::next_below` (byte-identical to
`random.Random.shuffle`); when `None`, it falls back to xorshift64
(byte-equivalent to pre-closure behavior). Cross-engine smoke now
sees byte-identical post-search library order under a shared
`random.Random`. See invariant I43 below for the field lifecycle
(caller-owned, not serialized into fingerprint, clone-preserved via
manual `Clone` impl). See the closure notice in
`SEARCH_LIMITATIONS.md` entry 16.

**Pinning tests** (`tests_rust/test_resolve.py`):
- `test_resolve_search_library_for_basic_land_tapped_shuffles_library` —
  asserts the post-resolve library is NOT the sequential
  identity permutation that the no-shuffle path would have
  produced.
- `test_resolve_search_library_for_basic_land_tapped_shuffle_is_deterministic` —
  asserts two clone-equal starting states produce the same
  post-search library permutation (seed derivation is pure-state).

The existing 7 round-23 tests under the
`test_resolve_search_library_for_basic_land_tapped_*` prefix
continue to pass; their assertions (top-of-library → battlefield,
second-from-top still in library, etc.) survive the shuffle
because the synthetic seed library is 100% Forest (identical
printings, distinct ids — shuffle reorders ids but doesn't add
or remove cards from the library set).

See invariant I42 below for the post-search shuffle contract.

### ~~G24.~~ CLOSED: `keep_hand(player_id)` fires a Paris scry-on-keep when `mulligan_count > 0`

- **Pinned by** (round-30 G24 closure):
  - **`keep_hand` no-op when mulligan_count == 0**:
    `tests_rust/test_mulligan.py::test_keep_hand_no_op_when_mulligan_count_is_zero`.
  - **`keep_hand` fires scry when mulligan_count > 0**:
    `tests_rust/test_mulligan.py::test_keep_hand_fires_scry_when_mulligan_count_positive`.
  - **`keep_hand` unknown player rejection**:
    `tests_rust/test_mulligan.py::test_keep_hand_unknown_player_raises`.
  - **`submit_scry_decision` routing**:
    `tests_rust/test_mulligan.py::test_submit_scry_decision_keep_on_top_returns_card_to_library_top`,
    `test_submit_scry_decision_send_to_bottom_routes_to_library_bottom`,
    `test_submit_scry_decision_empty_queue_raises`,
    `test_submit_scry_decision_wrong_head_discriminant_raises`,
    `test_submit_scry_decision_keep_top_fingerprint_matches_pre_keep`.
  - **Auto-resolve strategies**:
    `tests_rust/test_mulligan.py::test_auto_resolve_scry_keep_top_routes_to_library_top`,
    `test_auto_resolve_scry_send_bottom_routes_to_library_bottom`,
    `test_auto_resolve_default_for_scry_keeps_on_top`.
  - **Fingerprint + cross-player + clone isolation**:
    `tests_rust/test_mulligan.py::test_keep_hand_changes_fingerprint_while_pending`,
    `test_keep_hand_does_not_affect_other_player`,
    `test_keep_hand_clone_isolation`,
    `test_keep_hand_preserves_library_card_set`,
    `test_keep_hand_for_player_one`.
  - **Pending-decisions dict round-trip + empty-library guard**:
    `tests_rust/test_mulligan.py::test_pending_decisions_dict_round_trip_for_scry_choice`,
    `test_keep_hand_after_multiple_mulligans_still_one_scry`,
    `test_keep_hand_with_empty_library_pushes_empty_scry_choice`.
- **Invariant** (CR 103.4 Paris mulligan / round-30 G24 closure):
  - `GameState.keep_hand(player_id)` is the harness-driven "I'm done
    mulliganing" entrypoint. When the player's `mulligan_count > 0`
    it pops the top of their library and pushes a
    `PendingDecision::ScryChoice { source_obj_id: 0, controller,
    cards: vec![top_card] }`. When `mulligan_count == 0` (the
    player kept their initial 7 without mulliganing), `keep_hand`
    is a strict no-op — no pending decision pushed, no zone
    mutation, byte-identical fingerprint. Mirrors CR 103.4's
    "after each mulligan" gate.
  - The new `PendingDecision::ScryChoice` variant mirrors
    `SurveilChoice`'s shape (source_obj_id + controller + Vec of
    examined GameObjects) but the submit dispatcher routes very
    differently: `submit_scry_decision(keep_on_top: bool)` pushes
    the examined card to library top (`lib.insert(0, obj)`) on
    `keep_on_top=true`, or to library bottom (`lib.push(obj)`) on
    `keep_on_top=false`. A separate variant keeps the dispatcher
    surface honest — Surveil routes to library/graveyard; Scry
    routes to library-top/library-bottom.
  - `auto_resolve_pending_decisions` gains three new strategies:
    `"scry_keep_top"` (route to library top — matches Python's
    conservative no-agent-seated default), `"scry_send_bottom"`
    (route to library bottom), and `"default"` (which for
    `ScryChoice` is equivalent to `"scry_keep_top"`).
  - Empty-library guard: if the library is empty at `keep_hand`
    time, the variant is pushed with `cards: vec![]`. Submit /
    auto-resolve treat the empty case as a head-drain no-op.
  - **Backward compatibility**: existing tests / call sites that
    never call `keep_hand` continue to work unchanged. The scry
    is OPT-IN at the harness layer — calling code that doesn't
    want the scry simply doesn't call `keep_hand`.
  - The pending-decisions fingerprint slot serializes `ScryChoice`
    with the variant-tag + source/controller + per-examined-card
    object signature (same shape as `SurveilChoice` /
    `PickCardFromExaminedChoice`). Empty queues stay
    bit-equivalent to pre-r27 baselines.

The Paris-rule scry-on-keep is now end-to-end functional: harness
drives N `mulligan_atomic` calls then `keep_hand`, the engine
pauses on a `ScryChoice` if mulligan_count > 0, and the harness
either calls `submit_scry_decision(keep_on_top: bool)` or
`auto_resolve_pending_decisions(strategy)` to drain. See invariant
I24 below for the integration with the atomic-mulligan lifecycle.

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

### I17. Summoning-sick **creatures** with tap-cost activated abilities are excluded from both dispatch and emission

- **Pinned by**: `tests_rust/test_tap.py::test_activate_ability_on_summoning_sick_creature_with_tap_cost_is_rejected`
  (creature rejected),
  `tests_rust/test_tap.py::test_activate_ability_on_summoning_sick_land_with_tap_cost_is_allowed`
  (land allowed — creature-only gating);
  `tests_rust/test_legal.py::test_legal_decisions_activate_ability_excludes_summoning_sick_creature`
  (creature not emitted),
  `tests_rust/test_legal.py::test_legal_decisions_activate_ability_emits_for_summoning_sick_land`
  (land emitted).
- **Invariant**: CR 302.1 — a **creature** with `summoning_sick == true`
  whose activated ability has a tap cost (e.g. `{T}`) cannot pay
  that cost. **Lands (and other non-creature permanents) are
  exempt** — they can tap for mana the turn they enter the
  battlefield even though every freshly-allocated permanent carries
  `summoning_sick = true` (the CE1 universal-true default). The
  Rust port enforces the gate on BOTH sides:
  `apply_action`'s `ActivateAbility` arm in `state_ops_actions.rs`
  raises `ValueError` (no mutation) and the `legal_decisions`
  emitter in `state_ops_legal.rs` skips emission — but ONLY when
  the source is a creature (`printing.card_types.contains("Creature")`).
  The general gate is
  `is_creature && summoning_sick && requires_tap_cost`; the
  first-slice mana-only filter (the only wired ActivateAbility
  dispatch case today, where every printing's mana ability has an
  implicit `{T}`) gates on `is_creature && summoning_sick`.
  Mirrors Python's `legal.py:661-663`
  (`is_creature_now(obj) && obj.summoning_sick`) and
  `actions.py:_activate_ability` precheck. Closes parity gap G6
  (entry removed from "Confirmed gaps" above); the cast-bears
  probe's sick-land filter in `cross_engine.py::cast_bears_selector`
  is now defensive-only and removable in a future cleanup.

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

### I19. Empty-library draw flags the player; `apply_sbas` locks the loss into the sticky `has_lost`; surface accessors (`is_over` / `winner_id` / `is_draw`) are SBA-gated

- **Pinned by**:
  `tests_rust/test_library.py::test_drawcards_from_empty_library_marks_player_for_loss_on_next_sba`,
  `test_drawcards_count_larger_than_library_drains_then_loses_on_sba`,
  `tests_rust/test_zones.py::test_draw_card_from_empty_library_returns_none`
  (no-crash + cause-signal side-effect),
  `tests_rust/test_winloss.py::test_explicit_lose_game_marks_player`,
  `test_each_opponent_loses_life_lethal_then_sba_locks_the_loss`,
  `test_winner_id_pre_sba_stale_matches_python_semantics`,
  `test_is_over_winner_id_eager_for_empty_library_draw_via_pure_derivation`.
- **Invariant** (CR 704.5b / CR 104.2 — round-26 G10 + G11 closure,
  refined by CE10 CE-pure-derivation-is_over): two parallel API
  layers on the winloss surface.
  - The `draw_card` primitive, the `Effect::DrawCards` resolution
    arm, AND `advance_phase`'s auto-draw step (the
    `draw_card_inline` mirror used on entry to PHASE_DRAW — see
    `feature/draw-card-inline-flag`) all flip
    `Player.attempted_draw_on_empty = true` when the library pop
    returns `None`. All three entrypoints share the loss-flag
    side-effect so a player who decks out via ANY draw path
    (cast spell that resolves DrawCards, side-channel pymethod
    call, or auto-draw at start of their turn) gets flagged.
  - **Layer 1 — eager / cause-flags-driven** (the Rust-native
    API, unchanged from G10): `losers()` returns a player if
    **any** of the OR'd-three signals are true: `has_lost`,
    `attempted_draw_on_empty`, or `life <= 0`. Read directly (no
    SBA pass required) so the loss is observable eagerly. `winner()`
    and `is_game_over()` use the same OR'd-three predicate. This
    layer mirrors Python's eager `p.has_lost = True` in
    `turn.draw_card` — both engines can observe the cause-flag
    side-effect immediately.
  - **Layer 2 — SBA-gated / Python-named API** (the surface
    accessors, refined by CE10): `is_over()`, `state.winner_id`
    (getter), `state.is_draw` (getter) read ONLY from the sticky
    `Player.has_lost` flag. They match Python's identically-named
    fields exactly: Python's `winner_id` and `is_draw` are written
    only by `apply_state_based_actions` (`turn.py` lines 1384-1392),
    and `is_over` reads them. Pre-CE10, Rust's surface used the
    same eager OR'd-three predicate as Layer 1; that surfaced as a
    cross-engine smoke divergence on empty-library draws (the
    smoke harness doesn't fire SBAs between steps). Post-CE10,
    Layer 2 is SBA-gated, so both engines stay stale on the
    surface until `apply_sbas` commits the loss.
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
    Layer 2 stays stale through this revive sequence (no SBA fired
    — `has_lost` not set).
  - The explicit `lose_game(p)` primitive (Phage / Bargain) sets
    `has_lost` directly without going through SBA — useful for
    "you lose the game" cards where life is not the trigger.
    Because it writes `has_lost` directly, it flips BOTH layers
    in one call (the only path that does so without an SBA pass).

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
  - **Round-30 G24 closure — Paris scry-on-keep integration.** After
    the final `mulligan_atomic` call (or after deciding to keep the
    initial 7 without mulliganing), the harness calls
    `GameState.keep_hand(player_id)` to signal "I'm done
    mulliganing." When the player's `mulligan_count > 0`, this
    pops the top card of their library and pushes a
    `PendingDecision::ScryChoice` (see G24 above), modeling CR 103.4
    Paris scry-on-keep. When `mulligan_count == 0`, `keep_hand` is
    a strict no-op. The scry is OPT-IN at the harness layer:
    callers that don't model the post-mulligan scry simply don't
    call `keep_hand`. Cross-reference: see the new
    `PendingDecision::ScryChoice` variant + the
    `submit_scry_decision` / auto-resolve `"scry_keep_top"` /
    `"scry_send_bottom"` dispatchers documented under the (closed)
    G24 entry above.

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
    CastSpell / ActivateAbility). PassPriority itself is a TRUE
    NO-OP (CE2 closure): the arm leaves `priority_player`,
    `active_player`, AND `consecutive_passes` untouched. Mirrors
    Python's `apply_action(PassPriority)` which is literally
    `return` (src/mtg_bot/actions.py:990-991). Priority management
    flows through the `pass_priority` primitive directly (which
    DOES increment the counter and toggle the priority field) or
    through the composer `complete_step_via_priority_round`
    (which calls the primitive twice). The post-arm reset block
    at the bottom of `apply_action` is skipped via the
    `is_pass_priority` short-circuit so the no-op contract is
    bit-exact.
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
  - **Round-28 extension — `ChooseModeChoice` variant (4th).** Fourth
    variant on the multi-variant substrate, pushed by
    `Effect::ChooseOneMode { modes: Vec<Effect> }` — Python's
    `ModalChooseOne(modes=...)` (combinators.py:1112, 13 EoE cards)
    in its first-slice shape: resolve-time mode picking only (cast-
    time mode routing via `state.resolving_modes`, `or_both`, and
    per-mode target picking deferred). Payload: `{ source_obj_id,
    controller, modes: Vec<Effect> }`. Dispatcher
    `submit_choose_mode_decision(chosen_idx)` validates index range
    transactionally then recursively applies `modes[chosen_idx]` via
    `apply_effect` with the original `source_obj_id`. Auto-resolve
    gains `"choose_mode_0"` (picks `modes[0]`); `"default"` fallback
    also picks `modes[0]` — mirrors Python's no-agent-seated
    fallback in `ModalChooseOne.resolve`. Empty `modes` list is
    rejected at register time so the resolve arm always has at least
    one mode. Fingerprint serializer carries each mode's Debug
    format (same Debug-over-Serialize choice as MayDoChoice). Pinned
    by 14 new tests in `tests_rust/test_pending_decisions.py`:
    parse + missing-modes + empty-modes rejection; resolve-pushes-
    pending; submit mode-0 (draw) + mode-1 (gain-life) + out-of-
    range + empty-queue + cross-variant; auto-resolve
    `choose_mode_0` / `default`; non-pause `resolve_top_of_stack`
    auto-resolve; fingerprint divergence; clone isolation.
  - **Round-28 extension — `IfYouDoChoice` variant (5th).** Fifth
    variant on the multi-variant substrate, pushed by
    `Effect::IfYouDo { do_action, then_action }` — Python's
    `IfYouDo` (combinators.py:560, 7+ EoE cards) in its first-slice
    "looter" shape: do_action assumed implicitly success-on-yes
    (i.e. `IfYouDo(MayDo(X), Y)` form). Payload: `{ source_obj_id,
    controller, do_action: Box<Effect>, then_action: Box<Effect> }`.
    Dispatcher `submit_if_you_do_decision(yes)` applies both nested
    actions in order on "yes", drops both on "no" — with the same
    `source_obj_id` propagated so identity-coupled riders retain
    identity. Auto-resolve gains `"if_you_do_yes"` / `"if_you_do_no"`;
    `"default"` answers "yes" (mirrors Python's no-agent-seated
    `IfYouDo.resolve` — base-Agent says yes to the wrapped MayDo,
    so both fire). The `if_you_do_no` strategy also routes a
    MayDoChoice head to "no" (shared yes/no semantics — keeps a
    multi-variant queue draining predictably). General IfYouDo with
    do_actions that can signal failure (e.g. SacrificeACreature
    returning False on empty bf) is deferred — would require
    `apply_effect` to return `Result<bool>`. Pinned by 14 new tests
    in `tests_rust/test_pending_decisions.py`: parse + missing-
    fields rejection (both directions); resolve-pushes-pending;
    submit yes/no; empty-queue + cross-variant dispatcher rejection;
    auto-resolve `if_you_do_yes` / `if_you_do_no` / `default`; non-
    pause `resolve_top_of_stack` auto-resolve; fingerprint
    divergence; clone isolation.

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

### ~~CE2.~~ CLOSED: `apply_action(PassPriority)` is now a no-op matching Python

Closed by the round-28 CE2 slice (`feature/ce2-pass-priority`).
Rust's `apply_action({"kind": "pass_priority"})` is now a TRUE
NO-OP — it does NOT flip `priority_player` and it does NOT
increment `consecutive_passes`. This mirrors Python's
`apply_action(PassPriority)` which is literally `return`
(src/mtg_bot/actions.py:990-991). Priority management is owned by
the composer (`complete_step_via_priority_round`) and by callers
driving the `pass_priority` primitive directly — NOT by
`apply_action`. The xfail-pinned cross-engine smoke test
(`tests/test_parity_smoke.py::test_cross_engine_mode_priority_player_unchanged_by_pass_priority`)
flipped to expected-pass with the closure. New regression tests in
`tests_rust/test_priority.py` (5 tests in the "CE2 closure
regression" block) pin the no-op behavior in both directions
(p0 passes, p1 passes), pin the counter-unchanged contract, pin the
active-player-unchanged contract, and pin fingerprint stability.
Pre-existing rust-side tests that asserted the OLD toggle behavior
were flipped to assert the new no-op semantics (in
`tests_rust/test_actions.py` and `tests_rust/test_legal.py`). The
I25 invariant text below was tightened to reflect that
PassPriority via apply_action is now bit-equivalent to Python's
return-fast path.

### ~~CE3.~~ CLOSED: Library orientation aligned to Python's `index 0 = top` convention

Closed by the CE3 closure slice (`feature/ce3-library-pop`). Rust now
treats `lib[0]` as the top of the library (matching Python's
`library.pop(0)` convention) across every library mutator that
touches orientation:

- `state_ops_zones.rs::draw_card` — `lib.pop()` → `lib.remove(0)`.
- `state_ops_steps.rs::draw_card_inline` (the turn-loop draw step
  inline mirror) — same flip.
- `state_ops_mulligan.rs`: `mulligan` / `mulligan_to_n` /
  `mulligan_atomic` all redraw via `lib.remove(0)`;
  `bottom_cards_from_hand` + `mulligan_atomic`'s bottom-step now
  append to the tail (post-CE3 bottom = `lib[len-1]`).
- `state_ops_library.rs`: `scry` reads `lib[..n]` forward;
  `search_library_for_first_of_type` (and the move/shuffle variants)
  iterate forward; `mill_target_player` removes from head; `apply_scry`
  rebuilds with top_ids at the head and bottom_ids at the tail.
- `state_ops_resolve.rs`: `Effect::DrawCards`, `Effect::Mill`,
  `Effect::MillTargetPlayer`, `Effect::Surveil`,
  `Effect::LookTopNPutOneInHandRestToGraveyard`,
  `Effect::ManifestDread`, `Effect::ManifestDreadThenAttachSelf`,
  `Effect::LookAtTopNRevealOrCounter`,
  `Effect::EachOpponentMillsCards`,
  `Effect::SearchLibraryForBasicLandTapped`, and the broader
  `Effect::SearchLibraryForCard` family all walk top-first by
  forward iteration; `Effect::PutCardFromGraveyardOnBottomOfLibrary`
  and `Effect::OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary`
  push to the tail (bottom).
- `state_ops_decisions.rs`: `resolve_surveil_with_strategy`
  (`keep_all_on_top`) restores cards via `lib.insert(0, ...)` in
  reverse; the look-at-top-N reveal-yes / reveal-no submit paths
  push to the tail in reverse order so cards[0] (the topmost
  popped) lands at the very bottom (parity with the pre-CE3
  contract).
- `state_ops_choices.rs::choose_top_of_library_for_player` reads
  `library.first()` instead of `library.last()`.
- `state_ops_resolve.rs::register_and_inject_object` — the test-
  injection primitive now inserts injected library cards at `lib[0]`
  (top) so existing test fixtures that expect injected cards to be
  reachable by top-N readers continue to work without per-test
  changes.

The xfail-pinned cross-engine smoke test
`tests/test_parity_smoke.py::test_cross_engine_play_a_land_selector_walks_clean`
flipped to expected-pass; the companion symptom-pin
`test_cross_engine_play_a_land_selector_reports_ce3_symptom_at_step_0`
was removed alongside the xfail per the closure pair contract. The
existing Rust tests that pinned the pre-CE3 "top = lib.last()"
convention (test_zones / test_library / test_deck / test_choices /
test_mulligan / test_pending_decisions / test_resolve) were
updated to assert the post-CE3 "top = lib[0]" convention. Pinned
fingerprint baselines stayed bit-identical — the orientation flip
changed which end is *named* top but did NOT change the underlying
Vec construction order (`make_state` and `make_synthetic_state`
push input order into the Vec; the fingerprint walks that Vec
front-to-back unchanged).

### ~~CE4.~~ CLOSED: `battlefield_snapshot` emits in `etb_timestamp` order (matching Python's centralized append order)

Closed by the CE4 closure slice (`feature/ce4-bf-etb-order`). Option
(2) from the brief — the minimal-surface "stamp + sort" closure — was
taken. The per-player `battlefield: Arc<Vec<GameObject>>` split stays
intact; the snapshot and fingerprint readers stable-sort their
collected refs by a new per-object `etb_timestamp: u32` slot before
emitting.

- **Per-object slot**: `GameObject.etb_timestamp: u32` (defaults to
  `0`). Stamped at every battlefield-entry primitive by reading
  `state.next_etb_timestamp` and bumping the counter
  (`state::reserve_etb_timestamp(&mut state)`). Stamped sites:
  * `state_ops_cast.rs::move_from_hand_to_battlefield` (the
    `play_land` + `cast_creature` shared helper — refactored to take
    `&mut GameState` so it can bump the counter; both call sites
    updated).
  * `state_ops_zones.rs::move_object` (the generic mover —
    conditionally stamps when `target_zone == ZONE_BATTLEFIELD`).
  * `state_ops_zones.rs::move_object_from_graveyard_to_battlefield`
    (the reanimation primitive).
  * `state_ops_resolve.rs::move_source_post_resolve` (the canonical
    CR 608.2m permanent-mover — covers ResolveCreature /
    ResolveArtifact / ResolveEnchantment / ResolvePlaneswalker / any
    permanent-typed source landing post-resolve).
  * `state_ops_resolve.rs::Effect::CreateToken` (multi-token batch —
    reserves a contiguous block of timestamps so the within-effect
    creation order is strictly monotonic; bumps the counter once per
    token).
  * `state_ops_resolve.rs::Effect::CreateTokenCopyOfTargetCreatureYouControl`.
  * `state_ops_resolve.rs::Effect::SearchLibraryForBasicLandTapped`
    (loops over `count`; each searched land gets a fresh timestamp).
  * `state_ops_resolve.rs::Effect::ReturnCreatureFromYourGraveyardToBattlefield`.
  * `state_ops_resolve.rs::ReturnAllCreaturesFromYourGraveyardToBattlefield`
    (multi-bf-push; contiguous timestamp block, one per moved creature).
  * `state_ops_resolve.rs::register_and_inject_object` (test-injection
    primitive; stamps only when `target_zone == ZONE_BATTLEFIELD`).
  * `state_ops_resolve.rs::return_paired_exiles_for` (the round-28
    "until source leaves" manual hook; multi-bf-push, contiguous
    timestamp block).
  * `state_ops_decisions.rs::resolve_manifest_dread_to_battlefield`
    (manifest-dread chosen card → bf).

- **Bookkeeping counter**: `GameState.next_etb_timestamp: u32`
  (defaults to `0`). NOT serialized into the fingerprint — same
  precedent as `mulligan_count` and `consecutive_passes`: transient
  bookkeeping, not gameplay-relevant. Two states reached via
  different histories that share the same observable battlefield
  ORDER share a fingerprint regardless of how many bf-entries
  happened to get there.

- **Per-object slot is also NOT in the fingerprint's 8-tuple.** The
  field is read only as the **stable-sort key** in
  `state_ops_snapshot.rs::battlefield_snapshot` and the matching
  battlefield walk in `state_ops_fingerprint.rs::fingerprint`. The
  per-object 8-tuple shape (`printing_name, tapped, summoning_sick,
  damage, counters, attached_to, controller_id, id`) is unchanged.
  Consequence: every pinned fingerprint baseline involving
  `make_synthetic_state` stays bit-equal, because synthetic-state
  battlefields are built via `make_player` (which doesn't call
  `reserve_etb_timestamp`) — every object has timestamp 0, the
  stable-sort tie-breaks on the original p0-then-p1, insertion-order
  walk, and the emitted sequence matches the pre-CE4 walk byte-for-
  byte. Real ETB-driven flows produce strictly-monotonic timestamps
  (each `reserve_etb_timestamp` call bumps the counter), so the sort
  produces the ETB-interleaved order Python emits.

The xfail-pinned cross-engine smoke test
`tests/test_parity_smoke.py::test_cross_engine_multi_turn_selector_walks_clean`
flipped to expected-pass; the companion symptom-pin
`test_cross_engine_multi_turn_selector_surfaces_ce4_battlefield_ordering`
was removed alongside the xfail per the closure-pair contract
(mirrors the CE3 closure pattern). The pre-CE4 test
`tests_rust/test_snapshot.py::test_battlefield_snapshot_p0_then_p1_ordering`
that pinned the controller-grouped emission order was renamed and
inverted to
`test_battlefield_snapshot_etb_timestamp_ordering`, asserting that
two `register_and_inject_object` calls into ZONE_BATTLEFIELD emit
in the order they were called (p1's Bears first, p0's Forest
second), not in controller-grouped order. All other pinned
fingerprint baselines stayed bit-equal — full rust gate (1693
tests) green post-flip.

The matching cross-engine smoke (50 decisions with `multi_turn_selector`
on `slightly_bigger_deckspec`, seed 42) walks clean across all 50
steps post-closure. Pre-CE4 the same harness aborted at step 28
with the `battlefield` field divergence — Python emitting
Mountain-then-Forest (ETB order), Rust emitting Forest-then-Mountain
(controller order).

### ~~CE7.~~ CLOSED: `draw_card_inline` mirror flags `attempted_draw_on_empty` matching the pymethod and `Effect::DrawCards` arms

> **Numbering note.** Filed at CE7 even though CE6 (SBA-collection,
> the playbook's predicted CE5) and CE10 (CE-pure-derivation-is_over)
> landed first. The staging doc `docs/PENDING_CE_FILINGS_2026_05_11.md`
> (merge `50eb79ea`) originally reserved CE7 for the pure-derivation-
> is_over finding, but the in-flight is_over closure (merge
> `59b6054e`) took CE10 by the time this entry was filed. Per the
> playbook's monotonic-on-surface numbering policy, this entry
> takes the next-available pre-CE10 slot (CE7); CE8 below covers
> the still-open shuffle-PRNG finding, and CE9 is intentionally
> left unallocated for the next surfacing slice to claim.

Closed by `feature/draw-card-inline-flag` (feature commit
`1673e582`, merge `63f03067`). Pre-closure, Rust had two
`draw_card` paths with diverging empty-library behavior:

- `state_ops_zones.rs::draw_card` (pymethod) flagged
  `Player.attempted_draw_on_empty = true` on empty pop.
- `state_ops_steps.rs::draw_card_inline` (the `advance_phase`
  auto-draw mirror used on entry to PHASE_DRAW per CR 504.1) was
  a silent no-op on empty libraries.
- `state_ops_resolve.rs::Effect::DrawCards` (the resolution arm)
  flagged correctly.

Result: a player who decked out via the DRAW step (the common case
in real games) was un-flagged on Rust side, even though deck-out
via cast-spell-resolves-DrawCards or side-channel pymethod call
was correctly flagged.

**Closure shape.** Option B per the closure brief — mirror the
flag-set into the inline path directly rather than delegating to
the pymethod (Option A would have required `pub(crate)` visibility
on the pymethod, outside the slice scope). The inline mirror also
picks up the pymethod's defensive `attached_to` /
`exiled_with_source` reset on the drawn object (CR 400.7 round-28
attach foundation), so the two paths now match bit-for-bit.

Pinned by
`tests_rust/test_steps.py::test_advance_phase_auto_draw_on_empty_library_flags_attempted_draw`
(line 910) — synthetic state with `num_battlefield=0, num_hand=0,
num_library=0`, seeds `turn_number=5` so the CR 103.7c first-turn-
skip gate is open, walks UNTAP → UPKEEP → DRAW, asserts
`state.losers() == [0]` eagerly + `state.is_game_over() is True` +
`state.winner_id == 1` + `apply_sbas` locks the loss into the
sticky `has_lost`. The I19 invariant bullet (see "I19. Empty-library
draw flags the player...") was extended (in the same closure slice)
to list `advance_phase`'s auto-draw step as the third entrypoint
that flips the cause-signal.

The closure SURFACED the same CE-pure-derivation-is_over divergence
ultimately filed as CE10:
`test_cross_engine_single_card_libraries_multi_turn_walks_clean`
(line 308 in `tests/test_parity_smoke_edge_cases.py`) flipped from
passing to strict-xfailed at step 39 once the (newly fixed)
auto-draw path made Rust's `attempted_draw_on_empty` flip
observable on the multi-turn path; Python's SBA-gated `is_over`
stayed False. CE10's SBA-gate of the surface accessors then closed
the cascade.

### ~~CE6.~~ CLOSED: `collect_sba_victims` walks the battlefield in ETB-timestamp order (via shared `bf_iter_etb_sorted` helper)

> **Note on numbering.** The closure playbook
> (`docs/CE5_CE6_CE7_CLOSURE_PLAYBOOK.md`) reserved CE5 for this
> SBA-collection divergence based on the audit's ranked predictions,
> but the cast_bears_selector probe surfaced a different divergence
> first (the cast-vs-resolve gap below) and claimed the CE5 number.
> Per the playbook's coordination note at the cast-creature CE5
> entry, the planned CE5/CE6/CE7 sequence bumps to CE6/CE7/CE8
> when the corresponding slices land. This entry is the bumped CE6
> (closing the playbook's predicted "CE5 — SBA victim collection")
> per `feature/ce5-sba-order` branch + commit `cdb01fcd`.

Closed by the SBA-collection closure slice (`feature/ce5-sba-order`).
The
SBA victim-collection walk in
`rust/src/state_ops_sba.rs::collect_sba_victims` was a per-player
`for player in &self.players { for obj in player.battlefield.iter() }`
loop — p0-first, p1-second, in each player's per-player battlefield
Vec order. This diverged from Python's `turn.py:1242`
`_state_based_actions_pass` which walks the centralized
`state.battlefield` list (ETB-monotone post-CE4). Whenever ETB
timestamps interleaved across players, the two engines collected
victims in different orders — observable downstream by death-trigger
push order once Rust grows a trigger emitter (gated on CE8 substrate
work).

**Closure shape.** A new shared module
`rust/src/bf_iter.rs` exposes
`pub(crate) fn bf_iter_etb_sorted(state: &GameState) -> Vec<&GameObject>`,
matching the post-CE4 stable-sort precedent already established by
`state_ops_snapshot.rs::battlefield_snapshot` and
`state_ops_fingerprint.rs::fingerprint`. The helper collects refs
across both players' battlefields, then `sort_by_key(|o| o.etb_timestamp)`
— stable, so synthetic-state ties (every bf object at timestamp 0)
preserve the pre-closure p0-then-p1 walk and pinned baselines stay
bit-equal. `collect_sba_victims` now consumes the helper:

```rust
let mut victims = Vec::new();
for obj in crate::bf_iter::bf_iter_etb_sorted(self) {
    // ... unchanged 704.5f / 704.5g predicate logic ...
}
```

Only the iteration shape changed; the predicate logic (indestructible
filter, UEOT folds, effective-toughness calculation, 704.5f-before-
704.5g CR ordering) is bit-equal pre/post.

**Tests.** Five new regression tests in
`tests_rust/test_sba.py` under the "CE5 closure: SBA victim
collection" section heading (the section comment in the test file
retained the playbook's original CE5 label since the test code was
written before the in-flight cast-creature CE5 entry landed):

- `test_collect_sba_victims_walks_etb_order_across_players` — interleaved
  ETB stamps across p0/p1, verifies end-state per-graveyard projection
  (each player's graveyard receives its dead in the relative ETB order
  they died).
- `test_collect_sba_victims_etb_order_same_player_interleave` — pins
  the no-regression case (same-player projection preserves relative
  ETB order through a cross-player stamp interleave).
- `test_collect_sba_victims_etb_order_visible_via_clone_and_count` —
  cross-player simultaneous SBA where p1's creature has a lower ETB
  stamp than p0's; both end up graveyarded.
- `test_collect_sba_victims_empty_when_no_lethal` — empty-case path
  through the helper (no victims emitted).
- `test_collect_sba_victims_synthetic_state_tie_break_preserves_p0_first`
  — pins the synthetic-state tie-break (every timestamp == 0 →
  stable sort preserves p0-then-p1 walk, pre-closure baselines
  bit-equal).

**Fingerprint baselines.** Zero shifts. Synthetic-state bf objects
all carry `etb_timestamp == 0` (because `make_player` doesn't call
`reserve_etb_timestamp`), and the stable-sort tie-break preserves
the pre-closure p0-then-p1 walk on those fixtures. Per-graveyard
contents also stay bit-equal — `apply_sbas` pushes each victim onto
its controller's graveyard, so the same-player projection of any
collection order produces the same per-graveyard sequence. The
closure becomes observable only downstream: the trigger emitter
(future CE-emitter slice) will inherit ETB-ordered death-trigger
pushes, and cross-engine smoke at interleaved-ETB lethal scenarios
will agree on the collection order.

Full rust gate (1698 tests) green post-closure. The new shared
helper is also positioned for the playbook's predicted CE7 (combat
damage assignment, formerly CE6) and CE8 (cross-player find-first
Effect arms, formerly CE7) — those slices will consume
`bf_iter_etb_sorted` rather than re-inlining the collect-and-sort.
The two existing inline sites (`state_ops_snapshot.rs:189`,
`state_ops_fingerprint.rs:316-327`) remain inlined for now;
refactoring them to call the helper is a follow-up post-closure
housekeeping pass.

### I27. SBA victim collection walks battlefield in ETB-timestamp order via shared `bf_iter_etb_sorted` helper

Post-closure (CE6, per `feature/ce5-sba-order`),
`collect_sba_victims` enumerates battlefield objects via
the centralized `crate::bf_iter::bf_iter_etb_sorted` helper, which
stable-sorts refs across both players' battlefields by per-object
`etb_timestamp`. Tie-break preserves the original p0-then-p1
insertion-order walk so synthetic-state fixtures (where every bf
object carries timestamp 0) stay bit-equal with the pre-closure
collection order; real ETB-driven flows (`reserve_etb_timestamp`
bumps) produce strictly-monotonic timestamps and the helper emits
the ETB-interleaved order Python emits via its centralized
`state.battlefield` walk.

The helper is the post-CE4 abstraction step: every battlefield-walking
reader in the engine that needs ETB-ordered cross-player semantics
should call `bf_iter_etb_sorted` rather than re-inline a collect-and-
sort. Today's consumers: `collect_sba_victims` (this invariant).
Planned consumers per `docs/CE5_CE6_CE7_CLOSURE_PLAYBOOK.md` (using
its original numbering): combat damage assignment (playbook's CE6,
bumped to CE7 per the cast-creature CE5 coordination note),
cross-player find-first Effect arms (playbook's CE7, bumped to CE8),
future trigger emitter. The two existing inline stable-sort sites
(`state_ops_snapshot.rs::battlefield_snapshot` line 189 and
`state_ops_fingerprint.rs::fingerprint` lines 316-327) are CE4-closed
and produce identical output to the helper; refactoring them to call
the helper is a follow-up housekeeping pass.

### I26. `battlefield_snapshot` / fingerprint emit in ETB-timestamp monotonic order

Post-CE4 the observable battlefield order is the per-object
`etb_timestamp` sort key, stable-sort tie-breaking on the original
p0-then-p1, insertion-order walk. The invariant: two states with
the same set of bf objects and the same `etb_timestamp` values
produce identical `battlefield_snapshot` outputs and identical
fingerprint battlefield slots.

The fingerprint reads ETB order via this sort and does NOT serialize
`etb_timestamp` into the per-object 8-tuple — so the same gameplay-
relevant content reached via different ETB histories produces the
same digest as long as the relative order of the bf objects ends up
the same. (Two histories that produce different relative bf orders
do produce different digests; that's the intended sensitivity from
the CE4 closure.) Synthetic-state baselines all have timestamp 0
per-object and tie-break to the pre-CE4 walk, so the format is
backward-compatible with every pre-CE4 pinned digest.

The counter `state.next_etb_timestamp` and the per-object slot
`etb_timestamp` are both NOT serialized into the fingerprint
(transient bookkeeping; mirrors the `mulligan_count` /
`consecutive_passes` precedent).

### I29. `state.permanent_left_battlefield_this_turn` flips on every nonland battlefield-exit; resets on entry to PHASE_CLEANUP

- **Pinned by**:
  `tests_rust/test_void.py::test_move_object_creature_from_bf_to_graveyard_flips_flag`,
  `test_move_object_land_from_bf_to_graveyard_does_not_flip`,
  `test_move_object_from_hand_does_not_flip_flag`,
  `test_move_object_to_exile_from_bf_flips_flag`,
  `test_move_object_to_hand_from_bf_flips_flag`,
  `test_move_object_flag_is_state_scoped_not_per_player`,
  `test_move_object_missing_id_does_not_flip_flag`,
  `test_resolve_destroy_target_creature_flips_void_flag`,
  `test_resolve_exile_target_creature_flips_void_flag`,
  `test_resolve_return_to_hand_creature_flips_void_flag`,
  `test_resolve_sacrifice_creature_flips_void_flag`,
  `test_resolve_destroy_target_land_does_not_flip_void_flag`,
  `test_advance_phase_into_cleanup_resets_void_flags`,
  `test_advance_phase_into_cleanup_resets_via_real_ltb_event`,
  `test_void_flag_persists_across_non_cleanup_phase_changes`,
  `test_conditional_if_void_resolves_then_branch_after_production_ltb`,
  `test_conditional_if_void_resolves_else_branch_when_only_land_moved`.

- **Invariant** (closes the LTB-tracking deferred work documented on
  the round-29 `feature/rust-effect-conditional-if-void` slice). The
  `Effect::ConditionalIfVoid` resolver reads `state.is_void_active`
  (OR of `permanent_left_battlefield_this_turn` and
  `spell_warped_this_turn`) at resolve time. Before this slice the
  LTB half had no production setter sites — the predicate always
  evaluated to false at runtime; tests injected the state via the
  test-only `set_void_flags` pymethod. This slice wires the
  production setters so `Effect::ConditionalIfVoid` is load-bearing
  for real cards (Decode Transmissions, Hymn of the Faller, and the
  other 4 EoE "Void —" rider cards).

  **Setter sites** (all routed through the
  `mark_left_battlefield_if_nonland(state, printing_id)` helper in
  `rust/src/state_ops_zones.rs:60-95`, which gates on `not is_land`
  per Python's `turn.move_off_battlefield:163-164`):
  - `state_ops_zones.rs::GameState::move_object` — the chokepoint
    primitive (Option A). Sets the flag when the source-zone search
    succeeds against the battlefield Vec.
  - `state_ops_resolve.rs` — every Effect arm that inlines its own
    `Arc::make_mut`-remove of a permanent from a battlefield Vec:
    `ReturnToHand`, `ExileTarget`, `Sacrifice`, `DestroyTarget`,
    `DestroyTargetNonlandPermanent`, `DestroyTargetArtifact`,
    `DestroyTargetLand`, `DestroyAllCreatures` (sets unconditionally
    if any creature destroyed — creatures are nonland by definition),
    `OptionalSacArtifactForEffect`, `OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary`,
    `DestroyEnchantedPermanent`, `ExileTargetCreatureUntilSourceLeaves`,
    `ExileOpponentsNonlandPermanentUntilLeaves`,
    `EachOpponentSacrificesCreature`. Per-slice file-isolation has
    kept these arms from being refactored onto the `move_object`
    chokepoint (see the round-11 ExileTarget inline note); this
    slice does NOT collapse them onto `move_object` — that's a
    follow-up housekeeping pass. Instead every inline arm calls
    `mark_left_battlefield_if_nonland` directly with the obj's
    `printing_id` captured BEFORE the `obj` value moves into the
    destination zone's push.
  - `state_ops_sba.rs::apply_sbas` — the SBA destruction loop
    (CR 704.5f zero-toughness / 704.5g lethal-damage) likewise
    inlines its own battlefield removal and calls the helper.

  **Reset site**: `state_ops_steps.rs::cleanup_step_for_active_player_inline`
  (the inline mirror fired by `advance_phase` on entry to
  PHASE_CLEANUP). Both flags reset unconditionally at the bottom of
  the cleanup body (step (4) — after the hand-size discard, the
  damage clear, and the UEOT-modifier drain). Mirrors Python's
  `turn.run_cleanup_step:1094-1095`. Non-cleanup phase ticks leave
  the flag alone — the flag's lifetime is the whole turn.

  **State-scoped, not per-player**: the field lives on `GameState`,
  not on `Player`. Mirrors Python's `GameState.permanent_left_battlefield_this_turn`
  field declaration (`game.py:2619`). A nonland LTB triggered by
  either player makes Void active for every consumer regardless of
  controller — matches Python exactly.

  **Consumer**: `Effect::ConditionalIfVoid` (resolved in
  `state_ops_resolve.rs::apply_effect`'s ConditionalIfVoid arm)
  reads the predicate via `state.is_void_active`. The `spell_warped_this_turn`
  half (the other OR-input) is still substrate-only — no Rust call
  site flips it; warp casting is a future slice. The warp-cast
  substrate gap is audited at the slice level in
  `docs/SEARCH_LIMITATIONS.md` under "Rust port — warp alt-cost
  cast pipeline absent; `state.spell_warped_this_turn` substrate-
  only" (added 2026-05-12). The audit pins the closure shape: the
  warp-half setter is a one-line `state.spell_warped_this_turn =
  true` mirror of Python's `actions.py:1427,1457`, slotted into the
  future `cast_via_warp` primitive when (1) `CardPrinting` gets a
  `warp_cost` field, (2) `state_ops_cast.rs` grows a warp-cost
  primitive, and (3) `Action::CastSpell`'s `use_warp` arm flips
  from "ignore the flag" to "route to the warp primitive". Until
  then this I29 invariant covers ONLY the LTB half; the
  `is_void_active` getter intentionally OR's a permanently-false
  field so I29's LTB-half setter is still load-bearing for
  ConditionalIfVoid even with the warp half unwired.

  **Why a helper, not a single `move_object` chokepoint**: the
  Rust resolver was built with per-slice file isolation, so every
  Effect arm that moves a permanent off the battlefield inlines its
  own `Arc::make_mut` pop instead of calling the `move_object`
  pymethod (cross-file `#[pymethods]` private-fn friction —
  documented in the round-11 ExileTarget docstring and the
  state_ops_steps.rs module docstring's "Cross-slice composition"
  section). A single chokepoint per Option A would only catch
  callers that route through `move_object`; the inline arms would
  bypass it. The helper free-fn pattern is the established
  workaround for this class of cross-slice friction (compare
  `untap_all_for_player_inline` / `draw_card_inline` /
  `cleanup_step_for_active_player_inline` in `state_ops_steps.rs`).

  **Cross-reference**: I19 documents a similar transient cause-flag
  lifecycle (`Player.attempted_draw_on_empty` set by every draw
  entrypoint, transitioned into the sticky `has_lost` by
  `apply_sbas`). The Void-flag lifecycle is simpler — no
  SBA-transition step; the flag is both the cause-signal and the
  read surface, and the reset is a single cleanup-step write rather
  than a sticky permanent flag.

### I30. Cross-player find-first Effect arms walk battlefield in ETB-timestamp order via shared `bf_iter_etb_sorted` helper

Post-CE11, `Effect::TapAnotherTargetCreature` and
`Effect::UntapTargetOtherPermanent` enumerate eligible targets via
the centralized `crate::bf_iter::bf_iter_etb_sorted` helper, which
stable-sorts refs across both players' battlefields by per-object
`etb_timestamp`. Tie-break preserves the original p0-then-p1
insertion-order walk so synthetic-state fixtures (where every bf
object carries timestamp 0) stay bit-equal with the pre-CE11 walk;
real ETB-driven flows (`reserve_etb_timestamp` bumps) produce
strictly-monotonic timestamps and the helper emits the ETB-
interleaved order Python's `state.battlefield` walk emits.

Both arms read the player index off `obj.controller` rather than
an outer-loop enumerate index, then perform the mutating
`Arc::make_mut` write pass on `state.players[pidx].battlefield`
unchanged from pre-CE11.

The helper is the post-CE4 abstraction step established by I27 (the
CE6 SBA closure's invariant). Today's consumers post-CE11:
`collect_sba_victims` (I27), `Effect::TapAnotherTargetCreature`
(this invariant), `Effect::UntapTargetOtherPermanent` (this
invariant), and (post-CE9) `deal_combat_damage` (I31 — both
iteration sites). The future trigger emitter is gated on CE8
substrate. The two existing inline stable-sort sites
(`state_ops_snapshot.rs::battlefield_snapshot` line 189 and
`state_ops_fingerprint.rs::fingerprint` lines 316-327) are
CE4-closed and produce identical output to the helper; refactoring
them to call the helper is a follow-up housekeeping pass.

**Pinned by**:
`tests_rust/test_resolve.py::test_resolve_tap_another_picks_etb_first_across_players`,
`test_resolve_tap_another_picks_p1_when_p1_etb_first`,
`test_resolve_untap_other_picks_etb_first_across_players`,
`test_resolve_untap_other_picks_p0_when_p0_etb_first`.

### I31. Combat damage assignment walks battlefield in bf-ETB-timestamp order via shared `bf_iter_etb_sorted` helper; SBA destroy clears per-object combat marks on move-to-graveyard

- **Pinned by**:
  `tests/test_parity_smoke.py::test_cross_engine_multi_block_combat_selector_walks_clean`,
  `tests_rust/test_combat.py::test_multi_block_damage_assignment_picks_etb_first_blocker`,
  `tests_rust/test_combat.py::test_multi_block_damage_back_damage_uses_etb_order`,
  `tests_rust/test_combat.py::test_apply_sbas_clears_damage_on_creature_move_to_graveyard`.

- **Invariant** (closes CE9, per `feature/ce9-blocker-bf-order`).
  Post-closure, `state_ops_combat.rs::deal_combat_damage` walks the
  battlefield via the centralized `crate::bf_iter::bf_iter_etb_sorted`
  helper at both iteration sites:

  1. The per-attacker first-blocker pick (single-blocker damage
     simplification — the attacker's full power goes to the FIRST
     blocker matched in bf-ETB order, NOT the first blocker pushed
     onto `self.blockers`). Built as: collect the per-attacker
     `blocker_id` set from `self.blockers` into a `HashSet<u32>`,
     then `find_map` the first `bf_iter_etb_sorted` object whose id
     is in the set.

  2. The back-damage walk (each blocker emits its damage to the
     attacker, regardless of single-blocker damage assignment).
     Built as: collect the `(blocker_id, attacker_id)` map from
     `self.blockers` into a `HashMap<u32, u32>`, then iterate
     `bf_iter_etb_sorted` filtered to blocker ids in the map. Each
     blocker still emits its damage entry — only the order of
     accumulation differs. Invisible on the symmetric 2/2-vs-2/2
     surface; visible for future variants (lifelink with interleaved
     bf, deathtouch upgrade-then-mark-lethal sequencing).

  Mirrors Python's `combat.py:389,405`
  ``[o for o in state.battlefield if o.id in attacker.blocked_by]``
  walk. The walk is technically a CR 510.1d bug (active player
  chooses damage assignment order = declare order), but the parity
  reference is Python's observable behavior — a long-term Python-
  side fix is a separate follow-up todo.

- **Secondary invariant — SBA destroy clears per-object combat
  marks on move-to-graveyard.** `state_ops_sba.rs::apply_sbas`'s
  move-to-graveyard arm zeroes `obj.damage`, `obj.tapped`, and
  `obj.attached_to` on the way in. Mirrors Python's
  `turn.move_off_battlefield`:230-240 clear-on-zone-change set
  (CR 400.7 / 614.12). counters stay because Python's
  `move_off_battlefield` does NOT clear counters either —
  the observable shape follows Python rather than CR 121.2.
  This was a paired secondary divergence surfaced by the
  multi-block smoke at step 196 (Python's graveyard entries
  had damage=0, Rust's had damage=lethal); closed in the same
  slice as the bf-ETB iteration shift so the CE9 smoke pin
  flips to clean in one move.

- **Why a shared helper instead of inlining**: same rationale as
  I27 (SBA victim collection). The post-CE4 abstraction step is to
  centralize every "walk both players' bfs in ETB order" reader
  through `bf_iter_etb_sorted`. Today's consumers:
  `collect_sba_victims` (I27), the two cross-player find-first
  Effect arms (I30), and `deal_combat_damage` (I31 — both call
  sites). The future trigger emitter is gated on CE8 substrate.

- **Follow-up todo** (deferred): file a Python-side fix for
  `combat.py:389,405` to walk `attacker.blocked_by` in push order
  (matching CR 510.1d's "active player chooses damage assignment
  order"). When that lands, switch Rust's two iteration sites BACK
  to `self.blockers` push order and update this invariant. Scope:
  doubles CE9's blast radius through the Python combat path
  because every Python-side multi-block scenario in the existing
  test suite would shift; deferred until a slice's cadence has
  room.

### I32. `state.resolving_combat_damage_amount` write site: per-event set inside `apply_damage_pass`; reset to 0 between events

- **Pinned by**:
  `tests_rust/test_combat.py::test_resolving_combat_damage_amount_reset_to_zero_after_player_damage`,
  `test_resolving_combat_damage_amount_reset_to_zero_after_creature_damage`,
  `test_resolving_combat_damage_amount_write_overrides_pre_existing_value`,
  `test_resolving_combat_damage_amount_no_attackers_leaves_slot_untouched`,
  `test_resolving_combat_damage_amount_cross_engine_draw_eq_starwinder`.

- **Invariant** (closes the `SEARCH_LIMITATIONS.md` "Rust port —
  `Effect::DrawCardsEqualToResolvingCombatDamage` write site
  deferred" entry). For each per-PlanEntry application inside
  `state_ops_combat.rs::GameState::apply_damage_pass`:

  1. `self.resolving_combat_damage_amount = entry.amount as i32`
     BEFORE the per-entry damage / deathtouch / lifelink mutations
     fire, so any downstream effect that reads the slot sees this
     event's amount.
  2. `self.resolving_combat_damage_amount = 0` AFTER the mutations
     and lifelink fire, so the slot is 0 between events.

  Mirrors Python's per-event set / reset boundaries at
  `combat.py:618,623` (granted dealt-damage trigger resolve, around
  `ability.effect.resolve`) and `actions.py:2684,2699` (stack-pushed
  trigger resolve, around `effect.resolve` in `resolve_top_of_stack`).
  In Python the slot is also mirrored from `StackItem.combat_damage_amount`
  at resolve time (a value the trigger emitter stores at push time);
  Rust today has no apply-loop trigger emitter, so step 1 IS the
  production write — the Effect's read-arm
  (`state_ops_resolve.rs::Effect::DrawCardsEqualToResolvingCombatDamage`)
  now sees a non-zero value any time a downstream resolve runs while
  an apply-loop event is in flight.

- **Why per-event, not per-`deal_combat_damage`-call**: the slot's
  semantic is "the amount THIS event dealt", not "the maximum the
  step dealt". CR-wise, combat damage is dealt simultaneously
  (CR 510.2), but observable behavior at the trigger fire site is
  per-event — Pain for All, Requiem Monolith, Starwinder all read
  the amount of the event they're observing, not an aggregate. The
  reset is what enforces the per-event scoping; without it, the
  last event's amount would leak into a Late-resolving trigger
  that fires after the apply loop returns.

- **No pre-/post- sweep of the slot around the whole call**: the
  write site is scoped strictly to the per-event apply, so a caller
  that pre-sets the slot for a reason (e.g. test harness, or a
  future trigger emitter that needs to thread an amount through to
  a no-op `deal_combat_damage` invocation) is NOT clobbered. The
  no-attacker-leaves-slot-untouched test pins this.

- **Future closure**: when the apply-loop trigger emitter lands
  (combat-damage triggers pushed to the Rust stack at fire time
  with `combat_damage_amount` plumbed onto a `StackItem`-equivalent),
  the read site at `state_ops_resolve.rs:5093` will be unblocked
  end-to-end inside one engine call — no more "re-establish the
  slot to the dealt amount" composition step in the cross-engine
  test. The current write site stays as-is at that point; only
  the trigger-emitter call site composes around it.

### I33. Mass-effect resolve arms walk battlefield in bf-ETB-timestamp order via shared `bf_iter_etb_sorted` helper

- **Pinned by**:
  `tests_rust/test_resolve.py::test_resolve_damage_each_creature_bf_etb_interleaved`,
  `test_resolve_destroy_all_creatures_bf_etb_interleaved`,
  `test_resolve_destroy_all_creatures_bf_etb_indestructible_interleaved`.

- **Invariant** (closes pre-emptive parity for two MEDIUM-risk mass-
  effect sites in `state_ops_resolve.rs` flagged by
  `docs/RUST_BF_ITERATION_AUDIT.md` § 4 R3-adjacent shape, per
  `feature/bf-iter-resolve-arms`). Post-closure, both arms iterate
  every Creature on either battlefield via the centralized
  `crate::bf_iter::bf_iter_etb_sorted` helper rather than walking
  `for pidx in 0..state.players.len()` per-player Vec order:

  1. `Effect::DamageEachCreature` — collects every Creature's
     `(controller_idx, obj_id)` pair from the helper, then applies
     `damage = damage.saturating_add(amount)` to each via a
     per-controller `Arc::make_mut` mutating pass. Damage marking is
     idempotent, so the OUTCOME is bit-identical pre- and post-closure
     on every existing fixture (28 prior tests stay green); the
     change is pre-emptive for future trigger emission order
     (CE8 substrate).

  2. `Effect::DestroyAllCreatures` — collects every destroyable
     (Creature, non-indestructible) `(controller_idx, obj_id)` pair
     from the helper, then pops each from its controller's bf and
     pushes into that controller's graveyard with CR 400.7 zone-
     change reset. Per-controller graveyard contents stay identical
     pre- and post-closure (the centralized walk filtered to a
     single controller produces the same per-controller sequence as
     the prior per-player walk did), so the existing 9 pinned tests
     for DestroyAllCreatures stay bit-equal. The Round-29 Void LTB
     flag (`state.permanent_left_battlefield_this_turn`) is still
     set once if any creature was destroyed.

  Mirrors Python's `effects/generic/damage.py:DealNDamageToEachCreature`
  victim collection
  (`victims = [o for o in state.battlefield if o.printing.is_creature]`)
  and `effects/generic/destroy.py:DestroyAllCreatures.resolve`
  (`for obj in state.battlefield if obj.printing.is_creature: destroy(...)`)
  walks against the centralized `state.battlefield` ETB-monotone order.

- **Why a shared helper instead of inlining**: same rationale as
  I27 (SBA victim collection) and I30 (cross-player find-first). The
  post-CE4 abstraction step is to centralize every "walk both
  players' bfs in ETB order" reader through `bf_iter_etb_sorted`.
  Today's consumers post-I33: `collect_sba_victims` (I27),
  `Effect::TapAnotherTargetCreature` (I30),
  `Effect::UntapTargetOtherPermanent` (I30), `deal_combat_damage`
  (I31 — both call sites), `Effect::DamageEachCreature` (this
  invariant), `Effect::DestroyAllCreatures` (this invariant). The
  future trigger emitter is gated on CE8 substrate.

- **Why pre-emptive, not probe-surfaced**: the damage / destroy
  outcomes are order-invariant (each eligible Creature gets `+amount`
  exactly once / ends up in its own owner's graveyard exactly once),
  so today's parity smoke harness does NOT observe a divergence
  through these two sites — the change is for future-proofing when
  CE8's trigger emitter lands and visit order becomes load-bearing
  for stack-pushed damage / death triggers. Closing while the
  `bf_iter_etb_sorted` helper pattern is established (I27 / I30 /
  I31 precedent) saves a future probe-close-probe round once
  triggers exist.

- **Tie-break invariant**: synthetic-state fixtures with default-0
  ETB timestamps preserve the pre-closure p0-then-p1 walk via the
  helper's stable sort, keeping pre-I33 pinned baselines bit-equal.
  Real ETB-driven flows produce strictly-monotonic timestamps and
  the helper emits the ETB-interleaved order Python's
  `state.battlefield` walk emits. The three new pinning tests use
  `register_and_inject_object` to drive strictly-monotonic ETB
  stamps interleaved across both players (p0_old → p1_mid →
  p0_new → p1_new) to exercise the non-trivial direction.

- **Out of scope for this slice**: 
  - Other R3-cluster single-controller find-first arms in
    `state_ops_resolve.rs` (e.g. `PumpCreaturesYouControlUntilEOT`,
    `PutPlusOneCounterOnEachCreatureYouControl`) — single-player
    walks are parity-safe under CE4's intra-player-monotone
    timestamps (audit § 4 R6 LOW classification).
  - "Defender-only" find-first arms (DestroyTargetNonlandPermanent,
    DestroyTargetArtifact, DestroyTargetLand, TapTargetArtifactOrCreature)
    walk only `state.players[defender_idx].battlefield` for their
    first eligible target. These pick a wrong-player target relative
    to Python's `~IsLand() & ~IsPlayer()` (etc.) any-bf filter, but
    that's a TARGETING semantics divergence beyond the ETB tie-break
    question — handled by the broader target-resolution rewrite
    in `docs/SEARCH_LIMITATIONS.md`'s first-slice deterministic
    target deferral, not this invariant.

### I34. `winner_id` is sticky across the BOTH-LOST transition via a write-once shadow field on `GameState`

- **Pinned by**:
  `tests_rust/test_winloss.py::test_ce12_single_player_loss_writes_sticky_on_first_sba`,
  `test_ce12_sequential_kills_winner_id_stays_sticky`,
  `test_ce12_simultaneous_bilateral_kill_no_sticky_writes_draw`,
  `test_ce12_game_not_ended_pre_sba_no_sticky_write`,
  `test_ce12_sba_with_no_losers_leaves_sticky_none`,
  `test_ce12_sticky_survives_clone`,
  `test_ce12_fingerprint_excludes_winner_id_sticky`;
  `tests/test_parity_smoke.py::test_cross_engine_retaliation_selector_walks_clean`
  (260-decision bilateral-combat walk, parity-clean post-closure).

- **Invariant** (closes CE12, per Phase 5 "converge Rust toward
  Python, never modify Python" — Option B from the CE12 closure-
  direction options). `GameState` carries a new field
  `winner_id_sticky: Option<u8>` (default `None`). The
  field is the canonical mirror of Python's
  `GameState.winner_id` write-once SBA-written semantic
  (`turn.py:1387-1393` — gated on `state.winner_id is None`, so
  once written the field is STICKY and the alive=1 -> alive=0
  transition never clears it).

  **Write path** (inside `state_ops_sba.rs::apply_sbas`, right
  after the per-player `has_lost` commit pass):

  ```text
  if winner_id_sticky.is_none() {
      match (p0.has_lost, p1.has_lost) {
          (false, true) -> winner_id_sticky = Some(p0.id),
          (true, false) -> winner_id_sticky = Some(p1.id),
          _             -> {} // ongoing or simultaneous-both-lost
      }
  }
  ```

  The `is_none()` gate enforces write-once. The `(true, true)`
  branch skips — matching Python's path where `apply_state_based_actions`
  sees `len(alive) == 0` first and only writes `is_draw=True`,
  leaving `winner_id` at None (the simultaneous-loss-without-prior-
  write shape).

  **Read paths** (`state_ops_winloss.rs`):

  1. `winner_id` getter — returns `winner_id_sticky` if `Some(_)`,
     else falls back to the pre-CE12 live derivation from
     `has_lost` flags (CE10's two-layer split is preserved for the
     fallback case).
  2. `is_over()` getter — returns `winner_id_sticky.is_some() ||
     p0.has_lost || p1.has_lost`. Mirrors Python's
     `winner_id is not None or is_draw` — a sticky winner keeps
     is_over True forever, and a bilateral-loss draw keeps it True
     via the `has_lost` union.
  3. `is_draw` getter — returns `p0.has_lost && p1.has_lost`,
     INDEPENDENT of `winner_id_sticky`. Mirrors Python: the SBA
     writer at `turn.py:1384-1386` gates ONLY on `not state.is_draw`,
     NOT on `winner_id is None`. So a sequential-kills sequence —
     SBA pass A flips winner_id to 0 (after p1's loss commit), SBA
     pass B sees both lost and flips is_draw to True — lands with
     BOTH `winner_id == 0` AND `is_draw == True`. Rust's read-side
     getters reproduce that compound shape.

- **Why a shadow field instead of inlining the write into
  `has_lost`**: Python's `Player.has_lost` and
  `GameState.winner_id` carry DIFFERENT semantics — `has_lost` is
  per-player and stays True forever once set, while `winner_id`
  captures "which player was the sole-survivor at the first SBA
  pass that observed exactly one alive". Bilaterally killing both
  players via sequential SBA passes leaves `has_lost == [true,
  true]` but `winner_id` at the player who survived the FIRST
  alive=1 SBA pass. A single field can't carry both pieces of
  information; the shadow field captures the "first sole-survivor
  moment" cleanly.

- **Bookkeeping field — NOT serialized into fingerprint**: mirrors
  `mulligan_count` (I21), `consecutive_passes` (I25), and
  `next_etb_timestamp` (CE4 closure) — bookkeeping state for the
  SBA-gated outcome API, NOT part of the gameplay-relevant state
  digest. The pinned fingerprint baselines (`make_state`,
  synthetic-state mutation deltas) stay bit-equal. Pinned by
  `test_ce12_fingerprint_excludes_winner_id_sticky`: two states
  reached via different paths (one through SBA + sticky-write, one
  through `lose_game` which bypasses `apply_sbas`) that share the
  same observable `has_lost` shape and life totals produce the
  same fingerprint despite differing in `winner_id_sticky`.

- **Cross-reference**:
  - **I19** (the foundational empty-library SBA-driven loss
    transition) — `winner_id_sticky` is written by the SAME
    `apply_sbas` pass that flips `attempted_draw_on_empty ->
    has_lost`, so the empty-library single-loss case writes the
    sticky in lockstep with the eager loss commit.
  - **I29** (Void LTB and second-half flag) — independent
    bookkeeping, listed here for I-section navigation only.
  - **CE10's two-layer API split** (the cause-flags eager API:
    `losers` / `winner` / `is_game_over` / `is_player_alive` —
    UNAFFECTED by sticky). The sticky-winner closure operates
    exclusively on the SBA-gated outcome layer (`is_over` /
    `winner_id` / `is_draw`), preserving the eager API's pre-SBA
    semantics for in-flight scans (`apply_sbas` itself, harness
    code that needs to detect cause-flag-driven loss before the
    next SBA pass).

- **Closure direction rationale**: CE12 offered an Option A
  (Python-side fix — clear `state.winner_id` on alive=0
  transition) and Option B (Rust-side shadow field). Option B was
  taken per Phase 5 convention "converge Rust toward Python, never
  modify Python". The Python semantic IS the bug-for-bug source
  of truth for the cross-engine smoke harness, replay capture
  (`replay_capture.py:325` reward signal), and the eval rounds'
  per-game outcome attribution. Modifying Python here would have
  shifted the reward signal on every existing replay corpus and
  required a parallel pass through the trained-weights pipeline;
  the shadow field is a no-op on every existing baseline.

### I35. `summoning_sick` is preserved across leaves-battlefield transitions (Rust mirrors Python's `move_off_battlefield` non-clear)

- **Pinned by**:
  `tests_rust/test_resolve.py::test_ce13_destroy_target_preserves_summoning_sick_on_ltb`,
  `test_ce13_destroy_all_creatures_preserves_summoning_sick_for_all_sick`,
  `test_ce13_exile_target_preserves_summoning_sick_focused`,
  `test_ce13_return_to_hand_preserves_summoning_sick_focused`,
  `test_ce13_reanimate_etb_still_stamps_summoning_sick_true`;
  `tests/test_parity_smoke.py::test_cross_engine_mass_removal_selector_walks_clean`
  (170-decision mass-removal walk, parity-clean post-closure).

- **Invariant** (closes CE13, per Phase 5 "converge Rust toward
  Python, never modify Python" — Option B from the CE13 closure-
  direction options). On a leaves-battlefield (LTB) transition,
  Rust's destroy / exile / sacrifice / bounce arms preserve
  `obj.summoning_sick` as-is on the leaving object instead of
  resetting it to `false`. Mirrors Python's
  `src/mtg_bot/turn.py:141-250::move_off_battlefield`, which
  resets `damage`, `marked_lethal`, `damaged_this_turn`, `tapped`,
  `attacking`, `blocking`, `blocked_by`, and `attached_to` but
  specifically does NOT clear `summoning_sick`.

  CR 302.1 makes `summoning_sick` battlefield-only state — the
  flag has no gameplay meaning in the graveyard / exile / hand /
  library zones. Re-ETB paths (creature-spell resolve, token
  creation, reanimate, search-for-land-into-bf) unconditionally
  restamp `sick=true` (creatures) or `sick=false` (lands), so the
  preserved-on-LTB value never feeds back into a decision surface.
  The invariant is parity-noise-elimination on the cross-engine
  fingerprint compare, not a gameplay correctness fix.

- **LTB sites updated** (every Effect arm in
  `rust/src/state_ops_resolve.rs` that pops from `battlefield`
  and pushes into a non-battlefield zone):

  1. `Effect::ReturnToHand` (bounce, battlefield → hand)
  2. `Effect::ExileTarget` (battlefield → exile)
  3. `Effect::Sacrifice` (battlefield → graveyard)
  4. `Effect::DestroyTarget` (battlefield → graveyard)
  5. `Effect::DestroyAllCreatures` (mass; battlefield → graveyard)
     — the probe-identified surface site
  6. `Effect::DestroyTargetNonlandPermanent` (battlefield → graveyard)
  7. `Effect::DestroyTargetArtifact` (battlefield → graveyard)
  8. `Effect::DestroyTargetLand` (battlefield → graveyard)
  9. `Effect::EachOpponentSacrificesCreature` (battlefield → graveyard)

  Each site previously contained an explicit
  `obj.summoning_sick = false` next to the other CR 400.7
  resets (`tapped`, `damage`, `counters`, `attached_to`,
  `exiled_with_source`). The line was dropped from every LTB
  site; the surrounding resets are preserved.

- **ETB sites untouched**: `Effect::SearchLibraryForBasicLandTapped`
  (library → battlefield, stamps `sick=false` per CR 302.1
  land-exemption), `move_source_post_resolve` (stamps `sick=true`
  on resolved permanent spells), the reanimate arm
  (`Effect::ReturnCreatureFromYourGraveyardToBattlefield`, stamps
  `sick=true`), and `state_ops_zones.rs::create_token` (stamps
  `sick=true`) are all unaffected — they're battlefield-ENTRY
  sites, where the CR 302.1 stamp is correct.

- **Non-LTB resets retained (not touched by this slice)**:
  `Effect::Mill` (library → graveyard, no battlefield transit),
  `Effect::DiscardCard` / `Effect::DiscardSelf` /
  `Effect::EachOpponentDiscards` (hand → graveyard),
  `Effect::CounterTargetSpell` (any-zone → graveyard for the
  countered spell's source). All of these touch objects that
  carry `sick=false` by construction (no path puts a sick=true
  flag on a hand / library / stack object), so the line is a
  no-op in practice — but kept for code-symmetry with the other
  `tapped = false` / `damage = 0` / `counters = 0` resets.

- **Untap-step clear retained**: `state_ops_steps.rs::clear_summoning_sick_for_player_inline`
  (and its mirror in `state_ops_tap.rs`) explicitly clears
  `summoning_sick = false` on every battlefield object during
  the untap step. This is the CR 302.1-correct ETB-symmetric
  clear — when a sick creature has been on the battlefield since
  its controller's last turn, the untap step clears the flag.
  Mirrors Python's `turn.run_untap_step`.

- **Cross-reference**:
  - **CE13** (the divergence this closure retired). The
    probe-identified surface site was
    `Effect::DestroyAllCreatures` resolve at the wrath fire on
    `mass_removal_selector` step 168.
  - **I33** (mass-effect resolve arms walk bf in ETB-monotone
    order via `bf_iter_etb_sorted`). I35 sits adjacent — same
    LTB arms, different per-object state slot. The two
    invariants stack: bf-ETB walk order determines VICTIM
    selection / iteration order; preserve-on-LTB determines the
    per-victim state shape AFTER selection.
  - **CE1's universal-true summoning_sick default** (closed in
    round 28, when Python's per-object default was aligned with
    Rust's). The pre-CE1 ETB stamp was conditional on
    `is_creature(printing)`; post-CE1 every battlefield-entering
    object gets `sick=true` unconditionally, with the untap step
    clearing the flag at the controller's next untap. I35
    completes the symmetric pair: ETB sets, untap clears, LTB
    preserves.

- **Closure direction rationale**: CE13 offered an Option A
  (Python-side fix — add `obj.summoning_sick = False` to
  `turn.move_off_battlefield`) and Option B (Rust-side drop).
  Option B was taken per Phase 5 convention. Modifying Python's
  `move_off_battlefield` would have shifted every fingerprint
  baseline that captured a graveyard / exile snapshot of a
  destroyed creature with a non-trivial pre-LTB `sick` state,
  and required a parallel pass through the replay corpus +
  trained-weights pipeline. The Rust-side drop is bit-equal on
  every existing baseline (the pre-CE13 fingerprint fixtures
  used synthetic-state objects with `sick=false` on the
  battlefield, so neither pre- nor post-CE13 Rust produced a
  visible state change in those fixtures).

- **Fingerprint baselines**: zero shifts. The synthetic-state
  fixtures used by `test_fingerprint.py` and the pinned
  cross-engine baselines all use battlefield objects with
  `summoning_sick=false` (test-construction default). The new
  behavior only matters when a `summoning_sick=true` creature is
  destroyed / exiled / sacrificed / bounced — a configuration
  that surfaces in the live `mass_removal_selector` probe walk
  (where Bears id 5 was cast at turn 13 and destroyed by wrath
  in the SAME turn's PRECOMBAT_MAIN, so its sick flag was still
  true at LTB time) but not in any baseline fixture.

### I36. Deathtouch redefines "lethal" for CR 510.1c damage assignment to 1 in BOTH the trample and no-trample branches of `deal_combat_damage`

- **Pinned by**:
  `tests_rust/test_combat.py::test_deathtouch_attacker_two_blockers_both_die`,
  `test_deathtouch_attacker_three_blockers_all_marked_lethal`,
  `test_trample_deathtouch_4_4_vs_3_3_blocker_one_to_blocker_three_to_defender`,
  `test_trample_deathtouch_4_4_vs_5_5_blocker_one_to_blocker_three_to_defender`,
  `test_trample_deathtouch_1_1_vs_3_3_blocker_no_trample_excess`,
  `test_trample_deathtouch_exact_one_power_no_excess`;
  `tests/test_parity_smoke.py::test_cross_engine_deathtouch_selector_walks_clean`
  (200-decision deathtouch + multi-block walk, parity-clean
  post-closure).

- **Invariant** (closes CE14, per Phase 5 "converge Rust toward
  Python, never modify Python" — Option A from the CE14 closure-
  direction options). In `rust/src/state_ops_combat.rs::deal_combat_damage`,
  both the trample and no-trample multi-block damage assignment
  branches honor CR 702.2b's deathtouch-redefines-lethal rule
  uniformly:

  - **Trample branch** (CR 702.19c interaction): when the
    attacker has `deathtouch`, the per-blocker `blocker_cap`
    drops from `blocker_toughness` to `1`. The blocker absorbs
    `min(attacker_power, 1)`; the remainder (`attacker_power - 1`)
    tramples through to the defender. Pre-existing as of the
    trample slice — unchanged by CE14.

  - **No-trample branch** (CR 510.1c assignment ordering):
    when the attacker has `deathtouch`, the per-blocker `need`
    drops from `effective_toughness - blocker.damage` to `1`.
    The loop walks ALL blockers in `bf_iter_etb_sorted` order
    (mirroring Python's `combat.py:419-435` per-blocker loop),
    assigning `min(remaining, need)` to each non-last blocker
    and `remaining` to the last blocker (the "is_last and not
    has_trample" tail from Python). The apply-damage pass
    (`apply_damage_pass`) then upgrades each blocker's marked
    damage to `>= blocker.toughness` via the deathtouch-source
    check (`state_ops_combat.rs:1162-1166`), so SBA destroys
    every blocker the attacker touched.

- **Why both branches matter**: CR 702.2b's "any nonzero amount
  of combat damage assigned to a creature by a source with
  deathtouch is considered to be lethal" applies at the
  assignment-order step (CR 510.1c) and binds the attacker's
  required-lethal-floor uniformly — independent of whether the
  attacker also has trample. The trample branch happened to
  honor the deathtouch=1 cap from the start of the trample
  slice (it's the only way to compute the trample-through
  excess correctly); the no-trample branch was the pre-CE14 gap.
  Pre-closure, a deathtouch attacker without trample
  blocked by N blockers killed only the bf-ETB-first one —
  the no-trample branch emitted a single PlanEntry carrying
  full `attacker_power` to `first_blocker`, leaving blockers
  2..N untouched with `damage=0`.

- **Loop shape parity with Python** (`combat.py:419-435`):
  ```rust
  let mut remaining: i16 = attacker_power;
  for (i, &blocker_id) in bf_ordered_blockers.iter().enumerate() {
      if remaining <= 0 { break; }
      let need = if attacker_has_deathtouch { 1 } else {
          max(0, effective_toughness(blocker) - blocker.damage)
      };
      let is_last = i == n_blockers - 1;
      let assigned = if is_last { remaining }
                     else { min(remaining, need) };
      // emit PlanEntry { source, blocker, assigned, pass }
      remaining -= assigned;
  }
  ```
  Matches Python's loop element-by-element with the
  `is_last and not has_trample: assigned = remaining` tail
  preserved (the no-trample-branch caller already gates on
  `!attacker_has_trample`, so `is_last` alone is sufficient
  inside this branch).

- **Round-5 single-blocker observable preserved**: when there
  is exactly ONE blocker, the loop runs once with `i=0` and
  `is_last=true`, so `assigned = remaining = attacker_power`.
  Bit-equal to the pre-CE14 single-PlanEntry shape; the CE9
  single-blocker tests
  (`test_blocked_attacker_damages_blocker_not_player`,
  `test_blocker_damages_attacker`,
  `test_multi_block_damage_assignment_picks_etb_first_blocker`)
  all continue to pass without modification.

- **Multi-block back-damage walk unchanged**: every declared
  blocker still emits its own back-damage PlanEntry targeting
  the attacker via the `blocker_to_attacker` map walk
  (state_ops_combat.rs ~ line 999-1023). I31's bf-ETB-monotone
  back-damage walk composes orthogonally with I36's per-blocker
  forward-damage walk.

- **Cross-reference**:
  - **CE14** (the divergence this closure retired). The
    probe-identified surface site was step 174 of
    `deathtouch_selector` on the `multi_blocker_deckspec` walk,
    where a 2/2 deathtouch attacker against two 2/2 Bears
    killed both blockers in Python and only one in Rust.
  - **I31** (combat damage assignment walks bf-ETB-sorted).
    I36 sits adjacent — same combat-damage forward-pass loop,
    different per-blocker `need` calculation. The two
    invariants stack: bf-ETB walk order determines the
    iteration sequence; deathtouch's lethal redefinition
    determines per-blocker `need`.
  - **Trample's CR 702.19c interaction** (already pinned by
    the `test_trample_deathtouch_*` family). I36 generalizes
    the deathtouch-cap-is-1 rule to cover the no-trample
    branch too — the rule now applies uniformly to all
    deathtouch attackers regardless of trample presence.
  - **I37** (trample multi-block damage assignment walks all
    blockers with per-blocker `need_i` floor; remainder spills
    to defender). I37 lands the structural per-blocker walk in
    the trample branch (CE15 closure) — I36 + I37 together
    specify the post-CE14/CE15 multi-block damage assignment
    shape uniformly across the trample and no-trample boundaries.

### I37. Trample multi-block damage assignment walks ALL blockers in bf-ETB order with per-blocker `need_i` floor; remainder spills to defender (CR 702.19b + 702.19c)

- **Pinned by**:
  `tests_rust/test_combat.py::test_trample_two_blockers_no_deathtouch_no_excess`,
  `test_trample_two_blockers_no_deathtouch_with_excess`,
  `test_trample_deathtouch_two_blockers_excess`,
  `test_trample_single_blocker_preserved_post_ce15`;
  plus the pre-existing single-blocker trample test family
  (`test_trample_blocked_excess_goes_to_defender`,
  `test_trample_blocked_no_excess_when_attacker_smaller_than_blocker_toughness`,
  `test_trample_blocked_exact_lethal_no_excess`,
  `test_trample_only_4_4_vs_3_3_blocker_pins_existing_round9_behavior`,
  `test_trample_deathtouch_4_4_vs_3_3_blocker_one_to_blocker_three_to_defender`,
  `test_trample_deathtouch_4_4_vs_5_5_blocker_one_to_blocker_three_to_defender`,
  `test_trample_deathtouch_1_1_vs_3_3_blocker_no_trample_excess`,
  `test_trample_deathtouch_exact_one_power_no_excess`).

- **Invariant** (closes CE15, per Phase 5 "converge Rust toward
  Python, never modify Python"). In
  `rust/src/state_ops_combat.rs::deal_combat_damage`, the trample
  branch walks every blocker in `bf_iter_etb_sorted` order with
  per-blocker `need_i`:

  ```rust
  // attacker_has_trample == true
  let mut remaining: i16 = attacker_power;
  for &blocker_id_i in bf_ordered_blockers.iter() {
      if remaining <= 0 { break; }
      let need: i16 = if attacker_has_deathtouch {
          1  // CR 702.19c: deathtouch redefines lethal to 1
      } else {
          max(0, effective_toughness(blocker) - blocker.damage)
      };
      // Trample: NO is_last-takes-remainder tail (the spill below
      // handles the remainder). Each blocker absorbs only its
      // lethal floor.
      let assigned: i16 = min(remaining, need);
      // emit PlanEntry { blocker_id_i, assigned } via passes_for_source
      remaining -= assigned;
  }
  if remaining > 0 {
      // emit PlanEntry { defender, remaining } — trample-through
  }
  ```

  Matches Python's `combat.py:419-440` loop element-by-element
  under `has_trample=True`. Python's `is_last and not has_trample:
  assigned = remaining` tail is intentionally NOT applied in the
  trample case (the `if has_trample and remaining > 0` block at
  Python's `combat.py:436-440` collects the remainder for the
  defender).

- **Why I36 and I37 are split** rather than folded into one
  invariant: the two branches share the bf-ETB iteration pattern
  and the deathtouch lethal redefinition, but diverge on what
  happens to the remainder after every blocker has absorbed its
  `need_i`. The no-trample branch (I36) has Python's `is_last and
  not has_trample: assigned = remaining` tail — the last blocker
  absorbs whatever power remains, preserving the round-5 single-
  blocker "assign full power to first blocker" observable. The
  trample branch (I37) routes the remainder to the defender as
  trample-through. Future refactors that consolidate the two
  branches into a single loop must preserve both tails by gating
  on `has_trample` inside the loop body.

- **Single-blocker observable preserved**: with exactly ONE
  blocker, the trample loop runs once with `assigned = min(power,
  need)`, then `remaining = power - assigned` spills to the
  defender. Bit-equal to the pre-CE15
  `to_blocker = min(power, blocker_cap)` /
  `excess = power - blocker_cap` math (where `blocker_cap = 1 if
  deathtouch else blocker_toughness`). The 8 pre-existing
  single-blocker trample / trample+deathtouch tests continue to
  pass without modification.

- **Pre-CE15 gap**: the trample branch had a single-PlanEntry
  shortcut that emitted only to `first_blocker` (the bf-ETB-first
  eligible blocker) carrying `min(power, blocker_cap)`, leaving
  blockers 2..N untouched with `damage=0`. CE14's diagnostic note
  surfaced the asymmetry: CE14 fixed the no-trample branch's
  identical pattern, leaving the trample branch as the same bug
  with different downstream math. CE15 closes the trample-branch
  half preemptively (no separate probe; the diagnosis was
  complete).

- **Cross-reference**:
  - **CE15** (the divergence this closure retired). Identified
    in CE14's diagnostic note rather than via a fresh
    cross-engine probe.
  - **I31** (combat damage assignment walks bf-ETB-sorted). I37
    composes on top of I31 — bf-ETB walk order determines the
    iteration sequence; per-blocker `need_i` determines the
    per-blocker assignment.
  - **I36** (deathtouch's lethal redefinition in BOTH branches).
    I37 generalizes the per-blocker walk pattern across the
    trample/no-trample boundary; I36 generalizes the deathtouch
    lethal redefinition across the same boundary. The two
    invariants stack: I36 + I37 together specify the post-CE14/
    CE15 multi-block damage assignment shape uniformly.
  - **Multi-block back-damage walk** unchanged (every declared
    blocker still emits its own back-damage PlanEntry — that pass
    already iterated all blockers pre-CE15). I31's bf-ETB-monotone
    back-damage walk composes orthogonally with I37's per-blocker
    forward-damage walk.

### I38. `Action::DeclareBlockers` apply arm post-validates each touched attacker via `is_legal_block_assignment`; illegal final assignments are silently dropped from `state.blockers` via `.retain`

- **Pinned by**:
  `tests_rust/test_combat.py::test_apply_action_declare_blockers_menace_single_blocker_dropped`,
  `test_apply_action_declare_blockers_menace_two_blockers_retained`,
  `test_apply_action_declare_blockers_menace_zero_blockers_unblocked`,
  `test_apply_action_declare_blockers_non_menace_single_blocker_retained`;
  plus the cross-engine parity pins
  `tests/test_parity_smoke.py::test_cross_engine_menace_selector_single_blocker_walks_clean`
  (the closure trigger that flipped from strict-xfail to expected
  pass) and the two scenario A/B clean-walk pins
  (`..._no_blockers_walks_clean`, `..._both_blockers_walks_clean`).

- **Invariant** (closes CE16, per Phase 5 "converge Rust toward
  Python, never modify Python"). In
  `rust/src/state_ops_actions.rs`'s `Action::DeclareBlockers` arm,
  after the per-pair `declare_blocker(blocker_id, attacker_id)`
  dispatch loop, a post-loop validation pass collects the unique
  attacker ids that the assignments touched and, for each, calls
  `is_legal_block_assignment(attacker_id)` (defined at
  `state_ops_combat.rs:779-789`). For every attacker that fails
  the predicate, the matching `(attacker_id, _)` entries are
  removed from `state.blockers` via
  `.retain(|(a, _)| !illegal.contains(a))`. The attacker proceeds
  as if unblocked; combat damage hits the defender.

- **Today's only failure case** is menace (CR 702.110b): a menace
  attacker with exactly one blocker fails the predicate.
  Non-menace attackers, menace attackers with zero blockers, and
  menace attackers with two or more blockers all pass the
  predicate, so the retain pass is a no-op for them. Future
  multi-block constraints folded into `is_legal_block_assignment`
  inherit the post-loop retain behavior automatically; no apply-
  arm change required.

- **Mirrors Python's silent-drop shape**. `actions.py:2555-2566`
  groups blockers by attacker after the per-pair eligibility
  loop and, for each attacker carrying `"menace"` AND
  `len(blocker_ids) < 2`, calls `validated.pop(bid, None)` on each
  blocker assigned to that attacker. The action does NOT raise —
  Python treats the request as "do your best; drop illegal sub-
  pieces". Rust's post-loop `.retain` mirrors that shape exactly.

- **Why the retain pass goes AFTER the per-pair loop, not before
  or interleaved**: `is_legal_block_assignment` reads
  `self.blockers`, so the predicate needs the final block set to
  count correctly. The first blocker assigned to a menace attacker
  is illegal in isolation but legal once a second is added —
  declare-time rejection would force callers to declare in some
  artificial "all at once" form. The post-loop retain is the
  natural integration point, and matches Python's "validate after
  the per-pair filter" shape.

- **Scope of the touched-attackers set**: we collect the unique
  attacker ids from THIS apply call's assignments and only retain
  against those. Pre-existing legal blocks on OTHER attackers
  (declared by a prior apply_action call, or by the synthetic-
  state injection path) are left alone — the apply arm only
  validates the work it just did.

- **Cross-reference**:
  - **CE16** (the divergence this closure retired).
  - **`is_legal_block_assignment`** predicate at
    `state_ops_combat.rs:779-789`. This invariant wires the
    predicate into the apply path; the predicate itself ships
    independently and is callable read-only from Python tests.
  - **Python `actions.py:2555-2566`** — the reference
    implementation whose silent-drop shape this invariant
    matches.

### I39. "Defender-only" target arms in `state_ops_resolve.rs` walk both players' battlefield in ETB-timestamp order via shared `bf_iter_etb_sorted` helper (no controller restriction)

- **Pinned by**:
  `tests_rust/test_resolve.py::test_resolve_destroy_target_nonland_permanent_picks_etb_first_across_players`,
  `test_resolve_destroy_target_nonland_permanent_defender_only_no_opponent_eligible`,
  `test_resolve_destroy_target_nonland_permanent_source_controller_only_eligible`,
  `test_resolve_destroy_target_artifact_picks_etb_first_across_players`,
  `test_resolve_destroy_target_artifact_defender_only_no_opponent_eligible`,
  `test_resolve_destroy_target_artifact_source_controller_only_eligible`,
  `test_resolve_destroy_target_land_picks_etb_first_across_players`,
  `test_resolve_destroy_target_land_defender_only_no_opponent_eligible`,
  `test_resolve_destroy_target_land_source_controller_only_eligible`,
  `test_resolve_tap_target_artifact_or_creature_picks_etb_first_across_players`,
  `test_resolve_tap_target_artifact_or_creature_defender_only_no_opponent_eligible`,
  `test_resolve_tap_target_artifact_or_creature_source_controller_only_eligible`.

- **Invariant** (closes the I33-flagged "defender-only" target-arm
  divergence, per `feature/defender-only-target-arms`). The four
  "first-slice deterministic target" arms in `state_ops_resolve.rs`
  now select their target via the centralized
  `crate::bf_iter::bf_iter_etb_sorted` helper rather than scanning
  `state.players[(1 - active_player)].battlefield` top-to-bottom:

  1. `Effect::DestroyTargetNonlandPermanent` (~line 2503) — first
     non-Land, non-indestructible permanent across BOTH bfs.
  2. `Effect::DestroyTargetArtifact` (~line 2549) — first Artifact,
     non-indestructible permanent across BOTH bfs.
  3. `Effect::DestroyTargetLand` (~line 2600) — first Land,
     non-indestructible permanent across BOTH bfs.
  4. `Effect::TapTargetArtifactOrCreature` (~line 3477) — first
     permanent matching the Artifact-OR-Creature filter across BOTH
     bfs. Idempotent on already-tapped target.

  Each arm reads the controller index off `obj.controller` rather
  than the prior hard-coded `defender_idx = (1 - active_player)`,
  then performs the mutating `Arc::make_mut` pass on
  `state.players[controller].battlefield` (and `.graveyard` for the
  destroy arms).

  Mirrors Python's
  `effects/generic/destroy.py:Destroy.resolve` and
  `effects/generic/tap.py:Tap.resolve`, which use the `TargetSpec`
  grammar against the centralized `state.battlefield` (a single
  list aggregating both players' permanents in ETB-insertion
  order — see `game.py:2585`). Python's filters
  (`~IsLand() & ~IsPlayer()`, `IsArtifact()`, `IsLand()`, and the
  `IsArtifact() | IsCreature()` union for `TapTargetArtifactOrCreature`)
  carry NO controller restriction, so Rust's pre-I39 defender-only
  walk picked a wrong-player target whenever the source's own bf
  carried the first ETB-ordered eligible permanent (and worse,
  fizzled when ONLY the source had an eligible target).

- **Three divergence directions pinned per arm** (12 tests total):

  - **Cross-player ETB-interleave** — source's bf has the older
    eligible permanent; defender's has the newer one. Pre-I39 picked
    defender's (wrong); post-I39 picks source's (matches Python).
  - **Defender-only-eligible** — only defender has an eligible
    permanent. Behavior unchanged pre/post I39 (the walk still finds
    it).
  - **Source-controller-only-eligible** — only source has an
    eligible permanent. Pre-I39 fizzled (defender's walk found
    nothing); post-I39 destroys/taps the source's own permanent
    matching Python.

- **Why a shared helper instead of inlining**: same rationale as
  I27 (SBA victim collection), I30 (cross-player find-first taps/
  untaps), I31 (combat damage assignment), and I33 (mass-effect
  resolve arms). The post-CE4 abstraction step is to centralize
  every "walk both players' bfs in ETB order" reader through
  `bf_iter_etb_sorted`. Today's consumers post-I39:
  `collect_sba_victims` (I27),
  `Effect::TapAnotherTargetCreature` (I30),
  `Effect::UntapTargetOtherPermanent` (I30),
  `deal_combat_damage` (I31 — both call sites),
  `Effect::DamageEachCreature` (I33),
  `Effect::DestroyAllCreatures` (I33),
  `Effect::DestroyTargetNonlandPermanent` (this invariant),
  `Effect::DestroyTargetArtifact` (this invariant),
  `Effect::DestroyTargetLand` (this invariant),
  `Effect::TapTargetArtifactOrCreature` (this invariant).
  The future trigger emitter is gated on CE8 substrate.

- **Tie-break invariant**: synthetic-state fixtures with default-0
  ETB timestamps preserve the pre-closure p0-then-p1 walk via the
  helper's stable sort. The 12 new pinning tests use
  `register_and_inject_object` to drive strictly-monotonic ETB
  stamps so the cross-player direction is exercised meaningfully;
  the unmodified existing tests continue to rely on the tie-break
  shape. A small handful of pre-I39 tests with synthetic-state
  fixtures had to be updated: their assertions pinned the now-fixed
  bug (the "defender-only" scan happening to also pick the
  defender's bf[0] match), and the new tests' "destroys p0's own
  permanent" / "picks p0's first Bears in cross-player walk"
  shapes reflect Python's any-bf walk semantics. These are:
  `test_resolve_destroy_target_nonland_permanent_destroys_first_creature`,
  `test_resolve_destroy_target_nonland_permanent_resets_state`,
  `test_resolve_destroy_target_*_targets_source_controller_when_only_eligible`
  (3 renamed from `_skips_active_players_own`),
  `test_resolve_tap_aoc_picks_first_creature_in_bf_etb_order`
  (renamed from `_picks_first_creature_on_defender_bf`),
  `test_resolve_tap_aoc_picks_creature_over_later_artifact` (renamed
  from `_picks_artifact_when_present`), and the `_no_eligible_fizzles`
  / `_idempotent_on_already_tapped` shapes.

- **Why surfaced now (not earlier)**: I33 closed the two MEDIUM-risk
  mass-effect sites and explicitly deferred this slice with the note
  "defender-only 'target' arms walk only
  `state.players[defender_idx].battlefield` for their first eligible
  target. These pick a wrong-player target relative to Python's
  any-bf filter, but that's a TARGETING semantics divergence beyond
  the ETB tie-break question." This slice closes that follow-up:
  the divergence is broader than ETB-monotone-order — it's a
  controller-scope mismatch — and the fix shape is the same
  helper-driven walk that all the I27/I30/I31/I33 sibling arms
  already use.

- **Fingerprint baselines**: bit-equal pre- vs post-I39 on every
  synthetic-state fixture in `tests_rust/test_fingerprint.py`. The
  synthetic-state fixtures don't carry cross-player ETB-interleaved
  eligible targets for these four effects, so the centralized walk
  produces the same target pick as the pre-I39 defender-only walk
  (or both fizzle).

### I40. `legal_decisions` declare_attackers eligibility filters defender via shared `battlefield_has_keyword` helper (mirrors apply-time gate)

- **Pinned by**:
  `tests_rust/test_legal.py::test_legal_decisions_declare_attackers_defender_creature_excluded`,
  `tests/test_parity_smoke.py::test_cross_engine_defender_selector_legal_decisions_excludes_defender`
  (formerly the CE17 strict-xfail symptom pin, now expected-pass).

- **Invariant** (closes CE17, per Phase 5 "converge Rust toward
  Python, never modify Python" — Option A from the CE17 closure-
  plan). The DeclareAttackers eligibility loop in
  `state_ops_legal.rs::legal_decisions` short-circuits any
  battlefield permanent whose effective keyword set contains
  `"defender"` via
  `crate::state_ops_combat::battlefield_has_keyword(self, obj.id,
  "defender")`. The helper reads printed keywords AND
  UEOT-granted keywords (CR 613 layer 6) — same surface the
  apply-time gate consults — so a creature that gained defender
  from a UEOT modifier this turn is filtered too.

  Mirrors:
  - Python's source-of-truth filter at
    `src/mtg_bot/combat.py:eligible_attackers` line 22:
    `"defender" not in effective_keywords(state, o)`.
  - Rust's apply-time gate at `state_ops_combat.rs:639-641`
    (`if battlefield_has_keyword(self, obj_id, "defender") {
    return false; }`).

  Same helper, same lookup, both surfaces.

- **Pre-I40 gap**: `state_ops_legal.rs:556-608` (DeclareAttackers
  emission inside `legal_decisions`) filtered eligibility on
  ``tapped`` + ``creature`` + ``summoning_sick`` vs ``haste`` only
  — NO DEFENDER FILTER. The module docstring at lines 167-180
  flagged this as deferred: *"Defender keyword (CR 702.3) —
  Python's eligible_attackers filters this out at enumeration time;
  first slice defers to the primitive's per-id gate at apply."*
  Result: every declare_attackers subset that included a
  defender's id was emitted as if legal — e.g. with Bears id 5
  and Bear Wall id 14 (defender) both untapped on p0's bf, the
  emitted subsets were ``[(), (5,), (14,), (5, 14)]``; the last
  two were illegal per CR 702.3. Apply-time silently dropped
  illegal subsets, so production engine state was unaffected, but
  MCTS / ISMCTS / capability-probe paths wasted node expansions on
  illegal candidates.

- **Why a shared helper instead of inlining**: same rationale as
  I27/I30/I31/I33/I39 — centralize through the existing
  `battlefield_has_keyword` (UEOT-aware) so the eligibility filter
  and the apply-time gate read the same truth. The slot was
  visible at `state_ops_combat.rs:328` (was previously file-private
  `fn`; CE17 closure widens to `pub(crate)` so
  `state_ops_legal.rs` can call it cross-module).

- **Fix shape**: one logical clause added to the eligibility loop
  (after the summoning-sick-vs-haste gate, before the
  `eligible.push(obj.id)`):

      if crate::state_ops_combat::battlefield_has_keyword(self, obj.id, "defender") {
          continue;
      }

- **Cross-reference**: I40 (enumeration) and the apply-time gate
  at `state_ops_combat.rs:639-641` are the two halves of the
  CR 702.3 enforcement on the Rust side. Python collapses both
  surfaces into a single `eligible_attackers` reader because its
  `legal_actions` doesn't enumerate DeclareAttackers subsets
  (search-side combat-decisions factoring instead — see
  `state_ops_legal.rs` module docstring on "DeclareAttackers
  emission (Rust-only)").

- **Fingerprint baselines**: NO shifts. `legal_decisions` is a
  pure reader; it does not mutate `GameState`. The CE17 closure
  changes only the emission shape — production self-play / eval
  state outcomes were already unaffected pre-closure (apply-time
  silently dropped illegal subsets). The fingerprint baselines in
  `tests_rust/test_fingerprint.py` are bit-equal pre- vs post-I40.

### ~~CE5.~~ CLOSED: `cast_spell` cross-engine parity via harness-side `resolve_top_of_stack_python` mirror

Closed by the CE5 closure slice (`feature/ce5-cast-resolve`).
Option (2) from the pre-closure two-option plan — the lowest-cost
harness-side mirror — was taken. Rust's
`state_ops_cast.rs::cast_creature` keeps its no-stack semantics
(cast + resolve fused into one primitive); the cross-engine
harness in `src/mtg_bot/parity/cross_engine.py` now drains
Python's stack after every `cast_spell` action so the post-step
compare sees Python's resolved state instead of its in-flight
StackItem.

**Closure shape.** A new harness primitive
`resolve_top_of_stack_python(py_state) -> int` in
`src/mtg_bot/parity/cross_engine.py` drains the Python stack until
empty, mirroring `simulate.priority_loop` line 257: pop one item
via `resolve_top_of_stack`, run `state_based_actions`, repeat. The
while-loop also catches any trigger items the resolve itself
pushes (ETBs etc.) — today no-op on the synthetic deck (Bears has
no triggers), correct shape for future trigger-bearing printings.

`step_both` is the integration site. After both engines apply the
action dict, the harness checks
`action_dict["kind"] in _RUST_AUTO_RESOLVE_ACTION_KINDS` (today:
just `cast_spell`) and runs the drain if so. The frozenset gate is
the extension point: any future Rust primitive that ships fused
cast+resolve semantics (e.g. a no-stack `activate_non_mana_ability`
arm) appends its kind there. This is the same harness-mirror
pattern as `advance_phase_python` — HARNESS-only, production
engines unchanged. Rust keeps its no-stack `cast_creature`;
production Python keeps its push-StackItem-then-resolve flow
through the real priority loop.

**Tests.** The pre-closure strict-xfail clean-walk pin
`test_cross_engine_cast_bears_selector_walks_clean` flipped to
expected-pass at N=150 decisions (the brief's target window). The
walk traverses every prior surface divergence point cleanly: the
cast at step 108 (this slice), the empty-library draw at step 119
(closed independently by CE10's SBA-gating of the surface
accessors), and the post-cast/post-loss-flag turns 10+. Companion
symptom-pin
`test_cross_engine_cast_bears_selector_surfaces_ce5_cast_resolve_at_step_108`
deleted per the CE2/CE3/CE4 closure-pair contract — the symptom no
longer surfaces post-closure. Two new regression tests pin the new
equilibrium:

- `test_cross_engine_cast_bears_selector_cast_step_108_walks_clean_post_ce5`
  — at step 108 (the cast step) both engines agree: 7 bf objects
  including Grizzly Bears, empty stack on both sides.
- `test_cross_engine_resolve_top_of_stack_python_drains_stack` —
  exercises the harness primitive directly: pins the step_both
  integration AND the no-op contract on empty stacks.

**Invariant: see I28 below** — pins the harness-mirror as the
canonical Python-Rust cast comparison contract.

**Fingerprint baselines.** Zero shifts. The mirror is harness-only;
no production engine code path changed on either side. Rust's
`cast_creature` still emits the same bf-stamped, no-stack
post-state it always has; Python's `_cast_spell` still pushes a
StackItem (production Python's priority loop drains it normally).
The only place the new primitive runs is `step_both` in the
cross-engine harness.

**Out of scope (recorded as future slices).** The
cast_bears_selector probe surfaced one side finding while reaching
step 108 that this slice intentionally does NOT address:

- **Rust `ActivateAbility` rejects summoning-sick LANDS** (CR 302.1
  applies only to creatures tapping for tap-cost abilities; lands
  are exempt). The `state_ops_actions.rs` dispatch arm at line ~523
  gates on `obj.summoning_sick` regardless of card type. The
  selector sidesteps this by Python-side filtering sick lands; a
  future one-line slice can drop the gate when source is a land.

(The second pre-closure side finding — Rust's eager `is_over` on
empty-library draw at step 119 — was closed by CE10 in
`feature/ce-pure-derivation-is-over`, which landed before this
slice. Both engines now stay stale on the surface accessors until
SBAs fire, and the 150-decision walk crosses step 119 parity-clean.)

The next-natural CE5-closure-extension is to widen the
`cast_bears_selector` (or a successor) past the cast into combat
declarations, which would surface the playbook's CE7 (combat damage
assignment — formerly playbook-CE6 pre-renumber)
collection-order divergence as the next CE candidate.

(Other smoke-flagged divergences may be added by follow-up Phase 5
slices as the deck pool / decision script grows.)

### I28. Cross-engine `cast_spell` parity via harness-side `resolve_top_of_stack_python` mirror

`step_both` in `src/mtg_bot/parity/cross_engine.py` drains Python's
stack via `resolve_top_of_stack_python` after every action whose
kind is in `_RUST_AUTO_RESOLVE_ACTION_KINDS` (today:
`{"cast_spell"}`). The drain mirrors `simulate.priority_loop`'s
"resolve until empty" contract (CR 117.4): pop one StackItem via
`resolve_top_of_stack`, run `state_based_actions`, repeat. This
parity-aligns Python's observable state with Rust's no-stack
`cast_creature` semantics for cross-engine comparison purposes.

The invariant: when the cross-engine walker applies a `cast_spell`
action, the post-step compare sees both engines' stacks empty and
both engines' battlefields with the resolved permanent. Production
Python is unchanged — the harness primitive is invoked only from
`step_both`. Production Rust is unchanged — `cast_creature`'s
no-stack semantics are preserved (documented in the
`state_ops_cast.rs:293` docstring and reaffirmed here).

Extension point: any future Rust primitive that ships fused
cast+resolve semantics for a different action kind appends its
kind to `_RUST_AUTO_RESOLVE_ACTION_KINDS`. The drain itself is
already trigger-loop-correct (the while-loop catches any items the
resolve itself pushes), so the only update needed for new kinds is
the action-kind gate.

### ~~CE8.~~ CLOSED: All 8 gameplay shuffle sites accept an external `rng` parameter; cross-engine shuffles consume a shared `random.Random` stream

> **Status: FULLY CLOSED by `feature/ce8-slice-1` (substrate +
> setup-shuffle) followed by `feature/ce8-slice-2` (the remaining 6
> gameplay shuffle entries).** Every Rust gameplay-RNG site now
> accepts an optional `rng: Option<&Bound<'_, PyAny>>` kwarg via the
> shared substrate in `rust/src/external_rng.rs::next_below`. When
> supplied, the Fisher-Yates loop consumes draws from the
> caller-supplied Python `random.Random` instance, matching
> `random.Random.shuffle(list)` byte-for-byte. When `rng=None`
> (default), the legacy xorshift64 path runs unchanged so production
> cli/bench callers stay bit-equivalent to pre-slice behavior.
>
> **The 8 rewired sites (Slice 1 + Slice 2):**
>
> Slice 1 (setup-shuffle, 2 sites in `state_ops_setup.rs`):
> 1. `make_state` p0 library Fisher-Yates
> 2. `make_state` p1 library Fisher-Yates
>
> Slice 2 (6 gameplay sites):
> 3. `state_ops_library.rs::shuffle_library_with_seed`
> 4. `state_ops_library.rs::search_library_and_move_to_hand` (CR 701.18)
> 5. `state_ops_library.rs::search_library_for_first_of_type_and_shuffle` (CR 701.19)
> 6. `state_ops_mulligan.rs::mulligan`
> 7. `state_ops_mulligan.rs::mulligan_to_n`
> 8. `state_ops_mulligan.rs::mulligan_atomic`
>
> Both Slice 2 files use a shared `fisher_yates_shuffle_optional`
> helper that dispatches between the external rng path and the
> xorshift64 fallback. Each pymethod signature gains an
> `rng = None` keyword-only kwarg via `#[pyo3(signature = ...)]`;
> existing positional callers stay binary-compatible.
>
> **Tests pinning the closure:**
>
> Slice 1 (in place from `feature/ce8-slice-1`):
> - 10 new cases in `tests_rust/test_setup.py` covering the
>   setup-shuffle external-rng semantics (matches Python
>   `random.shuffle` byte-for-byte, determinism, precedence over
>   `shuffle_seed`, hand untouched, empty / single-card no-ops,
>   error on invalid rng).
> - 3 cross-engine smoke tests in
>   `tests/test_parity_smoke_edge_cases.py`
>   (`test_cross_engine_shared_rng_seed_walks_clean`,
>   `test_cross_engine_shared_rng_seed_matches_python_random_shuffle_byte_for_byte`,
>   `test_cross_engine_shared_rng_seed_walks_clean_for_multiple_seeds`).
>
> Slice 2 additions:
> - 10 new cases in `tests_rust/test_library.py` covering the three
>   library shuffle sites (matches Python MT byte-for-byte, failed
>   search still shuffles, backward-compat `rng=None` fallback,
>   determinism, invalid-rng error).
> - 7 new cases in `tests_rust/test_mulligan.py` covering the three
>   mulligan shuffle sites (matches Python MT byte-for-byte per
>   variant, backward-compat `rng=None` fallback, determinism,
>   invalid-rng error).
> - 7 new cross-engine smoke tests in
>   `tests/test_parity_smoke_edge_cases.py` (one per rewired site +
>   a multi-seed robustness pin):
>   `test_cross_engine_shuffle_library_with_seed_matches_python_mt_byte_for_byte`,
>   `test_cross_engine_search_library_and_move_to_hand_matches_python_mt_byte_for_byte`,
>   `test_cross_engine_search_library_for_first_of_type_and_shuffle_matches_python_mt_byte_for_byte`,
>   `test_cross_engine_mulligan_matches_python_mt_byte_for_byte`,
>   `test_cross_engine_mulligan_to_n_matches_python_mt_byte_for_byte`,
>   `test_cross_engine_mulligan_atomic_matches_python_mt_byte_for_byte`,
>   `test_cross_engine_gameplay_shuffles_walk_clean_for_multiple_seeds`.
>
> The legacy `shuffle_seed` strict-xfail at
> `tests/test_parity_smoke_edge_cases.py` line 401 and its line-427
> companion stay as-is: they pin the LEGACY xorshift64 path, which
> is preserved by Slice 1 + Slice 2 as the `rng=None` backward-
> compat fallback. Production cli/bench callers don't need the
> rewire — the new substrate is opt-in.
>
> **Invariant: see I41 below** — pins all 8 gameplay shuffle sites
> as consumers of the `external_rng` substrate.
>
> **Out of scope (per the playbook).** G19
> (SearchLibraryForBasicLandTapped no-shuffle in the
> `state_ops_resolve.rs` Effect arm) shares the substrate but is a
> separate one-Effect-arm slice; CE8 closure leaves G19 open.
>
> **Numbering note.** CE7 above is the inline-vs-pymethod asymmetry;
> CE9 is intentionally left unallocated for the next surfacing
> slice. See the staging doc
> `docs/PENDING_CE_FILINGS_2026_05_11.md` (merge `50eb79ea`) for
> the reconciliation history — the is_over closure pre-empted the
> staging doc's proposed CE7 and took CE10 instead, so this
> finding shifts from staged-CE9 to filed-CE8.

### I41. All 8 gameplay shuffle sites accept an external `rng` parameter and consume Fisher-Yates draws from the caller-supplied Python `random.Random` via `external_rng::next_below`

Post-CE8 (Slice 1 + Slice 2), every Rust gameplay shuffle entry
takes an optional `rng: Option<&Bound<'_, PyAny>>` kwarg. When
`Some(_)`, the in-loop draw source is
`crate::external_rng::next_below(py_rng, n)` — a callback to the
Python `random.Random._randbelow(n)` primitive that matches
exactly what `random.Random.shuffle(list)` consumes. The control
flow is the standard `for i in (1..n).rev() { swap(i, j) }`
Fisher-Yates loop; only the source of `j` differs between the
external-rng path and the legacy xorshift64 fallback.

The 8 consumer sites:

| # | File | Method | CR backing |
|---|---|---|---|
| 1, 2 | `state_ops_setup.rs` | `make_state` (p0 + p1 setup shuffle) | CR 103.4 / 701.20 |
| 3 | `state_ops_library.rs` | `shuffle_library_with_seed` | CR 701.20 |
| 4 | `state_ops_library.rs` | `search_library_and_move_to_hand` (post-search shuffle) | CR 701.18 |
| 5 | `state_ops_library.rs` | `search_library_for_first_of_type_and_shuffle` | CR 701.19 |
| 6 | `state_ops_mulligan.rs` | `mulligan` (in-mulligan shuffle) | CR 103.4 |
| 7 | `state_ops_mulligan.rs` | `mulligan_to_n` | CR 103.4 |
| 8 | `state_ops_mulligan.rs` | `mulligan_atomic` | CR 103.4 |

Slice 2 added a shared `fisher_yates_shuffle_optional(v, rng, seed)`
helper in each of `state_ops_library.rs` and `state_ops_mulligan.rs`
that dispatches between the external rng path (when `rng.is_some()`)
and the legacy xorshift64 path (when `rng.is_none()`). Slice 1's
setup-shuffle uses a closely-related shape (a paired free function
+ inline branch in `make_state`). A future housekeeping slice can
consolidate the three xorshift64 struct copies into a shared
`rng_internal` module — not required for the closure.

**Backward compat:** the `rng=None` (or omitted) path is the
xorshift64 fallback, byte-equivalent to pre-Slice-1 behavior.
Production callers (cli, bench) don't pass `rng=` and stay on the
xorshift64 path; only the parity harness and the cross-engine smoke
tests opt into the external-rng path.

**Pinned by**:
`tests_rust/test_setup.py` (10 external-rng cases per Slice 1),
`tests_rust/test_library.py` (10 external-rng cases per Slice 2),
`tests_rust/test_mulligan.py` (7 external-rng cases per Slice 2),
`tests/test_parity_smoke_edge_cases.py` (3 Slice 1 cross-engine
smoke tests + 7 Slice 2 cross-engine smoke tests pinning each
rewired site against Python's MT reference).

**Out of scope (carry-forwards):**

- ~~**G19**~~ — closed by `feature/g19-search-shuffle`. The
  `Effect::SearchLibraryForBasicLandTapped` arm in
  `state_ops_resolve.rs` now shuffles per CR 701.19 / 701.22 via
  an inlined xorshift64 Fisher-Yates. The arm did NOT join the
  external_rng substrate — Effect resolution doesn't currently
  thread an `rng` through `apply_effect`, so the post-search
  shuffle is xorshift64-only. Cross-engine MT parity for this
  one Effect is a follow-up Effect-rng-threading slice. See
  invariant I42 + the SEARCH_LIMITATIONS follow-up entry.
- **xorshift64 struct deduplication** — three identical
  `XorShift64` struct copies remain (one per file: setup, library,
  mulligan); G19 added an inline xorshift64 in `state_ops_resolve.rs`
  too, technically a fourth occurrence (open-coded, not a struct).
  Consolidating into `rust/src/rng_internal.rs` is a housekeeping
  follow-up; not load-bearing for parity.

### I42. `Effect::SearchLibraryForBasicLandTapped` shuffles the library after the search per CR 701.19 / 701.22

Post-`feature/g19-search-shuffle` (this closure), the
`Effect::SearchLibraryForBasicLandTapped` resolve arm in
`rust/src/state_ops_resolve.rs::apply_effect` Fisher-Yates shuffles
the active player's library after all `count` picks have landed
(or after the early-`break` on no-more-basic-lands). Honors CR
701.19 / 701.22's "always shuffle after search" invariant
regardless of search outcome.

**Shuffle path: inlined xorshift64 only.** Unlike the 8 pymethod
shuffle sites covered by I41, this Effect arm doesn't yet consume
the external_rng substrate — `apply_effect` lacks the `rng`
parameter that would thread it through, and adding it touches every
intervening call site (`resolve_top_of_stack`,
`resolve_top_of_stack_pause`, `apply_effect_pub`,
`auto_resolve_pending_decisions`, plus every test surface). The
inlined xorshift64 path seeds off
`(turn_number, active_player, source_obj_id, library_len)` mixed
through the golden-ratio constant `0x9E3779B97F4A7C15` — stable
across reruns of the same starting state, distinct enough across
back-to-back resolutions in one game that the same library doesn't
get the same permutation twice.

**Pinned by**:
- `tests_rust/test_resolve.py::test_resolve_search_library_for_basic_land_tapped_shuffles_library`
  — asserts post-resolve library is NOT the sequential identity
  permutation the no-shuffle path would have produced.
- `tests_rust/test_resolve.py::test_resolve_search_library_for_basic_land_tapped_shuffle_is_deterministic`
  — asserts two clone-equal starting states produce the same
  post-search library permutation (seed derivation is pure-state).

**Cross-engine MT parity for this Effect was deferred and is now
closed.** The `feature/effect-rng-threading` slice extended the I41
substrate to this arm via `GameState.rng: Option<Py<PyAny>>` (Option
A from `docs/RUST_EFFECT_RNG_AUDIT.md` §4). When the caller installs
a `random.Random` via `set_external_rng`, the post-search Fisher-
Yates reads draws via `external_rng::next_below`, producing byte-
identical permutations to `random.Random.shuffle(list)` on the
Python side. When unset (production cli / bench), the xorshift64
path above runs unchanged. See invariant I43 below for the
`GameState.rng` lifecycle contract.

- **Pinned by**:
  `tests/test_parity_smoke_edge_cases.py::test_cross_engine_shuffle_seed_walks_clean`
  (line 401, strict-xfail) for the clean-walk pin at step 0.
  Companion passing pin
  `test_cross_engine_shuffle_seed_surfaces_library_divergence_for_multiple_seeds`
  (line 427) confirms the divergence shape across seeds 1, 7, 42, 100.
- **Surfaced by**: Phase-5 edge-case probe round (`c4dd5d5a`).
  `slightly_bigger_deckspec` with `shuffle_seed=42` builds matched
  states; the initial-state field view diverges on `library_p0` and
  `library_p1` at step 0 (before any decision is applied).
  Reproducible per-seed: the same seed produces the same Python
  permutation and the same Rust permutation, just different from
  each other.
- **Rust today**: Rust's shuffle (called internally during
  `make_state` when `shuffle_seed` is set, plus in
  `Effect::ShuffleLibrary` and friends) uses a xorshift64 PRNG,
  chosen for its small footprint and reproducibility within Rust's
  own gate. The same seed that produces permutation P_py on
  Python's `random.Random` produces permutation P_rust on Rust's
  xorshift64; P_py ≠ P_rust except by birthday-style accident.
- **CR / Python expected**: CR 103.4 / 701.20 mandate that the
  library is randomized; the CR is silent on WHICH PRNG the engine
  uses. The parity reference is "Python's Mersenne Twister output
  for any given seed" because the cross-engine smoke contract pins
  Python as the parity source-of-truth for observable state (per
  `RUST_PARITY_PLAN` Decision 1).
- **Impact**: medium. Does NOT block real-game play (each engine's
  internal randomization is sound). DOES block cross-engine smoke
  at any spec that sets a non-`None` `shuffle_seed`. The harness
  sidesteps this today by defaulting `shuffle_seed=None` (no initial
  shuffle); every other Phase-5 cross-engine test relies on that
  default. Also blocks closure of G19 (the
  SearchLibraryForBasicLandTapped no-shuffle gap) because both gaps
  share the RNG-externalization closure path.
- **Closeable**: yes — three-option closure (mirrors the
  `RUST_PARITY_PLAN.md` Decision 1 options):
  1. **Rust adopts Mersenne Twister.** Port MT19937 into Rust
     (existing crate `rand_mt` or a vendored impl) and route every
     `shuffle_deck` site through it. Largest surface; ties Rust to
     a specific Python implementation detail.
  2. **Both engines accept an external RNG stream.** Add a
     `seed_bytes` (or `pre_shuffled_indices`) parameter to
     `make_state` on both sides; the harness pre-computes the
     shuffle on one side (e.g. Python) and feeds the result to the
     other (via the parameter). Decouples engines from PRNG choice;
     matches the `RUST_PARITY_PLAN` Decision 1 option (b). Medium
     surface. Also closes G19 because the
     SearchLibraryForBasicLandTapped Rust arm can consume the same
     external stream to mirror Python's shuffle behavior.
  3. **Harness disables shuffle entirely.** Force `shuffle_seed=None`
     on every cross-engine spec; the strict-xfail flips by removing
     the test. Lowest cost but does not close G19 and leaves real
     shuffles untested cross-engine.

  Recommendation per the retro doc's "Honorable mentions" (RNG
  externalization gates CE8 + G19 + many search-library Effects):
  Option 2 is the architecturally correct shape but is a substrate
  slice; schedule when CE5 (cast-vs-resolve) closure lands and the
  cadence has room for substrate work.

### I43. `GameState.rng` — caller-owned external rng for in-Effect shuffles; set via `set_external_rng`, consumed by `Effect::SearchLibraryForBasicLandTapped`, NOT serialized into fingerprint, clone-preserved via manual `Clone` impl

Post-`feature/effect-rng-threading` (this slice), `GameState`
carries an `rng: Option<Py<PyAny>>` field with the following
lifecycle contract:

**Set / clear surface.** The
`GameState.set_external_rng(rng: Option<&Bound<'_, PyAny>>)`
pymethod installs (or clears) the rng. Caller-owned: the parity
harness and cross-engine smoke tests opt in once per game by
passing a Python `random.Random` instance; production cli / bench
callers leave it unset and stay on the xorshift64 fallback.

**Consumer surface.** Today the only consumer is
`Effect::SearchLibraryForBasicLandTapped`'s post-search Fisher-
Yates (see I42). The arm reads `state.rng_ref()` immediately
before the in-arm shuffle loop; on `Some(_)`, the loop swaps
indices drawn via `crate::external_rng::next_below(py_rng, n)`
(byte-identical to `random.Random.shuffle(list)`'s
`_randbelow(n)` consumption shape). On `None`, the legacy
xorshift64 fallback runs. Additional Effect arms that grow rng
consumers (the deferred-shuffle `Effect::SearchLibraryForCard`
per `docs/RUST_EFFECT_RNG_AUDIT.md` §5 E2; any future "random
discard" / "random ordering" Effects) plug into the same
substrate by reading `state.rng_ref()` at their resolve site.

**NOT serialized into the fingerprint.** Like `mulligan_count`,
`consecutive_passes`, `next_etb_timestamp`, and
`winner_id_sticky`, the rng field is bookkeeping state, not
gameplay-relevant state. Two `GameState`s with the same
observable shape produce identical fingerprints regardless of
whether/which `random.Random` is stashed on either of them. Pinned
baselines stay bit-equal — production pinned-fingerprint tests
that never call `set_external_rng` see no shift, and a test that
DOES call `set_external_rng` followed by no shuffle-consuming
Effect also sees no shift.

**Clone semantics.** `GameState` ships a manual `Clone` impl
(rather than `#[derive(Clone)]`) because PyO3 0.23's
`Py<T>::Clone` requires the `py-clone` feature, which globally
panics any clone-without-GIL site — too sharp an edge for a struct
that already clones cheaply at MCTS rates. The manual impl
explicitly enters `Python::with_gil` and `clone_ref`s the stashed
rng (Python refcount bump). All `GameState::clone` call sites
today run under the GIL (every pymethod entry, plus the implicit
clones in fingerprint paths), so the GIL acquisition is a no-op
token-handoff at runtime.

**Two clones share the SAME `random.Random` instance.** This is
correct for the cross-engine smoke use case (one rng per game,
consumed by both engines); MCTS-style search-tree forking that
needs independent rng streams must `set_external_rng(None)` on
the forked branch.

**Pinned by**:
- `tests_rust/test_resolve.py::test_resolve_search_library_for_basic_land_tapped_external_rng_matches_python_shuffle`
  — Effect arm consumes from the stashed rng on resolve.
- `tests_rust/test_resolve.py::test_resolve_search_library_for_basic_land_tapped_external_rng_none_falls_back_to_xorshift`
  — `set_external_rng(None)` is byte-equivalent to never setting.
- `tests_rust/test_resolve.py::test_resolve_search_library_for_basic_land_tapped_external_rng_differs_from_xorshift`
  — external rng path produces a distinct permutation from
  xorshift64.
- `tests_rust/test_resolve.py::test_resolve_search_library_for_basic_land_tapped_external_rng_preserved_across_clone`
  — clone preserves the rng reference.
- `tests_rust/test_resolve.py::test_resolve_search_library_for_basic_land_tapped_external_rng_clone_isolation`
  — clones share the rng instance (consecutive draws).
- `tests/test_parity_smoke_edge_cases.py::test_cross_engine_search_library_for_basic_land_tapped_external_rng_matches_python_mt`
  — cross-engine MT byte-for-byte parity under shared rng.
- `tests/test_parity_smoke_edge_cases.py::test_cross_engine_search_library_for_basic_land_tapped_shared_rng_walks_clean_for_multiple_seeds`
  — multi-seed robustness companion.

### I44. Mutual-KO end-state matches cross-engine after two `lose_life` calls + `apply_sbas_until_quiescent` (G12 closure)

- **Pinned by**:
  - `tests_rust/test_winloss.py::test_mutual_zero_via_sequential_lose_life_is_draw`
    (Rust-side end-state pin),
  - `tests_rust/test_winloss.py::test_mutual_zero_cross_engine_end_state_matches_python`
    (cross-engine, simultaneous variant),
  - `tests_rust/test_winloss.py::test_mutual_zero_cross_engine_sequential_variant_matches_python`
    (cross-engine, sequential variant),
  - `tests/test_parity_smoke.py::test_cross_engine_retaliation_selector_walks_clean`
    (integration: 260-decision bilateral combat walk that already
    exercised the SBA-gated outcome layer through end-of-game).

- **Invariant (closes G12)**. With two `lose_life(p_i, n_i)` calls
  sufficient to drive both players to `life <= 0` followed by
  `apply_sbas_until_quiescent`, both engines reach the IDENTICAL
  observable end-state:
  - `sorted(losers()) == [0, 1]`
  - `winner_id` is `None` (simultaneous variant — both `has_lost`
    flip in one SBA pass, sticky-write gate skips per I34's
    `(true, true)` branch) OR equal to the survivor's id
    (sequential variant — first SBA pass observes alive=1,
    sticky-writes the survivor; second SBA pass observes alive=0
    but the I34 write-once gate preserves the sticky).
  - `is_draw == True` (both `has_lost == True`).
  - `is_over()` / `is_game_over()` == `True`.

  The "which variant fires" branch is driven by how many `apply_sbas`
  passes the caller interleaves between the two `lose_life` calls:
  zero interleavings (both `lose_life` first, then SBA) -> sim
  variant; one interleaved SBA pass (`lose_life(p0)` -> SBA ->
  `lose_life(p1)` -> SBA) -> sequential variant. Both branches
  are bit-equal across engines.

- **Why the original substrate "gap" is closeable without a new
  Effect**: neither engine has a single Effect that hits both
  players atomically, but neither does REAL MTG: per CR 704.5a,
  state-based actions are checked simultaneously when a player
  would receive priority, so the simultaneous-loss observation
  point is the SBA pass itself — not the Effect resolution. Two
  back-to-back `lose_life(p, n)` writes to `players[i].life`
  followed by ONE `apply_sbas_until_quiescent` puts the SBA-gated
  outcome layer in the same shape as a hypothetical single
  symmetric Effect would. The CE12 sticky-winner closure pinned
  this observation-point invariant; the G12 closure makes it
  load-bearing on the cross-engine surface.

- **NOT a parity-substrate claim about Effects themselves.** If a
  future EoE printing actually requires a symmetric two-player
  `LoseLife` Effect (e.g. "each player loses N life" punisher),
  that's a new Effect variant to add to both engines, with a new
  G-entry tracking the substrate work. The Effect-level addition
  doesn't change THIS invariant — both engines would still route
  through the SAME `players[i].life` mutation + SBA pass,
  preserving the end-state shape pinned here. G12 is closed at
  the OBSERVABLE-END-STATE layer; the Effect-vocabulary layer is
  a separate scope.

- **Cross-reference**:
  - **I34** — the CE12 sticky-winner closure that makes
    `winner_id` / `is_over` / `is_draw` SBA-gated and pins the
    simultaneous-vs-sequential bilateral-kill branches.
  - **I7** — `apply_sbas_until_quiescent` is a no-op after
    game-over (so calling SBA again after the mutual-KO
    transition doesn't flip outcomes).
  - **I19** — the foundational empty-library SBA-driven loss
    transition; mutual-KO via empty libraries follows the same
    apply_sbas-gated shape.

### I45. Double-strike regular-substep damage spills to the defending player when the attacker's only blocker died in the first-strike substep (CE18 closure)

- **Pinned by**:
  - `tests/test_parity_smoke.py::test_cross_engine_double_strike_selector_walks_clean`
    (200-decision cross-engine clean-walk pin on
    `multi_blocker_deckspec` + `double_strike_selector`, formerly
    the CE18 strict-xfail walks_clean pin, now expected-pass).
  - `tests_rust/test_combat.py::test_double_strike_regular_damage_spills_to_defender_when_sole_blocker_dies_fs`
    (Rust-side direct synthetic-state pin: 2/2 DS attacker + 1 vanilla
    blocker → defender life drops 20 → 18 after combat damage).
  - `tests_rust/test_combat.py::test_double_strike_regular_damage_does_not_spill_when_other_blocker_alive`
    (negative-branch pin: 3/3 DS attacker + 2 blockers, only the
    first dies in FS → no spillover to defender; the entry on the
    dead blocker is DROPPED, not redirected).
  - `tests_rust/test_combat.py::test_double_strike_vs_larger_blocker_mutual_death_no_spillover_regression`
    (regression: blocker survives FS → regular entry stays on the
    blocker, NOT redirected).
  - `tests_rust/test_combat.py::test_double_strike_unblocked_full_damage_to_defender_regression`
    (regression: player-target entries unaffected by the filter).
  - `tests_rust/test_combat.py::test_double_strike_attacker_kills_blocker_in_first_strike_step`
    (existing test, updated at closure to assert defender life drops
    on the sole-blocker-dies-in-FS scenario).

- **Invariant** (closes CE18, per Phase 5 "converge Rust toward
  Python, never modify Python, regardless of CR-correctness"). In
  `state_ops_combat.rs:deal_combat_damage`, when the two-pass
  first-strike / double-strike timing kicks in and the pass-2
  alive-predicate filter rejects an entry with
  `target = DamageTarget::Creature(target_id)` because the target
  died in pass 1:

  - **If the entry's `source_id` is in `self.attackers` AND
    the source has no remaining alive blockers** (computed by
    counting `(att_id, blk_id) in self.blockers` rows whose
    `blk_id` still satisfies `battlefield_creature_alive`), the
    entry is **redirected** to
    `DamageTarget::Player(defending_player)` (= `1 - active_player`),
    preserving `amount` and `pass`.
  - **If the entry's `source_id` is in `self.attackers` AND the
    source still has ≥1 alive blocker**, the entry is **dropped**
    (the surviving blocker(s) have their own assignments — no
    spillover).
  - **If the entry's `source_id` is a blocker** (back-damage entry
    whose attacker target is now dead), the entry is **dropped**
    (back-damage doesn't redirect anywhere — the blocker has a
    single attacker target by construction; once it's dead, the
    second-strike back-damage is wasted).
  - Player-target entries are **never** filtered (a
    `DamageTarget::Player(_)` entry passes through unchanged).
  - Source-alive filter (filter (a)) still gates: a source that
    took lethal damage in pass 1 doesn't strike back, including
    DS sources that fell in pass 1 (they don't get a second
    strike).

  This mirrors Python's per-substep `_resolve_damage_step` shape,
  where `combat.py:389,405` rebuilds the attacker's `blockers` list
  freshly each substep (`[o for o in state.battlefield if o.id in
  attacker.blocked_by]`) and `combat.py:413`'s `if not blockers:`
  branch routes to the defending player.

- **Why this is a parity invariant, NOT a CR-correctness claim.**
  CR 702.4 + CR 510.1h say a creature stays blocked even if all
  its blockers leave the battlefield mid-combat; without trample,
  the attacker's remaining damage is wasted. Python's behavior is
  CR-divergent (over-permissive: routes damage to the defender
  that should be wasted). Phase 5 convention overrides
  CR-correctness — Rust converges on Python. A future global
  Python-side fix (rewrite `combat.py:413` to NOT route to
  defender when `attacker.blocked_by` is non-empty even if its
  current battlefield-residents are dead) would let Rust ALSO drop
  the redirect, but that's a separate scope (tracked as a
  follow-up; the Phase 5 reference is Python today).

- **Cross-reference**:
  - **I32** — `state.resolving_combat_damage_amount` set/reset
    per damage event, including redirected entries (the redirect
    preserves `amount`, so the slot's value at apply time is
    correct on either branch).
  - **CE9** — bf-ETB-ordered blocker iteration, which feeds the
    attacker_blocker_ids set the redirect map is keyed against.
  - **CE14 / CE15** — the multi-blocker damage assignment walks
    that decide which blockers receive how much damage in pass 1
    (the inputs to the redirect's "are any blockers still alive"
    check).

### I46. `legal_decisions` emits CastSpell at instant-speed windows + honors flash keyword via per-card timing gate above the sorcery-timing short-circuit (CE19 closure)

- **Pinned by**:
  - `tests/test_parity_smoke.py::test_cross_engine_flash_test_a_closes_ce19`
    (cross-engine both-engines-agree pin: p0 has Bear Flash in hand
    at p1's PRECOMBAT_MAIN with priority on p0 →
    `set(py_cast_card_ids) == set(rust_cast_card_ids)` AND the
    flash card's id is in both sets; formerly the CE19 strict shape-
    pin asserting "Rust does NOT emit", now expected-pass equality).
  - `tests/test_parity_smoke.py::test_cross_engine_flash_test_b_own_turn_main_phase_parity`
    (cross-engine sanity: both engines emit CastSpell for the flash
    creature at own-turn main phase — sorcery timing OR flash
    keyword, either branch fires).
  - `tests/test_parity_smoke.py::test_cross_engine_flash_test_c_vanilla_off_turn_negative_parity`
    (cross-engine over-correction guard: neither engine emits
    CastSpell for a vanilla creature at the off-active priority
    window).
  - `tests_rust/test_legal.py::test_legal_decisions_flash_creature_off_active_turn_emits_cast_spell_ce19`
    (Rust-only direct synthetic-state pin: Bear Flash injection at
    p1's PRECOMBAT_MAIN + priority=p0 + `legal_decisions(0)` emits
    CastSpell for the flash card).
  - `tests_rust/test_legal.py::test_legal_decisions_flash_creature_own_turn_emits_cast_spell`
    (Rust-only own-turn pin: also asserts the no-double-emission
    invariant via the shared `seen_castspell` HashSet —
    `cast_ids.count(bear_flash_id) == 1`).
  - `tests_rust/test_legal.py::test_legal_decisions_vanilla_creature_off_active_turn_omits_cast_spell_ce19`
    (Rust-only over-correction guard: vanilla creature at off-
    active priority window → emission collapses to `[pass_priority]`).
  - `tests_rust/test_legal.py::test_legal_decisions_instant_off_active_turn_emits_cast_spell_ce19`
    (Rust-only `is_instant`-arm pin: printed Instant at off-active
    priority window → CastSpell emitted via the is_instant clause,
    distinct from the flash-keyword arm).

- **Invariant** (closes CE19, per Phase 5 "converge Rust toward
  Python, never modify Python"). In `state_ops_legal.rs::
  GameState::legal_decisions`, the CastSpell emission is split into
  TWO passes sharing a single `seen_castspell` HashSet keyed on
  `printing.name`:

  1. **Instant-speed pass** lives ABOVE the sorcery-timing short-
     circuit. Walks the priority holder's hand and emits a
     CastSpell for any card where
     `printing.card_types.contains("Instant") ||
     printing.keywords.contains("flash")`. Land cards are filtered
     (CR 305.1 — lands play as a special action, not a cast). Runs
     regardless of `is_sorcery_timing`; this is the load-bearing
     change vs pre-closure where the entire CastSpell block lived
     below the sorcery-timing return.
  2. **Sorcery-timing gate**: if `is_sorcery_timing` is false
     (`active != priority` OR `phase ∉ {MAIN1, MAIN2}` OR stack non-
     empty), return here with PassPriority + DeclareAttackers /
     DeclareBlockers + instant-speed CastSpell emissions already
     pushed.
  3. **PlayLand emission** (unchanged from pre-closure).
  4. **Sorcery-speed CastSpell pass** runs AFTER PlayLand. Filters
     out Lands, Instants, AND flash-keyword cards (the same `flash`
     guard Python's `legal.py:366` applies, plus the
     `_is_sorcery_speed_spell` check at lines 339-345 that excludes
     Instants). The shared `seen_castspell` HashSet would dedup the
     overlap anyway (a flash card already emitted instant-speed
     hits the set on its second visit and skips), but the explicit
     filter mirrors Python's filter shape one-to-one.
  5. **ActivateAbility emission** (unchanged from pre-closure).

  The per-card timing gate at the unified emission level is
  `is_instant || keywords.contains("flash") || is_sorcery_timing`
  — restated structurally as two loops + shared HashSet so the
  emission order respects Python's instant-speed-before-PlayLand-
  before-sorcery-speed ordering, not just the membership shape.

- **Emission order** at sorcery timing: `[PassPriority,
  (DeclareAttackers...), (DeclareBlockers...),
  CastSpell(instant/flash)..., PlayLand..., CastSpell(sorcery)...,
  ActivateAbility...]`. At non-sorcery-timing: `[PassPriority,
  (DeclareAttackers...), (DeclareBlockers...),
  CastSpell(instant/flash)...]` only — the function returns at
  step 2. Matches Python's natural append order in `legal.py:178
  → 217-301 → 303 (gate) → 319-329 → 335-445 → 612-829`.

- **CR backing**:
  - **CR 117.1 + 307.1** — instants may be cast any time the player
    has priority (the `is_instant` clause).
  - **CR 702.13a** — flash is a static ability that lets the spell
    be cast any time the player could cast an instant (the
    `"flash" in keywords` clause).
  - **CR 305.1** — lands play via a special action, not via the
    stack; never CastSpell.
  - **CR 117.1c** (Python `_is_sorcery_timing` at `legal.py:25-32`)
    — sorcery-speed actions require active player = priority +
    main step + empty stack.

- **Why two loops, not one with a unified per-card gate**. A single
  loop with `if !(is_instant || has_flash || is_sorcery_timing)
  continue` would emit ALL eligible cards before PlayLand at
  sorcery timing — putting sorcery-speed creature emissions ahead
  of PlayLand in the action list. Python's order at sorcery timing
  is `[PassPriority, (instant-speed casts), PlayLand, (sorcery-
  speed casts)]` — the two-pass shape with PlayLand between them
  preserves this exactly. Four pre-existing test_legal.py emission-
  order pin tests (`...cast_spell_after_play_land...`,
  `...land_plus_creature_emit_in_python_order`,
  `...activate_ability_emission_order_after_cast_spell`,
  `...all_four_emission_kinds_present_in_priority_order`) lock the
  order; the two-pass implementation passes all of them while a
  unified single loop did not.

- **Cross-reference**:
  - **CE19** — the gap this invariant closes.
  - **I40** — companion `legal_decisions` enumeration-time filter
    (defender keyword for DeclareAttackers eligibility); same
    "filter at enumeration time, not just at apply time" shape.
  - Module docstring `rust/src/state_ops_legal.rs` "CastSpell
    extension" section — updated to the post-closure shape (was
    "Future slices add the instant-speed window by moving the
    CastSpell loop ABOVE the sorcery-timing return"; now describes
    the shipped two-pass form).

### I47. Every bf-entry ETB-stamping site fans out `Event::Enters` via the `pending_etb_dispatches` deferred-dispatch queue + a `drain_pending_etb_dispatches` post-pop drainer (Slice 2 of ETB-trigger closure)

- **Pinned by**:
  - `tests_rust/test_triggers.py::test_rs2_search_library_for_basic_land_tapped_fires_etb`
    (RS2 — Cultivate-shape search-and-bf arm).
  - `tests_rust/test_triggers.py::test_rs3_reanimation_fires_etb`
    (RS3 — `Effect::ReturnCreatureFromYourGraveyardToBattlefield`).
  - `tests_rust/test_triggers.py::test_rs4_create_token_fires_etb_per_token`
    (RS4 — `Effect::CreateToken` block allocator, one ENTERS per
    token in stamp order).
  - `tests_rust/test_triggers.py::test_rs5_create_token_copy_fires_etb`
    (RS5 — `Effect::CreateTokenCopyOfTargetCreatureYouControl`,
    observed via a Panharmonicon-shape "always" witness).
  - `tests_rust/test_triggers.py::test_rs6_mass_reanimation_fires_etb_per_creature`
    (RS6 — `Effect::ReturnAllCreaturesFromYourGraveyardToBattlefield`,
    one ENTERS per reanimated creature in stamp order).
  - `tests_rust/test_triggers.py::test_rs7_paired_exile_recall_fires_etb`
    (RS7 — `return_paired_exiles_for(source_id)` pymethod, plus
    the `i32 -> PyResult<i32>` signature flip pin).
  - `tests_rust/test_triggers.py::test_rs8_register_and_inject_battlefield_fires_etb`
    (RS8 — `register_and_inject_object` test fixture battlefield
    injection now fires ENTERS).
  - `tests_rust/test_triggers.py::test_rs9_move_object_to_battlefield_fires_etb`
    (RS9 — `move_object(_, ZONE_BATTLEFIELD, _)` generic mover).
  - `tests_rust/test_triggers.py::test_rs9_move_object_to_hand_does_not_fire_etb`
    (RS9 over-correction guard — non-bf targets stay silent).
  - `tests_rust/test_triggers.py::test_rs10_move_object_from_graveyard_fires_etb`
    (RS10 — `move_object_from_graveyard_to_battlefield` reanimation
    primitive).
  - `tests_rust/test_triggers.py::test_rs11_play_land_fires_etb`
    (RS11 — `play_land` no-stack path via
    `move_from_hand_to_battlefield`).
  - `tests_rust/test_triggers.py::test_rs12_manifest_dread_fires_etb`
    (RS12 — `resolve_manifest_dread_to_battlefield` pending-
    decision submit path).
  - `tests_rust/test_triggers.py::test_once_per_turn_ledger_suppresses_repeat_fires`
    (end-to-end: a `once_per_turn=True` observer fires on its own
    RS8 injection, gets suppressed on a subsequent RS10
    reanimation entry, and fires again after
    `cleanup_step_for_active_player` clears the ledger).

- **Invariant**. Every site that stamps an `etb_timestamp` and
  pushes a `GameObject` onto a player's `battlefield` (12 sites
  catalogued in `docs/RUST_ETB_TRIGGER_AUDIT.md` §4) routes its
  ENTERS dispatch through the shared
  `GameState.pending_etb_dispatches: Vec<u32>` queue. After the
  bf-push, the site appends the entered permanent's id to the
  queue; the surrounding "resolving slot owner" then calls
  `state_ops_resolve::drain_pending_etb_dispatches(state)` which
  loops `dispatch_event(Event::Enters, id)` per queued id until
  the queue is empty (re-entrant: a dispatch's trigger effect
  can re-fill the queue, the loop picks the new ids up).

- **Why deferred (not inline) dispatch**. Effect arms can mutate
  the stack mid-resolution (`Effect::CounterTargetSpell` removes a
  stack item; future trigger-from-trigger paths push more
  triggers). Dispatching ENTERS inline from inside `apply_effect`
  would pile a fresh trigger on top of the resolving spell's stack
  item, breaking the resolver's `pop()` "pop the resolving slot"
  invariant (the freshly-pushed trigger would be popped instead
  of the resolving slot). The deferred-queue pattern keeps
  `apply_effect` stack-quiet and gives the resolver a clean pop;
  the drainer fires after the resolving slot leaves the stack.

- **RS-site → owner site map** (`docs/RUST_ETB_TRIGGER_AUDIT.md`
  §4 IDs):

  | RS  | Effect / primitive                                        | Drain site                                            |
  |-----|-----------------------------------------------------------|-------------------------------------------------------|
  | RS1 | cast-resolve via `resolve_top_of_stack` (Slice 1)         | `resolve_top_of_stack` + `_pause`                     |
  | RS2 | `Effect::SearchLibraryForBasicLandTapped`                 | `resolve_top_of_stack` (drain via spell-resolve path) |
  | RS3 | `Effect::ReturnCreatureFromYourGraveyardToBattlefield`    | `resolve_top_of_stack` (spell-resolve)                |
  | RS4 | `Effect::CreateToken` block allocator                     | `resolve_top_of_stack` (spell-resolve)                |
  | RS5 | `Effect::CreateTokenCopyOfTargetCreatureYouControl`       | `resolve_top_of_stack` (spell-resolve)                |
  | RS6 | `Effect::ReturnAllCreaturesFromYourGraveyardToBattlefield`| `resolve_top_of_stack` (spell-resolve)                |
  | RS7 | `return_paired_exiles_for(source_id)` pymethod            | `return_paired_exiles_for` itself                     |
  | RS8 | `register_and_inject_object` (test fixture)               | `register_and_inject_object` itself                   |
  | RS9 | `move_object(_, ZONE_BATTLEFIELD, _)` generic mover       | `move_object` itself                                  |
  | RS10| `move_object_from_graveyard_to_battlefield`               | `move_object_from_graveyard_to_battlefield` itself    |
  | RS11| `move_from_hand_to_battlefield` (play_land, cast_creature)| `move_from_hand_to_battlefield` itself                |
  | RS12| `resolve_manifest_dread_to_battlefield`                   | `resolve_manifest_dread_to_battlefield` itself        |

- **Drain order — FIFO**. Per-arm-collected ids land in the queue
  in ETB-stamp order (the order the arm pushed them onto the
  battlefield). The drainer iterates in queue-push order so the
  ETB-stamp order = ENTERS-fire order, mirroring Python's
  centralized `state.battlefield` walk inside its per-permanent
  `put_into_battlefield -> _trigger_etb_abilities` loop.

- **Re-entrancy bound**. Finite by construction — each dispatch
  can only re-push ids for permanents that are actually moved onto
  the battlefield by a triggered effect, and the registry / Effect
  vocabulary today caps that at a small per-resolution number.
  The drain loop terminates when an iteration produces an empty
  `mem::take` output.

- **Once-per-turn ledger** (Slice 1 substrate, end-to-end pinned
  in Slice 2 by `test_once_per_turn_ledger_suppresses_repeat_fires`):
  triggers flagged `once_per_turn = true` consult
  `state.triggered_this_turn: HashSet<(source_id, ability_index)>`
  before push; matched-set entries are suppressed. The ledger is
  cleared at `cleanup_step_for_active_player` so the gate re-opens
  each turn.

- **CR backing**:
  - **CR 603.6a** — triggered abilities fire when their event
    occurs; the deferred-dispatch queue is the rust equivalent of
    Python's centralized `dispatch_event`.
  - **CR 603.3b** — APNAP ordering of simultaneous triggers
    (deliberately simplified — same shape as Python; documented
    in `docs/SEARCH_LIMITATIONS.md` and audit §2.5).

- **Out of scope for Slice 2** (queued for Slice 3+):
  - ~~Bridging legacy `etb_effects: Vec<Effect>` into the predicate
    path~~ — **closed by Slice 3 — see I49.** The parse-time
    synthesis + inline-loop retirement landed together, so a
    printing carrying `etb_effects` now fires the same effect via
    the predicate-path dispatcher (no double-fire surface).
  - ~~Smoke-harness `cross_engine.py` registry-dict wiring for the
    `triggered_abilities` key.~~ — **closed by Slice 3 — see I49.**
    `CardDef.triggered_abilities` ports through both
    `build_python_state` and `build_rust_state`.
  - Richer Predicate variants (HasSubtype, IsLand, IsArtifact,
    Controlled, Subject).
  - Wider Event variants (Dies, Cast, Attacks, DealsDamage).
  - Panharmonicon-shape `etb_trigger_multiplier`.

### I48. `CardPrinting.activated_abilities` substrate — cost-paying activated abilities walk through a per-ability `ActivatedAbility { cost, effect, is_mana_ability }` Vec; `legal_decisions` emits per-ability when affordable + untapped (tap_self) + non-sick (creature tap_self), and the `ActivateAbility` apply arm dispatches by index, pays mana via `state_ops_cast::pay_mana_cost_pub`, taps the source for `tap_self`, and pushes a `StackItem` for `is_mana_ability=false` (CE20 Slice 1 closure)

- **Pinned by**:
  - `tests/test_parity_smoke.py::test_cross_engine_activated_cost_test_a_emission_parity_post_ce20_closure`
    (emission-side both-engines-agree pin: Bear Caster `{1}{G}, T:
    Draw a card` emits ActivateAbility identically on Python and
    Rust when p0's pool covers the cost).
  - `tests/test_parity_smoke.py::test_cross_engine_activated_cost_test_c_apply_dispatch_parity_post_ce20_closure`
    (dispatch-side both-engines-agree pin: apply succeeds on both
    engines; post-state convergence on Bear-tapped + pool drained
    of `{1}{G}` + stack carries the draw effect).
  - `tests/test_parity_smoke.py::test_cross_engine_activated_cost_test_d_python_underpays_silently`
    (subtler-axis pin: Python's `_activate_ability` primitive
    doesn't self-gate on affordance, Rust's apply arm DOES;
    unaffordable cost raises `"unaffordable from controller's mana
    pool"` on Rust while Python silently under-pays through
    `auto_tap_for_cost`).
  - 12 `tests_rust/test_activated.py` substrate pins (parser
    surface + Bear Caster apply path + emission gate).

- **Invariant**. `CardPrinting.activated_abilities:
  Vec<ActivatedAbility>` is the canonical Rust-side representation
  for cost-paying activated abilities. Each entry carries:
  - `cost: ActivationCost { mana: ManaCost, tap_self: bool }` — Slice
    1 minimum field set (richer cost shapes — `sacrifice_self`,
    `pay_life`, `requires_*` — land in follow-up slices alongside
    their dispatch primitives in lockstep, so the parser surface
    stays consistent with the dispatcher's coverage).
  - `effect: Effect` — same closed vocabulary spell-resolve consumes.
  - `is_mana_ability: bool` — `true` bypasses the stack (CR 605.3a),
    `false` pushes a `StackItem::new_trigger`-shaped slot whose
    payload effect fires on the next `resolve_top_of_stack` pop.

  ~~The legacy `mana_produced: Option<Vec<String>>` field stays as the
  free-mana-ability hatch (`{T}: Add {color(s)}`) and remains the
  source-of-truth for Forest / Mountain / Llanowar Elves shapes.
  Both paths coexist...~~ **CLOSED by I51** — the bridge slice
  synthesizes one ActivatedAbility entry per printing with
  `mana_produced.is_some()` at parse time and retires the dual-path
  emission + dual-path apply-dispatch. The `mana_produced` field
  stays as I50's auto-tap composer input but is no longer a runtime
  path. See I51 for the bridge invariant.

- **Affordability gate**:
  - **Emission** (`legal.rs`): pool + auto-tap-from-lands headroom
    via `auto_tap_headroom_pool` (I49). Matches Python's
    `can_pay_cost` model — sums the controller's current pool plus
    every untapped non-sick mana source on bf
    (`printing.mana_produced.is_some()`), then runs `pool_can_cover`
    on the composed pool.
  - **Apply** (`actions.rs`): pool-only via `pay_mana_cost_pub` —
    the controller must already have the mana in pool to commit.
    Activator must tap mana sources ahead of time via separate
    `ActivateAbility(forest, 0)` actions. Matches Python's
    "permissive in `legal_actions`, strict in `_activate_ability`"
    model.

- **Tap-self gate** (emission AND apply): tapped source rejects;
  summoning-sick creature source rejects (CR 302.1 narrows to
  abilities whose cost requires tapping — non-tap-cost abilities
  on a fresh creature still emit). The Slice 1 gate is
  `is_creature && summoning_sick && cost.tap_self`. Mirrors I17.

- **Stack push for non-mana abilities**: `is_mana_ability=false`
  pushes a `StackItem::new_trigger(source_id, controller, effect,
  ability_index)`. The trigger-resolver arm in
  `state_ops_resolve::resolve_top_of_stack` fires the effect via
  `apply_effect` and skips `move_source_post_resolve` (the source
  is already on the battlefield — exactly the semantics needed for
  an activated ability resolving). The `StackItem::TriggeredAbility`
  discriminant captures both ETB triggers AND activated abilities
  for Slice 1 — the dedup-key `ability_index` distinguishes the two
  on a given source.

- **Out of scope** (follow-up slices, each lands with its
  dispatch counterpart in lockstep):
  - Spacecraft station-charge specific shapes: ~~`tier_threshold`
    gate~~ **CLOSED by I53** — see below; the charge-counter-as-cost
    variant (`Pay N charge counters: ...`) stays deferred (no EoE
    printing carries it).
  - Planeswalker loyalty (uses counters as cost, distinct from
    mana; needs `pay_loyalty` cost primitive).
  - ~~Equipment equip costs (specific cost shape + target).~~
    **CLOSED by I54** — see below; the target-pick substrate is
    now in place, which also unblocks the targeted sacrifice
    variants.
  - Sacrifice-as-cost: ~~`sacrifice_self`~~ **CLOSED by I52** —
    see below; the targeted variants (`sacrifice_another_*`,
    `sacrifice_a_land`, `sacrifice_food`) can now ride on the
    Equipment-equip target-pick substrate (closed by I54) — next
    slice candidate.
  - Tap-an-untapped-permanent-you-control (Gene Pollinator shape).
  - Activation-gate predicates (`requires_*` Bonders' Enclave).
  - ~~Bridging legacy `mana_produced` into a synthesized
    `ActivatedAbility { is_mana_ability: true, cost: { tap_self:
    true }, effect: AddManaToPool(...) }` entry (retires the
    side-channel).~~ **CLOSED by I51** — see below.
  - ~~Auto-tap-from-lands composer to match Python's `can_pay_cost`
    headroom accounting on the Rust side.~~ **CLOSED by I50** —
    see below.

### I50. `legal_decisions` ActivateAbility emission affordability includes auto-tap-from-lands headroom via `auto_tap_headroom_pool` composer (CE20 follow-up closure)

- **Pinned by**:
  - `tests/test_parity_smoke.py::test_cross_engine_activated_cost_test_e_auto_tap_headroom_emission_parity`
    (cross-engine emission convergence: with 0 floating pool + 3
    untapped Forests on p0's bf, BOTH engines emit
    `ActivateAbility` for the Bear Caster `{1}{G}` cost via
    auto-tap headroom).
  - 5 `tests_rust/test_activated.py` regression pins:
    - `test_auto_tap_headroom_emits_with_empty_pool_plus_untapped_forests`
    - `test_auto_tap_headroom_no_emission_with_empty_pool_no_lands`
    - `test_auto_tap_headroom_excludes_tapped_lands`
    - `test_auto_tap_headroom_gates_on_source_sickness_not_land_sickness`
    - `test_auto_tap_headroom_pool_only_path_still_works`
  - `tests_rust/test_activated.py::test_bear_caster_no_emission_when_unaffordable`
    (updated to tap default-bf Forests first, anchoring the
    "zero-headroom + empty pool" branch).

- **Invariant.** `state_ops_legal.rs::auto_tap_headroom_pool(state,
  player_idx) -> ManaPool` composes the controller's emission-side
  affordability pool as:

  ```text
  start_with: state.players[player_idx].mana_pool
  for each obj on state.players[player_idx].battlefield:
      if printing.mana_produced is None: continue
      if obj.tapped: continue
      if is_creature(printing) && obj.summoning_sick: continue
      for sym in mana_produced:
          pool[sym] += 1  (saturating)
  return pool
  ```

  The `ActivateAbility` emission filter at
  `state_ops_legal.rs:1056` calls
  `pool_can_cover(&auto_tap_headroom_pool(self, idx), &ability.cost.mana)`
  instead of the pre-I50 `pool_can_cover(&self.players[idx].mana_pool, ...)`.

- **Apply-time strictness preserved.** The
  `ActivateAbility` apply arm in `state_ops_actions.rs:622-656`
  still uses the pool-only `pay_mana_cost_pub` gate — players must
  physically have the mana in their pool to activate. Only emission
  widens. Matches Python's "permissive in `legal_actions`, strict
  in `_activate_ability`" model — Python's `actions.py:336-403`
  `can_pay_cost` accounts for auto-tap-from-lands headroom; Python's
  `_activate_ability` calls `auto_tap_for_cost` ahead of time but
  doesn't self-gate.

- **CR 302.1 still applies to the SOURCE, not the mana lands.** A
  summoning-sick Bear Caster can't activate its `{T}` ability even
  when 2 untapped Forests provide headroom. The composer only
  excludes summoning-sick CREATURE mana sources (Llanowar Elves on
  the ETB turn) — lands skip CR 302.1 entirely.

- **Saturating add.** Each per-symbol increment is
  `pool.color = pool.color.saturating_add(1)` (u8 slot). A
  battlefield with 256+ untapped Forests caps at 255 G headroom; no
  realistic test surface hits the cap, but the saturating add
  prevents wrap-around UB if a fuzz / stress test ever fabricates
  one.

- **No bf-iteration-order dependency.** Unlike
  `bf_iter_etb_sorted` (CE5 invariant I26), the composer's output
  is order-independent — it's a per-color count summation, so
  whatever iteration order `battlefield.iter()` produces yields the
  same `ManaPool`. The CE5 bf-walk-order invariant isn't a
  load-bearing input here.

### I51. Legacy `CardPrinting.mana_produced: Option<Vec<String>>` bridged to a synthesized `ActivatedAbility` entry at parse time + the legacy emission block / legacy apply-dispatch branch retired (CE20 follow-up closure)

- **Pinned by**:
  - 11 `tests_rust/test_activated.py` regression pins (`test_bridge_*`)
    covering: Forest emission / apply (back-compat for every
    pre-bridge caller); Mountain apply (non-Green colors); double-
    green land aggregation (same-color pip summation); hybrid dual-
    land Sequence wrap; creature summoning sickness gate on the
    synthesized tap_self cost; tapped-source emission skip; bridge
    prepended-before-explicit-entries ordering invariant; bridged
    ability is `is_mana_ability=true` (stack bypass); invalid
    ability index raises the unified `has no ability at index` error.
  - `tests_rust/test_mana.py::test_activate_ability_credits_source_controller_not_active_player`
    (the source-controller-vs-active-player parity pin — bridge's
    apply dispatch swaps `state.active_player` temporarily so
    `AddManaToPool` credits the right pool).
  - `tests_rust/test_actions.py::test_apply_action_activate_ability_opponent_source_is_allowed_by_dispatcher`
    (same parity pin from the actions surface).
  - The 17 pre-bridge `test_activated.py` smoke tests + 5 auto-tap
    headroom tests stay green unchanged (the synthesized entry is
    observably equivalent to the legacy free-mana-ability behavior).

- **Invariant.** `cards::apply_mana_produced_bridge(mana_produced,
  existing) -> Vec<ActivatedAbility>` synthesizes ONE
  ActivatedAbility from a `mana_produced: Some(vec!["G", ...])`
  field and PREPENDS it to the existing `activated_abilities` Vec:

  ```text
  cost:   ManaCost::default() (free) + tap_self=true
  effect: AddManaToPool { color, amount } per color in mana_produced
          (aggregated by color: ["G","G"] → one AddManaToPool with
          amount=2; ["G","U"] → Sequence of two AddManaToPool entries).
  is_mana_ability: true (CR 605.1)
  ```

  PREPENDED so `ability_index=0` continues to refer to the free
  mana ability — every pre-bridge caller of
  `ActivateAbility(forest_id, 0)` keeps working bit-equal.

- **Two consumers, one helper.** The bridge function is called from
  TWO sites:
  1. `cards.rs::parse_printing` for dict-input registry callers
     (real-card registry path).
  2. `state.rs::make_synthetic_state` for the test-fixture Forest +
     Llanowar Elves printings (direct `CardPrinting` literal
     construction, bypasses `parse_printing`).

  Sharing the helper guarantees the synthetic state's mana sources
  emit identically to dict-registered mana sources — the bug a
  parse-time-only bridge would have introduced was that every test
  using the synthetic state's pre-seeded Forests would see ZERO
  ActivateAbility emissions because the synthetic Forest had no
  synthesized entry on its `activated_abilities` Vec.

- **Legacy emission block retired.** The pre-bridge
  `state_ops_legal.rs` emission filter walked two paths
  side-by-side: a legacy `mana_produced.is_some()` one-shot at
  `ability_index=0` AND the new-substrate `activated_abilities`
  walk. The bridge collapses both into the single
  `activated_abilities` walk — no double-emit risk (the legacy
  one-shot is gone, no other consumer reads `mana_produced.is_some()`
  for emission).

- **Legacy apply-dispatch branch retired.** The pre-bridge
  `state_ops_actions.rs::ActivateAbility` apply arm carried an
  `is_legacy_mana_produced` fallback that ran a saturating-u8 pool
  credit loop on the source's `printing.mana_produced` symbols.
  Post-bridge: the apply arm dispatches uniformly into
  `printing.activated_abilities[ability_index]` — every mana-only
  source's `ability_index=0` resolves to the synthesized
  `AddManaToPool` effect via `state_ops_resolve::apply_effect_pub`.

- **Source-controller parity pin.** `apply_effect` for
  `AddManaToPool` reads `state.active_player` as the implicit
  controller (CE20-substrate-shape; consistent with every other
  apply_effect arm). The bridge's apply dispatch temporarily swaps
  `state.active_player = controller_idx` around the mana-ability
  resolve so a Forest on player 1's bf activated during player 0's
  turn correctly credits player 1's pool — matches the pre-bridge
  legacy path's explicit `controller_idx` debit. Pinned by
  `test_activate_ability_credits_source_controller_not_active_player`.
  The swap is restored before the apply arm returns; safe for the
  CR 605.1 mana-only effect surface (no other side effects observe
  `active_player` mid-dispatch).

- **`mana_produced` field stays.** The legacy `Option<Vec<String>>`
  field on `CardPrinting` is NOT removed — `auto_tap_headroom_pool`
  (I50) still reads it for the emission-side speculative pool
  composition. The field is now the SYNTHESIS SOURCE, not the
  runtime path: bridge synthesis at parse-time + auto-tap headroom
  composition at emission-time both consume it; the actual cost-pay
  + effect-apply pipeline never touches it post-bridge.

- **Out of scope of this slice (deferred to future follow-ups):**
  - Removing the `mana_produced` field entirely. It's the
    auto-tap composer's input today (I50); migrating I50 to read
    the synthesized `ActivatedAbility` entry's effect tree is
    larger than this slice. The field stays as a hatch for now.
  - Multi-`mana_produced`-entry-per-printing shapes ("Tap for {G}
    or {W}" choose-one mana abilities). Today `mana_produced:
    Some(vec!["G"])` is interpreted as "Tap to add {G}";
    `Some(vec!["G", "W"])` is interpreted as "Tap to add {G} AND
    {W}" (a hybrid producer). The CHOOSE-ONE variant has no Rust
    representation today — needs a richer Effect shape (mode
    selection) and is a separate slice.

### I52. `ActivationCost.sacrifice_self: bool` extends the cost shape; dispatch commits mana → tap → sacrifice → effect (CE20 follow-up Slice 2 closure)

- **Pinned by**:
  - 14 new `tests_rust/test_activated.py` `test_sacrifice_self_*`
    regression pins covering parser surface (3), apply-arm
    state-mutation (4), tap+sac composition + Phase 3 tap precheck
    ordering (2), controller-resolution (1), emission gating (2),
    and the pre-existing `test_activated_abilities_unknown_cost_key_raises`
    updated to use `pay_life` (still-unmodeled key) instead of the
    now-allow-listed `sacrifice_self`.

- **Cost shape extension**. `ActivationCost` grows a `pub
  sacrifice_self: bool` field (defaults `false` via `Default`).
  `parse_activation_cost` adds `"sacrifice_self"` to the allow-list;
  unknown keys still raise loud. Mirrors Python's
  `ActivationCost.sacrifice_self` at `effects/base.py:340-388`.

- **Apply-arm dispatch order** (`state_ops_actions.rs::ActivateAbility`):
  1. Locate source on battlefield (Phase 1).
  2. Resolve ability shape (Phase 2).
  3. Tap-self precheck — already-tapped + creature-sickness gates
     fire BEFORE any commit (Phase 3). Composes with `sacrifice_self`:
     if both are set and the source is already tapped, the activation
     rejects with no state mutation.
  4. Pay mana cost — pool-only via `pay_mana_cost_pub` (Phase 4).
     Failure raises with no state mutation (CR 117.10: costs pay
     atomically, no partial commits).
  5. Commit tap_self (Phase 5).
  6. **Commit sacrifice_self** (Phase 5b, NEW). Source moves from
     bf to its controller's graveyard with the same field-reset
     shape `Effect::Sacrifice` uses: `tapped=false`, `damage=0`,
     `counters=0`, `attached_to=None`, `exiled_with_source=None`;
     preserve `summoning_sick` per CE13 I35. LTB void-flag stamps
     via `mark_left_battlefield_if_nonland` (CE13 / I29) — the
     sacrifice rides on the same primitive every other bf-exit
     uses.
  7. Dispatch the effect (Phase 6). For `is_mana_ability=false`
     pushes a StackItem; the stack item resolves with the source
     already in graveyard (the resolver finds the source_id by
     scanning all zones, so post-sacrifice resolution works
     uniformly).

- **CR 117.10 atomicity pin**. The mana cost fails BEFORE the
  sacrifice commits — `test_sacrifice_self_raises_when_mana_insufficient`
  asserts that an unaffordable activation leaves the source on bf
  with no graveyard growth. Phases 4 and 5b are sequenced: 5b only
  runs after Phase 4 succeeds.

- **Source-controller graveyard pin**. The sacrifice commit moves
  the source to `state.players[controller_idx].graveyard`, not
  `state.players[active_player].graveyard`. Matches the bridge
  slice's source-controller invariant (I51) — pinned by
  `test_sacrifice_self_credits_correct_controller_graveyard`
  (player-1-side source on player-0's turn moves to player 1's gy).

- **Emission gating unchanged**. The new-path emission walk
  (`state_ops_legal.rs:1056+`) doesn't grow a `sacrifice_self`-specific
  check — sacrifice-self is always payable when the source exists,
  which the walk implicitly guarantees by iterating
  `state.players[idx].battlefield`. Pool / tap state / sickness
  gates still fire for cost ingredients orthogonal to sacrifice.

- **Out of scope of this slice (deferred)**:
  - Targeted sacrifice variants: `sacrifice_another_creature`,
    `sacrifice_a_land`, `sacrifice_food`,
    `sacrifice_another_artifact`, etc. Need target fan-out at
    `legal_decisions` emission and an optional
    `target_creature_id`-shaped key on the ActivateAbility dict;
    they ride on Equipment-equip Slice 4's target-pick substrate.
  - Routing `dispatch_event(Event::Dies, source_id)` for creature
    sacrifices. Dies-event wiring landed in ETB Slice 5 (commit
    2fd9aa31) but the SBA-destroy site is the only existing
    dispatch — wiring sacrifice into Dies is a separate slice.

### I53. `ActivatedAbility.tier_threshold: i32 = 0` extends the substrate with a usability gate; `GameObject.charge_counters: i32 = 0` is the per-object tracker (CE20 follow-up Slice 3 Spacecraft station-charge closure)

- **Pinned by**:
  - 15 new `tests_rust/test_activated.py` `test_tier_gate_*` /
    `test_tier_threshold_*` / `test_charge_counters_*` /
    `test_set_charge_counters_*` / `test_get_charge_counters_*`
    regression pins covering parser surface (3), emission gating at
    sub/at/above-threshold (3), apply-arm tier precheck (2), no
    decrement (1), multi-tier independent gating (2), back-compat
    zero-default (1), G8 independence pin (1), test-helper return
    convention (1), test-helper unknown-id (1).

- **Cost shape extension**. `ActivatedAbility` grows
  `pub tier_threshold: i32` field (defaults `0` — no gate, back-
  compat with every pre-Slice-3 caller). `parse_activated_ability`
  accepts optional `tier_threshold: int` (defaults to 0 when key
  absent); negative values raise loud. Mirrors Python's
  `ActivatedAbility.tier_threshold: int = 0` at `effects/base.py:447`.

- **Per-object tracker**. `GameObject` grows
  `pub charge_counters: i32` field (defaults `0`). Distinct from
  the existing `counters: i32` slot (+1/+1 counters) — G8 multi-kind
  counter open gap stays as a separate concern; the two fields are
  observably independent. Test-helpers `set_charge_counters(obj_id,
  value)` + `get_charge_counters(obj_id) -> Option<i32>` exposed via
  pyo3 (mirrors `force_set_summoning_sick`'s test-helper
  convention).

- **Tier gate is a USABILITY gate, NOT a cost**. The source's
  `charge_counters` is COMPARED against `tier_threshold` at
  `legal_decisions` emission AND at apply-time precheck; the
  activation does NOT decrement charge counters (sub-tier
  activations are simply unavailable). Pinned by
  `test_tier_gate_does_not_decrement_charge_counters` and
  `test_tier_gate_apply_at_threshold_succeeds`.

- **Emission gate ordering** (`state_ops_legal.rs:1099+`): the
  tier check fires FIRST in the per-ability loop, before
  `tap_self` (already-tapped + sickness) and before
  `pool_can_cover` (mana affordability). A sub-tier source is
  outright inert; checking its mana / tap state is wasted work and
  could leak observable signal (e.g. emission count varying by
  pool state under a sub-tier source).

- **Apply-arm gate ordering** (`state_ops_actions.rs:557+`): Phase
  3a (NEW) runs BEFORE Phase 3 (tap precheck), Phase 4 (mana pay),
  Phase 5 (tap commit), Phase 5b (sacrifice commit), and Phase 6
  (effect dispatch). A direct (bypass-emission) caller submitting
  a sub-tier activation raises with `below tier threshold` BEFORE
  any state mutation.

- **Multi-tier shape**. A printing can carry multiple
  ActivatedAbility entries with different `tier_threshold`s
  (Eternity Elevator's shape: tier-3 + tier-10 + tier-20
  abilities). Each entry gates independently in the
  per-ability emission walk. Pinned by
  `test_tier_gate_multi_tier_independent_gating` and
  `test_tier_gate_multi_tier_above_both_emits_both`.

- **GameObject construction sites updated**. The new
  `charge_counters: 0` initializer added to 6 `GameObject` literal-
  construction sites: `state.rs::make_object`,
  `state_ops_setup.rs`, `state_ops_deck.rs`,
  `state_ops_resolve.rs` (token creation + clone-target token +
  register_and_inject_object). The default-0 value is the back-
  compat shape — every pre-Slice-3 fixture-state object reads its
  charge_counters as 0 and the tier gate passes for any printing
  with `tier_threshold=0` (i.e. every pre-Slice-3 printing).

- **Out of scope (deferred to future slices)**:
  - Charge-counter-as-COST variant (`Pay N charge counters: ...`).
    No EoE printing carries this shape; a grep of the EoE pool's
    oracle text for "Pay [0-9]+ charge counter" returns zero hits.
    Future slice will add `ActivationCost.charge_counters: i32`
    with a Phase 4b decrement commit if a card actually surfaces.
  - The station mechanic that ACCRUES charge counters (tap one or
    more crewing creatures to add charge counters). Out of scope of
    this slice — needs a "tap multiple creatures" cost primitive
    that's its own follow-up. Test fixtures seed charge counters
    directly via the `set_charge_counters` test-helper.
  - Zone-change reset of `charge_counters`. Per CR 400.7 per-object
    state should reset when an object changes zones, but the
    existing `counters = 0` resets at ~14 sites don't yet have a
    `charge_counters = 0` companion. The gap is benign for
    Slice 3's test surface (objects stay on bf throughout each
    test); a future cleanup slice will add the resets in lockstep
    with sealing the Spacecraft cost-pay variant.

### I54. `ActivationCost.requires_target_creature_you_control: bool` extends the cost shape; emission fan-out + apply-arm target validation + StackItem payload-target threading (CE20 follow-up Slice 4 Equipment-equip closure)

- **Pinned by**:
  - 21 new `tests_rust/test_activated.py` `test_equip_*` /
    `test_non_target_*` regression pins covering parser surface (3),
    emission target fan-out + eligibility filters (5: per-target,
    self-exclusion, opponent-exclusion, non-creature-exclusion,
    affordability), apply-arm target validation (6: happy-path,
    retarget, missing-target, self-target, opponent-target,
    non-creature-target, unknown-id), mana-cost debit (1),
    back-compat non-target dict shape (3: omitted key / explicit
    None / spurious target ignored), resolve-arm payload-target
    pick (1).
  - The pre-existing `test_legal_decisions_activate_ability_dict_shape_is_minimal`
    updated to assert the new 4-key dict shape (kind / source_id /
    ability_index / target_creature_id) — Slice 4 grew the wire
    shape by one field.

- **Cost shape extension**. `ActivationCost` grows
  `pub requires_target_creature_you_control: bool` field (defaults
  `false` via `Default`). `parse_activation_cost` adds
  `"requires_target_creature_you_control"` to the allow-list;
  unknown keys still raise loud. Mirrors Python's Equipment-equip
  shape at `effects/generic/attach.py` (Python flag-fields the
  cost; Rust mirrors via the bool).

- **Action dict shape extension**. `Action::ActivateAbility` grows
  `pub target_creature_id: Option<u32>` field. The
  `parse_action`/`action_to_pydict` round-trip handles both shapes
  losslessly: missing key OR explicit `None` map to `None` (the
  pre-Slice-4 wire format stays accepted as-is); `Some(id)` carries
  the chosen target. `action_to_pydict` always emits the key for
  symmetric round-trip (`None` → Python `None`).

- **Emission target fan-out** (`state_ops_legal.rs:1131+`). When the
  ability's cost flags `requires_target_creature_you_control = true`,
  the per-ability loop walks the activator's battlefield and emits
  ONE `ActivateAbility` dict per legal target creature. Eligibility
  per CR 702.6c: target must be a creature on the activator's bf
  AND not the source itself. Target's summoning sickness is NOT a
  barrier (equip is mana-only — the target's tap state is
  irrelevant). Non-target activations (the pre-Slice-4 shape) emit
  one dict per source as before with `target_creature_id = None`.

- **Apply-arm target validation** (`state_ops_actions.rs:572+`,
  Phase 2.5 NEW). Fires BEFORE Phase 3a (tier gate) / Phase 3
  (tap precheck) / Phase 4 (mana pay) / Phase 5 (commits). Raises
  loud BEFORE any state mutation on:
  - Missing `target_creature_id` for an ability that requires one.
  - `target_creature_id == source_id` (self-target).
  - Target not on the activator's bf, or target's printing isn't
    a Creature.
  Non-target activations silently accept (and ignore) a stray
  `target_creature_id` — matches Python's permissive
  accept-and-ignore for spurious kwargs.

- **StackItem payload-target threading**. `TriggerPayload` grows
  `pub target_id: Option<u32>` field; `StackItem::new_trigger`
  (legacy, pre-Slice-4) sets it `None`; new
  `StackItem::new_trigger_with_target` constructor carries
  `Some(target_id)` for targeted activations. The non-mana
  activation arm picks the constructor based on
  `validated_target_id`. The is_mana_ability arm seeds
  `state.current_resolve_payload_target_id` directly via swap
  (same pattern as the Slice 1 bridge `active_player` swap).

- **Resolve-time payload-target pickup** (`state_ops_resolve.rs:4361+`).
  `Effect::EquipToTargetCreatureYouControl` now reads
  `state.current_resolve_payload_target_id` (swapped in by the
  stack resolver from `trigger_payload.target_id` before
  `apply_effect` fires, restored after). When `Some(id)` and the
  target is still legal (CR 608.2b — recheck legality at
  resolve), stamp it. When `Some(id)` but the target has become
  illegal (e.g. left the battlefield), silently fizzle. When
  `None` (no payload-target was seeded — pre-Slice-4 callers, or
  the ETB-attach sibling variant), fall back to the prior
  first-eligible-creature walk for back-compat.

- **Transient resolver field**. `GameState.current_resolve_payload_target_id:
  Option<u32>` is the resolver's stash slot for the chosen target.
  Mirrors the `state.active_player` swap pattern (the Slice 1
  bridge follow-up's solution to source-controller resolution).
  NOT serialized into the fingerprint — same transient bookkeeping
  shape as `consecutive_passes`, `next_etb_timestamp`,
  `resolving_combat_damage_amount`. Restored to its prior value
  after each apply so no observable state leaks across resolution
  boundaries.

- **Foundation that pre-existed**: `GameObject.attached_to:
  Option<u32>` (`state.rs:58`), `Effect::EquipToTargetCreatureYouControl`
  variant (round-29), the attach mutation at
  `state_ops_resolve.rs:4279-4326` (the AttachToTargetCreatureYouControl
  sibling — Equipment ETB path). The Slice 4 closure plumbs the
  ACTIVATED equip-ability path through these primitives without
  modifying the underlying attach mutation; only the
  target-pick policy at the resolve site grows from
  "first-eligible" to "payload-target with first-eligible
  fallback".

- **7 EoE Equipment printings affected**: Auxiliary Boosters,
  Squire's Lightblade, Atomic Microsizer, Illvoi Light Jammer,
  Hylderblade, Meltstrider's Gear, The Dominion Bracelet.

- **Out of scope (deferred to future slices)**:
  - **Targeted sacrifice variants** (`sacrifice_another_creature`,
    `sacrifice_a_land`, `sacrifice_food`,
    `sacrifice_another_artifact_or_land`, etc.). Each variant rides
    on the Slice 4 target-pick substrate (same
    `requires_target_*` flag pattern, same `target_creature_id` (or
    `target_*_id`) key on the dict, same payload-target threading
    to a new effect arm per sacrifice flavor). Slice 5+ scope.
  - **Multi-target activations** (target a creature AND a player,
    target N creatures, etc.). Single-target Slice 4 scope; the
    payload shape supports only one `target_id` today. Multi-target
    needs `target_ids: Vec<u32>` and an effect-side multi-target
    arm.
  - **Walker loyalty target redirect** (CR 119.5 — combat damage
    targeting a planeswalker). Separate slice (Walker Slice B per
    the playbook); needs DeclareAttackers growth, not
    ActivateAbility growth.
  - **The cross-engine smoke harness's
    `activated_cost_side_channel` Bear-Caster probe**. Bear Caster
    is not a targeted activation; the probe stays unchanged. A
    future Equipment-equip cross-engine probe would inject a
    synthetic equip printing on BOTH engines and exercise the
    target-fan-out emission shape — deferred to a follow-up that
    also confirms parity-clean walk shapes for the equip dict.

### I49. Legacy `etb_effects: Vec<Effect>` bridged to `triggered_abilities` at parse time + cross_engine.py `printing_dict` wires `triggered_abilities` through to Rust's `register_and_inject_object` (Slice 3 of ETB-trigger closure)

- **Pinned by**:
  - `tests/test_cross_engine_etb_triggers.py::test_card_def_carries_triggered_abilities_field`
    (DeckSpec-side: `CardDef.triggered_abilities` defaults to empty
    tuple, accepts a tuple of trigger dicts).
  - `tests/test_cross_engine_etb_triggers.py::test_python_state_builder_wires_triggered_abilities`
    (Python-side: dict-shape triggered_abilities translate via the
    `_ta_dict_to_python_triggered_ability` bridge into Python's
    `TriggeredAbility(event=Event.ENTERS, predicate=IsSelf(), effect=DrawCards(amount=1))`).
  - `tests/test_cross_engine_etb_triggers.py::test_rust_state_builder_wires_triggered_abilities`
    (Rust-side: the registered printing dispatches the synthesized
    self-ETB trigger when an instance enters the battlefield; the
    trigger lands on the stack post-resolve as a `StackItemKind::TriggeredAbility`).
  - `tests/test_cross_engine_etb_triggers.py::test_pre_slice_3_specs_unaffected`
    (regression guard: a DeckSpec leaving `triggered_abilities` at
    the default empty tuple produces zero triggers, zero stack
    pushes, identical to pre-Slice-3 behavior).
  - `tests_rust/test_triggers.py` (all 24 substrate + RS-site smokes,
    unchanged — the bridge is a parse-time-only rewrite; the
    dispatch path's observable shape doesn't change).
  - Updated regression tests across `tests_rust/test_resolve.py`,
    `test_zones.py`, `test_ueot.py`, `test_pending_decisions.py`,
    `test_combat.py` — every test that previously cast a printing
    carrying `etb_effects` and asserted the side-effects had landed
    after ONE `resolve_top_of_stack` call now drains an additional
    `resolve_top_of_stack` to pop the on-stack ETB trigger that the
    Slice 3 synthesis produces. Observable end-state matches the
    pre-Slice-3 inline shape.

- **Invariant — parse-time synthesis**. `cards.rs::parse_printing`
  reads `etb_effects: Vec<Effect>` from the registry dict (kept for
  back-compat with pre-Slice-3 fixtures), then synthesizes one
  `TriggeredAbility { event: Event::Enters,
  predicate: Predicate::SourceIsSelf, effect: <each etb_effect>,
  once_per_turn: false }` per `etb_effects` entry and appends to
  `triggered_abilities`. Synthesized entries land AFTER any
  explicitly-declared `triggered_abilities` so dispatcher walk order
  is stable (declaration order first, then synthesized self-ETB
  shims). Resolver-side: the inline `etb_effects` loop in
  `resolve_top_of_stack` and `resolve_top_of_stack_pause` is
  retired — every self-ETB effect now fires through the
  predicate-path `dispatch_event(Event::Enters, source_id)` walker,
  same substrate as Slice 1/2's Panharmonicon-shape observer
  triggers.

- **Observable behavior change — triggers now go on the stack**.
  Pre-Slice-3 the inline `etb_effects` loop applied the effects
  immediately at resolution time (no stack push, no priority
  window). Post-Slice-3 each `etb_effects` entry becomes a
  `StackItem::TriggeredAbility` that resolves LIFO on a subsequent
  `resolve_top_of_stack` call. The on-stack shape is CR-faithful
  (CR 603 — triggered abilities go on the stack), preserves the
  Slice 1/2 fingerprint baselines (the same effect lands the same
  observable end-state once the stack drains), and only the
  intermediate state at "just after the cast resolved but before
  the trigger drained" differs.

- **No double-fire**. The audit pinned the legacy inline path as
  the ONLY pre-Slice-3 self-ETB site. Slice 3 retires that loop in
  one go, so there's no risk of a printing carrying both
  `etb_effects` and an explicit `triggered_abilities` entry that
  matches `SourceIsSelf` firing the same effect twice. (Pre-Slice-3
  the audit verified no EoE printing carried both shapes; today
  there's no path to double-fire even if a future fixture did.)

- **Cross-engine wiring** (`src/mtg_bot/parity/cross_engine.py`):
  - `CardDef` gains a `triggered_abilities: tuple[dict, ...] = ()`
    field carrying registry-dict-shape entries.
  - `build_rust_state` passes `triggered_abilities` through the
    `printing_dict` builder into `register_printing` — Rust's
    parser handles the dict shape (existing Slice 1 surface).
  - `build_python_state` translates each dict through the new
    `_ta_dict_to_python_triggered_ability` helper into Python's
    `TriggeredAbility(event=Event.ENTERS, predicate=..., effect=...,
    once_per_turn=...)` shape, then attaches the resulting tuple to
    `CardPrinting.triggered_abilities`.
  - Effect-kind / predicate-kind translation surfaces (`_ta_dict_to_
    python_effect`, `_ta_dict_to_python_predicate`) currently cover
    the substrate-minimum kinds — `draw_cards`, `gain_life` for
    effects; `always`, `source_is_self`, `source_is_creature`,
    `not`, `and` for predicates. New CE19-shape probes add an arm
    per kind in lockstep with the Rust `parse_effect` /
    `parse_predicate` arm.

- **CR backing** — same as I47 (CR 603.6a). Slice 3 doesn't add
  new CR coverage; it consolidates the existing self-ETB inline
  hatch into the same dispatch substrate.

- **Out of scope for Slice 3** (queued for Slice 4+):
  - Richer Predicate variants (`HasSubtype`, `IsLand`, `IsArtifact`,
    `Controlled`, `Subject`) — needed for landfall, artifact-enters,
    Kavu-shape predicates from `cards/parser/triggers.py:603-1266`.
  - Wider `Event` variants (`Dies`, `Cast`, `Attacks`,
    `DealsDamage`) and their dispatch sites.
  - Panharmonicon-shape `etb_trigger_multiplier` for cards that
    grant N-x ETB firings.
  - A full multi-turn cross-engine smoke that drives a CE19-shape
    probe end-to-end through both engines and asserts fingerprint
    parity once the predicate algebra is rich enough to express
    "another creature enters under your control" (today's
    `SourceIsCreature & ~SourceIsSelf` Slice 1 substrate is close
    but lacks the `Controlled(YOU)` predicate needed for a
    Panharmonicon-faithful probe).
  - Removing `CardPrinting.etb_effects` from the Rust struct
    entirely. The field stays as the synthesis source for back-compat
    with pre-Slice-3 fixtures; a future cleanup slice can retire the
    field once all in-tree fixtures move to `triggered_abilities`
    directly.

### ~~CE9.~~ CLOSED: Combat damage assignment walks battlefield in bf-ETB order via shared `bf_iter_etb_sorted` helper

Closed by `feature/ce9-blocker-bf-order` (this slice). Per the
playbook's §3 Option A: parity with observable Python first, with a
long-term Python-side combat.py fix deferred to a follow-up todo (CR
510.1d says the active player chooses damage assignment order, which
is declare-order; Python's `combat.py:389,405` walk is technically a
bug vs CR, but matching observable Python is the cross-engine
reference for now).

**Closure shape — two iteration sites in `state_ops_combat.rs`,
both routed through `bf_iter_etb_sorted`:**

- `state_ops_combat.rs:865-868` (per-attacker first-blocker pick)
  — pre-closure used `self.blockers.iter().find_map(...)` walking
  the `Vec<(u32, u32)>` in declare push order. Post-closure builds
  a `HashSet<u32>` of blocker ids for this attacker, then walks
  `crate::bf_iter::bf_iter_etb_sorted(self)` and `find_map`s the
  first object whose id is in the set. Mirrors Python's
  ``[o for o in state.battlefield if o.id in attacker.blocked_by]``
  walk semantically and observably.

- `state_ops_combat.rs:962` (back-damage from every declared
  blocker) — pre-closure iterated `for &(attacker_id, blocker_id)
  in &self.blockers` directly. Post-closure builds a
  `HashMap<u32, u32>` mapping `blocker_id -> attacker_id`, then
  walks `bf_iter_etb_sorted(self)` filtered to objects whose id
  appears in the map. Each blocker still emits its damage entry —
  only the order of accumulation differs, which is invisible on
  the symmetric 2/2-vs-2/2 surface but matters for any future
  variant where the order of accumulation is observable (lifelink
  with interleaved bf, deathtouch upgrade-then-mark-lethal
  sequencing).

The `state_ops_combat.rs:1025-1028` first-strike alive-check filter
inherits the pass-1 plan's iteration order via the
`plan.into_iter().partition(...)` — no separate change needed; the
plan now contains entries in bf-ETB order from the two corrected
walk sites above.

**Secondary closure — SBA destroy path clears `damage` / `tapped` /
`attached_to` on move-to-graveyard.** `state_ops_sba.rs::apply_sbas`
previously preserved per-object combat marks (damage, tapped) when
moving a lethally-damaged creature to its controller's graveyard.
Python's `turn.move_off_battlefield`:230-240 clears those fields
on the way out (CR 400.7 / 614.12). Pre-CE9 this divergence was
invisible because no parity test compared graveyard-entry per-object
damage on an SBA-destroyed creature; the multi-block smoke surfaced
it as a paired secondary divergence on `graveyard_p0` /
`graveyard_p1` (Python: damage=0; Rust: damage=lethal). This slice
adds the `obj.damage = 0; obj.tapped = false; obj.attached_to = None`
reset to the SBA move (mirroring Python's clear set). Counters stay
— Python's `move_off_battlefield` does NOT clear counters either, so
the observable shape stays aligned with Python rather than CR 121.2.

**Tests.** The pre-closure strict-xfail clean-walk pin
`test_cross_engine_multi_block_combat_selector_walks_clean` flipped
to expected-pass at N=210 decisions on `multi_blocker_deckspec`.
Companion symptom-pin
`test_cross_engine_multi_block_combat_selector_surfaces_ce9_at_step_196`
deleted per the CE2/CE3/CE4/CE5/CE6 closure-pair contract. Three
new regression tests pin the new equilibrium in
`tests_rust/test_combat.py`:

- `test_multi_block_damage_assignment_picks_etb_first_blocker`
  — declare two blockers in REVERSE bf order; assert the bf-ETB-
  first blocker (NOT the declare-first one) takes the attacker's
  damage.
- `test_multi_block_damage_back_damage_uses_etb_order` —
  asymmetric blocker powers (2 + 1 = 3) against a 3/3 attacker;
  pin the post-damage marks so the helper consumption is observable
  on the attacker / both blockers.
- `test_apply_sbas_clears_damage_on_creature_move_to_graveyard`
  — pin the secondary closure shape: per-object combat marks
  zero out on the way to the graveyard.

**Fingerprint baselines.** Stayed bit-equal. Synthetic-state pinned
digests (every bf object at `etb_timestamp=0`) have a tie-break that
preserves the pre-closure p0-then-p1 walk; real ETB-driven flows
were not previously pinned at the digest layer. Full rust gate
(1756 + 3 new = 1759 tests post-merge) green; full parity-smoke
gate (78 tests) green.

**Follow-up todo.** Per Option A: file a Python-side fix to make
`combat.py:389,405` walk `attacker.blocked_by` in push order
(matching CR 510.1d). When that lands, switch Rust's two iteration
sites BACK to `self.blockers` push order and update I31. Scoped as
a separate slice because (a) it doubles the CE9 blast radius
through the Python combat path and (b) the engineering-correct shape
is mostly invisible on observable single-blocker scenarios — the
short-term parity is more valuable than the CR-correct semantics
right now.

### ~~CE10.~~ CLOSED: `is_over` / `winner_id` / `is_draw` surface accessors are SBA-gated (matching Python's SBA-written fields)

> **Numbering note.** Skipping CE6-CE9 deliberately. The
> `docs/CE5_CE6_CE7_CLOSURE_PLAYBOOK.md` reserved CE5-CE7 for the
> SBA-victim-collection / damage-assignment / target-pick sequence
> based on the ORDER_SENSITIVE_SURFACES.md audit's ranked
> predictions. The cast_bears_selector probe surfaced a different
> divergence first (the cast-vs-resolve gap, also currently numbered
> CE5 — a separate in-flight renumbering will resolve the collision).
> CE-pure-derivation-is_over was surfaced informally by the Phase-5
> edge-case slice and pinned by strict-xfail in
> `tests/test_parity_smoke_edge_cases.py`; the retro doc ranked it
> as priority #2 for the next session. Jumping to CE10 here leaves
> CE6-CE9 free for the playbook's pre-staged slices and any
> renumbering fallout from the cast-vs-resolve collision.

Closed by `feature/ce-pure-derivation-is-over` (this slice). The
pre-closure Rust implementation of the three Python-named surface
accessors used the same eager OR'd-three predicate as the Rust-native
`losers()` / `winner()` / `is_game_over()` API:

```rust
fn is_over(&self) -> bool {
    self.is_game_over()  // OR'd-three across both players
}
#[getter]
fn winner_id(&self) -> Option<u8> {
    self.winner()  // OR'd-three with the unique-survivor short-circuit
}
#[getter]
fn is_draw(&self) -> bool {
    // OR'd-three on both players simultaneously
}
```

Python's same-named fields (`GameState.is_over`, `GameState.winner_id`,
`GameState.is_draw`) are written ONLY by
`turn.apply_state_based_actions` (lines 1383-1393). The cross-engine
smoke harness (`scripts/parity_smoke.py`, `tests/test_parity_smoke*.py`)
does NOT fire SBAs between decision steps, so an empty-library
side-channel `draw_card` surfaced a NOVEL divergence: Rust's
`attempted_draw_on_empty` cause-flag eagerly flipped `is_over` to
True / `winner_id` to the opponent, while Python's `winner_id` field
stayed `None` because no SBA wrote to it. The cause-flag side
(`has_lost` on Python, `attempted_draw_on_empty` on Rust) agreed; the
surface accessors diverged.

Pinned by (now-passing, was strict-xfail):

- `tests/test_parity_smoke_edge_cases.py::test_cross_engine_empty_library_side_channel_draw_walks_clean`
  — empty-library side-channel draw via `play_a_land_selector`,
  walks parity-clean at N=2 steps.
- `tests/test_parity_smoke_edge_cases.py::test_cross_engine_single_card_libraries_multi_turn_walks_clean`
  — 1-card libraries via `multi_turn_selector`, walks parity-clean
  at N=100 steps after both engines deplete their libraries by
  turn 3 and the inline auto-draw fires on subsequent DRAW steps.

Also pinned by the post-closure shape on the companion symptom test:

- `test_cross_engine_empty_library_side_channel_draw_post_closure_both_engines_stay_stale`
  — inverted from its pre-closure shape, now asserts that both
  engines stay stale on the surface (no SBA fired) and that
  `is_over` / `winner_id` are absent from the divergence set.

**The closure.** Rust's `is_over` / `winner_id` / `is_draw` getters
in `rust/src/state_ops_winloss.rs` now read ONLY from the sticky
`Player.has_lost` flag, mirroring Python's surface exactly:

```rust
fn is_over(&self) -> bool {
    self.players[0].has_lost || self.players[1].has_lost
}
#[getter]
fn winner_id(&self) -> Option<u8> {
    match (p0.has_lost, p1.has_lost) {
        (false, true) => Some(p0.id),
        (true, false) => Some(p1.id),
        _ => None,
    }
}
#[getter]
fn is_draw(&self) -> bool {
    self.players[0].has_lost && self.players[1].has_lost
}
```

The Rust-native API stays unchanged: `losers()`, `winner()`,
`is_game_over()`, and `is_player_alive()` still use the eager OR'd-three
predicate (`has_lost || attempted_draw_on_empty || life <= 0`) so
callers that need pre-SBA loss observability — notably `apply_sbas`
itself, which folds cause-flags into the sticky `has_lost` — keep
their existing semantics. See I19 ("Empty-library draw flags the
player...") for the full two-layer invariant.

**Why Option A (modify Rust) over Option B (modify Python).** Python
is the reference per `docs/RUST_PARITY_PLAN.md` ("Python is the source
of truth; Rust mirrors"); modifying Python risks downstream churn in
search, training, and the 7000+ Python test suite. Modifying Rust is
the smaller surface — three method bodies — and lands the parity
without touching the well-tested Python pathway.

**Tests updated.** Three existing Rust tests pinned the pre-closure
eager-surface behavior; they were updated in-place to either (a)
call `apply_sbas_until_quiescent` to commit the loss before asserting
on `winner_id`, or (b) switch to the eager `winner()` / `is_game_over()`
API where the test's intent was eager-cause-flag observability:

- `tests_rust/test_library.py::test_drawcards_from_empty_library_marks_player_for_loss_on_next_sba`
- `tests_rust/test_library.py::test_drawcards_count_larger_than_library_drains_then_loses_on_sba`
- `tests_rust/test_steps.py::test_advance_phase_auto_draw_on_empty_library_flags_attempted_draw`

Plus seven tests in `tests_rust/test_winloss.py` under the "Python-
compatible outcome getters" heading were rewritten to pin the new
SBA-gated semantics (renamed with `_sba_gated` suffix where helpful;
two new tests added pinning the parity-critical pre-SBA-stale
contract): `test_is_over_sba_gated_one_dead_via_set_life_then_sba`,
`test_is_over_sba_gated_both_dead_via_set_life_then_sba`,
`test_is_draw_all_four_shapes_sba_gated`,
`test_winner_id_all_four_shapes_sba_gated`,
`test_winner_id_pre_sba_stale_matches_python_semantics`,
`test_is_over_winner_id_eager_for_empty_library_draw_via_pure_derivation`,
`test_revive_via_gain_life_pre_sba_clears_eager_loss`.

**Fingerprint baselines unaffected.** The `fingerprint()` method
inlines its own `life <= 0`-based predicate (see
`state_ops_fingerprint.rs:295-304`), not the surface accessors, so
the closure doesn't shift any pinned fingerprint baseline. The
fingerprint's eager predicate matches Python's `hash_state` recipe
shape (which reads Python's `is_over()` field-view at hash time, NOT
a synthetic re-derivation) — that recipe was always cause-flag-driven
because Python's stack/UI tests run SBAs before hashing. Cross-engine
fingerprint byte-equality stays out of scope (see the module
docstring's "Cross-engine parity scope" — Python's `mana_pool` shape
diverges).

**Composes with** I19 (the I-invariant that documents the two-layer
API split) and with future SBA-driven slices (death-trigger emission,
the trigger-queue mirror) which will keep using the eager `losers()` /
`winner()` API to detect cause-flags-driven loss before SBA writes
`has_lost`.

### ~~CE11.~~ CLOSED: cross-player find-first Effect arms walk battlefield in ETB-timestamp order (via shared `bf_iter_etb_sorted` helper)

> **Numbering note.** This is the divergence labeled CE7 in the
> `docs/RUST_BF_ITERATION_AUDIT.md` and `docs/CE5_CE6_CE7_CLOSURE_PLAYBOOK.md`
> §4 pre-renumber labeling. The numbering collision with CE7 in this
> doc (`draw_card_inline` mirror flags, closed earlier) is resolved by
> jumping to CE11 here. The audit's predicted ordering CE5 → CE6 → CE7
> maps to this doc's CE6 (SBA-victim collection) → CE9 (combat damage
> assignment, in flight) → CE11 (this slice) at the playbook-coordinated
> renumber. CE10 was an unrelated surface-accessor closure that took
> the next number when it landed.

Closed by `feature/cross-player-find-first` (this slice).
Pre-CE11 the two Effect arms `Effect::TapAnotherTargetCreature`
(`rust/src/state_ops_resolve.rs:4682`) and `Effect::UntapTargetOtherPermanent`
(`rust/src/state_ops_resolve.rs:4712`) walked their first-eligible
target via a labeled `'outer: for (pidx, player) in state.players.iter().enumerate()`
loop — p0-first, p1-second, in each player's per-player battlefield
Vec order. Python's `effects/generic/tap.py:277-295` (`TapAnotherTargetCreature`
via the base `Tap` class's `legal_targets` pipeline) and
`effects/generic/tap.py:346-386` (`UntapTargetOtherPermanent.legal_targets`)
both walk the centralized `state.battlefield` (ETB-monotone post-CE4)
filtered by their respective predicates and pick the first match. The
two engines diverged whenever a p1 permanent had a lower ETB stamp
than the first p0 eligible target — i.e. whenever the cross-player
walk's tie-break direction mattered.

**Closure shape.** Both arms switch their outer iteration to
`for obj in crate::bf_iter::bf_iter_etb_sorted(state)` (the shared
helper introduced by the CE6 SBA-victim closure, `cdb01fcd`). Predicate
logic is unchanged:

- `TapAnotherTargetCreature`: `obj.id != source_obj_id` AND the
  printing's `card_types` contains `"Creature"`. Pick first.
- `UntapTargetOtherPermanent`: `obj.id != source_obj_id` AND
  `obj.tapped`. Pick first.

Player index is read off `obj.controller` rather than the outer
enumerate index. The mutating per-player `Arc::make_mut` write pass
is identical to pre-CE11.

**Tests.** Four new regression tests in `tests_rust/test_resolve.py`
under the "CE7 closure: cross-player find-first arms walk ETB-timestamp
order" section (CE7 = audit-labeled identifier, kept in test docstrings
for cross-doc grep-ability):

- `test_resolve_tap_another_picks_etb_first_across_players` — p0
  ETB-older, p1 newer; source on p1. Pins ETB-first match wins
  regardless of source controller.
- `test_resolve_tap_another_picks_p1_when_p1_etb_first` — the
  LOAD-BEARING direction: p1 ETB-older, p0 newer; pre-CE11 Rust
  picked p0's newer creature, post-CE11 picks p1's older one
  matching Python's centralized walk.
- `test_resolve_untap_other_picks_etb_first_across_players` —
  symmetric LOAD-BEARING case for the untap arm: p1 ETB-older
  tapped permanent wins over p0's newer tapped permanent.
- `test_resolve_untap_other_picks_p0_when_p0_etb_first` — pins the
  no-regression direction (p0 ETB-older wins under both pre- and
  post-CE11 walks).

Adds a `_two_two_creature_dict()` helper local to the CE7 test section
(mirroring the SBA-test convention from `tests_rust/test_sba.py`).

**Fingerprint baselines.** Zero shifts. Pinned baselines use
deterministic setups where the tie-break direction doesn't matter
(single-controller resolutions, drain-bf-first patterns, or
synthetic-seed-shaped fixtures where every bf object's
`etb_timestamp == 0`). The helper's stable sort preserves the
pre-CE11 p0-then-p1 walk on those fixtures, so the 10 pre-existing
tests in the TapAnother + UntapOther sections of `test_resolve.py`
stay bit-equal — none of them pinned the OLD cross-player p0-first
behavior in a way that would shift.

**Pre-emptive parity fix.** This closure is NOT smoke-surfaced: no
cross-engine probe drove a `TapAnotherTargetCreature` /
`UntapTargetOtherPermanent` resolution with interleaved ETB
timestamps yet (Starport-Security and Nanoform-Sentinel-shape cards
exist in the EoE pool, but the current probes don't trigger their
abilities at non-trivial ETB-interleaved states). Closing now keeps
the `bf_iter_etb_sorted` helper consumer set complete (CE6's SBA +
CE11's two find-first arms) while the helper is fresh, rather than
waiting for a probe to surface the divergence later.

Full rust gate (1760 tests post-closure, +4 vs the pre-CE11 1756)
green. Pre-existing `test_no_orphan_rust_variants` Python red
unrelated (pending unmerged coverage-overrides PR).

---

### CE12 — CLOSED by `feature/ce12-sticky-winner-id`

**Status**: closed 2026-05-12 via Option B (Rust-side sticky shadow
field), per Phase 5 convention "converge Rust toward Python, never
modify Python". Closure invariant lives at **I34** below.

The xfail-strict surface-pin
`test_cross_engine_retaliation_selector_surfaces_ce12_winner_id_sticky_vs_derived`
was retired; its companion
`test_cross_engine_retaliation_selector_pre_ce12_walks_clean` was
generalized to
`test_cross_engine_retaliation_selector_walks_clean` (full 260-step
walk parity-clean, no carve-out around step 226).

See I34 for the post-closure invariant pin.

---

### CE13 — CLOSED by `feature/ce13-summoning-sick-ltb`

**Status**: closed 2026-05-12 via Option B (Rust-side convergence
on Python), per Phase 5 convention "converge Rust toward Python,
never modify Python". Closure invariant lives at **I35** below.

The xfail-strict surface-pin
`test_cross_engine_mass_removal_selector_surfaces_ce13_summoning_sick_on_ltb`
was retired and replaced with the full-walk
`test_cross_engine_mass_removal_selector_walks_clean` (170-step
walk parity-clean across the former CE13 surface at step 168). Its
companion symptom-pin
`test_cross_engine_mass_removal_selector_pre_ce13_walks_clean`
was deleted per the CE2-CE11 pair-pin convention.

See I35 for the post-closure invariant pin.

---

### CE14 — CLOSED by `feature/ce14-deathtouch-multiblock`

**Status**: closed 2026-05-12 via Option A (Rust-side convergence
on Python), per Phase 5 convention "converge Rust toward Python,
never modify Python". Closure invariant lives at **I36** below.

The xfail-strict surface-pin
`test_cross_engine_deathtouch_selector_walks_clean` was flipped
from strict-xfail to an expected-pass full-walk parity assertion
(200-step walk parity-clean across the former CE14 surface at
step 174). Its companion symptom-pin
`test_cross_engine_deathtouch_selector_surfaces_ce14_at_step_174`
was deleted per the CE2-CE13 pair-pin convention.

The CE9 multi-block back-damage test
(`test_multi_block_damage_back_damage_uses_etb_order` in
`tests_rust/test_combat.py`) was updated to assert the post-CE14
per-blocker damage distribution (`bf_first_blocker.damage == 2`,
`bf_second_blocker.damage == 1` on the 3/3 attacker vs 2/2 + 1/1
blocker shape) — its pre-closure assertion was a pin on the
single-PlanEntry simplification Rust shipped under round-5 scope,
which CE14 generalized.

See I36 for the post-closure invariant pin.

---

### CE15 — CLOSED by `feature/ce15-trample-multiblock`

**Status**: closed 2026-05-12 via Option A (Rust-side convergence
on Python), per Phase 5 convention "converge Rust toward Python,
never modify Python". Closure invariant lives at **I37** below.

**Closed preemptively based on the deathtouch probe's diagnosis**;
no separate OPEN-phase probe was run because CE14's closure
(`f5d37b37`) explicitly identified the same bug pattern in the
trample branch as part of its diagnostic note ("Rust's
`state_ops_combat.rs:905-955` (trample branch) only emits to
`first_blocker` for the in-blocker portion, while Python's
`combat.py:419-435` walks all blockers"). The fix mirrors CE14's
no-trample multi-block per-blocker assignment loop: the trample
branch now walks every blocker in `bf_iter_etb_sorted` order with
`need_i = 1 if deathtouch else effective_toughness - blocker.damage`
per blocker, then spills the remainder to the defender via the
existing trample-excess emission (Python's `if has_trample and
remaining > 0` block at `combat.py:436-440`).

The trample branch's pre-existing deathtouch=1 cap was preserved
unchanged (CE14's diagnostic note confirmed it was correct);
CE15's edit is structural — the single-PlanEntry first-blocker
shortcut becomes a per-blocker walk. Single-blocker trample
behavior is bit-equal to the pre-CE15 shape (loop runs once,
absorbs `min(power, need)`, remainder spills to defender —
identical to the pre-CE15 `to_blocker = min(power, cap)` /
`excess = power - cap` math).

4 new regression tests in `tests_rust/test_combat.py`:

- `test_trample_two_blockers_no_deathtouch_no_excess` — 4/4 trample
  vs 2x 2/2: blocker A 2 (dies), blocker B 2 (dies), defender 0.
  Pre-CE15: blocker A 4, blocker B 0, defender 0.
- `test_trample_two_blockers_no_deathtouch_with_excess` — 5/5
  trample vs 2x 2/2: blocker A 2, blocker B 2, defender 1.
  Pre-CE15: blocker A 2, blocker B 0, defender 3 (single-blocker
  trample math used `blocker_cap = first_blocker.toughness`).
- `test_trample_deathtouch_two_blockers_excess` — 4/4
  trample+deathtouch vs 2x 2/2: blocker A 1 (lethal), blocker B 1
  (lethal), defender 2. Pre-CE15: blocker A 1, blocker B 0,
  defender 3.
- `test_trample_single_blocker_preserved_post_ce15` — pins the
  round-9 single-blocker shape post-refactor (5/5 trample vs 2/2:
  blocker 2, defender 3) so future per-blocker-loop refactors
  don't regress the common case.

No cross-engine smoke probe was added for CE15 — existing combat
probes' smoke runs don't use trample, and the preemptive-closure
trade-off intentionally skips probe authoring. A future
trample-bearing deckspec walk (or extending the
`first_strike_selector` to add trample) would surface any
remaining wiring asymmetry, but the unit-test surface above
covers the load-bearing damage-distribution shapes.

See I37 for the post-closure invariant pin.

---

### ~~CE16.~~ CLOSED: `Action::DeclareBlockers` apply arm post-validates each touched attacker via `is_legal_block_assignment`; single-blocker menace assignments are silently dropped

Closed by `feature/ce16-menace-validation` (this slice). The
pre-closure Rust `Action::DeclareBlockers` arm at
`state_ops_actions.rs:241-243` iterated the assignments Vec and
called `declare_blocker(blocker_id, attacker_id)` per pair, then
returned. The per-pair primitive has no menace gate, and the
existing `is_legal_block_assignment` predicate at
`state_ops_combat.rs:779-789` — which correctly returns `false`
for a menace attacker with exactly one blocker — was never
consulted. A single-blocker menace assignment was accepted into
`self.blockers` and combat damage ran as a normal single-block
exchange (attacker + blocker trade). Python's `actions.py:2555-2566`
silently drops the illegal block via a post-validation
`validated.pop(...)` pass.

Option A from the pre-closure plan was taken (Rust-side
convergence on Python, per Phase 5 "converge Rust toward Python,
never modify Python"). After the per-pair `declare_blocker` loop,
the apply arm now collects the unique attacker ids that the
assignments touched, calls `is_legal_block_assignment` for each,
and retains-out the matching `(attacker_id, _)` entries from
`state.blockers` for attackers that fail the predicate:

```rust
let mut unique_attackers: Vec<u32> = Vec::new();
for (_, attacker_id) in &assignments {
    if !unique_attackers.contains(attacker_id) {
        unique_attackers.push(*attacker_id);
    }
}
for (blocker_id, attacker_id) in assignments {
    slf.call_method1("declare_blocker", (blocker_id, attacker_id))?;
}
let illegal: Vec<u32> = {
    let state = slf.borrow();
    unique_attackers
        .into_iter()
        .filter(|aid| !state.is_legal_block_assignment(*aid))
        .collect()
};
if !illegal.is_empty() {
    let mut state = slf.borrow_mut();
    state.blockers.retain(|(a, _)| !illegal.contains(a));
}
```

Pinned by (now-passing, was strict-xfail):

- `tests/test_parity_smoke.py::test_cross_engine_menace_selector_single_blocker_walks_clean`
  — the 200-decision walk with `block_decision="single"` now
  walks parity-clean. Was strict-xfail pre-closure.

Companion symptom-pin
`test_cross_engine_menace_selector_single_blocker_surfaces_ce16_at_step_174`
deleted at closure per the CE2-CE15 pair-pin convention — the
symptom no longer surfaces post-closure.

New Rust-side regression tests (`tests_rust/test_combat.py`,
apply-arm layer):

- `test_apply_action_declare_blockers_menace_single_blocker_dropped`
  — apply_action on a single-blocker menace assignment leaves
  `state.blockers` empty (the retain pass drops the illegal
  block).
- `test_apply_action_declare_blockers_menace_two_blockers_retained`
  — apply_action on a two-blocker menace assignment keeps both
  blockers in `state.blockers` (multi-block satisfies CR
  702.110b).
- `test_apply_action_declare_blockers_menace_zero_blockers_unblocked`
  — apply_action with empty assignments against a menace
  attacker is a no-op; `state.blockers` stays empty.
- `test_apply_action_declare_blockers_non_menace_single_blocker_retained`
  — apply_action on a vanilla attacker + single blocker leaves
  the blocker in `state.blockers` (the menace gate must not leak
  into the default path).

Invariant: see I38 above — pins the post-loop retain as the
canonical Rust apply-arm validation contract.

**Fingerprint baselines.** Zero shifts. The change affects
mid-combat block validity, not the synthetic-state fixtures'
battlefields — the fixtures don't have menace attackers + single
blockers in their initial state. Production engine code paths
for non-menace combat are unchanged on both sides.

---

### CE17 — CLOSED by `feature/ce17-defender-legal`

**Status**: closed 2026-05-12 via Option A (Rust-side convergence
on Python), per Phase 5 convention "converge Rust toward Python,
never modify Python". Closure invariant lives at **I40** below.

The xfail-strict symptom pin
`test_cross_engine_defender_selector_legal_decisions_surfaces_ce17`
was renamed to
`test_cross_engine_defender_selector_legal_decisions_excludes_defender`
and the `@pytest.mark.xfail(strict=True, ...)` decorator removed,
flipping it from xfail-pass to a regular regression pin. The test
was both the strict-xfail and the symptom-pin (the CE17 probe shipped
a single combined test rather than the CE2-CE16 pair-pin pattern, so
there is no separate companion symptom-pin to delete).

One new Rust-side regression test in `tests_rust/test_legal.py`:
`test_legal_decisions_declare_attackers_defender_creature_excluded`
— builds a 2-creature p0 battlefield (Vanilla Bear + Defender Wall),
drives to DECLARE_ATTACKERS, and asserts the emitted powerset is
`{(), (bear_id,)}` (defender filtered out at enumeration time, not
just at apply).

The three apply-time clean-walk pins
(`test_cross_engine_defender_selector_defender_only_walks_clean` /
`..._both_walks_clean` / `..._normal_only_walks_clean`) and the
pre-injection backbone pin
(`test_cross_engine_defender_selector_pre_injection_walks_clean`)
continue to pass unchanged — the closure adds a filter at
enumeration time but does not affect the apply-time gate at
`state_ops_combat.rs:639-641`, which was already correct.

See I40 for the post-closure invariant pin.

---

### CE18 — CLOSED by `feature/ce18-double-strike-spillover`

**Status**: closed 2026-05-12 via Option A (Rust-side convergence
on Python), per Phase 5 convention "converge Rust toward Python,
never modify Python, regardless of CR-correctness". Closure
invariant lives at **I45** below.

The strict-xfail symptom pin
`test_cross_engine_double_strike_selector_surfaces_ce18_at_step_174`
was deleted (CE2-CE17 pair-pin convention). The strict-xfail
`@pytest.mark.xfail(strict=True, ...)` decorator on
`test_cross_engine_double_strike_selector_walks_clean` was
removed, flipping it from xfail-strict to a regular expected-pass
parity pin.

Four new Rust-side regression tests in `tests_rust/test_combat.py`:

- `test_double_strike_regular_damage_spills_to_defender_when_sole_blocker_dies_fs`
  — Test A: 2/2 DS attacker vs 2/2 vanilla blocker, sole blocker
  dies in FS, regular-pass damage spills to defender (life -2).
- `test_double_strike_regular_damage_does_not_spill_when_other_blocker_alive`
  — I45 negative branch: 3/3 DS attacker vs two 2/2 blockers; only
  the first dies in FS; the second is still alive so the
  regular-pass entry on the dead first blocker is DROPPED (not
  redirected). Defender life unchanged.
- `test_double_strike_vs_larger_blocker_mutual_death_no_spillover_regression`
  — Test B: 2/2 DS vs 4/4 blocker; blocker survives FS so regular
  entry stays on the blocker (NOT redirected); both die after
  regular pass; defender life unchanged.
- `test_double_strike_unblocked_full_damage_to_defender_regression`
  — Test C: 2/2 DS unblocked; player-target entries are never
  affected by the filter; defender takes 4.

The existing
`test_double_strike_attacker_kills_blocker_in_first_strike_step`
was also updated: its docstring + assertions now reflect the I45
spillover (defender life drops 20 → 18 after the closure; previously
the test was silent on defender life and the no-spillover behavior
was correct for the pre-CE18 model).

The four cross-engine apply-time pins (the structural-state pin,
the Test-B mutual-death pin, the Test-C unblocked pin, and the
pre-injection backbone pin) continue to pass unchanged — they were
already parity-clean pre-closure, only the walks_clean Test A pin
was the load-bearing surface.

See I45 for the post-closure invariant pin.

---

### CE19 — CLOSED by `feature/ce19-flash-instant`

**Status**: closed 2026-05-12 via Option A (Rust-side convergence
on Python), per Phase 5 convention "converge Rust toward Python,
never modify Python". Closure invariant lives at **I46** below.

The pre-closure shape-pin
`test_cross_engine_flash_test_a_surfaces_ce19` was renamed to
`test_cross_engine_flash_test_a_closes_ce19` and the assertion
flipped from "Rust does NOT emit CastSpell" to a strict
`rust_id in rust_cast_card_ids` + a stronger
`set(py_cast_card_ids) == set(rust_cast_card_ids)` both-engines-
agree pin (the set-equality catches a future over-correction
where Rust emits additional non-flash non-instant cards at the
off-active priority window — a different and larger divergence
than CE19 itself). No companion symptom-pin to delete (the probe
shipped a single shape-pin + two parity-clean sanity branches +
one walks_clean pin).

Four new Rust-side regression tests in `tests_rust/test_legal.py`
pin the four corners of the timing × flash × type matrix:

- `test_legal_decisions_flash_creature_off_active_turn_emits_cast_spell_ce19`
  — Bear Flash on p0's hand at p1's PRECOMBAT_MAIN with priority
  on p0 → CastSpell emitted via the instant-speed pass.
- `test_legal_decisions_flash_creature_own_turn_emits_cast_spell`
  — Bear Flash on p0's own main phase → CastSpell emitted (was
  already passing pre-closure via sorcery-speed pass); also pins
  the no-double-emission invariant via shared seen_castspell
  HashSet (count == 1).
- `test_legal_decisions_vanilla_creature_off_active_turn_omits_cast_spell_ce19`
  — Vanilla 2/2 on p0's hand at p1's turn with p0 priority → NO
  CastSpell (over-correction guard).
- `test_legal_decisions_instant_off_active_turn_emits_cast_spell_ce19`
  — Printed Instant on p0's hand at p1's turn with p0 priority →
  CastSpell emitted via the is_instant clause of the per-card
  gate (distinct from the flash-keyword arm).

The three companion parity-clean sanity pins
(`test_cross_engine_flash_test_b_own_turn_main_phase_parity` /
`...test_c_vanilla_off_turn_negative_parity` /
`..._selector_pre_injection_walks_clean`) continue to pass
unchanged — they were parity-clean pre-closure (B: both emit at
sorcery timing; C: neither emits at off-active vanilla; pre-
injection: backbone has no flash divergence to surface).

See I46 for the post-closure invariant pin.

### CE20 — CLOSED by `feature/ce20-activated-substrate`

**Status**: closed 2026-05-12 via Option A (Rust-side convergence
on Python), per Phase 5 convention "converge Rust toward Python,
never modify Python, regardless of CR-correctness". Closure
invariant lives at **I48** below.

The two load-bearing shape-pins
`test_cross_engine_activated_cost_test_a_surfaces_ce20` and
`test_cross_engine_activated_cost_test_c_apply_dispatch_surfaces_ce20`
were renamed to
`test_cross_engine_activated_cost_test_a_emission_parity_post_ce20_closure`
and
`test_cross_engine_activated_cost_test_c_apply_dispatch_parity_post_ce20_closure`
and their assertions flipped from "Rust does NOT emit / Rust
raises 'has no mana_produced'" to "Rust DOES emit / Rust apply
succeeds + cross-engine field-view convergence on tap state +
mana pool + stack". Test D was kept as a pin on the
"Python-doesn't-self-gate, Rust-DOES-self-gate" axis with the
raise message updated to the new
"unaffordable from controller's mana pool" shape. Test B
(no-affordance both-engines-don't-emit) and the pre-injection
clean-walk pin continue to pass unchanged.

Twelve new Rust-side regression tests in `tests_rust/test_activated.py`:

- 4 parser-surface pins (default empty Vec, full Bear Caster parse,
  default zero mana cost, unknown cost-key raise).
- 4 apply-path pins (succeeds with pool, raises on empty pool,
  raises on already-tapped source, raises on summoning-sick source).
- 4 emission-path pins (emits when affordable + untapped + non-sick,
  no emission when pool empty / tapped / sick).

Four existing `tests_rust/test_actions.py` tests updated to the new
error-message shape ("has no ability at index N" replaces the old
"only ability_index=0" / "no mana_produced" raises for Forest at
non-zero index and Grizzly Bears at any index).

See I48 for the post-closure invariant pin.

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
