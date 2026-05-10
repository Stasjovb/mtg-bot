//! Win / loss condition primitives on `GameState`.
//!
//! Filled in by a TDD-slice branch (see `tests_rust/README.md`).
//! Stub block exists so other slices can grow `GameState` in
//! parallel without conflicting on a single `#[pymethods]` block.
//!
//! Composes with the round-1 life slice — a player with life <= 0
//! loses (CR 104.3a, simplified). Future slices add the other loss
//! conditions (deck-out 104.3b, poison counters 104.3c, etc.).

use crate::state::GameState;
use pyo3::prelude::*;

#[pymethods]
impl GameState {
    // (win / loss methods land here)
}
