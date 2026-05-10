//! Life-modification primitives on `GameState`.
//!
//! Ports the Python side's `gain_life` helper plus the many direct
//! `p.life -= amount` mutations scattered through `combat.py`,
//! `actions.py`, and `effects/` into a small, named API:
//! `get_life`, `set_life`, `gain_life`, `lose_life`.
//!
//! **Negative-amount semantics — documented divergence from Python.**
//! Python's `gain_life` silently no-ops on `amount <= 0` (returns 0,
//! makes no mutation), and `lose_life` doesn't exist as a named
//! helper at all (callers mutate `p.life` directly). The Rust port
//! raises `ValueError` on a negative `amount` for both `gain_life`
//! and `lose_life`. Rationale: silent no-ops on bad inputs hide
//! caller bugs (see the user's "silent no-op pipeline runs are
//! pipeline bugs" guidance). `amount = 0` is a legitimate value and
//! is allowed as a true no-op.
//!
//! **No clamping at zero.** `lose_life` allows the result to go
//! negative — the engine reports raw life totals; "loss at 0 is a
//! game-loss" is a state-based action handled at a higher layer that
//! is not yet implemented.
//!
//! **CoW for `Player`.** `Player` lives by-value in
//! `GameState.players: [Player; 2]` (not behind an `Arc`), so a
//! `GameState.clone()` deep-copies the Player struct. Mutating
//! `players[i].life` on a clone therefore does not bleed back into
//! the original — verified by `test_modify_one_clone_does_not_affect_other`.

use crate::state::GameState;
use pyo3::exceptions::{PyIndexError, PyValueError};
use pyo3::prelude::*;

fn check_player_id(player_id: u8) -> PyResult<usize> {
    let idx = player_id as usize;
    if idx >= 2 {
        return Err(PyIndexError::new_err(format!(
            "player_id {player_id} out of range (must be 0 or 1)"
        )));
    }
    Ok(idx)
}

fn check_non_negative(name: &str, amount: i32) -> PyResult<()> {
    if amount < 0 {
        return Err(PyValueError::new_err(format!(
            "{name}: amount must be non-negative, got {amount}"
        )));
    }
    Ok(())
}

#[pymethods]
impl GameState {
    /// Return `player_id`'s current life total. Raises `IndexError`
    /// if `player_id` is not 0 or 1.
    fn get_life(&self, player_id: u8) -> PyResult<i32> {
        let idx = check_player_id(player_id)?;
        Ok(self.players[idx].life)
    }

    /// Set `player_id`'s life total to `life`. No clamping — accepts
    /// any `i32`, including negatives (matches the engine semantics
    /// of "report raw life totals; let a higher layer handle SBAs").
    fn set_life(&mut self, player_id: u8, life: i32) -> PyResult<()> {
        let idx = check_player_id(player_id)?;
        self.players[idx].life = life;
        Ok(())
    }

    /// Add `amount` life to `player_id`. Raises `ValueError` if
    /// `amount` is negative; `amount == 0` is allowed and is a no-op.
    fn gain_life(&mut self, player_id: u8, amount: i32) -> PyResult<()> {
        let idx = check_player_id(player_id)?;
        check_non_negative("gain_life", amount)?;
        self.players[idx].life += amount;
        Ok(())
    }

    /// Subtract `amount` life from `player_id`. Raises `ValueError`
    /// if `amount` is negative; `amount == 0` is allowed and is a
    /// no-op. The result may go negative — the engine reports raw
    /// life totals.
    fn lose_life(&mut self, player_id: u8, amount: i32) -> PyResult<()> {
        let idx = check_player_id(player_id)?;
        check_non_negative("lose_life", amount)?;
        self.players[idx].life -= amount;
        Ok(())
    }
}
