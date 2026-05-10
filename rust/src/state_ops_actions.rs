//! `apply_action(action_dict)` pymethod on `GameState`.
//!
//! Phase 3 dispatcher — `docs/RUST_PARITY_PLAN.md`. Parses an `Action`
//! dict via `actions::parse_action`, matches on the closed enum, and
//! routes to the right primitive (e.g. `Action::PassPriority` →
//! existing `pass_priority()` from the round-4 priority slice;
//! `Action::PlayLand` → `play_land()` from round 4's cast slice).
//!
//! ## Slice scope
//!
//! Round 22 wired `PassPriority`; round 23 adds `PlayLand` (10 of 420
//! decisions / ~2.4% in round-20's sample game — the 4th-most-frequent
//! variant). Future slices grow the match arm (CastSpell, Activate,
//! ...) plus a `legal_decisions` enumerator and a
//! `state.consecutive_passes` field for the "both passed -> resolve /
//! advance" composition.
//!
//! ## Actor convention for hand-targeting actions
//!
//! The Python `PlayLand(card_id: int)` dataclass carries only the
//! card id — the actor is implicit. Python's `apply_action` takes an
//! explicit `player_id` parameter; the Rust dispatcher derives the
//! same value from `state.priority_player` (the player currently
//! making decisions). The `play_land` primitive itself takes
//! `(obj_id, player_id)` and only succeeds if `obj_id` is in that
//! player's hand, so misrouted dispatch fails cleanly rather than
//! silently mutating the wrong side.
//!
//! ## Cross-file dispatch pattern (round-16)
//!
//! `pass_priority()` lives in `state_ops_priority.rs` as a
//! `#[pymethods]` method on `GameState`. PyO3's `multiple-pymethods`
//! feature lets the methods coexist on the same class, but the
//! underlying Rust fn stays module-private — we can't call
//! `self.pass_priority()` directly from this slice without touching
//! `state_ops_priority.rs` (forbidden by the per-slice file-isolation
//! rule). The fix is to take `Bound<'_, Self>` rather than `&mut self`
//! and dispatch through the Python attribute layer with
//! `call_method0`. PyO3's `Bound<T>` is a borrow-checked handle to a
//! Python object; the `.borrow()` / `.borrow_mut()` cost is identical
//! to the borrow the `#[pymethods]` macro would have generated for
//! `&mut self`, so the pattern adds at most one extra Python-attr
//! lookup per call. See `state_ops_stack.rs:process_stack_until_empty`
//! for the original use of this pattern.

use crate::actions::{parse_action, Action};
use crate::state::GameState;
use pyo3::prelude::*;
use pyo3::types::PyDict;

#[pymethods]
impl GameState {
    /// Apply a Python-side Action dict to this state. The dict's
    /// `kind` selects the arm; each arm routes to the matching
    /// primitive on `GameState`.
    ///
    /// Returns `None` — this is a side-effecting mutator (Python
    /// convention for void methods).
    ///
    /// Arms:
    /// - `{"kind": "pass_priority"}` → calls `pass_priority()`
    ///   (round 22).
    /// - `{"kind": "play_land", "card_id": <u32>}` → calls
    ///   `play_land(card_id, priority_player)` (round 23).
    ///
    /// Unknown `kind` raises `ValueError`; missing `kind` or other
    /// required keys (e.g. `card_id` for `play_land`) raise
    /// `KeyError`. Both bubble up from `actions::parse_action`.
    fn apply_action(slf: Bound<'_, Self>, action_dict: &Bound<'_, PyDict>) -> PyResult<()> {
        let action = parse_action(action_dict)?;
        match action {
            Action::PassPriority => {
                // Cross-file pymethod dispatch (round-16 pattern):
                // `pass_priority` lives in state_ops_priority.rs and
                // is private to that module's `impl GameState` block.
                // Go through the Python attribute layer to call it.
                slf.call_method0("pass_priority")?;
            }
            Action::PlayLand { card_id } => {
                // Same cross-file pattern as `pass_priority`, but
                // `play_land(obj_id, player_id)` takes args, so
                // use `call_method1`. The actor is the priority
                // player — Python's `PlayLand` dataclass carries
                // only `card_id` and the dispatcher resolves the
                // implicit actor here. We borrow `slf` for the
                // single u8 field read, then drop the borrow before
                // re-entering Python via `call_method1` (which
                // would re-borrow under the hood).
                let player_id = slf.borrow().priority_player;
                slf.call_method1("play_land", (card_id, player_id))?;
            }
        }
        Ok(())
    }
}
