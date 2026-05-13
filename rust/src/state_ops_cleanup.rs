//! Cleanup-step primitives on `GameState`.
//!
//! Filled in by a TDD-slice branch (see `tests_rust/README.md`).
//! Stub block exists so other slices can grow `GameState` in
//! parallel without conflicting on a single `#[pymethods]` block.
//!
//! First-slice scope: hand-size limit enforcement at cleanup
//! (CR 514.1 — discard down to maximum hand size, default 7).
//! Composes with state_ops_library's `discard` and the round-2
//! `state_ops_steps`'s phase encoding.
//!
//! Round-8 extension: a composition primitive
//! `cleanup_step_for_active_player()` that runs the two halves of
//! CR 514 we model — hand-size discard (514.1) for the active
//! player followed by clearing all marked damage (514.2) on both
//! players' battlefields. Returns a summary dict
//! `{"discarded": N, "damage_cleared": M}` so callers can log /
//! assert the per-step counts without re-walking zones.
//!
//! Ordering: hand-size discard FIRST, then damage clearance — the
//! numbered sub-rules of CR 514 execute in order (514.1 before
//! 514.2). Mirrors the source-of-truth `run_cleanup_step` in
//! `src/mtg_bot/turn.py` (hand-size while-loop precedes the
//! damage-clear loop). Matters once "discard triggers" arrive: a
//! hand-size discard could trigger an ability that pings a
//! creature, and that ping's damage is then cleared by 514.2 in
//! the same cleanup step.
//!
//! Round-27 extension (UEOT framework): CR 514.3 "until end of turn"
//! effects expiration now fires inside `cleanup_step_for_active_player`
//! AFTER CR 514.1 (hand-size discard) and CR 514.2 (damage clear). The
//! shape:
//!  - walk both players' battlefield zones
//!  - for each object whose `ueot_modifiers` is non-empty, route through
//!    `Arc::make_mut` (skipping the clone when every object on the
//!    battlefield is UEOT-clean) and drain its modifiers Vec.
//! See `clear_ueot_modifiers_all` for the primitive and the round-27
//! brief for the full architectural framing. This closes parity gap G7.
//!
//! Out of scope (CR 514.4):
//!  - 514.4 "no abilities triggered? skip the second cleanup step"
//!    — composes with triggered-ability machinery.
//!
//! ## Discard target choice (deterministic — stepping-stone)
//!
//! ## Discard target choice (deterministic — stepping-stone)
//!
//! Real MTG: when forced to discard at cleanup, the active player
//! chooses which cards to discard. This slice's primitive deterministically
//! pops from the END of the hand Vec (most recently drawn). Once the
//! search side has a discard-decision node, a future slice can take
//! a vector of obj_ids to discard rather than picking blindly. The
//! deterministic choice is good enough for state-evolution parity
//! tests today and lets the cleanup step make forward progress in
//! search rollouts. See the same shortcut in
//! `src/mtg_bot/turn.py:run_cleanup_step` (`ap.hand.pop()` with no
//! decision node), which is what we're matching.
//!
//! ## CoW
//!
//! Mutates two zones (hand + graveyard) on the same player. Both
//! routed through `Arc::make_mut`, preserving the CoW invariant.
//! `test_clone_then_discard_does_not_affect_original` is the canary.
//! The round-8 composition adds a third mutation — battlefield
//! damage markers — so its CoW canary
//! (`test_clone_then_cleanup_does_not_affect_original`) extends the
//! check across all three.
//!
//! ## Cross-slice composition (inlined logic)
//!
//! `cleanup_step_for_active_player` ought to delegate to the
//! existing `enforce_hand_size_limit` (this file) and
//! `clear_all_damage` (state_ops_damage.rs). PyO3's
//! `multiple-pymethods` lets the two `#[pymethods]` blocks coexist
//! but the methods stay Rust-private to their owning modules.
//! `enforce_hand_size_limit` is callable from this file (same
//! module) but `clear_all_damage` is not — so the damage half is
//! INLINED here, mirroring the two-loop shape of
//! `state_ops_damage.rs::clear_damage_for_player` (skip
//! Arc::make_mut when no permanent has damage; one CoW clone
//! covers the per-player sweep). Same friction the round-7
//! counterspell agent and the round-2 untap-step composition
//! described — until parallel-slice constraints relax, the
//! duplication is deliberate. A follow-up consolidation can promote
//! `clear_all_damage` to `pub(crate)` (or factor into a free
//! function) and wire this primitive through it.

