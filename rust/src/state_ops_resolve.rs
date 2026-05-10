//! Stack-resolution primitives on `GameState`.
//!
//! First-cut composition slice: pops the top stack item, finds its
//! source GameObject (search both players' four tracked zones),
//! reads the source printing's effects via `self.registry`, and
//! dispatches each effect against the closed `Effect` enum the
//! round-3 bridge slice landed.
//!
//! Composes:
//! - round-5 stack slice (`push/pop/peek_top_of_stack`,
//!   `state.stack: Vec<StackItem>`).
//! - round-3 bridge-ext (`CardPrinting.effects: Vec<Effect>` with
//!   the `DealDamage` variant).
//! - round-3 damage slice (`deal_damage` shape — though resolve
//!   here goes straight to `players[idx].life` for AnyPlayer and
//!   to `obj.damage += amount` via `Arc::make_mut` for AnyCreature
//!   to avoid coupling slice files; once the parallel-slice
//!   constraint relaxes a follow-up consolidates onto
//!   `state_ops_damage::deal_damage`).
//!
//! ## Slice scope
//!
//! - **Supported effects: just `DealDamage`.** It's the only
//!   `Effect` variant in the bridge today (round-3 only landed
//!   that one). The dispatcher is a `match` on the closed enum so
//!   adding a new variant in the bridge is a build-time error
//!   here until this file dispatches it — the desired "fail loud
//!   on unknown" property comes for free from Rust exhaustiveness.
//! - **Targeting is deterministic + simplified.**
//!   - `TargetFilter::AnyPlayer` -> the defending player
//!     (`1 - active_player`). No "choose a target" surface yet.
//!   - `TargetFilter::AnyCreature` -> the FIRST object on the
//!     defending player's battlefield (smallest battlefield-Vec
//!     index). No creature-type filtering, no protection /
//!     hexproof / shroud, no per-spell target-selection. If the
//!     defender's battlefield is empty, the spell fizzles —
//!     stack item still pops, but no damage is applied.
//!   Real targeting is a future slice once the cast-time target-
//!   choice surface lands.
//! - **No spell-source movement after resolve.** Real MTG: an
//!   instant/sorcery on the stack goes to graveyard after
//!   resolution; a permanent spell goes to battlefield. For first
//!   slice, just pop the stack item — caller is responsible for
//!   movement. Documented as a stepping-stone.
//! - **Empty stack returns None gracefully** (no exception). Same
//!   convention as `pop_top_of_stack`.
//!
//! ## Test-fixture surface
//!
//! `register_and_inject_object(printing_dict, controller, zone) ->
//! u32` is a test-only helper that (a) parses + appends the
//! printing dict into the in-place registry via `Arc::make_mut`
//! and (b) constructs a fresh GameObject pointing at it on the
//! requested zone. Lives here (not in `state.rs`) because the
//! parallel-slice file-isolation rule prevents touching
//! `state.rs`; a follow-up consolidation slice can move this
//! into a more central location once that constraint relaxes.
//! The id assigned is `1 + max(existing object id)` so it never
//! collides with synthetic-state ids.

use crate::cards::{parse_printing, Effect, RegistryData, TargetFilter};
use crate::state::{GameObject, GameState, StackItem};
use crate::state_ops_zones::{
    ZONE_BATTLEFIELD, ZONE_GRAVEYARD, ZONE_HAND, ZONE_LIBRARY,
};
use pyo3::exceptions::{PyIndexError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::sync::Arc;

/// Build a 2-key dict from a StackItem. Mirrors the helper in
/// `state_ops_stack.rs` — duplicated here per the per-slice
/// file-isolation rule (private helpers can't be shared across
/// slice files until the consolidation slice).
fn stack_item_to_dict<'py>(
    py: Python<'py>,
    item: &StackItem,
) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("source_obj_id", item.source_obj_id)?;
    d.set_item("controller", item.controller)?;
    Ok(d)
}

/// Find the source GameObject by id across both players' four
/// tracked zones. Returns a copy (GameObject is `Copy`) along with
/// its printing_id, so the caller can drop the borrow on `state`
/// before mutating it (e.g. to apply damage).
fn find_source_printing_id(state: &GameState, obj_id: u32) -> Option<u32> {
    for player in &state.players {
        for zone in [
            &player.hand,
            &player.library,
            &player.battlefield,
            &player.graveyard,
        ] {
            for obj in zone.iter() {
                if obj.id == obj_id {
                    return Some(obj.printing_id);
                }
            }
        }
    }
    None
}

