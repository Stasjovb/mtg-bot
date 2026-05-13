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
use std::sync::Arc;

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
    /// - `{"kind": "pass_priority"}` → **no-op** (CE2 closure).
    ///   Mirrors Python's `apply_action(PassPriority)` which is a
    ///   pure `return` — priority management is owned by the
    ///   composer (`complete_step_via_priority_round`) and by the
    ///   `pass_priority` primitive when called directly, NOT by
    ///   `apply_action`. The `consecutive_passes` counter is NOT
    ///   incremented here (the counter only advances when callers
    ///   invoke the primitive directly or the composer). See the
    ///   inline arm comment + invariant I25 in
    ///   `docs/RUST_PARITY_GAPS.md` for the full rationale.
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
    ///   "ability_index": <u32>}` → mana-ability dispatch (round 25).
    ///   For `ability_index = 0` on an untapped battlefield permanent
    ///   whose printing has `mana_produced.is_some()`, taps the
    ///   source and credits the controller's mana pool with the
    ///   pips listed in `mana_produced` (one per element, saturating
    ///   at u8::MAX per color). Mirrors the legal_decisions emission
    ///   gate (round 24, `state_ops_legal.rs`) which only emits this
    ///   shape for the same predicate. Raises `ValueError` if
    ///   `ability_index != 0`, the source isn't on any battlefield,
    ///   the source is already tapped, the source is
    ///   summoning-sick (CR 302.1 — closes parity gap G6), or the
    ///   printing has no `mana_produced` (non-mana activated
    ///   abilities are a future-slice scope — they need richer
    ///   cost-pay + effect-resolution primitives).
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
        // Round-27 G3 closure: every non-PassPriority arm is a
        // priority-round-breaking mutation — record up front whether
        // we'll need to reset `consecutive_passes` and (for the
        // CR 117.1c "AP gets priority after a spell is cast / ability
        // resolves" rule) `priority_player = active_player` after a
        // successful dispatch.
        //
        // PassPriority itself is a NO-OP (CE2 closure). It does NOT
        // touch `priority_player`, and it does NOT increment
        // `consecutive_passes`. The counter only advances when
        // callers invoke the `pass_priority` primitive directly OR
        // when the `complete_step_via_priority_round` composer drives
        // it. This mirrors Python's `apply_action(PassPriority)`
        // which is a pure `return` (actions.py:990-991) — priority
        // management is owned by `simulate.priority_loop`, not by
        // `apply_action`.
        //
        // Stubs that always raise (TurnFaceUp / UnlockRoomHalf /
        // ActivateStation) never reach the post-arm reset because
        // they short-circuit with `?` propagation.
        let is_pass_priority = matches!(action, Action::PassPriority);
        match action {
            Action::PassPriority => {
                // CE2 closure: TRUE NO-OP. Matches Python's
                // `apply_action(PassPriority)` which is literally
                // `return` (src/mtg_bot/actions.py:990-991). The
                // `is_pass_priority` flag suppresses the post-arm
                // reset block below, so this arm leaves
                // `priority_player`, `active_player`, AND
                // `consecutive_passes` untouched. The composer
                // (`complete_step_via_priority_round`) is the
                // priority-management entrypoint that drives the
                // underlying `pass_priority` primitive — and that
                // primitive (not this arm) is the place where the
                // counter advances. See invariant I25 in
                // `docs/RUST_PARITY_GAPS.md`.
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
                //
                // CE16 closure (Phase 5 follow-up #15): after the
                // per-pair `declare_blocker` loop, post-validate each
                // attacker's block assignment via
                // `is_legal_block_assignment` (defined in
                // `state_ops_combat.rs:779-789`). Illegal final
                // assignments — today, only menace attackers with
                // exactly one blocker (CR 702.110b) — are silently
                // dropped from `state.blockers` via `.retain`, mirroring
                // Python's `actions.py:2555-2566` `validated.pop(...)`
                // post-validation pass. The attacker proceeds as if
                // unblocked; combat damage hits the defender. We
                // collect the unique attacker ids from the just-pushed
                // assignments (the dispatch only changes blocks for
                // attackers it touches — leaving pre-existing legal
                // blocks for OTHER attackers alone), then for each
                // failing attacker call `.retain` on `state.blockers`
                // to unwind its blocker entries. Order of the retain
                // walk doesn't matter — `is_legal_block_assignment`
                // is read-only on `state.blockers`, and we collect
                // the failing-attacker set BEFORE mutating.
                let mut unique_attackers: Vec<u32> = Vec::new();
                for (_, attacker_id) in &assignments {
                    if !unique_attackers.contains(attacker_id) {
                        unique_attackers.push(*attacker_id);
                    }
                }
                for (blocker_id, attacker_id) in assignments {
                    slf.call_method1("declare_blocker", (blocker_id, attacker_id))?;
                }
                // Identify attackers whose final assignment is illegal
                // (read-only predicate call), then prune.
                let illegal: Vec<u32> = {
                    let state = slf.borrow();
                    unique_attackers
                        .into_iter()
                        .filter(|aid| !state.is_legal_block_assignment(*aid))
                        .collect()
                };
                if !illegal.is_empty() {
                    let mut state = slf.borrow_mut();
                    state
                        .blockers
                        .retain(|(a, _)| !illegal.contains(a));
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
            Action::UnlockRoomHalf {
                card_id: _,
                half_name: _,
            } => {
                // First-slice scope (mirrors round-23's ActivateAbility
                // and round-24's TurnFaceUp pattern): ship the Action
                // variant + bridge round-trip scaffold; the dispatch arm
                // is a stub because no Rust Room-half state exists yet.
                // Python's `GameObject` carries a per-Room
                // `unlocked_halves: set[str]` field that tracks which
                // halves of a Room enchantment have been unlocked — the
                // Rust `GameObject` struct has no such field today, and
                // there's no half-specific effect activation primitive.
                // A future slice adds the per-object Room state +
                // `unlock_room_half(card_id, half_name)` primitive
                // (analogous to how Python's `_unlock_room_half`
                // mutates the set, pays the half's mana cost, and fires
                // the half-specific ENTERS triggers) and then flips
                // this arm to a real `call_method1("unlock_room_half",
                // (card_id, half_name, priority_player))` dispatch —
                // at which point the variant + bridge already shipped
                // here keep working unchanged. The variant ships now so
                // callers building Action dicts can already use the
                // `unlock_room_half` shape and hit a clear "not
                // implemented yet" error path instead of `unknown
                // action kind`, and the parity harness surfaces the
                // gap loudly when Python emits an UnlockRoomHalf
                // decision (CR 715.3-4 — DSK Rooms mechanic is the
                // production driver).
                return Err(pyo3::exceptions::PyValueError::new_err(
                    "UnlockRoomHalf dispatch not implemented yet (Rust Room \
                     enchantment state + half-name resolution missing; future \
                     slice flips the dispatch). This slice ships only the \
                     Action variant + bridge round-trip."
                ));
            }
            Action::ActivateStation {
                spacecraft_id: _,
                crew_id: _,
            } => {
                // First-slice scope (mirrors round-23's ActivateAbility
                // and round-24's TurnFaceUp / UnlockRoomHalf pattern):
                // ship the Action variant + bridge round-trip scaffold;
                // the dispatch arm is a stub because no Rust Spacecraft
                // charge-counter state / crew-tap resolution primitive
                // exists yet. Python's `_activate_station` taps the crew
                // creature (cost), reads its power, and adds that many
                // charge counters to the Spacecraft (effect) — Rust has
                // neither the Spacecraft state field for charge counters
                // nor a primitive that links tap-as-cost to counter-add-
                // as-effect. A future slice adds the per-object
                // Spacecraft charge state + the activate-station
                // primitive (analogous to how Python's
                // `_activate_station` mutates both sides atomically) and
                // then flips this arm to a real `call_method1(
                // "activate_station", (spacecraft_id, crew_id,
                // priority_player))` dispatch — at which point the
                // variant + bridge already shipped here keep working
                // unchanged. The variant ships now so callers building
                // Action dicts can already use the `activate_station`
                // shape and hit a clear "not implemented yet" error
                // path instead of `unknown action kind`, and the parity
                // harness surfaces the gap loudly when Python emits an
                // ActivateStation decision (EoE Spacecraft station
                // mechanic — the EoE Spacecraft cycle is the production
                // driver). **This completes the Action enum scaffold:
                // all 8 Python Action subclasses now have Rust
                // variants.**
                return Err(pyo3::exceptions::PyValueError::new_err(
                    "ActivateStation dispatch not implemented yet (Rust \
                     Spacecraft charge-counter state + crew-tap resolution \
                     missing; future slice flips the dispatch). This slice \
                     ships only the Action variant + bridge round-trip."
                ));
            }
            Action::ActivateAbility {
                source_id,
                ability_index,
            } => {
                // CE20 Slice 1 + bridge follow-up dispatch: single
                // unified path through `printing.activated_abilities`.
                // The bridge synthesis in `cards.rs::parse_printing`
                // pre-populates a free mana-ability entry at
                // `ability_index = 0` for every printing with
                // `mana_produced.is_some()`, so the dispatch arm no
                // longer needs a separate `mana_produced` fallback.
                // Mirrors Python's `actions._activate_ability` at
                // `src/mtg_bot/actions.py:1928-2002`:
                //
                //   1. Locate the source on a battlefield.
                //   2. Resolve the ability: dispatch into
                //      `printing.activated_abilities[ability_index]`
                //      (loud raise on out-of-range index).
                //   3. Cost-pay phase: check tap-self gate (untapped
                //      + non-sick for creatures) + mana affordability,
                //      then commit (tap source, debit pool).
                //   4. Effect phase: `is_mana_ability=true` →
                //      `apply_effect` directly (CR 605.3a — mana
                //      abilities bypass the stack); `is_mana_ability=false`
                //      → push a `StackItem::new_trigger`-shaped slot
                //      so the next `resolve_top_of_stack` fires it.
                let mut binding = slf.borrow_mut();
                let state: &mut GameState = &mut *binding;
                // Phase 1: locate the source on a battlefield (either
                // player's — `legal_decisions` only emits for the
                // priority player but the dispatcher is permissive so
                // a direct hand-built caller gets the same error
                // shape regardless of which side controls the source).
                let mut found: Option<(usize, usize, u32)> = None;
                // (controller_idx, bf_pos, printing_id)
                for pidx in 0..state.players.len() {
                    if let Some(pos) = state.players[pidx]
                        .battlefield
                        .iter()
                        .position(|o| o.id == source_id)
                    {
                        let printing_id = state.players[pidx].battlefield[pos].printing_id;
                        found = Some((pidx, pos, printing_id));
                        break;
                    }
                }
                let (controller_idx, bf_pos, printing_id) = match found {
                    Some(t) => t,
                    None => {
                        return Err(PyValueError::new_err(format!(
                            "ActivateAbility: source {source_id} not on any \
                             battlefield"
                        )))
                    }
                };
                // Phase 2: resolve the ability shape. We snapshot
                // everything we need from the immutable registry view
                // up-front so the mutation phases below can borrow
                // `state.players[...]` freely.
                #[derive(Debug)]
                struct ResolvedAbility {
                    /// Mana to spend from the controller's pool.
                    mana_cost: crate::cards::ManaCost,
                    /// Tap the source as part of cost?
                    tap_self: bool,
                    /// Sacrifice the source as part of cost
                    /// (CE20 follow-up Slice 2)?
                    sacrifice_self: bool,
                    /// Effect to fire on resolution.
                    effect: crate::cards::Effect,
                    /// Mana ability (CR 605.3a — bypass stack)?
                    is_mana_ability: bool,
                    /// Whether the source's printing has the "Creature"
                    /// card_type — gated below by summoning sickness
                    /// when combined with `tap_self`.
                    is_creature: bool,
                    /// Minimum `GameObject.charge_counters` the source
                    /// must have to be eligible (CE20 follow-up Slice 3
                    /// Spacecraft station-charge). 0 = no gate.
                    tier_threshold: i32,
                }
                let resolved: ResolvedAbility = {
                    let printing = state.registry.lookup(printing_id).ok_or_else(|| {
                        PyValueError::new_err(format!(
                            "ActivateAbility: source {source_id} printing \
                             not in registry"
                        ))
                    })?;
                    let is_creature =
                        printing.card_types.iter().any(|t| t == "Creature");
                    // Bridge follow-up: the legacy `mana_produced`
                    // side-channel has been retired — every printing
                    // with `mana_produced.is_some()` carries a
                    // synthesized ActivatedAbility at ability_index=0
                    // (see `cards.rs::parse_printing` bridge synthesis).
                    // ability_index must fall inside the
                    // activated_abilities Vec.
                    if (ability_index as usize) < printing.activated_abilities.len() {
                        let ab = &printing.activated_abilities[ability_index as usize];
                        ResolvedAbility {
                            mana_cost: ab.cost.mana.clone(),
                            tap_self: ab.cost.tap_self,
                            sacrifice_self: ab.cost.sacrifice_self,
                            effect: ab.effect.clone(),
                            is_mana_ability: ab.is_mana_ability,
                            is_creature,
                            tier_threshold: ab.tier_threshold,
                        }
                    } else {
                        // ability_index out of range. Loud fail —
                        // the emission gate in legal_decisions never
                        // produces this shape; a direct caller built
                        // a malformed dict.
                        return Err(PyValueError::new_err(format!(
                            "ActivateAbility: source {source_id} has no \
                             ability at index {ability_index} \
                             (printing has {} activated_abilities)",
                            printing.activated_abilities.len(),
                        )));
                    }
                };
                // Phase 3a: CE20 follow-up Slice 3 tier gate. The
                // source must have at least `tier_threshold` charge
                // counters for the ability to be usable. This is a
                // usability gate (NOT a cost) — failing the gate
                // raises BEFORE any mana / tap / sacrifice commit.
                // Mirrors the emission filter's tier check at
                // `state_ops_legal.rs` so a direct (bypass-emission)
                // caller gets the same rejection shape.
                if resolved.tier_threshold > 0 {
                    let obj = &state.players[controller_idx].battlefield[bf_pos];
                    if obj.charge_counters < resolved.tier_threshold {
                        return Err(PyValueError::new_err(format!(
                            "ActivateAbility: source {source_id} below \
                             tier threshold (charge_counters={} < \
                             tier_threshold={})",
                            obj.charge_counters, resolved.tier_threshold,
                        )));
                    }
                }
                // Phase 3: cost-pay precheck. tap_self requires the
                // source untapped and non-sick (creature-only —
                // CR 302.1, see I17).
                if resolved.tap_self {
                    let obj = &state.players[controller_idx].battlefield[bf_pos];
                    if obj.tapped {
                        return Err(PyValueError::new_err(format!(
                            "ActivateAbility: source {source_id} is \
                             already tapped (tap_self cost can't be paid)"
                        )));
                    }
                    if resolved.is_creature && obj.summoning_sick {
                        return Err(PyValueError::new_err(format!(
                            "ActivateAbility: source {source_id} is \
                             summoning-sick (CR 302.1) — can't pay \
                             tap_self cost the turn it entered the \
                             battlefield"
                        )));
                    }
                }
                // Phase 4: pay the mana cost (if any). pay_mana_cost
                // on the controller's pool either succeeds (commits)
                // or returns false with no mutation. Mirrors the
                // affordability shape Python's `auto_tap_for_cost`
                // checks before committing — but unlike Python,
                // Rust's pool is the SOLE mana source for cost-pay
                // (no auto-tap-from-lands fallback yet); the caller
                // is responsible for pre-populating the pool from
                // their lands. A future slice can grow an auto-tap
                // composer that mirrors the Python pipeline.
                let mana_paid: bool = {
                    let pool = &mut state.players[controller_idx].mana_pool;
                    crate::state_ops_cast::pay_mana_cost_pub(pool, &resolved.mana_cost)
                };
                if !mana_paid {
                    return Err(PyValueError::new_err(format!(
                        "ActivateAbility: source {source_id} cost is \
                         unaffordable from controller's mana pool \
                         (mana_cost generic={}, W={}, U={}, B={}, R={}, G={})",
                        resolved.mana_cost.generic,
                        resolved.mana_cost.white,
                        resolved.mana_cost.blue,
                        resolved.mana_cost.black,
                        resolved.mana_cost.red,
                        resolved.mana_cost.green,
                    )));
                }
                // Phase 5: commit tap_self (if applicable). The mana
                // cost is already debited above.
                if resolved.tap_self {
                    let bf_mut = Arc::make_mut(
                        &mut state.players[controller_idx].battlefield,
                    );
                    bf_mut[bf_pos].tapped = true;
                }
                // Phase 5b: commit sacrifice_self (CE20 follow-up
                // Slice 2). Costs pay BEFORE effect resolves (CR
                // 117.10 / 119) — the source moves to its
                // controller's graveyard now, and the effect
                // dispatched below in Phase 6 fires with the source
                // already off the battlefield.
                //
                // **Source-cleanup shape.** Mirrors
                // `Effect::Sacrifice` at `state_ops_resolve.rs:1061`
                // (TargetFilter::AnyCreature variant): zero damage +
                // counters + attached_to + exiled_with_source on
                // the way out; preserve `summoning_sick` per the
                // CE13 I35 closure (sickness is battlefield-only
                // state, but the field stays as-is in the
                // graveyard for off-bf bookkeeping). LTB void-flag
                // (CE13 / I29) stamps via
                // `mark_left_battlefield_if_nonland`.
                //
                // **Self-ETB triggers do NOT fire on sacrifice** —
                // ETB and LTB are distinct events. The dispatch
                // event we care about post-sacrifice is `Dies` (for
                // creatures) or `Leaves` more broadly; ETB-Slice-5
                // landed `Event::Dies` on the SBA-destroy site
                // (commit 2fd9aa31). Routing the sacrifice through
                // `dispatch_event(Event::Dies, ...)` is out of scope
                // of this slice — the Phase 5b commit only moves
                // the object; trigger fan-out lives in a future
                // slice that wires Dies into the sacrifice-cost
                // path.
                if resolved.sacrifice_self {
                    let bf_mut = Arc::make_mut(
                        &mut state.players[controller_idx].battlefield,
                    );
                    // Defensive: bf_pos was captured before any
                    // mutation; tap_self commit above didn't change
                    // the Vec layout, so bf_pos is still valid.
                    let mut obj = bf_mut.remove(bf_pos);
                    obj.zone = crate::state_ops_zones::ZONE_GRAVEYARD;
                    obj.tapped = false;
                    // CE13 I35: summoning_sick stays as-is.
                    obj.damage = 0;
                    obj.counters = 0;
                    obj.attached_to = None;
                    obj.exiled_with_source = None;
                    let sac_printing_id = obj.printing_id;
                    let sac_obj_id = obj.id;
                    Arc::make_mut(
                        &mut state.players[controller_idx].graveyard,
                    )
                    .push(obj);
                    // CE13 / I29: stamp the LTB void flag for nonland
                    // permanents leaving the battlefield. Same
                    // primitive every other bf-exit uses; the cost
                    // path doesn't bypass it.
                    crate::state_ops_zones::mark_left_battlefield_if_nonland(
                        state,
                        sac_printing_id,
                    );
                    // Slice 10: LTB fan-out at the sacrifice-cost
                    // bf-exit. Mirrors the Effect-arm bf-exit pattern
                    // in state_ops_resolve.rs: queue the sac'd id
                    // and drain so the LEAVES trigger lands on the
                    // stack before the cost-pay phase returns.
                    state.pending_leaves_dispatches.push(sac_obj_id);
                    crate::state_ops_resolve::drain_pending_leaves_dispatches(
                        state,
                    )?;
                }
                // Phase 6: dispatch the effect.
                if resolved.is_mana_ability {
                    // New-substrate mana ability: bypass the stack
                    // and resolve immediately (CR 605.3a).
                    //
                    // **Controller-of-effect contract.** Mana abilities
                    // credit the SOURCE'S CONTROLLER's pool, not
                    // `state.active_player`'s — a Forest on player 1's
                    // bf activated during player 0's turn must add G
                    // to player 1's pool. `apply_effect_pub` for
                    // `AddManaToPool` reads `state.active_player` as
                    // the implicit controller (CE20-substrate-shape;
                    // every other apply_effect arm does the same), so
                    // we temporarily swap `active_player` to the
                    // source's controller for the duration of the
                    // mana-ability dispatch. This is the bridge
                    // follow-up's parity fix — the pre-bridge legacy
                    // path explicitly debited `controller_idx`; the
                    // post-bridge new path inherits the same semantics
                    // via the swap. Restored after the apply.
                    //
                    // Safe vs other-side-effects: a mana ability is
                    // CR 605.1 "produces mana, doesn't target", so
                    // its effect is exclusively `AddManaToPool` or
                    // (rarely) a Sequence of them. Other arms of
                    // `apply_effect` that read `state.active_player`
                    // for non-mana purposes (PumpCreaturesYouControl,
                    // DealDamage, etc.) are NOT reachable via a
                    // mana ability — registry-input validation would
                    // mark them as non-mana abilities, and the
                    // synthetic state's bridge synthesis only ever
                    // produces AddManaToPool / Sequence(AddManaToPool).
                    let saved_active = state.active_player;
                    state.active_player = controller_idx as u8;
                    let dispatch_result = crate::state_ops_resolve::apply_effect_pub(
                        state,
                        &resolved.effect,
                        source_id,
                    );
                    state.active_player = saved_active;
                    dispatch_result?;
                } else {
                    // Non-mana ability: push a stack item carrying
                    // the effect payload so a subsequent
                    // `resolve_top_of_stack` fires it (CR 605 /
                    // 113.3b — non-mana activated abilities use the
                    // stack). Mirrors Python's `_activate_ability`
                    // stack push at `actions.py:1928-2002`. We use
                    // the existing `new_trigger` shape (it's the
                    // closest payload-carrying StackItem variant; the
                    // resolver fires it via `apply_effect` and
                    // skips `move_source_post_resolve`, exactly the
                    // semantics we want for an activated ability).
                    // `ability_index` rides through as the payload's
                    // dedup key — matches what Python's
                    // `StackItem.ability` reference encodes.
                    let controller = controller_idx as u8;
                    state.stack.push(crate::state::StackItem::new_trigger(
                        source_id,
                        controller,
                        resolved.effect.clone(),
                        ability_index,
                    ));
                }
                // Round-27 G4 closure: priority reset after the
                // activate happens at the post-arm reset block
                // (below) — same shape as every other non-pass arm.
            }
        }
        // Round-27 G3 + G4 post-arm reset (CR 117.1c).
        //
        // After any non-PassPriority action successfully dispatches,
        // the priority round it interrupted ends:
        //
        //  - `priority_player` resets to `active_player` (CR 117.1c
        //    — AP gets priority after a spell is cast or an ability
        //    resolves; for non-spell actions like PlayLand /
        //    DeclareAttackers / DeclareBlockers the parity-load-bearing
        //    behavior is the same: priority returns to the active
        //    player after the action, mirroring Python
        //    `simulate.py:priority_loop` which sets
        //    `priority_idx = state.active_player_idx` after every
        //    non-pass branch).
        //
        //  - `consecutive_passes` resets to 0 — a non-pass mutation
        //    breaks any in-flight pass streak.
        //
        // Cast/activate also touched `priority_player` from inside
        // their respective primitive bodies (cast_creature) /
        // dispatch arm (ActivateAbility), which is harmless — the
        // post-arm reset writes the same value (AP) again. Keeping
        // the reset BOTH at the primitive layer AND here protects
        // direct-primitive callers (e.g. tests that call
        // `cast_creature` directly without going through
        // `apply_action`) from a missed reset.
        if !is_pass_priority {
            let mut state = slf.borrow_mut();
            state.priority_player = state.active_player;
            state.consecutive_passes = 0;
        }
        Ok(())
    }
}
