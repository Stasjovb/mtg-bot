//! Counter-spell primitives on `GameState`.
//!
//! Filled in by a TDD-slice branch (see `tests_rust/README.md`).
//! Stub block exists so other slices can grow `GameState` in
//! parallel without conflicting on a single `#[pymethods]` block.
//!
//! First-slice scope: `counter_spell(target_obj_id)` removes the
//! corresponding stack item from the stack (the "countered" spell
//! never resolves) and moves the spell's source to the controller's
//! graveyard. Composes round-5's stack `remove_from_stack` and
//! round-1 zones `move_object`. Counter-spell legality enforcement
//! (e.g. "this spell can't be countered") is deferred until the
//! cant_be_countered flag exists on CardPrinting.

use crate::state::GameState;
use pyo3::prelude::*;

#[pymethods]
impl GameState {
    // (counter-spell methods land here)
}
