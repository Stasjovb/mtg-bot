//! Priority management primitives on `GameState`.
//!
//! Mirrors `src/mtg_bot/game.py:GameState.priority_player_idx` and
//! the priority-round mechanism in `src/mtg_bot/turn.py`. The Rust
//! side keeps `priority_player` as a `u8` field on `GameState`
//! (already present from the foundation commit) and exposes
//! Python-callable getters / setters and pass-priority semantics
//! here.
//!
//! ## Slice scope
//!
//! Pass-priority is a 2-player toggle: `priority_player` flips to
//! the other player. Multi-player priority (CR 800.4 / APNAP) is
//! out of scope until/unless the engine grows past 2 players.
//!
//! ## Round-27 G3 + G4 + G15 closure: priority + steps + stack composition
//!
//! This slice closes the priority-composition layer:
//!
//! - **G3 (consecutive_passes + composer)**: `GameState.consecutive_passes`
//!   tracks "how many times in a row has `pass_priority` been called
//!   without any intervening non-pass mutation?". `pass_priority`
//!   increments it; every non-pass mutation (cast, activate, advance_phase,
//!   give_priority_to) resets it to 0. The new
//!   `complete_step_via_priority_round()` composer is the harness-facing
//!   "two passes finish the round" primitive — see its docstring for
//!   the CR 117.4 / 117.5 routing logic.
//! - **G4 (cast/activate reset priority to active)**: `cast_creature`
//!   and `apply_action`'s `ActivateAbility` arm now set
//!   `priority_player = active_player` after a successful mutation
//!   (CR 117.1c — the active player gets priority after a spell is
//!   cast or an ability resolves). Reset happens at the primitive
//!   layer so direct calls compose the same as dispatched ones.
//! - **G15 (advance_phase priority reset on wrap)**: `advance_phase`
//!   now resets `priority_player = active_player` when CLEANUP -> UNTAP
//!   wraps (CR 117.1a — the new active player gets priority at the
//!   start of their turn). Lives in `state_ops_steps.rs`.
//!
//! ## Round-9 extension: priority + stack composition
//!
//! `complete_priority_round` is the priority-round-completion
//! primitive. CR 117.4 / 117.5: when both players consecutively pass
//! priority while the stack is non-empty, the top stack item
//! resolves; CR 117.1c then says the active player gets priority
//! again. This file's caller is responsible for tracking whether
//! both players have passed (round-9 doesn't extend `GameState` with
//! a consecutive-pass counter — that would need a `state.rs` edit
//! which the parallel-slice file-isolation rule forbids). The caller
//! invokes `complete_priority_round()` once it's decided the round
//! is complete.
//!
//! ### Pop-only stepping-stone (NOT a full resolver)
//!
//! `complete_priority_round` does NOT dispatch the resolved item's
//! effects. It pops the top stack item, returns its dict, and resets
//! `priority_player` to `active_player`. Real effect dispatch lives
//! in `state_ops_resolve.rs:resolve_top_of_stack`.
//!
//! **Cross-file private-method friction.** This slice WANTS to call
//! `resolve_top_of_stack` directly so a single primitive does both
//! the bookkeeping AND the effect dispatch — but that method is
//! private to its module's `pyclass` impl block, and the parallel-
//! slice file-isolation rule forbids touching `state_ops_resolve.rs`
//! from this slice. Per the recurring inlining pattern (5+
//! instances: round-7 counterspell inlined `move_object`, round-8
//! resolve-effects inlined `draw_card`, etc.), the pragmatic call
//! here is to **inline a minimal version**: pop + reset priority, no
//! effect dispatch. That keeps the slice surface small AND
//! preserves a clean separation of concerns between
//! priority-bookkeeping (this file) and effect-dispatch
//! (`state_ops_resolve.rs`). A future composition slice can chain
//! the two — e.g. add a `resolve_and_complete_round()` umbrella —
//! once the file-isolation rule relaxes.

use crate::state::{GameState, StackItem};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyDict;

/// Build a 2-key dict from a StackItem. Mirrors the helper in
/// `state_ops_stack.rs` and `state_ops_resolve.rs` — duplicated here
/// per the per-slice file-isolation rule (private helpers can't be
/// shared across slice files until the consolidation slice).
fn stack_item_to_dict<'py>(
    py: Python<'py>,
    item: &StackItem,
) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("source_obj_id", item.source_obj_id)?;
    d.set_item("controller", item.controller)?;
    Ok(d)
}

#[pymethods]
impl GameState {
    /// Read the player who currently has priority. Returns the raw
    /// `u8` player id (0 or 1 in the 2-player model).
    fn get_priority_player(&self) -> u8 {
        self.priority_player
    }