use crate::state::{GameObject, GameState};
use crate::state_ops_steps::PHASE_CLEANUP;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::sync::Arc;

#[pymethods]
impl GameState {
    /// Enforce the hand-size limit for `player_id`: while the hand
    /// is larger than `max_hand_size`, pop a card from the end of
    /// hand and push it onto that player's graveyard. Returns the
    /// number of cards discarded.
    ///
    /// Validates `player_id` is in `[0, 1]` and `max_hand_size >= 0`;
    /// raises `ValueError` otherwise. (No silent no-op — invalid
    /// inputs at this layer indicate a caller bug.)
    ///
    /// CoW-safe: each zone mutation routes through `Arc::make_mut`,
    /// so cloning a `GameState` and then enforcing on the clone
    /// leaves the source's hand and graveyard untouched.
    fn enforce_hand_size_limit(
        &mut self,
        player_id: u8,
        max_hand_size: i32,
    ) -> PyResult<usize> {
        if player_id >= 2 {
            return Err(PyValueError::new_err(format!(
                "player_id must be 0 or 1, got {player_id}"
            )));
        }
        if max_hand_size < 0 {
            return Err(PyValueError::new_err(format!(
                "max_hand_size must be >= 0, got {max_hand_size}"
            )));
        }
        let max = max_hand_size as usize;
        let idx = player_id as usize;
        let player = &mut self.players[idx];
        let current = player.hand.len();
        if current <= max {
            return Ok(0);
        }
        let to_discard = current - max;
        // Mutating both zones: route each through Arc::make_mut so
        // the CoW invariant holds.
        let hand = Arc::make_mut(&mut player.hand);
        let mut popped: Vec<crate::state::GameObject> = Vec::with_capacity(to_discard);
        for _ in 0..to_discard {
            // pop() from the END of the Vec — see module docstring
            // on the deterministic-choice stepping-stone.
            let mut obj = hand
                .pop()
                .expect("hand.len() > max guaranteed by current > max check above");
            obj.zone = crate::state_ops_zones::ZONE_GRAVEYARD;
            popped.push(obj);
        }
        let graveyard = Arc::make_mut(&mut player.graveyard);
        for obj in popped {
            graveyard.push(obj);
        }
        Ok(to_discard)
    }

    /// Round-27 UEOT framework primitive — clear every UEOT modifier
    /// on every battlefield permanent (CR 514.3). Returns the number
    /// of objects whose `ueot_modifiers` Vec was non-empty before
    /// draining. Skips the `Arc::make_mut` clone on a battlefield
    /// where no permanent has any UEOT modifier — the warm path
    /// (no UEOT effect active at end-of-turn) pays zero allocation.
    ///
    /// Callable independently for tests that want to assert the
    /// UEOT-clear in isolation from the hand-size + damage-clear
    /// passes; `cleanup_step_for_active_player` also fires this
    /// AFTER CR 514.1 + CR 514.2 (the CR 514 numbered-rule order).
    ///
    /// **Closeable parity gap**: this is the round-27 closure of G7.
    fn clear_ueot_modifiers_all(&mut self) -> usize {
        let mut cleared: usize = 0;
        for player in self.players.iter_mut() {
            // Warm-path skip: nothing to clear on this battlefield.
            if player
                .battlefield
                .iter()
                .all(|o| o.ueot_modifiers.is_empty())
            {
                continue;
            }
            let zone: &mut Vec<GameObject> = Arc::make_mut(&mut player.battlefield);
            for obj in zone.iter_mut() {
                if !obj.ueot_modifiers.is_empty() {
                    cleared += 1;
                    obj.ueot_modifiers.clear();
                }
            }
        }
        cleared
    }

