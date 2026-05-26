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

/// **Spacecraft Station substrate Phase 1 — Cycle 2 (substrate-only,
/// 2026-05-25).** Validate + apply a Station activation. Silently
/// no-ops on invalid inputs (crew tapped / summoning-sick / not own
/// / same id as Spacecraft / Spacecraft not own / spacecraft missing
/// / non-Spacecraft target / non-creature crew). Mirrors Python's
/// `_activate_station` silent-validate pattern at
/// `src/mtg_bot/actions.py:2353-2407`.
///
/// On success:
///   * `crew.tapped` flips to `true` (cost — tap the crew).
///   * `spacecraft.charge_counters += effective_power(crew)`
///     (effect — add power-many charge counters). The legal-action
///     emitter has already filtered eligible crew (non-tapped,
///     non-summoning-sick, own, non-self); the resolver re-validates
///     defensively because the emitter is not the only entry point
///     (the parity-replay harness drives `apply_action` from a
///     Python-derived dict — the resolver MUST be robust to a stale
///     id, mirroring Python's silent-no-op pattern).
///
/// **Phase 1 does NOT honor the
/// `grants_toughness_as_station_power_for_creatures_you_control`
/// flag** (Tapestry Warden's flag — Python at `actions.py:2393-2401`
/// consults it). Phase 1's admit predicate (Cycle 3) positively
/// rejects any Tapestry-Warden-style printing, so this asymmetry is
/// bench-invisible; SL §9 entry #2 pins it as a Phase-2+ widen.
///
/// **Phase 1 reader scope.** Cycle 2 ships the resolver + the
/// legal-action emitter that produces ActivateStation dicts. The
/// admit gate stays closed (Galvanizing Sawship STAYS DECLINED post-
/// C2 — Cycle 3 owns the inversion). The resolver is therefore
/// dead-relative-to-production this cycle; it powers the C2 unit
/// pins + lights up the moment C3 admits the Sawship.
fn apply_activate_station(
    state: &mut GameState,
    player_id: u8,
    spacecraft_id: u32,
    crew_id: u32,
) {
    // Silent no-op: same id (crew can't be the spacecraft itself).
    if spacecraft_id == crew_id {
        return;
    }
    // Locate spacecraft + crew on the battlefield (any player's bf —
    // gate on controller below). Record their player_idx so the
    // mutation path can pick the right Arc.
    let mut spacecraft_loc: Option<(usize, u32)> = None;
    let mut crew_loc: Option<(usize, u32)> = None;
    for (idx, player) in state.players.iter().enumerate() {
        for obj in player.battlefield.iter() {
            if obj.id == spacecraft_id {
                spacecraft_loc = Some((idx, obj.printing_id));
            }
            if obj.id == crew_id {
                crew_loc = Some((idx, obj.printing_id));
            }
        }
    }
    let Some((sp_idx, sp_pid)) = spacecraft_loc else {
        return;
    };
    let Some((cr_idx, cr_pid)) = crew_loc else {
        return;
    };
    // Spacecraft must be a Spacecraft (subtypes ∋ "Spacecraft").
    let Some(sp_printing) = state.registry.lookup(sp_pid) else {
        return;
    };
    if !sp_printing.subtypes.iter().any(|s| s == "Spacecraft") {
        return;
    }
    // Spacecraft + crew must be controlled by player_id.
    let sp_controller = state.players[sp_idx]
        .battlefield
        .iter()
        .find(|o| o.id == spacecraft_id)
        .map(|o| o.controller);
    let cr_controller = state.players[cr_idx]
        .battlefield
        .iter()
        .find(|o| o.id == crew_id)
        .map(|o| o.controller);
    if sp_controller != Some(player_id) || cr_controller != Some(player_id) {
        return;
    }
    // Crew must be a printed creature (a Spacecraft crewing another
    // Spacecraft is rejected per Python's `_activate_station`:
    // "spacecraft can't crew another spacecraft" — actions.py:2374-
    // 2375). Note Python keys on `crew.printing.is_creature` (the
    // printed flag), NOT `is_creature_now` — so a stationed
    // Spacecraft is NOT eligible to crew another Spacecraft. Rust
    // mirrors that strict printed-creature gate.
    let Some(cr_printing) = state.registry.lookup(cr_pid) else {
        return;
    };
    if !cr_printing.card_types.iter().any(|t| t == "Creature") {
        return;
    }
    // Crew must be untapped + not summoning-sick (tap-as-cost gate).
    let (crew_tapped, crew_sick) = match state.players[cr_idx]
        .battlefield
        .iter()
        .find(|o| o.id == crew_id)
        .map(|o| (o.tapped, o.summoning_sick))
    {
        Some(pair) => pair,
        None => return,
    };
    if crew_tapped || crew_sick {
        return;
    }
    // Effective power of the crew = printed power + counters +
    // ueot_power_bonus. Mirrors `legal_effective_power` at
    // `state_ops_legal.rs:472` and Python's
    // `effective_power(state, crew)` at `game.py:2138-2251`. Phase 1
    // does NOT honor the Tapestry-Warden toughness-substitution
    // (admit-time guard rejects that printing — SL §9 entry #2).
    let printed_base = cr_printing.power.unwrap_or(0) as i32;
    let crew_obj = state.players[cr_idx]
        .battlefield
        .iter()
        .find(|o| o.id == crew_id);
    let Some(crew_obj) = crew_obj else { return };
    let base = crew_obj
        .ueot_base_pt_override()
        .map(|(p, _)| p)
        .or_else(|| crew_obj.ueot_becomes_land_creature_pt().map(|(p, _)| p))
        .unwrap_or(printed_base);
    let crew_power = base + crew_obj.ueot_power_bonus() + crew_obj.counters;
    // Mutate: tap the crew, add charge counters to the spacecraft.
    // Two Arc::make_mut sites (one per controller's bf) — same
    // pattern as `state_ops_tap.rs::mutate_battlefield_obj`. The
    // crew-tap mutation goes through first, mirroring Python's
    // `tap_permanent(state, crew); add_charge_counters(state,
    // spacecraft, crew_station_power)` ordering at
    // `actions.py:2402-2403`.
    {
        let bf = Arc::make_mut(&mut state.players[cr_idx].battlefield);
        for o in bf.iter_mut() {
            if o.id == crew_id {
                o.tapped = true;
                break;
            }
        }
    }
    {
        let bf = Arc::make_mut(&mut state.players[sp_idx].battlefield);
        for o in bf.iter_mut() {
            if o.id == spacecraft_id {
                o.charge_counters = o.charge_counters.saturating_add(crew_power);
                break;
            }
        }
    }
}

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
        // Stubs that always raise (TurnFaceUp / UnlockRoomHalf) never
        // reach the post-arm reset because they short-circuit with `?`
        // propagation. **C2 (2026-05-25):** `ActivateStation` is no
        // longer a raising stub — the dispatch arm now invokes the
        // real `apply_activate_station` resolver and flows through
        // the post-arm reset like any other priority-round-breaking
        // mutation.
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
                //
                // **Round-15 YOU_ATTACK once-per-combat dispatch.**
                // After all per-attacker `Event::Attacks` dispatches
                // complete, snapshot the current attackers count and
                // fire `Event::YouAttack` ONCE if any attacker was
                // registered. Mirrors Python's
                // `_fire_you_attack_triggers(state, declared)` in
                // `combat.py` which skips the dispatch when `declared`
                // is empty (no legal attacker was declared).
                //
                // Subject convention: same PLAYER_SUBJECT_OFFSET
                // sentinel as the phase-step events — the subject is
                // the active player (the attacker's controller).
                // `ControlledByYou` resolves the player index from the
                // sentinel; `Always` ignores the subject_id entirely.
                //
                // The snapshot is taken AFTER the loop so all
                // per-attacker tap + Attacks triggers have already
                // been pushed (correct stack ordering: BECOMES_TAPPED
                // → ATTACKS per attacker, then YOU_ATTACK once for
                // the whole combat step — matches Python's ordering
                // in `combat.declare_attackers`).
                let attackers_before = slf.borrow().attackers.len();
                for attacker_id in attacker_ids {
                    slf.call_method1("declare_attacker", (attacker_id,))?;
                }
                // Fire YOU_ATTACK once if at least one new attacker
                // was registered during this loop.
                let (any_new_attacker, active_player_idx) = {
                    let state = slf.borrow();
                    let any = state.attackers.len() > attackers_before;
                    (any, state.active_player)
                };
                if any_new_attacker {
                    // Reuse PLAYER_SUBJECT_OFFSET sentinel (see cards.rs
                    // doc-comment) so ControlledByYou resolves the active
                    // player without colliding with game-object IDs.
                    let player_subject = crate::cards::PLAYER_SUBJECT_OFFSET
                        + active_player_idx as u32;
                    let mut state = slf.borrow_mut();
                    crate::state_ops_resolve::dispatch_event(
                        &mut state,
                        crate::cards::Event::YouAttack,
                        player_subject,
                    )?;
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
                use_warp,
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
                //
                // **Phase-1 warp substrate (round-63): `use_warp` is
                // now LIVE.** When `use_warp=true`, route to the new
                // `cast_creature_warp` primitive (pays `warp_cost`,
                // sets `spell_warped_this_turn`, stamps
                // `warp_exile_pending` for the end-step exile sweep).
                // Otherwise the round-4 `cast_creature` path (which
                // also serves the warp exile-recast: a `warped`
                // exile object recast at NORMAL `mana_cost` arrives
                // here with `use_warp=false`). The remaining flags
                // (kicked / cast_for_free / use_impending /
                // cast_room_half) stay deferred.
                //
                // **Spell-card-bridge lever (round-70): the non-warp
                // `else` now routes a non-creature Instant/Sorcery to
                // the new `cast_spell_noncreature` primitive.** The
                // dispatch stays a thin delegator (the landed warp
                // pattern): try `cast_spell_noncreature` first; it
                // type-gates INSIDE the primitive (exactly as
                // `cast_creature` / `cast_creature_warp` do) and
                // returns `Ok(false)` for a creature — in which case
                // we fall through to the round-4 `cast_creature` path
                // (which also serves the warp exile-recast). The
                // primitive pays `mana_cost`, binds the
                // deterministic-first target, pushes a spell
                // `StackItem`, and returns; the harness drives the
                // resolve (CE5 cast-vs-resolve mirror). Mirrors
                // Python's `_cast_spell` instant/sorcery branch.
                let player_id = slf.borrow().priority_player;
                if use_warp {
                    slf.call_method1(
                        "cast_creature_warp",
                        (card_id, player_id),
                    )?;
                } else {
                    // **Aura-attachment substrate — Phase 1 STEP 3
                    // (round-78).** Try `cast_aura` first: the
                    // primitive type-gates inside on the printing's
                    // `is_aura` flag and returns `Ok(false)` for a
                    // non-Aura (NO mutation — exactly the
                    // `cast_spell_noncreature` / `cast_creature`
                    // dispatch pattern). On `false` we fall through
                    // to `cast_spell_noncreature` (Instant/Sorcery
                    // path), then `cast_creature` (the round-4
                    // creature path + warp exile-recast). Order is
                    // load-bearing — Auras are noncreature
                    // Enchantments, so `cast_spell_noncreature` would
                    // reject them as "not Instant/Sorcery" and the
                    // cast would silently no-op without the aura arm.
                    let cast_aura_ok: bool = slf
                        .call_method1(
                            "cast_aura",
                            (card_id, player_id),
                        )?
                        .extract()?;
                    if cast_aura_ok {
                        // **Cast-time auto-resolve seat alignment
                        // (Phase 2 S2 extension follow-up — Tractor Beam
                        // closure, 2026-05-20).**
                        //
                        // Python parity: `_select_spell_targets`
                        // (`actions.py:1337-1357`) binds the chosen
                        // enchant target **synchronously at cast time**
                        // by invoking `p.agent.choose_target(...)` inline,
                        // BEFORE the spell's StackItem leaves
                        // `_cast_spell`. The bound target rides on the
                        // StackItem; resolve reads it via the
                        // `target_obj_id` slot. Rust's `cast_aura`
                        // primitive (state_ops_cast.rs Phase 9) instead
                        // pushes a `PendingDecision::EnchantTargetChoice`
                        // onto the pending-decisions queue and returns
                        // with the StackItem's `target_obj_id = None`
                        // — leaving the binding for a later
                        // `submit_enchant_target_decision(...)` /
                        // `auto_resolve_pending_decisions(...)` call.
                        //
                        // Without an apply_action-side auto-drain the
                        // cross-engine bench-loader path
                        // (`step_both` + `drain_stack_both`) fizzles the
                        // Aura on Rust: the next
                        // `resolve_top_of_stack` reads
                        // `top.target_obj_id = None`, routes through
                        // `move_aura_post_resolve` with `target_obj_id =
                        // None`, and the Aura goes to graveyard
                        // (CR 608.2b illegal-target shape). Python
                        // attaches normally because its agent picked the
                        // target inline at cast time. Documented at
                        // `docs/SEARCH_LIMITATIONS.md` under the
                        // "Tractor Beam bench-loader admit honest-stop"
                        // entry — a production-deck shadow bake-in
                        // divergence at archetype 2 / seed 1 / step 874.
                        //
                        // Fix: drain the pending decision with the
                        // deterministic-first `"default"` strategy
                        // (the `EnchantTargetChoice` arm at
                        // `state_ops_decisions.rs:518-555` binds
                        // `candidates[0]` to the StackItem's
                        // `target_obj_id` via
                        // `bind_enchant_target_to_stack_item`). Mirrors
                        // the `_PickFirstLegalTargetAgent` bench/probe
                        // convention every other cast-time target picker
                        // already uses (Radiant Strike, Focus Fire,
                        // Seedship Impact).
                        //
                        // **Why scoped to the `cast_aura_ok=true`
                        // branch.** `cast_spell_noncreature` and
                        // `cast_creature` already bind their
                        // deterministic-first target inline (see the
                        // round-70 spell-card-bridge lever and the
                        // round-4 creature path) — they DO NOT queue
                        // any pending decisions. Draining here only
                        // affects the Aura cast path. The `empty
                        // candidates` aura cast (no legal hosts; cast
                        // still completes per Python parity at
                        // `actions.py:1354`) skips the
                        // `pending_decisions.push` inside `cast_aura`
                        // so the auto-resolve walk is a no-op for that
                        // case — exactly the same shape Python's
                        // `_select_spell_targets` produces when `legal`
                        // is empty.
                        let mut state = slf.borrow_mut();
                        crate::state_ops_decisions::auto_resolve_pending(
                            &mut state,
                            "default",
                        )?;
                    } else {
                        let cast_spell_ok: bool = slf
                            .call_method1(
                                "cast_spell_noncreature",
                                (card_id, player_id),
                            )?
                            .extract()?;
                        if !cast_spell_ok {
                            slf.call_method1(
                                "cast_creature",
                                (card_id, player_id),
                            )?;
                        }
                    }
                }
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
                spacecraft_id,
                crew_id,
            } => {
                // **Spacecraft Station substrate Phase 1 — Cycle 2
                // (substrate-only, 2026-05-25).** Dispatch flipped
                // from the C1 stub to the real `apply_activate_station`
                // resolver. The resolver silent-validates every
                // precondition (Spacecraft own, crew own, crew not
                // tapped / sick, crew is a printed creature, not
                // same id) and on success taps the crew + adds
                // `effective_power(crew)`-many charge counters to
                // the Spacecraft.
                //
                // **Why a free function instead of `call_method1`.**
                // The other dispatch arms (PlayLand, DeclareAttackers,
                // ...) route to existing `#[pymethods]` primitives via
                // the Python attribute layer because those primitives
                // pre-date the dispatch table. The Station resolver
                // is brand-new this cycle and doesn't need Python-
                // visibility (Python's `_activate_station` is module-
                // private at `actions.py:2353` — the engine never
                // calls into the Rust resolver from Python). A free
                // Rust function is the simpler shape; future slices
                // can promote it to a pymethod if a probe needs the
                // direct surface.
                let player_id = slf.borrow().priority_player;
                apply_activate_station(
                    &mut slf.borrow_mut(),
                    player_id,
                    spacecraft_id,
                    crew_id,
                );
            }
            Action::ActivateAbility {
                source_id,
                ability_index,
                target_creature_id,
                sacrifice_target_id,
                chosen_mode_idx,
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
                    /// CE20 follow-up Slice 4 (Equipment-equip): when
                    /// `true`, the activator MUST submit a
                    /// `target_creature_id` in the action dict, and
                    /// the dispatch arm validates the target then
                    /// threads it into the StackItem payload (or the
                    /// `state.current_resolve_payload_target_id`
                    /// transient slot for mana-ability paths).
                    requires_target_creature_you_control: bool,
                    /// CE20 Slice 6 (targeted-sacrifice variants).
                    /// `true` when the cost flags
                    /// `sacrifice_another_creature_or_artifact`. The
                    /// activator MUST submit a `sacrifice_target_id`
                    /// and the target MUST be a creature or artifact
                    /// on the activator's bf, NOT the source itself.
                    sacrifice_another_creature_or_artifact: bool,
                    /// CE20 Slice 6. `true` when the cost flags
                    /// `sacrifice_a_land`. The activator MUST submit
                    /// a `sacrifice_target_id` and the target MUST be
                    /// a land on the activator's bf — the source
                    /// itself IS eligible (Dust-Bowl-style — no
                    /// "another" qualifier).
                    sacrifice_a_land: bool,
                    /// CE20 Slice 6. `true` when the cost flags
                    /// `sacrifice_another_artifact`. The activator
                    /// MUST submit a `sacrifice_target_id` and the
                    /// target MUST be an artifact on the activator's
                    /// bf, NOT the source itself.
                    sacrifice_another_artifact: bool,
                    /// CE20 Slice 7 (subtype-filtered sacrifice).
                    /// `true` when the cost flags `sacrifice_food`.
                    /// The activator MUST submit a `sacrifice_target_id`
                    /// and the target MUST be on the activator's bf
                    /// with `subtypes` containing "Food" — the source
                    /// itself IS eligible (no "another" qualifier).
                    sacrifice_food: bool,
                    /// CE20 Slice 7 (subtype-filtered sacrifice).
                    /// `true` when the cost flags `sacrifice_a_desert`.
                    /// The activator MUST submit a `sacrifice_target_id`
                    /// and the target MUST be on the activator's bf
                    /// with `subtypes` containing "Desert" — the source
                    /// itself IS eligible.
                    sacrifice_a_desert: bool,
                    /// CE20 Slice 5 (Walker loyalty Slice A). Signed
                    /// loyalty cost. Positive = pay (decrement
                    /// `loyalty_counters` by N); negative = add
                    /// (increment by |N|); zero = no cost. Committed
                    /// in Phase 5d.
                    loyalty: i32,
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
                            requires_target_creature_you_control:
                                ab.cost.requires_target_creature_you_control,
                            sacrifice_another_creature_or_artifact:
                                ab.cost.sacrifice_another_creature_or_artifact,
                            sacrifice_a_land: ab.cost.sacrifice_a_land,
                            sacrifice_another_artifact:
                                ab.cost.sacrifice_another_artifact,
                            sacrifice_food: ab.cost.sacrifice_food,
                            sacrifice_a_desert: ab.cost.sacrifice_a_desert,
                            loyalty: ab.cost.loyalty,
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
                // Phase 2.5: CE20 follow-up Slice 4 target-pick
                // validation. When the ability's cost flags
                // `requires_target_creature_you_control = true` (today
                // only Equipment-equip), the action dict MUST carry a
                // `target_creature_id` and that id MUST resolve to a
                // legal target on the activator's battlefield. Legal
                // target: a creature on the activator's bf that
                // ISN'T the source itself (CR 702.6c — an Equipment
                // can't equip itself). Target's summoning sickness is
                // not a barrier (equip costs nothing target-side).
                //
                // **Symmetric error shape with the rest of the apply
                // pipeline**: raise BEFORE any commit so a malformed
                // dict leaves no state mutation. Emission walks
                // already pre-filter to only legal targets, so this
                // raise only fires for direct callers that build a
                // dict with an illegal target (test / synthetic path).
                //
                // **Conversely** for non-target activations, an
                // accidentally-supplied target_creature_id is
                // silently ignored (matches Python's permissive
                // accept-and-ignore for spurious kwargs on
                // `ActivateAbility(target_creature_id=...)`).
                // **Carrier-AA substrate Phase 2a Cycle 2 (2026-05-25).**
                // Recognize ``Effect::ReturnTargetLandFromGraveyardToHand``
                // as a SECOND target-shape on the
                // ``target_creature_id`` slot — when an AA's effect is
                // this variant (Petrified Field's pilot AA), the
                // ``target_creature_id`` slot acts as the chosen
                // graveyard-Land card id, NOT a bf-Creature id. The
                // legal-emit fan-out arm at
                // ``state_ops_legal.rs::legal_decisions`` (this
                // cycle's other deliverable) walks the activator's
                // graveyard for Land cards and emits one
                // ``ActivateAbility`` per eligible target with
                // ``target_creature_id = Some(grave_land_id)``.
                let is_return_land_from_gy_effect = matches!(
                    resolved.effect,
                    crate::cards::Effect::ReturnTargetLandFromGraveyardToHand,
                );
                // **Carrier-AA substrate Phase 3A Cycle 1 (2026-05-25).**
                // Recognize ``Effect::ExileTargetAttackingCreatureUntilEnd
                // Step`` as a THIRD target-shape on the
                // ``target_creature_id`` slot — when an AA's effect is
                // this variant (Mystifying Maze's pilot AA), the
                // ``target_creature_id`` slot acts as the chosen
                // attacking-creature id. Validation walks
                // ``state.attackers`` for the target id + verifies the
                // target is on a battlefield + opponent-controlled +
                // printed-Creature. The legal-emit fan-out arm at
                // ``state_ops_legal.rs::legal_decisions`` (this
                // cycle's other deliverable) walks ``state.attackers``
                // and emits one ``ActivateAbility`` per eligible
                // attacker with ``target_creature_id = Some(attacker_id)``.
                let is_exile_attacking_creature_effect = matches!(
                    resolved.effect,
                    crate::cards::Effect::ExileTargetAttackingCreatureUntilEndStep,
                );
                // **Carrier-AA substrate Phase 3C Cycle 2 (2026-05-26).**
                // Recognize ``Effect::BecomesCopyOfTargetLand`` as a
                // FOURTH target-shape on the ``target_creature_id``
                // slot — when an AA's effect is this variant (Thespian's
                // Stage's pilot AA), the ``target_creature_id`` slot
                // acts as the chosen Land id (own or opponent
                // controlled). Validation walks BOTH players'
                // battlefields for the target id + verifies the
                // target is printed as a Land. The legal-emit fan-out
                // arm at ``state_ops_legal.rs::legal_decisions`` (this
                // cycle's other deliverable) walks both bfs and emits
                // one ``ActivateAbility`` per eligible Land target
                // with ``target_creature_id = Some(land_id)``.
                let is_becomes_copy_of_land_effect = matches!(
                    resolved.effect,
                    crate::cards::Effect::BecomesCopyOfTargetLand,
                );
                // **Carrier-AA substrate Phase 4C Cycle 1 (2026-05-26).**
                // Recognize ``Effect::ExileTargetCardFromGraveyard`` as
                // a FIFTH target-shape on the ``target_creature_id``
                // slot — when an AA's effect is this variant (Ghost
                // Vacuum's AA[0] pilot), the ``target_creature_id``
                // slot acts as the chosen graveyard-card id (either
                // player's graveyard). Validation walks BOTH players'
                // graveyards for the target id. The legal-emit fan-
                // out arm at
                // ``state_ops_legal.rs::legal_decisions`` walks both
                // graveyards and emits one ``ActivateAbility`` per
                // eligible target with ``target_creature_id =
                // Some(card_id)``.
                let is_exile_target_card_from_gy_effect = matches!(
                    resolved.effect,
                    crate::cards::Effect::ExileTargetCardFromGraveyard,
                );
                // **Carrier-AA substrate Phase 4D Cycle 1 (2026-05-26).**
                // Recognize ``Effect::LockOrUnlockDoorOfTargetRoomYouControl``
                // as a SIXTH target-shape on the ``target_creature_id``
                // slot — when an AA's effect is this variant (Keys to
                // the House's AA[1]), the ``target_creature_id`` slot
                // acts as the chosen Room id (controller-controlled
                // only, per the `You control` rider). Validation walks
                // the activator's battlefield for the target id +
                // verifies the target is printed with the Room
                // subtype. The Cycle 2 legal-emit fan-out arm in
                // ``state_ops_legal.rs::legal_decisions`` (NOT YET
                // LANDED at this commit) will walk
                // ``state.players[controller_idx].battlefield`` for
                // Room-subtyped permanents and emit one
                // ``ActivateAbility`` per eligible target × per door-
                // half. Cycle 1 only wires the apply-side
                // (action-dict → resolve) — the legal-side fan-out is
                // C2's deliverable; direct-callers / synthetic tests
                // drive the resolve path.
                let is_lock_or_unlock_door_effect = matches!(
                    resolved.effect,
                    crate::cards::Effect::LockOrUnlockDoorOfTargetRoomYouControl,
                );
                let validated_target_id: Option<u32> =
                    if resolved.requires_target_creature_you_control {
                        let Some(target_id) = target_creature_id else {
                            return Err(PyValueError::new_err(format!(
                                "ActivateAbility: source {source_id} \
                                 requires a target creature you control \
                                 (target_creature_id key missing or None)"
                            )));
                        };
                        if target_id == source_id {
                            return Err(PyValueError::new_err(format!(
                                "ActivateAbility: source {source_id} \
                                 cannot target itself (CR 702.6c — \
                                 Equipment can't equip itself)"
                            )));
                        }
                        // Target must be on the activator's
                        // (controller's) battlefield AND a creature.
                        let target_legal: bool = {
                            let bf = &state.players[controller_idx].battlefield;
                            let registry = &state.registry;
                            bf.iter().any(|obj| {
                                if obj.id != target_id {
                                    return false;
                                }
                                let Some(printing) = registry
                                    .printings
                                    .get(obj.printing_id as usize)
                                else {
                                    return false;
                                };
                                printing.card_types.iter().any(|t| t == "Creature")
                            })
                        };
                        if !target_legal {
                            return Err(PyValueError::new_err(format!(
                                "ActivateAbility: source {source_id} \
                                 target {target_id} not a legal target \
                                 (must be a creature on activator's bf, \
                                 not the source itself)"
                            )));
                        }
                        Some(target_id)
                    } else if is_exile_attacking_creature_effect {
                        // **Carrier-AA substrate Phase 3A Cycle 1 (2026-05-
                        // 25).** Attacking-creature target validation
                        // for Mystifying Maze. The legal-emit fan-out
                        // arm in `state_ops_legal.rs::legal_decisions`
                        // walks `state.attackers` and emits one
                        // `ActivateAbility` per eligible target with
                        // `target_creature_id = Some(attacker_id)`. The
                        // validator here re-checks the chosen target
                        // against `state.attackers` + opponent-controlled
                        // + on-battlefield invariants.
                        //
                        // **target_creature_id is OPTIONAL** on this
                        // effect — the substrate-fallback path in the
                        // resolve arm (no target seated) is silent-
                        // fizzle, matching Python's `if not targets:
                        // return` early-return at `exile.py:216-217`.
                        // Direct-callers / synthetic tests rely on
                        // either passing the chosen attacker id or
                        // omitting it to drive the fizzle path.
                        match target_creature_id {
                            Some(target_id) => {
                                // Must be in state.attackers.
                                if !state.attackers.contains(&target_id) {
                                    return Err(PyValueError::new_err(format!(
                                        "ActivateAbility: source {source_id} \
                                         target {target_id} not currently \
                                         attacking (not in state.attackers; \
                                         CR 117.5 — Mystifying Maze's AA \
                                         requires an attacking-creature \
                                         target)"
                                    )));
                                }
                                // Must be on SOME battlefield + opponent-
                                // controlled + printed-Creature.
                                let target_legal: bool = {
                                    let registry = &state.registry;
                                    let mut ok = false;
                                    for (pidx, player) in
                                        state.players.iter().enumerate()
                                    {
                                        if let Some(t_obj) = player
                                            .battlefield
                                            .iter()
                                            .find(|o| o.id == target_id)
                                        {
                                            // Opponent-controlled?
                                            if pidx == controller_idx {
                                                break;
                                            }
                                            let Some(printing) = registry
                                                .printings
                                                .get(t_obj.printing_id as usize)
                                            else {
                                                break;
                                            };
                                            ok = printing
                                                .card_types
                                                .iter()
                                                .any(|t| t == "Creature");
                                            break;
                                        }
                                    }
                                    ok
                                };
                                if !target_legal {
                                    return Err(PyValueError::new_err(format!(
                                        "ActivateAbility: source {source_id} \
                                         target {target_id} not a legal \
                                         attacking-creature target (must be \
                                         a Creature on a battlefield, \
                                         opponent-controlled relative to \
                                         the activator)"
                                    )));
                                }
                                Some(target_id)
                            }
                            None => None,
                        }
                    } else if is_lock_or_unlock_door_effect {
                        // **Carrier-AA substrate Phase 4D Cycle 1
                        // (2026-05-26).** Room-target validation for
                        // Keys to the House's AA[1]. Cycle 2 ships the
                        // legal-emit fan-out arm in
                        // ``state_ops_legal.rs::legal_decisions``; the
                        // validator here re-checks the chosen target
                        // against bf-presence + printed-Room subtype +
                        // controller-match (``You control`` rider).
                        // Mirrors Python's
                        // ``LockOrUnlockDoorOfTargetRoomYouControl.
                        // legal_targets`` walk over the activator's
                        // battlefield for ``o.printing.is_room`` at
                        // ``effects/generic/misc.py:229-237``.
                        //
                        // **target_creature_id is OPTIONAL** on this
                        // effect — the substrate-fallback path in the
                        // resolve arm (no target seated) is silent-
                        // fizzle, matching Python's `if not targets:
                        // return` early-return at `misc.py:243`.
                        // Direct-callers / synthetic tests rely on
                        // either passing the chosen Room id or omitting
                        // it to drive the fizzle path.
                        match target_creature_id {
                            Some(target_id) => {
                                // Must be on the activator's bf AND
                                // printed with the Room subtype.
                                let target_legal: bool = {
                                    let bf = &state
                                        .players[controller_idx]
                                        .battlefield;
                                    let registry = &state.registry;
                                    bf.iter().any(|obj| {
                                        if obj.id != target_id {
                                            return false;
                                        }
                                        let Some(printing) = registry
                                            .printings
                                            .get(obj.printing_id as usize)
                                        else {
                                            return false;
                                        };
                                        printing.subtypes
                                            .iter()
                                            .any(|s| s == "Room")
                                    })
                                };
                                if !target_legal {
                                    return Err(PyValueError::new_err(format!(
                                        "ActivateAbility: source {source_id} \
                                         target {target_id} not a legal \
                                         Room target (must be a Room-subtyped \
                                         permanent on the activator's bf; \
                                         CR 715 — Keys to the House's AA[1] \
                                         requires `target Room you control`)"
                                    )));
                                }
                                Some(target_id)
                            }
                            None => None,
                        }
                    } else if is_becomes_copy_of_land_effect {
                        // **Carrier-AA substrate Phase 3C Cycle 2
                        // (2026-05-26).** Land-target validation for
                        // Thespian's Stage. The legal-emit fan-out arm
                        // in `state_ops_legal.rs::legal_decisions`
                        // walks BOTH players' battlefields for printed-
                        // Land objects and emits one `ActivateAbility`
                        // per eligible target with
                        // `target_creature_id = Some(land_id)`. The
                        // validator here re-checks the chosen target
                        // against bf-presence + printed-Land + own-or-
                        // opponent (no own-control restriction, per
                        // CR 109.3 / 613 and Python's
                        // `BecomesCopyOfTargetLand.legal_targets` walk
                        // over `state.battlefield` at
                        // `effects/generic/become_type.py:269-276`).
                        //
                        // **target_creature_id is OPTIONAL** on this
                        // effect — the substrate-fallback path in the
                        // resolve arm (no target seated) is silent
                        // fizzle, matching Python's `if source is None
                        // or not targets: return` early-return at
                        // `become_type.py:285-286`. Direct-callers /
                        // synthetic tests rely on either passing the
                        // chosen land id or omitting it to drive the
                        // fizzle path.
                        match target_creature_id {
                            Some(target_id) => {
                                // Must be on SOME battlefield AND
                                // printed Land. ANY controller (own
                                // or opponent) — no `pidx ==
                                // controller_idx` exclusion.
                                let target_legal: bool = {
                                    let registry = &state.registry;
                                    let mut ok = false;
                                    for player in state.players.iter() {
                                        if let Some(t_obj) = player
                                            .battlefield
                                            .iter()
                                            .find(|o| o.id == target_id)
                                        {
                                            let Some(printing) = registry
                                                .printings
                                                .get(t_obj.printing_id as usize)
                                            else {
                                                break;
                                            };
                                            ok = printing
                                                .card_types
                                                .iter()
                                                .any(|t| t == "Land");
                                            break;
                                        }
                                    }
                                    ok
                                };
                                if !target_legal {
                                    return Err(PyValueError::new_err(format!(
                                        "ActivateAbility: source {source_id} \
                                         target {target_id} not a legal \
                                         copy-Land target (must be a Land on \
                                         a battlefield; CR 109.3 / 613 — \
                                         Thespian's Stage targets ANY Land)"
                                    )));
                                }
                                Some(target_id)
                            }
                            None => None,
                        }
                    } else if is_exile_target_card_from_gy_effect {
                        // **Carrier-AA substrate Phase 4C Cycle 1
                        // (2026-05-26).** Graveyard-card target
                        // validation for Ghost Vacuum's AA[0]. The
                        // legal-emit fan-out arm in
                        // `state_ops_legal.rs::legal_decisions` walks
                        // BOTH players' graveyards (no card-type
                        // filter, no controller restriction — the
                        // printed text reads "target card from a
                        // graveyard"). The validator here re-checks
                        // the chosen target against graveyard-
                        // presence on EITHER player.
                        //
                        // **target_creature_id is OPTIONAL** on this
                        // effect — the substrate-fallback path in the
                        // resolve arm (no target seated) is silent
                        // fizzle, matching Python's
                        // `ExileTargetCardFromGraveyard.resolve` at
                        // `exile.py:325-326`'s `if not targets:
                        // return` early-return.
                        match target_creature_id {
                            Some(target_id) => {
                                // Must be on SOME player's graveyard.
                                // No card-type filter — printed text
                                // accepts any card type.
                                let target_legal: bool = {
                                    let mut ok = false;
                                    for player in state.players.iter() {
                                        if player
                                            .graveyard
                                            .iter()
                                            .any(|o| o.id == target_id)
                                        {
                                            ok = true;
                                            break;
                                        }
                                    }
                                    ok
                                };
                                if !target_legal {
                                    return Err(PyValueError::new_err(format!(
                                        "ActivateAbility: source {source_id} \
                                         target {target_id} not a legal \
                                         graveyard-card target (must be a \
                                         card in SOME player's graveyard; \
                                         Ghost Vacuum's AA[0] targets \
                                         either player's graveyard)"
                                    )));
                                }
                                Some(target_id)
                            }
                            None => None,
                        }
                    } else if is_return_land_from_gy_effect {
                        // Phase-2a graveyard-Land target validation.
                        // ``target_creature_id`` is OPTIONAL on this
                        // effect (substrate-fallback path supports
                        // ``None`` via the resolve arm's deterministic-
                        // first-legal scan; direct-callers / synthetic
                        // tests rely on it). When ``Some(id)``, the
                        // id MUST resolve to a Land card in the
                        // ACTIVATOR's graveyard — CR 701.3 + Python's
                        // ``ReturnFromGraveyard.legal_targets`` at
                        // ``effects/generic/graveyard.py:183-191``
                        // walks ``state.player_by_id(controller_id)
                        // .graveyard`` only. The source itself is NOT
                        // pre-excluded here because at apply-time the
                        // sacrifice_self cost hasn't yet committed
                        // (the cost-pay path runs AFTER this
                        // validation block in the activation pipeline,
                        // so the source is still on the bf — not in
                        // the graveyard — and naturally absent from
                        // the gy target pool).
                        match target_creature_id {
                            Some(target_id) => {
                                let target_legal: bool = {
                                    let gy = &state.players[controller_idx].graveyard;
                                    let registry = &state.registry;
                                    gy.iter().any(|obj| {
                                        if obj.id != target_id {
                                            return false;
                                        }
                                        let Some(printing) = registry
                                            .printings
                                            .get(obj.printing_id as usize)
                                        else {
                                            return false;
                                        };
                                        printing
                                            .card_types
                                            .iter()
                                            .any(|t| t == "Land")
                                    })
                                };
                                if !target_legal {
                                    return Err(PyValueError::new_err(format!(
                                        "ActivateAbility: source {source_id} \
                                         target {target_id} not a legal \
                                         graveyard-Land target (must be a \
                                         Land card in activator's graveyard)"
                                    )));
                                }
                                Some(target_id)
                            }
                            None => None,
                        }
                    } else {
                        // Non-target activation: accept None or
                        // ignore a stray target_creature_id key. The
                        // payload won't be threaded into the
                        // StackItem / current_resolve_payload_target_id.
                        None
                    };
                // Phase 2.7: CE20 follow-up Slice 6 + Slice 7
                // sacrifice-target validation. When the cost flags any
                // of the targeted-sac variants (Slice 6's
                // `sacrifice_another_creature_or_artifact` /
                // `sacrifice_a_land` / `sacrifice_another_artifact`,
                // or Slice 7's `sacrifice_food` / `sacrifice_a_desert`),
                // the action dict MUST carry a `sacrifice_target_id`
                // and that id MUST resolve to a legal sac target on the
                // activator's battlefield.
                //
                // Per-variant eligibility:
                //   - sacrifice_another_creature_or_artifact: target
                //     has Creature OR Artifact card_type, NOT self.
                //   - sacrifice_a_land: target has Land card_type;
                //     self IS eligible (printed text "a land" with no
                //     "another" qualifier).
                //   - sacrifice_another_artifact: target has Artifact
                //     card_type, NOT self.
                //   - sacrifice_food: target's subtypes contains "Food";
                //     self IS eligible (no "another" qualifier).
                //   - sacrifice_a_desert: target's subtypes contains
                //     "Desert"; self IS eligible.
                //
                // Symmetric error shape with Phase 2.5: raise BEFORE
                // any commit so a malformed dict leaves no state
                // mutation. Non-sacrifice activations accept-and-
                // ignore a stray sacrifice_target_id (parity with
                // Phase 2.5's stray-target_creature_id handling).
                let needs_sac_target = resolved
                    .sacrifice_another_creature_or_artifact
                    || resolved.sacrifice_a_land
                    || resolved.sacrifice_another_artifact
                    || resolved.sacrifice_food
                    || resolved.sacrifice_a_desert;
                let validated_sac_target_id: Option<u32> =
                    if needs_sac_target {
                        let Some(sac_id) = sacrifice_target_id else {
                            return Err(PyValueError::new_err(format!(
                                "ActivateAbility: source {source_id} \
                                 requires a sacrifice target \
                                 (sacrifice_target_id key missing or None)"
                            )));
                        };
                        // Per-variant legality check.
                        let target_legal: bool = {
                            let bf = &state.players[controller_idx].battlefield;
                            let registry = &state.registry;
                            bf.iter().any(|obj| {
                                if obj.id != sac_id {
                                    return false;
                                }
                                let Some(printing) = registry
                                    .printings
                                    .get(obj.printing_id as usize)
                                else {
                                    return false;
                                };
                                let is_self = sac_id == source_id;
                                let is_creature = printing
                                    .card_types
                                    .iter()
                                    .any(|t| t == "Creature");
                                let is_artifact = printing
                                    .card_types
                                    .iter()
                                    .any(|t| t == "Artifact");
                                let is_land = printing
                                    .card_types
                                    .iter()
                                    .any(|t| t == "Land");
                                // Subtype checks (Slice 7) —
                                // case-sensitive Title Case match per
                                // CR/Scryfall convention.
                                let is_food = printing
                                    .subtypes
                                    .iter()
                                    .any(|s| s == "Food");
                                let is_desert = printing
                                    .subtypes
                                    .iter()
                                    .any(|s| s == "Desert");
                                if resolved
                                    .sacrifice_another_creature_or_artifact
                                {
                                    !is_self && (is_creature || is_artifact)
                                } else if resolved.sacrifice_a_land {
                                    is_land
                                } else if resolved.sacrifice_another_artifact {
                                    !is_self && is_artifact
                                } else if resolved.sacrifice_food {
                                    is_food
                                } else if resolved.sacrifice_a_desert {
                                    is_desert
                                } else {
                                    false
                                }
                            })
                        };
                        if !target_legal {
                            return Err(PyValueError::new_err(format!(
                                "ActivateAbility: source {source_id} \
                                 sacrifice_target {sac_id} not a legal \
                                 sacrifice target for this cost variant \
                                 (must be on activator's bf and match \
                                 the cost's sacrifice filter)"
                            )));
                        }
                        Some(sac_id)
                    } else {
                        None
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
                // Phase 3b: CE20 Slice 5 (Walker loyalty) loyalty gate.
                // Positive `cost.loyalty` requires the source to have
                // at least `cost.loyalty` loyalty counters. Negative
                // (add-loyalty) values are always affordable. Mirrors
                // the emission filter's pin so a direct (bypass-
                // emission) caller gets the same rejection shape.
                if resolved.loyalty > 0 {
                    let obj = &state.players[controller_idx].battlefield[bf_pos];
                    if obj.loyalty_counters < resolved.loyalty {
                        return Err(PyValueError::new_err(format!(
                            "ActivateAbility: source {source_id} \
                             insufficient loyalty (loyalty_counters={} \
                             < cost.loyalty={})",
                            obj.loyalty_counters, resolved.loyalty,
                        )));
                    }
                }
                // Phase 3c: CE20 Slice 5 (Walker loyalty Slice C)
                // once-per-turn-per-walker gate (CR 606.3 — "a player
                // may activate a loyalty ability of a planeswalker
                // they control only if no player has activated a
                // loyalty ability of that planeswalker this turn").
                // When the source is a planeswalker and the
                // (controller, source_id) key is already in the
                // ledger, refuse the activation. Mirrors the
                // emission-side skip in `state_ops_legal.rs` so a
                // direct (bypass-emission) caller gets the same
                // rejection shape.
                //
                // **Source-type check on Planeswalker card_type.**
                // Today this maps 1:1 to "has a loyalty ability"
                // (Tezzeret-shape walkers carry only loyalty
                // abilities), so gating on card_type instead of a
                // per-ability `is_loyalty: bool` is sufficient. A
                // future walker printing with a non-loyalty
                // activated ability (rare) would over-gate here —
                // fix would be a per-ability flag, deferred until a
                // printing actually carries the mixed shape.
                let source_is_walker = state
                    .registry
                    .lookup(printing_id)
                    .map(|p| {
                        p.card_types.iter().any(|t| t == "Planeswalker")
                    })
                    .unwrap_or(false);
                if source_is_walker
                    && state
                        .loyalty_activated_this_turn
                        .contains(&(controller_idx as u8, source_id))
                {
                    return Err(PyValueError::new_err(format!(
                        "ActivateAbility: source {source_id} \
                         planeswalker has already activated a \
                         loyalty ability this turn \
                         (CR 606.3 — once-per-turn-per-walker)"
                    )));
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
                // Phase 4: pay the mana cost (if any) by **auto-tapping
                // from lands**, byte-mirroring Python's
                // `_activate_ability` (`src/mtg_bot/actions.py:
                // 1992-1995`), which pays the ability mana via the
                // IDENTICAL `auto_tap_for_cost` call `_cast_spell` makes
                // (`actions.py:1662`): consume the floating pool first,
                // then tap untapped non-sick controller lands for the
                // remainder.
                //
                // **G7 frontier (a) closure — the §2-4 analog for
                // `ActivateAbility`.** Previously this site paid STRICTLY
                // from the controller's floating pool
                // (`pay_mana_cost_pub`), bailing with a raw `ValueError`
                // when the pool alone fell short. But the legal emitter
                // offers `ActivateAbility` on pool **+ auto-tappable
                // lands** (`state_ops_legal.rs:2105` →
                // `auto_tap_headroom_pool`, the `can_pay_cost` shape,
                // byte-equal to Python's `legal.py:653` predicate). So a
                // production-deck activation whose cost needs land-
                // tapping (pool alone short) was emitted-legal then
                // raw-rejected here — the bake-in's arch2/s1 step-318
                // self-inconsistency (`ActivateAbility(121,0)`, `{2}`
                // Lander, pool `{U:1}` + 2 untapped Forests). Routing
                // through the SAME `auto_tap_pay_for_cost` helper the
                // three §2-4 cast sites use makes apply honor what legal
                // offered, exactly as Python's `_activate_ability` does.
                // The plan-then-commit helper still degrades a genuinely
                // unpayable over-emit to the SAME no-mutation
                // `Ok(false)` → raw-`ValueError` bail (no fallback
                // hybrid; honest failure preserved).
                let mana_paid: bool =
                    crate::state_ops_cast::auto_tap_pay_for_cost(
                        state, controller_idx, &resolved.mana_cost,
                    )?;
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
                //
                // **Round-58 BECOMES_TAPPED event bridge — `{T}`
                // tap-self activated-ability-cost site.** Python's
                // `_activate_ability` (`src/mtg_bot/actions.py:
                // 1997-2000`) pays the `tap_self` cost via
                // `turn.tap_permanent(state, source)`, which fires
                // `Event.BECOMES_TAPPED` for the source — and it does
                // so AFTER the mana cost is paid but BEFORE any
                // sacrifice cost / target selection / effect push.
                // The Phase-3 precheck above already raised if the
                // source was tapped, so reaching here means the
                // source was UNTAPPED — the "state actually changed"
                // branch Python's `tap_permanent` dispatches on
                // (no-op-if-already-tapped is unreachable here).
                // Dispatch right after the flip and before Phase 5b
                // (sacrifice_self), matching Python's cost-payment
                // order so the becomes-tapped trigger lands on the
                // stack ahead of anything the rest of activation
                // pushes.
                if resolved.tap_self {
                    let bf_mut = Arc::make_mut(
                        &mut state.players[controller_idx].battlefield,
                    );
                    bf_mut[bf_pos].tapped = true;
                    crate::state_ops_resolve::dispatch_event(
                        state,
                        crate::cards::Event::BecomesTapped,
                        source_id,
                    )?;
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
                    obj.original_printing_id = None;
                    obj.door_states = None;
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
                    // Round-55: token-cease sibling. The Lander
                    // `{2},Sac:` cost path lands here — a sacrificed
                    // Lander token ceases to exist (CR 111.7) instead
                    // of sitting in the graveyard. drain_pending_
                    // leaves_dispatches' tail removes it AFTER the
                    // LEAVES dispatch (so the token is still an
                    // observer for its own LEAVES trigger — Python's
                    // by-reference move_off_battlefield semantics).
                    crate::state_ops_zones::queue_token_cease(state, sac_obj_id);
                    crate::state_ops_resolve::drain_pending_leaves_dispatches(
                        state,
                    )?;
                }
                // Phase 5c: CE20 Slice 6 + Slice 7 — commit a TARGETED
                // sacrifice (sacrifice_another_*, sacrifice_a_land,
                // sacrifice_food, sacrifice_a_desert). Same
                // field-reset + LTB-void-flag + LEAVES queue + drain
                // plumbing as Phase 5b, but the moved object is the
                // chosen sac target, NOT the source. The activator
                // controls the sac target (Phase 2.7 enforced bf
                // containment on activator's side), so the target's
                // controller_idx == activator's controller_idx.
                //
                // **bf_pos validity after Phase 5b sac_self.** If
                // both sacrifice_self AND a targeted sac flag are
                // somehow set on the same ability (today no printing
                // does this), Phase 5b would have moved the source —
                // and Phase 5c would then look up the target by id,
                // which is safe (we don't rely on bf_pos here). The
                // ordering still holds: source dies before target if
                // the printed text reads "Sacrifice this, sacrifice
                // another creature: ..." (no EoE shape today).
                //
                // **Self-sac via Dust Bowl path.** When the source IS
                // a land and `sacrifice_a_land` flags true with the
                // chosen target == source_id, the bf_pos we captured
                // earlier may still be valid (no Phase 5b mutation
                // for non-`sacrifice_self` paths). The lookup-by-id
                // pattern below handles both cases uniformly.
                if let Some(sac_target_id) = validated_sac_target_id {
                    let bf_pos_of_target = state.players[controller_idx]
                        .battlefield
                        .iter()
                        .position(|o| o.id == sac_target_id);
                    if let Some(pos) = bf_pos_of_target {
                        let bf_mut = Arc::make_mut(
                            &mut state.players[controller_idx].battlefield,
                        );
                        let mut obj = bf_mut.remove(pos);
                        obj.zone = crate::state_ops_zones::ZONE_GRAVEYARD;
                        obj.tapped = false;
                        // CE13 I35: summoning_sick stays as-is.
                        obj.damage = 0;
                        obj.counters = 0;
                        obj.attached_to = None;
                        obj.original_printing_id = None;
                        obj.door_states = None;
                        obj.exiled_with_source = None;
                        let sac_printing_id = obj.printing_id;
                        let sac_obj_id = obj.id;
                        Arc::make_mut(
                            &mut state.players[controller_idx].graveyard,
                        )
                        .push(obj);
                        crate::state_ops_zones::mark_left_battlefield_if_nonland(
                            state,
                            sac_printing_id,
                        );
                        // LTB fan-out (parity with Phase 5b).
                        state.pending_leaves_dispatches.push(sac_obj_id);
                        // Round-55: token-cease sibling (parity with
                        // Phase 5b) — a sacrificed token target
                        // (sacrifice_another_* etc.) ceases to exist.
                        crate::state_ops_zones::queue_token_cease(
                            state, sac_obj_id,
                        );
                        crate::state_ops_resolve::drain_pending_leaves_dispatches(
                            state,
                        )?;
                    } else {
                        // Defensive: Phase 2.7 already verified the
                        // target is on the activator's bf; reaching
                        // here means a concurrent mutation between
                        // validation and commit (impossible in the
                        // synchronous apply path). Raise loudly so the
                        // bug surfaces if invariants drift.
                        return Err(PyValueError::new_err(format!(
                            "ActivateAbility: sacrifice_target {sac_target_id} \
                             vanished between validation and commit \
                             (invariant violation)"
                        )));
                    }
                }
                // Phase 5d: CE20 Slice 5 (Walker loyalty Slice A)
                // loyalty-counter commit. Signed subtraction handles
                // both directions uniformly:
                //   - positive cost.loyalty (a "-N" ability): walker
                //     LOSES N loyalty counters (decrement).
                //   - negative cost.loyalty (a "+N" ability): walker
                //     GAINS |N| loyalty counters (increment).
                //   - zero: no-op (a "0" ability).
                //
                // **The walker is NOT moved to gy inline here** —
                // even if `loyalty_counters` drops to 0 or below, the
                // SBA pass at state_ops_sba.rs catches it and routes
                // the walker through the standard bf→gy primitives
                // (so LTB triggers fire, etc.) on the next SBA tick.
                // This matches CR 704.5i: SBAs handle walker-zero-
                // loyalty as a simultaneous-action with other SBAs,
                // not inline at activation.
                //
                // **Source position assumption**: bf_pos was captured
                // at Phase 1 and may be stale if Phase 5b/5c moved the
                // source (in particular: sacrifice_self would have
                // moved the source to gy at Phase 5b, in which case
                // the source isn't on bf anymore and we should NOT
                // attempt a loyalty mutation). Defensively look up by
                // id: skip if the source has left the bf.
                if resolved.loyalty != 0 {
                    let bf = &state.players[controller_idx].battlefield;
                    if let Some(pos) =
                        bf.iter().position(|o| o.id == source_id)
                    {
                        let bf_mut = Arc::make_mut(
                            &mut state.players[controller_idx].battlefield,
                        );
                        bf_mut[pos].loyalty_counters -= resolved.loyalty;
                    }
                    // If the source has already left bf (Phase 5b
                    // sacrifice_self path), skip — the loyalty
                    // commit's observable effect doesn't apply to an
                    // off-bf object.
                }
                // Phase 5e: CE20 Slice 5 (Walker loyalty Slice C)
                // once-per-turn-per-walker ledger stamp. CR 606.3 is
                // a per-planeswalker turn limit. Stamp AFTER the
                // loyalty-counter commit (Phase 5d) so a Phase 3-or-4
                // failure that returns early leaves no ledger
                // residue.
                //
                // **Stamps on EVERY successful walker activation**,
                // including the "0" ability (cost.loyalty == 0). The
                // rule's wording is "activated A loyalty ability" —
                // the cost value (positive / zero / negative) doesn't
                // matter; any successful activation locks the walker
                // for the turn.
                //
                // **Gated on Planeswalker card_type** (same gate as
                // Phase 3c). Non-walker activations don't touch the
                // ledger.
                //
                // Same source-position assumption as Phase 5d: the
                // source MAY have left the bf at this point (Phase 5b
                // sacrifice_self path on a hypothetical
                // walker-with-sacrifice-self cost). The ledger stamp
                // is still correct in that case — CR 606.3 doesn't
                // require the walker to still be on the bf to be
                // "locked"; it's bookkeeping on which walker was
                // activated this turn. We stamp unconditionally on
                // source_is_walker.
                if source_is_walker {
                    state
                        .loyalty_activated_this_turn
                        .insert((controller_idx as u8, source_id));
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
                    // CE20 follow-up Slice 4: also seed the
                    // payload-target slot so the
                    // EquipToTargetCreatureYouControl arm reads the
                    // chosen target. For mana-ability activations
                    // the payload target shouldn't normally be set
                    // (mana abilities don't target), but the swap is
                    // harmless when validated_target_id is None
                    // (None overwrites None).
                    let saved_target =
                        state.current_resolve_payload_target_id;
                    state.current_resolve_payload_target_id =
                        validated_target_id;
                    let dispatch_result = crate::state_ops_resolve::apply_effect_pub(
                        state,
                        &resolved.effect,
                        source_id,
                    );
                    state.current_resolve_payload_target_id = saved_target;
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
                    //
                    // **CE20 follow-up Slice 4**: when the activation
                    // carries a chosen target, push the
                    // `new_trigger_with_target` shape so the
                    // resolver seeds
                    // `current_resolve_payload_target_id` before
                    // firing `apply_effect`. Non-target activations
                    // push the legacy `new_trigger` shape (target_id
                    // = None in the payload).
                    let controller = controller_idx as u8;
                    let mut stack_item = match validated_target_id {
                        Some(tid) => crate::state::StackItem::new_trigger_with_target(
                            source_id,
                            controller,
                            resolved.effect.clone(),
                            ability_index,
                            tid,
                        ),
                        None => crate::state::StackItem::new_trigger(
                            source_id,
                            controller,
                            resolved.effect.clone(),
                            ability_index,
                        ),
                    };
                    // **Carrier-AA substrate Phase 4D Cycle 2 (2026-05-
                    // 26).** Thread the agent-chosen door-half index
                    // onto the StackItem so the resolver bracket at
                    // `state_ops_resolve.rs::resolve_top_of_stack` can
                    // copy it into `state.current_resolve_chosen_mode_
                    // idx` before firing `apply_effect` — which the
                    // `Effect::LockOrUnlockDoorOfTargetRoomYouControl`
                    // resolve arm at `state_ops_resolve.rs:25190` reads
                    // to pick the toggle bit. The new_trigger / new_
                    // trigger_with_target constructors leave the slot
                    // at `None` (Spell-kind-only per the Phase 1
                    // `ModalChooseOne` envelope), so this is the
                    // honest post-construction stamp for the activated-
                    // ability path. For non-modal activations the
                    // dispatch path passes `chosen_mode_idx = None` →
                    // the resolve arm defaults to half-0 (no observable
                    // difference for non-Room effects).
                    stack_item.chosen_mode_idx = chosen_mode_idx;
                    state.stack.push(stack_item);
                }
                // Round-27 G4 closure: priority reset after the
                // activate happens at the post-arm reset block
                // (below) — same shape as every other non-pass arm.
            }
            Action::AttackerDecision {
                attacker_id,
                attack,
            } => {
                // G1 factored per-attacker sub-decision apply
                // (the C1-analog for the combat axis). Faithful
                // mirror of Python's `_apply_attacker_decision`
                // (`engine_adapter.py:1080-1099`): on `attack=true`
                // record the creature as an attacker; on
                // `attack=false` do NOTHING (the adapter only
                // appends to `_chosen_attackers` when
                // `decision.attack`, `:1095-1096` — a "don't
                // attack" decision contributes no state change).
                //
                // **Single source of truth with the whole-action
                // path.** `attack=true` dispatches the EXACT same
                // round-5 `declare_attacker(obj_id)` primitive the
                // whole-action `DeclareAttackers { attacker_ids }`
                // arm above loops over — so applying a factored
                // sequence
                // `[AttackerDecision(c1,T), AttackerDecision(c2,F),
                //  AttackerDecision(c3,T)]` is byte-identical to
                // applying the accumulated whole
                // `DeclareAttackers({c1, c3})`. The primitive's
                // `bool` return (eligible/ineligible) is discarded
                // exactly as the whole-action arm discards it
                // (the eligible-set filter is implicit via the
                // per-id gate — mirrors Python's adapter, which
                // walks `eligible_attackers`-derived pending ids).
                if attack {
                    slf.call_method1("declare_attacker", (attacker_id,))?;
                }
            }
            Action::BlockerDecision {
                blocker_id,
                attacker_id,
            } => {
                // G1 factored per-blocker sub-decision apply.
                // Faithful mirror of Python's
                // `_apply_blocker_decision`
                // (`engine_adapter.py:1114-1131`): record the block
                // ONLY when `attacker_id is not None` (`:1127-1128`
                // — the "don't block" branch contributes no state
                // change). `Some(atk)` dispatches the EXACT same
                // round-5 `declare_blocker(blocker_id, atk)`
                // primitive the whole-action `DeclareBlockers`
                // arm loops over, so a factored sequence applies
                // byte-identically to the accumulated whole. The
                // whole-action arm's post-validation `.retain`
                // (menace single-blocker unwind, CE16) is NOT
                // re-run per factored decision — that final-state
                // validation belongs at the accumulation boundary
                // (the B3 provider finalizes via the whole-action
                // `DeclareBlockers` arm, which keeps the CE16
                // post-validation; a single factored decision is
                // an intermediate accumulation step, exactly as
                // Python's per-blocker `_apply_blocker_decision`
                // does no menace post-validation — that lives in
                // the engine's `_declare_blockers` finalize,
                // `actions.py:2555-2566`).
                if let Some(atk) = attacker_id {
                    slf.call_method1("declare_blocker", (blocker_id, atk))?;
                }
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
