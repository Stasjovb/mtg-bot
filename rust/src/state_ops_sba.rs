//! State-based action (SBA) primitives on `GameState`.
//!
//! Filled in by a TDD-slice branch (see `tests_rust/README.md`).
//! Stub block exists so other slices can grow `GameState` in
//! parallel without conflicting on a single `#[pymethods]` block.
//!
//! ## Slice scope
//!
//! **Lethal-damage SBA (CR 704.5g) AND 0-toughness SBA (CR 704.5f):**
//!
//! - 704.5g — a creature whose marked damage is >= its toughness is
//!   destroyed (moved from battlefield to its controller's graveyard).
//! - 704.5f — a creature with toughness 0 (or less) is put into its
//!   owner's graveyard. Effective toughness for this check is
//!   ``printing.toughness + obj.counters`` (round-3's net-i32 +1/+1
//!   vs -1/-1 model: positive counters add, negative subtract).
//!
//! Per CR ordering, 704.5f is checked BEFORE 704.5g; the practical
//! effect is identical (the union of victims is the same set), but
//! the order matters for niche corner cases — a creature at 0
//! effective toughness due to counters dies via 704.5f rather than
//! 704.5g, which becomes observable to triggered abilities once
//! they care about the cause of destruction.
//!
//! Exposes:
//! - `apply_sbas() -> usize` — single pass over both players'
//!   battlefields; collects every creature dying to either rule,
//!   then destroys each by moving it into its controller's graveyard.
//!   Returns the count of destructions.
//! - `apply_sbas_until_quiescent() -> usize` — CR 704.3 fixed-point
//!   loop. Repeatedly calls `apply_sbas` until a pass returns 0;
//!   returns the number of passes that fired. With only destruction
//!   SBAs in scope today, every realistic scenario completes in 0 or
//!   1 pass; the primitive exists so cascading-effect slices (sagas,
//!   death triggers) plug into the same loop without reshaping
//!   callers. A `MAX_PASSES = 100` safety raises `PyValueError` if
//!   exceeded.
//! - `is_lethal(obj_id) -> Option<bool>` — predicate form for
//!   704.5g. `Some(true)` when damage >= toughness, `Some(false)`
//!   when it is below, `None` for non-creatures (toughness is None)
//!   or unknown ids. (704.5f's effective-toughness predicate is
//!   inlined into `apply_sbas`; a public `is_zero_toughness` helper
//!   would be a one-liner addition if a caller needs it.)
//!
//! Composes with:
//! - `state_ops_damage` — supplies the damage marker for 704.5g.
//! - `state_ops_counters` — supplies `obj.counters` (the net +1/+1
//!   contribution) for 704.5f.
//! - `CardPrinting.toughness: Option<i16>` from the bridge-ext slice
//!   (round 3) — the base toughness; gates whether either rule
//!   applies (non-creatures stay).
//! - `state_ops_zones::move_object` — the underlying graveyard move
//!   pattern; replicated inline here rather than called via the
//!   pyclass method to keep the destructive collect-then-mutate loop
//!   self-contained and avoid a `&mut self` re-entrancy round-trip.
//!
//! ## Indestructible (CR 702.12)
//!
//! Creatures whose printing carries the `"indestructible"` keyword
//! are exempt from BOTH destruction paths above:
//!
//! - 704.5g (lethal damage): per CR 702.12a, indestructible permanents
//!   aren't destroyed by damage. Damage still marks (the damage field
//!   updates and clears at end of turn via cleanup), it just doesn't
//!   trigger destruction.
//! - 704.5f (0-or-negative toughness): per CR 702.12b, the SBA wording
//!   "is destroyed" carves out indestructible creatures here too.
//!
//! Implementation: `collect_sba_victims` looks up
//! `printing.keywords.iter().any(|k| k == "indestructible")` and skips
//! the entire creature when true (before either rule fires). Counter
//! / damage tracking is unaffected — only the destruction step is
//! gated.
//!
//! Indestructible only protects from "destroy". Exile (round-11's
//! ExileTarget effect) still removes indestructible creatures; that
//! path doesn't go through this slice.
//!
//! ## Out of scope (deferred to future slices)
//!
//! - **Integration with combat and spell-resolution call sites.**
//!   The loop primitive `apply_sbas_until_quiescent` exists, but
//!   wiring it into the priority-pass / spell-resolution drivers is
//!   a separate slice. Today callers explicitly invoke it.
//! - **Marked damage clearing.** Damage clears at end of turn (CR
//!   514.2), NOT on every SBA pass. apply_sbas does NOT zero damage
//!   on surviving creatures; `clear_all_damage` from the damage
//!   slice covers the cleanup-step path.
//! - **Regeneration / planeswalker loyalty / legend rule / +1/+1 vs
//!   -1/-1 cancellation / saga age / aura on illegal target / etc.**
//!   Other CR 704.5 SBAs are subsequent slices.
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
use crate::state_ops_zones::mark_left_battlefield_if_nonland;
use pyo3::prelude::*;
use std::sync::Arc;

