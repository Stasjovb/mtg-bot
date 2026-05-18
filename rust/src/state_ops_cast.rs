//! Cast / play primitives on `GameState`.
//!
//! First Rust port of the "play" surface — see Python's
//! ``_play_land`` and ``_cast_spell`` in ``src/mtg_bot/actions.py``
//! for the semantics being trimmed down here. The Python pipeline
//! threads alt-costs, room halves, warp / impulse / top-of-library
//! origins, ETB triggers, stack push, and priority pass into one
//! call; this slice carves off the irreducible primitive: take a
//! card from hand, pay its mana, deposit it on the battlefield.
//!
//! ## Scope simplifications
//!
//! - **No stack yet.** Casting a creature spell moves it directly
//!   hand -> battlefield after paying mana. Sorceries / instants /
//!   triggered-via-stack interactions are deferred until a Rust-side
//!   stack lands.
//! - **No one-land-per-turn enforcement.** ``play_land`` does not
//!   consult or update ``lands_played_this_turn``. The Python side
//!   gates this in ``legal_actions``, not inside the play primitive
//!   itself; the primitive's responsibility is the membership move
//!   and the printing-type check. **TODO**: revisit once a per-turn
//!   flag lives on ``GameState`` (today's ``GameState`` has no such
//!   field — adding one would force an edit on ``state.rs`` that
//!   sibling slices need to keep clean this round).
//! - **No sorcery-speed restriction (CR 307.1) yet — so flash
//!   (CR 702.8) is currently a no-op.** ``cast_creature`` does not
//!   gate on ``state.phase`` at all today: a creature spell can be
//!   cast in any phase, including UNTAP, the opponent's combat,
//!   etc. The Python side gates sorcery-speed in ``legal_actions``,
//!   not in the play primitive. When a future slice adds the phase
//!   gate (rejecting non-main casts), the same slice will read
//!   ``printing.keywords`` for ``"flash"`` and skip the gate when
//!   the keyword is present. Until that gate lands, flash creatures
//!   already cast at any phase — vacuously satisfying the rule —
//!   and the ``test_cast.py`` flash tests pin that behavior so the
//!   future slice can extend the guard without regressing flash.
//!   One-land-per-turn is still caller-side, same rationale.
//!
//! ## Type-based detectors: card_types from foundation r6 (cf1fc6c)
//!
//! Foundation r6 added `CardPrinting.card_types: Vec<String>` and
//! seeded the synthetic registry with proper types — Forest carries
//! `["Land"]`, Grizzly Bears and Llanowar Elves both carry
//! `["Creature"]`. This slice rewires both detectors to consult
//! `card_types` directly:
//!
//! - `play_land` accepts iff `card_types` contains `"Land"`.
//! - `cast_creature` accepts iff `card_types` contains `"Creature"`.
//!
//! The round-4 stepping stone — `mana_produced.is_some()` for
//! "this is a land" — has been retired. That predicate produced a
//! documented false-positive on Llanowar Elves (which has
//! `mana_produced = Some(["G"])` in the synthetic seed for the
//! mana-slice's tap-for-mana coverage); the new card_types-based
//! detector correctly rejects elves-as-lands. Symmetrically,
//! `cast_creature` no longer relies on `mana_cost` / `power`
//! heuristics — a Land printing with a mana cost (none exist in
//! the synthetic seed, but the field is structurally allowed)
//! would not slip through.
//!
//! ## Mana payment
//!
//! ``cast_creature`` reads the printing's ``mana_cost``, deducts
//! colored pips from the matching pool slot, then fills generic from
//! whatever's left in W/U/B/R/G/C order. Returns ``false`` (no
//! mutation) if the pool can't cover the colored requirement or the
//! generic fill. Hybrid / X / phyrexian / snow costs are not
//! modeled. The "best-effort spend" heuristic mirrors Python's
//! ``pay_mana_cost`` for first-pass scope; a future slice can
//! introduce a proper search when costs admit multiple legal payment
//! plans.
//!
//! ## CoW invariants
//!
//! Both methods mutate two zones (hand + battlefield) on the same
//! player and the player's mana pool. Each zone goes through
//! ``Arc::make_mut`` so cloning a ``GameState`` and casting on the
//! clone leaves the source state's zones untouched. The mana pool
//! lives by-value in ``Player`` (``ManaPool`` is ``Copy``), so
//! cloning the GameState already deep-copies the pool — no Arc
//! juggling needed there. ``test_clone_then_cast_does_not_affect_original``
//! and ``test_play_land_clone_then_play_does_not_affect_original``
//! are the load-bearing canaries.

use crate::state::{GameObject, GameState, ManaPool};
use pyo3::exceptions::PyIndexError;
use pyo3::prelude::*;
use std::sync::Arc;

const ZONE_BATTLEFIELD: u8 = 2;
/// Local mirror of `crate::state_ops_zones::ZONE_HAND` (= 0),
/// matching the existing `ZONE_BATTLEFIELD` local-const pattern in
/// this module. Used by the G7-S1 exile-recast zone normalization in
/// `cast_creature` (exile -> hand at cast time).
const ZONE_HAND: u8 = 0;

fn check_player_id(player_id: u8) -> PyResult<usize> {
    let idx = player_id as usize;
    if idx >= 2 {
        return Err(PyIndexError::new_err(format!(
            "player_id {player_id} out of range (must be 0 or 1)"
        )));
    }
    Ok(idx)
}

/// Total pip count of a `ManaCost`. Used by `pay_mana_cost`'s
/// insufficient-total fast-fail before the per-color spend loop
/// touches anything.
fn cost_total(cost: &crate::cards::ManaCost) -> u32 {
    cost.generic as u32
        + cost.white as u32
        + cost.blue as u32
        + cost.black as u32
        + cost.red as u32
        + cost.green as u32
}

fn pool_total(pool: &ManaPool) -> u32 {
    pool.white as u32
        + pool.blue as u32
        + pool.black as u32
        + pool.red as u32
        + pool.green as u32
        + pool.colorless as u32
}