/// Apply a single Effect to `state`. Closed-enum match: adding a
/// new variant in the bridge will turn this into a build-time
/// error (exhaustiveness) until handled here — the desired "fail
/// loud" property for free.
fn apply_effect(state: &mut GameState, effect: &Effect) -> PyResult<()> {
    match effect {
        Effect::DealDamage { amount, target } => {
            let defender: u8 = 1 - state.active_player;
            let amount_i32 = *amount;
            match target {
                TargetFilter::AnyPlayer => {
                    state.players[defender as usize].life -= amount_i32;
                }
                TargetFilter::AnyCreature => {
                    // First object in the defender's battlefield Vec
                    // (smallest index). No creature-type filter — see
                    // module docstring. If the battlefield is empty,
                    // the spell fizzles silently.
                    let defender_idx = defender as usize;
                    let bf = &state.players[defender_idx].battlefield;
                    if bf.is_empty() {
                        return Ok(());
                    }
                    let target_id = bf[0].id;
                    let amount_i16 = amount_i32.min(i16::MAX as i32) as i16;
                    let zone: &mut Vec<GameObject> =
                        Arc::make_mut(&mut state.players[defender_idx].battlefield);
                    for obj in zone.iter_mut() {
                        if obj.id == target_id {
                            obj.damage = obj.damage.saturating_add(amount_i16);
                            break;
                        }
                    }
                }
            }
        }
    }
    Ok(())
}

#[pymethods]
impl GameState {
    /// Resolve the top stack item. Returns the resolved item as a
    /// dict (same shape as `pop_top_of_stack`), or `None` if the
    /// stack was empty.
    ///
    /// Steps:
    /// 1. Peek top; if empty, return None.
    /// 2. Look up the source GameObject by id across all four
    ///    zones on both players.
    /// 3. Read the source printing's effects from the registry.
    /// 4. Dispatch each effect (currently only `DealDamage`).
    /// 5. Pop the stack item and return its dict.
    ///
    /// If the source GameObject can't be found in any zone, the
    /// item still pops — no effects fire (treated like a fizzle).
    /// This matches the "lost track of source" failure mode: the
    /// stack drains, the player observes no effect.
    fn resolve_top_of_stack<'py>(
        &mut self,
        py: Python<'py>,
    ) -> PyResult<Option<Bound<'py, PyDict>>> {
        // Peek without popping so we can read effects before
        // committing to drain.
        let top = match self.stack.last() {
            None => return Ok(None),
            Some(item) => item.clone(),
        };

        // Find the source's printing_id, then collect a snapshot of
        // its effects so we can drop the registry borrow before
        // mutating self.
        let effects: Vec<Effect> = match find_source_printing_id(self, top.source_obj_id)
        {
            Some(printing_id) => match self.registry.lookup(printing_id) {
                Some(printing) => printing.effects.clone(),
                None => Vec::new(),
            },
            None => Vec::new(),
        };

        for effect in &effects {
            apply_effect(self, effect)?;
        }

        // Now drain the popped item and return its dict.
        let popped = self
            .stack
            .pop()
            .expect("peeked top but pop returned None — stack invariant broken");
        Ok(Some(stack_item_to_dict(py, &popped)?))
    }

    /// **Test-fixture surface.** Register a printing dict into the
    /// in-place registry, construct a fresh GameObject pointing at
    /// it on `target_zone` for player `controller`, and return the
    /// new object's id.
    ///
    /// Used by `tests_rust/test_resolve.py` to set up cross-slice
    /// composition tests (a Bombard-shaped DealDamage source on the
    /// battlefield) without needing a separate `Registry` pyclass
    /// or hand-rolling synthetic states for every test. The id is
    /// `1 + max(existing obj.id across all zones)` so it never
    /// collides with synthetic-state ids.
    ///
    /// Lives in this slice (not `state.rs`) per the per-slice
    /// file-isolation rule. A follow-up consolidation slice can
    /// move it once the parallel-slice constraint relaxes.
    fn register_and_inject_object(
        &mut self,
        printing_dict: &Bound<'_, PyDict>,
        controller: u8,
        target_zone: u8,
    ) -> PyResult<u32> {
        if (controller as usize) >= 2 {
            return Err(PyIndexError::new_err(format!(
                "controller {controller} out of range (must be 0 or 1)"
            )));
        }

        // Append to the registry. Arc::make_mut clones RegistryData
        // on first write only when other clones observe it — same
        // CoW shape as zones.
        let printing = parse_printing(printing_dict)?;
        let reg: &mut RegistryData = Arc::make_mut(&mut self.registry);
        let printing_id = reg.printings.len() as u32;
        reg.printings.push(printing);

        // Pick a fresh obj_id: 1 + max across all zones on both
        // players. Synthetic-state ids start at 0 and pack densely;
        // this guarantees no collision regardless of seed shape.
        let mut next_id: u32 = 0;
        for player in &self.players {
            for zone in [
                &player.hand,
                &player.library,
                &player.battlefield,
                &player.graveyard,
            ] {
                for obj in zone.iter() {
                    if obj.id >= next_id {
                        next_id = obj.id + 1;
                    }
                }
            }
        }

        let obj = GameObject {
            id: next_id,
            printing_id,
            controller,
            zone: target_zone,
            tapped: false,
            summoning_sick: false,
            damage: 0,
            counters: 0,
        };

        let player = &mut self.players[controller as usize];
        let dest = match target_zone {
            ZONE_HAND => &mut player.hand,
            ZONE_LIBRARY => &mut player.library,
            ZONE_BATTLEFIELD => &mut player.battlefield,
            ZONE_GRAVEYARD => &mut player.graveyard,
            other => {
                return Err(PyValueError::new_err(format!(
                    "register_and_inject_object: unsupported target_zone {other} (valid: 0-3)"
                )));
            }
        };
        Arc::make_mut(dest).push(obj);
        Ok(next_id)
    }
}
