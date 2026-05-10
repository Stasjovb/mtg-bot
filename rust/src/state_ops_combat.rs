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
//! - **No double-strike / infect / protection / unblockable.**
//!   First-strike + trample land in this slice; the remaining
//!   keywords are deferred. Future combat slices peel off one keyword
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
//! - **Trample (CR 702.19) IS modeled — single-blocker case only.**
//!   When an attacker with `"trample"` in `printing.keywords` is
//!   blocked, any excess of `attacker.power` over the (single)
//!   blocker's printed `toughness` is dealt to the defending player.
//!   `excess = max(attacker.power - blocker.toughness, 0)`. Trample
//!   does NOT add a second helping on the unblocked path — an
//!   unblocked attacker already deals all its power to the defender
//!   through the existing path; trample only widens the blocked path.
//!   Multi-blocker damage distribution (CR 510.1c) stays deferred —
//!   the round-5 combat slice itself only applies attacker.power to
//!   the FIRST declared blocker.
//! - **First-strike (CR 702.7) IS modeled.** When ANY participant in
//!   combat has `"first_strike"` in `printing.keywords`,
//!   `deal_combat_damage` runs in two passes: a "first-strike damage
//!   step" applying only first-strike sources' damage, then a
//!   "regular damage step" applying only non-first-strike sources'
//!   damage AND only from sources still alive (i.e. their marked
//!   `damage` is < their printed `toughness` after the first step).
//!   Trample / deathtouch / lifelink fire inside whichever pass
//!   actually applies the damage. **No double-strike** in this slice
//!   (a double-strike creature would deal damage in BOTH passes);
//!   deferred. SBAs are still NOT fired between the two passes —
//!   the within-function "alive" check uses `damage < toughness`
//!   rather than running `apply_sbas`, mirroring the round-5
//!   simplification that the SBA slice owns lethal-damage cleanup.
//! - **Haste (CR 702.10) IS modeled.** A creature with `"haste"` in
//!   `printing.keywords` bypasses the summoning-sickness rejection
//!   in `declare_attacker` — a freshly-cast haste creature can
//!   attack the turn it enters. Haste does NOT bypass the "must be
//!   untapped to attack" precondition (a pre-tapped haste creature
//!   is still rejected) and does NOT skip the tap-on-attack step
//!   (haste != vigilance — a haste creature without vigilance still
//!   taps when declared as attacker). Haste + vigilance composes:
//!   the haste branch handles the summoning-sick gate, the vigilance
//!   branch handles the tap step. Haste also affects activated
//!   tap-abilities in real MTG (CR 302.1 covers both attacking and
//!   activating tap-cost abilities); this slice only models the
//!   attacking half because `declare_attacker` is the only summoning-
//!   sick gate today.
//! - **Defender (CR 702.3) IS modeled.** A creature whose printing
//!   carries the `"defender"` keyword is rejected at `declare_attacker`.
//!   Defender wins over haste — a creature with both keywords still
//!   cannot attack (haste only bypasses the summoning-sickness gate;
//!   it does not grant the ability to attack a creature otherwise
//!   prohibited from attacking). Defender does NOT affect blocking,
//!   damage, or any other phase. Other "can't attack" effects (Propaganda,
//!   summoning-sick-without-haste was already covered) and attacked-alone
//!   restrictions are still deferred.
//! - **Menace (CR 702.110) IS modeled — predicate, not declare-time gate.**
//!   A creature with `"menace"` can't be blocked except by two or more
//!   creatures. Enforcement uses an `is_legal_block_assignment(attacker_id)`
//!   predicate rather than rejecting at `declare_blocker`: the first
//!   blocker assigned to a menace attacker is illegal in isolation but
//!   legal once a second is added — declare-time rejection would force
//!   callers into an artificial "all-at-once" submission API. The
//!   predicate counts entries in `self.blockers` matching `attacker_id`
//!   and returns false iff the attacker has menace AND that count is
//!   exactly 1. Zero blockers (unblocked) and 2+ blockers are legal;
//!   non-menace attackers always pass. Other multi-blocker constraints
//!   (e.g. "can't be blocked by more than two") stay deferred.
//! - **No other attack-eligibility legality checks** beyond
//!   "creature on attacker's battlefield, untapped, not summoning-sick
//!   (modulo haste), not defender". "Can't attack" continuous effects
//!   beyond defender, attacked-alone restrictions, etc. remain deferred.
//! - **Flying (CR 702.9) + reach (CR 702.17) IS modeled.** A flying
//!   attacker (printing carries `"flying"`) can only be blocked by
//!   creatures whose printing carries `"flying"` or `"reach"`; other
//!   blockers are refused at `declare_blocker`. Reach on the BLOCKER
//!   is the gate-opener; reach on the ATTACKER is a no-op for blocking
//!   purposes (a reach attacker is treated as a ground creature —
//!   blockable by anything). Defender-only, color protection,
//!   "can't be blocked by ..." gates are still deferred.
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

