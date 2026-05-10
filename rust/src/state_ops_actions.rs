//! `apply_action(action_dict)` pymethod on `GameState`.
//!
//! Round-22 foundation slice — Phase 3 kickoff of
//! `docs/RUST_PARITY_PLAN.md`. Parses an `Action` dict via
//! `actions::parse_action`, matches on the closed enum, and routes to
//! the right primitive (e.g. `Action::PassPriority` → existing
//! `pass_priority()` from the round-4 priority slice).
//!
//! ## First-slice scope
//!
//! Only the `PassPriority` arm is wired up — round-20 measurements
//! showed `PassPriority` was 364 of 420 decisions (~87%) in a sample
//! game, so it's the highest-impact variant to land first. Future
//! slices grow the match arm (CastSpell, PlayLand, Activate, ...)
//! plus a `legal_decisions` enumerator and `state.consecutive_passes`
//! tracking for the "both passed -> resolve / advance" composition.
//!
//! ## Cross-file dispatch pattern (round-16)
//!
//! `pass_priority()` lives in `state_ops_priority.rs` as a
//! `#[pymethods]` method on `GameState`. PyO3's `multiple-pymethods`
//! feature lets the methods coexist on the same class, but the
//! underlying Rust fn stays module-private — we can't call
//! `self.pass_priority()` directly from this slice without touching
//! `state_ops_priority.rs` (forbidden by the per-slice file-isolation
//! rule). The fix is to take `Bound<'_, Self>` rather than `&mut self`
//! and dispatch through the Python attribute layer with
//! `call_method0`. PyO3's `Bound<T>` is a borrow-checked handle to a
//! Python object; the `.borrow()` / `.borrow_mut()` cost is identical
//! to the borrow the `#[pymethods]` macro would have generated for
//! `&mut self`, so the pattern adds at most one extra Python-attr
//! lookup per call. See `state_ops_stack.rs:process_stack_until_empty`
//! for the original use of this pattern.

use crate::actions::{parse_action, Action};
use crate::state::GameState;
use pyo3::prelude::*;
use pyo3::types::PyDict;

#[pymethods]
impl GameState {
    /// Apply a Python-side Action dict to this state. The dict's
    /// `kind` selects the arm; each arm routes to the matching
    /// primitive on `GameState`.
    ///
    /// Returns `None` — this is a side-effecting mutator (Python
    /// convention for void methods).
    ///
    /// Round-22 first-slice arms:
    /// - `{"kind": "pass_priority"}` → calls `pass_priority()`.
    ///
    /// Unknown `kind` raises `ValueError`; missing `kind` raises
    /// `KeyError`. Both bubble up from `actions::parse_action`.
    fn apply_action(slf: Bound<'_, Self>, action_dict: &Bound<'_, PyDict>) -> PyResult<()> {
        let action = parse_action(action_dict)?;
        match action {
            Action::PassPriority => {
                // Cross-file pymethod dispatch (round-16 pattern):
                // `pass_priority` lives in state_ops_priority.rs and
                // is private to that module's `impl GameState` block.
                // Go through the Python attribute layer to call it.
                slf.call_method0("pass_priority")?;
            }
        }
        Ok(())
    }
}
