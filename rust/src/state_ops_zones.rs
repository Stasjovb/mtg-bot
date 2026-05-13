//! Zone-movement primitives on `GameState`.
//!
//! First TDD slice on the engine port. Owns the per-object membership
//! moves (battlefield -> graveyard, library -> hand on draw, etc.) and
//! a couple of read helpers (`find_object_zone`, `graveyard_sizes`)
//! that the move tests need to assert against.
//!
//! ## Zone identifier encoding (option b)
//!
//! Zones are represented by raw `u8` constants exposed as `pub const`
//! at module scope. The alternative — a `ZoneKind` enum on
//! `state.rs` — would have forced an edit on a file two sibling TDD
//! slices also need to grow this commit, so we keep the encoding
//! inline. The constants are duplicated in `tests_rust/test_zones.py`
//! for readability; a follow-up slice can either expose them as
//! module-level Python attrs on `mtg_bot_engine` or upgrade to an
//! enum once the parallel-slice constraint relaxes.
//!
//! ## "Top of library" convention
//!
//! `draw_card` removes the FIRST element of the library `Vec` (index 0)
//! and pushes it onto the hand. This matches Python's
//! `library.pop(0)` convention exactly — index 0 = top of library;
//! the last element of the Vec is the bottom. CE3 (round 28 cross-
//! engine smoke divergence) closure: prior to this slice, Rust used
//! `Vec::pop` (tail = top) for O(1) cost while Python used
//! `pop(0)` — same DeckSpec drew opposite cards. Aligned to Python's
//! convention here so the eventual 1000-game smoke harness sees
//! matched draws on both engines. See `docs/RUST_PARITY_GAPS.md`
//! section CE3 for the full closure rationale. The O(n) front-pop
//! cost is acceptable at the 40-60-card library scale; a follow-up
//! slice can store libraries back-to-front internally and keep the
//! `Vec::pop` shape if a bench surfaces real regression.

use crate::state::{GameObject, GameState, Zone};
use pyo3::exceptions::PyIndexError;
use pyo3::prelude::*;
use std::sync::Arc;

pub const ZONE_HAND: u8 = 0;
pub const ZONE_LIBRARY: u8 = 1;
pub const ZONE_BATTLEFIELD: u8 = 2;
pub const ZONE_GRAVEYARD: u8 = 3;
#[allow(dead_code)]
pub const ZONE_STACK: u8 = 4;
#[allow(dead_code)]
pub const ZONE_EXILE: u8 = 5;

/// Find an object in `zone` by id; if present, remove it (preserving
/// order) and return the owned `GameObject`. CoW-safe: takes
/// `&mut Zone` (= `&mut Arc<Vec<GameObject>>`) and goes through
/// `Arc::make_mut`, so the inner `Vec` is cloned on first write only
/// when other clones are observing it.
fn take_from_zone(zone: &mut Zone, obj_id: u32) -> Option<GameObject> {
    let pos = zone.iter().position(|o| o.id == obj_id)?;
    let v = Arc::make_mut(zone);
    Some(v.remove(pos))
}

/// Round-29 EoE Void LTB tracking helper.
///
/// Called by every battlefield-exit site (the `move_object` primitive
/// + every Effect arm that inlines its own `Arc::make_mut`-remove of
/// a permanent from a battlefield Vec, see `state_ops_resolve.rs` +
/// `state_ops_sba.rs`). Mirrors Python's
/// `turn.move_off_battlefield` gate at `src/mtg_bot/turn.py:163-164`:
///
/// ```python
/// if not obj.printing.is_land:
///     state.permanent_left_battlefield_this_turn = True
/// ```
///
/// The gate is per-object via the printing's `card_types` —
/// non-lands flip the flag, lands skip silently. Unknown printing
/// ids (registry miss) are treated as non-lands and flip the flag,
/// matching the loud-fail-elsewhere / fail-open-here convention used
/// by neighboring helpers (the synthetic-state harness never
/// produces dangling printing_ids, but injected-card tests can).
///
/// Cheap and idempotent — `bool = true` is fine to set repeatedly.
/// The reset site is `cleanup_step_for_active_player_inline` in
/// `state_ops_steps.rs` (entry to PHASE_CLEANUP). See
/// `docs/RUST_PARITY_GAPS.md` I29 for the full lifecycle invariant.
pub(crate) fn mark_left_battlefield_if_nonland(
    state: &mut GameState,
    printing_id: u32,
) {
    let is_land = state
        .registry
        .lookup(printing_id)
        .map(|p| p.card_types.iter().any(|t| t == "Land"))
        .unwrap_or(false);
    if !is_land {
        state.permanent_left_battlefield_this_turn = true;
    }
}

