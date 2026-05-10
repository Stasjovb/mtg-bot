//! State construction from explicit zone contents.
//!
//! Bridge surface for the parity harness: lets Python build a Rust
//! GameState with caller-supplied registry + per-player library /
//! hand contents, so the same starting state can be constructed on
//! both engines from the same deck list.
//!
//! Round-23 foundation stub. The rust-state-from-decklists slice
//! fills in the `make_state` pyfunction.

#![allow(dead_code)]