    /// Python-property alias for `active_player`. Mirrors Python's
    /// `GameState.active_player_idx` dataclass field — read as a plain
    /// attribute (no parens). Used by `scripts/parity_smoke.py:hash_state`
    /// and other bridge consumers that read the Python surface
    /// uniformly.
    #[getter]
    fn active_player_idx(&self) -> u8 {
        self.active_player
    }

    /// Python-property alias for `get_priority_player()`. Mirrors
    /// Python's `GameState.priority_player_idx` dataclass field —
    /// read as a plain attribute (no parens). Same semantics as the
    /// existing `get_priority_player()` pymethod; this is the
    /// property-style alias.
    #[getter]
    fn priority_player_idx(&self) -> u8 {
        self.priority_player
    }

    /// Read the consecutive-pass counter. Round-27 G3 closure:
    /// `complete_step_via_priority_round` uses this to detect "both
    /// players have passed in succession". Exposed so tests can pin
    /// the counter's increment / reset behavior.
    fn get_consecutive_passes(&self) -> u8 {
        self.consecutive_passes
    }

    /// Pass priority to the other player. In the 2-player model
    /// this is a simple toggle (`1 - priority_player`). Returns the
    /// new priority-holder's id so callers can chain off the result
    /// without a follow-up `get_priority_player()` call.
    ///
    /// Note: this only moves `priority_player`; `active_player`
    /// stays put. Active-player rotation is the job of the
    /// turn-rollover path in `state_ops_steps.rs:advance_phase`.
    ///
    /// **Round-27 G3 closure**: each `pass_priority` invocation bumps
    /// `consecutive_passes` by 1 (saturating, but practical use stays
    /// under 4). The composer `complete_step_via_priority_round`
    /// reads this counter to decide when to resolve / advance.
    /// Non-pass mutations (cast, activate, advance_phase) reset the
    /// counter to 0.
    fn pass_priority(&mut self) -> u8 {
        self.priority_player = 1 - self.priority_player;
        self.consecutive_passes = self.consecutive_passes.saturating_add(1);
        self.priority_player
    }

    /// Direct priority setter for tests / fast-forward scenarios.
    /// Validates the player_id is in {0, 1}; raises `ValueError`
    /// otherwise rather than silently corrupting state.
    ///
    /// **Round-27 G3 closure**: an explicit priority assignment is
    /// NOT a "pass" event — it resets `consecutive_passes` to 0. The
    /// counter tracks ONLY consecutive `pass_priority` calls; any
    /// other priority-touching API breaks the streak.
    fn give_priority_to(&mut self, player_id: u8) -> PyResult<()> {
        if player_id > 1 {
            return Err(PyValueError::new_err(format!(
                "player_id out of range: {player_id} (must be 0 or 1)"
            )));
        }
        self.priority_player = player_id;
        self.consecutive_passes = 0;
        Ok(())
    }

