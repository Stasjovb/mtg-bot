//! Deck-loading primitives on `GameState`.
//!
//! Filled in by a TDD-slice branch (see `tests_rust/README.md`).
//! Stub block exists so other slices can grow `GameState` in
//! parallel without conflicting on a single `#[pymethods]` block.
//!
//! First-slice scope: `load_deck(player_id, [printing_id, ...])`
//! replaces the player's library with fresh GameObjects (one per
//! printing_id in the input list, in order); top-of-library = LAST
//! element of the Vec to mirror the round-1 zones convention.
//! Composes with the round-4 library shuffle and round-1 zones.

use crate::state::GameState;
use pyo3::prelude::*;

#[pymethods]
impl GameState {
    // (deck-loading methods land here)
}
