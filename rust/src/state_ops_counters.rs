//! Counter primitives on `GameState`.
//!
//! Filled in by a TDD-slice branch (see `tests_rust/README.md`).
//! Stub block exists so other slices can grow `GameState` in
//! parallel without conflicting on a single `#[pymethods]` block.
//!
//! `GameObject.counters: i32` already exists (per-instance scalar);
//! the first slice models +1/+1 (positive) and -1/-1 (negative)
//! as a single net count, since they cancel at SBAs. Future slices
//! extend to a proper multi-kind map once a card needs charge / lore
//! / loyalty / brick / etc.
//!
//! ## Net-i32 model and the SBA-cancellation TODO
//!
//! The Python engine stores `plus_one_counters` and `minus_one_counters`
//! as separate fields and cancels them pairwise inside
//! `state_based_actions` (CR 704.5p). The Rust port collapses both
//! into a single signed integer: `+N` ≡ N net +1/+1 counters,
//! `-N` ≡ N net -1/-1 counters. That captures the post-cancellation
//! amount that contributes to effective P/T, which is the only thing
//! every downstream caller actually reads. The price is that "how
//! many distinct +1/+1 counters does this creature have right now"
//! becomes inexpressible — fine until a card asks (e.g. an effect
//! that doubles +1/+1 counters specifically), which is a future slice.
//!
//! TODO: when SBA enforcement lands on the Rust side, callers that
//! mutate counters can stop pre-cancelling via the i32 representation
//! and the SBA pass can do its own bookkeeping. Today this primitive
//! is the entire counter system; the i32 IS the post-SBA net value.
//!
//! ## Read locations
//!
//! +1/+1 counters can technically live in any zone (Athreos returns
//! cards from the graveyard with counter triggers, time counters tick
//! on suspended cards in exile, etc.) — so the lookup walks every
//! tracked zone, not just battlefield. This differs from
//! `state_ops_tap.rs::is_tapped`, which restricts to battlefield
//! because only battlefield permanents have a defined "tapped" state.

use crate::state::{GameObject, GameState};
use pyo3::exceptions::PyIndexError;
use pyo3::prelude::*;
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

/// Walk every player's four tracked zones (hand, library, battlefield,
/// graveyard) and apply `f` to the matching object via `Arc::make_mut`
/// on the containing zone Vec. Returns `true` if an object with
/// `obj_id` was found (regardless of whether `f` actually mutated it),
/// `false` if no matching object exists.
///
/// Mirrors the shape of `state_ops_tap.rs::mutate_battlefield_obj`,
/// scoped to all-zones. Lives in this file (not shared with `_zones`)
/// per the slice-isolation rule — refactoring into a shared helper is
/// a follow-up once the parallel-slice constraint relaxes.
fn mutate_object_anywhere<F>(state: &mut GameState, obj_id: u32, mut f: F) -> bool
where
    F: FnMut(&mut GameObject),
{
    for player in state.players.iter_mut() {
        // Hand.
        if player.hand.iter().any(|o| o.id == obj_id) {
            let zone: &mut Vec<GameObject> = Arc::make_mut(&mut player.hand);
            for obj in zone.iter_mut() {
                if obj.id == obj_id {
                    f(obj);
                    return true;
                }
            }
        }
        // Library.
        if player.library.iter().any(|o| o.id == obj_id) {
            let zone: &mut Vec<GameObject> = Arc::make_mut(&mut player.library);
            for obj in zone.iter_mut() {
                if obj.id == obj_id {
                    f(obj);
                    return true;
                }
            }
        }
        // Battlefield.
        if player.battlefield.iter().any(|o| o.id == obj_id) {
            let zone: &mut Vec<GameObject> = Arc::make_mut(&mut player.battlefield);
            for obj in zone.iter_mut() {
                if obj.id == obj_id {
                    f(obj);
                    return true;
                }
            }
        }
        // Graveyard.
        if player.graveyard.iter().any(|o| o.id == obj_id) {
            let zone: &mut Vec<GameObject> = Arc::make_mut(&mut player.graveyard);
            for obj in zone.iter_mut() {
                if obj.id == obj_id {
                    f(obj);
                    return true;
                }
            }
        }
    }
    false
}

