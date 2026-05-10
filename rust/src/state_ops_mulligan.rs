//! Mulligan / opening-hand primitives on `GameState`.
//!
//! Filled in by a TDD-slice branch (see `tests_rust/README.md`).
//! Stub block exists so other slices can grow `GameState` in
//! parallel without conflicting on a single `#[pymethods]` block.
//!
//! First-slice scope: `mulligan(player_id, seed)` shuffles the
//! library + draws an opening hand of 7. Caller invokes repeatedly
//! to do iterative mulligans (CR 103.4 / London mulligan); cost is
//! tracked externally for now.
//!
//! Composes round-1 zones (draw_card) + round-4 library
//! (shuffle_library_with_seed). The cross-file private-method
//! friction is hit again — inline the logic per the recurring
//! pattern.

use crate::state::GameState;
use pyo3::prelude::*;

#[pymethods]
impl GameState {
    // (mulligan / opening-hand methods land here)
}
