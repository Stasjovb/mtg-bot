//! Read-only zone snapshot getters on `GameState`.
//!
//! Round-21 foundation stub. The rust-bridge-zone-snapshots slice fills
//! in the pymethods. These getters return Python lists of dicts that
//! the parity smoke (`scripts/parity_smoke.py`) hashes the same way it
//! hashes Python's GameState zones — they're the bridge surface that
//! lets the harness compare a Rust state to a Python state.

use crate::state::GameState;
use pyo3::prelude::*;

#[pymethods]
impl GameState {}
