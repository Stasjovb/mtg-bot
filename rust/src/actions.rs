//! Closed `Action` enum + Python-dict bridge.
//!
//! Round-22 foundation slice (Phase 3 kickoff of `docs/RUST_PARITY_PLAN.md`).
//! Mirrors the `cards.rs` pattern (closed enum + dict bridge / unknown-kind
//! error path / round-trip-able shape). Every Python `Action` subclass has a
//! corresponding Rust variant — no fallback path, per round 5's
//! no-opaque-blob design.
//!
//! ## Slice scope
//!
//! Round 22 landed `PassPriority` (364 of 420 decisions / ~87% in
//! round-20's sample game). Round 23 adds `PlayLand` (10 of 420 / ~2.4%
//! — the 4th-most-frequent variant after `PassPriority`,
//! `MainPhaseLand`-style decisions, and `CastSpell`). Future slices add
//! the remaining common Actions (CastSpell, Activate, ...) and the
//! `legal_decisions` enumerator.
//!
//! ## Bridge surface
//!
//! Python builds plain dicts describing each Action; Rust parses to
//! the closed enum at the FFI boundary inside `apply_action`. The
//! `parse_action` / `action_to_pydict` helpers stay module-internal
//! for this slice — Python only sees the `apply_action(dict)` end-to-end
//! surface on `GameState`. Future slices can lift these to module-level
//! pyfunctions when a test needs to round-trip a dict in isolation;
//! today the end-to-end path is enough.

