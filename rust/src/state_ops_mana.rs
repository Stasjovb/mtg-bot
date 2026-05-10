//! Mana production / payment primitives on `GameState` and per-player
//! mana pool methods.
//!
//! Filled in by a TDD-slice branch (see `tests_rust/README.md`).
//! Stub block exists so other slices can grow `GameState` in
//! parallel without conflicting on a single `#[pymethods]` block.
//!
//! `Player.mana_pool: ManaPool` is the new state field landing in
//! this commit's foundation; this slice's branch grows the methods
//! that read and mutate it.

use crate::state::GameState;
use pyo3::prelude::*;

#[pymethods]
impl GameState {
    // (mana production / payment methods land here)
}
