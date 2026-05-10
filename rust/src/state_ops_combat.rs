//! Combat primitives on `GameState`.
//!
//! Ports the irreducible end-to-end "attacker hits a blocker, both
//! might die" combat scenario from `src/mtg_bot/combat.py`. The
//! Python side spreads combat across hundreds of lines (predicate-
//! style event dispatch, first-strike / double-strike timing, trample,
//! deathtouch, lifelink, infect, prevention, exalted / vigilance,
//! "whenever attacks/blocks/deals combat damage" triggers). The first
//! Rust slice carves off the four primitives the higher layers will
//! call into: `declare_attacker`, `declare_blocker`,
//! `deal_combat_damage`, `clear_combat`, plus read accessors
//! `get_attackers` / `get_blockers`.
//!
//! The state shape (`attackers: Vec<u32>`, `blockers:
//! Vec<(u32, u32)>`) was added in this round's foundation commit on
//! `state.rs`; this slice fills in the operations.
//!
//! ## Scope simplifications (mirrored on `tests_rust/test_combat.py`)
//!
//! - **No first-strike / double-strike / deathtouch / trample /
//!   lifelink / vigilance / infect / protection / unblockable.**
//!   Damage in this slice is one symmetric round: each attacker
//!   assigns `power` damage to its first blocker (or to the defending
//!   player if unblocked), and each blocker assigns `power` damage
//!   back to the attacker. Future combat slices peel off one keyword
//!   at a time.
//! - **No legality checks beyond "creature on attacker's battlefield,
//!   untapped, not summoning-sick".** Tapped and summoning-sick
//!   creatures are rejected as attackers; that's the full attack-
//!   eligibility vocabulary today. Defender keyword, "can't attack"
//!   effects, attacked-alone restrictions are deferred.
//! - **No blocking restrictions beyond "blocker is a creature, on
//!   the battlefield, not tapped, and the named attacker is in
//!   `state.attackers`".** Flying / reach, defender-only, color
//!   protection, "can't be blocked by ..." gates are deferred.
//! - **Single-blocker damage assignment.** When multiple blockers are
//!   declared on the same attacker, the attacker assigns its full
//!   power to the FIRST declared blocker. All declared blockers
//!   still deal their power back to the attacker. Trample / multi-
//!   blocker damage ordering (CR 510.1c) is the SBA-and-trample
//!   slice's job.
//! - **No "whenever attacks/blocks/deals combat damage" triggers.**
//!   No event dispatcher in Rust yet.
//! - **No SBAs after damage.** Lethal damage staying past
//!   `deal_combat_damage` is intentional — the SBA sibling slice
//!   owns "damage >= toughness => destroy" (CR 704.5h).
//! - **`clear_combat` does not untap attackers.** Untapping is the
//!   untap-step's job (`state_ops_steps.rs:advance_phase` /
//!   `state_ops_tap.rs:untap_all_for_player`). `clear_combat` only
//!   zeroes the `attackers` / `blockers` Vecs.
//!
//! ## Cross-slice composition
//!
//! - **Tap on declare-attacker:** `declare_attacker` flips
//!   `tapped = true` on the declared creature in-place via
//!   `Arc::make_mut`. Mirrors the tap-slice's `tap_object` shape but
//!   inlined here so the parallel-TDD constraint (sibling slices own
//!   their own files) doesn't force a `pub(crate)` promotion on
//!   `state_ops_tap.rs`.
//! - **Damage on combat damage:** `deal_combat_damage` mutates each
//!   damaged creature's `damage` field in-place via `Arc::make_mut` on
//!   the containing battlefield Vec. Mirrors the damage-slice's
//!   `deal_damage` shape but inlined here for the same parallel-TDD
//!   reason.
//! - **Life on unblocked:** unblocked attackers subtract their power
//!   from the defending player's `life` field directly — same path
//!   `lose_life` uses. The two-player model picks the defender as
//!   `1 - active_player`.
//!
//! ## CoW invariant
//!
//! Both `declare_attacker` (taps) and `deal_combat_damage` (marks
//! damage) mutate per-zone Vecs through `Arc::make_mut`, so cloning
//! a `GameState` and mutating the clone leaves the original
//! untouched. The two `test_clone_then_..._does_not_affect_original`
//! canaries pin this — same load-bearing shape as the per-slice CoW
//! canaries in `test_tap.py` and `test_damage.py`.

use crate::state::{GameObject, GameState};
use pyo3::prelude::*;
use std::sync::Arc;

