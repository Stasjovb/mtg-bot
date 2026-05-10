//! Stack primitives on `GameState`.
//!
//! Filled in by a TDD-slice branch (see `tests_rust/README.md`).
//! Stub block exists so other slices can grow `GameState` in
//! parallel without conflicting on a single `#[pymethods]` block.
//!
//! `GameState.stack: Vec<StackItem>` already exists (added in this
//! commit's foundation; top of stack = LAST element of Vec for O(1)
//! pop, mirroring the library convention). This slice grows push /
//! peek / pop / size / empty queries. Resolution semantics — what
//! happens when a stack item resolves — depend on the effect
//! grammar and are deferred to a future slice.

use crate::state::GameState;
use pyo3::prelude::*;

#[pymethods]
impl GameState {
    // (stack methods land here)
}