#[pymethods]
impl GameState {
    /// Mirror of `battlefield_sizes` / `hand_sizes` for the graveyard
    /// zone. Lives here rather than `state.rs` because the
    /// graveyard-side assertions land with the first move-into-
    /// graveyard test in this slice.
    #[getter]
    fn graveyard_sizes(&self) -> [usize; 2] {
        [
            self.players[0].graveyard.len(),
            self.players[1].graveyard.len(),
        ]
    }

    /// Resolve an object id to the zone constant naming the zone it
    /// currently lives in. Returns `None` if no object with that id
    /// is in any of the five tracked zones (hand / library /
    /// battlefield / graveyard / exile) on either player. The stack
    /// is still not searched (a stack item is keyed by source id,
    /// not by full GameObject membership) — once it is, the search
    /// extends here.
    ///
    /// **Round-14 update:** exile is now searched. Round-1 ignored
    /// exile because nothing read FROM exile yet; round-11 added
    /// `Effect::ExileTarget` (write into exile) and this slice is
    /// the matching "exile is now a first-class read source" half.
    ///
    /// The lookup is membership-based, NOT a read of the object's
    /// `zone` field. That field carries placeholder data on
    /// `make_synthetic_state`-built objects (see `make_object` in
    /// `state.rs` — every fresh object is stamped `zone: 1`
    /// regardless of where it actually lands). `move_object` keeps
    /// the field in sync going forward; this method is the source of
    /// truth either way.
    fn find_object_zone(&self, obj_id: u32) -> Option<u8> {
        for player in &self.players {
            if player.hand.iter().any(|o| o.id == obj_id) {
                return Some(ZONE_HAND);
            }
            if player.library.iter().any(|o| o.id == obj_id) {
                return Some(ZONE_LIBRARY);
            }
            if player.battlefield.iter().any(|o| o.id == obj_id) {
                return Some(ZONE_BATTLEFIELD);
            }
            if player.graveyard.iter().any(|o| o.id == obj_id) {
                return Some(ZONE_GRAVEYARD);
            }
            if player.exile.iter().any(|o| o.id == obj_id) {
                return Some(ZONE_EXILE);
            }
        }
        None
    }

