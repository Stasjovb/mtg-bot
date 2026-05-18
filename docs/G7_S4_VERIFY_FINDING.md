# G7 Slice S4 — verify-first finding

**Date:** 2026-05-17
**Branch:** `feature/g7-s4-warp-riders`
**Base:** `main` @ `cd3a5f4e`
**Scope:** `cast_creature_warp` stack-push + warp-rider/provenance
resolve-deferral (the design doc's S4 owner section, lines 438-468 of
`docs/RUST_STACK_RESOLUTION_DESIGN.md`).

## Outcome: S4 scope CONFIRMED against live source. Implemented (not a clean-verify, not contradicted).

`cast_creature_warp` IS still atomic on `main`. The design doc's S4
hypothesis holds; the S1 stack-push pattern transfers cleanly with NO
structural change and NO `state.rs` field addition. The
non-creature-permanent boundary is genuinely a **distinct slice
(S4b)** — flagged, NOT folded in; the S2 tripwire stays as-is.

## 1. `cast_creature_warp` is STILL ATOMIC (design CONFIRMED)

`rust/src/state_ops_cast.rs:691-813` (live @ `cd3a5f4e`):

- `:785-790` — moves the card to the battlefield INSIDE the primitive
  via `move_from_hand_to_battlefield` (hand arm) /
  `move_from_graveyard_to_battlefield` (Timeline-Culler gy arm).
- `:791-807` — stamps `summoning_sick = true` AND
  `warp_exile_pending = true` on the just-moved battlefield object at
  cast time.

This is the exact pre-S1 shape S1 removed from `cast_creature`. The
design doc's S4 scope (apply the S1 stack-push shape; defer the
bf-entry-coupled riders to resolve) is confirmed, not contradicted.

## 2. Python rider split (SoT — verified `actions.py:1361-1560`, `:2969-3027`)

**Cast-time, genuinely (stays at cast time — Python `_cast_spell`):**

- `state.spell_warped_this_turn = True` — `:1427` (hand) / `:1457`
  (graveyard). A `GameState` bool, not per-object.
- Warp life-cost debit `p.life -= life_cost` — `:1432` / `:1460`.
- Card removed from source zone; `card.zone = STACK`; StackItem
  appended — `:1403`/`:1450`, `:1751-1767`.
- `WarpExileSelf` delayed trigger scheduled — `:1550-1559`.

**Resolve-time (Python `put_into_battlefield`):**

- `obj.summoning_sick = True` — `:2993` (UNCONDITIONAL for all
  permanents in Python; Rust gates `&& creature` — see §4).
- Impending time-counter init from `cast_via_impending` — `:3004-3007`.
- Patched-Plaything `cast_via_hand` -1/-1 — `:3018-3027`.

## 3. Rider-field inventory + the key risk — RESOLVED structurally

`GameObject` (`state.rs:34-219`) carries `warp_exile_pending` (`:207`)
and `warped` (`:218`). It does NOT carry `cast_via_impending`,
`cast_via_hand`, `time_counters`, or any room-half field.

**Rust does not implement `use_impending` or `cast_room_half` at
all.** The legal emitter hard-codes `use_impending: false` /
`cast_room_half: None` (`state_ops_legal.rs:511-513`); the
`Action::CastSpell` dispatch explicitly ignores both
(`state_ops_actions.rs:292-293`, documented deferred plumbing). They
are pre-existing separately-deferred plumbing, NOT riders S4
introduces a defer for — there is nothing for S4 to move to resolve
for impending/room because the cast surface never reaches them. **S4's
actual live rider surface is exactly `warp_exile_pending`** (plus
`summoning_sick`, already resolve-time via S1's
`move_source_post_resolve`).

