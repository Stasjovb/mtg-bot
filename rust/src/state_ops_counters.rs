//! Counter primitives on `GameState`.
//!
//! Filled in by a TDD-slice branch (see `tests_rust/README.md`).
//! Stub block exists so other slices can grow `GameState` in
//! parallel without conflicting on a single `#[pymethods]` block.
//!
//! `GameObject.counters: i32` already exists (per-instance scalar);
//! the first slice models +1/+1 (positive) and -1/-1 (negative)
//! as a single net count, since they cancel at SBAs. Future slices
//! extend to a proper multi-kind map once a card needs charge / lore
//! / loyalty / brick / etc.

use crate::state::GameState;
use pyo3::prelude::*;

#[pymethods]
impl GameState {
    // (counter modification methods land here)
}