    /// Move the object with id `obj_id` out of its current zone and
    /// into `target_zone` on player `target_player`. Updates the
    /// object's `zone` field to `target_zone` so a later
    /// `find_object_zone` agrees with whatever inspects the field
    /// directly. Returns `True` on success, `False` if no object with
    /// that id exists in any tracked zone.
    ///
    /// CoW-safe: each zone mutation goes through `Arc::make_mut`, so
    /// cloning a `GameState` and then calling `move_object` on the
    /// clone leaves the source state's zone Vecs untouched.
    ///
    /// **Round-14 update:** the source-zone search now also iterates
    /// exile, and `ZONE_EXILE` is a valid destination — so callers
    /// can move an object INTO exile (sidestepping the round-11
    /// ExileTarget effect dispatch when the bare primitive is what's
    /// needed) and OUT of exile back to a tracked zone. Pre-r14 the
    /// dispatch silently routed unknown destinations (incl. exile)
    /// into the graveyard; that fallback remains for any other
    /// non-modeled value (including the stack, which still has no
    /// per-object zone Vec). The module docstring covers the
    /// stack limitation.
    fn move_object(
        &mut self,
        obj_id: u32,
        target_zone: u8,
        target_player: u8,
    ) -> PyResult<bool> {
        // Find + remove from source zone (search both players, all five
        // tracked zones — round-14 added exile to the iteration).
        //
        // Round-29 EoE Void tracking: also remember whether the source
        // zone was the battlefield. If it was AND the object isn't a
        // land (CR 110.4 / EoE Void rule mirror: only nonland permanents
        // leaving the battlefield enable Void), we flip
        // `state.permanent_left_battlefield_this_turn = true` after the
        // remove succeeds. Mirrors Python's
        // `turn.move_off_battlefield` (turn.py:158-164) which gates the
        // flag on `not obj.printing.is_land`. See
        // `docs/RUST_PARITY_GAPS.md` I29 for the full invariant.
        let mut taken: Option<GameObject> = None;
        let mut source_was_battlefield = false;
        for player in self.players.iter_mut() {
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
                source_was_battlefield = true;
                break;
            }
            if let Some(obj) = take_from_zone(&mut player.graveyard, obj_id) {
                taken = Some(obj);
                break;
            }
            if let Some(obj) = take_from_zone(&mut player.exile, obj_id) {
                taken = Some(obj);
                break;
            }
        }
        let Some(mut obj) = taken else {
            return Ok(false);
        };
        // Round-29 Void LTB tracking: flag flips only on
        // battlefield-exit of a nonland permanent. See
        // `mark_left_battlefield_if_nonland` for the full
        // commentary on the gate + reset lifecycle.
        //
        // ETB-trigger Slice 8 (LEAVES_BATTLEFIELD fan-out): queue
        // the leaving object's id for dispatch. Mirrors Python's
        // `_fire_leaves_battlefield_triggers` call in
        // `move_off_battlefield` (turn.py:289) which fires for ALL
        // bf-exits regardless of card type (lands included). The
        // deferred dispatch happens after the move-zone mutation
        // commits and (if there's also a queued ENTERS — e.g.
        // bounce-then-replay primitive) after the ENTERS drain.
        if source_was_battlefield {
            mark_left_battlefield_if_nonland(self, obj.printing_id);
            self.pending_leaves_dispatches.push(obj.id);
        }
        obj.zone = target_zone;
        obj.controller = target_player;
        // CE4 closure: ETB-stamp the object only when it's entering
        // the battlefield. Reserves the timestamp BEFORE the mutable
        // player borrow below.
        if target_zone == ZONE_BATTLEFIELD {
            obj.etb_timestamp = crate::state::reserve_etb_timestamp(self);
            // CE20 Slice 5 (Walker loyalty — starting_loyalty ETB
            // seeding). For a walker entering the battlefield via
            // `move_object`, seed `loyalty_counters` from
            // `printing.starting_loyalty`. No-op for non-walkers.
            crate::state::seed_starting_loyalty_for_etb(self, &mut obj);
        }
        // ETB-trigger Slice 2 (RS9): capture the obj_id of objects
        // entering the battlefield so we can fan-out
        // `dispatch_event(Event::Enters, ...)` AFTER the push releases
        // the player-mut borrow. Non-bf moves leave `entered_id` as
        // None so the dispatch is a no-op for hand/library/exile/
        // graveyard moves.
        let entered_id: Option<u32> = if target_zone == ZONE_BATTLEFIELD {
            Some(obj.id)
        } else {
            None
        };

