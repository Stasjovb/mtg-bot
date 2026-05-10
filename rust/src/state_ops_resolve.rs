//! Stack-resolution primitives on `GameState`.
//!
//! Filled in by a TDD-slice branch (see `tests_rust/README.md`).
//! Stub block exists so other slices can grow `GameState` in
//! parallel without conflicting on a single `#[pymethods]` block.
//!
//! First-slice scope: `resolve_top_of_stack()` peeks the top stack
//! item, looks up its source printing's effects via the registry,
//! applies each effect, then pops the item. Supported effects today:
//! just `DealDamage` (the only Effect variant in the bridge).
//!
//! Composes: stack (round-5 stack slice) + bridge effects
//! (round-3 bridge-ext) + damage (round-3 damage slice). Targeting
//! is simplified — TargetFilter::AnyPlayer / AnyCreature picks
//! "the defending player" / "the first creature on the
//! defending player's battlefield" deterministically. Real targeting
//! requires a target-choice surface that's a future slice.

use crate::state::GameState;
use pyo3::prelude::*;

#[pymethods]
impl GameState {
    // (stack-resolution methods land here)
}
