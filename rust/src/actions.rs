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
        other => Err(PyValueError::new_err(format!(
            "unknown action kind {other:?}; valid: pass_priority, play_land, declare_attackers"
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
    }
    Ok(d)
}
