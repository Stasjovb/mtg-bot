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
//! Other cleanup-step actions (CR 514.2 damage clearance,
//! 514.3 "until end of turn" effects expiration) are deferred —
//! the damage clearance might compose via the existing
//! `clear_all_damage` from state_ops_damage.
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

use crate::state::GameState;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
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
}