// Zone constants — duplicated from state_ops_zones.rs (per the
// per-slice isolation rule; a follow-up consolidation slice can
// share these via a common module once the parallel-slice constraint
// relaxes).
const ZONE_GRAVEYARD: u8 = 3;
const ZONE_BATTLEFIELD: u8 = 2;

/// **BLOCKED-RUST-EFFECT slice (round 60) — Perigee Beckoner granted
/// dies-rider honoring (module-private, re-derived here per the
/// per-slice file-isolation rule rather than cross-calling the
/// resolve module).**
///
/// Called from `apply_sbas` AFTER a freshly-destroyed creature has
/// been moved to its owner's graveyard and its DIES/LEAVES dispatches
/// have fired. If the dying object (now in the graveyard) carried a
/// `UeotModifier::GrantedDiesReturnTapped` marker, move it back to
/// its OWNER's battlefield, TAPPED, dropping ONLY the
/// `GrantedDiesReturnTapped` marker (so a second death this turn does
/// NOT re-fire the rider) while KEEPING any `PowerToughnessBonus`
/// (Python's source-of-truth behavior — see the in-body round-53
/// effective-state note).
///
/// Mirrors Python's `PerigeeBeckonerDiesReturnTappedEffect.resolve`
/// (`effects/bespoke.py:2107`): the dying creature sits in its
/// owner's graveyard; remove it, drop the layer-6 grant (Rust
/// analogue: remove the marker — NOT a full UEOT clear, because
/// Python re-uses the same object and `put_into_battlefield` leaves
/// `temp_power_bonus` intact), put it back on the OWNER's
/// battlefield (oracle: "under its owner's control", NOT the spell
/// controller's), set `tapped = true`. Tokens cease to exist on
/// death (CR 111.7) — the round-55 token-cease path already removed
/// them, and this helper's graveyard-membership lookup makes the
/// token case a natural no-op (the id is no longer in any graveyard).
///
/// `owner_id` is the controller the SBA loop pushed the dead object
/// to its graveyard under (first-slice owner==controller
/// convention, matching the bare SBA destroy path's CR 400.6
/// note). Returns `true` iff a return-tapped actually happened.
fn perigee_return_tapped_if_marked(
    state: &mut GameState,
    owner_id: u8,
    obj_id: u32,
) -> bool {
    let oidx = owner_id as usize;
    let pos = match state.players[oidx]
        .graveyard
        .iter()
        .position(|o| o.id == obj_id)
    {
        Some(p) => p,
        None => return false, // moved elsewhere / token-ceased → no-op
    };
    let carries_marker = state.players[oidx].graveyard[pos]
        .ueot_modifiers
        .iter()
        .any(|m| matches!(
            m,
            crate::state::UeotModifier::GrantedDiesReturnTapped
        ));
    if !carries_marker {
        return false;
    }
    let gy: &mut Vec<GameObject> =
        Arc::make_mut(&mut state.players[oidx].graveyard);
    let mut obj = gy.remove(pos);
    // **Round-53 effective-state lesson applied — Python is the
    // source of truth.** Python's `PerigeeBeckonerDiesReturnTappedEffect`
    // RE-USES the same `GameObject` (`put_into_battlefield(state,
    // source, ...)`), and `put_into_battlefield` does NOT reset the
    // per-object `temp_power_bonus` — only the bespoke effect's
    // layer-6 grant-clear runs. So Python's returned creature KEEPS
    // the +P/+T pump (verified: effective power stays 4 after the
    // return; loses the rider so a 2nd death does NOT re-return).
    // To stay byte-equal with that source-of-truth behavior, Rust
    // drops ONLY the `GrantedDiesReturnTapped` marker (mirrors the
    // layer-6 grant-clear → no re-fire on a 2nd death) and KEEPS the
    // `PowerToughnessBonus` (mirrors `temp_power_bonus` surviving the
    // same-object return). A naive "clear all UEOT (clean CR 400.7
    // new-object)" would make Rust 2/2 vs Python 4/2 — a real §2
    // divergence the round-53 directive says to resolve by matching
    // Python, NOT by copying a textbook rule the source engine does
    // not implement here.
    obj.ueot_modifiers
        .retain(|m| !matches!(
            m,
            crate::state::UeotModifier::GrantedDiesReturnTapped
        ));
    obj.zone = ZONE_BATTLEFIELD;
    obj.controller = owner_id; // "under its owner's control"
    obj.tapped = true; // "tapped"
    obj.damage = 0;
    obj.attached_to = None;
    obj.exiled_with_source = None;
    obj.etb_timestamp = crate::state::reserve_etb_timestamp(state);
    Arc::make_mut(&mut state.players[oidx].battlefield).push(obj);
    true
}