/// Try to spend `cost` out of `pool`. On success the pool is
/// debited in place and `true` is returned; on failure the pool
/// is left untouched and `false` is returned.
///
/// Algorithm: pay every colored requirement first (a colored pip
/// can only be paid by its own color), then fill generic in
/// **C first, then W/U/B/R/G** order. The colorless-first ordering
/// matches Magic's "spend colorless before colored" intuition: a
/// player who has both colorless and colored mana will normally
/// prefer to keep their colored mana free for future colored
/// requirements. The test
/// ``test_cast_creature_with_generic_cost_uses_any_color`` pins
/// that ordering against a stray red pip in the pool. A future
/// slice with hybrid / X / phyrexian costs replaces this best-
/// effort spend with a proper plan-search.
/// `pub(crate)` re-export wrapper for the local `pay_mana_cost` so
/// the CE20 Slice 1 ActivateAbility dispatch in
/// `state_ops_actions.rs` can pay mana from the same primitive that
/// spell casts use. Returns the same true-on-success / false-no-
/// mutation semantics.
pub(crate) fn pay_mana_cost_pub(pool: &mut ManaPool, cost: &crate::cards::ManaCost) -> bool {
    pay_mana_cost(pool, cost)
}

fn pay_mana_cost(pool: &mut ManaPool, cost: &crate::cards::ManaCost) -> bool {
    // Fast-fail on totals. Saves a partial spend + rollback in the
    // common "you don't have enough mana, period" case.
    if pool_total(pool) < cost_total(cost) {
        return false;
    }
    // Snapshot so we can roll back on a partial-pay failure (a
    // colored pip the pool can't cover).
    let snapshot = *pool;
    if pool.white < cost.white
        || pool.blue < cost.blue
        || pool.black < cost.black
        || pool.red < cost.red
        || pool.green < cost.green
    {
        return false;
    }
    pool.white -= cost.white;
    pool.blue -= cost.blue;
    pool.black -= cost.black;
    pool.red -= cost.red;
    pool.green -= cost.green;
    let mut generic_remaining = cost.generic as u32;
    for slot in [
        &mut pool.colorless,
        &mut pool.white,
        &mut pool.blue,
        &mut pool.black,
        &mut pool.red,
        &mut pool.green,
    ] {
        if generic_remaining == 0 {
            break;
        }
        let take = (*slot as u32).min(generic_remaining) as u8;
        *slot -= take;
        generic_remaining -= take as u32;
    }
    if generic_remaining > 0 {
        // Shouldn't happen — pool_total covered the case above —
        // but defend anyway with a rollback.
        *pool = snapshot;
        return false;
    }
    true
}

/// Move the GameObject with id `obj_id` out of `state.players[idx].hand`
/// and onto `state.players[idx].battlefield`, stamping its `zone`
/// field to battlefield. Returns the moved object on success, or
/// `None` if no object with that id is in hand. Both zone mutations
/// route through `Arc::make_mut` so the CoW invariant holds.
///
/// **CE4 closure**: stamps the freshly-entering permanent's
/// `etb_timestamp` from `state.next_etb_timestamp` (then bumps the
/// counter by 1, saturating). This is THE canonical bf-entry helper
/// for play_land + cast_creature; future helpers that fold spell
/// resolution into the same primitive should route through here.
fn move_from_hand_to_battlefield(
    state: &mut GameState,
    idx: usize,
    obj_id: u32,
) -> PyResult<Option<GameObject>> {
    let Some(pos) = state.players[idx].hand.iter().position(|o| o.id == obj_id) else {
        return Ok(None);
    };
    // CE4: reserve the timestamp BEFORE the borrow-conflict-prone
    // mutable zone slices so we never need a second borrow of `state`.
    let etb_ts = state.next_etb_timestamp;
    state.next_etb_timestamp = state.next_etb_timestamp.saturating_add(1);
    // CE20 Slice 5 (Walker loyalty — starting_loyalty ETB seeding).
    // Pre-read the printing's walker-and-starting-loyalty shape on
    // the immutable registry BEFORE taking the player-mutable borrow
    // below — Rust borrow checker doesn't do field splitting through
    // method calls so we can't read `state.registry` while holding
    // `&mut state.players[idx]`. Look up by hand.position's pid.
    let starting_loyalty: i32 = {
        let pid = state.players[idx].hand[pos].printing_id;
        match state.registry.lookup(pid) {
            Some(printing)
                if printing.card_types.iter().any(|t| t == "Planeswalker") =>
            {
                printing.starting_loyalty
            }
            _ => 0,
        }
    };
    let player = &mut state.players[idx];
    let hand = Arc::make_mut(&mut player.hand);
    let mut obj = hand.remove(pos);
    obj.zone = ZONE_BATTLEFIELD;
    obj.etb_timestamp = etb_ts;
    // CR 606.5b ETB seed (continued). For non-walkers
    // starting_loyalty is 0, leaving loyalty_counters at its current
    // value (also 0 — the default from make_object).
    if starting_loyalty != 0 {
        obj.loyalty_counters = starting_loyalty;
    }
    let snapshot = obj.clone();
    let entered_id = obj.id;
    let bf = Arc::make_mut(&mut player.battlefield);
    bf.push(obj);
    // ETB-trigger Slice 2 (RS11): queue + drain ENTERS for the
    // freshly-arrived permanent. Routes both `play_land` (CR 305.5
    // — playing a land is not casting a spell, so the land bypasses
    // the stack) and `cast_creature`'s no-stack primitive through
    // the predicate path. The normal stack-cast flow lands via RS1
    // in `state_ops_resolve.rs::resolve_top_of_stack` instead, so
    // this call site is the one place where hand->bf moves outside
    // of a stack resolution emit ENTERS.
    state.pending_etb_dispatches.push(entered_id);
    crate::state_ops_resolve::drain_pending_etb_dispatches(state)?;
    // Return a snapshot clone of the freshly-pushed object for the
    // caller's book-keeping (e.g. summoning-sick stamping is done by
    // the caller AFTER this push via `bf.iter_mut().find()`, see
    // `cast_creature`). Round-27 note: `GameObject` lost its `Copy`
    // derive when `ueot_modifiers: Vec<UeotModifier>` landed, so the
    // pre-r27 "return the moved value by copy" shape now requires an
    // explicit clone — the empty-modifiers warm path makes that
    // clone cheap (a null heap ptr + zero len/cap).
    Ok(Some(snapshot))
}