**Key risk (design §"Risk") — RESOLVED with no structural change.**
The `warp_exile_sweep_on_end_step` (`state_ops_steps.rs:365`) keys off
the **battlefield object's** `warp_exile_pending` flag. Rust's
spell-stack model keeps the stack-resident source object alive in its
origin zone (hand / graveyard) until resolution; `take_source`
(`state_ops_resolve.rs:230-245`) moves the WHOLE owned `GameObject`
(fields intact, nothing reset) and `move_source_post_resolve`
(`:285-332`) pushes it to the battlefield. So stamping
`warp_exile_pending = true` on the **stack-resident source object at
cast time** makes the flag ride through resolution onto the
post-resolution battlefield object — exactly where the end-step sweep
reads it. No new field, no StackItem rider slot, no `state.rs`
serialization touch. This is the direct mirror of S1's exile-recast
zone-normalization pattern (S1 stamped/cleared object fields on the
stack-resident source at cast time and let resolution carry them).

## 4. Non-creature-permanent boundary — DISTINCT SLICE (S4b), NOT folded in

**Decision: flag as S4b. Keep `tests_rust/test_resolve.py::
test_s2_non_creature_permanent_cannot_be_stacked_boundary` exactly
as-is (loud honest tripwire).**

Rationale (verify-first):

- S4's design-doc scope (lines 438-468) is strictly
  `cast_creature_warp` (a creature-gated primitive) + warp/impending/
  room riders. "Rust files touched" is `state_ops_cast.rs`
  (`cast_creature_warp`) + `state_ops_resolve.rs` (rider consumption)
  — no new cast primitive, no aura-attach subsystem.
- Opening bare Enchantment / Artifact / Planeswalker / Aura casting
  requires a NEW cast-primitive-routing path: such a permanent falls
  through BOTH `cast_creature` (Creature-gated, `:541-542`) and
  `cast_spell_noncreature` (Instant|Sorcery-gated). That is a
  *separate cast-primitive-routing problem*, structurally orthogonal
  to warp-rider deferral.
- Closing it ALSO requires resolve-time aura attachment (Python
  `actions.py:2720-2758`) — a whole `attached_to`-at-resolve
  subsystem Rust does not have on the resolve path — plus flipping
  the `move_source_post_resolve` `&& creature` guard (`:301-303`) to
  Python's unconditional all-permanent `summoning_sick`.
- Folding all of that in would materially broaden S4 well beyond the
  warp-rider scope. The brief's explicit guard ("If it materially
  broadens S4 ... or reveals a separate cast-primitive-routing
  problem, do NOT force it — honest-flag it as its own slice (S4b)")
  applies squarely.

The S2 tripwire remains the honest signal: when a future **S4b** opens
non-creature-permanent casting, its `assert ... is False` flips and
that lane is forced to fix the guard + add resolve-time aura attach
(new-code-is-right). S4 does NOT touch it, does NOT weaken it.

## 5. What S4 implements

- `cast_creature_warp`: removed the atomic bf move + cast-time
  `summoning_sick`/`warp_exile_pending` stamps. It now pays
  `warp_cost`, debits the warp life rider, sets
  `state.spell_warped_this_turn = true` (all genuinely cast-time per
  Python), normalizes the graveyard-warp source graveyard→hand at
  cast time (the S1 exile-recast normalization pattern — so the
  stack-resident source is findable by `find_source_printing_id` /
  `take_source`, which do NOT search the graveyard's warp arm... see
  note), stamps `warp_exile_pending = true` on the stack-resident
  source object, fires `Event::Cast`, pushes a bare
  `StackItem::new_spell`, resets priority/passes, returns WITHOUT
  resolving. `summoning_sick` + the bf entry + ETB now happen at
  resolution via the already-present `move_source_post_resolve` +
  `resolve_top_of_stack` (byte-mirroring Python's
  `put_into_battlefield`), and `warp_exile_pending` rides the source
  object onto the post-resolution bf object so the end-step sweep
  still keys off the right object.
