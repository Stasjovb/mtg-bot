//! Mana production / mana pool primitives on `GameState`.
//!
//! Ports the Python side's per-player mana-pool mutations
//! (`Player.mana_pool` in `src/mtg_bot/game.py`, populated by
//! `AddManaToPool` and friends in `src/mtg_bot/effects/generic/mana.py`)
//! into a small, named API on the Rust `GameState`:
//! `get_mana_pool`, `add_mana`, `remove_mana`, `empty_mana_pool`,
//! `tap_for_mana`.
//!
//! **Negative-amount semantics** (mirrors the life slice — see
//! `state_ops_life.rs`): `add_mana` and `remove_mana` take `i32`
//! amounts and raise `ValueError` on a negative value rather than
//! silently flooring or wrapping. Rationale: the Python side's
//! "silent no-op on bad inputs" is a known anti-pattern (see the
//! user's "silent no-op pipeline runs are pipeline bugs" guidance).
//! `amount = 0` is allowed and is a true no-op. `remove_mana`
//! underflow (e.g. removing 1 green from an empty pool) raises
//! rather than clamping at zero — silent underflow would mask
//! paid-but-not-collected bugs in cost-payment code.
//!
//! **Mana-production lookup is provisional.** `tap_for_mana`
//! recognizes Forests by string-matching the printing's `name`
//! against `"Forest"`. This works for the synthetic 3-printing
//! registry today and keeps the slice scoped to this single file.
//! The proper fix — a typed `mana_produced` field on
//! `CardPrinting` — requires touching `cards.rs`, which a sibling
//! agent is editing this round, so it lands in a future bridge
//! slice. The provisional path is a deliberate "fewer files, fewer
//! conflicts" trade for the round-2 parallel TDD batch; the test
//! `test_tap_for_mana_on_forest_produces_green` is the trip-wire
//! that will fail once we replace it with the real mapping.
//!
//! **CoW for the mana pool.** `Player` lives by-value in
//! `GameState.players: [Player; 2]`, and `ManaPool` is itself
//! `Copy + Clone + Default`. Cloning a `GameState` therefore
//! deep-copies the mana pool by value — no `Arc::make_mut`
//! juggling, same shape as life. The `tap_for_mana` path also
//! mutates a battlefield zone (`Arc<Vec<GameObject>>`) and routes
//! that through `Arc::make_mut` so the per-zone CoW invariant
//! still holds for the tap side.

use crate::state::{GameObject, GameState};
use pyo3::exceptions::{PyIndexError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::sync::Arc;

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

/// Project a (color: &str) onto a mut ref to the matching `u8` slot
/// of a `ManaPool`. Returns `Err(ValueError)` if the color string
/// isn't one of W/U/B/R/G/C (case-sensitive — matches the closed
/// vocabulary used elsewhere in the engine).
fn slot_mut<'a>(
    pool: &'a mut crate::state::ManaPool,
    color: &str,
) -> PyResult<&'a mut u8> {
    match color {
        "W" => Ok(&mut pool.white),
        "U" => Ok(&mut pool.blue),
        "B" => Ok(&mut pool.black),
        "R" => Ok(&mut pool.red),
        "G" => Ok(&mut pool.green),
        "C" => Ok(&mut pool.colorless),
        other => Err(PyValueError::new_err(format!(
            "unknown mana color {other:?}; valid: W, U, B, R, G, C"
        ))),
    }
}

