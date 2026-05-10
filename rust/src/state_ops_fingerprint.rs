//! `fingerprint() -> str` pymethod on `GameState`.
//!
//! Round-22 foundation stub. The `rust-bridge-fingerprint` slice
//! fills in a Rust-computed hash that matches what
//! `scripts/parity_smoke.py:hash_state` produces for an equivalent
//! Python state. Same field set, same order, same SHA1 digest.
//!
//! This is the canonical state-equality oracle for parity testing —
//! when a Rust state and a Python state are byte-equivalent in
//! gameplay-relevant content, they produce the same fingerprint
//! string. The harness can then compare a single string instead of
//! walking zone snapshots dict-by-dict.

use crate::state::GameState;
use pyo3::prelude::*;

#[pymethods]
impl GameState {}