/// **Phase-1 warp exile-recast (round-63).** Sibling of
/// `move_from_hand_to_battlefield` for the warp exile-recast path: a
/// `warped` object in `player.exile` moves to the battlefield (CR
/// 400.7 — new object; the caller clears `warped`/
/// `warp_exile_pending`). Mirrors the hand helper's CE4 timestamp
/// reservation + walker-loyalty seed + ENTERS drain so the recast
/// permanent is byte-identical to a hand-cast one (modulo the
/// origin zone). Returns the pushed-object snapshot, or `None` if
/// the id isn't a live exile object for `idx`.
///
/// **G7 Slice S1:** `cast_creature` no longer fuses cast+resolve, so
/// the exile-recast no longer moves exile -> battlefield in the cast
/// primitive (it normalizes exile -> hand at cast time and lets
/// `move_source_post_resolve` land it on the battlefield at
/// resolution, byte-mirroring Python). This helper is retained for
/// G7 Slice S4 (`cast_creature_warp` + riders) which still has the
/// exile-recast move pattern to re-home; `#[allow(dead_code)]` keeps
/// the warning quiet in the S1-only interim without deleting the
/// verified helper.
#[allow(dead_code)]
fn move_from_exile_to_battlefield(
    state: &mut GameState,
    idx: usize,
    obj_id: u32,
) -> PyResult<Option<GameObject>> {
    let Some(pos) = state.players[idx]
        .exile
        .iter()
        .position(|o| o.id == obj_id)
    else {
        return Ok(None);
    };
    let etb_ts = state.next_etb_timestamp;
    state.next_etb_timestamp = state.next_etb_timestamp.saturating_add(1);
    let starting_loyalty: i32 = {
        let pid = state.players[idx].exile[pos].printing_id;
        match state.registry.lookup(pid) {
            Some(printing)
                if printing.card_types.iter().any(|t| t == "Planeswalker") =>
            {
                printing.starting_loyalty
            }
            _ => 0,
        }
    };
    let player = &mut state.players[idx];
    let exile = Arc::make_mut(&mut player.exile);
    let mut obj = exile.remove(pos);
    obj.zone = ZONE_BATTLEFIELD;
    obj.etb_timestamp = etb_ts;
    if starting_loyalty != 0 {
        obj.loyalty_counters = starting_loyalty;
    }
    let snapshot = obj.clone();
    let entered_id = obj.id;
    let bf = Arc::make_mut(&mut player.battlefield);
    bf.push(obj);
    state.pending_etb_dispatches.push(entered_id);
    crate::state_ops_resolve::drain_pending_etb_dispatches(state)?;
    Ok(Some(snapshot))
}

/// **Phase-2 warp-cast-from-graveyard (Timeline Culler).** Sibling of
/// `move_from_hand_to_battlefield` / `move_from_exile_to_battlefield`
/// for the graveyard→battlefield warp-cast path: a
/// `warp_castable_from_graveyard` object in `player.graveyard` moves
/// to the battlefield (mirrors Python's `actions.py:1437-1464`
/// `p.graveyard.remove(card)` then `put_into_battlefield`). Identical
/// CE4 timestamp reservation + walker-loyalty seed + ENTERS drain as
/// the hand / exile helpers so the graveyard-warp-cast permanent is
/// byte-identical to a hand-warp-cast one (modulo the origin zone —
/// Timeline Culler has `triggered_abilities=()` so the ETB drain is
/// inert for THIS card but keeps the path forward-correct and
/// identical to the hand arm). Returns the pushed-object snapshot, or
/// `None` if the id isn't a live graveyard object for `idx`.
///
/// **G7 Slice S4:** `cast_creature_warp` no longer fuses
/// cast+resolve, so the graveyard-warp source no longer moves
/// graveyard -> battlefield in the cast primitive (it normalizes
/// graveyard -> hand at cast time — the S1 exile-recast pattern — and
/// lets `move_source_post_resolve` land it on the battlefield at
/// resolution, byte-mirroring Python). This helper is now S4-dead;
/// `#[allow(dead_code)]` keeps the warning quiet without deleting the
/// verified helper (exact treatment S1 gave
/// `move_from_exile_to_battlefield`).
#[allow(dead_code)]
fn move_from_graveyard_to_battlefield(
    state: &mut GameState,
    idx: usize,
    obj_id: u32,
) -> PyResult<Option<GameObject>> {
    let Some(pos) = state.players[idx]
        .graveyard
        .iter()
        .position(|o| o.id == obj_id)
    else {
        return Ok(None);
    };
    let etb_ts = state.next_etb_timestamp;
    state.next_etb_timestamp = state.next_etb_timestamp.saturating_add(1);
    let starting_loyalty: i32 = {
        let pid = state.players[idx].graveyard[pos].printing_id;
        match state.registry.lookup(pid) {
            Some(printing)
                if printing.card_types.iter().any(|t| t == "Planeswalker") =>
            {
                printing.starting_loyalty
            }
            _ => 0,
        }
    };
    let player = &mut state.players[idx];
    let graveyard = Arc::make_mut(&mut player.graveyard);
    let mut obj = graveyard.remove(pos);
    obj.zone = ZONE_BATTLEFIELD;
    obj.etb_timestamp = etb_ts;
    if starting_loyalty != 0 {
        obj.loyalty_counters = starting_loyalty;
    }
    let snapshot = obj.clone();
    let entered_id = obj.id;
    let bf = Arc::make_mut(&mut player.battlefield);
    bf.push(obj);
    state.pending_etb_dispatches.push(entered_id);
    crate::state_ops_resolve::drain_pending_etb_dispatches(state)?;
    Ok(Some(snapshot))
}

#[pymethods]
impl GameState {
    /// Read the `summoning_sick` flag for the battlefield permanent
    /// with id `obj_id`. Returns `Some(flag)` when found, `None`
    /// when no such object lives on either player's battlefield.
    /// Mirrors the read shape of `is_tapped` in `state_ops_tap.rs`.
    /// Lives in this module because the cast slice is the first to
    /// stamp `summoning_sick = true` on a fresh permanent and the
    /// test ``test_cast_creature_summoning_sick_after_cast`` reads
    /// it back. Earlier slices used `summoning_sick: false` as the
    /// `make_object` default but never observed it.
    fn is_summoning_sick(&self, obj_id: u32) -> Option<bool> {
        for player in &self.players {
            for obj in player.battlefield.iter() {
                if obj.id == obj_id {
                    return Some(obj.summoning_sick);
                }
            }
        }
        None
    }

