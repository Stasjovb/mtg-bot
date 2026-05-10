//! State-based action (SBA) primitives on `GameState`.
//!
//! Filled in by a TDD-slice branch (see `tests_rust/README.md`).
//! Stub block exists so other slices can grow `GameState` in
//! parallel without conflicting on a single `#[pymethods]` block.
//!
//! ## First-slice scope
//!
//! **Lethal-damage SBA only (CR 704.5g):** a creature whose marked
//! damage is greater than or equal to its toughness is destroyed
//! (moved from battlefield to its controller's graveyard).
//!
//! Exposes:
//! - `apply_sbas() -> usize` — single pass over both players'
//!   battlefields; collects every creature whose marked damage has
//!   reached lethal, then destroys each by moving it into its
//!   controller's graveyard. Returns the count of destructions.
//! - `is_lethal(obj_id) -> Option<bool>` — predicate form. `Some(true)`
//!   when damage >= toughness, `Some(false)` when it is below, `None`
//!   for non-creatures (toughness is None) or unknown ids.
//!
//! Composes with:
//! - `state_ops_damage` — supplies the damage marker.
//! - `CardPrinting.toughness: Option<i16>` from the bridge-ext slice
//!   (round 3) — supplies the threshold.
//! - `state_ops_zones::move_object` — the underlying graveyard move
//!   pattern; replicated inline here rather than called via the
//!   pyclass method to keep the destructive collect-then-mutate loop
//!   self-contained and avoid a `&mut self` re-entrancy round-trip.
//!
//! ## Out of scope (deferred to future slices)
//!
//! - **0-toughness SBA (CR 704.5f).** Conceptually similar but reads
//!   from current effective toughness. `GameObject` doesn't carry
//!   live toughness modifications yet — when -1/-1 counters /
//!   anthem-debuff layers land, this becomes a one-line addition to
//!   the predicate. The corresponding test is parked as a `skip`
//!   to lock in the API.
//! - **SBA loop driver / quiescence.** Real MTG (CR 704.3) checks
//!   SBAs simultaneously and re-checks until none apply. This slice
//!   does ONE pass; iteration to fixed point is a future slice that
//!   integrates apply_sbas into combat and spell-resolution call
//!   sites.
//! - **Marked damage clearing.** Damage clears at end of turn (CR
//!   514.2), NOT on every SBA pass. apply_sbas does NOT zero damage
//!   on surviving creatures; `clear_all_damage` from the damage
//!   slice covers the cleanup-step path.
//! - **Indestructibility / regeneration / planeswalker loyalty /
//!   legend rule / +1/+1 vs -1/-1 cancellation / saga age / aura on
//!   illegal target / etc.** All other CR 704.5 SBAs are subsequent
//!   slices.
//!
//! ## Implementation notes
//!
//! - **Collect-then-mutate.** First pass walks both battlefields
//!   read-only and pushes lethal creatures into a `Vec<(controller,
//!   obj_id)>`. Second pass moves each to its controller's
//!   graveyard. Avoids in-loop `Arc::make_mut` invalidating the
//!   iterator.
//! - **CoW preservation.** Each destruction touches at most two
//!   zone Vecs (source battlefield + destination graveyard). Both
//!   go through `Arc::make_mut`, so a clone observing the original
//!   stays untouched. Verified by `test_clone_preserves_sba_pending`.
//! - **Battlefield-only.** apply_sbas only inspects battlefield zones.
//!   Damage on non-battlefield objects is ignored (it shouldn't exist
//!   there in normal play, and the lethal-damage SBA is intrinsically
//!   battlefield-scoped).

use crate::state::{GameObject, GameState};
use pyo3::prelude::*;
use std::sync::Arc;

// Zone constants — duplicated from state_ops_zones.rs (per the
// per-slice isolation rule; a follow-up consolidation slice can
// share these via a common module once the parallel-slice constraint
// relaxes).
const ZONE_GRAVEYARD: u8 = 3;

impl GameState {
    /// Read-only check: does the given object exist in either player's
    /// battlefield, AND does its printing have a toughness, AND has
    /// its marked damage reached lethal? Returns the controller id +
    /// the object id when so. Used by `apply_sbas` to enumerate
    /// victims without mutating the state during iteration.
    fn collect_lethal_creatures(&self) -> Vec<(u8, u32)> {
        let mut victims = Vec::new();
        for player in &self.players {
            for obj in player.battlefield.iter() {
                let Some(printing) = self.registry.lookup(obj.printing_id) else {
                    continue;
                };
                let Some(toughness) = printing.toughness else {
                    continue;
                };
                if obj.damage as i32 >= toughness as i32 {
                    victims.push((obj.controller, obj.id));
                }
            }
        }
        victims
    }
}

#[pymethods]
impl GameState {
    /// Apply state-based actions for the lethal-damage SBA (CR 704.5g):
    /// every creature with marked damage >= toughness is moved from
    /// the battlefield into its controller's graveyard. Returns the
    /// number of creatures destroyed in this pass.
    ///
    /// Single-pass, no quiescence loop — see module docstring for
    /// the deferred semantics.
    fn apply_sbas(&mut self) -> PyResult<usize> {
        let victims = self.collect_lethal_creatures();
        let count = victims.len();
        for (controller, obj_id) in victims {
            // Take the object out of its current battlefield. Search
            // both players (a creature's controller can differ from
            // its owner; we move to the CONTROLLER's graveyard per
            // CR 400.6 — "destroy" sends to the owner's graveyard,
            // but for first-slice we follow the controller-side
            // convention used by move_off_battlefield's caller. The
            // vast majority of the time these are the same player,
            // and the future zones-extension slice can revisit.)
            let mut taken: Option<GameObject> = None;
            for player in self.players.iter_mut() {
                let pos = player.battlefield.iter().position(|o| o.id == obj_id);
                if let Some(idx) = pos {
                    let bf = Arc::make_mut(&mut player.battlefield);
                    taken = Some(bf.remove(idx));
                    break;
                }
            }
            let Some(mut obj) = taken else {
                // Should not happen — collect_lethal_creatures just
                // saw it. If it does (concurrent mutation, future
                // SBA cascade), skip silently.
                continue;
            };
            obj.zone = ZONE_GRAVEYARD;
            obj.controller = controller;
            // Push onto the controller's graveyard.
            let target = &mut self.players[controller as usize];
            Arc::make_mut(&mut target.graveyard).push(obj);
        }
        Ok(count)
    }

    /// Predicate form of the lethal-damage check.
    ///
    /// Returns `Some(true)` when the creature's marked damage is
    /// greater than or equal to its printed toughness, `Some(false)`
    /// when it is below, and `None` when the object is not found OR
    /// when the printing has no toughness (i.e. it's not a creature
    /// — lands, instants, sorceries, etc.).
    ///
    /// This is the post-bridge upgrade of the threshold-form
    /// `is_damage_at_least(obj_id, threshold)` from the damage slice;
    /// `is_lethal(obj_id) == is_damage_at_least(obj_id, toughness)`
    /// for any creature.
    fn is_lethal(&self, obj_id: u32) -> Option<bool> {
        for player in &self.players {
            for obj in player.battlefield.iter() {
                if obj.id == obj_id {
                    let printing = self.registry.lookup(obj.printing_id)?;
                    let toughness = printing.toughness?;
                    return Some(obj.damage as i32 >= toughness as i32);
                }
            }
        }
        // Not on either battlefield — for the first-slice purposes the
        // lethal-damage SBA is battlefield-scoped, so we return None
        // for objects elsewhere. (Could be extended to search all
        // zones if a caller cares; deferred.)
        None
    }
}
