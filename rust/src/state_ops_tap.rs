//! Tap / untap primitives on `GameState`.
//!
//! Filled in by a TDD-slice branch (see `tests_rust/README.md`).
//! Stub block exists so other slices can grow `GameState` in
//! parallel without conflicting on a single `#[pymethods]` block.

use crate::state::GameState;
use pyo3::prelude::*;

#[pymethods]
impl GameState {
    // (tap / untap methods land here)
}
