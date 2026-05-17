//! Phase / step advancement primitives on `GameState`.
//!
//! Mirrors `src/mtg_bot/turn.py:STEP_ORDER` and the simulation
//! driver that walks through it. The Python side carries a `Step`
//! enum and a global `STEP_ORDER` tuple; the Rust side keeps `phase`
//! as a `u8` field on `GameState` (already present from the
//! foundation commit) and constants live here at module scope.
//!
//! ## Phase encoding (option a — 12 raw u8 constants)
//!
//! Like the zones-slice's zone constants: a `Phase` enum on
//! `state.rs` would have forced an edit on a file two sibling TDD
//! slices were also growing in parallel, so the encoding stays
//! inline as `pub const u8` constants. Duplicated test-side in
//! `tests_rust/test_steps.py` for readability; a follow-up slice
//! can promote either side once parallel-slice constraints relax.
//!
//! Order matches Python's `STEP_ORDER`:
//!
//! UNTAP / UPKEEP / DRAW / PRECOMBAT_MAIN / BEGINNING_OF_COMBAT /
//! DECLARE_ATTACKERS / DECLARE_BLOCKERS / COMBAT_DAMAGE /
//! END_OF_COMBAT / POSTCOMBAT_MAIN / END / CLEANUP.
//!
//! ## Cross-slice composition (inlined workaround)
//!
//! `advance_phase` fires four cross-slice side-effects, each
//! mirrored as a free function in this file (see the helper bodies
//! below):
//!
//! 1. `empty_all_mana_pools_inline` — every advance_phase call,
//!    BEFORE the phase counter ticks. CR 106.4 mana-empty on phase
//!    exit (mirror of state_ops_mana.rs's `empty_all_mana_pools`).
//! 2. `untap_all_for_player_inline` + `clear_summoning_sick_for_player_inline`
//!    — on ENTRY to PHASE_UNTAP for the new active player. CR 302.1
//!    summoning-sick clear + the tap slice's untap sweep.
//! 3. `draw_card_inline` — on ENTRY to PHASE_DRAW, gated by
//!    `turn_number != 1`. CR 504.1 active-player draw, with the
//!    CR 103.7c first-turn skip.
//! 4. `cleanup_step_for_active_player_inline` — on ENTRY to
//!    PHASE_CLEANUP. CR 514.1 hand-size discard (active player,
//!    max=7) + CR 514.2 marked-damage clear (both battlefields).
//!
//! `multiple-pymethods` does let two sibling `#[pymethods] impl
//! GameState` blocks coexist, but methods defined in each block keep
//! their default Rust visibility (private to the module that owns
//! them). The tap-slice's `untap_all_for_player`, the zone-slice's
//! `draw_card`, and the cleanup-slice's `cleanup_step_for_active_player`
//! are all `fn`-private to their owning modules, so a direct call
//! from this module hits E0624. The brief's contingency for exactly
//! this case is to INLINE the equivalent body here. The inlined
//! versions mirror the sibling logic (skip the `Arc::make_mut` clone
//! when no work is needed / mirror the `pop` + zone-stamp + push
//! pattern from `draw_card` / mirror the two-step CR 514.1 -> 514.2
//! shape from `cleanup_step_for_active_player`). The mana-empty
//! helper (`empty_all_mana_pools_inline`) is a degenerate case —
//! `state_ops_mana.rs::empty_all_mana_pools` IS already pub via its
//! `#[pymethods]` block, but `advance_phase` is GIL-free
//! (`&mut self -> u8`) and the `#[pymethods]` form would require
//! threading a `Python<'py>` token through the call site; the inline
//! mirror keeps the dispatch shape uniform with the other helpers.
//! When the parallel-slice constraint relaxes a follow-up can either
//! promote the originals to `pub(crate)` or factor the helpers into
//! free functions — until then the duplication is the right call
//! (no edits to sibling files mid-parallel-development).
//!
//! ## CR 103.7c first-turn skip
//!
//! Per CR 103.7c, "in a two-player game, the player who plays first
//! skips the draw step of their first turn." Python's `simulate.py`
//! gates this on `state.turn_number != 1` alone (see comment in
//! `simulate.py:300-310`): on turn 1 the active player IS the
//! starting player because `turn_number` only ticks past 1 after the
//! first turn ends, so `turn_number == 1` is sufficient regardless
//! of which seat started.
//!
//! Rust mirror: `advance_phase` gates the auto-draw on
//! `turn_number != 1`. The synthetic-state harness seeds
//! `turn_number = 5` so the gate is open by default; tests that
//! exercise the first-turn skip explicitly drop `turn_number` to 1
//! before walking through the draw step.