use pyo3::exceptions::{PyKeyError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyDict;

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Action {
    /// Pass priority (CR 116.4). The decision is "I'm done acting at
    /// this priority moment". When both players consecutively pass on
    /// an empty stack, the engine advances to the next phase; when
    /// both pass on a non-empty stack, the top of the stack resolves.
    /// Round-22 first slice scope: this variant just records the
    /// decision; the "both passed -> resolve / advance" composition
    /// is a future slice (legal_decisions enumerator + state.consecutive_passes
    /// tracking are deferred). The current `pass_priority()` primitive
    /// only toggles priority to the other player.
    PassPriority,
    /// Play a land from hand (CR 305.2). `card_id` is the GameObject
    /// id in the active / priority player's hand. Restrictions (one
    /// per turn, only on your turn, only at sorcery speed) are the
    /// caller's responsibility to enforce — a future
    /// `legal_decisions()` enumerator will filter; `apply_action`
    /// delegates to the existing `play_land` primitive which only
    /// validates the card is in hand and is a land. The Python
    /// `PlayLand(card_id: int)` dataclass mirrors the same shape.
    /// Round-20 frequency: 10 of 420 decisions (~2.4%) in the sample
    /// game — the highest-impact PlayLand-style variant to add after
    /// `PassPriority`.
    PlayLand { card_id: u32 },
    /// Declare the set of attacking creatures for this combat (CR 508.1).
    /// `attacker_ids` mirrors Python's `frozenset[int]` — an unordered
    /// set of GameObject ids on the active player's battlefield that
    /// will become attackers. The round-5 `declare_attacker` primitive
    /// validates each id (creature predicate, untapped, not summoning
    /// sick modulo haste, not defender); ineligible ids are silently
    /// rejected by the primitive's `bool` return, mirroring Python's
    /// `_declare_attackers` filtering behavior. Pass an empty set to
    /// attack with nothing.
    ///
    /// **Shape note: `Vec<u32>`, not `HashSet`/`BTreeSet`.** The Python
    /// `DeclareAttackers(attacker_ids: frozenset[int])` dataclass is a
    /// set, but the dict serialization at the bridge boundary is a
    /// list — order is preserved across the FFI. `apply_action`'s
    /// dispatch loop calls `declare_attacker` once per id in iteration
    /// order, so the Vec shape gives the caller deterministic
    /// application order. The parity harness sorts before passing if
    /// it wants a canonical order; this slice does not impose one.
    ///
    /// Round-20 frequency: 16 of 420 decisions (~3.8%) in the sample
    /// game — the 3rd-most-frequent variant after `PassPriority` and
    /// `PlayLand`.
    DeclareAttackers { attacker_ids: Vec<u32> },
    /// Declare blocker assignments for combat (CR 509.1).
    /// `assignments` is a list of `(blocker_id, attacker_id)` pairs
    /// where each blocker is on the defending player's battlefield
    /// and each attacker is on the attacking player's battlefield +
    /// currently in `state.attackers`. The round-5 `declare_blocker`
    /// primitive validates each pair (creature predicate, untapped
    /// blocker, attacker-in-attackers, flying/skulk gates); ineligible
    /// pairs are silently rejected by the primitive's `bool` return,
    /// mirroring the Python side's filtering behavior. Pass an empty
    /// list to block with nothing.
    ///
    /// **Pair shape: `(blocker_id, attacker_id)`** — the same order as
    /// the underlying `declare_blocker(blocker_id, attacker_id)`
    /// primitive's argument list. Note this is the OPPOSITE order from
    /// `state.blockers` (which stores `(attacker_id, blocker_id)` pairs
    /// for fast attacker-keyed lookups during damage assignment).
    /// `apply_action` translates by passing `(blocker, attacker)`
    /// straight through to the primitive, which handles the storage-side
    /// reorder.
    ///
    /// **Iteration order is preserved.** `apply_action` calls
    /// `declare_blocker` once per pair in input order. The order matters
    /// for damage assignment when multiple blockers block the same
    /// attacker — the round-5 combat-damage assignment gives the
    /// attacker's power to the FIRST declared blocker for that
    /// attacker. Same blocker can't be in multiple pairs (one block per
    /// blocker, per CR 509.1c — but this slice doesn't enforce that
    /// gate; the caller / future `legal_decisions` enumerator owns it).
    /// Same attacker CAN appear in multiple pairs (multi-block).
    ///
    /// Round-20 frequency: 5 of 420 decisions (~1.2%) in the sample
    /// game — the 4th-most-frequent variant after `PassPriority`,
    /// `PlayLand`, and `DeclareAttackers`.
    DeclareBlockers { assignments: Vec<(u32, u32)> },
    /// Activate an ability on a permanent (CR 113.3 + 602). `source_id`
    /// is the GameObject whose ability fires; `ability_index` is the
    /// 0-based index into the source's printing.activated_abilities
    /// list (CR 602.2 — printings can have multiple activated
    /// abilities, indexed by position). Mirrors Python's
    /// `ActivateAbility(source_id: int, ability_index: int)`
    /// dataclass — two ints, no implicit actor (the source object's
    /// controller is the actor, resolved by the underlying primitive
    /// from the battlefield index when it lands).
    ///
    /// Round-20 frequency: 8 of 420 decisions (~1.9%) in the sample
    /// game — the 5th-most-frequent variant after `PassPriority`,
    /// `DeclareAttackers`, `PlayLand`, and `DeclareBlockers`.
    ///
    /// **Dispatch is currently a stub.** No Rust `activate_ability`
    /// primitive exists yet (rounds 1-22 didn't build one). Until a
    /// future slice adds the primitive (mana-cost pay + ability
    /// resolution flow, mirroring how `play_land` / `cast_creature`
    /// pay mana costs), `apply_action` raises `ValueError` for this
    /// variant; the variant + bridge round-trip ship now, so a
    /// follow-up slice only needs to flip the dispatch arm.
    ///
    /// **CE20 follow-up Slice 4 (Equipment-equip).** The optional
    /// `target_creature_id` carries the chosen target for activations
    /// whose cost flags `requires_target_creature_you_control = true`
    /// (CR 702.6c — equip targets a creature you control). Default
    /// `None` for every pre-Slice-4 caller (the legacy 2-int shape) —
    /// the bridge round-trips `parse_action` ↔ `action_to_pydict`
    /// losslessly on both shapes. Apply-arm logic raises if the cost
    /// requires a target and the field is `None`, OR if the target
    /// fails the legality check (must be a creature on the
    /// activator's bf and not the source itself).
    ActivateAbility {
        source_id: u32,
        ability_index: u32,
        target_creature_id: Option<u32>,
    },
    /// Cast a spell from hand (CR 601). `card_id` is the GameObject
    /// id in the priority player's hand. The 5 optional fields carry
    /// alt-cost / mode metadata mirrored bit-for-bit from Python's
    /// `CastSpell(card_id, use_warp=False, kicked=False,
    /// cast_for_free=False, use_impending=False, cast_room_half=None)`
    /// dataclass so a Python-emitted dict round-trips losslessly
    /// through `parse_action` → `action_to_pydict`:
    ///
    ///   - `use_warp`: warp alt-cost (EoE — impulse-cast from
    ///     exile zone or warp-from-hand with end-of-turn exile).
    ///   - `kicked`: kicker additional cost paid on top of the base
    ///     mana cost (only legal when the printing has a kicker_cost).
    ///   - `cast_for_free`: free-cast windows (e.g. Weftwalking's
    ///     "first spell each player casts may be cast without paying
    ///     its mana cost"). Mutually exclusive with use_warp / kicked.
    ///   - `use_impending`: impending deferred-creature mode (DSK /
    ///     EoE Overlord cycle — enters with `impending_count` time
    ///     counters, creature-ness suppressed until the last counter
    ///     comes off at the controller's end step).
    ///   - `cast_room_half`: which half of a Room enchantment (DSK)
    ///     — `None` for non-Room cards, `Some(name)` for Rooms (the
    ///     half-name string is the Room's locked-door label that the
    ///     unlock-cost is sourced from).
    ///
    /// Round-20 frequency: 17 of 420 decisions (~4.0%) — the
    /// second-most-frequent non-`PassPriority` variant after
    /// `DeclareAttackers`.
    ///
    /// **First-slice scope: variant + bridge ship; dispatch IGNORES
    /// the flags.** The existing round-4 `cast_creature(obj_id,
    /// player_id)` primitive doesn't yet accept alt-cost / mode
    /// flags; wiring each flag through is a future-slice followup
    /// (the warp / kicker / impending plumbing depends on Effect
    /// dispatch for those mechanics + cost-stacking infrastructure
    /// that doesn't exist in Rust yet). The variant landing now
    /// unblocks the Python → Rust bridge round-trip for production
    /// `CastSpell` payloads — search-loop dispatch can drive Rust
    /// state through the same dict shape Python already emits, and a
    /// future slice flips the dispatch arm without changing the
    /// variant's shape. Mirrors the round-23 ActivateAbility
    /// "scaffold the variant, defer the dispatch semantics" pattern.
    CastSpell {
        card_id: u32,
        use_warp: bool,
        kicked: bool,
        cast_for_free: bool,
        use_impending: bool,
        cast_room_half: Option<String>,
    },
    /// Turn a face-down permanent face up by paying its underlying
    /// card's mana cost (CR 701.34 / 707.4 — Morph / Manifest Dread
    /// flip + Edge of Eternities Spacecraft station / launch). `card_id`
    /// is the GameObject on the priority player's battlefield to flip.
    /// Mirrors Python's `TurnFaceUp(card_id: int)` dataclass — a
    /// single-int shape, identical to `PlayLand`. CR 701.34 / 707.4 is
    /// a special action — does not use the stack; costs are paid
    /// immediately and the flip resolves at once.
    ///
    /// **Dispatch is currently a stub.** No Rust face-down GameObject
    /// state exists yet (the `GameObject` struct has no `face_down`
    /// flag, and there's no Spacecraft charge-counter resolution), so
    /// there's nothing for a `turn_face_up` primitive to flip. Until a
    /// future slice adds the per-object face-down state + the flip
    /// primitive (analogous to how `tap` / `untap` toggle the existing
    /// `tapped` flag), `apply_action` raises `ValueError` for this
    /// variant; the variant + bridge round-trip ship now, so a
    /// follow-up slice only needs to flip the dispatch arm. Mirrors the
    /// round-23 ActivateAbility "scaffold the variant, defer the
    /// dispatch semantics" pattern.
    TurnFaceUp { card_id: u32 },
    /// Tap a creature to add charge counters to a Spacecraft (Edge of
    /// Eternities "station" activation). `spacecraft_id` is the
    /// GameObject id of the Spacecraft permanent on the active player's
    /// battlefield; `crew_id` is the creature being tapped (cost) to
    /// add a charge counter to the Spacecraft (effect). Mirrors
    /// Python's `ActivateStation(spacecraft_id: int, crew_id: int)`
    /// dataclass — two ints, no implicit actor (the Spacecraft's
    /// controller is the actor, resolved by the underlying primitive
    /// from the battlefield index when it lands). Sorcery-speed only
    /// (enforced by the future `legal_decisions` enumerator, not by
    /// this dispatch arm).
    ///
    /// Per the EoE Spacecraft cycle: Spacecraft enter as artifacts with
    /// no creature types and accumulate charge counters via station-
    /// attaching; they turn face up (become creatures with printed
    /// stats) when launched via `TurnFaceUp` once enough charge counters
    /// have been added. The station action adds a number of charge
    /// counters equal to the tapped creature's power.
    ///
    /// **Dispatch is currently a stub.** Rust has no Spacecraft
    /// charge-counter state today, and there's no crew-tap-resolution
    /// primitive that ties the tap-as-cost to the counter-add-as-effect.
    /// Until a future slice adds the Spacecraft charge-counter state +
    /// the activate-station primitive (analogous to how Python's
    /// `_activate_station` taps the crew creature, reads its power, and
    /// adds that many charge counters to the Spacecraft), `apply_action`
    /// raises `ValueError` for this variant; the variant + bridge
    /// round-trip ship now, so a follow-up slice only needs to flip the
    /// dispatch arm. Mirrors the round-23 ActivateAbility and round-24
    /// TurnFaceUp / UnlockRoomHalf "scaffold the variant, defer the
    /// dispatch semantics" pattern.
    ActivateStation { spacecraft_id: u32, crew_id: u32 },
    /// Pay a Room enchantment half's mana cost to unlock it (DSK Rooms
    /// mechanic, CR 715.3-4). `card_id` is the GameObject id of the
    /// Room enchantment on the active player's battlefield;
    /// `half_name` is which of the two halves to unlock (the half's
    /// name string per the printing — Rooms have two named halves and
    /// the controller picks which to unlock). Mirrors Python's
    /// `UnlockRoomHalf(card_id: int, half_name: str)` dataclass —
    /// two fields, one int + one string, no implicit actor (the
    /// Room's controller is the actor, resolved from the battlefield
    /// index when the primitive lands).
    ///
    /// Per CR 715.3-4: as a sorcery, the controller of an unlocked
    /// Room on the battlefield with at least one locked door may
    /// unlock a locked door of that Room by paying its mana cost as
    /// though they were casting an enchantment spell. The unlock
    /// action is NOT a spell — it doesn't go on the stack. On apply,
    /// the named half is added to the Room's `unlocked_halves` set
    /// and any newly-active triggered abilities on the entering half
    /// (e.g. "When you unlock this door, ...") fire.
    ///
    /// **Dispatch is currently a stub.** Rust has no Room-half state
    /// today — the per-object `unlocked_halves: set[str]` field that
    /// Python's `GameObject` carries is missing on the Rust side, and
    /// there's no half-specific effect activation. Until a future
    /// slice adds the per-object Room state + the unlock primitive
    /// (analogous to how Python's `_unlock_room_half` mutates the set
    /// and fires the half-specific ENTERS triggers), `apply_action`
    /// raises `ValueError` for this variant; the variant + bridge
    /// round-trip ship now, so a follow-up slice only needs to flip
    /// the dispatch arm. Mirrors the round-23 ActivateAbility and
    /// round-24 TurnFaceUp "scaffold the variant, defer the dispatch
    /// semantics" pattern.
    UnlockRoomHalf { card_id: u32, half_name: String },
}

// --- dict -> Rust ------------------------------------------------

fn require<'py>(
    dict: &Bound<'py, PyDict>,
    key: &str,
) -> PyResult<Bound<'py, PyAny>> {
    dict.get_item(key)?
        .ok_or_else(|| PyKeyError::new_err(format!("missing required key: {key:?}")))
}