    /// Play a land from `player_id`'s hand onto their battlefield.
    /// Returns `true` on success, `false` on every precondition
    /// failure: no object with `obj_id` in that player's hand, no
    /// such printing in the registry, or the printing's `card_types`
    /// does not contain `"Land"` (clean type-based detector — see
    /// module docstring).
    ///
    /// **Does not enforce one-land-per-turn** — the Python side
    /// gates that in `legal_actions`. **Does not consult sorcery
    /// speed.** Caller's responsibility for both.
    fn play_land(&mut self, obj_id: u32, player_id: u8) -> PyResult<bool> {
        let idx = check_player_id(player_id)?;
        // Locate + read the printing immutably to decide the call's
        // outcome before any Arc::make_mut clone fires.
        let printing_id = match self.players[idx]
            .hand
            .iter()
            .find(|o| o.id == obj_id)
            .map(|o| o.printing_id)
        {
            Some(pid) => pid,
            None => return Ok(false),
        };
        let printing = match self.registry.lookup(printing_id) {
            Some(p) => p,
            None => return Ok(false),
        };
        if !printing.card_types.iter().any(|t| t == "Land") {
            return Ok(false);
        }
        // Commit the move. The hand search re-runs inside
        // `move_from_hand_to_battlefield`; that's fine — the cost is
        // a single second linear scan we already know will hit, and
        // it keeps the helper self-contained.
        let moved = move_from_hand_to_battlefield(self, idx, obj_id)?;
        Ok(moved.is_some())
    }

    /// **G7 Slice S1 (stack-and-priority creature cast).** Cast a
    /// creature spell from `player_id`'s hand. Pays the printing's
    /// `mana_cost` out of the player's mana pool, fires `Event::Cast`,
    /// and **pushes a spell `StackItem`** — the card does NOT enter
    /// the battlefield here. Returns `true` on success, `false` on
    /// any precondition failure: object not in hand (nor a `warped`
    /// exile-recast), no such printing, the printing's `card_types`
    /// does not contain `"Creature"`, or insufficient mana.
    ///
    /// **Stack-and-priority semantics (G7 Slice S1 — was no-stack).**
    /// This primitive now mirrors `cast_spell_noncreature` exactly:
    /// it pays mana, dispatches the CAST event, pushes a
    /// `StackItem::new_spell` (the spell GameObject stays in the hand
    /// zone — Rust's pre-existing spell-stack model;
    /// `find_source_printing_id` / `take_source` search the hand at
    /// resolve), resets priority/passes, and **returns WITHOUT
    /// resolving**. The harness drives `resolve_top_of_stack`
    /// separately (CE5 cast-vs-resolve mirror today; the real
    /// adapter priority loop in production). At resolution the
    /// ALREADY-PRESENT `move_source_post_resolve`
    /// (`state_ops_resolve.rs:285-332`) lands the creature on the
    /// battlefield with `summoning_sick = true` (`:301-303`) + a
    /// fresh ETB timestamp (`:311-318`), then `resolve_top_of_stack`
    /// dispatches `Event::Enters` — byte-mirroring Python's
    /// resolve-time `put_into_battlefield` (`actions.py:2778` ->
    /// `:2993` sets `summoning_sick = True`). NO `summoning_sick`
    /// stamp is applied here at cast time — Python doesn't either
    /// (`_cast_spell` `actions.py:1403/1751-1767` only removes the
    /// card from its source zone, sets `zone=STACK`, and appends the
    /// `StackItem`; the bf entry + summoning sickness happen at
    /// resolve).
    ///
    /// Creature spells carry NO cast-time target (a vanilla permanent
    /// spell has no `_select_spell_targets` pick), so the bare
    /// untargeted `StackItem::new_spell` constructor is used (vs
    /// `cast_spell_noncreature`'s `new_spell_with_targets` for
    /// single-/two-target instants/sorceries). `cast_creature_warp`
    /// + the warp/impending/room riders are deferred to G7 Slice S4
    /// (this S1 lane is creature-only, non-warp; the
    /// `cast_creature_warp` primitive is untouched here).
    fn cast_creature(&mut self, obj_id: u32, player_id: u8) -> PyResult<bool> {
        let idx = check_player_id(player_id)?;
        // Phase 1: read-only lookup. Find the object in hand, fetch
        // the printing's cost + types. Bail before any mutation if
        // any step fails. The type check happens here (pre-mutation)
        // so a non-creature spell never has its mana speculatively
        // debited.
        //
        // **Phase-1 warp exile-recast (round-63):** if the object is
        // NOT in hand but IS a `warped` object in this player's
        // exile, this is a warp exile-recast — pay the NORMAL
        // `mana_cost` (legal.py:478-489 / actions.py:1476-1510). The
        // hand path is tried first (the common case); the exile
        // fallback only fires for a `warped` exile object. Both pay
        // `mana_cost` (the recast is at full cost — `use_warp=false`).
        let in_hand = self.players[idx]
            .hand
            .iter()
            .any(|o| o.id == obj_id);
        let from_exile_warped = !in_hand
            && self.players[idx]
                .exile
                .iter()
                .any(|o| o.id == obj_id && o.warped);
        let printing_id = if in_hand {
            match self.players[idx]
                .hand
                .iter()
                .find(|o| o.id == obj_id)
                .map(|o| o.printing_id)
            {
                Some(pid) => pid,
                None => return Ok(false),
            }
        } else if from_exile_warped {
            match self.players[idx]
                .exile
                .iter()
                .find(|o| o.id == obj_id && o.warped)
                .map(|o| o.printing_id)
            {
                Some(pid) => pid,
                None => return Ok(false),
            }
        } else {
            return Ok(false);
        };
        let cost = match self.registry.lookup(printing_id) {
            Some(p) => {
                if !p.card_types.iter().any(|t| t == "Creature") {
                    return Ok(false);
                }
                p.mana_cost.clone()
            }
            None => return Ok(false),
        };
        // Phase 2: try the mana spend on a copy of the pool. If it
        // succeeds, commit; otherwise return false with no mutation.
        let mut pool_copy = self.players[idx].mana_pool;
        if !pay_mana_cost(&mut pool_copy, &cost) {
            return Ok(false);
        }
        self.players[idx].mana_pool = pool_copy;
        // **G7 S1 exile-recast zone normalization.** Python's
        // exile-recast (`actions.py:1501-1502`) does
        // `p.exile.remove(card)` then `card.warped = False` AT CAST
        // TIME, and `card.zone = Zone.STACK` (`:1751`) — the recast
        // card leaves exile and sits on the STACK until resolution
        // (byte-identical to the hand path; nothing on the
        // battlefield yet). Rust's spell-stack model keeps the
        // stack-resident source IN a tracked zone, and
        // `find_source_printing_id` / `take_source`
        // (`state_ops_resolve.rs:205-246`) search hand / library /
        // battlefield / graveyard but **NOT exile**. So move the
        // exile-recast object exile -> hand here (the zone the
        // spell-stack model uses for its stack-resident source,
        // exactly as `cast_spell_noncreature` leaves its source in
        // hand) and clear the warp markers at cast time, mirroring
        // Python's cast-time `card.warped = False`. At resolution
        // `move_source_post_resolve` takes it hand -> battlefield
        // (creature -> bf + summoning_sick), byte-equal to Python's
        // `put_into_battlefield`. The recast is a fresh permanent
        // (CR 400.7) — clearing `warp_exile_pending` too matches the
        // prior no-stack primitive's clear.
        if from_exile_warped {
            if let Some(pos) = self.players[idx]
                .exile
                .iter()
                .position(|o| o.id == obj_id)
            {
                let exile = Arc::make_mut(&mut self.players[idx].exile);
                let mut obj = exile.remove(pos);
                obj.zone = ZONE_HAND;
                obj.warped = false;
                obj.warp_exile_pending = false;
                let hand = Arc::make_mut(&mut self.players[idx].hand);
                hand.push(obj);
            }
        }
        // Dispatch Event::Cast NOW — after mana payment commits but
        // before the StackItem push, the SAME ordering as
        // `cast_spell_noncreature` (Delta 6, `:842-850`) /
        // `cast_creature_warp`. CR 601.2 — a spell is "cast" the
        // moment its cost is paid. The subject is the card-being-cast
        // still in the hand zone (the push leaves it there);
        // predicate matchers walk all four zones so the hand-zone
        // lookup finds it.
        crate::state_ops_resolve::dispatch_event(
            self,
            crate::cards::Event::Cast,
            obj_id,
        )?;
        // **G7 S1: push the spell StackItem, do NOT move to
        // battlefield, do NOT auto-resolve.** Mirrors
        // `cast_spell_noncreature`'s Delta-4 push (`:943-957`). A
        // vanilla creature spell carries NO cast-time target (Python
        // `_select_spell_targets` returns `()` for a bare permanent
        // spell), so the bare untargeted `new_spell` constructor is
        // used. `resolve_top_of_stack` later applies any
        // `printing.effects` (none for a vanilla creature) and
        // `move_source_post_resolve` sends the creature hand ->
        // battlefield (CR 608.2m via the ALREADY-PRESENT
        // `post_resolve_destination` permanent -> ZONE_BATTLEFIELD
        // route, stamping `summoning_sick` + the ETB timestamp), then
        // `dispatch_event(Event::Enters)` fires the ETB triggers —
        // all at resolution time, byte-mirroring Python's
        // `put_into_battlefield`.
        self.stack
            .push(crate::state::StackItem::new_spell(obj_id, player_id));
        // CR 117.1c — the active player gets priority after a spell
        // is cast. Verbatim from `cast_spell_noncreature` Delta 7
        // (`:958-962`) / `cast_creature_warp`. The cast push (not the
        // resolution pop) is the reset moment, matching Python: the
        // priority loop resets priority via the post-non-pass-action
        // path (`simulate.py:274-282`) when the cast is applied, then
        // resets again after the eventual resolution
        // (`simulate.py:266-267`). The post-cast reset here is the
        // first of those two; the post-resolution reset is the loop's
        // job (S3 verifies the priority-round composition end-to-end).
        // Also reset `consecutive_passes` — a successful cast is a
        // non-pass mutation that breaks any pass streak.
        self.priority_player = self.active_player;
        self.consecutive_passes = 0;
        Ok(true)
    }

