//! `legal_decisions(player_id) -> list[Action]` enumerator.
//!
//! The Phase 3 keystone: emits the closed set of legal Actions the
//! priority-holder can take right now. Python's MCTS / ISMCTS drives
//! off this enumeration; Rust must match Python's emission order
//! exactly (Action types + per-type inner ordering) for trajectory
//! parity in `scripts/parity_smoke.py`.
//!
//! Foundation stub. The `rust-legal-decisions-skeleton` slice fills
//! in the first-slice enumerator with PassPriority + PlayLand;
//! subsequent slices grow it to cover CastSpell, ActivateAbility,
//! DeclareAttackers, DeclareBlockers.

use crate::state::GameState;
use pyo3::prelude::*;

#[pymethods]
impl GameState {}