/// Read currently-marked `damage` on a battlefield creature, or 0 if
/// not present. Used by the first-strike "is the source still alive
/// for the regular damage step?" check in `deal_combat_damage`.
fn battlefield_creature_damage(state: &GameState, obj_id: u32) -> i16 {
    for player in state.players.iter() {
        for obj in player.battlefield.iter() {
            if obj.id == obj_id {
                return obj.damage;
            }
        }
    }
    0
}

/// Plan target for one entry in `deal_combat_damage`'s damage plan.
/// Hoisted out of the function body so the per-pass apply helper
/// (`apply_damage_pass`) can take the entry list as a parameter.
enum DamageTarget {
    Creature(u32),
    Player(u8),
}

/// One entry in `deal_combat_damage`'s damage plan: a source dealing
/// `amount` damage to `target`, plus whether the source carries
/// first-strike (so the two-pass partition can route entries without
/// re-reading the keyword).
struct PlanEntry {
    source_id: u32,
    target: DamageTarget,
    amount: i16,
    source_has_first_strike: bool,
}

/// "Is this creature still alive after the first-strike damage step?"
/// Returns true unless the creature's current marked `damage` is
/// >= its printed `toughness` (CR 704.5g lethal-damage condition,
/// inlined here without firing SBAs — the SBA slice owns the
/// destroy-creature mutation; we only need the predicate to gate
/// pass-2 damage from a creature that took lethal in pass 1).
/// Returns true for creatures with toughness <= 0 (treated as
/// already-dead via the > check) — but that's a degenerate seed and
/// the test surface doesn't exercise it.
fn battlefield_creature_alive(state: &GameState, obj_id: u32) -> bool {
    let toughness = battlefield_creature_toughness(state, obj_id);
    if toughness <= 0 {
        return false;
    }
    let damage = battlefield_creature_damage(state, obj_id);
    (damage as i32) < (toughness as i32)
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
    /// - object is NOT summoning-sick — UNLESS the printing carries
    ///   the `"haste"` keyword (CR 702.10), in which case the
    ///   summoning-sickness restriction is bypassed.
    ///
    /// Vigilance only suppresses the tap-on-attack step; it does NOT
    /// bypass the "must be untapped to attack" precondition (a
    /// pre-tapped vigilance creature still fails) and does NOT grant
    /// haste.
    ///
    /// Haste only suppresses the summoning-sickness rejection; it
    /// does NOT bypass the "must be untapped to attack" precondition
    /// (a pre-tapped haste creature still fails) and does NOT grant
    /// vigilance — a haste creature without vigilance still taps when
    /// it attacks. Haste + vigilance composes (attack on the same turn
    /// it entered AND skip the tap).
    ///
    /// Defender (CR 702.3) is the fifth gate, added in this slice: a
    /// creature with `"defender"` in its printing keywords is rejected
    /// regardless of taps / summoning sickness / haste. Defender wins
    /// over haste — a creature with both keywords still cannot attack.
    ///
    /// **No legality checks beyond the five above.** "Can't attack"
    /// continuous effects beyond defender, attacked-alone restrictions,
    /// and "doesn't untap during untap step" interactions are deferred —
    /// see module docstring.
    fn declare_attacker(&mut self, obj_id: u32) -> bool {
        // Read-only validation pass — bail before any mutation if the
        // creature isn't eligible.
        let Some((tapped, summoning_sick)) = read_creature_status(self, obj_id) else {
            return false;
        };
        if tapped {
            return false;
        }
        // Defender (CR 702.3): a creature with defender can't attack.
        // This is independent of haste / summoning sickness — defender
        // wins over haste even when haste would otherwise bypass the
        // summoning-sickness gate.
        if battlefield_has_keyword(self, obj_id, "defender") {
            return false;
        }
        // Haste (CR 702.10) bypasses summoning sickness ONLY. Read the
        // keyword once here so the eligibility gate and the (later)
        // tap step can both see it — though only the eligibility gate
        // currently consults it; haste does NOT skip the tap step.
        // Pre-read so we don't pay the Arc::make_mut clone cost when
        // the creature is going to be rejected for some other reason.
        let has_haste = battlefield_has_keyword(self, obj_id, "haste");
        if summoning_sick && !has_haste {
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
    /// - if the attacker has the `"flying"` keyword (CR 702.9), the
    ///   blocker must have either `"flying"` or `"reach"` (CR 702.17)
    ///   — otherwise the block is refused.
    ///
    /// **No blocking restrictions beyond the four above.** Defender-only,
    /// color protection, "can't be blocked by ..." gates are deferred —
    /// see module docstring.
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
        // Flying gate (CR 702.9): a flying attacker can only be blocked
        // by creatures with flying or reach (CR 702.17). Reach on the
        // attacker is irrelevant for the blocking direction — only
        // flying on the attacker triggers this restriction.
        if battlefield_has_keyword(self, attacker_id, "flying") {
            let blocker_has_flying = battlefield_has_keyword(self, blocker_id, "flying");
            let blocker_has_reach = battlefield_has_keyword(self, blocker_id, "reach");
            if !blocker_has_flying && !blocker_has_reach {
                return false;
            }
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

    /// Validation predicate: is the current set of blockers against
    /// `attacker_id` a legal assignment under the keyword constraints
    /// this slice models?
    ///
    /// Today's only check: **menace (CR 702.110)** — a creature with
    /// `"menace"` can't be blocked except by two or more creatures.
    /// The predicate returns `false` iff the attacker has menace AND
    /// has exactly one blocker assigned in `self.blockers`. Returns
    /// `true` for:
    /// - non-menace attackers (any block count is legal)
    /// - menace attackers with zero blockers (unblocked is legal —
    ///   menace constrains HOW the attacker is blocked, not whether
    ///   it must be)
    /// - menace attackers with two or more blockers (multi-block
    ///   requirement satisfied)
    ///
    /// Used as a post-declare validator: callers run this after all
    /// blocks have been declared and unwind / reject the assignment
    /// when it returns false. We don't enforce at `declare_blocker`
    /// because the first blocker assigned to a menace attacker is
    /// illegal in isolation but legal once a second is added —
    /// declare-time rejection would force an "all-at-once"
    /// submission API.
    ///
    /// Read-only: never mutates state. Returns `true` for unknown
    /// `attacker_id` (no blockers can match → 0 blockers → legal).
    fn is_legal_block_assignment(&self, attacker_id: u32) -> bool {
        let blocker_count = self
            .blockers
            .iter()
            .filter(|(a, _)| *a == attacker_id)
            .count();
        if battlefield_has_keyword(self, attacker_id, "menace") && blocker_count == 1 {
            return false;
        }
        true
    }

    /// Resolve one round of combat damage.
    ///
    /// For each declared attacker:
    /// - If the attacker has at least one blocker (the FIRST entry
    ///   in `self.blockers` matching `attacker_id`): assign attacker
    ///   power as damage to that blocker. If the attacker has
    ///   `"trample"`, any excess of `attacker.power` over the
    ///   blocker's printed toughness is also dealt to the defending
    ///   player (CR 702.19).
    /// - If the attacker has no blocker: subtract attacker power from
    ///   the defending player's life. Defender = `1 - active_player`
    ///   in the two-player model. Trample does NOT add a second
    ///   helping on the unblocked path.
    ///
    /// For each declared blocker: assign blocker power as damage to
    /// the attacker. This is the symmetric back-damage half of the
    /// exchange.
    ///
    /// **First-strike (CR 702.7) IS modeled.** When ANY participant
    /// has `"first_strike"`, damage runs in two passes: pass 1 applies
    /// only first-strike sources' damage; pass 2 applies the rest,
    /// excluding sources whose marked `damage` >= printed `toughness`
    /// after pass 1 (i.e. sources that took lethal in pass 1 don't
    /// strike back). When NO participant has first-strike, the path
    /// degenerates to one pass, bit-identical to the pre-first-strike
    /// behavior.
    ///
    /// **No double-strike** in this slice — see module docstring.
    ///
    /// **No SBA enforcement between passes.** The "alive" check in
    /// pass 2 is a within-function `damage < toughness` predicate;
    /// dead creatures are NOT moved to the graveyard. Damage marks
    /// stay; lethal-damage-destroys-creature is the SBA slice's job.
    fn deal_combat_damage(&mut self) -> PyResult<()> {
        // Snapshot attacker/blocker plans first. Mutating the
        // battlefield (damage marks, life) is held off until after the
        // plan is built so simultaneous-damage semantics aren't
        // sequence-corrupted (e.g. attacker dies mid-loop and stops
        // dealing). Each plan entry carries:
        // - the source's id (so we can re-read deathtouch / lifelink
        //   keywords without re-walking the per-attacker logic)
        // - the target (creature / player)
        // - the literal `amount` of damage
        // - whether the source has first-strike (so we can partition
        //   the plan into pass-1 vs pass-2 entries without re-reading
        //   the keyword on every dispatch).
        let mut plan: Vec<PlanEntry> = Vec::new();

        let defending_player: u8 = 1 - self.active_player;

        for &attacker_id in &self.attackers {
            let attacker_power = battlefield_creature_power(self, attacker_id);
            let attacker_has_first_strike =
                battlefield_has_keyword(self, attacker_id, "first_strike");
            let attacker_has_trample = battlefield_has_keyword(self, attacker_id, "trample");
            // Find the FIRST blocker matching this attacker (single-
            // blocker damage simplification — see module docstring).
            let first_blocker: Option<u32> = self
                .blockers
                .iter()
                .find_map(|(a, b)| if *a == attacker_id { Some(*b) } else { None });
            if let Some(blocker_id) = first_blocker {
                if attacker_power > 0 {
                    // Trample (CR 702.19): the attacker is required
                    // to assign at least lethal (= blocker.toughness)
                    // to the blocker, but may assign at most that
                    // amount to the blocker, sending the excess to
                    // the defender. We use the strict "lethal to
                    // blocker, excess to defender" assignment so
                    // tests can see the blocker's marked damage equal
                    // its toughness (not the attacker's full power).
                    //
                    // Without trample, the attacker assigns its full
                    // power to the blocker — same as the round-5
                    // single-blocker simplification.
                    if attacker_has_trample {
                        let blocker_toughness =
                            battlefield_creature_toughness(self, blocker_id);
                        // Damage to blocker: min(attacker_power,
                        // blocker_toughness). When attacker_power <=
                        // blocker_toughness the blocker absorbs all
                        // of it (no excess); when attacker_power >
                        // blocker_toughness the blocker takes its
                        // toughness's worth and the rest goes to the
                        // defender.
                        let to_blocker = std::cmp::min(attacker_power, blocker_toughness);
                        if to_blocker > 0 {
                            plan.push(PlanEntry {
                                source_id: attacker_id,
                                target: DamageTarget::Creature(blocker_id),
                                amount: to_blocker,
                                source_has_first_strike: attacker_has_first_strike,
                            });
                        }
                        let excess = (attacker_power as i32) - (blocker_toughness as i32);
                        if excess > 0 {
                            plan.push(PlanEntry {
                                source_id: attacker_id,
                                target: DamageTarget::Player(defending_player),
                                amount: excess as i16,
                                source_has_first_strike: attacker_has_first_strike,
                            });
                        }
                    } else {
                        plan.push(PlanEntry {
                            source_id: attacker_id,
                            target: DamageTarget::Creature(blocker_id),
                            amount: attacker_power,
                            source_has_first_strike: attacker_has_first_strike,
                        });
                    }
                }
            } else if attacker_power > 0 {
                // Unblocked: the full attacker power goes to the
                // defender. Trample does NOT double-count here.
                plan.push(PlanEntry {
                    source_id: attacker_id,
                    target: DamageTarget::Player(defending_player),
                    amount: attacker_power,
                    source_has_first_strike: attacker_has_first_strike,
                });
            }
        }
        // Back-damage from EVERY declared blocker, regardless of
        // assignment order. (Real MTG: each blocker also deals damage
        // simultaneously; multi-blocker complexity is deferred but
        // the back-damage lane is symmetric.)
        for &(attacker_id, blocker_id) in &self.blockers {
            let blocker_power = battlefield_creature_power(self, blocker_id);
            let blocker_has_first_strike =
                battlefield_has_keyword(self, blocker_id, "first_strike");
            if blocker_power > 0 {
                plan.push(PlanEntry {
                    source_id: blocker_id,
                    target: DamageTarget::Creature(attacker_id),
                    amount: blocker_power,
                    source_has_first_strike: blocker_has_first_strike,
                });
            }
        }

        // First-strike timing (CR 702.7): if ANY plan entry's source
        // has first-strike, run two passes. Pass 1 applies only the
        // first-strike entries; then pass 2 applies the non-first-
        // strike entries — but only from sources still alive after
        // pass 1 (so a creature that took lethal first-strike damage
        // doesn't strike back).
        //
        // When no plan entry has first-strike, the partition is empty
        // / full and the two-pass code degenerates to one pass over
        // the original list — bit-identical to the pre-first-strike
        // behavior.
        let any_first_strike = plan.iter().any(|e| e.source_has_first_strike);

        if any_first_strike {
            // Partition into (first-strike pass, regular pass).
            let (pass_1, pass_2_all): (Vec<PlanEntry>, Vec<PlanEntry>) =
                plan.into_iter().partition(|e| e.source_has_first_strike);
            // Apply pass 1.
            self.apply_damage_pass(pass_1);
            // Filter pass 2 to only sources still alive after pass 1.
            // A source is alive iff its marked damage < printed
            // toughness — see `battlefield_creature_alive`.
            let pass_2: Vec<PlanEntry> = pass_2_all
                .into_iter()
                .filter(|e| battlefield_creature_alive(self, e.source_id))
                .collect();
            self.apply_damage_pass(pass_2);
        } else {
            self.apply_damage_pass(plan);
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

// Private (non-pymethods) impl for damage-pass application. Lives in
// a sibling `impl` so `#[pymethods]` doesn't try to expose it to Python
// (taking a `Vec<PlanEntry>` of a Rust-only struct, it can't be
// marshalled anyway).
impl GameState {
    /// Apply one damage pass: iterate the entries, mutate damage
    /// marks / player life, fire deathtouch upgrades and lifelink
    /// gains. Shared between the single-pass (no first-strike) and
    /// two-pass (first-strike present) branches of
    /// `deal_combat_damage` so the deathtouch / lifelink composition
    /// stays in one place.
    fn apply_damage_pass(&mut self, entries: Vec<PlanEntry>) {
        for entry in entries {
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
            // its power; trample-excess entries also fire lifelink
            // for their excess amount).
            if source_has_lifelink {
                if let Some(controller) = source_controller {
                    let cidx = controller as usize;
                    if cidx < self.players.len() {
                        self.players[cidx].life += entry.amount as i32;
                    }
                }
            }
        }
    }
}