    /// **G7 Slice S4 (stack-and-priority warp-creature cast).**
    /// Warp-cast a creature from `player_id`'s hand OR (if absent
    /// there and the printing is `warp_castable_from_graveyard`) the
    /// GRAVEYARD. Mirrors `cast_creature`'s S1 stack-push shape with
    /// the warp deltas. Verified against the live `cast_creature` +
    /// Python `actions.py:1393-1560` / `put_into_battlefield`.
    ///
    /// **Stack-and-priority semantics (G7 Slice S4 — was atomic).**
    /// Pays `warp_cost`, debits the warp life rider, sets
    /// `state.spell_warped_this_turn = true` (the genuinely cast-time
    /// riders — Python sets all three in `_cast_spell` BEFORE the
    /// StackItem push), stamps `warp_exile_pending = true` on the
    /// stack-resident SOURCE object (NOT on a bf object — there is no
    /// bf object yet), fires `Event::Cast`, pushes a bare
    /// `StackItem::new_spell` (the spell GameObject stays in its
    /// origin zone — Rust's spell-stack model), resets
    /// priority/passes, and **returns WITHOUT resolving**. At
    /// resolution the ALREADY-PRESENT `move_source_post_resolve`
    /// (`state_ops_resolve.rs:285-332`) lands the creature on the
    /// battlefield with `summoning_sick = true` (`:301-303`) + a
    /// fresh ETB timestamp, then `resolve_top_of_stack` dispatches
    /// `Event::Enters` — byte-mirroring Python's resolve-time
    /// `put_into_battlefield` (`actions.py:2993` sets
    /// `summoning_sick`). `take_source` moves the WHOLE owned object
    /// (fields intact), so the cast-time `warp_exile_pending` rides
    /// onto the post-resolution bf object — exactly where the
    /// end-step sweep (`state_ops_steps.rs::
    /// warp_exile_sweep_on_end_step`) keys off it. NO `summoning_sick`
    /// / `warp_exile_pending`-on-a-bf-object stamp here at cast time
    /// (the design's key risk — resolved structurally by riding the
    /// flag on the source object, the direct mirror of S1's
    /// exile-recast zone normalization).
    ///
    /// **Deltas vs `cast_creature` (S1 shape):**
    ///
    /// 0. **Source-zone cascade:** hand first, then graveyard gated
    ///    on `warp_castable_from_graveyard` — mirrors Python's single
    ///    `_cast_spell` `if hand: ... elif gy-warp:` cascade so the
    ///    `Action::CastSpell` dispatch site stays byte-identical.
    /// 1. **Cost source:** pays `printing.warp_cost` (unwrapped — the
    ///    legal emitter only offered `use_warp=true` when this is
    ///    `Some`) instead of `printing.mana_cost`. Mirrors Python's
    ///    `effective_warp_cost(...)[0]` (`actions.py:1399-1400`) / the
    ///    graveyard branch's `card.printing.warp_cost` (`:1448`).
    /// 1b. **Life rider:** after the mana spend commits, debit
    ///    `printing.warp_additional_life_cost` UNCONDITIONALLY (CR
    ///    117.9b — part of the warp alternative cost, no decision
    ///    point). Genuinely cast-time in Python (`:1432`/`:1460`).
    /// 2. **`spell_warped_this_turn`:** set `true` after the mana
    ///    spend commits, mirroring Python `:1427` (hand) / `:1457`
    ///    (graveyard). A `GameState` bool; genuinely cast-time.
    /// 3. **`warp_exile_pending`:** stamp `true` on the STACK-RESIDENT
    ///    SOURCE object (hand arm) or normalize the graveyard-warp
    ///    source graveyard→hand and stamp it there (graveyard arm),
    ///    so it rides through `move_source_post_resolve` onto the
    ///    post-resolution bf object. Set IDENTICALLY for both arms —
    ///    Python schedules the SAME `WarpExileSelf` for both
    ///    (`actions.py:1550-1559`). Rust's model: a deterministic
    ///    phase-entry sweep keyed off the bf object's flag, NOT
    ///    Python's stack-pushed delayed trigger (documented in
    ///    `SEARCH_LIMITATIONS.md`).
    /// 4. **Graveyard-source normalization:** like S1's exile-recast
    ///    (`cast_creature` exile→hand at cast time), the
    ///    graveyard-warp source is normalized graveyard→hand at cast
    ///    time so it byte-matches Python's `p.graveyard.remove(card)`
    ///    + `card.zone = STACK` (`:1450`/`:1751`) and the spell-stack
    ///    source model stays uniform with the hand arm. The
    ///    `move_from_graveyard_to_battlefield` /
    ///    `move_from_exile_to_battlefield` helpers are S4-dead for
    ///    this path (retained `#[allow(dead_code)]`, same treatment
    ///    S1 gave the exile helper).
    /// 5. **Priority tail:** verbatim from `cast_creature` (S1).
    ///
    /// Returns `true` on success, `false` on the same precondition
    /// failures as `cast_creature` plus "not in hand AND (not in
    /// graveyard OR not `warp_castable_from_graveyard`)" / "the
    /// printing has no `warp_cost`" (defensive — the legal emitter
    /// never offers `use_warp=true` without these).
    fn cast_creature_warp(
        &mut self,
        obj_id: u32,
        player_id: u8,
    ) -> PyResult<bool> {
        let idx = check_player_id(player_id)?;
        // **Phase-2 source-zone resolution (mirrors Python's
        // `_cast_spell` `if card in hand: ... elif graveyard-warp:`
        // cascade in ONE function — actions.py:1393/1437).** Look up
        // the object in the HAND first; if absent, fall through to
        // the GRAVEYARD gated on `warp_castable_from_graveyard`. This
        // keeps the `Action::CastSpell` dispatch site byte-identical
        // (no new arm) — exactly as Python keeps the cascade inside
        // `_cast_spell`. `from_graveyard` records which arm fired so
        // the move + provenance match Python's two branches.
        let (printing_id, from_graveyard) = if let Some(pid) = self
            .players[idx]
            .hand
            .iter()
            .find(|o| o.id == obj_id)
            .map(|o| o.printing_id)
        {
            (pid, false)
        } else if let Some(pid) = self.players[idx]
            .graveyard
            .iter()
            .find(|o| o.id == obj_id)
            .map(|o| o.printing_id)
        {
            // Only the graveyard-cast rider authorizes a
            // graveyard-origin warp cast (Python actions.py:1444
            // `grave_card.printing.warp_castable_from_graveyard`).
            let gy_ok = self
                .registry
                .lookup(pid)
                .map(|p| p.warp_castable_from_graveyard)
                .unwrap_or(false);
            if !gy_ok {
                return Ok(false);
            }
            (pid, true)
        } else {
            return Ok(false);
        };
        // Delta 1: pay `warp_cost` (not `mana_cost`). Bail if the
        // printing has no warp (defensive) or isn't a creature.
        let (cost, life_cost) = match self.registry.lookup(printing_id) {
            Some(p) => {
                if !p.card_types.iter().any(|t| t == "Creature") {
                    return Ok(false);
                }
                let wc = match &p.warp_cost {
                    Some(wc) => wc.clone(),
                    None => return Ok(false),
                };
                (wc, p.warp_additional_life_cost)
            }
            None => return Ok(false),
        };
        let mut pool_copy = self.players[idx].mana_pool;
        if !pay_mana_cost(&mut pool_copy, &cost) {
            return Ok(false);
        }
        self.players[idx].mana_pool = pool_copy;
        // Delta 2: production write of `spell_warped_this_turn`
        // (mirrors Python actions.py:1427 hand / :1457 graveyard —
        // BOTH branches set it). Plain bool on GameState, no CoW.
        // Set after the mana spend commits.
        self.spell_warped_this_turn = true;
        // **Phase-2: pay the warp ability's "Pay N life" rider**
        // (Timeline Culler). The legal emitter has already gated
        // `life > warp_additional_life_cost`, so this never drops
        // the caster below 1. `life_cost == 0` (every Phase-1/1.5
        // card) is a no-op. Mirrors Python actions.py:1430-1436
        // (hand) / :1458-1464 (graveyard) — debited unconditionally
        // inside the cast (CR 117.9b: the Pay-2-life is part of the
        // warp alternative cost, no decision point). Player.life is
        // i32; widen the u8 rider to match.
        if life_cost > 0 {
            self.players[idx].life -= life_cost as i32;
        }
        // **G7 S4 Delta 4: graveyard-source zone normalization.**
        // Python's graveyard-warp branch (`actions.py:1450`) does
        // `p.graveyard.remove(card)` then `card.zone = Zone.STACK`
        // (`:1751`) AT CAST TIME — the source leaves the graveyard
        // and sits on the STACK until resolution (byte-identical to
        // the hand arm; nothing on the battlefield yet). Rust's
        // spell-stack model keeps the stack-resident source IN a
        // tracked zone; to byte-match Python's "card left the
        // graveyard at cast time" AND keep the spell-stack source
        // model uniform with the hand arm, normalize the
        // graveyard-warp source graveyard -> hand here (the same zone
        // the hand arm leaves its source in; the EXACT shape of S1's
        // exile-recast exile -> hand normalization in `cast_creature`
        // `:576-590`). `find_source_printing_id` / `take_source`
        // (`state_ops_resolve.rs:205-245`) then find it in the hand
        // at resolve and `move_source_post_resolve` lands it on the
        // battlefield (creature -> bf + summoning_sick), byte-equal
        // to Python's `put_into_battlefield`. The
        // `move_from_graveyard_to_battlefield` helper is now S4-dead
        // for this path (retained `#[allow(dead_code)]`, same
        // treatment S1 gave `move_from_exile_to_battlefield`).
        if from_graveyard {
            if let Some(pos) = self.players[idx]
                .graveyard
                .iter()
                .position(|o| o.id == obj_id)
            {
                let gy =
                    Arc::make_mut(&mut self.players[idx].graveyard);
                let mut obj = gy.remove(pos);
                obj.zone = ZONE_HAND;
                let hand =
                    Arc::make_mut(&mut self.players[idx].hand);
                hand.push(obj);
            }
        }
        // **G7 S4 Delta 3: stamp `warp_exile_pending` on the
        // STACK-RESIDENT SOURCE object (NOT a bf object — there is no
        // bf object yet).** `take_source` moves the WHOLE owned
        // GameObject (fields intact, nothing reset —
        // `state_ops_resolve.rs:230-245`) and
        // `move_source_post_resolve` pushes it to the battlefield
        // (`:285-332`), so this cast-time flag rides through
        // resolution onto the post-resolution bf object — exactly
        // where the end-step sweep
        // (`state_ops_steps.rs::warp_exile_sweep_on_end_step`) keys
        // off it. Set IDENTICALLY for the hand AND (now
        // hand-normalized) graveyard arm — Python schedules the SAME
        // `WarpExileSelf` for both (`actions.py:1550-1559` runs for
        // any `use_warp`). This is the design's "key risk" resolved
        // structurally: no new field, no StackItem rider slot, no
        // `state.rs` serialization touch — the direct mirror of S1's
        // exile-recast object-field-on-the-stack-resident-source
        // pattern. (After the graveyard normalization above, the
        // source for BOTH arms is in this player's HAND.)
        if let Some(pos) = self.players[idx]
            .hand
            .iter()
            .position(|o| o.id == obj_id)
        {
            let hand = Arc::make_mut(&mut self.players[idx].hand);
            hand[pos].warp_exile_pending = true;
        }
        // Dispatch Event::Cast NOW — after mana payment + the
        // cast-time riders commit but before the StackItem push, the
        // SAME ordering as `cast_creature` (S1, `:599-603`) /
        // `cast_spell_noncreature`. CR 601.2 — a spell is "cast" the
        // moment its cost is paid. The subject is the card-being-cast
        // still in the hand zone (the push leaves it there; the
        // graveyard arm was normalized into the hand above); predicate
        // matchers walk all four zones so the hand-zone lookup finds
        // it.
        crate::state_ops_resolve::dispatch_event(
            self,
            crate::cards::Event::Cast,
            obj_id,
        )?;
        // **G7 S4: push the spell StackItem, do NOT move to
        // battlefield, do NOT auto-resolve.** Verbatim from
        // `cast_creature` (S1, `:619-620`). A vanilla creature spell
        // (warp cards: Timeline Culler etc. have
        // `triggered_abilities=()`) carries NO cast-time target, so
        // the bare untargeted `new_spell` constructor is used.
        // `resolve_top_of_stack` later runs `move_source_post_resolve`
        // (creature hand -> battlefield, stamping `summoning_sick` +
        // the ETB timestamp; the `warp_exile_pending` flag rides
        // along on the owned object) then `dispatch_event(Enters)` —
        // all at resolution, byte-mirroring Python's
        // `put_into_battlefield`.
        self.stack
            .push(crate::state::StackItem::new_spell(obj_id, player_id));
        // Delta 5: priority/passes reset, verbatim from `cast_creature`
        // (S1, `:633-634`). The cast push (not the resolution pop) is
        // the reset moment, matching Python's post-non-pass-action
        // priority reset (`simulate.py:274-282`); the post-resolution
        // reset is the priority loop's job.
        self.priority_player = self.active_player;
        self.consecutive_passes = 0;
        Ok(true)
    }

