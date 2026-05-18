# G7 Slice S3 — verify-first finding (priority / response windows)

**Date:** 2026-05-17
**Branch:** `feature/g7-s3-priority-windows` off `main @ 9e884681`
**Outcome:** **CLEAN-VERIFY NO-OP** — no `rust/src/` change. The
design-doc S3 hypothesized priority-reset fix was **already landed by
S1** (`5803aea7`). Live source CONTRADICTS the brief's pre-S1 quote.
This is a valid S3 outcome (same class as S2/B1 honest clean-verifies)
— no diff was manufactured.

---

## 1. What the brief / design doc hypothesized

The brief's central S3 hypothesis (echoing the design doc
`RUST_STACK_RESOLUTION_DESIGN.md:386-397`):

> The **high-probability concrete Rust fix** is the cast-time priority
> reset. `cast_creature`'s `priority_player = active_player` reset
> (`state_ops_cast.rs:~563`) made sense for the old no-stack / atomic
> semantics but is WRONG for stack semantics; the docstring at
> `state_ops_cast.rs:~551-562` EXPLICITLY anticipates this — *"A future
> stack-using cast slice will need to re-think when the reset fires"*.
> S3 likely fixes this ordering.

The brief itself flagged the verify-first exit: *"If live source
CONTRADICTS the design doc's S3 (e.g. the reset is already correct
post-S1 ...), STOP, write `G7_S3_VERIFY_FINDING.md`, report — do not
force."*

## 2. The stale-text correction (verified)

- The quoted docstring *"A future stack-using cast slice will need to
  re-think when the reset fires (after the cast push? or after the
  resolution pop?)"* exists **only at `6b3e5565^`** — i.e. PRE-S1
  (`git show 6b3e5565^:rust/src/state_ops_cast.rs`, lines 555-560).
- **S1 (`6b3e5565`, merged `5803aea7`) already deleted that open
  question and replaced it with a definitive resolution.** Live
  `state_ops_cast.rs:621-630` (post-S1, on `main @ 9e884681`):

  > *"The cast push (not the resolution pop) is the reset moment,
  > matching Python: the priority loop resets priority via the
  > post-non-pass-action path (`simulate.py:274-282`) when the cast is
  > applied, then resets again after the eventual resolution
  > (`simulate.py:266-267`). The post-cast reset here is the first of
  > those two; the post-resolution reset is the loop's job (S3 verifies
  > the priority-round composition end-to-end)."*

So the brief's quoted phrase is **stale** — S1 already re-thought the
reset and landed the answer. The design doc's S3 section (lines
386-397) is itself a pre-S1 hypothesis the S1 lane superseded.

## 3. Verified live-source priority/resolution sequence (the byte-equal proof)

### 3.1 Python SoT — `simulate.py:priority_loop` (231-282)

- `_next_alive` (simulate.py:46-52): walk `+1 mod n` from `start_idx`,
  skip `has_lost`, all-lost → `start_idx`.
- Loop init (`:235`): `priority_idx = _next_alive(state,
  state.active_player_idx)`.
- All-pass + non-empty stack (`:254-267`): `resolve_top_of_stack` →
  `state_based_actions` → `pass_count = 0; priority_idx =
  _next_alive(state, state.active_player_idx)` — **priority resets to
  active AFTER resolution**.
- Non-pass action (`:274-282`): `apply_action` →
  `state_based_actions` → `pass_count = 0; priority_idx =
  _next_alive(state, state.active_player_idx)` — **priority resets to
  active AFTER the action**.

Python **never resets priority at cast-push**; the reset is a
consequence of the loop running after `apply_action` returns.

### 3.2 Rust adapter loop — `rust_engine_adapter.py:_run_priority_action` (421-511)

This is the **production** Rust-driver loop (NOT the pop-only G3
composer `complete_step_via_priority_round` — confirmed it drains via
the effect-dispatching `resolve_top_of_stack` at `:442`).

- Non-pass branch (`:494-511`): `self._rust.apply_action(d)` →
  `apply_sbas()` → `self._reset_priority_to_active()` (`:510-511`).
  Comment `:507-509`: *"CR 117.3c / engine_adapter.py:985-987:
  priority returns to the active player after any non-pass action.
  Rust's apply_action does not guarantee this; mirror it."*
