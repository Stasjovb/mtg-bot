//! Damage primitives on `GameState`.
//!
//! Filled in by a TDD-slice branch (see `tests_rust/README.md`).
//! Stub block exists so other slices can grow `GameState` in
//! parallel without conflicting on a single `#[pymethods]` block.
//!
//! `GameObject.damage: i16` already exists — per-instance scalar.
//! First slice models damage as direct mutation of that field;
//! lethal-damage SBA enforcement (CR 704.5h) is a future slice
//! once a Rust-side state-based-actions loop lands.

use crate::state::GameState;
use pyo3::prelude::*;

#[pymethods]
impl GameState {
    // (damage methods land here)
}
