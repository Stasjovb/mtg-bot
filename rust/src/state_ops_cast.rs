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

    /// Cast a creature spell from `player_id`'s hand. Pays the
    /// printing's `mana_cost` out of the player's mana pool, moves
    /// the card to the battlefield, and stamps the new permanent
    /// with `summoning_sick = true`. Returns `true` on success,
    /// `false` on any precondition failure: object not in hand, no
    /// such printing, the printing's `card_types` does not contain
    /// `"Creature"`, or insufficient mana.
    ///
    /// **No-stack semantics.** The Python pipeline pushes a
    /// `StackItem`, settles priority, then resolves; this primitive
    /// short-circuits to the resolved state. ETB triggers, "when X
    /// is cast" hooks, and any choice points the spell normally
    /// presents are deferred until a Rust-side stack lands.
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
        // `mana_cost` (legal.py:478-489 / actions.py:1476-1510), move
        // exile->bf, clear `warped`. The hand path is tried first
        // (the common case); the exile fallback only fires for a
        // `warped` exile object. Both pay `mana_cost` (the recast is
        // at full cost — `use_warp=false`).
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
        // Slice 6: dispatch Event::Cast NOW — after mana payment
        // commits but before the move-to-bf fires its ENTERS
        // dispatch. CR 601.2 — a spell is "cast" the moment its
        // cost is paid (technically before, but post-cost-pay is
        // the closest moment Rust's no-stack primitive can hook
        // into). CAST fires BEFORE ENTERS, matching the Python flow
        // where the spell stack item resolves on top of the cast
        // event.
        //
        // The subject is the card-being-cast still in the hand zone
        // (move-to-bf hasn't fired yet). Predicate matchers walk
        // all four zones so the hand-zone lookup finds it.
        crate::state_ops_resolve::dispatch_event(
            self,
            crate::cards::Event::Cast,
            obj_id,
        )?;
        // Phase 3: move the card. Stamp summoning sickness AFTER the
        // push (stamp on the in-place battlefield slot, since
        // `move_from_hand_to_battlefield` returns the snapshot at
        // push time). The warp exile-recast moves exile->bf via the
        // sibling helper and clears the `warped` marker (the recast
        // is a fresh permanent — CR 400.7 — mirroring Python
        // actions.py:1502 `card.warped = False`).
        if from_exile_warped {
            let _ = move_from_exile_to_battlefield(self, idx, obj_id)?;
        } else {
            let _ = move_from_hand_to_battlefield(self, idx, obj_id)?;
        }
        let player = &mut self.players[idx];
        let bf = Arc::make_mut(&mut player.battlefield);
        if let Some(obj) = bf.iter_mut().find(|o| o.id == obj_id) {
            obj.summoning_sick = true;
            if from_exile_warped {
                obj.warped = false;
                obj.warp_exile_pending = false;
            }
        }
        // Round-27 G4 closure: CR 117.1c — the active player gets
        // priority after a spell is cast (or after an ability
        // resolves). The Rust `cast_creature` primitive fuses the
        // Python "push to stack -> resolve" sequence into a single
        // mutation (no-stack semantics — see the docstring above), so
        // the "after cast" priority reset happens here at the
        // primitive layer. A future stack-using cast slice will need
        // to re-think when the reset fires (after the cast push? or
        // after the resolution pop?), but the no-stack shape today
        // makes "after the primitive succeeds" the only well-defined
        // moment. Also reset `consecutive_passes` — a successful
        // cast is a non-pass mutation that breaks any pass streak.
        self.priority_player = self.active_player;
        self.consecutive_passes = 0;
        Ok(true)
    }

    /// **Phase-1 warp substrate (round-63) + Phase 2 (Timeline
    /// Culler).** Warp-cast a creature from `player_id`'s hand OR (if
    /// absent there and the printing is `warp_castable_from_graveyard`)
    /// the GRAVEYARD: identical to `cast_creature` with these deltas
    /// (verified against the live `cast_creature` + Python
    /// `actions.py:1393-1464` bodies):
    ///
    /// 0. **(Phase 2) Source-zone cascade:** hand first, then
    ///    graveyard gated on `warp_castable_from_graveyard` — mirrors
    ///    Python's single `_cast_spell` `if hand: ... elif gy-warp:`
    ///    cascade so the `Action::CastSpell` dispatch site stays
    ///    byte-identical (no new arm). Phase-1/1.5 cards are never in
    ///    the graveyard when warp-cast and carry
    ///    `warp_castable_from_graveyard=false`, so the fall-through
    ///    never triggers for them (unchanged behavior).
    /// 1. **Cost source:** pays `printing.warp_cost` (unwrapped —
    ///    the legal emitter only offered `use_warp=true` when this
    ///    is `Some`) instead of `printing.mana_cost`. Mirrors
    ///    Python's `effective_warp_cost(...)` element `[0]`
    ///    (`actions.py:1399-1400`) / the graveyard branch's
    ///    `card.printing.warp_cost` (`actions.py:1448`).
    /// 1b. **(Phase 2) Life rider:** after the mana spend commits,
    ///    debit `printing.warp_additional_life_cost` from the
    ///    caster's life UNCONDITIONALLY (CR 117.9b — part of the warp
    ///    alternative cost, no decision point). The legal emitter has
    ///    already gated `life > rider`, so this never drops below 1.
    ///    `rider == 0` (every Phase-1/1.5 card) is a no-op. Mirrors
    ///    Python `actions.py:1430-1436` (hand) / `:1458-1464`
    ///    (graveyard).
    /// 2. **`spell_warped_this_turn`:** set `true` after the mana
    ///    spend commits, mirroring Python `actions.py:1427` (hand) /
    ///    `:1457` (graveyard) — BOTH branches set it. The field is a
    ///    plain `bool` on `GameState` (`state.rs`; no Arc dance).
    /// 3. **`warp_exile_pending`:** stamp `true` on the just-cast
    ///    permanent (alongside the `summoning_sick = true` stamp) so
    ///    the `PHASE_END_STEP`-entry sweep
    ///    (`state_ops_steps.rs::warp_exile_sweep_on_end_step`)
    ///    exiles it at the next end step. Set IDENTICALLY for the
    ///    hand AND graveyard arm — Python schedules the SAME
    ///    `WarpExileSelf` for both (`actions.py:1550-1559` runs for
    ///    any `use_warp`). Rust's no-stack model: a deterministic
    ///    phase-entry sweep, NOT Python's stack-pushed delayed
    ///    trigger — documented in `SEARCH_LIMITATIONS.md`.
    /// 4. **Type gate / priority tail:** unchanged from
    ///    `cast_creature` (the `Creature`-type gate passes on
    ///    `Artifact Creature` / a bare `Creature`; the priority/
    ///    passes reset is verbatim).
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
        // CAST event before ENTERS, same ordering as `cast_creature`.
        crate::state_ops_resolve::dispatch_event(
            self,
            crate::cards::Event::Cast,
            obj_id,
        )?;
        // Delta 1b: move from the resolved source zone. Hand →
        // `move_from_hand_to_battlefield` (Phase 1, unchanged);
        // graveyard → `move_from_graveyard_to_battlefield` (Phase 2,
        // mirrors Python actions.py:1450 `p.graveyard.remove(card)` +
        // put_into_battlefield). Both fire the SAME CAST→ENTERS drain
        // path so any ETB fires byte-equal (inert for Timeline
        // Culler — triggered_abilities=() — but forward-correct).
        if from_graveyard {
            let _ =
                move_from_graveyard_to_battlefield(self, idx, obj_id)?;
        } else {
            let _ = move_from_hand_to_battlefield(self, idx, obj_id)?;
        }
        let player = &mut self.players[idx];
        let bf = Arc::make_mut(&mut player.battlefield);
        if let Some(obj) = bf.iter_mut().find(|o| o.id == obj_id) {
            obj.summoning_sick = true;
            // Delta 3: stamp the end-step warp-exile schedule. This
            // is set IDENTICALLY for the hand AND graveyard arm —
            // Python schedules the SAME `WarpExileSelf` delayed
            // trigger for both branches (actions.py:1550-1559 runs
            // for any `use_warp`), so a graveyard-warp-cast Timeline
            // Culler is exiled by the SAME deterministic
            // PHASE_END_STEP sweep and then re-castable from exile at
            // NORMAL {B}{B} (the Phase-1 sweep + exile-recast handle
            // the rest unchanged — the exile object is in exile, not
            // the graveyard, so it never re-enters the graveyard-warp
            // loop).
            obj.warp_exile_pending = true;
        }
        // Delta 4: priority/passes reset, verbatim from
        // `cast_creature`.
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
        // Delta 5: bind the deterministic-first legal target. Phase-1
        // scope is the `target_slot_kinds()==()` single-creature/
        // permanent slot; the same `bf_iter_etb_sorted` first-creature
        // scan the per-card bespoke Effect resolve arms use (Python's
        // centralized `state.battlefield` walk + the deterministic-
        // first convention). Bound at cast time so the chosen target
        // is fixed when the spell goes on the stack (matching Python's
        // separate `_select_spell_targets` decision producing one
        // bound target on the StackItem). The closed Tier-A spell
        // arms self-scan and ignore this; it is the forward substrate
        // for payload-target-reading arms (pin #4 / #6).
        let bound_target: Option<u32> =
            crate::bf_iter::bf_iter_etb_sorted(self)
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
        // Delta 4: push the spell StackItem (card stays in hand —
        // Rust's pre-existing spell-stack model). The existing
        // `resolve_top_of_stack` drains it: applies `printing.effects`
        // with the target swapped in, then `move_source_post_resolve`
        // sends the spell hand → graveyard (FREE — CR 608.2m).
        self.stack.push(crate::state::StackItem::new_spell_with_target(
            obj_id,
            player_id,
            bound_target,
        ));
        // Delta 7: priority/passes reset, verbatim from
        // `cast_creature` / `cast_creature_warp`.
        self.priority_player = self.active_player;
        self.consecutive_passes = 0;
        Ok(true)
    }
}