    /// Round-9 priority + stack composition primitive.
    ///
    /// Caller signals "both players have consecutively passed
    /// priority" by invoking this method. Behavior:
    /// - **Empty stack** -> return `None`. No mutation. (CR 117.4
    ///   would end the current step here, but step-ending is the job
    ///   of `state_ops_steps.rs:advance_phase` — a future composition
    ///   slice wires these together.)
    /// - **Non-empty stack** -> pop the top item, reset
    ///   `priority_player` to `active_player` (CR 117.1c), and return
    ///   the popped item's dict (`{source_obj_id, controller}`).
    ///
    /// **This method does NOT dispatch effects.** Real MTG resolves
    /// the popped spell/ability's effects (deal damage, draw cards,
    /// etc.); this is a pop-only stepping-stone for the priority-
    /// round bookkeeping. Effect dispatch lives in
    /// `state_ops_resolve.rs:resolve_top_of_stack` — see the module
    /// docstring above for the cross-file-friction rationale and
    /// future-consolidation note.
    fn complete_priority_round<'py>(
        &mut self,
        py: Python<'py>,
    ) -> PyResult<Option<Bound<'py, PyDict>>> {
        // Empty stack -> None, no mutation. (Round-27 G3: the
        // step-end leg is handled by `complete_step_via_priority_round`;
        // this older primitive keeps its pop-only contract.)
        let Some(popped) = self.stack.pop() else {
            return Ok(None);
        };
        // CR 117.1c: AP gets priority after a spell or ability
        // resolves. (We're a stepping-stone: the "after resolves"
        // here is "after the top is popped"; a future slice that
        // adds effect dispatch keeps this same priority reset.)
        self.priority_player = self.active_player;
        // Round-27 G3: a stack-resolution event ends the current
        // priority round — the post-resolution priority round starts
        // fresh, so reset the consecutive-pass counter.
        self.consecutive_passes = 0;
        Ok(Some(stack_item_to_dict(py, &popped)?))
    }

    /// Round-27 G3 closure — the harness-facing step-completion composer.
    ///
    /// Implements the CR 117.4 / CR 117.5 / CR 117.1a + 1c routing:
    /// when both players have consecutively passed priority, EITHER
    /// the top of the stack resolves (non-empty stack) OR the current
    /// step ends (empty stack).
    ///
    /// **Operation**:
    /// 1. Call `pass_priority` twice (both players pass). After the
    ///    two calls, `consecutive_passes >= 2` and priority is back
    ///    where it started.
    /// 2. **Non-empty stack**: pop the top, reset
    ///    `priority_player = active_player` (CR 117.1c — AP gets
    ///    priority after the resolution), reset `consecutive_passes`
    ///    (the resolution event ends the priority round), and return
    ///    `False` to signal "step did not advance — more priority
    ///    rounds happen". The pop is the same pop-only stepping-stone
    ///    `complete_priority_round` exposes; real effect dispatch lives
    ///    in `state_ops_resolve.rs::resolve_top_of_stack` and is left
    ///    to the caller for now (same cross-file private-method friction
    ///    documented on `complete_priority_round`).
    /// 3. **Empty stack**: call `advance_phase` (which itself empties
    ///    mana pools, ticks the phase counter, fires the per-phase
    ///    side-effects, and resets priority to `active_player` on the
    ///    CLEANUP -> UNTAP wrap per G15). `advance_phase` resets
    ///    `consecutive_passes` to 0 as part of its non-pass-mutation
    ///    contract. Return `True` to signal "step advanced".
    ///
    /// **Returns** `true` when the step advanced (empty-stack leg);
    /// `false` when a stack item resolved instead (non-empty-stack
    /// leg). Callers running a priority loop can use this to decide
    /// whether to break out of the current step or keep running
    /// priority rounds.
    ///
    /// Mirrors Python's `simulate.py:priority_loop` logic (lines
    /// 245-280): when `pass_count >= alive_count()` with `state.stack`
    /// non-empty, call `resolve_top_of_stack` and reset
    /// `priority_idx = state.active_player_idx`; with empty stack,
    /// return (end-of-step). The Rust shape collapses that loop body
    /// into a single composer call.
    ///
    /// **Why `Bound<'_, Self>` rather than `&mut self`.** The
    /// empty-stack leg calls `advance_phase`, which lives in
    /// `state_ops_steps.rs`'s sibling `#[pymethods] impl GameState`
    /// block — private to that module per Rust's visibility rules.
    /// The cross-file pymethod dispatch pattern (established by
    /// `apply_action` in `state_ops_actions.rs`) goes through the
    /// Python attribute layer via `slf.call_method0("advance_phase")`,
    /// which requires `Bound<'_, Self>`. Same shape here.
    fn complete_step_via_priority_round(slf: Bound<'_, Self>) -> PyResult<bool> {
        // (1) Both players pass priority. We borrow + drop the mut
        //     borrow before re-entering Python via call_method0 below.
        {
            let mut state = slf.borrow_mut();
            let _ = state.pass_priority();
            let _ = state.pass_priority();
        }
        // After two passes in a 2-player game, priority is back where
        // it started AND consecutive_passes >= 2. The composer
        // doesn't re-check the counter — the contract is "the caller
        // is asserting both players have passed by invoking this
        // method", same shape as the existing `complete_priority_round`
        // contract.

        // (2) Stack-non-empty leg: resolve top, reset to AP, return
        //     false (no step advance).
        let stack_empty = slf.borrow().stack.is_empty();
        if !stack_empty {
            let mut state = slf.borrow_mut();
            // Inline the pop + reset (mirrors `complete_priority_round`'s
            // pop-only stepping-stone shape — real effect dispatch is
            // out of this slice's scope per the cross-file
            // private-method friction note).
            let _popped = state.stack.pop();
            state.priority_player = state.active_player;
            state.consecutive_passes = 0;
            return Ok(false);
        }

        // (3) Empty-stack leg: advance the phase. `advance_phase`
        //     handles the mana-empty, the per-phase hooks, the
        //     CLEANUP -> UNTAP wrap (with the G15 priority reset), and
        //     resets `consecutive_passes` to 0 itself.
        slf.call_method0("advance_phase")?;
        Ok(true)
    }
}