use crate::state::{GameObject, GameState, ManaPool};
use crate::state_ops_zones::{
    mark_left_battlefield_if_nonland, ZONE_EXILE, ZONE_GRAVEYARD, ZONE_HAND,
};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::sync::Arc;

// `#[allow(dead_code)]` on the constants only the test side reads —
// they're part of the published phase vocabulary so we don't want to
// drop them, but Rust-side code only references the boundaries
// (UNTAP / CLEANUP) and the predicate-test fences (MAIN1 / MAIN2 /
// BEGIN_COMBAT / END_COMBAT). Mirror of `STEP_ORDER` in Python's
// `src/mtg_bot/turn.py`.
pub const PHASE_UNTAP: u8 = 0;
#[allow(dead_code)]
pub const PHASE_UPKEEP: u8 = 1;
#[allow(dead_code)]
pub const PHASE_DRAW: u8 = 2;
pub const PHASE_MAIN1: u8 = 3;
pub const PHASE_BEGIN_COMBAT: u8 = 4;
#[allow(dead_code)]
pub const PHASE_DECLARE_ATTACKERS: u8 = 5;
#[allow(dead_code)]
pub const PHASE_DECLARE_BLOCKERS: u8 = 6;
#[allow(dead_code)]
pub const PHASE_COMBAT_DAMAGE: u8 = 7;
pub const PHASE_END_COMBAT: u8 = 8;
pub const PHASE_MAIN2: u8 = 9;
#[allow(dead_code)]
pub const PHASE_END_STEP: u8 = 10;
pub const PHASE_CLEANUP: u8 = 11;

const PHASE_MAX: u8 = PHASE_CLEANUP;

/// Free-function mirror of `state_ops_tap.rs:untap_all_for_player`.
/// See the module docstring for why this duplication exists. Same
/// CoW shape — short-circuits if every permanent on the target
/// battlefield is already untapped AND no permanent carries a stun
/// counter, otherwise one `Arc::make_mut` covers the in-place sweep.
///
/// **Round-30 stun-counter substrate (CR 701.20).** "If a permanent
/// with a stun counter would become untapped, instead remove a stun
/// counter from it." For each permanent the active player controls:
///   - If `stun_counters > 0`, decrement by 1 and leave `tapped`
///     unchanged (stays tapped this turn).
///   - Otherwise clear `tapped = false` per the bare untap-step
///     rule (CR 502.1).
/// Mirrors Python's `src/mtg_bot/turn.py:88-96`.
///
/// **CoW short-circuit.** The make_mut now fires when ANY object
/// either is tapped or carries a stun counter — pre-r30 baselines
/// (no stun counters anywhere on the bf) keep the same warm path.
fn untap_all_for_player_inline(state: &mut GameState, player_id: u8) {
    let player = match state.players.iter_mut().find(|p| p.id == player_id) {
        Some(p) => p,
        None => return,
    };
    if player
        .battlefield
        .iter()
        .all(|o| !o.tapped && o.stun_counters == 0)
    {
        return;
    }
    let zone: &mut Vec<GameObject> = Arc::make_mut(&mut player.battlefield);
    for obj in zone.iter_mut() {
        if obj.stun_counters > 0 {
            // CR 701.20: doesn't untap; instead remove a stun counter.
            obj.stun_counters -= 1;
            continue;
        }
        obj.tapped = false;
    }
}