        let target = &mut self.players[target_player as usize];
        let dest: &mut Zone = match target_zone {
            ZONE_HAND => &mut target.hand,
            ZONE_LIBRARY => &mut target.library,
            ZONE_BATTLEFIELD => &mut target.battlefield,
            ZONE_EXILE => &mut target.exile,
            // ZONE_GRAVEYARD and any unknown value (incl. stack
            // until that lands) fall into the graveyard for now. The
            // module docstring covers the limitation.
            _ => &mut target.graveyard,
        };
        Arc::make_mut(dest).push(obj);
        // ETB-trigger Slice 2 (RS9): queue + drain ENTERS for the
        // newly-arrived bf permanent. Mirrors Python's
        // `put_into_battlefield` per-permanent fan-out — the generic
        // `move_object` primitive carries every Effect arm that
        // routes through it.
        if let Some(id) = entered_id {
            self.pending_etb_dispatches.push(id);
            crate::state_ops_resolve::drain_pending_etb_dispatches(self)?;
        }
        // ETB-trigger Slice 8: drain any queued LEAVES dispatches
        // AFTER the ENTERS drain so a bounce-and-replay primitive
        // (LEAVES + ENTERS in one call) sees ENTERS-then-LEAVES
        // push order — and the stack being LIFO, LEAVES resolves
        // first. (Today's `move_object` carries either a LEAVES
        // OR an ENTERS, never both at once; the ordering pin is
        // defensive for future LTB-into-bounce variants.)
        crate::state_ops_resolve::drain_pending_leaves_dispatches(self)?;
        Ok(true)
    }

    /// Pop the top of `player_id`'s library and push it onto that
    /// player's hand. Returns the drawn object's id, or `None` if
    /// the library was empty.
    ///
    /// "Top of library" = FIRST element of the library `Vec` (index 0),
    /// matching Python's `library.pop(0)` convention. See the module
    /// docstring for the CE3 closure rationale.
    ///
    /// **Empty-library side-effect (CR 704.5b).** When the library
    /// is empty the pop returns `None` AND the player's
    /// `attempted_draw_on_empty` cause-signal is set to `true` —
    /// the next `apply_sbas` pass transitions that into the
    /// sticky `has_lost` flag. `losers()` ALSO OR's the flag in
    /// directly so the loss is observable BEFORE the SBA pass runs.
    /// Mirrors Python's eager `p.has_lost = True` shape in
    /// `turn.draw_card`. Round-26 G10 closure.
    fn draw_card(&mut self, player_id: u8) -> Option<u32> {
        let player = &mut self.players[player_id as usize];
        let lib = Arc::make_mut(&mut player.library);
        if lib.is_empty() {
            // CR 704.5b: empty-library draw flags the player for
            // loss on the next SBA pass.
            player.attempted_draw_on_empty = true;
            return None;
        }
        let mut obj = lib.remove(0);
        obj.zone = ZONE_HAND;
        // Round-28 attach foundation: CR 400.7 clears attach state
        // on zone change. A library card can't legally be attached
        // today, but reset defensively to mirror move_object family.
        obj.attached_to = None;
        obj.exiled_with_source = None;
        let drawn_id = obj.id;
        Arc::make_mut(&mut player.hand).push(obj);
        Some(drawn_id)
    }

    /// Reanimation primitive — move the object with id `obj_id` out of
    /// `player_id`'s graveyard and onto that player's battlefield with
    /// `summoning_sick = true`.
    ///
    /// Specific variant of `move_object` that is hard-coded to
    /// graveyard -> battlefield: the search is restricted to the named
    /// player's graveyard (no cross-player or cross-zone fallback) so
    /// callers can't accidentally yank an opponent's graveyard card or
    /// reanimate something that's still on the battlefield.
    ///
    /// **Per-object state reset on zone change** (CR 400.7) — `tapped`,
    /// `damage`, `counters` are zeroed on the way onto the battlefield.
    /// `summoning_sick` is the deliberate exception: stamped `true`
    /// per CR 302.1 (the new permanent has summoning sickness; the
    /// reanimated creature can't attack on the turn it enters), so a
    /// reanimated creature behaves like a freshly-cast one. Defensive
    /// reset on damage even though a graveyard object shouldn't carry
    /// damage in practice (CR 614.12 — damage clears on zone change
    /// already), but the test suite stamps damage onto the graveyard
    /// object directly to validate the reset arm.
    ///
    /// Returns `Ok(true)` on a successful move, `Ok(false)` if no
    /// object with `obj_id` lives in the named player's graveyard
    /// (whether the id is unknown, on the battlefield, in the hand,
    /// in the library, or in someone else's graveyard). Raises
    /// `IndexError` on out-of-range `player_id` per the loud-fail
    /// convention of every other player-indexed primitive
    /// (`gain_life`, `pay_mana_cost`, `deal_damage_to_player`,
    /// `search_library_for_first_of_type`).
    ///
    /// CoW-safe: each zone Vec mutation routes through `Arc::make_mut`.
    fn move_object_from_graveyard_to_battlefield(
        &mut self,
        player_id: u8,
        obj_id: u32,
    ) -> PyResult<bool> {
        let idx = player_id as usize;
        if idx >= 2 {
            return Err(PyIndexError::new_err(format!(
                "player_id {player_id} out of range (must be 0 or 1)"
            )));
        }
        let pos = match self.players[idx].graveyard.iter().position(|o| o.id == obj_id) {
            Some(p) => p,
            None => return Ok(false),
        };
        // CE4: reserve the timestamp BEFORE the mutable player borrow
        // so we never need a second borrow of `self`.
        let etb_ts = crate::state::reserve_etb_timestamp(self);
        let player = &mut self.players[idx];
        let gy = Arc::make_mut(&mut player.graveyard);
        let mut obj = gy.remove(pos);
        // Per-object state reset (CR 400.7) + the summoning-sickness
        // stamp (CR 302.1). controller stays the same — reanimating
        // onto the player's own battlefield.
        obj.zone = ZONE_BATTLEFIELD;
        obj.tapped = false;
        obj.damage = 0;
        obj.counters = 0;
        obj.summoning_sick = true;
        // Round-28 attach foundation: CR 400.7 clears the attach
        // relationship on zone change. A reanimated Equipment / Aura
        // enters unattached.
        obj.attached_to = None;
        obj.exiled_with_source = None;
        // CE4 closure: stamp ETB timestamp on this reanimation.
        obj.etb_timestamp = etb_ts;
        let entered_id = obj.id;
        Arc::make_mut(&mut player.battlefield).push(obj);
        // ETB-trigger Slice 2 (RS10): queue + drain ENTERS for the
        // reanimated creature. Mirrors Python's
        // `put_into_battlefield` / `_trigger_etb_abilities` call on
        // the reanimation path.
        self.pending_etb_dispatches.push(entered_id);
        crate::state_ops_resolve::drain_pending_etb_dispatches(self)?;
        Ok(true)
    }

    /// Regrowth-style primitive — move the object with id `obj_id` out
    /// of `player_id`'s graveyard and into that player's hand.
    ///
    /// Specific variant of `move_object` that is hard-coded to
    /// graveyard -> hand: the search is restricted to the named
    /// player's graveyard (no cross-player or cross-zone fallback).
    /// The complement of `move_object_from_graveyard_to_battlefield`
    /// (round-17): same shape, but lands in the hand and does NOT
    /// stamp `summoning_sick = true` — cards in hand have no
    /// summoning sickness; that stamp is specific to entering the
    /// battlefield.
    ///
    /// **Per-object state reset on zone change** (CR 400.7) — `tapped`,
    /// `damage`, `counters`, and `summoning_sick` are all zeroed on
    /// the way into the hand. Defensive reset on damage even though
    /// a graveyard object shouldn't carry damage in practice (CR
    /// 614.12 — damage clears on zone change already), but the test
    /// suite stamps damage onto the graveyard object directly to
    /// validate the reset arm.
    ///
    /// Returns `Ok(true)` on a successful move, `Ok(false)` if no
    /// object with `obj_id` lives in the named player's graveyard
    /// (whether the id is unknown, on the battlefield, in the hand,
    /// in the library, or in someone else's graveyard). Raises
    /// `IndexError` on out-of-range `player_id` per the loud-fail
    /// convention of every other player-indexed primitive.
    ///
    /// CoW-safe: each zone Vec mutation routes through `Arc::make_mut`.
    fn move_object_from_graveyard_to_hand(
        &mut self,
        player_id: u8,
        obj_id: u32,
    ) -> PyResult<bool> {
        let idx = player_id as usize;
        if idx >= 2 {
            return Err(PyIndexError::new_err(format!(
                "player_id {player_id} out of range (must be 0 or 1)"
            )));
        }
        let player = &mut self.players[idx];
        let pos = match player.graveyard.iter().position(|o| o.id == obj_id) {
            Some(p) => p,
            None => return Ok(false),
        };
        let gy = Arc::make_mut(&mut player.graveyard);
        let mut obj = gy.remove(pos);
        // Per-object state reset (CR 400.7). controller stays the same
        // — returning to the player's own hand. summoning_sick resets
        // to false (cards in hand have no summoning sickness; the
        // round-17 reanimate variant is the only place that stamps
        // summoning_sick = true).
        obj.zone = ZONE_HAND;
        obj.tapped = false;
        obj.damage = 0;
        obj.counters = 0;
        obj.summoning_sick = false;
        // Round-28 attach foundation: CR 400.7 clears the attach
        // relationship on zone change.
        obj.attached_to = None;
        obj.exiled_with_source = None;
        Arc::make_mut(&mut player.hand).push(obj);
        Ok(true)
    }

    /// Round-28 attach foundation — set `aura_id`'s `attached_to`
    /// slot to `Some(target_id)`. Returns `true` on a successful
    /// stamp, `false` when no GameObject with id `aura_id` exists
    /// in any zone (the `target_id` is NOT validated — callers may
    /// stamp a not-on-bf id; the fingerprint serializer + Python's
    /// equivalent `obj.attached_to = target.id` make the same
    /// "trust the caller" assumption).
    ///
    /// Scans every zone on both players to find the aura; on hit,
    /// goes through `Arc::make_mut` on that zone's Vec to preserve
    /// CoW. Used by tests + future activated-Equip primitives. Not
    /// called by the resolve pipeline (the
    /// `Effect::AttachToTargetCreatureYouControl` arm stamps the
    /// field inline since it already has the source on a bf).
    fn attach(&mut self, aura_id: u32, target_id: u32) -> bool {
        for player in self.players.iter_mut() {
            for zone in [
                &mut player.hand,
                &mut player.library,
                &mut player.battlefield,
                &mut player.graveyard,
                &mut player.exile,
            ] {
                if zone.iter().any(|o| o.id == aura_id) {
                    let z = Arc::make_mut(zone);
                    for obj in z.iter_mut() {
                        if obj.id == aura_id {
                            obj.attached_to = Some(target_id);
                            return true;
                        }
                    }
                }
            }
        }
        false
    }
}