impl GameState {
    /// Read-only enumeration of creatures that should be destroyed by
    /// SBAs this pass. Walks both battlefields and applies, in order:
    ///
    /// 1. **CR 704.5f (0-toughness):** effective toughness =
    ///    `printing.toughness + obj.counters`. If <= 0, victim.
    /// 2. **CR 704.5g (lethal damage):** `obj.damage >= effective_toughness`.
    ///    Effective toughness folds in the +1/+1 vs -1/-1 counter
    ///    contribution: a 2/2 with two +1/+1 counters takes 3 damage
    ///    and survives (effective 4 > 3); a 4/4 with two -1/-1 counters
    ///    takes 3 damage and dies (effective 2 <= 3). When `obj.counters
    ///    == 0` effective and printed toughness coincide, so the
    ///    no-counter cases reduce to the printed-toughness predicate.
    ///
    /// Returns `(controller_id, obj_id)` pairs. Each obj_id appears at
    /// most once even if both rules would catch it, because the inner
    /// loop short-circuits on the first matching rule.
    fn collect_sba_victims(&self) -> Vec<(u8, u32)> {
        // CE5 closure: walk battlefield in ETB-timestamp order
        // (matching Python's centralized `state.battlefield` walk in
        // `turn.py:1242`) via the shared `bf_iter_etb_sorted` helper.
        // Pre-CE5 this looped p0-then-p1; that diverged from Python
        // whenever ETB timestamps interleaved across players. The
        // helper's stable-sort preserves the pre-CE5 walk for
        // synthetic-state fixtures (all timestamps == 0), so pinned
        // baselines stay bit-equal.
        let mut victims = Vec::new();
        for obj in crate::bf_iter::bf_iter_etb_sorted(self) {
            let Some(printing) = self.registry.lookup(obj.printing_id) else {
                continue;
            };
            // CE20 Slice 5 (Walker loyalty Slice A): CR 704.5i — "If a
            // planeswalker has loyalty 0, it's put into its owner's
            // graveyard." Catch any walker with `loyalty_counters <= 0`
            // before the creature pass; the walker doesn't need to be
            // a creature to die this way. Walker filter: card_type
            // includes "Planeswalker". Same bf-ETB-timestamp-ordered
            // walk + same field-reset + same LEAVES queue plumbing as
            // the creature SBA paths below (DIES not pushed — walkers
            // don't fire Event::Dies per Python's
            // `move_off_battlefield` shape; only LEAVES_BATTLEFIELD
            // fires).
            let is_walker = printing
                .card_types
                .iter()
                .any(|t| t == "Planeswalker");
            if is_walker && obj.loyalty_counters <= 0 {
                victims.push((obj.controller, obj.id));
                continue;
            }
            let Some(toughness) = printing.toughness else {
                // Non-creature — neither 704.5f nor 704.5g apply.
                continue;
            };
            // CR 702.12 — indestructible permanents are exempt
            // from both destruction-by-damage (704.5g) and
            // destruction-by-zero-toughness (704.5f). Damage and
            // counters still track; only the destruction step is
            // skipped. Round-27 UEOT framework: indestructibility
            // can also be granted UEOT (Plaza of Heroes), so the
            // gate folds in any `UeotModifier::GrantKeyword`
            // entries too.
            if printing.keywords.iter().any(|k| k == "indestructible")
                || obj.ueot_has_keyword("indestructible")
            {
                continue;
            }
            // Round-27 UEOT framework: effective_toughness folds
            // in `ueot_toughness_bonus` (CR 613 layer 7c) on top
            // of the pre-r27 (printed + counters) calculation, so
            // an "until end of turn" +N/+M pump shrinks the
            // lethal-damage and zero-toughness victims correctly.
            // Round-28: a `UeotModifier::SetBasePT` (CR 613.4
            // layer 7b) overrides the printed base entirely;
            // counters + layer-7c bonuses still stack on top.
            let base_toughness = obj
                .ueot_base_pt_override()
                .map(|(_, t)| t)
                .unwrap_or(toughness as i32);
            let effective_toughness =
                base_toughness + obj.counters + obj.ueot_toughness_bonus();
            // 704.5f first per CR ordering.
            if effective_toughness <= 0 {
                victims.push((obj.controller, obj.id));
                continue;
            }
            // 704.5g second — also keyed on effective toughness.
            if obj.damage as i32 >= effective_toughness {
                victims.push((obj.controller, obj.id));
            }
        }
        victims
    }
}

