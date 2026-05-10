//! State-based action (SBA) primitives on `GameState`.
//!
//! Filled in by a TDD-slice branch (see `tests_rust/README.md`).
//! Stub block exists so other slices can grow `GameState` in
//! parallel without conflicting on a single `#[pymethods]` block.
//!
//! First-slice scope: lethal-damage SBA (CR 704.5g — a creature
//! whose marked damage is at least its toughness is destroyed) and
//! the empty-library / negative-life loss conditions hooked into
//! the existing winloss slice's pure-derivation predicate. Composes
//! with state_ops_damage (damage), the bridge-ext's
//! CardPrinting.toughness, and state_ops_winloss (loss check).
//!
//! Future slices add the long-tail SBAs: aura without a legal
//! target falls off (704.5n), legendary-rule (704.5j),
//! +1/+1 vs -1/-1 cancellation (704.5r), commander damage
//! (704.5v), etc.

use crate::state::GameState;
use pyo3::prelude::*;

#[pymethods]
impl GameState {
    // (SBA methods land here)
}
