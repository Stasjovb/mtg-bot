//! Library / discard primitives on `GameState`.
//!
//! Filled in by a TDD-slice branch (see `tests_rust/README.md`).
//! Stub block exists so other slices can grow `GameState` in
//! parallel without conflicting on a single `#[pymethods]` block.
//!
//! First slice scope: shuffle (Fisher-Yates with a seedable RNG),
//! discard (hand -> graveyard movement), scry (look at top N,
//! reorder, optionally bottom). All compose with the round-1
//! zone movement primitives.

use crate::state::GameState;
use pyo3::prelude::*;

#[pymethods]
impl GameState {
    // (library / discard methods land here)
}
