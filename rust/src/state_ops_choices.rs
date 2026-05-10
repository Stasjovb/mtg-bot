//! Helpers for "the active player makes a deterministic first-slice
//! choice" — used by effect dispatch and tests. Round-18 foundation
//! stub; round-18 choices slice fills in the body.
//!
//! The intent: extract the "pick the first card on the defender's
//! battlefield" / "first card in hand" / "top of library" patterns
//! that are duplicated across DealDamage / TapTarget / DestroyTarget /
//! AddCounters / DiscardCard arms in apply_effect into a small set
//! of named primitives. Each picker is a pure function over GameState
//! that returns `Option<u32>` (the chosen object id) or `None` when
//! the choice would fizzle. A future slice can then collapse the
//! duplicated arm code onto these helpers without touching cards.rs.

use crate::state::GameState;
use pyo3::prelude::*;

#[pymethods]
impl GameState {}