/// Parse a Python dict into the closed `Action` enum. Single point of
/// validation: unknown `kind` values and missing required keys raise
/// loudly here, before `apply_action` dispatches anything.
pub fn parse_action(dict: &Bound<'_, PyDict>) -> PyResult<Action> {
    let kind: String = require(dict, "kind")?.extract()?;
    match kind.as_str() {
        "pass_priority" => Ok(Action::PassPriority),
        "play_land" => {
            let card_id: u32 = require(dict, "card_id")?.extract()?;
            Ok(Action::PlayLand { card_id })
        }
        "declare_attackers" => {
            // Accept any Python iterable — list, tuple, frozenset, set
            // — by `iter()`-ing the object and extracting each
            // element as a u32. PyO3's `extract::<Vec<u32>>()` is
            // restricted to `Sequence` (list/tuple) and would reject
            // a frozenset / set with a `TypeError: 'frozenset' object
            // cannot be converted to 'Sequence'`, but the Python
            // `DeclareAttackers(attacker_ids: frozenset[int])`
            // dataclass field IS a frozenset — callers who pass the
            // dataclass field directly (without going through the
            // bridge's list-serialization step) would hit that
            // failure. Iterating with `try_iter` covers both shapes.
            // Wrong inner type (e.g. a string in the set) bubbles up
            // as a `TypeError` from PyO3's extract machinery —
            // matches the `card_id`-wrong-type behavior on
            // `play_land`.
            let raw = require(dict, "attacker_ids")?;
            let mut attacker_ids: Vec<u32> = Vec::new();
            for item in raw.try_iter()? {
                attacker_ids.push(item?.extract::<u32>()?);
            }
            Ok(Action::DeclareAttackers { attacker_ids })
        }
        "declare_blockers" => {
            // Same `try_iter` shape as `declare_attackers` at the outer
            // level — accept any iterable (list, tuple, set, frozenset,
            // generator) of pair-shaped inner items. For the INNER
            // pair, we iterate again rather than `extract::<(u32, u32)>()`
            // because PyO3's tuple-extract is strict: it accepts only
            // Python `tuple`, rejecting `list` with
            // `TypeError: 'list' object cannot be converted to 'PyTuple'`.
            // Python's `DeclareBlockers(assignments: tuple[tuple[int,
            // int], ...])` dataclass field is a tuple of tuples, but
            // the on-the-wire JSON-style shape often uses lists of
            // lists — the bridge accepts both. We pre-collect the
            // inner iteration to validate the exact-2 shape before
            // unpacking; wrong arity (`3-tuple, 1-list`) raises
            // `ValueError` here. Wrong inner element type (string,
            // None) bubbles up as `TypeError` from `extract::<u32>`.
            let raw = require(dict, "assignments")?;
            let mut assignments: Vec<(u32, u32)> = Vec::new();
            for item in raw.try_iter()? {
                let item = item?;
                let mut parts = Vec::with_capacity(2);
                for elem in item.try_iter()? {
                    parts.push(elem?.extract::<u32>()?);
                    if parts.len() > 2 {
                        return Err(PyValueError::new_err(
                            "declare_blockers assignment must be a 2-element (blocker_id, attacker_id) pair",
                        ));
                    }
                }
                if parts.len() != 2 {
                    return Err(PyValueError::new_err(
                        "declare_blockers assignment must be a 2-element (blocker_id, attacker_id) pair",
                    ));
                }
                assignments.push((parts[0], parts[1]));
            }
            Ok(Action::DeclareBlockers { assignments })
        }
        "activate_ability" => {
            // Two-int shape: `source_id` (the GameObject whose ability
            // fires) + `ability_index` (0-based index into the source's
            // printing.activated_abilities list). Same shape as
            // `play_land`'s `card_id` extraction — missing either key
            // → `KeyError` via `require`; wrong type → `TypeError` /
            // `ValueError` from PyO3's `extract::<u32>` machinery.
            //
            // CE20 follow-up Slice 4 (Equipment-equip): optional
            // `target_creature_id` carries the chosen target for
            // activations whose cost flags
            // `requires_target_creature_you_control = true`. Missing
            // key OR explicit `None` map to `None` (matches Python's
            // `ActivateAbility(target_creature_id=None)` default).
            let source_id: u32 = require(dict, "source_id")?.extract()?;
            let ability_index: u32 = require(dict, "ability_index")?.extract()?;
            let target_creature_id: Option<u32> =
                match dict.get_item("target_creature_id")? {
                    Some(v) if !v.is_none() => Some(v.extract()?),
                    _ => None,
                };
            Ok(Action::ActivateAbility {
                source_id,
                ability_index,
                target_creature_id,
            })
        }
        "cast_spell" => {
            // `card_id` is required (the only positional field on
            // Python's `CastSpell` dataclass — every other field has
            // a keyword default). The 5 flag fields are all optional;
            // missing keys default to the Python dataclass defaults
            // (False for bools, None for cast_room_half). This means
            // a "minimal" `{"kind": "cast_spell", "card_id": N}` dict
            // is the equivalent of Python's `CastSpell(card_id=N)`
            // call — the most common shape the search loop emits.
            //
            // Wrong types bubble up as `TypeError` / `ValueError`
            // from `extract::<bool>` / `extract::<String>` — same
            // shape as the `card_id`-wrong-type behavior on
            // `play_land` / `activate_ability`.
            let card_id: u32 = require(dict, "card_id")?.extract()?;
            let use_warp: bool = match dict.get_item("use_warp")? {
                Some(v) => v.extract()?,
                None => false,
            };
            let kicked: bool = match dict.get_item("kicked")? {
                Some(v) => v.extract()?,
                None => false,
            };
            let cast_for_free: bool = match dict.get_item("cast_for_free")? {
                Some(v) => v.extract()?,
                None => false,
            };
            let use_impending: bool = match dict.get_item("use_impending")? {
                Some(v) => v.extract()?,
                None => false,
            };
            // `cast_room_half` is `Option<String>`: missing key OR
            // explicit `None` both map to `None`. A non-None,
            // non-string value raises `TypeError` from
            // `extract::<String>`.
            let cast_room_half: Option<String> = match dict.get_item("cast_room_half")? {
                Some(v) if !v.is_none() => Some(v.extract()?),
                _ => None,
            };
            Ok(Action::CastSpell {
                card_id,
                use_warp,
                kicked,
                cast_for_free,
                use_impending,
                cast_room_half,
            })
        }
        "turn_face_up" => {
            // Single-int shape mirroring `play_land` — `card_id` is the
            // GameObject id of the face-down permanent on the priority
            // player's battlefield to flip face up. Missing key →
            // `KeyError` via `require`; wrong type → `TypeError` /
            // `ValueError` from PyO3's `extract::<u32>` machinery.
            let card_id: u32 = require(dict, "card_id")?.extract()?;
            Ok(Action::TurnFaceUp { card_id })
        }
        "unlock_room_half" => {
            // Two-field shape — `card_id` (u32) names the Room
            // enchantment on the active player's battlefield;
            // `half_name` (string) selects which of the two halves to
            // unlock. Mirrors Python's `UnlockRoomHalf(card_id: int,
            // half_name: str)` dataclass — both fields required, no
            // optional flags. Missing either key → `KeyError` via
            // `require`; wrong type → `TypeError` / `ValueError` from
            // PyO3's `extract::<u32>` / `extract::<String>` machinery.
            let card_id: u32 = require(dict, "card_id")?.extract()?;
            let half_name: String = require(dict, "half_name")?.extract()?;
            Ok(Action::UnlockRoomHalf { card_id, half_name })
        }
        "activate_station" => {
            // Two-int shape mirroring `activate_ability` — `spacecraft_id`
            // names the Spacecraft permanent on the active player's
            // battlefield; `crew_id` names the creature being tapped as
            // cost to add a charge counter to the Spacecraft. Mirrors
            // Python's `ActivateStation(spacecraft_id: int, crew_id: int)`
            // dataclass — both fields required, no optional flags.
            // Missing either key → `KeyError` via `require`; wrong type
            // → `TypeError` / `ValueError` from PyO3's `extract::<u32>`
            // machinery.
            let spacecraft_id: u32 = require(dict, "spacecraft_id")?.extract()?;
            let crew_id: u32 = require(dict, "crew_id")?.extract()?;
            Ok(Action::ActivateStation {
                spacecraft_id,
                crew_id,
            })
        }
        other => Err(PyValueError::new_err(format!(
            "unknown action kind {other:?}; valid: pass_priority, play_land, declare_attackers, declare_blockers, activate_ability, cast_spell, turn_face_up, unlock_room_half, activate_station"
        ))),
    }
}

