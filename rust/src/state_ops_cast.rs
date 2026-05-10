//! Cast / play primitives on `GameState`.
//!
//! Filled in by a TDD-slice branch (see `tests_rust/README.md`).
//! Stub block exists so other slices can grow `GameState` in
//! parallel without conflicting on a single `#[pymethods]` block.
//!
//! First slice scope: `play_land(obj_id)` (lands skip the stack)
//! and `cast_creature(obj_id)` (creature spells in the simplified
//! "no stack yet" model — directly to battlefield after paying
//! mana). Sorceries / instants / triggered-via-stack interactions
//! are deferred until a Rust-side stack lands.

use crate::state::GameState;
use pyo3::prelude::*;

#[pymethods]
impl GameState {
    // (cast / play methods land here)
}