    /// **Spell-card-bridge lever, Phase 1 (round-70).** Cast a
    /// non-creature Instant/Sorcery from `player_id`'s hand. Sibling
    /// of `cast_creature` / `cast_creature_warp` with these deltas
    /// (verified against both live bodies):
    ///
    /// 1. **Hand lookup only** (no exile-recast branch — that is
    ///    warp-specific). Mirrors `cast_creature_warp`'s simple
    ///    `hand.iter().find(...).map(|o| o.printing_id)` shape.
    /// 2. **Type gate inverted:** require `"Instant"` OR `"Sorcery"`
    ///    in `card_types` AND NOT `"Creature"` (the dual of
    ///    `cast_creature`'s `:444` Creature gate). Same pre-mutation
    ///    `Ok(false)` bail shape so a non-spell never has its mana
    ///    speculatively debited. Returning `Ok(false)` for a creature
    ///    lets the `Action::CastSpell` dispatch try this primitive
    ///    first-after-warp then fall through to `cast_creature`.
    /// 3. **Pay `printing.mana_cost`** (the guardrail rejected
    ///    X / kicker / warp / additional-cost-choice, so `mana_cost`
    ///    is the whole cost). Exact `cast_creature:453-457` shape.
    /// 4. **Push a spell `StackItem`, do NOT move to battlefield.**
    ///    The spell GameObject stays in the hand zone (Rust's
    ///    pre-existing spell-stack model — `find_source_printing_id` /
    ///    `take_source` search hand; the existing
    ///    `mass_removal_side_channel` / Doom-Blade resolve path relies
    ///    on this). `resolve_top_of_stack` then applies
    ///    `printing.effects` and `move_source_post_resolve` takes the
    ///    card from hand → graveyard via the ALREADY-PRESENT
    ///    Instant/Sorcery → ZONE_GRAVEYARD route
    ///    (`post_resolve_destination:251-256`, UNCHANGED — the
    ///    spell→graveyard move is FREE; CR 608.2m already handled).
    /// 5. **Bind the single target at cast time** via the same
    ///    deterministic-first scan the per-card bespoke Effect resolve
    ///    arms apply (the no-callback first-legal-target campaign
    ///    convention; mirrors Python's `_select_spell_targets`
    ///    binding ONE target onto the StackItem at cast time). Stored
    ///    in `StackItem.target_obj_id` (Gate B'', §3.4). The closed
    ///    Tier-A spell arms self-scan the battlefield and ignore the
    ///    payload target, so the swap is a correct no-op for them
    ///    (byte-equality is delivered by self-scan == Python
    ///    first-legal, proven by the Tier-A real-EoE probes); the
    ///    field is the forward substrate for targeted arms that opt
    ///    into the payload-target convention.
    /// 6. **Fire the `Event::Cast` dispatch** before the stack push,
    ///    same ordering as `cast_creature:470-474` /
    ///    `cast_creature_warp:585-589`.
    /// 7. **Resolve is NOT fused.** The primitive pushes the
    ///    StackItem and returns; the harness drives
    ///    `resolve_top_of_stack` separately (CE5 cast-vs-resolve
    ///    mirror — `step_both` drains both stacks before the
    ///    field-view compare, so the mid-stack card-in-hand asymmetry
    ///    vs Python is never compared; the compare is post-resolve).
    ///
    /// Returns `true` on success, `false` on the same precondition
    /// failures as `cast_creature` (object not in hand, no such
    /// printing, insufficient mana) PLUS "the printing is not a
    /// non-creature Instant/Sorcery".
    fn cast_spell_noncreature(
        &mut self,
        obj_id: u32,
        player_id: u8,
    ) -> PyResult<bool> {
        let idx = check_player_id(player_id)?;
        // Delta 1: hand lookup only.
        let printing_id = match self.players[idx]
            .hand
            .iter()
            .find(|o| o.id == obj_id)
            .map(|o| o.printing_id)
        {
            Some(pid) => pid,
            None => return Ok(false),
        };
        // Delta 2: inverted type gate — Instant/Sorcery AND NOT
        // Creature. Bail (no mutation) on anything else so the
        // dispatch can fall through to `cast_creature`.
        let cost = match self.registry.lookup(printing_id) {
            Some(p) => {
                let is_spell = p
                    .card_types
                    .iter()
                    .any(|t| t == "Instant" || t == "Sorcery");
                let is_creature = p
                    .card_types
                    .iter()
                    .any(|t| t == "Creature");
                if !is_spell || is_creature {
                    return Ok(false);
                }
                p.mana_cost.clone()
            }
            None => return Ok(false),
        };
        // Delta 3: pay `mana_cost` on a pool copy; commit or bail.
        let mut pool_copy = self.players[idx].mana_pool;
        if !pay_mana_cost(&mut pool_copy, &cost) {
            return Ok(false);
        }
        self.players[idx].mana_pool = pool_copy;
        // Delta 6: CAST event before the stack push, same ordering as
        // `cast_creature` / `cast_creature_warp`. The subject is the
        // card still in hand (the push leaves it there); predicate
        // matchers walk all zones so the hand-zone lookup finds it.
        crate::state_ops_resolve::dispatch_event(
            self,
            crate::cards::Event::Cast,
            obj_id,
        )?;
        // Delta 5: bind the deterministic-first legal target(s).
        //
        // **Phase 1 (single-target, `target_slot_kinds()==()`):** the
        // first creature on EITHER battlefield in `bf_iter_etb_sorted`
        // order (Python's centralized `state.battlefield` walk + the
        // deterministic-first convention). The closed Tier-A spell
        // arms self-scan and ignore it; it is the forward substrate
        // for payload-target-reading arms.
        //
        // **Phase 2 (2-slot heterogeneous grammar — Diplomatic
        // Relations):** the printing's `effects[0]` is the 2-slot
        // effect. Python's `_select_spell_targets` iterates
        // `target_slot_kinds()` and, per slot, filters the flat
        // `legal_targets` to the slot's kind and picks the
        // first-legal (the `_PickFirstLegalTargetAgent` bench/probe
        // convention). For Diplomatic Relations the kinds are
        // `("my_creature","creature")` and `legal_targets` is
        // `mine ++ theirs` in `state.battlefield` order, so:
        //   slot 0 = first creature the caster controls,
        //   slot 1 = first creature a NON-caster controls.
        // We re-derive that EXACT pair here off `bf_iter_etb_sorted`
        // (the cross-engine-proven equivalent of Python's
        // `state.battlefield` ordering — the same equivalence the
        // Phase-1 Depressurize/Focus-Fire real-EoE probes pinned),
        // partitioned by `o.controller == player_id`. Bound at cast
        // time so the picks are fixed on the StackItem (matching
        // Python binding two targets onto the StackItem at cast
        // time). The bare-single-target detection stays the default:
        // a 2-slot effect is detected structurally via
        // `Effect::DiplomaticRelationsEffect` (the ONLY 2-slot
        // grammar admitted today; the guardrail
        // `_printing_is_bridge_simple_spell` Phase-2 widening only
        // lets this exact shape through).
        let is_two_slot = self
            .registry
            .lookup(printing_id)
            .map(|p| {
                matches!(
                    p.effects.first(),
                    Some(crate::cards::Effect::DiplomaticRelationsEffect)
                )
            })
            .unwrap_or(false);
        let (bound_target, bound_target_2): (Option<u32>, Option<u32>) =
            if is_two_slot {
                // 2-slot: slot 0 = first caster-controlled creature,
                // slot 1 = first non-caster-controlled creature, both
                // in `bf_iter_etb_sorted` order.
                let mut slot0: Option<u32> = None;
                let mut slot1: Option<u32> = None;
                for o in crate::bf_iter::bf_iter_etb_sorted(self) {
                    let is_creature = self
                        .registry
                        .lookup(o.printing_id)
                        .map(|p| {
                            p.card_types.iter().any(|t| t == "Creature")
                        })
                        .unwrap_or(false);
                    if !is_creature {
                        continue;
                    }
                    if o.controller == player_id {
                        if slot0.is_none() {
                            slot0 = Some(o.id);
                        }
                    } else if slot1.is_none() {
                        slot1 = Some(o.id);
                    }
                    if slot0.is_some() && slot1.is_some() {
                        break;
                    }
                }
                (slot0, slot1)
            } else {
                // Phase-1 single-target: first creature on EITHER bf.
                let t = crate::bf_iter::bf_iter_etb_sorted(self)
                    .into_iter()
                    .find_map(|o| {
                        let printing =
                            self.registry.lookup(o.printing_id)?;
                        if printing
                            .card_types
                            .iter()
                            .any(|t| t == "Creature")
                        {
                            Some(o.id)
                        } else {
                            None
                        }
                    });
                (t, None)
            };
        // Delta 4: push the spell StackItem (card stays in hand —
        // Rust's pre-existing spell-stack model). The existing
        // `resolve_top_of_stack` drains it: applies `printing.effects`
        // with the target(s) swapped in, then
        // `move_source_post_resolve` sends the spell hand → graveyard
        // (FREE — CR 608.2m). `new_spell_with_targets` carries both
        // slots; `target_obj_id_2` is `None` for Phase-1 single-target
        // pushes (back-compat — byte-identical to the prior
        // single-slot push the Phase-2 unified constructor subsumed).
        self.stack.push(crate::state::StackItem::new_spell_with_targets(
            obj_id,
            player_id,
            bound_target,
            bound_target_2,
        ));
        // Delta 7: priority/passes reset, verbatim from
        // `cast_creature` / `cast_creature_warp`.
        self.priority_player = self.active_player;
        self.consecutive_passes = 0;
        Ok(true)
    }
}
