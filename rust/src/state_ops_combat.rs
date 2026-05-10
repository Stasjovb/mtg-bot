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
//! - **No first-strike / double-strike / trample / infect / protection
//!   / unblockable.**
//!   Damage in this slice is one symmetric round: each attacker
//!   assigns `power` damage to its first blocker (or to the defending
//!   player if unblocked), and each blocker assigns `power` damage
//!   back to the attacker. Future combat slices peel off one keyword
//!   at a time.
//! - **Vigilance (CR 702.20) IS modeled.** A creature with
//!   `"vigilance"` in `printing.keywords` skips the tap step on
//!   declare-attacker — it gets pushed onto `self.attackers` but
//!   `obj.tapped` stays False. Vigilance does NOT bypass the
//!   "must be untapped to attack" precondition (a pre-tapped
//!   vigilance creature is still rejected) and does NOT grant haste
//!   (a summoning-sick vigilance creature is still rejected).
//! - **Deathtouch (CR 702.2) IS modeled.** When a creature with
//!   `"deathtouch"` in `printing.keywords` deals NONZERO combat
//!   damage to another creature, the recipient's marked `damage` is
//!   upgraded to AT LEAST its printed `toughness` so the round-5
//!   lethal-damage SBA pass (`apply_sbas`) destroys it. The literal
//!   damage dealt is still the source's power — deathtouch only
//!   changes the lethality treatment, not the amount any other rule
//!   reads (CR 702.2c). Zero-power deathtouch creatures do NOT
//!   trigger the upgrade because deathtouch requires nonzero damage
//!   (CR 702.2b).
//! - **Lifelink (CR 702.15) IS modeled.** When a creature with
//!   `"lifelink"` in `printing.keywords` deals combat damage, its
//!   controller gains that much life — composed with the round-1
//!   life slice's mutation (`players[controller].life += amount`).
//!   Fires on damage dealt to creatures (blockers / attackers) AND
//!   on damage dealt to the defending player. This first slice only
//!   covers combat damage because `deal_combat_damage` is the only
//!   damage source today; non-combat damage sources will gain the
//!   same lifelink hook when they grow up.
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

/// Does this battlefield permanent's printing carry the
/// `"vigilance"` keyword? Returns false for unknown ids and for
/// printings whose `keywords` Vec doesn't contain the lowercase
/// `"vigilance"` string. Used by `declare_attacker` to skip the
/// tap-on-attack step (CR 702.20).
fn battlefield_has_vigilance(state: &GameState, obj_id: u32) -> bool {
    battlefield_has_keyword(state, obj_id, "vigilance")
}

/// Generic "does this battlefield permanent carry `keyword`?" check.
/// Returns false for unknown ids, non-battlefield objects, and
/// printings whose `keywords` Vec doesn't contain the lowercase
/// keyword string. Shared by the vigilance / deathtouch / lifelink
/// branches.
fn battlefield_has_keyword(state: &GameState, obj_id: u32, keyword: &str) -> bool {
    let Some((_, printing_id)) = locate_battlefield_obj(state, obj_id) else {
        return false;
    };
    let Some(printing) = state.registry.lookup(printing_id) else {
        return false;
    };
    printing.keywords.iter().any(|k| k == keyword)
}

/// Read printing.toughness for a battlefield creature, returning 0
/// for non-creatures or unknown ids. Used by `deal_combat_damage` to
/// size the deathtouch upgrade (the recipient's damage is bumped to
/// at least this value).
fn battlefield_creature_toughness(state: &GameState, obj_id: u32) -> i16 {
    let Some((_, printing_id)) = locate_battlefield_obj(state, obj_id) else {
        return 0;
    };
    let Some(printing) = state.registry.lookup(printing_id) else {
        return 0;
    };
    printing.toughness.unwrap_or(0)
}

/// Read controller (player index) of a battlefield creature, or
/// `None` if not present. Used by `deal_combat_damage` to credit
/// lifelink life-gain to the right player.
fn battlefield_creature_controller(state: &GameState, obj_id: u32) -> Option<u8> {
    for player in state.players.iter() {
        for obj in player.battlefield.iter() {
            if obj.id == obj_id {
                return Some(obj.controller);
            }
        }
    }
    None
}

