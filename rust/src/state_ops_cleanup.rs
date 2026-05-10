//! Cleanup-step primitives on `GameState`.
//!
//! Filled in by a TDD-slice branch (see `tests_rust/README.md`).
//! Stub block exists so other slices can grow `GameState` in
//! parallel without conflicting on a single `#[pymethods]` block.
//!
//! First-slice scope: hand-size limit enforcement at cleanup
//! (CR 514.1 — discard down to maximum hand size, default 7).
//! Composes with state_ops_library's `discard` and the round-2
//! `state_ops_steps`'s phase encoding.
//!
//! Other cleanup-step actions (CR 514.2 damage clearance,
//! 514.3 "until end of turn" effects expiration) are deferred —
//! the damage clearance might compose via the existing
//! `clear_all_damage` from state_ops_damage.

use crate::state::GameState;
use pyo3::prelude::*;

#[pymethods]
impl GameState {
    // (cleanup-step methods land here)
}