/// Read-only sibling of `mutate_object_anywhere`. Walks the four
/// tracked zones on both players and returns the matching object's
/// `counters` field, or `None` if no such object exists.
fn read_counters(state: &GameState, obj_id: u32) -> Option<i32> {
    for player in &state.players {
        for zone in [
            &player.hand,
            &player.library,
            &player.battlefield,
            &player.graveyard,
        ] {
            for obj in zone.iter() {
                if obj.id == obj_id {
                    return Some(obj.counters);
                }
            }
        }
    }
    None
}

#[pymethods]
impl GameState {
    /// Read the net counter value on the object with `obj_id`.
    ///
    /// Returns `Some(n)` where `n` is the signed net count
    /// (+ for +1/+1, - for -1/-1) if the object exists in any
    /// tracked zone; `None` otherwise. Distinguishes "object not
    /// found" from "object found and at zero counters" — callers
    /// validating a target before applying an effect rely on that.
    fn get_counters(&self, obj_id: u32) -> Option<i32> {
        read_counters(self, obj_id)
    }

    /// Write the absolute counter value on the object with `obj_id`.
    ///
    /// Returns `true` if an object with that id was found and
    /// updated, `false` if no matching object exists in any tracked
    /// zone. Like `tap_object`, this is a silent no-op rather than
    /// an exception — matches the Python convention for effects
    /// whose targeted permanent has already left the relevant zone.
    fn set_counters(&mut self, obj_id: u32, value: i32) -> bool {
        mutate_object_anywhere(self, obj_id, |obj| {
            obj.counters = value;
        })
    }

    /// Increment (or decrement, for negative `delta`) the counter
    /// value on the object with `obj_id`.
    ///
    /// Returns `true` if an object with that id was found and
    /// updated, `false` if no matching object exists. The value can
    /// freely cross zero in either direction — see the module
    /// docstring on the net-i32 model.
    fn add_counters(&mut self, obj_id: u32, delta: i32) -> bool {
        mutate_object_anywhere(self, obj_id, |obj| {
            obj.counters = obj.counters.saturating_add(delta);
        })
    }

    /// The +1/+1 contribution to effective power.
    ///
    /// For the net-i32 model this is just the counter value. Real
    /// effective-power composition (base + counters + auras +
    /// ContinuousModifiers) is a future slice; this method returns
    /// the counter contribution alone. Returns `None` if no object
    /// with `obj_id` exists.
    fn power_bonus_from_counters(&self, obj_id: u32) -> Option<i32> {
        read_counters(self, obj_id)
    }

    /// The +1/+1 contribution to effective toughness.
    ///
    /// Symmetric with `power_bonus_from_counters` because +1/+1
    /// (and -1/-1) counters affect both stats equally. The two
    /// methods exist as distinct names so a future slice that
    /// introduces asymmetric counter types (+1/+0 etc.) has a
    /// clean upgrade path.
    fn toughness_bonus_from_counters(&self, obj_id: u32) -> Option<i32> {
        read_counters(self, obj_id)
    }