/// Locate a battlefield permanent by id and return `(player_idx,
/// printing_id)` so callers can read printing data (power, etc.) and
/// know which player's battlefield to mutate. Returns `None` if no
/// battlefield permanent has that id.
fn locate_battlefield_obj(state: &GameState, obj_id: u32) -> Option<(usize, u32)> {
    for (idx, player) in state.players.iter().enumerate() {
        for obj in player.battlefield.iter() {
            if obj.id == obj_id {
                return Some((idx, obj.printing_id));
            }
        }
    }
    None
}

/// Apply `f` to the battlefield permanent with `obj_id` via
/// `Arc::make_mut` on the containing battlefield Vec. Returns whether
/// the object was found. Inlined per-slice because sibling tap/damage
/// slices own their own copies of this helper (parallel-TDD
/// constraint — see module docstring).
fn mutate_battlefield_obj<F>(state: &mut GameState, obj_id: u32, mut f: F) -> bool
where
    F: FnMut(&mut GameObject),
{
    for player in state.players.iter_mut() {
        if player.battlefield.iter().any(|o| o.id == obj_id) {
            let zone: &mut Vec<GameObject> = Arc::make_mut(&mut player.battlefield);
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

/// Read-only check: is this object on a battlefield AND a creature
/// (printing.power.is_some())? Returns `Some((tapped, summoning_sick))`
/// when the object exists on a battlefield AND is a creature; `None`
/// otherwise (object missing OR non-creature).
fn read_creature_status(state: &GameState, obj_id: u32) -> Option<(bool, bool)> {
    let (idx, printing_id) = locate_battlefield_obj(state, obj_id)?;
    let printing = state.registry.lookup(printing_id)?;
    if printing.power.is_none() {
        return None;
    }
    // Re-find the object to read its tapped / summoning_sick flags.
    for obj in state.players[idx].battlefield.iter() {
        if obj.id == obj_id {
            return Some((obj.tapped, obj.summoning_sick));
        }
    }
    None
}

/// Read printing.power for a battlefield creature, returning 0 for
/// non-creatures or unknown ids. Used by `deal_combat_damage` to size
/// each side's contribution to the symmetric exchange.
fn battlefield_creature_power(state: &GameState, obj_id: u32) -> i16 {
    let Some((_, printing_id)) = locate_battlefield_obj(state, obj_id) else {
        return 0;
    };
    let Some(printing) = state.registry.lookup(printing_id) else {
        return 0;
    };
    printing.power.unwrap_or(0)
}

#[pymethods]
impl GameState {
    /// Declare the battlefield creature with `obj_id` as an attacker.
    ///
    /// On success: pushes `obj_id` onto `self.attackers`, taps the
    /// creature, returns `true`. On any precondition failure:
    /// returns `false` with no mutation.
    ///
    /// Preconditions:
    /// - object exists on some battlefield
    /// - object's printing has `power.is_some()` (creature predicate)
    /// - object is NOT tapped
    /// - object is NOT summoning-sick
    ///
    /// **No legality checks beyond the four above.** Defender, "can't
    /// attack", attacked-alone restrictions, and "doesn't untap during
    /// untap step" interactions are deferred — see module docstring.
    fn declare_attacker(&mut self, obj_id: u32) -> bool {
        // Read-only validation pass — bail before any mutation if the
        // creature isn't eligible.
        let Some((tapped, summoning_sick)) = read_creature_status(self, obj_id) else {
            return false;
        };
        if tapped || summoning_sick {
            return false;
        }
        // Eligible. Tap the creature (CR 508.1c — attacking taps the
        // attacker, modulo vigilance which is deferred) and record it
        // on the attackers Vec. The tap goes through Arc::make_mut so
        // the CoW invariant survives.
        let tapped_ok = mutate_battlefield_obj(self, obj_id, |obj| {
            obj.tapped = true;
        });
        if !tapped_ok {
            // Should be unreachable — read_creature_status already
            // located it. Defensive: if a clone race or other
            // instability removed it, undo nothing.
            return false;
        }
        self.attackers.push(obj_id);
        true
    }

    /// Declare the battlefield creature with `blocker_id` as a
    /// blocker against the previously-declared attacker `attacker_id`.
    ///
    /// On success: pushes `(attacker_id, blocker_id)` onto
    /// `self.blockers`, returns `true`. On any precondition failure:
    /// returns `false` with no mutation.
    ///
    /// Preconditions:
    /// - `attacker_id` is in `self.attackers`
    /// - `blocker_id` resolves to a battlefield creature
    /// - blocker is NOT tapped
    ///
    /// **No blocking restrictions beyond the three above.** Flying /
    /// reach, defender-only, "can't be blocked by ..." gates are
    /// deferred — see module docstring.
    ///
    /// Blocking does NOT tap the blocker (CR 509.1).
    fn declare_blocker(&mut self, blocker_id: u32, attacker_id: u32) -> bool {
        if !self.attackers.contains(&attacker_id) {
            return false;
        }
        let Some((tapped, _summoning_sick)) = read_creature_status(self, blocker_id) else {
            // Object missing OR non-creature.
            return false;
        };
        if tapped {
            return false;
        }
        // Note: we do NOT check the blocker's summoning_sick flag.
        // Summoning sickness restricts attacking and tap-abilities,
        // not blocking (CR 302.1) — a freshly cast creature can block
        // the turn it comes down.
        self.blockers.push((attacker_id, blocker_id));
        true
    }

    /// Read the declared attackers as a list of object ids in
    /// declaration order. Returns a fresh `Vec<u32>` (a Python list
    /// after the PyO3 conversion).
    fn get_attackers(&self) -> Vec<u32> {
        self.attackers.clone()
    }

    /// Read the declared blocker pairs as a list of `(attacker_id,
    /// blocker_id)` tuples in declaration order.
    fn get_blockers(&self) -> Vec<(u32, u32)> {
        self.blockers.clone()
    }

    /// Resolve one round of combat damage.
    ///
    /// For each declared attacker:
    /// - If the attacker has at least one blocker (the FIRST entry
    ///   in `self.blockers` matching `attacker_id`): assign attacker
    ///   power as damage to that blocker. (Multi-blocker assignment
    ///   ordering / trample lives in a future slice.)
    /// - If the attacker has no blocker: subtract attacker power from
    ///   the defending player's life. Defender = `1 - active_player`
    ///   in the two-player model.
    ///
    /// For each declared blocker (regardless of whether it's the
    /// "first" blocker on its attacker): assign blocker power as
    /// damage to the attacker. This is the symmetric back-damage
    /// half of the exchange.
    ///
    /// **No first-strike / double-strike timing.** Damage is one
    /// monolithic step today; the two-step ordering lands in a
    /// future slice when first-strike comes online.
    ///
    /// **No SBA enforcement.** Damage marks stay; lethal-damage-
    /// destroys-creature is the SBA slice's job.
    fn deal_combat_damage(&mut self) -> PyResult<()> {
        // Snapshot attacker/blocker plans first. Mutating the
        // battlefield (damage marks, life) is held off until after the
        // plan is built so simultaneous-damage semantics aren't
        // sequence-corrupted (e.g. attacker dies mid-loop and stops
        // dealing). The plan is a Vec of (target_kind, target_id,
        // amount) triples. target_kind is "creature" or "player";
        // target_id is the obj id (creature) or player id (player).
        enum DamageTarget {
            Creature(u32),
            Player(u8),
        }
        let mut plan: Vec<(DamageTarget, i16)> = Vec::new();

        let defending_player: u8 = 1 - self.active_player;

        for &attacker_id in &self.attackers {
            let attacker_power = battlefield_creature_power(self, attacker_id);
            // Find the FIRST blocker matching this attacker (single-
            // blocker damage simplification — see module docstring).
            let first_blocker: Option<u32> = self
                .blockers
                .iter()
                .find_map(|(a, b)| if *a == attacker_id { Some(*b) } else { None });
            if let Some(blocker_id) = first_blocker {
                if attacker_power > 0 {
                    plan.push((DamageTarget::Creature(blocker_id), attacker_power));
                }
            } else if attacker_power > 0 {
                plan.push((DamageTarget::Player(defending_player), attacker_power));
            }
        }
        // Back-damage from EVERY declared blocker, regardless of
        // assignment order. (Real MTG: each blocker also deals damage
        // simultaneously; trample / multi-blocker complexity is
        // deferred but the back-damage lane is symmetric.)
        for &(attacker_id, blocker_id) in &self.blockers {
            let blocker_power = battlefield_creature_power(self, blocker_id);
            if blocker_power > 0 {
                plan.push((DamageTarget::Creature(attacker_id), blocker_power));
            }
        }

        // Apply the plan.
        for (target, amount) in plan {
            match target {
                DamageTarget::Creature(obj_id) => {
                    mutate_battlefield_obj(self, obj_id, |obj| {
                        obj.damage = obj.damage.saturating_add(amount);
                    });
                }
                DamageTarget::Player(player_id) => {
                    let idx = player_id as usize;
                    if idx < self.players.len() {
                        self.players[idx].life -= amount as i32;
                    }
                }
            }
        }
        Ok(())
    }

    /// End-of-combat scaffolding cleanup: empty `self.attackers` and
    /// `self.blockers`.
    ///
    /// Does NOT untap declared attackers — that's the untap-step's
    /// job (CR 502.1). Does NOT clear marked damage on creatures —
    /// damage wears off in the cleanup step (CR 514.2), which lives
    /// in `state_ops_damage.rs:clear_all_damage`.
    fn clear_combat(&mut self) {
        self.attackers.clear();
        self.blockers.clear();
    }
}