    /// Run the cleanup step for the current `active_player` —
    /// composition of CR 514.1 (hand-size discard, max=7 hard-coded),
    /// CR 514.2 (clear all marked damage on both battlefields), and
    /// CR 514.3 (until-end-of-turn modifier expiration).
    ///
    /// Order: hand-size discard FIRST, damage clearance second,
    /// UEOT-modifier expiration third (matches CR 514's numbered
    /// sub-rules and the source-of-truth loop in
    /// `src/mtg_bot/turn.py:run_cleanup_step`). See module docstring
    /// on why ordering matters.
    ///
    /// Returns a Python dict `{"discarded": N, "damage_cleared": M,
    /// "ueot_cleared": K}`:
    /// - `discarded`: number of cards moved from active player's
    ///   hand to graveyard (0 if hand was already <= 7).
    /// - `damage_cleared`: count of permanents (across both
    ///   battlefields) whose marked damage was non-zero before the
    ///   call. A no-op cleanup (no damage anywhere) reports 0.
    /// - `ueot_cleared`: count of permanents (across both
    ///   battlefields) whose `ueot_modifiers` Vec was non-empty
    ///   before draining. Round-27 addition.
    ///
    /// Hard-codes max-hand-size = 7 because every active-player
    /// cleanup in canonical MTG uses 7. The lower-level
    /// `enforce_hand_size_limit(player_id, max)` stays available for
    /// callers that need a different cap (Reliquary Tower sentinel
    /// once we add a no-max representation).
    ///
    /// Does NOT advance the phase or check whether the engine is
    /// actually IN the cleanup phase — the caller picks when to
    /// fire this. Same shape as the round-2 untap composition: a
    /// primitive that the phase machinery layers on top of, not
    /// the phase-transition itself.
    fn cleanup_step_for_active_player<'py>(
        &mut self,
        py: Python<'py>,
    ) -> PyResult<Bound<'py, PyDict>> {
        // (1) CR 514.1 — hand-size discard for the active player.
        let active = self.active_player;
        let discarded = self.enforce_hand_size_limit(active, 7)?;

        // (2) CR 514.2 — clear all marked damage on both battlefields.
        // Inlined per the cross-slice composition note in the module
        // docstring. Two-pass shape per player: first count the
        // permanents with non-zero damage (so the summary is
        // accurate), then if any, route through `Arc::make_mut`
        // exactly once and zero them in place. Skipping the CoW
        // clone when nothing has damage matches the optimization
        // in `state_ops_damage.rs::clear_damage_for_player`.
        let mut damage_cleared: usize = 0;
        for player in self.players.iter_mut() {
            let count = player.battlefield.iter().filter(|o| o.damage != 0).count();
            if count == 0 {
                continue;
            }
            damage_cleared += count;
            let zone: &mut Vec<GameObject> = Arc::make_mut(&mut player.battlefield);
            for obj in zone.iter_mut() {
                obj.damage = 0;
            }
        }

        // (3) CR 514.3 — drain every UEOT modifier on every
        // battlefield permanent (round-27 closure of parity gap G7).
        // Same CoW shape as the damage-clear pass — skip the
        // `Arc::make_mut` clone when no object has any UEOT modifier.
        let mut ueot_cleared: usize = 0;
        for player in self.players.iter_mut() {
            if player
                .battlefield
                .iter()
                .all(|o| o.ueot_modifiers.is_empty())
            {
                continue;
            }
            let zone: &mut Vec<GameObject> = Arc::make_mut(&mut player.battlefield);
            for obj in zone.iter_mut() {
                if !obj.ueot_modifiers.is_empty() {
                    ueot_cleared += 1;
                    obj.ueot_modifiers.clear();
                }
            }
        }

        // (4) ETB-trigger Slice 1 — reset the once-per-turn ledger
        // so any `once_per_turn = true` triggered ability becomes
        // re-fireable next turn. Mirrors Python's
        // `state.once_per_turn_fired.clear()` at cleanup.
        // Substrate-only in Slice 1: no Slice-1 trigger fixture
        // uses the gate, but the reset is part of the substrate
        // contract.
        self.triggered_this_turn.clear();

        // (5) CE20 Slice 5 (Walker loyalty Slice C) — reset the
        // once-per-turn-per-walker ledger so every walker becomes
        // re-activatable next turn. CR 606.3 is "this turn"-scoped;
        // the cleanup step is the natural reset point (same site as
        // the ETB once-per-turn ledger above). A walker that died
        // mid-turn has a stale ledger entry that survives until
        // here; the clear is unconditional (cheaper than walking
        // bf to filter-stamp).
        self.loyalty_activated_this_turn.clear();

        let d = PyDict::new(py);
        d.set_item("discarded", discarded)?;
        d.set_item("damage_cleared", damage_cleared)?;
        d.set_item("ueot_cleared", ueot_cleared)?;
        Ok(d)
    }

    /// **Round-17: end-of-turn wrap composition primitive.** Run the
    /// cleanup step for the current active player, then advance phase
    /// to the NEXT turn's UNTAP step. After this returns:
    ///
    /// - `turn_number` is incremented by 1
    /// - `phase` is `PHASE_UNTAP` (0)
    /// - `active_player` is swapped (CR 500.7 — turn rolls to the
    ///   non-active player at the cleanup -> untap wrap)
    /// - every permanent on the battlefield has its marked damage
    ///   zeroed (CR 514.2)
    /// - the previously-active player's hand is at most 7 cards (CR 514.1)
    /// - the new active player's permanents have lost summoning
    ///   sickness (CR 302.1, fired automatically by `advance_phase`'s
    ///   round-14 untap-step hook)
    ///
    /// Composes:
    /// 1. `cleanup_step_for_active_player()` (same file — handles
    ///    CR 514.1 hand-size + CR 514.2 damage clear)
    /// 2. `set_phase(PHASE_CLEANUP)` to land on cleanup
    /// 3. `advance_phase()` to wrap CLEANUP -> UNTAP, which fires:
    ///    - turn-counter bump
    ///    - active-player swap
    ///    - the round-2 untap sweep on the new active player
    ///    - the round-14 summoning-sick clear on the new active player
    ///
    /// Order matters: `cleanup_step_for_active_player` is keyed on
    /// `self.active_player` which is the OLD active player (the one
    /// whose turn is ending), so the cleanup must run BEFORE the
    /// CLEANUP -> UNTAP wrap flips active. Setting phase to CLEANUP
    /// first ensures `advance_phase`'s `phase == PHASE_CLEANUP` branch
    /// fires the wrap regardless of the engine's prior phase — callers
    /// can invoke `end_turn_and_start_next` from any phase to skip
    /// straight to the next turn's UNTAP.
    ///
    /// **Cross-file dispatch (round-16 `Bound<'_, Self>` pattern).**
    /// `advance_phase` is defined in `state_ops_steps.rs` and is
    /// Rust-private to that module under `multiple-pymethods` (E0624
    /// if called as `self.advance_phase()` from this file). The fix is
    /// to take `Bound<'_, Self>` rather than `&mut self` and dispatch
    /// through the Python attribute layer with `call_method0`. PyO3's
    /// `Bound<T>` is a borrow-checked handle to the Python object;
    /// `borrow_mut()`'s cost is identical to the borrow the
    /// `#[pymethods]` macro would have generated. See
    /// `state_ops_stack.rs::process_stack_until_empty` for the
    /// reference implementation.
    ///
    /// `cleanup_step_for_active_player` lives in this same file so a
    /// direct `borrow_mut().cleanup_step_for_active_player(py)?` call
    /// is allowed; routing it through `call_method0` keeps the dispatch
    /// shape uniform with the cross-file `advance_phase` call. We use
    /// `call_method0` for both for consistency.
    fn end_turn_and_start_next(slf: Bound<'_, Self>) -> PyResult<()> {
        // (1) Run cleanup step for the OLD active player. This must
        // happen before the active-player swap; CR 514 fires during
        // the cleanup step of the player whose turn is ending.
        slf.call_method0("cleanup_step_for_active_player")?;

        // (2) Land on the CLEANUP phase so the next advance_phase tick
        // wraps CLEANUP -> UNTAP. Going through set_phase rather than
        // walking advance_phase forward is intentional: a single
        // CLEANUP -> UNTAP wrap is the semantically right "end of turn"
        // step, regardless of how many phases the engine has already
        // advanced through this turn.
        slf.borrow_mut().phase = PHASE_CLEANUP;

        // (3) Advance once to wrap CLEANUP -> UNTAP. This fires:
        //     - turn_number += 1
        //     - active_player swap
        //     - round-2 untap sweep on the new active player
        //     - round-14 summoning-sick clear on the new active player
        slf.call_method0("advance_phase")?;

        Ok(())
    }
}