- Resolution branch (`:434-444`): `resolve_top_of_stack()` →
  `apply_sbas()` → `self._reset_priority_to_active()` (`:444`).
- `_reset_priority_to_active` (`:300-326`): target =
  `self._next_alive_idx(int(self._rust.active_player_idx))`;
  `_next_alive_idx` (`:244-272`) is a documented byte-exact port of
  Python `simulate._next_alive`.

### 3.3 Why the cast-push reset is redundant, NOT divergent

`cast_creature`'s `self.priority_player = self.active_player`
(`state_ops_cast.rs:633`) — and the identical resets in
`cast_creature_warp` (`:810`) / `cast_spell_noncreature` (`:1030`) —
fires INSIDE `apply_action`. The adapter's non-pass branch then
**immediately overwrites `priority_player`** via
`_reset_priority_to_active()` (`:511`) the instant `apply_action`
returns — to exactly Python's `_next_alive(active_player_idx)` target,
at exactly Python's `simulate.py:282` post-non-pass-action reset point,
**before any STATE_EQ / LEGAL_SET_EQ compare point** (per-apply
compare). So the engine-side cast-push reset is dead/redundant for the
cross-engine path; it cannot diverge because the adapter loop's reset
is the authoritative one and it byte-mirrors Python.

Post-resolution, the adapter loop's `_reset_priority_to_active()`
(`:444`) byte-mirrors Python's `simulate.py:266-267`.

### 3.4 Response-window legal-set emission composes (I46 + C1)

- `state_ops_legal.rs` instant-speed CastSpell pass (`:1454-1507`) is
  gated **per-card** on `is_instant || has_flash`, run BEFORE the
  sorcery-timing gate (`is_sorcery_timing` requires
  `self.stack.is_empty()`, `:1450-1452`). A permanent spell on the
  stack does NOT suppress the opponent's instant-speed `CastSpell`
  emission — the response window emits correctly (I46 two-pass).
- The C1 keystone (Slice 1 mana `f1f09bbb`, Slice 2 target-
  satisfiability `e6e3db58`, Slice 3 additional-cost `bb29df8d`) is
  **all in `main @ 9e884681` ancestry** (verified via
  `git merge-base --is-ancestor`). Slices 1/2 are woven into the
  emission gate (`state_ops_legal.rs:1508,1520`). So S3's
  response-window LEGAL_SET_EQ does NOT trip on a known-open C1 axis —
  the design's sequencing precondition is satisfied. **B1 is DONE.**

## 4. Conclusion

The design-doc S3 scope is **CONTRADICTED** by live source on the
"high-probability Rust fix" point: the cast-push priority reset is NOT
a divergence (S1 already resolved the open question and the adapter
loop is the byte-equal authority). The response-window machinery
(adapter loop priority/resolution sequencing + I46 instant-speed
emission + C1 mana/target gating) is **already present and composes**.

**S3 lands as a clean-verify no-op** + the design-named deliverable:
the first real **nested-response-window cross-engine pin** (opponent
casts an instant in response to a permanent spell on the stack — both
engines agree on the legal set at the response window AND the resolved
LIFO order). No `rust/src/` change → no `.pyd` rebuild → no residue
cadence.

## 5. Next divergence / S4 follow-up (NOT unmasked here — flagged)

S3 does NOT unmask a new divergence (the sequence is byte-equal). The
design's own S4 scope is the next owed piece and is unaffected by this
clean-verify:

- **S4 owns** `cast_creature_warp` (`state_ops_cast.rs:691-869`) —
  still atomic (`move_*_to_battlefield` at `:785-790`, NOT stack-pushed)
  + the rider/provenance deferral (warp / impending / room /
  cast-from-X). The S2 boundary pin
  (`test_s2_non_creature_permanent_cannot_be_stacked_boundary`) still
  guards the non-creature-permanent `&& creature` summoning-sick guard
  + absent resolve-time aura attach as S4 territory.
- S5 (triggers-on-stack) is largely present (verification).

The full C4 / `rust_shadow` bake-in is NOT expected clean post-S3 (S4
warp + S5 trigger pieces still owe); but the post-cast
priority/resolution SEQUENCE is byte-equal, so the bake-in gets
materially past the G7 cast-resolve trip for the creature case.
