//! `legal_decisions(player_id) -> list[Action]` enumerator.
//!
//! The Phase 3 keystone: emits the closed set of legal Actions the
//! priority-holder can take right now. Python's MCTS / ISMCTS drives
//! off this enumeration; Rust must match Python's emission order
//! exactly (Action types + per-type inner ordering) for trajectory
//! parity in `scripts/parity_smoke.py`.
//!
//! ## Emission-order audit vs Python's `legal_actions`
//!
//! Python's `src/mtg_bot/legal.py:legal_actions(state, player_id)` is
//! the source of truth. The relevant line ranges this slice mirrors:
//!
//! - **Line 178**: `actions: list[Action] = [PassPriority()]` —
//!   PassPriority is the FIRST element, prepended before any other
//!   variant. Future slices that grow the enumerator must keep
//!   PassPriority at index 0; the task brief's "PassPriority is last"
//!   wording is incorrect — the Python source has it first, and
//!   parity is bit-for-bit relative to Python.
//! - **Line 180-181**: `if not _has_priority(state, player_id):
//!   return actions` — the priority gate. Only the priority holder
//!   gets a non-trivial list; off-priority callers see
//!   `[PassPriority()]` and bail.
//! - **Lines 21-22**: `_has_priority` compares
//!   `state.players[state.priority_player_idx].id == player_id`. We
//!   use `state.priority_player == player_id` directly (Rust stores
//!   player ids equal to their indices in the 2-player model).
//! - **Lines 25-32**: `_is_sorcery_timing` — active player == priority
//!   player, current step is in `MAIN_STEPS`, stack is empty, AND
//!   priority is held. PlayLand only emits inside sorcery timing.
//! - **Line 303-304**: `if not _is_sorcery_timing(...): return actions`
//!   — after the (deferred) instant-speed cast block, Python bails
//!   if it isn't sorcery timing. First-slice's no-instant-casts world
//!   means we can short-circuit on this check at the top.
//! - **Lines 319-329**: PlayLand emission. `if p.lands_played_this_turn
//!   < max_lands: ... for card in p.hand: if card.printing.is_land:
//!   ... actions.append(PlayLand(card.id))`. Hand iteration order
//!   matches Python's, with a dedup by `(printing.name,)` key.
//!
//! ## Deliberate divergence: one-land-per-turn gate
//!
//! Python's line 319 reads `if p.lands_played_this_turn < max_lands`.
//! Rust's `GameState` has no `lands_played_this_turn` field today —
//! the parallel-slice file-isolation rule forbids adding it to
//! `state.rs` from this slice. First-slice behavior: emit a PlayLand
//! action for every Land in hand regardless of the per-turn limit.
//! Documented in `docs/SEARCH_LIMITATIONS.md`; caller / future slice
//! enforcement (either by adding the field + checking here, or by
//! re-checking via the underlying `play_land` primitive's mutation-
//! tracker) is the Phase 5 fix.
//!
//! ## Hand-card dedup by printing name (line 322-329)
//!
//! Two copies of the same printing in hand reach identical end-states
//! modulo the GameObject id (Python's invariant — see the long comment
//! at lines 220-229). The dedup key in Python is `(printing.name,)`;
//! mirroring that here makes the emission list collapse "two Forests"
//! to a single PlayLand action with the first hand-order Forest's id.

use crate::state::GameState;
use crate::state_ops_steps::{PHASE_MAIN1, PHASE_MAIN2};
use pyo3::exceptions::PyIndexError;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::collections::HashSet;

fn check_player_id(player_id: u8) -> PyResult<usize> {
    let idx = player_id as usize;
    if idx >= 2 {
        return Err(PyIndexError::new_err(format!(
            "player_id {player_id} out of range (must be 0 or 1)"
        )));
    }
    Ok(idx)
}

/// Build a `{"kind": "pass_priority"}` dict.
fn pass_priority_dict(py: Python<'_>) -> PyResult<Bound<'_, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("kind", "pass_priority")?;
    Ok(d)
}

/// Build a `{"kind": "play_land", "card_id": <id>}` dict.
fn play_land_dict(py: Python<'_>, card_id: u32) -> PyResult<Bound<'_, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("kind", "play_land")?;
    d.set_item("card_id", card_id)?;
    Ok(d)
}

