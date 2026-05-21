//! Counter-spell primitives on `GameState`.
//!
//! First-cut composition slice: removes a stack item by source
//! `obj_id` and moves the corresponding GameObject to its
//! controller's graveyard. The "countered spell goes to graveyard"
//! step is CR 701.6 (a countered spell is placed into its owner's
//! graveyard) — we route to controller's graveyard for first slice
//! since owner-vs-controller tracking isn't yet split out.
//!
//! The Python source-of-truth for the spell-counter operation is
//! `src/mtg_bot/effects/generic/stack_control.py:CounterTargetSpell`,
//! which sets `item.countered = True` and the resolution layer
//! later short-circuits the spell. The Rust shape is more direct:
//! we drop the stack item AND move the source to graveyard in the
//! same call, since the resolve slice doesn't consume a `countered`
//! flag.
//!
//! ## Slice scope
//!
//! - **No "can't be countered" enforcement.** A future slice will
//!   add `cant_be_countered: bool` to `CardPrinting` and have
//!   `counter_spell` return False (or raise) when the targeted
//!   stack item's source carries that flag. Until then the engine
//!   trusts the caller picked a legal target — matching the
//!   parser-side legality choice on the Python side.
//! - **Caller picks the target obj_id.** No verification that the
//!   countering source is itself a "counter spell" effect. That
//!   legality decision lives in the parser / decision layer.
//! - **Source goes to controller's graveyard.** The stack item
//!   carries the controller; we look up the source GameObject in
//!   any zone and route it to `players[controller].graveyard` via
//!   `move_object`. Real MTG sends countered spells to their
//!   *owner's* graveyard — owner tracking is a future slice.
//! - **Duplicate-source semantics: FIFO (bottom-most match).**
//!   Reuses round-5's `remove_from_stack`, which scans bottom-to-
//!   top. If two stack items share a source obj_id (rare — e.g. a
//!   copy-this-spell effect that re-uses the source), we remove
//!   the bottom-most one. A future top-down variant can land if a
//!   real card needs it.
//! - **No replacement effects, no triggers.** "When a spell is
//!   countered..." triggers (Wickerbough Elder etc.) are deferred.
//! - **Source-not-found is a soft failure.** If the stack item
//!   exists but no GameObject with that id is in any tracked zone,
//!   the stack item is still removed and we return True — same
//!   "lost track of source" failure mode the resolve slice
//!   tolerates. The graveyard movement is a best-effort step.
//!
//! Composes:
//! - round-5 stack slice: `remove_from_stack(obj_id)` (bottom-up
//!   FIFO scan) on `state_ops_stack.rs`.
//! - round-1 zones slice: `move_object(obj_id, zone, player)` on
//!   `state_ops_zones.rs`.

use crate::state::{GameObject, GameState, Zone};
use crate::state_ops_zones::ZONE_GRAVEYARD;
use pyo3::prelude::*;
use std::sync::Arc;

/// Find an object in `zone` by id; if present, remove it (preserving
/// order) and return the owned `GameObject`. CoW-safe via
/// `Arc::make_mut`. Duplicated from `state_ops_zones.rs` per the
/// per-slice file-isolation rule (private helpers can't be shared
/// across slice files until the consolidation slice).
fn take_from_zone(zone: &mut Zone, obj_id: u32) -> Option<GameObject> {
    let pos = zone.iter().position(|o| o.id == obj_id)?;
    let v = Arc::make_mut(zone);
    Some(v.remove(pos))
}

/// Move the GameObject with `obj_id` (searched across both players'
/// four tracked zones) into `target_player`'s graveyard. Returns
/// `true` if the object was found and moved; `false` if no object
/// with that id exists. Duplicated from `state_ops_zones.rs`'s
/// `move_object` (which is `#[pymethods]`-private to that slice) per
/// the per-slice file-isolation rule.
fn move_to_graveyard(state: &mut GameState, obj_id: u32, target_player: u8) -> bool {
    let mut taken: Option<GameObject> = None;
    // G7 S5a (Option β): a spell on the stack has its owned
    // GameObject in `state.stack_objects`, NOT a per-player zone.
    // Counter targets a stack spell, so for the common case the
    // source lives in the store — check it FIRST (pre-S5a the spell
    // was hand-resident and the per-player sweep found it; this is
    // the byte-equivalent for the re-homed model; without it a
    // countered spell's GameObject orphans in the store and never
    // reaches the graveyard).
    if let Some(pos) =
        state.stack_objects.iter().position(|o| o.id == obj_id)
    {
        taken = Some(state.stack_objects.remove(pos));
    }
    for player in state.players.iter_mut() {
        if taken.is_some() {
            break;
        }
        if let Some(obj) = take_from_zone(&mut player.hand, obj_id) {
            taken = Some(obj);
            break;
        }
        if let Some(obj) = take_from_zone(&mut player.library, obj_id) {
            taken = Some(obj);
            break;
        }
        if let Some(obj) = take_from_zone(&mut player.battlefield, obj_id) {
            taken = Some(obj);
            break;
        }
        if let Some(obj) = take_from_zone(&mut player.graveyard, obj_id) {
            taken = Some(obj);
            break;
        }
    }
    let Some(mut obj) = taken else {
        return false;
    };
    obj.zone = ZONE_GRAVEYARD;
    obj.controller = target_player;
    let dest = &mut state.players[target_player as usize].graveyard;
    Arc::make_mut(dest).push(obj);
    true
}