#[pymethods]
impl GameState {
    /// Declare the battlefield creature with `obj_id` as an attacker.
    ///
    /// On success: pushes `obj_id` onto `self.attackers`, taps the
    /// creature (UNLESS the printing carries the `"vigilance"`
    /// keyword — CR 702.20), returns `true`. On any precondition
    /// failure: returns `false` with no mutation.
    ///
    /// Preconditions:
    /// - object exists on some battlefield
    /// - object's printing has `power.is_some()` (creature predicate)
    /// - object is NOT tapped
    /// - object is NOT summoning-sick
    ///
    /// Vigilance only suppresses the tap-on-attack step; it does NOT
    /// bypass the "must be untapped to attack" precondition (a
    /// pre-tapped vigilance creature still fails) and does NOT grant
    /// haste (a summoning-sick vigilance creature still fails).
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
        // Vigilance check: read before mutating so we don't pay the
        // Arc::make_mut clone cost when we're going to skip the tap.
        let has_vigilance = battlefield_has_vigilance(self, obj_id);
        // Eligible. Tap the creature (CR 508.1c — attacking taps the
        // attacker, modulo vigilance) and record it on the attackers
        // Vec. The tap goes through Arc::make_mut so the CoW invariant
        // survives. Vigilance creatures skip the tap step entirely.
        if !has_vigilance {
            let tapped_ok = mutate_battlefield_obj(self, obj_id, |obj| {
                obj.tapped = true;
            });
            if !tapped_ok {
                // Should be unreachable — read_creature_status already
                // located it. Defensive: if a clone race or other
                // instability removed it, undo nothing.
                return false;
            }
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
        // dealing). Each plan entry carries:
        // - the source's id (so we can re-read deathtouch / lifelink
        //   keywords without re-walking the per-attacker logic)
        // - the target (creature / player)
        // - the literal `amount` of damage (the source's power; this
        //   is what lifelink gains AND what the regular `damage +=`
        //   add uses — deathtouch upgrades only the recipient's mark,
        //   not the dealt amount, per CR 702.2c).
        enum DamageTarget {
            Creature(u32),
            Player(u8),
        }
        struct PlanEntry {
            source_id: u32,
            target: DamageTarget,
            amount: i16,
        }
        let mut plan: Vec<PlanEntry> = Vec::new();

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
                    plan.push(PlanEntry {
                        source_id: attacker_id,
                        target: DamageTarget::Creature(blocker_id),
                        amount: attacker_power,
                    });
                }
            } else if attacker_power > 0 {
                plan.push(PlanEntry {
                    source_id: attacker_id,
                    target: DamageTarget::Player(defending_player),
                    amount: attacker_power,
                });
            }
        }
        // Back-damage from EVERY declared blocker, regardless of
        // assignment order. (Real MTG: each blocker also deals damage
        // simultaneously; trample / multi-blocker complexity is
        // deferred but the back-damage lane is symmetric.)
        for &(attacker_id, blocker_id) in &self.blockers {
            let blocker_power = battlefield_creature_power(self, blocker_id);
            if blocker_power > 0 {
                plan.push(PlanEntry {
                    source_id: blocker_id,
                    target: DamageTarget::Creature(attacker_id),
                    amount: blocker_power,
                });
            }
        }

        // Apply the plan.
        for entry in plan {
            // Read the source's keywords + controller BEFORE applying
            // mutations. Deathtouch upgrades the recipient's mark to
            // at least its toughness (CR 702.2b — only fires on
            // nonzero damage, which the plan already filters via
            // `> 0` guards). Lifelink credits the source's controller
            // with `amount` life regardless of target kind.
            let source_has_deathtouch =
                battlefield_has_keyword(self, entry.source_id, "deathtouch");
            let source_has_lifelink =
                battlefield_has_keyword(self, entry.source_id, "lifelink");
            let source_controller = battlefield_creature_controller(self, entry.source_id);

            match entry.target {
                DamageTarget::Creature(obj_id) => {
                    let recipient_toughness = battlefield_creature_toughness(self, obj_id);
                    let amount = entry.amount;
                    mutate_battlefield_obj(self, obj_id, |obj| {
                        obj.damage = obj.damage.saturating_add(amount);
                        // Deathtouch: upgrade the recipient's marked
                        // damage to at least its toughness so the SBA
                        // slice destroys it. The plan only contains
                        // entries with `amount > 0`, satisfying CR
                        // 702.2b's "nonzero damage" precondition.
                        if source_has_deathtouch && recipient_toughness > 0 {
                            if (obj.damage as i32) < (recipient_toughness as i32) {
                                obj.damage = recipient_toughness;
                            }
                        }
                    });
                }
                DamageTarget::Player(player_id) => {
                    let idx = player_id as usize;
                    if idx < self.players.len() {
                        self.players[idx].life -= entry.amount as i32;
                    }
                }
            }

            // Lifelink: gain life on the source's controller equal to
            // the literal damage amount. Fires once per damage entry
            // (so a lifelink attacker hitting a player gains its
            // power; a lifelink blocker hitting an attacker gains
            // its power).
            if source_has_lifelink {
                if let Some(controller) = source_controller {
                    let cidx = controller as usize;
                    if cidx < self.players.len() {
                        self.players[cidx].life += entry.amount as i32;
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
