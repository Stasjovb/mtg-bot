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
        other => Err(PyValueError::new_err(format!(
            "unknown action kind {other:?}; valid: pass_priority, play_land, declare_attackers, declare_blockers"
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
    }
    Ok(d)
}
