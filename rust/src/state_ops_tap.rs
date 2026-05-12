//! Tap / untap primitives on `GameState`.
//!
//! Mirrors the per-controller `obj.tapped = True/False` sites in
//! `src/mtg_bot/effects/generic/tap.py` plus the per-controller
//! battlefield sweep in `src/mtg_bot/turn.py:run_untap_step`. The
//! Python side mutates `obj.tapped` in place because Python objects
//! are heap-allocated; the Rust side carries POD GameObjects in
//! `Arc<Vec<GameObject>>` zones so each mutation must go through
//! `Arc::make_mut` to preserve copy-on-write semantics for clones.
//!
//! See `tests_rust/test_tap.py` — the load-bearing CoW invariant
//! lives in `test_tap_one_clone_does_not_tap_other`.

use crate::state::{GameObject, GameState};
use pyo3::prelude::*;
use std::sync::Arc;

/// Helper: walk every player's battlefield and apply `f` to the
/// matching object via `Arc::make_mut`. Returns `Some(true)` if
/// `f` returned `true` (state changed), `Some(false)` if the object
/// was found but `f` returned `false` (no change), and `None` if
/// no object with that id exists on any battlefield.
///
/// Other zones (hand / library / graveyard) have no in-game concept
/// of "tapped" — only permanents on the battlefield carry tapped
/// state — so we restrict the search to battlefields. That also
/// keeps the `Arc::make_mut` clone scoped to the one Vec we
/// actually mutate.
fn mutate_battlefield_obj<F>(state: &mut GameState, obj_id: u32, mut f: F) -> Option<bool>
where
    F: FnMut(&mut GameObject) -> bool,
{
    for player in state.players.iter_mut() {
        if player.battlefield.iter().any(|o| o.id == obj_id) {
            let zone: &mut Vec<GameObject> = Arc::make_mut(&mut player.battlefield);
            for obj in zone.iter_mut() {
                if obj.id == obj_id {
                    return Some(f(obj));
                }
            }
        }
    }
    None
}

#[pymethods]
impl GameState {
    /// Tap the battlefield permanent with `obj_id`.
    ///
    /// Returns `True` if the state changed (object was untapped and
    /// is now tapped), `False` otherwise (object was already tapped,
    /// or no battlefield permanent has that id). Mirrors the Python
    /// "tap as cost" idiom that needs to distinguish a fresh tap
    /// from an idempotent no-op.
    fn tap_object(&mut self, obj_id: u32) -> bool {
        mutate_battlefield_obj(self, obj_id, |obj| {
            if obj.tapped {
                false
            } else {
                obj.tapped = true;
                true
            }
        })
        .unwrap_or(false)
    }

    /// Untap the battlefield permanent with `obj_id`.
    ///
    /// Returns `True` if the state changed (object was tapped and
    /// is now untapped), `False` otherwise. Symmetric to `tap_object`.
    fn untap_object(&mut self, obj_id: u32) -> bool {
        mutate_battlefield_obj(self, obj_id, |obj| {
            if obj.tapped {
                obj.tapped = false;
                true
            } else {
                false
            }
        })
        .unwrap_or(false)
    }

    /// Read-only tapped query.
    ///
    /// Returns `Some(tapped_state)` if `obj_id` is on a battlefield,
    /// `None` if no such object exists. Distinguishing "object not
    /// found" from "object found and untapped" matters for callers
    /// that need to validate a target before applying an effect.
    fn is_tapped(&self, obj_id: u32) -> Option<bool> {
        for player in &self.players {
            for obj in player.battlefield.iter() {
                if obj.id == obj_id {
                    return Some(obj.tapped);
                }
            }
        }
        None
    }

    /// The untap-step primitive: untap every battlefield permanent
    /// controlled by `player_id`. Mirrors the per-controller sweep
    /// at `src/mtg_bot/turn.py:87-104` (without the stun-counter /
    /// attached-prevents-untap gates — those land in later slices).
    ///
    /// Goes through `Arc::make_mut` exactly once on the target
    /// player's battlefield Vec, regardless of how many objects
    /// flip — one CoW clone covers all the in-place flips.
    fn untap_all_for_player(&mut self, player_id: u8) {
        let player = match self.players.iter_mut().find(|p| p.id == player_id) {
            Some(p) => p,
            None => return,
        };
        // Skip the make_mut clone if there's nothing to flip — every
        // object is already untapped.
        if player.battlefield.iter().all(|o| !o.tapped) {
            return;
        }
        let zone: &mut Vec<GameObject> = Arc::make_mut(&mut player.battlefield);
        for obj in zone.iter_mut() {
            obj.tapped = false;
        }
    }

    /// Clear `summoning_sick` on every battlefield permanent controlled
    /// by `player_id`. Mirrors the beginning-of-untap-step sweep that
    /// `advance_phase` composes (`state_ops_steps.rs::clear_summoning_sick_for_player_inline`);
    /// exposed as a pymethod so test fixtures can place creatures via
    /// `move_object` and then mark them as "been on the battlefield
    /// long enough" without driving a full turn loop.
    ///
    /// In real play this fires exactly once per turn during the
    /// active player's untap step (CR 302.1 — a creature you control
    /// continuously since the beginning of your most recent turn
    /// doesn't have summoning sickness). The public pymethod is a
    /// test convenience; production game flow continues to use
    /// `advance_phase` for the composed untap + sickness-clear hook.
    fn clear_summoning_sick_for_player(&mut self, player_id: u8) {
        let player = match self.players.iter_mut().find(|p| p.id == player_id) {
            Some(p) => p,
            None => return,
        };
        if player.battlefield.iter().all(|o| !o.summoning_sick) {
            return;
        }
        let zone: &mut Vec<GameObject> = Arc::make_mut(&mut player.battlefield);
        for obj in zone.iter_mut() {
            obj.summoning_sick = false;
        }
    }

    /// Test-only side-channel: force-set the `summoning_sick` flag on
    /// the battlefield permanent with `obj_id`. Returns `true` if the
    /// state changed (object was found and flag differed), `false`
    /// otherwise (no such object on any battlefield, or already at the
    /// requested value).
    ///
    /// Why this exists: `register_and_inject_object` hardcodes
    /// `summoning_sick: false` on the injected permanent. The Phase 5
    /// haste cross-engine probe needs to inject a creature that's
    /// STILL summoning-sick (CR 702.10 — haste bypasses the
    /// summoning-sickness gate on declare-attackers; the only way to
    /// observe that bypass is to start the creature in the sick
    /// state). The vigilance / lifelink / deathtouch / first-strike
    /// probes all left the injected creature `summoning_sick=false`,
    /// so they did not need this helper.
    ///
    /// Mirrors the test-helper convention of `register_and_inject_object`
    /// — it's not a production primitive (real summoning-sick flips
    /// happen via the untap-step sweep in `state_ops_steps.rs` and the
    /// ETB stamp in `state_ops_cast.rs::resolve_*`), it's a fixture-
    /// setup escape hatch used only by cross-engine smoke probes.
    fn force_set_summoning_sick(&mut self, obj_id: u32, value: bool) -> bool {
        mutate_battlefield_obj(self, obj_id, |obj| {
            if obj.summoning_sick == value {
                false
            } else {
                obj.summoning_sick = value;
                true
            }
        })
        .unwrap_or(false)
    }
}

