//! Phase / step advancement primitives on `GameState`.
//!
//! Filled in by a TDD-slice branch (see `tests_rust/README.md`).
//! Stub block exists so other slices can grow `GameState` in
//! parallel without conflicting on a single `#[pymethods]` block.
//!
//! `GameState.phase: u8` already exists; this slice's branch picks
//! a canonical phase encoding (constants or proper enum), the
//! advance_phase rotation, and any composition with sibling slices'
//! primitives (e.g. firing untap_all_for_player at the untap step).

use crate::state::GameState;
use pyo3::prelude::*;

#[pymethods]
impl GameState {
    // (phase / step methods land here)
}
