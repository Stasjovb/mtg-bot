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
//! Round 22 wired `PassPriority`; round 23 added `PlayLand` (10 of 420
//! decisions / ~2.4% in round-20's sample game — the 4th-most-frequent
//! variant), `DeclareAttackers` (16 of 420 / ~3.8% — the
//! 3rd-most-frequent variant), and `DeclareBlockers` (5 of 420 /
//! ~1.2% — the 4th-most-frequent non-pass variant). Future slices
//! grow the match arm (CastSpell, Activate, ...) plus a
//! `legal_decisions` enumerator and a `state.consecutive_passes`
//! field for the "both passed -> resolve / advance" composition.
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
//! ## Actor convention for combat actions
//!
//! `DeclareAttackers` is a combat-step action — it fires on the
//! active player's turn, not at an arbitrary priority moment. The
//! `declare_attacker` primitive (round 5) is `(&mut self, obj_id: u32)`:
//! it only takes the creature id and reads the owning player from the
//! battlefield index, so the dispatcher doesn't need to pass a
//! player_id parameter. The active-vs-priority distinction is moot
//! here for declaring attackers (only the active player can declare
//! attackers; priority is at the start of the declare-attackers step
//! when this fires), but the dispatch loop still iterates with the
//! Vec's stable order so callers can pin a deterministic application
//! order via sorting the set before passing.
//!
//! `DeclareBlockers` is symmetric: the round-5
//! `declare_blocker(blocker_id, attacker_id)` primitive takes only the
//! two object ids and reads the owning player from the battlefield
//! index, so the dispatcher doesn't pass a player_id either. The
//! dispatch loop iterates the `Vec<(u32, u32)>` of pairs in input
//! order — matters for damage assignment when multiple blockers
//! block the same attacker (the first declared blocker eats the
//! attacker's full damage under the round-5 single-blocker damage
//! model).
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
use pyo3::exceptions::PyValueError;
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
    /// - `{"kind": "declare_attackers", "attacker_ids": [<u32>, ...]}`
    ///   → iterates the Vec and calls
    ///   `declare_attacker(attacker_id)` once per id (round 23).
    ///   Ineligible ids are silently rejected by the primitive's
    ///   `bool` return — mirrors Python's `_declare_attackers`
    ///   filtering behavior.
    /// - `{"kind": "declare_blockers", "assignments":
    ///   [(<u32>, <u32>), ...]}` → iterates the Vec of pairs and calls
    ///   `declare_blocker(blocker_id, attacker_id)` once per pair in
    ///   input order (round 23). Ineligible pairs are silently
    ///   rejected by the primitive's `bool` return.
    /// - `{"kind": "activate_ability", "source_id": <u32>,
    ///   "ability_index": <u32>}` → STUB. The variant + bridge round-
    ///   trip ship in round 23, but no Rust `activate_ability`
    ///   primitive exists yet (rounds 1-22 didn't build one), so the
    ///   dispatch arm raises `ValueError` with a "not implemented
    ///   yet" message. A future slice adds the primitive and flips
    ///   the arm to a real `call_method1("activate_ability",
    ///   (source_id, ability_index))` dispatch.
    /// - `{"kind": "cast_spell", "card_id": <u32>, "use_warp":
    ///   <bool>?, "kicked": <bool>?, "cast_for_free": <bool>?,
    ///   "use_impending": <bool>?, "cast_room_half": <str|None>?}`
    ///   → calls `cast_creature(card_id, priority_player)`. The 5
    ///   alt-cost / mode flags are parsed as data and ROUND-TRIP
    ///   through the bridge but are IGNORED by this dispatch arm
    ///   (first-slice scope, mirrors the ActivateAbility "scaffold
    ///   the variant, defer the dispatch semantics" pattern — see
    ///   the `Action::CastSpell` arm's inline comment for the
    ///   future-slice plumbing of warp / kicker / impending /
    ///   cast_for_free / cast_room_half).
    ///
    /// Unknown `kind` raises `ValueError`; missing `kind` or other
    /// required keys (e.g. `card_id` for `play_land`,
    /// `attacker_ids` for `declare_attackers`, `assignments` for
    /// `declare_blockers`, `source_id` / `ability_index` for
    /// `activate_ability`) raise `KeyError`. Both bubble up from
    /// `actions::parse_action`.
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
            Action::DeclareAttackers { attacker_ids } => {
                // Same cross-file pattern as `play_land`: iterate the
                // Vec and dispatch one `declare_attacker(obj_id)` call
                // per id. The primitive takes only the creature id
                // (not a player_id) — it reads the owning player from
                // the battlefield index, so the dispatcher doesn't
                // need to pre-resolve an actor here. Ineligible ids
                // (tapped, non-creature, summoning-sick without haste,
                // defender, etc.) are silently rejected by the
                // primitive's `bool` return; we discard the bool to
                // match Python's `_declare_attackers` filtering
                // behavior (the eligible-set filter on the Python side
                // is implicit here via the primitive's per-id gate).
                //
                // Iteration order is the Vec's order — stable from
                // parse_action's `extract::<Vec<u32>>()`, which
                // preserves the Python iterable's iteration order.
                // Callers that want a canonical order sort the set
                // before passing (the parity harness does this).
                for attacker_id in attacker_ids {
                    slf.call_method1("declare_attacker", (attacker_id,))?;
                }
            }
            Action::DeclareBlockers { assignments } => {
                // Same cross-file pattern: iterate the `Vec<(u32, u32)>`
                // of `(blocker_id, attacker_id)` pairs and dispatch one
                // `declare_blocker(blocker_id, attacker_id)` per pair.
                // The primitive takes both ids (not a player_id) — it
                // reads the owning player from the battlefield index,
                // so the dispatcher doesn't pre-resolve an actor here.
                // Ineligible pairs (tapped blocker, non-creature
                // blocker, attacker not in `state.attackers`, flying/
                // skulk gate failure, unknown ids) are silently
                // rejected by the primitive's `bool` return; we
                // discard the bool to match the silent-skip behavior
                // of the `DeclareAttackers` arm above.
                //
                // Iteration order is the Vec's order — stable from
                // `parse_action`'s `try_iter` + per-element extract,
                // which preserves the Python iterable's iteration
                // order. Order matters: when multiple blockers block
                // the same attacker, the round-5 combat-damage model
                // assigns the attacker's power to the first declared
                // blocker for that attacker.
                for (blocker_id, attacker_id) in assignments {
                    slf.call_method1("declare_blocker", (blocker_id, attacker_id))?;
                }
            }
            Action::CastSpell {
                card_id,
                use_warp: _,
                kicked: _,
                cast_for_free: _,
                use_impending: _,
                cast_room_half: _,
            } => {
                // Round-23(+) slice: ship the `CastSpell` variant +
                // bridge with all 5 alt-cost / mode flags as data;
                // dispatch IGNORES the flags and routes to the
                // existing round-4 `cast_creature(obj_id, player_id)`
                // primitive. Same pattern as `play_land` for the
                // actor resolution (the Python `CastSpell` dataclass
                // carries only `card_id`; the implicit actor is the
                // priority player). Borrow `slf` for the u8 read,
                // then drop the borrow before re-entering Python via
                // `call_method1` (which would re-borrow under the
                // hood).
                //
                // **Flags are silently ignored for first-slice.**
                // Mirrors the round-23 ActivateAbility "scaffold the
                // variant, defer the dispatch semantics" pattern —
                // search-loop dispatch can already drive Rust state
                // through the production `CastSpell` dict shape
                // (warp / kicker / impending / Room-half / free-cast
                // payloads round-trip losslessly through the
                // bridge), and a future slice wires each flag
                // through to a richer primitive:
                //   - use_warp -> alt-cost from exile (needs
                //     Effect::Warp + the cost-from-zone primitive).
                //   - kicked -> additional mana cost stacked on the
                //     base (needs cost-stacking infrastructure).
                //   - cast_for_free -> bypass the mana payment in
                //     `cast_creature`'s phase 2.
                //   - use_impending -> defer creature-ness via time
                //     counters + the new face-down-ish state field.
                //   - cast_room_half -> route to the picked Room
                //     half's mana cost + unlock effect.
                // No runtime warning when a non-default flag is set
                // — the test suite covers the "flags pass through
                // silently" contract (search-loop callers shouldn't
                // see ergonomic noise from the deferred-semantics
                // gap; the gap is documented here + in the variant
                // docstring + in the porting-status table).
                let player_id = slf.borrow().priority_player;
                slf.call_method1("cast_creature", (card_id, player_id))?;
            }
            Action::TurnFaceUp { card_id: _ } => {
                // First-slice scope (mirrors round-23's ActivateAbility
                // pattern): ship the Action variant + bridge round-trip
                // scaffold; the dispatch arm is a stub because no Rust
                // face-down GameObject state exists yet. The
                // `GameObject` struct has no `face_down` flag today, and
                // there's no Spacecraft charge-counter resolution
                // primitive — there's nothing for a `turn_face_up`
                // dispatch to flip. A future slice adds the per-object
                // face-down state field + flip primitive (analogous to
                // how `tap` / `untap` toggle the `tapped` flag) and then
                // flips this arm to a real `call_method1(
                // "turn_face_up", (card_id, priority_player))` dispatch
                // — at which point the variant + bridge already shipped
                // here keep working unchanged. The variant ships now so
                // callers building Action dicts can already use the
                // `turn_face_up` shape and hit a clear "not implemented
                // yet" error path instead of `unknown action kind`,
                // and the parity harness surfaces the gap loudly when
                // Python emits a TurnFaceUp decision (CR 701.34 /
                // 707.4 — EoE Spacecraft station+launch is the
                // production driver).
                return Err(pyo3::exceptions::PyValueError::new_err(
                    "TurnFaceUp dispatch not implemented yet (Rust face-down \
                     GameObject state + Spacecraft primitive missing; future \
                     slice flips the dispatch). This slice ships only the \
                     Action variant + bridge round-trip — apply_action raises \
                     to surface the gap loudly to the parity harness."
                ));
            }
            Action::ActivateAbility {
                source_id: _,
                ability_index: _,
            } => {
                // Round-23 slice ships the Action variant + bridge
                // (parse_action + action_to_pydict) round-trip
                // scaffold; the dispatch arm is a stub because no
                // Rust `activate_ability` primitive exists yet.
                // Grep across `rust/src/` confirms rounds 1-22 didn't
                // build one — the mana-cost-pay + ability-resolution
                // flow (analogous to how `play_land` and
                // `cast_creature` already handle their costs) is the
                // missing primitive. A future slice adds that
                // primitive then flips this arm to a real
                // `call_method1("activate_ability", (source_id,
                // ability_index))` dispatch — at which point the
                // variant + bridge already shipped here keep working
                // unchanged. Round-20 frequency: 8 of 420 decisions
                // (~1.9%) — worth a real implementation in a future
                // slice, but worth shipping the scaffold now so
                // callers building Action dicts can already build the
                // `activate_ability` shape and hit a clear error path
                // instead of `unknown action kind`.
                return Err(PyValueError::new_err(
                    "ActivateAbility dispatch not implemented yet \
                     (round 24+ — Rust primitive missing; this slice \
                     ships the Action variant scaffold + bridge \
                     round-trip only)",
                ));
            }
        }
        Ok(())
    }
}