/// Clear `summoning_sick` on every permanent the given player
/// controls (CR 302.1 — summoning sickness wears off when the
/// creature has been continuously controlled by its controller
/// since the start of that player's most recent turn). Fires from
/// `advance_phase` whenever the new phase is UNTAP, on the new
/// active player. Same CoW shape as `untap_all_for_player_inline`:
/// short-circuit when nothing is sick so the synthetic-state's
/// "no sick permanents on battlefield" warm path doesn't pay an
/// `Arc::make_mut` clone, otherwise one make_mut covers the sweep.
fn clear_summoning_sick_for_player_inline(state: &mut GameState, player_id: u8) {
    let player = match state.players.iter_mut().find(|p| p.id == player_id) {
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

/// Free-function mirror of `state_ops_zones.rs:draw_card`. See the
/// module docstring for why this duplication exists. Same shape —
/// pop the top of library (= first element of the Vec, post-CE3),
/// stamp the drawn object's `zone` to `ZONE_HAND`, push onto hand.
///
/// **Empty-library side-effect (CR 704.5b — round-26 G10 closure).**
/// When the library is empty the pop is skipped AND the player's
/// `attempted_draw_on_empty` cause-signal flips to `true`. The next
/// `apply_sbas` pass transitions that into the sticky `has_lost`
/// flag; `losers()` ALSO reads the cause-signal directly so the
/// loss is observable BEFORE the SBA pass runs. Mirrors the
/// pymethod `draw_card` (state_ops_zones.rs) and the
/// `Effect::DrawCards` resolution arm (state_ops_resolve.rs) — all
/// three entrypoints share the same loss-flag side-effect. Prior to
/// this slice the inline path was silent on empty, which left a
/// player who decked out via the DRAW step (the auto-draw at start
/// of turn — the common case) un-flagged on Rust side. See
/// `docs/RUST_PARITY_GAPS.md` I19 for the full invariant.
///
/// CoW-safe: each zone Vec mutation routes through `Arc::make_mut`.
fn draw_card_inline(state: &mut GameState, player_id: u8) {
    let idx = player_id as usize;
    if idx >= state.players.len() {
        return;
    }
    let player = &mut state.players[idx];
    let lib = Arc::make_mut(&mut player.library);
    if lib.is_empty() {
        // CR 704.5b — empty-library draw flags the player for loss
        // on the next SBA pass. Mirrors the pymethod draw_card and
        // the Effect::DrawCards arm.
        player.attempted_draw_on_empty = true;
        return;
    }
    // Post-CE3: top of library = lib[0].
    let mut obj = lib.remove(0);
    obj.zone = ZONE_HAND;
    // Round-28 attach foundation: CR 400.7 clears attach state on
    // zone change. A library card can't legally be attached today,
    // but reset defensively to mirror the pymethod's `draw_card`.
    obj.attached_to = None;
    obj.exiled_with_source = None;
    Arc::make_mut(&mut player.hand).push(obj);
}

/// Free-function mirror of `state_ops_cleanup.rs:cleanup_step_for_active_player`,
/// scoped to the side-effects `advance_phase` needs on entry to
/// PHASE_CLEANUP (CR 514.1 hand-size discard at max=7 for the active
/// player + CR 514.2 marked-damage clear on both battlefields + CR
/// 514.3 UEOT-modifier expiration on both battlefields, round-27).
/// The `#[pymethods]` variant returns a `Bound<PyDict>` summary, which
/// would require threading a `Python<'py>` token into `advance_phase`
/// (currently a plain `&mut self -> u8`). The inline mirror drops the
/// summary dict and keeps the call site GIL-free, matching the
/// established workaround pattern documented in the module docstring
/// (same friction as `untap_all_for_player_inline` / `draw_card_inline`).
///
/// Order: hand-size discard FIRST, then damage clear, then UEOT clear
/// — preserves the CR 514.1-before-514.2-before-514.3 sequencing
/// baked into `cleanup_step_for_active_player`. See that primitive's
/// module docstring for why ordering matters.
///
/// CoW-safe: each zone mutation routes through `Arc::make_mut`. The
/// damage-clear pass short-circuits when no permanent on a given
/// battlefield has marked damage, mirroring the optimization in
/// `state_ops_damage.rs::clear_damage_for_player` and the
/// `cleanup_step_for_active_player` source.
fn cleanup_step_for_active_player_inline(state: &mut GameState) {
    // (1) CR 514.1 — hand-size discard for the active player.
    // Hard-codes max=7 (every active-player cleanup in canonical MTG
    // uses 7; matches the primitive's hard-coded constant).
    let active = state.active_player as usize;
    if active < state.players.len() {
        let player = &mut state.players[active];
        let current = player.hand.len();
        const MAX_HAND: usize = 7;
        if current > MAX_HAND {
            let to_discard = current - MAX_HAND;
            let hand = Arc::make_mut(&mut player.hand);
            let mut popped: Vec<GameObject> = Vec::with_capacity(to_discard);
            for _ in 0..to_discard {
                // pop() from the END of the Vec — deterministic
                // choice stepping-stone, mirrors the primitive.
                let mut obj = hand
                    .pop()
                    .expect("hand.len() > MAX_HAND guaranteed by the check above");
                obj.zone = ZONE_GRAVEYARD;
                popped.push(obj);
            }
            let graveyard = Arc::make_mut(&mut player.graveyard);
            for obj in popped {
                graveyard.push(obj);
            }
        }
    }
    // (2) CR 514.2 — clear all marked damage on both battlefields.
    for player in state.players.iter_mut() {
        if player.battlefield.iter().all(|o| o.damage == 0) {
            continue;
        }
        let zone: &mut Vec<GameObject> = Arc::make_mut(&mut player.battlefield);
        for obj in zone.iter_mut() {
            obj.damage = 0;
        }
    }
    // (3) CR 514.3 — drain every UEOT modifier on every battlefield
    // permanent (round-27 closure of parity gap G7). Mirrors the
    // primitive `cleanup_step_for_active_player`'s CR-514.3 pass; same
    // CoW shape — skip the `Arc::make_mut` clone when no permanent on
    // a battlefield has any UEOT modifier.
    for player in state.players.iter_mut() {
        if player
            .battlefield
            .iter()
            .all(|o| o.ueot_modifiers.is_empty())
        {
            continue;
        }
        let zone: &mut Vec<GameObject> = Arc::make_mut(&mut player.battlefield);
        for obj in zone.iter_mut() {
            obj.ueot_modifiers.clear();
        }
    }
    // (4) Round-29 EoE Void turn-scoped tracking reset. Mirrors
    // Python's `run_cleanup_step` in `turn.py:1094-1095`:
    //
    //     state.permanent_left_battlefield_this_turn = False
    //     state.spell_warped_this_turn = False
    //
    // Cleanup-step entry is the canonical "this turn" boundary in
    // Python; we clear both Void-tracking flags here so the next
    // turn starts fresh. The flags fire `Effect::ConditionalIfVoid`
    // intervening-if predicates (read via `is_void_active`); see
    // `docs/RUST_PARITY_GAPS.md` I29 for the lifecycle invariant.
    // Cheap unconditional reset — both fields are plain `bool` on
    // GameState (not behind an Arc), so no CoW dance is needed.
    state.permanent_left_battlefield_this_turn = false;
    state.spell_warped_this_turn = false;
}

/// CR 106.4 — "When a phase or step ends, each player's mana pool
/// empties." Fired from `advance_phase` on every transition, BEFORE
/// the phase index ticks forward (i.e. at the moment the old phase
/// ends). Mirrors `state_ops_mana.rs::empty_all_mana_pools` (which is
/// already `pub` in its `#[pymethods]` block — calling that primitive
/// directly would require routing through PyO3's method dispatch and
/// a `Python<'py>` token, so we keep `advance_phase` GIL-free with
/// this free-function shape that operates on the underlying field
/// directly).
///
/// `ManaPool` is `Copy + Default`, so the assignment is a cheap
/// by-value reset on each player. No `Arc::make_mut` needed —
/// `ManaPool` lives inline on `Player`, not behind a shared zone Arc.
fn empty_all_mana_pools_inline(state: &mut GameState) {
    for player in state.players.iter_mut() {
        player.mana_pool = ManaPool::default();
    }
}

/// **Phase-1 warp substrate (round-63).** At the beginning of the
/// END step, exile every battlefield permanent the active player
/// controls that was warp-cast (`warp_exile_pending`). Mirrors
/// Python's `WarpExileSelf` delayed trigger fired by
/// `run_delayed_end_step_triggers` (turn.py:773) — Rust's no-stack
/// cast model makes this a deterministic phase-entry sweep instead
/// of a stack-pushed delayed triggered ability (documented
/// simplification, `docs/SEARCH_LIMITATIONS.md`). The exiled
/// permanent gets `warped=true` so the legal emitter offers the
/// exile-recast at normal cost on a later turn; `warp_exile_pending`
/// is cleared. CR 400.7 — the exiled card is a brand-new object:
/// reset the same per-object state the `Effect::ExileTarget` arm
/// resets (tapped / damage / counters / attached_to /
/// exiled_with_source). `summoning_sick` is intentionally NOT reset
/// (CE13 — Python's `move_off_battlefield` omits the clear; sickness
/// is battlefield-only state). Round-29 Void LTB tracking: a
/// non-land permanent leaving the battlefield flips
/// `permanent_left_battlefield_this_turn` (mirrors Python
/// `move_off_battlefield` turn.py:163-164). No LEAVES/DIES dispatch
/// is wired here: exile is not a graveyard transit (no DIES per CR),
/// and no bridge-admitted card carries a LEAVES trigger (the warp
/// cards have `triggered_abilities=()`; `_SAFE_TRIGGERS` has no
/// `leaves_battlefield` event) — the documented Phase-1
/// simplification covers this (`SEARCH_LIMITATIONS.md`). CoW: skip
/// the `Arc::make_mut` clone when no permanent is warp-pending.
fn warp_exile_sweep_on_end_step(state: &mut GameState) {
    let active = state.active_player as usize;
    if state.players[active]
        .battlefield
        .iter()
        .all(|o| !o.warp_exile_pending)
    {
        return;
    }
    // Partition: collect the warp-pending permanents off the
    // battlefield, push them to exile with the CR-400.7 reset.
    let player = &mut state.players[active];
    let bf: &mut Vec<GameObject> = Arc::make_mut(&mut player.battlefield);
    let mut exiled: Vec<GameObject> = Vec::new();
    let mut i = 0;
    while i < bf.len() {
        if bf[i].warp_exile_pending {
            let mut obj = bf.remove(i);
            // CR 400.7 / parity with Python's `move_off_battlefield`
            // (turn.py:231-240): reset damage / tapped / attached_to.
            // Python does NOT zero +1/+1 `counters` here and does NOT
            // clear `summoning_sick` (CE13) — match the source of
            // truth exactly so the per-object fingerprint 8-tuple is
            // byte-equal across engines for the warp-exile path
            // (`counters` IS in the tuple; the Phase-1 cards never
            // carry +1/+1 counters in the bench, but matching
            // Python's actual behavior keeps the path forward-
            // correct, not just coincidentally bit-equal).
            obj.zone = ZONE_EXILE;
            obj.tapped = false;
            obj.damage = 0;
            obj.attached_to = None;
            obj.exiled_with_source = None;
            obj.warp_exile_pending = false;
            // Python's WarpExileSelf sets obj.warped = True only for
            // non-tokens (effects/generic/exile.py:170-171). Phase-1
            // warp cards are never tokens; gate on the printing for
            // forward-correctness.
            let is_token = state
                .registry
                .lookup(obj.printing_id)
                .map(|p| {
                    p.supertypes.iter().any(|s| s == "Token")
                })
                .unwrap_or(false);
            if !is_token {
                obj.warped = true;
            }
            exiled.push(obj);
        } else {
            i += 1;
        }
    }
    let exile: &mut Vec<GameObject> = Arc::make_mut(&mut player.exile);
    let mut leaving_printing_ids: Vec<u32> = Vec::with_capacity(exiled.len());
    for obj in exiled {
        leaving_printing_ids.push(obj.printing_id);
        exile.push(obj);
    }
    // Round-29 Void LTB tracking: each non-land bf-exit flips the
    // flag. Done AFTER the player-mutable borrow drops (the helper
    // re-borrows `state.registry`).
    for pid in leaving_printing_ids {
        mark_left_battlefield_if_nonland(state, pid);
    }
}

#[pymethods]
impl GameState {
    /// Expose `active_player` to Python. The field already exists on
    /// `GameState` (set by `make_synthetic_state` to 0) but had no
    /// `#[getter]` attached; this slice's tests need to read it to
    /// verify the cleanup-step turn rollover. `state.rs` is owned by
    /// other slices this commit, so the getter lands here instead.
    #[getter]
    fn active_player(&self) -> u8 {
        self.active_player
    }

    /// Read-only phase query. Matches the Python convention of
    /// returning the active phase as a value rather than a method
    /// dispatch on the enum.
    fn current_phase(&self) -> u8 {
        self.phase
    }

    /// Advance one step in the canonical phase order, returning the
    /// new phase. When the previous phase was CLEANUP (11), wrap
    /// back to UNTAP (0), bump `turn_number`, and swap
    /// `active_player`. When the new phase is UNTAP, automatically
    /// fire the untap-step sweep on the new active player by calling
    /// the tap-slice's `untap_all_for_player`. This auto-fire happens
    /// on every UNTAP entry, including the initial wrap that flips
    /// the active player — the new active player's permanents
    /// untap at the top of their turn.
    ///
    /// When the new phase is DRAW, fire `draw_card` on the active
    /// player per CR 504.1 (active player draws one card during
    /// their draw step), gated by the CR 103.7c first-turn skip
    /// (`turn_number != 1`). See the module docstring for why the
    /// first-turn check is `turn_number` alone — Python's
    /// `simulate.py` uses the same gate and the rationale (on turn
    /// 1 the active player IS the starting player) applies bit-for-
    /// bit here. The synthetic-state harness seeds
    /// `turn_number = 5`, so the gate is open by default; an
    /// explicit setter (none yet) or stepping back to 1 would let
    /// callers exercise the first-turn skip.
    ///
    /// **Phase-boundary side-effect composition.** Per CR 106.4
    /// ("when a phase or step ends, each player's mana pool empties")
    /// every `advance_phase` call empties both players' mana pools
    /// BEFORE the phase counter ticks forward — the mana-empty models
    /// the EXIT of the old phase. Per CR 514.1 + CR 514.2 the cleanup
    /// step's hand-size discard (active player, max=7) and marked-
    /// damage clear (both battlefields) fire on ENTRY to PHASE_CLEANUP
    /// — i.e. when the new phase becomes CLEANUP. The full lifecycle
    /// for the CLEANUP phase is therefore:
    ///
    /// 1. advance_phase X (incoming from END_STEP):
    ///    a. exit END_STEP -> empty mana pools (CR 106.4)
    ///    b. tick phase to CLEANUP
    ///    c. enter CLEANUP -> cleanup_step (CR 514.1 + 514.2)
    /// 2. advance_phase X+1 (outgoing from CLEANUP):
    ///    a. exit CLEANUP -> empty mana pools (CR 106.4)
    ///    b. wrap phase to UNTAP, turn_number += 1, swap active_player
    ///    c. enter UNTAP -> untap sweep + summoning-sick clear
    ///
    /// Step (1c)'s cleanup_step runs on the OLD active player (the
    /// one whose turn is ending) because the active-player swap
    /// doesn't happen until the CLEANUP -> UNTAP wrap in step (2b).
    fn advance_phase(&mut self) -> u8 {
        // CR 106.4 — exit-of-old-phase side effect. Empty both
        // players' mana pools BEFORE the phase counter ticks. Fires
        // on every advance_phase call; mirrors the source-of-truth
        // primitive `empty_all_mana_pools` (state_ops_mana.rs).
        // The inline mirror exists for the same GIL-token reason as
        // the other inline helpers — see this file's module docstring.
        empty_all_mana_pools_inline(self);
        // Round-27 G3 closure: advancing the phase is a non-pass
        // mutation — it breaks any consecutive-pass streak that was
        // building up before the advance. Reset to 0 so a subsequent
        // `pass_priority` re-starts counting from 1.
        self.consecutive_passes = 0;
        if self.phase == PHASE_CLEANUP {
            self.phase = PHASE_UNTAP;
            self.turn_number += 1;
            // Two-player swap. If the engine ever grows past two
            // players, replace with `(active_player + 1) % n`.
            self.active_player = 1 - self.active_player;
            // Round-27 G15 closure: CR 117.1a — the active player
            // gets priority at the start of each step (and at the
            // start of each turn). On the CLEANUP -> UNTAP wrap the
            // active player has just flipped, so reset priority to
            // the NEW active player here. Mirrors Python's
            // `simulate.py:212-213` which sets
            // `state.priority_player_idx = 0` after the active-player
            // swap at the start of a new turn — the Rust version is
            // the same rule generalized for either seat.
            self.priority_player = self.active_player;
        } else {
            self.phase += 1;
        }
        if self.phase == PHASE_UNTAP {
            // Inlined sibling-slice logic — see the workaround note
            // in the module docstring. Mirrors
            // `state_ops_tap.rs:untap_all_for_player`: skip the
            // `Arc::make_mut` clone when nothing is tapped, then do
            // a single CoW clone covering every in-place flip.
            untap_all_for_player_inline(self, self.active_player);
            // CR 302.1 — at the start of the active player's untap
            // step, every permanent that player has controlled
            // continuously since the start of their previous turn
            // loses summoning sickness. The synthetic-state seed
            // doesn't track "continuous control" yet (every newly
            // ETB'd permanent gets sickness via the cast slice and
            // resolve slice's `summoning_sick = true` stamps); the
            // operational rule reduces to "clear sickness on the
            // new active player's permanents at their UNTAP entry".
            // Same CoW shape as the untap sweep — see the helper.
            clear_summoning_sick_for_player_inline(self, self.active_player);
        }
        if self.phase == PHASE_DRAW && self.turn_number != 1 {
            // CR 504.1 — active player draws one card during their
            // draw step. CR 103.7c first-turn skip: the player who
            // plays first skips their draw step on turn 1. Python's
            // `simulate.py` gates on `turn_number != 1` alone
            // (rationale: on turn 1 the active player IS the
            // starting player because turn_number only ticks past 1
            // after the first turn ends — see the comment block in
            // `simulate.py:300-310`). Mirror the same gate here so
            // parity holds bit-for-bit. Inlined draw — see the
            // module docstring for the cross-slice friction note.
            draw_card_inline(self, self.active_player);
        }
        if self.phase == PHASE_END_STEP {
            // **Phase-1 warp substrate (round-63).** At the beginning
            // of the END step, exile every battlefield permanent the
            // active player controls that was warp-cast
            // (`warp_exile_pending`). Mirrors Python's
            // `WarpExileSelf` delayed trigger fired by
            // `run_delayed_end_step_triggers` (turn.py:773) with
            // `offset = 0` for sorcery-speed warps cast on the
            // caster's own turn — both Phase-1 cards are sorcery-
            // speed Artifact Creatures, so the warp cast and the
            // exile happen on the same turn's end step. Active player
            // here is the player whose turn it is (the turn wrap is
            // on the CLEANUP -> UNTAP advance, not END_STEP entry).
            // Rust's no-stack cast model makes this a deterministic
            // phase-entry sweep instead of a stack-pushed delayed
            // triggered ability — documented simplification, see
            // `docs/SEARCH_LIMITATIONS.md`. This END_STEP-entry hook
            // is new (only UNTAP / DRAW / CLEANUP had entry hooks
            // pre-Phase-1); it mirrors the PHASE_CLEANUP-entry hook
            // shape directly below.
            warp_exile_sweep_on_end_step(self);
        }
        if self.phase == PHASE_CLEANUP {
            // CR 514.1 + CR 514.2 — on entry to the cleanup step,
            // the active player discards down to max hand size (7)
            // and all marked damage on every battlefield is removed.
            // Active player is the OLD active player here (the turn
            // wrap happens on the CLEANUP -> UNTAP advance, not on
            // entry to CLEANUP), so the discard targets the player
            // whose turn is ending. Inlined per the cross-slice
            // friction note in the module docstring.
            cleanup_step_for_active_player_inline(self);
        }
        self.phase
    }

    /// True when the current phase is one of the two main phases
    /// (PRECOMBAT_MAIN / POSTCOMBAT_MAIN). Mirrors Python's
    /// `MAIN_STEPS` set in `turn.py`.
    fn is_main_phase(&self) -> bool {
        self.phase == PHASE_MAIN1 || self.phase == PHASE_MAIN2
    }

    /// True when the current phase is one of the five combat steps
    /// (BEGINNING_OF_COMBAT through END_OF_COMBAT inclusive).
    /// Mirrors Python's `COMBAT_STEPS` set in `turn.py`.
    fn is_combat_phase(&self) -> bool {
        (PHASE_BEGIN_COMBAT..=PHASE_END_COMBAT).contains(&self.phase)
    }

    /// Direct phase setter for tests / fast-forward scenarios.
    /// Validates the phase is in `[0, PHASE_CLEANUP]`. Production
    /// code should prefer `advance_phase` so the cross-slice
    /// composition fires; this setter intentionally does NOT trigger
    /// the untap step (that's `advance_phase`'s job — `set_phase` is
    /// raw state assignment).
    fn set_phase(&mut self, phase: u8) -> PyResult<()> {
        if phase > PHASE_MAX {
            return Err(PyValueError::new_err(format!(
                "phase out of range: {phase} (must be in [0, {PHASE_MAX}])"
            )));
        }
        self.phase = phase;
        Ok(())
    }

    /// Python-Step-name string for the current phase. Round 22 Phase
    /// 2b bridge expansion — `scripts/parity_smoke.py:hash_state`
    /// reads `state.step.name` (or falls back to `state.step` if
    /// that's already a string), folding the active step into its
    /// parity fingerprint. By returning the uppercase
    /// `mtg_bot.turn.Step.<NAME>` string directly, the Rust side
    /// satisfies the `getattr(..., "name", state.step)` fallback
    /// — the harness sees a plain `str` and uses it verbatim.
    ///
    /// Mapping (kept in lockstep with `src/mtg_bot/turn.py:Step` —
    /// the enum `.name` attribute, not the lowercase `.value`):
    ///
    /// - 0 `PHASE_UNTAP`              -> `"UNTAP"`
    /// - 1 `PHASE_UPKEEP`             -> `"UPKEEP"`
    /// - 2 `PHASE_DRAW`               -> `"DRAW"`
    /// - 3 `PHASE_MAIN1`              -> `"PRECOMBAT_MAIN"`
    /// - 4 `PHASE_BEGIN_COMBAT`       -> `"BEGINNING_OF_COMBAT"`
    /// - 5 `PHASE_DECLARE_ATTACKERS`  -> `"DECLARE_ATTACKERS"`
    /// - 6 `PHASE_DECLARE_BLOCKERS`   -> `"DECLARE_BLOCKERS"`
    /// - 7 `PHASE_COMBAT_DAMAGE`      -> `"COMBAT_DAMAGE"`
    /// - 8 `PHASE_END_COMBAT`         -> `"END_OF_COMBAT"`
    /// - 9 `PHASE_MAIN2`              -> `"POSTCOMBAT_MAIN"`
    /// - 10 `PHASE_END_STEP`          -> `"END"`
    /// - 11 `PHASE_CLEANUP`           -> `"CLEANUP"`
    ///
    /// Two deviations from the round-22 brief's best-guess mapping
    /// — both pinned to Python's actual `Step` enum names:
    ///
    /// 1. Python has **no** `FIRST_STRIKE_DAMAGE` step. `STEP_ORDER`
    ///    in `turn.py` goes `DECLARE_BLOCKERS -> COMBAT_DAMAGE`
    ///    directly (first-strike resolves inside the single combat-
    ///    damage step in this engine's simplification). Rust's
    ///    `PHASE_COMBAT_DAMAGE=7` therefore maps to `"COMBAT_DAMAGE"`,
    ///    not `"FIRST_STRIKE_DAMAGE"`.
    /// 2. Python phase 10 is `Step.END` (`.name == "END"`), not
    ///    `"POSTCOMBAT_MAIN"`. The brief's mapping skipped the
    ///    end-step entirely; we restore it so the Rust↔Python
    ///    parity hash sees the same name at index 10.
    ///
    /// Exposed as a `#[getter]` so Python-side reads use property
    /// access (`state.step`), matching how `hash_state` consumes it.
    /// Calling it as a function (`state.step()`) raises `TypeError`
    /// — pinned by the test side so the property shape doesn't
    /// silently regress to a method.
    #[getter]
    fn step(&self) -> &'static str {
        match self.phase {
            PHASE_UNTAP => "UNTAP",
            PHASE_UPKEEP => "UPKEEP",
            PHASE_DRAW => "DRAW",
            PHASE_MAIN1 => "PRECOMBAT_MAIN",
            PHASE_BEGIN_COMBAT => "BEGINNING_OF_COMBAT",
            PHASE_DECLARE_ATTACKERS => "DECLARE_ATTACKERS",
            PHASE_DECLARE_BLOCKERS => "DECLARE_BLOCKERS",
            PHASE_COMBAT_DAMAGE => "COMBAT_DAMAGE",
            PHASE_END_COMBAT => "END_OF_COMBAT",
            PHASE_MAIN2 => "POSTCOMBAT_MAIN",
            PHASE_END_STEP => "END",
            PHASE_CLEANUP => "CLEANUP",
            // `set_phase` clamps to [0, PHASE_CLEANUP] and
            // `advance_phase` cycles through the same range, so this
            // arm is unreachable in well-formed use. Return a
            // sentinel rather than panic so a future raw setter on
            // the `phase` field can't take down a parity fingerprint
            // mid-roll.
            _ => "UNKNOWN",
        }
    }
}