// --- Rust -> dict (round-trip) -----------------------------------

/// Serialize a Rust `Action` back to its Python dict shape. Held
/// module-internal for the round-22 slice; no Python pyfunction
/// exposure yet. The round-trip property (parse then serialize ==
/// input) is preserved so a future slice can lift this to a
/// `#[pyfunction]` without behavioral change.
#[allow(dead_code)]
pub fn action_to_pydict<'py>(
    py: Python<'py>,
    action: &Action,
) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    match action {
        Action::PassPriority => {
            d.set_item("kind", "pass_priority")?;
        }
        Action::PlayLand { card_id } => {
            d.set_item("kind", "play_land")?;
            d.set_item("card_id", *card_id)?;
        }
        Action::DeclareAttackers { attacker_ids } => {
            d.set_item("kind", "declare_attackers")?;
            // `Vec<u32>` round-trips through PyO3 as a Python list,
            // preserving Vec iteration order. The round-trip
            // property (parse_action → action_to_pydict → parse_action
            // yields the same Action) is preserved because `extract::<
            // Vec<u32>>()` on a list reads back the same order.
            d.set_item("attacker_ids", attacker_ids.clone())?;
        }
        Action::DeclareBlockers { assignments } => {
            d.set_item("kind", "declare_blockers")?;
            // `Vec<(u32, u32)>` round-trips through PyO3 as a Python
            // list of 2-tuples. Iteration order is preserved by the
            // PyO3 conversion. The inbound parser accepts any iterable
            // of 2-tuples / 2-element lists, so this list-of-tuples
            // shape is one valid input shape (the canonical wire
            // shape), and `parse_action(action_to_pydict(action))`
            // returns the same `Action::DeclareBlockers`.
            d.set_item("assignments", assignments.clone())?;
        }
        Action::ActivateAbility {
            source_id,
            ability_index,
            target_creature_id,
        } => {
            d.set_item("kind", "activate_ability")?;
            d.set_item("source_id", *source_id)?;
            d.set_item("ability_index", *ability_index)?;
            // CE20 follow-up Slice 4: always emit
            // `target_creature_id` so round-trip is symmetric — a
            // parse-then-serialize pair lands on a dict that exactly
            // equals the canonical "all-fields-present" shape.
            // Callers that emit the minimal {kind, source_id,
            // ability_index} shape get a slightly-richer dict back,
            // but the re-parsed Action is bit-identical (None default
            // for non-target activations).
            //
            // `Option<u32>` round-trips as `None` → Python None /
            // `Some(id)` → Python int via PyO3's `IntoPy` impl on
            // `Option<T>`.
            d.set_item("target_creature_id", *target_creature_id)?;
        }
        Action::CastSpell {
            card_id,
            use_warp,
            kicked,
            cast_for_free,
            use_impending,
            cast_room_half,
        } => {
            d.set_item("kind", "cast_spell")?;
            d.set_item("card_id", *card_id)?;
            // Always emit all 5 flag fields so round-trip is fully
            // symmetric — a parse-then-serialize pair lands on a dict
            // that exactly equals the canonical "all-fields-present"
            // shape. Callers that emit the minimal `{kind, card_id}`
            // shape get a slightly-richer dict back, but the
            // re-parsed Action is bit-identical (all-False / None
            // defaults).
            d.set_item("use_warp", *use_warp)?;
            d.set_item("kicked", *kicked)?;
            d.set_item("cast_for_free", *cast_for_free)?;
            d.set_item("use_impending", *use_impending)?;
            // `Option<String>` round-trips as `None` -> Python None /
            // `Some(s)` -> Python str. PyO3's `set_item` handles both
            // via the `IntoPy` impl on `Option<T>`.
            d.set_item("cast_room_half", cast_room_half.clone())?;
        }
        Action::TurnFaceUp { card_id } => {
            d.set_item("kind", "turn_face_up")?;
            d.set_item("card_id", *card_id)?;
        }
        Action::UnlockRoomHalf {
            card_id,
            half_name,
        } => {
            d.set_item("kind", "unlock_room_half")?;
            d.set_item("card_id", *card_id)?;
            d.set_item("half_name", half_name.clone())?;
        }
        Action::ActivateStation {
            spacecraft_id,
            crew_id,
        } => {
            d.set_item("kind", "activate_station")?;
            d.set_item("spacecraft_id", *spacecraft_id)?;
            d.set_item("crew_id", *crew_id)?;
        }
    }
    Ok(d)
}
