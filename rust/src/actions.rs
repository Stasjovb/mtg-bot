//! Closed `Action` enum + Python-dict bridge.
//!
//! Round-22 foundation slice (Phase 3 kickoff of `docs/RUST_PARITY_PLAN.md`).
//! Mirrors the `cards.rs` pattern (closed enum + dict bridge / unknown-kind
//! error path / round-trip-able shape). Every Python `Action` subclass has a
//! corresponding Rust variant — no fallback path, per round 5's
//! no-opaque-blob design.
//!
//! ## First-slice scope
//!
//! Only `PassPriority` is implemented — round-20 measurements showed
//! `PassPriority` was 364 of 420 decisions (~87%) in a sample game, so
//! it's the highest-impact variant to land first. Future slices add
//! the other 5 most-common Actions (CastSpell, PlayLand, Activate, etc.)
//! and the `legal_decisions` enumerator.
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
        other => Err(PyValueError::new_err(format!(
            "unknown action kind {other:?}; valid: pass_priority"
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
    }
    Ok(d)
}