#[pymethods]
impl GameState {
    /// Apply state-based actions for the destruction SBAs:
    /// CR 704.5f (0 effective toughness) and CR 704.5g (lethal damage).
    /// Every matching creature is moved from the battlefield into its
    /// controller's graveyard. Returns the number of creatures destroyed
    /// in this pass.
    ///
    /// Single-pass, no quiescence loop — see module docstring for
    /// the deferred semantics. 704.5f checked before 704.5g per CR
    /// ordering; in practice the union of victims is the same set.
    ///
    /// **Player-loss transition (round-26 G10 + G11).** Before the
    /// creature pass, fold the per-player cause-signals
    /// (`attempted_draw_on_empty`, `life <= 0`) into the sticky
    /// `has_lost` flag. This is the SBA transition that makes deck-out
    /// loss permanent (CR 704.5b) and locks in the life <= 0 loss
    /// (CR 704.5a). The return value remains the count of creatures
    /// destroyed in this pass — the player-loss work doesn't bump
    /// it (existing tests assert creature-count semantics; player
    /// loss is a separate SBA category in CR ordering).
    fn apply_sbas(&mut self) -> PyResult<usize> {
        // 704.5a / 704.5b player-loss SBAs first — fold cause-signals
        // into the sticky `has_lost`. Idempotent: re-running after a
        // player is already flagged is a no-op (preserves invariant
        // I7 — apply_sbas after game-over is stable).
        for p in self.players.iter_mut() {
            if !p.has_lost && (p.attempted_draw_on_empty || p.life <= 0) {
                p.has_lost = true;
            }
        }
        // CE12 closure (I34): write-once sticky winner_id. The FIRST
        // time the SBA pass observes "exactly one player has has_lost
        // = True" AND `winner_id_sticky` is still None, write the
        // OTHER player's id into `winner_id_sticky`. Mirrors Python's
        // turn.py:1387-1393 — the SBA writer gates the assignment on
        // `state.winner_id is None`, so once written the field is
        // STICKY. The subsequent alive=1 -> alive=0 transition (the
        // "bilateral KO after a sole-survivor moment" shape) only
        // writes `is_draw = True`; it never CLEARS the already-
        // written `winner_id`. See I34 in docs/RUST_PARITY_GAPS.md.
        if self.winner_id_sticky.is_none() {
            let p0_lost = self.players[0].has_lost;
            let p1_lost = self.players[1].has_lost;
            match (p0_lost, p1_lost) {
                (false, true) => self.winner_id_sticky = Some(self.players[0].id),
                (true, false) => self.winner_id_sticky = Some(self.players[1].id),
                // (false, false): game ongoing — nothing to write.
                // (true, true):  bilateral simultaneous loss with no
                //                prior sole-survivor moment — Python's
                //                writer sees `len(alive) == 0` first
                //                and only sets is_draw, leaving
                //                winner_id at None. Match that here.
                _ => {}
            }
        }
        let victims = self.collect_sba_victims();
        let count = victims.len();
        // BLOCKED-RUST-EFFECT slice (round 60) — Perigee Beckoner.
        // Collect (owner, id) for every SBA-destroyed creature that
        // carried the `UeotModifier::GrantedDiesReturnTapped` rider so
        // it can be returned to its owner's battlefield TAPPED after
        // the DIES/LEAVES dispatches fire (CR 603 granted delayed
        // trigger — the dying creature is still an observer for its
        // own dies/leaves trigger first, then the rider returns it,
        // mirroring Python's by-reference move_off_battlefield ordering
        // followed by the granted-trigger resolution).
        let mut perigee_return_ids: Vec<(u8, u32)> = Vec::new();
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
            // Per-object state reset on zone-change (CR 400.7 / 614.12).
            // Python's `turn.move_off_battlefield` clears combat marks
            // (damage, tapped, attached_to) on the way to the
            // destination zone; Rust's SBA destroy path inlines its
            // own move and previously preserved the marks. CE9
            // secondary closure (paired with the bf-order iteration
            // fix in `state_ops_combat.rs`): match Python's clear-on-
            // move-off by zeroing `damage` and `tapped` here so the
            // graveyard signature compares clean post-multi-block.
            // counters stay (CR 400.7 carves out "counters on the
            // permanent" — but CR 121.2 says counters cease to exist
            // on zone change for most counter kinds; Python's
            // move_off_battlefield does NOT clear counters either, so
            // we follow Python's observable behavior). attached_to is
            // also cleared per Python's `obj.attached_to = None` at
            // move_off_battlefield:240.
            obj.damage = 0;
            obj.tapped = false;
            obj.attached_to = None;
            let printing_id = obj.printing_id;
            let dying_obj_id = obj.id;
            // BLOCKED-RUST-EFFECT slice (round 60) — Perigee Beckoner.
            // Read the granted dies-rider marker BEFORE the object
            // moves to the graveyard (the CR 400.7 reset above zeroes
            // damage/tapped/attached but deliberately leaves
            // `ueot_modifiers` intact — same as the bare pump arm;
            // Python clears the layer-6 grant inside the bespoke
            // dies-effect, not on move_off_battlefield). A non-token
            // carrier is queued for return-tapped; tokens cease to
            // exist (CR 111.7) so they're never returned (the round-55
            // token-cease path + the helper's graveyard-membership
            // check both make that a natural no-op).
            let carries_perigee_rider = obj
                .ueot_modifiers
                .iter()
                .any(|m| matches!(
                    m,
                    crate::state::UeotModifier::GrantedDiesReturnTapped
                ));
            if carries_perigee_rider {
                perigee_return_ids.push((controller, dying_obj_id));
            }
            // Push onto the controller's graveyard.
            let target = &mut self.players[controller as usize];
            Arc::make_mut(&mut target.graveyard).push(obj);
            // Round-29 Void LTB: SBA destruction (704.5f/g — lethal
            // damage / zero toughness) is a battlefield-exit. Victims
            // are Creature-typed by filter (collect_sba_victims walks
            // creatures only), but route through the helper anyway
            // so the gate-in-one-place invariant holds.
            mark_left_battlefield_if_nonland(self, printing_id);
            // Slice 5: dispatch Event::Dies via the deferred-dispatch
            // queue. The SBA loop is mid-iteration over `victims`, so
            // calling dispatch_event inline could re-enter via a
            // trigger that pushes a new SBA victim onto the
            // battlefield (cascade death triggers etc.). The deferred
            // queue mirrors Slice 2's ENTERS pattern — push the id
            // now, drain after the loop. The drain happens at the
            // end of `apply_sbas` below.
            //
            // CE20 Slice 5 (Walker loyalty Slice A): Event::Dies is
            // CR 700.4 "a creature dies". A non-creature walker dying
            // via CR 704.5i (loyalty <= 0) is NOT a death — only the
            // LEAVES event fires. Gate the DIES push on
            // creature-typing so walker SBA-removal doesn't fire
            // spurious DIES triggers.
            let victim_is_creature = self
                .registry
                .lookup(printing_id)
                .map(|p| p.card_types.iter().any(|t| t == "Creature"))
                .unwrap_or(false);
            if victim_is_creature {
                self.pending_dies_dispatches.push(dying_obj_id);
            }
            // ETB-trigger Slice 8: every death is also a bf-exit.
            // Mirror Python's `move_off_battlefield` (turn.py:280-289)
            // which fires DIES first then LEAVES_BATTLEFIELD. Push
            // order: DIES first, LEAVES second; the matching drain
            // order below preserves that stack-push order. LIFO
            // resolution: LEAVES resolves before DIES. Walkers fire
            // ONLY LEAVES (no DIES per the creature-gate above).
            self.pending_leaves_dispatches.push(dying_obj_id);
            // Round-55: token-cease sibling. An SBA-destroyed token
            // creature (lethal damage / zero toughness) ceases to
            // exist (CR 111.7) rather than entering the graveyard.
            // Queued here; removed by the LEAVES-drain tail (and the
            // belt-and-suspenders sweep at apply_sbas' tail) AFTER
            // the DIES + LEAVES dispatches fire — so the token is
            // still an observer for its own dies/leaves trigger,
            // matching Python's by-reference move_off_battlefield.
            crate::state_ops_zones::queue_token_cease(self, dying_obj_id);
        }
        // Drain pending DIES dispatches AFTER the SBA loop completes.
        // Order matches push-order — each dying creature's triggers
        // fire in destruction order (which is bf-ETB-timestamp order
        // per `collect_sba_victims`'s walk).
        crate::state_ops_resolve::drain_pending_dies_dispatches(self)?;
        // ETB-trigger Slice 8: drain LEAVES dispatches AFTER DIES.
        // Stack push order: DIES then LEAVES; LIFO resolution
        // resolves LEAVES first, matching Python's
        // `move_off_battlefield` sequence (turn.py:280-289 fires
        // DIES then LEAVES; Python's stack is also LIFO).
        crate::state_ops_resolve::drain_pending_leaves_dispatches(self)?;
        // Round-55: belt-and-suspenders token-cease sweep. The LEAVES
        // drain above already drained the cease queue at its own
        // tail; this catches any token id queued by an SBA-destroy
        // bf-exit whose printing is a token (SBA-destroyed tokens —
        // a token creature dying to lethal damage / zero toughness).
        // Idempotent: if the LEAVES drain already emptied the queue
        // this is a zero-cost no-op.
        crate::state_ops_zones::drain_pending_token_cease(self);
        // BLOCKED-RUST-EFFECT slice (round 60) — Perigee Beckoner.
        // AFTER the DIES + LEAVES dispatches (the dying creature was an
        // observer for its own dies/leaves trigger, and any OTHER
        // creature's dies trigger that referenced it has already
        // resolved) + the token-cease sweep, return each marked
        // carrier to its owner's battlefield TAPPED. Order: post-drain
        // so the rider acts on the fully-settled post-death state,
        // mirroring Python's granted-trigger resolving off the stack
        // after the death is processed. Tokens already token-ceased
        // are a natural no-op (id no longer in any graveyard).
        for (owner_id, dead_id) in
            std::mem::take(&mut perigee_return_ids)
        {
            perigee_return_tapped_if_marked(self, owner_id, dead_id);
        }
        Ok(count)
    }

    /// Loop driver for state-based actions — CR 704.3 quiescence.
    ///
    /// Repeatedly calls `apply_sbas` until a pass produces zero
    /// destructions, returning the number of passes that fired
    /// (i.e. the number of `apply_sbas` invocations whose return
    /// value was > 0). A clean state returns 0.
    ///
    /// CR 704.3: "Whenever a player would get priority [...] the
    /// game first performs all applicable state-based actions as a
    /// single event. [...] After SBAs are performed, [...] if any
    /// SBAs were performed as a result of the check, all applicable
    /// SBAs are checked again." This method is the iteration-to-
    /// fixed-point that the round-5 single-pass `apply_sbas`
    /// deferred.
    ///
    /// With only the destruction SBAs available today (no cascading
    /// effects like death triggers or +1/+1-on-death yet), the loop
    /// completes in either 0 or 1 pass for every realistic scenario.
    /// Pinning the API now means later slices that add cascading
    /// effects (sagas, death triggers, ETB chains) plug into the
    /// same loop primitive without re-shaping callers.
    ///
    /// **Safety limit.** A `MAX_PASSES` guard (100) prevents any
    /// future infinite-loop bug from hanging the engine; exceeding
    /// it raises `PyValueError`. Real MTG SBA chains terminate quickly
    /// (the game state monotonically loses creatures / counters), so
    /// a triple-digit ceiling is far above any legitimate scenario.
    fn apply_sbas_until_quiescent(&mut self) -> PyResult<usize> {
        const MAX_PASSES: usize = 100;
        let mut passes = 0usize;
        loop {
            let destroyed = self.apply_sbas()?;
            if destroyed == 0 {
                return Ok(passes);
            }
            passes += 1;
            if passes > MAX_PASSES {
                return Err(pyo3::exceptions::PyValueError::new_err(format!(
                    "apply_sbas_until_quiescent exceeded {} passes — \
                     suspected infinite SBA loop",
                    MAX_PASSES
                )));
            }
        }
    }

    /// Predicate form of the lethal-damage check.
    ///
    /// Returns `Some(true)` when the creature's marked damage is
    /// greater than or equal to its EFFECTIVE toughness (printed +
    /// `obj.counters`), `Some(false)` when it is below, and `None`
    /// when the object is not found OR when the printing has no
    /// toughness (i.e. it's not a creature — lands, instants,
    /// sorceries, etc.).
    ///
    /// This stays in lockstep with `apply_sbas`'s 704.5g predicate so
    /// `is_lethal(id) == true` iff the creature would be destroyed by
    /// the next pass via the lethal-damage rule (modulo
    /// indestructibility, which the predicate intentionally ignores —
    /// 704.5g asks "is this lethal damage", indestructibility asks
    /// "does the destruction take effect"). For no-counter creatures
    /// effective and printed toughness coincide and the predicate
    /// reduces to the original `damage >= printing.toughness` form.
    fn is_lethal(&self, obj_id: u32) -> Option<bool> {
        for player in &self.players {
            for obj in player.battlefield.iter() {
                if obj.id == obj_id {
                    let printing = self.registry.lookup(obj.printing_id)?;
                    let toughness = printing.toughness?;
                    // Round-27 UEOT framework: keep this predicate in
                    // lockstep with `collect_sba_victims`'s effective-
                    // toughness recipe — fold counters AND
                    // `ueot_toughness_bonus` so a UEOT-pumped creature
                    // surfaces the right is_lethal answer at the
                    // mid-turn parity boundary. Round-28: SetBasePT
                    // overrides the printed base (last-applied wins).
                    let base_toughness = obj
                        .ueot_base_pt_override()
                        .map(|(_, t)| t)
                        .unwrap_or(toughness as i32);
                    let effective_toughness =
                        base_toughness + obj.counters + obj.ueot_toughness_bonus();
                    return Some(obj.damage as i32 >= effective_toughness);
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
