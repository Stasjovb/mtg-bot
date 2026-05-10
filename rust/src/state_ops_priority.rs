//! Priority management primitives on `GameState`.
//!
//! Mirrors `src/mtg_bot/game.py:GameState.priority_player_idx` and
//! the priority-round mechanism in `src/mtg_bot/turn.py`. The Rust
//! side keeps `priority_player` as a `u8` field on `GameState`
//! (already present from the foundation commit) and exposes
//! Python-callable getters / setters and pass-priority semantics
//! here.
//!
//! ## Slice scope
//!
//! Pass-priority is a 2-player toggle: `priority_player` flips to
//! the other player. Multi-player priority (CR 800.4 / APNAP) is
//! out of scope until/unless the engine grows past 2 players.
//!
//! ## Out of scope (deferred to future slices)
//!
//! - **Composition with phase advancement.** CR 117.1a says the
//!   active player gets priority at the start of each step.
//!   `advance_phase` lives in `state_ops_steps.rs` and intentionally
//!   does NOT touch `priority_player` here — a future slice will
//!   integrate state_ops_priority + state_ops_steps so the
//!   active-player-gets-priority rule fires automatically. The
//!   test `test_priority_unaffected_by_phase_advance_in_this_slice`
//!   in `tests_rust/test_priority.py` pins this slice boundary.
//! - **Priority round (both players pass with empty stack ->
//!   step ends per CR 117.4).** Depends on a stack object which the
//!   Rust engine does not have yet.

use crate::state::GameState;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

#[pymethods]
impl GameState {
    /// Read the player who currently has priority. Returns the raw
    /// `u8` player id (0 or 1 in the 2-player model).
    fn get_priority_player(&self) -> u8 {
        self.priority_player
    }

    /// Pass priority to the other player. In the 2-player model
    /// this is a simple toggle (`1 - priority_player`). Returns the
    /// new priority-holder's id so callers can chain off the result
    /// without a follow-up `get_priority_player()` call.
    ///
    /// Note: this only moves `priority_player`; `active_player`
    /// stays put. Active-player rotation is the job of the
    /// turn-rollover path in `state_ops_steps.rs:advance_phase`.
    fn pass_priority(&mut self) -> u8 {
        self.priority_player = 1 - self.priority_player;
        self.priority_player
    }

    /// Direct priority setter for tests / fast-forward scenarios.
    /// Validates the player_id is in {0, 1}; raises `ValueError`
    /// otherwise rather than silently corrupting state.
    fn give_priority_to(&mut self, player_id: u8) -> PyResult<()> {
        if player_id > 1 {
            return Err(PyValueError::new_err(format!(
                "player_id out of range: {player_id} (must be 0 or 1)"
            )));
        }
        self.priority_player = player_id;
        Ok(())
    }
}