#[pymethods]
impl GameState {
    /// Return `player_id`'s mana pool as a 6-key dict
    /// `{"W", "U", "B", "R", "G", "C"}`. Always returns all six
    /// keys, even when the corresponding count is 0 — Python
    /// callers can rely on the shape and skip a `.get(color, 0)`
    /// guard.
    fn get_mana_pool<'py>(
        &self,
        py: Python<'py>,
        player_id: u8,
    ) -> PyResult<Bound<'py, PyDict>> {
        let idx = check_player_id(player_id)?;
        let pool = &self.players[idx].mana_pool;
        let d = PyDict::new(py);
        d.set_item("W", pool.white)?;
        d.set_item("U", pool.blue)?;
        d.set_item("B", pool.black)?;
        d.set_item("R", pool.red)?;
        d.set_item("G", pool.green)?;
        d.set_item("C", pool.colorless)?;
        Ok(d)
    }

    /// Add `amount` mana of `color` to `player_id`'s pool. Raises
    /// `ValueError` on a negative `amount` or an unknown color;
    /// `IndexError` on an out-of-range `player_id`. `amount = 0`
    /// is a no-op.
    fn add_mana(&mut self, player_id: u8, color: &str, amount: i32) -> PyResult<()> {
        let idx = check_player_id(player_id)?;
        check_non_negative("add_mana", amount)?;
        let pool = &mut self.players[idx].mana_pool;
        let slot = slot_mut(pool, color)?;
        // Saturating to u8::MAX is intentional — 255 of any one
        // color is more than any real game produces, and silently
        // wrapping would be a worse failure mode than capping.
        *slot = slot.saturating_add(amount as u8);
        Ok(())
    }

    /// Remove `amount` mana of `color` from `player_id`'s pool.
    /// Raises `ValueError` on a negative `amount`, an unknown
    /// color, or an underflow (removing more than the pool holds).
    /// `amount = 0` is a no-op.
    fn remove_mana(
        &mut self,
        player_id: u8,
        color: &str,
        amount: i32,
    ) -> PyResult<()> {
        let idx = check_player_id(player_id)?;
        check_non_negative("remove_mana", amount)?;
        let pool = &mut self.players[idx].mana_pool;
        let slot = slot_mut(pool, color)?;
        let current = *slot as i32;
        if amount > current {
            return Err(PyValueError::new_err(format!(
                "remove_mana: underflow — pool has {current} {color:?}, \
                 can't remove {amount}"
            )));
        }
        *slot = (current - amount) as u8;
        Ok(())
    }

    /// Zero `player_id`'s entire mana pool. Mirrors the cleanup-step
    /// "empty the mana pool" rule. Leaves the opponent's pool
    /// untouched.
    fn empty_mana_pool(&mut self, player_id: u8) -> PyResult<()> {
        let idx = check_player_id(player_id)?;
        self.players[idx].mana_pool = crate::state::ManaPool::default();
        Ok(())
    }

    /// Tap a permanent for mana. Provisional implementation:
    /// recognizes Forests by string-matching the printing's `name`
    /// against `"Forest"` and producing `{G}` for the controller.
    /// Returns `Some("G")` on success, `None` on every failure mode
    /// (not on a battlefield, already tapped, not a recognized
    /// mana-producer). Crucially, the failure cases are silent —
    /// no error is raised, no mana is added, no tap is performed.
    /// This matches the Python convention where a mana ability
    /// that can't activate is just a no-op at the action layer.
    ///
    /// See the module docstring for why this is name-keyed rather
    /// than reading a typed `mana_produced` field on `CardPrinting`.
    fn tap_for_mana(&mut self, obj_id: u32) -> PyResult<Option<String>> {
        // Phase 1: locate the object + look up its printing name +
        // its controller. Done as an immutable scan so we can decide
        // whether to produce mana before we open up `Arc::make_mut`
        // on a zone.
        let mut found: Option<(usize, &str)> = None; // (controller_idx, name)
        for (player_idx, player) in self.players.iter().enumerate() {
            for obj in player.battlefield.iter() {
                if obj.id == obj_id {
                    if obj.tapped {
                        return Ok(None);
                    }
                    let name = match self.registry.lookup(obj.printing_id) {
                        Some(p) => p.name.as_ref(),
                        None => return Ok(None),
                    };
                    found = Some((player_idx, name));
                    break;
                }
            }
            if found.is_some() {
                break;
            }
        }
        let (controller_idx, name) = match found {
            Some(t) => t,
            None => return Ok(None),
        };
        // Provisional name-keyed mana production. Future slice
        // replaces this with a typed `mana_produced` field on
        // `CardPrinting`.
        let produced_color = match name {
            "Forest" => "G",
            _ => return Ok(None),
        };
        // Phase 2: commit the mutation. Tap the permanent (going
        // through `Arc::make_mut` on the zone) and credit the
        // controller's pool.
        let player = &mut self.players[controller_idx];
        let zone: &mut Vec<GameObject> = Arc::make_mut(&mut player.battlefield);
        for obj in zone.iter_mut() {
            if obj.id == obj_id {
                obj.tapped = true;
                break;
            }
        }
        let slot = slot_mut(&mut player.mana_pool, produced_color)
            .expect("produced_color is hard-coded to a valid slot");
        *slot = slot.saturating_add(1);
        Ok(Some(produced_color.to_string()))
    }
}