    /// Doubling Season-style "snap to doubled state" mutator. For
    /// every creature on `player_id`'s battlefield, multiply its
    /// counter value by 2. Zero stays zero, positive doubles
    /// (+3 → +6), negative doubles symmetrically (-2 → -4) — the
    /// "double the counter" interpretation applies to whichever
    /// kind is present.
    ///
    /// Real Doubling Season is a static replacement effect that
    /// intercepts counter-placement events; this primitive is the
    /// simpler one-shot mutator and a building block for the future
    /// replacement-effects framework. Useful today as a test tool
    /// for counter-stacking scenarios.
    ///
    /// Raises `IndexError` if `player_id` is not 0 or 1.
    ///
    /// Routes through `Arc::make_mut` on the battlefield Vec so
    /// the CoW invariant holds for clones observing the original.
    /// Optimization: skip the make_mut clone if no creature on
    /// this battlefield has non-zero counters — keeps the no-op
    /// call free of per-zone CoW costs.
    ///
    /// Uses `saturating_mul` so an extreme i32 value (close to
    /// i32::MAX/MIN) clamps rather than overflowing.
    fn double_counters_for_player(&mut self, player_id: u8) -> PyResult<()> {
        let idx = check_player_id(player_id)?;
        let player = &mut self.players[idx];
        // No-op fast path: nothing to double.
        if !player.battlefield.iter().any(|o| o.counters != 0) {
            return Ok(());
        }
        let zone: &mut Vec<GameObject> = Arc::make_mut(&mut player.battlefield);
        for obj in zone.iter_mut() {
            obj.counters = obj.counters.saturating_mul(2);
        }
        Ok(())
    }

    /// Proliferate primitive (CR 701.25). For every permanent on
    /// either player's battlefield that already has `counters != 0`,
    /// add one counter of the kind that's already there: positive
    /// stays positive and ticks up by 1, negative stays negative and
    /// ticks down by 1 (i.e. one more -1/-1 counter). Permanents at
    /// zero net counters are NOT touched — proliferate only adds to
    /// counter kinds that are already present.
    ///
    /// **Simplified model — divergence from real MTG.** Real
    /// proliferate (CR 701.25a) is a player choice: the controller
    /// picks any number of permanents and players that already have
    /// counters and chooses, for each, whether to add another counter
    /// of a kind it already has. This primitive instead deterministically
    /// proliferates every eligible permanent. That matches the most
    /// common board-state outcome for proliferate effects (Contagion
    /// Clasp, Inkmoth Nexus's first ability, Karn's Bastion) where
    /// the controller wants to grow their +1/+1 board and shrink the
    /// opponent's creatures with -1/-1 counters anyway, but it skips
    /// the "decline to proliferate" branch and the "proliferate enemy
    /// +1/+1 counters" suicide branch. See `docs/SEARCH_LIMITATIONS.md`
    /// for the full divergence note.
    ///
    /// Players (and their poison counters) are not modeled — the
    /// engine has no poison-counter field today, so the player-side
    /// half of proliferate is a no-op by absence.
    ///
    /// Saturating arithmetic — a counter at i32::MAX or i32::MIN
    /// stays clamped instead of wrapping.
    ///
    /// No-op fast path: if no permanent on either battlefield has
    /// non-zero counters, skip the per-zone `Arc::make_mut` clone
    /// entirely. Mirrors `double_counters_for_player`'s pattern;
    /// matters because proliferate-on-an-empty-board (e.g. cast
    /// Contagion Clasp turn 1 with no targets yet on the battlefield)
    /// is the dominant case during early-game search exploration.
    ///
    /// Returns `Ok(())` always; proliferate is an always-legal action
    /// at the engine level (the "no eligible targets" case is just a
    /// no-op, not an error).
    fn proliferate(&mut self) -> PyResult<()> {
        // No-op fast path: if neither battlefield has any non-zero
        // counters, skip both make_mut clones and return immediately.
        let any_targets = self
            .players
            .iter()
            .any(|p| p.battlefield.iter().any(|o| o.counters != 0));
        if !any_targets {
            return Ok(());
        }
        for player in self.players.iter_mut() {
            // Per-side fast path: if THIS battlefield has nothing to
            // proliferate, skip make_mut on it so a CoW clone of just
            // this side stays shared.
            if !player.battlefield.iter().any(|o| o.counters != 0) {
                continue;
            }
            let zone: &mut Vec<GameObject> = Arc::make_mut(&mut player.battlefield);
            for obj in zone.iter_mut() {
                if obj.counters > 0 {
                    obj.counters = obj.counters.saturating_add(1);
                } else if obj.counters < 0 {
                    obj.counters = obj.counters.saturating_sub(1);
                }
                // counters == 0 → leave alone per CR 701.25a.
            }
        }
        Ok(())
    }
}
