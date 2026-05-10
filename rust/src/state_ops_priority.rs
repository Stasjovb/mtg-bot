//! Priority management primitives on `GameState`.
//!
//! Filled in by a TDD-slice branch (see `tests_rust/README.md`).
//! Stub block exists so other slices can grow `GameState` in
//! parallel without conflicting on a single `#[pymethods]` block.
//!
//! `GameState.priority_player: u8` already exists; this slice
//! exposes Python-callable getters/setters and the pass-priority
//! semantics. Composition with phase advancement (active player
//! gets priority at start of each step) is left for a future
//! slice that integrates state_ops_priority + state_ops_steps.

use crate::state::GameState;
use pyo3::prelude::*;

#[pymethods]
impl GameState {
    // (priority methods land here)
}