- `move_from_exile_to_battlefield` / `move_from_graveyard_to_
  battlefield` are now both S4-dead for the warp cast path
  (`#[allow(dead_code)]`, retained — same treatment S1 gave the
  exile helper; the warp-from-graveyard source instead normalizes
  graveyard→hand at cast time, exactly like S1's exile→hand).

Note: `find_source_printing_id` / `take_source` search hand /
library / battlefield / graveyard (`state_ops_resolve.rs:205-245`).
The graveyard IS searched, so a graveyard-warp source could in
principle resolve straight out of the graveyard. BUT Python removes
it from the graveyard at cast time (`:1450`) and the card sits on the
STACK (in Rust's model, in a stack-resident zone). To byte-match
Python's "card left the graveyard at cast time" and keep the
spell-stack source model uniform with the hand arm + S1's exile-recast
precedent, the graveyard-warp source is normalized graveyard→hand at
cast time (same shape as S1's exile→hand normalization). Verified
byte-equal cross-engine by the existing
`test_r72_warp_phase2_bridge_graveyard_cast_lifecycle_byte_equal`
`step_both` lifecycle test (1532 gate) + the new
`test_g7s4_*` direct-shape probes.

## 5b. rust_shadow on a warp deck — VERIFIED finding

Driving the role-swapped `ShadowCheckedRustAdapter` over a synthetic
warp deck (`_r63_warp_synth_deckspec`) with the uniform-random driver
(seed 2026):

- **S4 does NOT regress the bake-in.** The run is divergence-clean
  over the bounded prefix (≥200 steps) BEFORE the pre-existing
  step-220 trip point — **byte-identical to `main` @ `cd3a5f4e`**
  (verified by reverting `state_ops_cast.rs` to HEAD, rebuilding,
  re-running: same seed, same first-divergence step 220, same
  error string). An atomic-vs-stack warp-cast STATE_EQ regression
  would have fired MUCH earlier; it does not.
- **The step-220 divergence is pre-existing + main-identical + a
  SEPARATE axis.** It is a `LEGAL_SET_EQ` on a warp `cast_spell`
  **OFFER** (`rust\py=[('cast_spell',0,True,...)] py\rust=[]`) — a
  legal-EMISSION asymmetry (Rust offers a warp cast the Python
  shadow's legal set does not). The random driver never even
  *applies* a warp cast because the legal set diverges first. This
  is the I20/G4-class warp legal-emission axis, owned by a later
  slice (S5+/legal-emission), **NOT S4's resolve-shape scope**. S4
  owns and proves byte-equal the warp-cast resolve SHAPE (the direct
  `apply` + `step_both` cross-engine probes).
- **Honest-stop, pinned not papered.**
  `test_g7s4_rust_shadow_warp_deck_clean_prefix_then_known_legal_emit_gap`
  asserts BOTH the S4-non-regression (clean prefix ≥200) AND that
  the known pre-existing divergence is SURFACED at its characterized
  boundary (`LEGAL_SET_EQ` + `cast_spell` in the error). If a later
  slice closes the warp legal-emission axis, the
  `raised is not None` assertion flips and the pin must be updated
  to the closed contract (new-code-is-right). The S4 brief's "S4 is
  NOT expected to make the full C4/rust_shadow bake-in clean — S5/S6
  still owe pieces" is exactly this: S4 made the warp-cast resolve
  shape stack-then-resolve byte-equal; the warp legal-emission
  parity is S5+ territory.

## 6. Discipline / scope confirmations

- `rust/src/` touched: `state_ops_cast.rs` ONLY (state_ops-only —
  does NOT fire the cards.rs residue cadence per CFI-1). No
  `state.rs` / serialization touch (no new field).
- CE5 (`cross_engine.py`) NOT touched (S7).
- The pop-only G3 composer `complete_step_via_priority_round` NOT
  wired through.
- S5 follow-up the design implies: with permanent (incl. warp)
  spells now resolving via `resolve_top_of_stack` →
  `move_source_post_resolve` → `dispatch_event(Enters)`, S5 verifies
  ETB-trigger-on-stack push ordering vs Python `put_into_battlefield`
  + respond-to-trigger nested windows for the warp/permanent case
  (largely already present; verification slice).