#[pymethods]
impl GameState {
    /// Counter the stack item whose source is `target_obj_id`.
    ///
    /// Returns `true` if a matching stack item was found and removed
    /// (the counter "lands"), `false` if no such stack item exists
    /// (no mutation in that case — both stack and zones untouched).
    ///
    /// On success:
    /// 1. The matching stack item is removed (FIFO: bottom-most
    ///    match if duplicates exist; in practice each spell-cast
    ///    produces one stack item with a unique source obj_id, so
    ///    the bottom-vs-top distinction rarely matters).
    /// 2. The source GameObject — wherever it currently lives — is
    ///    moved to the stack item's controller's graveyard via
    ///    `move_object`. If the source can't be found in any zone
    ///    (it shouldn't happen, but the engine doesn't enforce
    ///    obj-on-stack invariants yet), the stack removal still
    ///    counts as success and the graveyard step is a no-op —
    ///    same "lost track of source" failure mode the resolve
    ///    slice tolerates.
    fn counter_spell(&mut self, target_obj_id: u32) -> bool {
        // Find the matching stack item before removing, so we capture
        // its controller for the graveyard-routing step. Bottom-up scan
        // matches `remove_from_stack`'s FIFO semantics.
        let pos = match self
            .stack
            .iter()
            .position(|item| item.source_obj_id == target_obj_id)
        {
            Some(p) => p,
            None => return false,
        };
        let controller = self.stack[pos].controller;
        // Static / layered abilities substrate — Phase 2 (round-80,
        // 2026-05-20). CR 101.2: an uncounterable spell can't be
        // countered. Mirrors the `Effect::CounterTargetSpell` gate
        // in `state_ops_resolve.rs`. Two sources:
        //   1. source printing's `spell_is_uncounterable`.
        //   2. source is a creature spell AND controller has a
        //      permanent carrying `grants_creature_spells_
        //      uncounterable`.
        // Lookup the source via stack_objects first, then per-player
        // zones; the gate fails closed when the source can't be
        // located (matches the lost-track-of-source soft failure the
        // rest of this primitive tolerates).
        let src_printing_id: Option<u32> = self
            .stack_objects
            .iter()
            .find(|o| o.id == target_obj_id)
            .map(|o| o.printing_id)
            .or_else(|| {
                for player in self.players.iter() {
                    for zone in [
                        &player.hand,
                        &player.library,
                        &player.battlefield,
                        &player.graveyard,
                    ] {
                        if let Some(obj) =
                            zone.iter().find(|o| o.id == target_obj_id)
                        {
                            return Some(obj.printing_id);
                        }
                    }
                }
                None
            });
        if let Some(pid) = src_printing_id {
            if let Some(printing) = self.registry.lookup(pid) {
                if printing.spell_is_uncounterable {
                    return false;
                }
                let is_creature = printing
                    .card_types
                    .iter()
                    .any(|t| t == "Creature");
                if is_creature {
                    if let Some(player) = self.players.get(controller as usize) {
                        for obj in player.battlefield.iter() {
                            if let Some(p) =
                                self.registry.lookup(obj.printing_id)
                            {
                                if p.grants_creature_spells_uncounterable {
                                    return false;
                                }
                            }
                        }
                    }
                }
            }
        }
        // Remove the stack item.
        self.stack.remove(pos);
        // Best-effort: move the source GameObject to the controller's
        // graveyard. `move_to_graveyard` returns false if the source
        // isn't present in any tracked zone — we ignore that for the
        // same reason `resolve_top_of_stack` tolerates a missing
        // source.
        let _ = move_to_graveyard(self, target_obj_id, controller);
        true
    }
}
