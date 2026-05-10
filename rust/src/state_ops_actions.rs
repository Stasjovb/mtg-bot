//! `apply_action(action_dict)` pymethod on `GameState`.
//!
//! Round-22 foundation stub. The `rust-action-foundation` slice fills
//! the dispatcher: parses an Action dict via `actions::parse_action`,
//! matches on the closed enum, and routes to the right primitive
//! (e.g. `Action::PassPriority` → existing `pass_priority()` from
//! the round-4 priority slice via PyO3's call_method0 cross-file
//! pattern from round 16).
//!
//! Phase 3 of the parity plan (docs/RUST_PARITY_PLAN.md) — start of
//! the legal_decisions / apply_action surface that lets Python's
//! search loop drive Rust state.

use crate::state::GameState;
use pyo3::prelude::*;

#[pymethods]
impl GameState {}
