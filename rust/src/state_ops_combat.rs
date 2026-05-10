//! Combat primitives on `GameState`.
//!
//! Filled in by a TDD-slice branch (see `tests_rust/README.md`).
//! Stub block exists so other slices can grow `GameState` in
//! parallel without conflicting on a single `#[pymethods]` block.
//!
//! `GameState.attackers: Vec<u32>` and `GameState.blockers:
//! Vec<(u32, u32)>` already exist (added in this commit's
//! foundation). This slice grows declare_attackers, declare_blockers,
//! deal_combat_damage, and clear_combat (end-of-combat cleanup).

use crate::state::GameState;
use pyo3::prelude::*;

#[pymethods]
impl GameState {
    // (combat methods land here)
}