#[pymethods]
impl GameState {
    /// Return the list of legal Actions for `player_id` at this
    /// priority moment. Mirrors Python's
    /// `src/mtg_bot/legal.py:legal_actions` emission order (lines
    /// 168-895) — same Action types in the same sequence with the
    /// same per-type tie-breaking, so Python search drivers (MCTS /
    /// ISMCTS) can be drop-in.
    ///
    /// **First-slice scope (rust(legal-decisions-skeleton)):**
    /// - `PassPriority` — always emitted at index 0 (Python's
    ///   `legal.py:178`).
    /// - `PlayLand` — one per Land in the priority player's hand,
    ///   under sorcery-timing gates (Python's `legal.py:319-329`),
    ///   deduped by printing name.
    ///
    /// `CastSpell`, `ActivateAbility`, `DeclareAttackers`,
    /// `DeclareBlockers` grow in follow-up slices as the Action enum
    /// + primitives mature.
    ///
    /// Returns a list of Action dicts (round-trip-able with
    /// `apply_action`). Raises `IndexError` on an out-of-range
    /// `player_id`.
    fn legal_decisions<'py>(
        &self,
        py: Python<'py>,
        player_id: u8,
    ) -> PyResult<Vec<Bound<'py, PyDict>>> {
        let idx = check_player_id(player_id)?;

        // Python line 178: actions: list[Action] = [PassPriority()]
        let mut actions: Vec<Bound<'py, PyDict>> = Vec::with_capacity(1);
        actions.push(pass_priority_dict(py)?);

        // Python lines 180-181: priority gate. Off-priority callers
        // bail with just the PassPriority action.
        if self.priority_player != player_id {
            return Ok(actions);
        }

        // Python's `_is_sorcery_timing` (lines 25-32):
        //   active == priority AND step in MAIN_STEPS AND stack
        //   empty AND _has_priority. Priority is already confirmed
        //   above; the remaining conjuncts gate the sorcery-speed
        //   block (PlayLand here, plus CastSpell / DeclareAttackers /
        //   ActivateAbility in future slices).
        //
        // First-slice short-circuit: there are no instant-speed
        // actions to emit yet, so if it isn't sorcery timing we
        // return early at this point — Python's instant-speed block
        // (lines 246-301) is a no-op in our world. When CastSpell
        // lands, this early-return shrinks to a `continue past
        // sorcery-only block`.
        let is_sorcery_timing = self.active_player == player_id
            && (self.phase == PHASE_MAIN1 || self.phase == PHASE_MAIN2)
            && self.stack.is_empty();
        if !is_sorcery_timing {
            return Ok(actions);
        }

        // Python lines 319-329: PlayLand emission.
        //
        // Python gates on `p.lands_played_this_turn < max_lands` —
        // Rust has no such field today (see module docstring's
        // "Deliberate divergence" section); skip the gate, emit for
        // every Land in hand.
        //
        // Hand iteration order: zone-insertion order (matches
        // Python's `for card in p.hand`). Dedup key:
        // `(printing.name,)` — two copies of the same printing
        // collapse to one action.
        let mut seen_playland: HashSet<&str> = HashSet::new();
        for obj in self.players[idx].hand.iter() {
            let Some(printing) = self.registry.lookup(obj.printing_id) else {
                continue;
            };
            // Land detection: card_types contains "Land". Mirrors
            // Python's `card.printing.is_land` property, which is a
            // thin wrapper over the same containment check.
            let is_land = printing
                .card_types
                .iter()
                .any(|t| t == "Land");
            if !is_land {
                continue;
            }
            // Dedup by printing name; emit the first hand-order copy.
            let name: &str = printing.name.as_ref();
            if seen_playland.contains(name) {
                continue;
            }
            seen_playland.insert(name);
            actions.push(play_land_dict(py, obj.id)?);
        }

        // PlayLand goes BEFORE PassPriority in Python's natural
        // append order — but Python prepends PassPriority at line
        // 178, so Python's final list shape is
        // `[PassPriority, PlayLand_1, PlayLand_2, ...]`. We match
        // that by pushing PassPriority first then PlayLands after.

        Ok(actions)
    }
}
