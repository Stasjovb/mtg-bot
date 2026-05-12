//! Stack-resolution primitives on `GameState`.
//!
//! First-cut composition slice: pops the top stack item, finds its
//! source GameObject (search both players' four tracked zones),
//! reads the source printing's effects via `self.registry`, and
//! dispatches each effect against the closed `Effect` enum the
//! round-3 bridge slice landed.
//!
//! Composes:
//! - round-5 stack slice (`push/pop/peek_top_of_stack`,
//!   `state.stack: Vec<StackItem>`).
//! - round-3 bridge-ext (`CardPrinting.effects: Vec<Effect>` with
//!   the `DealDamage` variant).
//! - round-3 damage slice (`deal_damage` shape — though resolve
//!   here goes straight to `players[idx].life` for AnyPlayer and
//!   to `obj.damage += amount` via `Arc::make_mut` for AnyCreature
//!   to avoid coupling slice files; once the parallel-slice
//!   constraint relaxes a follow-up consolidates onto
//!   `state_ops_damage::deal_damage`).
//!
//! ## Slice scope
//!
//! - **Supported effects: `DealDamage`, `DrawCards`, `GainLife`.**
//!   Round-3 landed `DealDamage`; round-8 foundation extended the
//!   closed enum with `DrawCards { count }` and `GainLife { amount }`,
//!   and this slice wires both to dispatch. The dispatcher is a
//!   `match` on the closed enum so adding a new variant in the
//!   bridge is a build-time error here until this file dispatches
//!   it — the desired "fail loud on unknown" property comes for
//!   free from Rust exhaustiveness.
//!   - **DrawCards: controller = active_player.** Same first-slice
//!     convention as DealDamage. The `StackItem.controller` field
//!     exists already but isn't read here — future slice plumbs it
//!     through. Empty library short-circuits silently (deck-out
//!     integration via SBA is deferred).
//!   - **GainLife: controller = active_player.** Direct field write
//!     so a negative compile-time amount silently subtracts rather
//!     than firing the round-1 `gain_life` raise-on-negative guard.
//! - **Targeting is deterministic + simplified.**
//!   - `TargetFilter::AnyPlayer` -> the defending player
//!     (`1 - active_player`). No "choose a target" surface yet.
//!   - `TargetFilter::AnyCreature` -> the FIRST object on the
//!     defending player's battlefield (smallest battlefield-Vec
//!     index). No creature-type filtering, no protection /
//!     hexproof / shroud, no per-spell target-selection. If the
//!     defender's battlefield is empty, the spell fizzles —
//!     stack item still pops, but no damage is applied.
//!   Real targeting is a future slice once the cast-time target-
//!   choice surface lands.
//! - **Post-resolve spell-source movement** (round-7 slice).
//!   Real MTG CR 608.2m: when a spell finishes resolving, the
//!   spell-as-game-object moves out of the stack zone. An instant
//!   or sorcery goes to its owner's graveyard; a permanent spell
//!   becomes a permanent on the battlefield. After applying
//!   effects, `resolve_top_of_stack` looks up the source's
//!   `card_types` and dispatches:
//!   - "Instant" / "Sorcery" -> controller's graveyard
//!   - "Creature" / "Artifact" / "Enchantment" / "Planeswalker" /
//!     "Battle" -> controller's battlefield
//!   - empty `card_types` (synthetic-test escape hatch) -> leave
//!     the source where it is. Real MTG cards always have at
//!     least one card type; this branch only fires for
//!     first-slice synthetic cards.
//!   Creatures specifically: when entering the battlefield via
//!   this path, `summoning_sick` is stamped `true` (CR 302.1 —
//!   the new permanent has summoning sickness).
//! - **ETB-triggered effects** (round-9 slice). After post-resolve
//!   movement places a permanent on the controller's battlefield,
//!   the source printing's `etb_effects: Vec<Effect>` are dispatched
//!   one-by-one through the same `apply_effect` path the spell-
//!   effects use. First-slice simplifications (mirrored in
//!   `tests_rust/test_resolve.py`):
//!   - **Apply immediately, no real stack triggering.** Real MTG:
//!     ETB triggers go onto the stack and resolve in priority
//!     order, can be responded to with instant-speed effects, and
//!     (for "deal damage" ETBs) carry their own targets chosen
//!     on-trigger. First slice applies them inline at resolution
//!     time, same convention as the spell-effects path.
//!   - **Gating: only fire when the source landed on battlefield.**
//!     If post-resolve sent the source to graveyard (instant /
//!     sorcery) or left it in place (empty card_types escape
//!     hatch), `etb_effects` are skipped — by definition the
//!     trigger condition "this enters the battlefield" wasn't met.
//!     A schema-allowed but semantically-nonsense Instant carrying
//!     an etb_effects entry will NOT fire it; only its `effects`
//!     do (the spell's effect).
//!   - **Controller of ETB effects = `state.active_player`.** Same
//!     first-slice convention as DealDamage / DrawCards / GainLife.
//!     Real MTG plumbs the trigger's controller through the trigger
//!     ability; deferred along with the rest of the
//!     `StackItem.controller` plumbing.
//!   - **No replacement effects** ("ETB tapped", "ETB with N
//!     counters") — those are CR 614.1c replacement effects, a
//!     different schema. Not in scope.
//!   - **No "leaves the battlefield" triggers (LtB)** — different
//!     schema, different timing. Future slice.
//! - **Empty stack returns None gracefully** (no exception). Same
//!   convention as `pop_top_of_stack`.
//! - **Round-14 Sacrifice** (this slice). CR 701.16 — sacrifice a
//!   target permanent (it goes to its owner's graveyard).
//!   - **AnyCreature target -> first object on the ACTIVE player's
//!     battlefield (smallest index).** Asymmetric vs the bounce/exile/
//!     tap convention: in real MTG you sacrifice your OWN permanents,
//!     not the defender's. First-slice simplification picks
//!     ``state.active_player``'s battlefield[0] (mirroring the source-
//!     spell controller convention). No creature-type filter. Empty
//!     active-battlefield fizzles silently.
//!   - **AnyPlayer target** -> raises ValueError (cannot sacrifice a
//!     player), matching the bounce/exile/tap/untap AnyPlayer shape.
//!   - **Per-object state reset on zone change** (CR 400.7) — tapped
//!     / summoning_sick / damage / counters reset on the way out, same
//!     as ReturnToHand / ExileTarget.
//!   - Inlines ``Arc::make_mut`` pop-from-battlefield + push-to-
//!     graveyard per the recurring private-helper-cross-file pattern.
//! - **Round-13 UntapTarget**. Symmetric counterpart
//!   to round-12's TapTarget — same target selection convention,
//!   opposite tap state mutation. AnyCreature target -> first object
//!   on the defender's battlefield gets ``tapped = false``. Empty
//!   defender battlefield fizzles silently. AnyPlayer raises
//!   ValueError per the bounce/exile/tap convention. Already-
//!   untapped target is a silent no-op (idempotent). Inlines
//!   ``Arc::make_mut`` + ``tapped = false`` per the recurring
//!   private-helper-cross-file pattern.
//! - **Round-11 ExileTarget**. When a permanent is
//!   exiled, the dispatch pops it from its current zone (battlefield
//!   under the AnyCreature targeting convention) and pushes onto its
//!   owner's exile zone (CR 406). Per-object state — `tapped`,
//!   `summoning_sick`, `damage`, `counters` — resets on the way out
//!   per CR 400.7 (a card that changes zones is treated as a brand-
//!   new object). Mirrors the ReturnToHand reset convention.
//!   - **AnyCreature target** -> first object on the defender's
//!     battlefield (smallest index). Empty defender battlefield
//!     fizzles silently.
//!   - **AnyPlayer target** -> raises ValueError loudly (cannot
//!     exile a player), same shape as ReturnToHand-with-AnyPlayer.
//!   - **ZONE_EXILE = 5**: the constant was already declared in
//!     `state_ops_zones.rs` (alongside `ZONE_STACK = 4`) before this
//!     slice landed; we use it rather than picking a new integer.
//!   - **Read helpers in this slice** (`exile_sizes`,
//!     `exile_contains`, `exile_object_*`): pre-r11 read methods
//!     (`find_object_zone`, `get_damage`, etc.) only walk the four
//!     tracked zones, so the slice adds an exile-only read surface
//!     locally to make the dispatch positively testable. A future
//!     consolidation slice can extend the four-zone walkers once
//!     exile has more readers.
//!
//! ## Test-fixture surface
//!
//! `register_and_inject_object(printing_dict, controller, zone) ->
//! u32` is a test-only helper that (a) parses + appends the
//! printing dict into the in-place registry via `Arc::make_mut`
//! and (b) constructs a fresh GameObject pointing at it on the
//! requested zone. Lives here (not in `state.rs`) because the
//! parallel-slice file-isolation rule prevents touching
//! `state.rs`; a follow-up consolidation slice can move this
//! into a more central location once that constraint relaxes.
//! The id assigned is `1 + max(existing object id)` so it never
//! collides with synthetic-state ids.

use crate::cards::{parse_printing, Effect, RegistryData, TargetFilter};
use crate::state::{GameObject, GameState, PendingDecision, StackItem, UeotModifier};
use crate::state_ops_decisions::auto_resolve_pending;
use crate::state_ops_zones::{
    ZONE_BATTLEFIELD, ZONE_EXILE, ZONE_GRAVEYARD, ZONE_HAND, ZONE_LIBRARY,
};
use pyo3::exceptions::{PyIndexError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::sync::Arc;

/// Build a 2-key dict from a StackItem. Mirrors the helper in
/// `state_ops_stack.rs` — duplicated here per the per-slice
/// file-isolation rule (private helpers can't be shared across
/// slice files until the consolidation slice).
fn stack_item_to_dict<'py>(
    py: Python<'py>,
    item: &StackItem,
) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("source_obj_id", item.source_obj_id)?;
    d.set_item("controller", item.controller)?;
    Ok(d)
}

/// Find the source GameObject by id across both players' four
/// tracked zones. Returns its `printing_id` (a `u32`) so the
/// caller can drop the borrow on `state` before mutating it
/// (e.g. to apply damage). Round-27 note: pre-r27 this returned a
/// full Copy of the GameObject; the UEOT-modifiers Vec made
/// GameObject `Clone` rather than `Copy`, but every caller only
/// needs the `printing_id`, so the return shape contracted to a
/// scalar.
fn find_source_printing_id(state: &GameState, obj_id: u32) -> Option<u32> {
    for player in &state.players {
        for zone in [
            &player.hand,
            &player.library,
            &player.battlefield,
            &player.graveyard,
        ] {
            for obj in zone.iter() {
                if obj.id == obj_id {
                    return Some(obj.printing_id);
                }
            }
        }
    }
    None
}

/// Take the GameObject with id `obj_id` out of whichever of the
/// four tracked zones currently holds it. Returns the owned
/// `GameObject` (and the player_idx + source_zone constant for
/// observability) so the caller can update its `zone` field and
/// push it elsewhere. CoW-safe via `Arc::make_mut`. Returns `None`
/// if no object with that id exists in any tracked zone (the
/// "lost track of source" case).
fn take_source(state: &mut GameState, obj_id: u32) -> Option<(GameObject, u8, u8)> {
    for (pidx, player) in state.players.iter_mut().enumerate() {
        for (zone_const, zone) in [
            (ZONE_HAND, &mut player.hand),
            (ZONE_LIBRARY, &mut player.library),
            (ZONE_BATTLEFIELD, &mut player.battlefield),
            (ZONE_GRAVEYARD, &mut player.graveyard),
        ] {
            if let Some(pos) = zone.iter().position(|o| o.id == obj_id) {
                let v = Arc::make_mut(zone);
                let obj = v.remove(pos);
                return Some((obj, pidx as u8, zone_const));
            }
        }
    }
    None
}

/// Decision returned by the post-resolve dispatch: what zone (if
/// any) does this card_types tuple route to? `None` = leave source
/// in place (empty card_types = synthetic-test escape hatch).
fn post_resolve_destination(card_types: &[String]) -> Option<u8> {
    let is_spell = card_types
        .iter()
        .any(|t| t == "Instant" || t == "Sorcery");
    if is_spell {
        return Some(ZONE_GRAVEYARD);
    }
    let is_permanent = card_types.iter().any(|t| {
        t == "Creature"
            || t == "Artifact"
            || t == "Enchantment"
            || t == "Planeswalker"
            || t == "Battle"
    });
    if is_permanent {
        return Some(ZONE_BATTLEFIELD);
    }
    None
}

/// True iff `card_types` includes "Creature" — gates the
/// summoning-sick stamp on battlefield entry.
fn is_creature(card_types: &[String]) -> bool {
    card_types.iter().any(|t| t == "Creature")
}

/// Apply post-resolve movement (CR 608.2m). Looks up the source
/// printing's `card_types`, dispatches to graveyard / battlefield
/// per the rules above, no-op for empty card_types. Stamps
/// `summoning_sick = true` for creatures landing on the
/// battlefield. Returns the destination zone constant (so the
/// caller can tell whether to fire ETB triggers — round-9 slice
/// gates ETB on `Some(ZONE_BATTLEFIELD)`), or `None` if the source
/// was left in place (empty card_types) or no movement happened.
fn move_source_post_resolve(state: &mut GameState, source_obj_id: u32) -> Option<u8> {
    // Pull the printing's card_types into an owned Vec so we drop
    // the registry borrow before mutating zones.
    let printing_id = find_source_printing_id(state, source_obj_id)?;
    let (destination, creature) = match state.registry.lookup(printing_id) {
        Some(printing) => (
            post_resolve_destination(&printing.card_types),
            is_creature(&printing.card_types),
        ),
        None => return None,
    };
    let dest_zone = destination?; // empty card_types — leave source in place

    // Take from current zone; if not found, treat as silent no-op.
    let (mut obj, controller, _src_zone) = take_source(state, source_obj_id)?;
    obj.zone = dest_zone;
    if dest_zone == ZONE_BATTLEFIELD && creature {
        obj.summoning_sick = true;
    }
    let player = &mut state.players[controller as usize];
    let dest = match dest_zone {
        ZONE_HAND => &mut player.hand,
        ZONE_LIBRARY => &mut player.library,
        ZONE_BATTLEFIELD => &mut player.battlefield,
        ZONE_GRAVEYARD => &mut player.graveyard,
        // Unreachable per `post_resolve_destination`'s closed
        // returns (BATTLEFIELD or GRAVEYARD only); fall back to
        // graveyard rather than panic.
        _ => &mut player.graveyard,
    };
    Arc::make_mut(dest).push(obj);
    Some(dest_zone)
}

/// Apply a single Effect to `state`. Closed-enum match: adding a
/// new variant in the bridge will turn this into a build-time
/// error (exhaustiveness) until handled here — the desired "fail
/// loud" property for free.
///
/// `source_obj_id` is the resolving stack item's source GameObject
/// id. Most arms ignore it (they target the defending player /
/// active_player / a Vec-index pick); the round-23
/// `PutPlusOneCounterOnSelf` arm needs it to locate the "self" /
/// "this creature" recipient — the source object on the
/// battlefield. Threaded through here rather than re-finding from
/// the stack so the existing borrow-then-drop pattern in
/// `resolve_top_of_stack` (snapshot effects, drop registry borrow,
/// iterate) stays intact.
/// Cross-module wrapper for `apply_effect`. Round-28
/// `state_ops_decisions.rs::auto_resolve_pending_decisions` needs to
/// recursively apply the MayDo inner effect when the strategy resolves
/// to "yes"; the private `apply_effect` isn't reachable across module
/// boundaries so we expose this thin pub wrapper.
pub(crate) fn apply_effect_pub(
    state: &mut GameState,
    effect: &Effect,
    source_obj_id: u32,
) -> PyResult<()> {
    apply_effect(state, effect, source_obj_id)
}

fn apply_effect(
    state: &mut GameState,
    effect: &Effect,
    source_obj_id: u32,
) -> PyResult<()> {
    match effect {
        Effect::DealDamage { amount, target } => {
            let defender: u8 = 1 - state.active_player;
            let amount_i32 = *amount;
            match target {
                TargetFilter::AnyPlayer => {
                    state.players[defender as usize].life -= amount_i32;
                }
                TargetFilter::AnyCreature => {
                    // First object in the defender's battlefield Vec
                    // (smallest index). No creature-type filter — see
                    // module docstring. If the battlefield is empty,
                    // the spell fizzles silently.
                    let defender_idx = defender as usize;
                    let bf = &state.players[defender_idx].battlefield;
                    if bf.is_empty() {
                        return Ok(());
                    }
                    let target_id = bf[0].id;
                    let amount_i16 = amount_i32.min(i16::MAX as i32) as i16;
                    let zone: &mut Vec<GameObject> =
                        Arc::make_mut(&mut state.players[defender_idx].battlefield);
                    for obj in zone.iter_mut() {
                        if obj.id == target_id {
                            obj.damage = obj.damage.saturating_add(amount_i16);
                            break;
                        }
                    }
                }
            }
        }
        // Round-8: DrawCards. Caller's controller draws ``count``
        // cards. Convention (mirrors the DealDamage path above): the
        // controller for a resolving spell is `state.active_player`
        // for first slice. Real MTG plumbs the controller through
        // `StackItem.controller`; deferred to a future slice.
        //
        // **Inlining note (cross-file friction).** `draw_card` is a
        // `#[pymethods]` method on `GameState` defined in
        // `state_ops_zones.rs`. Per-slice file-isolation rule
        // forbids touching that file from this slice, so we inline
        // the pop-from-library + push-to-hand logic here, mirroring
        // how round-7's counterspell agent inlined `move_object`. A
        // follow-up consolidation slice can collapse the two
        // implementations once that constraint relaxes.
        //
        // Empty-library handling (CR 704.5b — round-26 G10 closure).
        // If the library is exhausted before we've drawn `count` cards
        // we stop AND flip the player's `attempted_draw_on_empty`
        // cause-signal. The next `apply_sbas` pass transitions that
        // into the sticky `has_lost` flag; `losers()` ALSO reads the
        // cause-signal directly so the loss is observable BEFORE the
        // SBA pass runs. Mirrors Python's eager `p.has_lost = True`
        // in `turn.draw_card`.
        Effect::DrawCards { count } => {
            let controller = state.active_player as usize;
            let n = (*count).max(0) as usize;
            for _ in 0..n {
                let player = &mut state.players[controller];
                let lib = Arc::make_mut(&mut player.library);
                let Some(mut obj) = lib.pop() else {
                    // CR 704.5b — empty-library draw flags the player.
                    player.attempted_draw_on_empty = true;
                    break;
                };
                obj.zone = ZONE_HAND;
                Arc::make_mut(&mut player.hand).push(obj);
            }
        }
        // Round-8: GainLife. Caller's controller gains `amount` life.
        // Direct field write (no `gain_life` call) so a negative
        // compile-time amount silently subtracts rather than
        // tripping the round-1 raise-on-negative guard. No real MTG
        // card today wants this, but the lowest-friction shape for
        // first slice is "don't validate, just write".
        Effect::GainLife { amount } => {
            let controller = state.active_player as usize;
            state.players[controller].life += *amount;
        }
        // Round-10: ReturnToHand. Bounce a target permanent back to
        // its current controller's hand (= owner's hand in the
        // first-slice convention where controller == owner).
        //
        // Targeting (mirrors DealDamage):
        //   - AnyCreature -> first object on the DEFENDING player's
        //     battlefield (smallest index). No creature-type filter.
        //     If the defender's battlefield is empty, the spell
        //     fizzles silently.
        //   - AnyPlayer -> semantically nonsense for a bounce. Raise
        //     ValueError loudly, matching the unknown-effect-kind
        //     shape — schema-allowed but doesn't make sense.
        //
        // **Inlining note (cross-file friction).** `move_object` is a
        // private helper on `state_ops_zones.rs`; per per-slice
        // file-isolation, we inline the minimal Arc::make_mut
        // pop-from-current-zone + push-to-target-hand here, mirroring
        // how DrawCards inlines the pop-library + push-hand logic.
        Effect::ReturnToHand { target } => match target {
            TargetFilter::AnyPlayer => {
                return Err(PyValueError::new_err(
                    "ReturnToHand with AnyPlayer target is semantically nonsense (cannot bounce a player)",
                ));
            }
            TargetFilter::AnyCreature => {
                let defender = (1 - state.active_player) as usize;
                let bf = &state.players[defender].battlefield;
                if bf.is_empty() {
                    return Ok(()); // fizzle silently
                }
                let target_id = bf[0].id;
                // Pop from defender's battlefield (target's current
                // zone). Use Arc::make_mut for CoW safety.
                let bf_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[defender].battlefield);
                let pos = bf_mut
                    .iter()
                    .position(|o| o.id == target_id)
                    .expect("target_id was bf[0] but not found on re-scan");
                let mut obj = bf_mut.remove(pos);
                // First-slice: target's controller == owner. The
                // bounce sends to the target's controller's (= owner's)
                // hand — which is `defender` here, since that's
                // where the target lives.
                obj.zone = ZONE_HAND;
                obj.tapped = false;
                obj.summoning_sick = false;
                obj.damage = 0;
                obj.counters = 0;
                obj.attached_to = None;
                obj.exiled_with_source = None;
                Arc::make_mut(&mut state.players[defender].hand).push(obj);
            }
        },
        // Round-10: Mill. Caller's controller (= active_player, first-
        // slice convention) puts the top `count` cards of their
        // library into their graveyard. "Top" is the LAST element of
        // the library Vec (mirrors round-1 zones convention used by
        // DrawCards above).
        //
        // Empty library mid-mill: stop silently. Real MTG: mill on
        // empty library is NOT a deck-out by itself (unlike a draw
        // attempt — CR 704.5b applies to drawing, not milling). So a
        // silent stop is closer to real rules than the DrawCards
        // short-circuit.
        //
        // Negative `count` is silently clamped to 0 (same shape as
        // DrawCards), which is also the count-0 no-op path.
        Effect::Mill { count } => {
            let controller = state.active_player as usize;
            let n = (*count).max(0) as usize;
            for _ in 0..n {
                let player = &mut state.players[controller];
                let lib = Arc::make_mut(&mut player.library);
                let Some(mut obj) = lib.pop() else {
                    break; // empty library — silent stop
                };
                obj.zone = ZONE_GRAVEYARD;
                Arc::make_mut(&mut player.graveyard).push(obj);
            }
        }
        // MillTargetPlayer — Scrabbling Skullcrab pattern (CR 701.13b).
        // 2 cards in the EoE pool per round-20 measurement.
        //
        // **Distinct from Effect::Mill.** Mill (above) mills the
        // CONTROLLER's library — no target. MillTargetPlayer mills a
        // chosen target PLAYER's library. First-slice deterministic
        // choice: defender (= 1 - active_player), mirroring the
        // DealDamage / TapTarget / TargetOpponentLosesLife "the one
        // opponent" convention. Future multiplayer / archenemy work
        // needs an explicit choice callback.
        //
        // **Negative count raises** loudly (defense-in-depth; the
        // parse_effect bridge already checks at register time, but
        // synthetic / injected printings could bypass the parser).
        // **count=0 is a legal no-op** (mirrors GainLife / DrawCards /
        // Mill / EachOpponentLosesLife / LoseLife zero-count
        // conventions). **Fewer cards in library than `count`**: mill
        // all remaining cards (Python parity with
        // `if not target.library: break`).
        //
        // **Top-of-library = LAST element of the Vec** (round-1 zones
        // convention, mirrored by the existing Mill arm and library
        // primitives in `state_ops_library.rs`). Per-object state reset
        // on graveyard move (CR 400.7), mirroring DestroyAllCreatures /
        // DestroyTarget / ExileTarget reset shape.
        //
        // **Inlining note.** A `mill_target_player` primitive exists in
        // `state_ops_library.rs` (round-19); per the recurring per-slice
        // file-isolation pattern (E0624 cross-file `#[pymethods]`
        // friction) this arm inlines the equivalent pop-N + push-to-
        // graveyard logic. A follow-up consolidation slice can collapse
        // onto the shared primitive once cross-file private-fn calls
        // re-open.
        Effect::MillTargetPlayer { count } => {
            if *count < 0 {
                return Err(PyValueError::new_err(format!(
                    "MillTargetPlayer count must be non-negative, got {count}"
                )));
            }
            // First-slice: defender = 1 - active_player. (Targeted-
            // player choice plumbing deferred — mirrors existing
            // single-target first-slice conventions.)
            let target_idx = (1 - state.active_player) as usize;
            let library_mut = Arc::make_mut(&mut state.players[target_idx].library);
            let n_to_mill = (*count as usize).min(library_mut.len());
            if n_to_mill == 0 {
                // count=0 OR empty target library — silent no-op.
            } else {
                let mut milled: Vec<GameObject> = Vec::with_capacity(n_to_mill);
                for _ in 0..n_to_mill {
                    if let Some(obj) = library_mut.pop() {
                        milled.push(obj);
                    }
                }
                let gy_mut = Arc::make_mut(&mut state.players[target_idx].graveyard);
                for mut obj in milled {
                    obj.zone = ZONE_GRAVEYARD;
                    obj.tapped = false;
                    obj.summoning_sick = false;
                    obj.damage = 0;
                    obj.counters = 0;
                    obj.attached_to = None;
                    obj.exiled_with_source = None;
                    gy_mut.push(obj);
                }
            }
        }
        // Round-11: ExileTarget. Move a target permanent from its
        // current zone to its owner's exile zone (CR 406). First-
        // slice convention: owner == controller, so "owner's exile"
        // is the target's current controller's exile.
        //
        // Targeting (mirrors DealDamage / ReturnToHand):
        //   - AnyCreature -> first object on the DEFENDING player's
        //     battlefield (smallest index). No creature-type filter.
        //     If the defender's battlefield is empty, the spell
        //     fizzles silently.
        //   - AnyPlayer -> semantically nonsense for exile (you can't
        //     exile a player). Raise ValueError loudly, matching the
        //     ReturnToHand-with-AnyPlayer shape.
        //
        // **Inlining note (cross-file friction).** Zone movement is
        // internal here, same as the ReturnToHand / Mill / DrawCards
        // paths above — `move_object` is a private helper on
        // `state_ops_zones.rs` and per per-slice file-isolation we
        // inline the minimal Arc::make_mut pop-from-current-zone +
        // push-to-target-exile here.
        //
        // **Object-state reset on zone change.** CR 400.7: a card
        // that changes zones is treated as a brand new object — its
        // tapped / summoning_sick / damage / counters fields all
        // reset on the way to exile. Mirrors the ReturnToHand reset
        // convention.
        Effect::ExileTarget { target } => match target {
            TargetFilter::AnyPlayer => {
                return Err(PyValueError::new_err(
                    "ExileTarget with AnyPlayer target is semantically nonsense (cannot exile a player)",
                ));
            }
            TargetFilter::AnyCreature => {
                let defender = (1 - state.active_player) as usize;
                let bf = &state.players[defender].battlefield;
                if bf.is_empty() {
                    return Ok(()); // fizzle silently
                }
                let target_id = bf[0].id;
                // Pop from defender's battlefield. Use Arc::make_mut
                // for CoW safety.
                let bf_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[defender].battlefield);
                let pos = bf_mut
                    .iter()
                    .position(|o| o.id == target_id)
                    .expect("target_id was bf[0] but not found on re-scan");
                let mut obj = bf_mut.remove(pos);
                // Stamp exile zone + reset per-object state. First-
                // slice: target's controller == owner, so push onto
                // `defender`'s exile (where the target lives).
                obj.zone = ZONE_EXILE;
                obj.tapped = false;
                obj.summoning_sick = false;
                obj.damage = 0;
                obj.counters = 0;
                obj.attached_to = None;
                obj.exiled_with_source = None;
                Arc::make_mut(&mut state.players[defender].exile).push(obj);
            }
        },
        // Round-12: TapTarget. Twiddle-shaped: tap a target permanent.
        //
        // Targeting (mirrors DealDamage / ReturnToHand / ExileTarget):
        //   - AnyCreature -> first object on the DEFENDING player's
        //     battlefield (smallest index). No creature-type filter.
        //     If the defender's battlefield is empty, the spell
        //     fizzles silently.
        //   - AnyPlayer -> semantically nonsense for tap (you can't
        //     tap a player). Raise ValueError loudly, matching the
        //     ReturnToHand / ExileTarget AnyPlayer shape.
        //
        // **Idempotent on already-tapped target.** Tapping a creature
        // that's already tapped is a silent no-op (no error, no other
        // state change). Mirrors the round-1 ``tap_object`` shape
        // (which returns ``False`` rather than raising).
        //
        // **Inlining note (cross-file friction).** ``tap_object`` is a
        // private ``#[pymethods]`` method in ``state_ops_tap.rs``;
        // per per-slice file-isolation we inline the minimal
        // ``Arc::make_mut`` + ``tapped = true`` here, mirroring how
        // DrawCards / Mill / ReturnToHand / ExileTarget all inline
        // their primitives for the same reason.
        Effect::TapTarget { target } => match target {
            TargetFilter::AnyPlayer => {
                return Err(PyValueError::new_err(
                    "TapTarget with AnyPlayer target is semantically nonsense (cannot tap a player)",
                ));
            }
            TargetFilter::AnyCreature => {
                let defender = (1 - state.active_player) as usize;
                let bf = &state.players[defender].battlefield;
                if bf.is_empty() {
                    return Ok(()); // fizzle silently
                }
                let target_id = bf[0].id;
                // Flip ``tapped = true`` on the target. Idempotent:
                // already-tapped targets are silently re-stamped
                // True (no-op). Use Arc::make_mut for CoW safety.
                let bf_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[defender].battlefield);
                for obj in bf_mut.iter_mut() {
                    if obj.id == target_id {
                        obj.tapped = true;
                        break;
                    }
                }
            }
        },
        // Round-13: UntapTarget. Symmetric counterpart to
        // round-12's TapTarget — same target selection convention,
        // opposite tap state mutation.
        //
        // Targeting (mirrors DealDamage / ReturnToHand / ExileTarget /
        // TapTarget):
        //   - AnyCreature -> first object on the DEFENDING player's
        //     battlefield (smallest index). No creature-type filter.
        //     If the defender's battlefield is empty, the spell
        //     fizzles silently.
        //   - AnyPlayer -> semantically nonsense for untap (you can't
        //     untap a player). Raise ValueError loudly, matching the
        //     bounce/exile/tap AnyPlayer convention.
        //
        // **Idempotent on already-untapped target.** Untapping a
        // creature that's already untapped is a silent no-op (no
        // error, no other state change). Mirrors the round-12
        // TapTarget already-tapped idempotency shape.
        //
        // **Inlining note (cross-file friction).** ``untap_object`` is
        // a private ``#[pymethods]`` method in ``state_ops_tap.rs``;
        // per per-slice file-isolation we inline the minimal
        // ``Arc::make_mut`` + ``tapped = false`` here, mirroring how
        // round-12 TapTarget inlined its primitive for the same E0624
        // cross-file friction.
        Effect::UntapTarget { target } => match target {
            TargetFilter::AnyPlayer => {
                return Err(PyValueError::new_err(
                    "UntapTarget with AnyPlayer target is semantically nonsense (cannot untap a player)",
                ));
            }
            TargetFilter::AnyCreature => {
                let defender = (1 - state.active_player) as usize;
                let bf = &state.players[defender].battlefield;
                if bf.is_empty() {
                    return Ok(()); // fizzle silently
                }
                let target_id = bf[0].id;
                // Flip ``tapped = false`` on the target. Idempotent:
                // already-untapped targets are silently re-stamped
                // False (no-op). Use Arc::make_mut for CoW safety.
                let bf_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[defender].battlefield);
                for obj in bf_mut.iter_mut() {
                    if obj.id == target_id {
                        obj.tapped = false;
                        break;
                    }
                }
            }
        },
        // Round-14: Sacrifice. CR 701.16 — a sacrificed permanent is
        // put into its owner's graveyard.
        //
        // **Asymmetric vs the bounce/exile/tap convention.** Real MTG:
        // you sacrifice your OWN permanents (not the defender's). The
        // first-slice simplification picks ``state.active_player``'s
        // battlefield[0] (mirroring the source-spell controller
        // convention: a Sacrifice cast by the active player sacrifices
        // one of the active player's own permanents). No creature-type
        // filter, no per-spell target choice. Empty active-battlefield
        // -> fizzle silently (stack still pops).
        //
        // **AnyPlayer target raises** (semantically nonsense — you
        // can't sacrifice a player). Matches the
        // ReturnToHand/ExileTarget/TapTarget/UntapTarget AnyPlayer shape.
        //
        // **Object-state reset on zone change.** CR 400.7: a card that
        // changes zones is treated as a brand new object — its tapped
        // / summoning_sick / damage / counters fields all reset on the
        // way to graveyard. Mirrors the ReturnToHand / ExileTarget
        // reset convention.
        //
        // **Inlining note (cross-file friction).** Per per-slice file-
        // isolation, we inline the minimal Arc::make_mut pop-from-
        // battlefield + push-to-graveyard here, mirroring how
        // ReturnToHand / ExileTarget / Mill / DrawCards inline their
        // primitives for the same E0624 cross-file reason.
        Effect::Sacrifice { target } => match target {
            TargetFilter::AnyPlayer => {
                return Err(PyValueError::new_err(
                    "Sacrifice with AnyPlayer target is semantically nonsense (cannot sacrifice a player)",
                ));
            }
            TargetFilter::AnyCreature => {
                let active = state.active_player as usize;
                let bf = &state.players[active].battlefield;
                if bf.is_empty() {
                    return Ok(()); // fizzle silently
                }
                let target_id = bf[0].id;
                // Pop from active player's battlefield. Use
                // Arc::make_mut for CoW safety.
                let bf_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[active].battlefield);
                let pos = bf_mut
                    .iter()
                    .position(|o| o.id == target_id)
                    .expect("target_id was bf[0] but not found on re-scan");
                let mut obj = bf_mut.remove(pos);
                // Stamp graveyard zone + reset per-object state. First-
                // slice: target's controller == owner, so push onto
                // active player's graveyard (where the sacrificed
                // permanent's owner lives).
                obj.zone = ZONE_GRAVEYARD;
                obj.tapped = false;
                obj.summoning_sick = false;
                obj.damage = 0;
                obj.counters = 0;
                obj.attached_to = None;
                obj.exiled_with_source = None;
                Arc::make_mut(&mut state.players[active].graveyard).push(obj);
            }
        },
        // Round-15: AddCounters. Routes through round-2's signed net-
        // i32 counter model — positive `count` adds +1/+1 counters,
        // negative `count` adds -1/-1 counters; both deltas land on
        // the same i32 field via `saturating_add`. Net values can
        // freely cross zero in either direction.
        //
        // Targeting (mirrors DealDamage / TapTarget / UntapTarget /
        // ReturnToHand / ExileTarget):
        //   - AnyCreature -> first object on the DEFENDING player's
        //     battlefield (smallest index). No creature-type filter.
        //     If the defender's battlefield is empty, the spell
        //     fizzles silently.
        //   - AnyPlayer -> semantically nonsense for counters (you
        //     can't put counters on a player). Raise ValueError
        //     loudly, matching the bounce/exile/tap/untap AnyPlayer
        //     shape.
        //
        // **Inlining note (cross-file friction).** `add_counters` is a
        // private `#[pymethods]` method on `state_ops_counters.rs`; per
        // per-slice file-isolation we inline the minimal
        // `Arc::make_mut` + `saturating_add` here, mirroring how
        // TapTarget / UntapTarget / Sacrifice inlined their primitives
        // for the same E0624 cross-file reason.
        Effect::AddCounters { target, count } => match target {
            TargetFilter::AnyPlayer => {
                return Err(PyValueError::new_err(
                    "AddCounters with AnyPlayer target is semantically nonsense (cannot put counters on a player)",
                ));
            }
            TargetFilter::AnyCreature => {
                let defender = (1 - state.active_player) as usize;
                let bf = &state.players[defender].battlefield;
                if bf.is_empty() {
                    return Ok(()); // fizzle silently
                }
                let target_id = bf[0].id;
                let delta = *count;
                let bf_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[defender].battlefield);
                for obj in bf_mut.iter_mut() {
                    if obj.id == target_id {
                        obj.counters = obj.counters.saturating_add(delta);
                        break;
                    }
                }
            }
        },
        // Round-15: DiscardCard. CR 701.8 — a discarded card is put
        // into its owner's graveyard. First-slice: owner == controller,
        // so the discard lands on the target player's own graveyard.
        //
        // Targeting:
        //   - AnyPlayer -> the DEFENDING player. First-slice: the
        //     active player's spell forces the opponent to discard
        //     (Mind Rot / Wrench Mind shape). Real MTG plumbs target-
        //     player choice through the cast surface; deferred.
        //   - AnyCreature -> semantically nonsense for discard (you
        //     can't discard a creature). Raise ValueError loudly,
        //     mirrored from the bounce/exile/tap/untap AnyPlayer shape
        //     for the symmetric AnyCreature-on-DiscardCard error.
        //
        // **Deterministic choice = hand[0].** First slice picks the
        // first card in the target's hand by index (no per-spell
        // discard choice yet). Empty hand fizzles silently (stack
        // still pops, source still moves post-resolve).
        //
        // **Per-object state reset on zone change** (CR 400.7) —
        // tapped / summoning_sick / damage / counters reset on the way
        // to graveyard, mirroring the ReturnToHand / ExileTarget /
        // Sacrifice reset convention. (In practice a card in hand has
        // those fields at default already, but keep the reset for
        // schema-uniformity with the other zone-change paths.)
        //
        // **Inlining note (cross-file friction).** Per per-slice file-
        // isolation we inline the minimal `Arc::make_mut`
        // `Vec::remove(0)` + push-to-graveyard here, mirroring
        // ReturnToHand / ExileTarget / Sacrifice / Mill / DrawCards.
        Effect::DiscardCard { target } => match target {
            TargetFilter::AnyCreature => {
                return Err(PyValueError::new_err(
                    "DiscardCard with AnyCreature target is semantically nonsense (cannot discard a creature)",
                ));
            }
            TargetFilter::AnyPlayer => {
                let defender = (1 - state.active_player) as usize;
                let hand = &state.players[defender].hand;
                if hand.is_empty() {
                    return Ok(()); // fizzle silently
                }
                // Pop hand[0] (deterministic first-slice choice). Use
                // Arc::make_mut for CoW safety.
                let hand_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[defender].hand);
                let mut obj = hand_mut.remove(0);
                // Stamp graveyard zone + reset per-object state
                // (CR 400.7).
                obj.zone = ZONE_GRAVEYARD;
                obj.tapped = false;
                obj.summoning_sick = false;
                obj.damage = 0;
                obj.counters = 0;
                obj.attached_to = None;
                obj.exiled_with_source = None;
                Arc::make_mut(&mut state.players[defender].graveyard).push(obj);
            }
        },
        // Round-16: ScryN. CR 701.18 — controller looks at the top
        // ``count`` cards of their library, may put any number on the
        // bottom, the rest stay on top in any order.
        //
        // **First-slice deterministic shortcut: keep all on top.**
        // This satisfies the "scry happened" semantics without
        // requiring a decision callback to choose which cards go to
        // the bottom (deferred to a future slice that plumbs a real
        // "which to bottom" decision surface, mirroring how
        // ``StackItem.controller`` is plumbed deferred-style). Keep-
        // on-top is mechanically a no-op on the library — no zone
        // moves, no order change — so there is literally nothing to
        // mutate here.
        //
        // **Controller convention: ``state.active_player``** — same
        // first-slice shape as DrawCards / GainLife (both also
        // implicit-controller). Real MTG plumbs the spell controller
        // through ``StackItem.controller``; deferred.
        //
        // **Negative ``count`` raises** loudly (CR 701.18 doesn't
        // define Scry -1; surface it as a schema error). This differs
        // from DrawCards / Mill which silently clamp negatives to 0.
        //
        // **count > library size** clamps to library length per
        // CR 701.18d ("if there aren't enough cards in your library,
        // look at all the cards"). With keep-on-top, the clamp is also
        // a no-op — we just don't error.
        //
        // **Inlining note (cross-file friction).** Round-4 landed
        // ``apply_scry`` as a private ``#[pymethods]`` method on
        // ``state_ops_library.rs``; per per-slice file-isolation +
        // E0624 cross-file friction we'd have to inline anyway, and
        // the keep-on-top first-slice has no library mutation, so the
        // dispatch reduces to a sign check. A future slice that
        // plumbs the real "which to bottom" decision can either
        // collapse onto ``apply_scry`` (after a consolidation slice)
        // or grow the inline path here.
        Effect::ScryN { count } => {
            if *count < 0 {
                return Err(PyValueError::new_err(format!(
                    "ScryN count must be non-negative, got {count}"
                )));
            }
            // First-slice deterministic keep-on-top: no library
            // mutation needed. Empty / clamped library is a silent
            // no-op (nothing to look at, nothing to move). The
            // ``state.active_player`` reference here is the controller
            // we'd resolve against once a real decision callback
            // lands; binding a local makes the controller convention
            // explicit for future readers even though we don't
            // dispatch on it today.
            let _controller = state.active_player as usize;
        }
        // Round-17: DestroyTarget. CR 701.7 — a destroyed permanent is
        // put into its owner's graveyard.
        //
        // Targeting (mirrors DealDamage / ReturnToHand / ExileTarget /
        // TapTarget):
        //   - AnyCreature -> first object on the DEFENDING player's
        //     battlefield (smallest index). No creature-type filter.
        //     If the defender's battlefield is empty, the spell
        //     fizzles silently.
        //   - AnyPlayer -> semantically nonsense for destroy (you can't
        //     destroy a player). Raise ValueError loudly, matching the
        //     ReturnToHand / ExileTarget / TapTarget / UntapTarget /
        //     Sacrifice / AddCounters AnyPlayer shape.
        //
        // **Asymmetric vs Sacrifice.** Sacrifice picks the ACTIVE
        // player's own battlefield; DestroyTarget picks the DEFENDING
        // player's battlefield. Diverges from the "you sacrifice your
        // own permanent" semantics — destroy is the standard removal
        // shape (Murder / Doom Blade / Naturalize) targeting an
        // opponent's permanent.
        //
        // **Indestructible is honored** (CR 702.12): if the target's
        // printing has the ``indestructible`` keyword, the destroy is
        // suppressed silently — Ok(()) with no permanent movement.
        // Mirrors the round-13 SBA indestructible logic. Effect still
        // ran (no error); the stack still pops, the source still
        // moves post-resolve.
        //
        // **Object-state reset on zone change** (CR 400.7) — tapped /
        // summoning_sick / damage / counters reset on the way to
        // graveyard, mirroring the ReturnToHand / ExileTarget /
        // Sacrifice reset convention.
        //
        // **Inlining note (cross-file friction).** Per per-slice file-
        // isolation, we inline the minimal Arc::make_mut pop-from-
        // battlefield + push-to-graveyard here, mirroring how
        // Sacrifice / ExileTarget / ReturnToHand inline their
        // primitives for the same E0624 cross-file reason.
        Effect::DestroyTarget { target } => match target {
            TargetFilter::AnyPlayer => {
                return Err(PyValueError::new_err(
                    "DestroyTarget with AnyPlayer target is semantically nonsense (cannot destroy a player)",
                ));
            }
            TargetFilter::AnyCreature => {
                let defender = (1 - state.active_player) as usize;
                let bf = &state.players[defender].battlefield;
                if bf.is_empty() {
                    return Ok(()); // fizzle silently
                }
                let target_id = bf[0].id;
                // Indestructible check: peek the target's printing's
                // keywords before mutating anything. Suppress the
                // destroy silently if "indestructible" is present.
                let target_printing_id = bf[0].printing_id;
                let is_indestructible = match state.registry.lookup(target_printing_id) {
                    Some(printing) => printing
                        .keywords
                        .iter()
                        .any(|k| k == "indestructible"),
                    None => false,
                };
                if is_indestructible {
                    return Ok(()); // CR 702.12 — suppress silently
                }
                // Pop from defender's battlefield. Use Arc::make_mut
                // for CoW safety.
                let bf_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[defender].battlefield);
                let pos = bf_mut
                    .iter()
                    .position(|o| o.id == target_id)
                    .expect("target_id was bf[0] but not found on re-scan");
                let mut obj = bf_mut.remove(pos);
                // Stamp graveyard zone + reset per-object state
                // (CR 400.7). First-slice: target's controller ==
                // owner, so push onto defender's graveyard (where
                // the destroyed permanent's owner lives).
                obj.zone = ZONE_GRAVEYARD;
                obj.tapped = false;
                obj.summoning_sick = false;
                obj.damage = 0;
                obj.counters = 0;
                obj.attached_to = None;
                obj.exiled_with_source = None;
                Arc::make_mut(&mut state.players[defender].graveyard).push(obj);
            }
        },
        // Round-17: DamageEachOpponent. CR 701.4 + AOE pattern — the
        // controller deals ``amount`` damage to each of their
        // opponents.
        //
        // **Two-player engine first slice: damages the defender.** No
        // explicit target — the controller is implicit
        // (state.active_player) and the one opponent is the defender
        // (1 - active_player). Mirrors the DealDamage AnyPlayer arm
        // with implicit-defender targeting.
        //
        // **Negative ``amount`` raises** loudly (mirrors round-3
        // DealDamage's raise-on-negative shape; "deal -2 damage" is
        // schema nonsense). amount=0 is a legitimate no-op success
        // (mirrors GainLife/DrawCards/Mill zero-count conventions).
        Effect::DamageEachOpponent { amount } => {
            if *amount < 0 {
                return Err(PyValueError::new_err(format!(
                    "DamageEachOpponent amount must be non-negative, got {amount}"
                )));
            }
            let defender = (1 - state.active_player) as usize;
            state.players[defender].life -= *amount;
        }
        // Round-18: DamageEachCreature. CR 701.4 — Pyroclasm pattern:
        // mark ``damage += amount`` on every creature on every player's
        // battlefield.
        //
        // **Symmetric AOE: applies to BOTH players' battlefields.**
        // Unlike DealDamage / DestroyTarget / TapTarget (which target
        // the defender) and Sacrifice (which targets the active player),
        // DamageEachCreature is implicit-target and hits every creature
        // regardless of controller. No target filter — the variant
        // doesn't carry a TargetFilter for that reason.
        //
        // **Creature-only filter via printing's card_types.** Lands /
        // artifacts / enchantments / planeswalkers on the battlefield
        // are not touched — only objects whose printing has "Creature"
        // in card_types take the damage mark. The check goes through
        // ``state.registry.lookup(obj.printing_id)``; no fallback if
        // lookup fails (treat as non-creature, skip silently — matches
        // the "lost track of source" failure mode elsewhere).
        //
        // **Indestructible is honored at SBA time, NOT here.** This
        // slice only marks damage; SBAs decide who dies. So we do NOT
        // filter on indestructible — write damage to every creature,
        // round-13 SBA will suppress destruction for indestructible
        // ones with lethal damage. Mirrors the round-3 DealDamage shape
        // where lethal damage is also written, then SBAs reap.
        //
        // **Negative ``amount`` raises** loudly (mirrors round-3
        // DealDamage and round-17 DamageEachOpponent raise-on-negative
        // shapes). amount=0 is a legitimate no-op success (mirrors
        // GainLife / DrawCards / Mill / DamageEachOpponent zero-count
        // conventions).
        //
        // **Inlining note (cross-file friction).** Per per-slice file-
        // isolation we inline the minimal ``Arc::make_mut`` +
        // ``saturating_add`` here on each player's battlefield,
        // mirroring how round-3 DealDamage / round-15 AddCounters
        // inline their primitives for the same E0624 cross-file reason.
        Effect::DamageEachCreature { amount } => {
            if *amount < 0 {
                return Err(PyValueError::new_err(format!(
                    "DamageEachCreature amount must be non-negative, got {amount}"
                )));
            }
            let amount_i16 = (*amount).min(i16::MAX as i32) as i16;
            // Snapshot which obj_ids on each player's battlefield are
            // creatures BEFORE mutating, so we drop the registry borrow
            // before reaching for ``Arc::make_mut`` on the zone Vec.
            for pidx in 0..state.players.len() {
                let creature_ids: Vec<u32> = state.players[pidx]
                    .battlefield
                    .iter()
                    .filter_map(|obj| match state.registry.lookup(obj.printing_id) {
                        Some(printing)
                            if printing.card_types.iter().any(|t| t == "Creature") =>
                        {
                            Some(obj.id)
                        }
                        _ => None,
                    })
                    .collect();
                if creature_ids.is_empty() {
                    continue;
                }
                let bf_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[pidx].battlefield);
                for obj in bf_mut.iter_mut() {
                    if creature_ids.contains(&obj.id) {
                        obj.damage = obj.damage.saturating_add(amount_i16);
                    }
                }
            }
        }
        // Round-19: CreateToken. CR 701.6 — Servo/Soldier maker
        // pattern. The active player (= controller of the resolving
        // spell, first-slice convention mirrored from DealDamage /
        // DrawCards / GainLife) gets ``count`` fresh GameObjects on
        // their battlefield, all referencing ``token_printing_id``.
        //
        // **Each token enters with summoning sickness** (CR 302.1 —
        // fresh permanents have summoning sickness), untapped, no
        // damage, no counters, ``zone = ZONE_BATTLEFIELD``. Mirrors
        // the round-7 post-resolve creature-on-bf stamp shape (also
        // ``summoning_sick = true`` there) and the round-15
        // ``move_object_from_graveyard_to_battlefield`` reanimation
        // primitive.
        //
        // **count=0 is a legal no-op** — mirrors GainLife / DrawCards
        // / Mill / DamageEach* zero-count conventions. **count<0
        // raises** loudly, mirrors ScryN / DealDamage /
        // DamageEachOpponent / DamageEachCreature raise-on-negative.
        //
        // **Unknown ``token_printing_id``** (not present in the
        // registry) raises loudly — schema validation seam, the
        // printing must exist before you can make tokens of it.
        // Mirrors the registry-bounds check in ``load_deck``.
        //
        // **Fresh-id allocation** mirrors ``state_ops_deck.rs::
        // load_deck`` and ``register_and_inject_object``: scan every
        // zone (hand / library / battlefield / graveyard / exile) on
        // both players for the current max id, allocate sequentially
        // from ``max + 1``. Linear scan over all objects is fine
        // here — token creation is not in the hot loop and the
        // synthetic+production pools are bounded.
        //
        // **Inlining note (cross-file friction).** Per per-slice file-
        // isolation we build the GameObjects + push to the active
        // player's battlefield via ``Arc::make_mut`` directly, same
        // shape as ``load_deck`` (which lives in a sibling file we
        // can't touch from this slice).
        Effect::CreateToken {
            count,
            token_printing_id,
        } => {
            if *count < 0 {
                return Err(PyValueError::new_err(format!(
                    "CreateToken count must be non-negative, got {count}"
                )));
            }
            // Registry-bounds check up front so an unknown printing_id
            // surfaces before any state mutation (mirrors load_deck's
            // whole-or-nothing validation contract).
            let token_pid = *token_printing_id;
            if state.registry.lookup(token_pid).is_none() {
                return Err(PyValueError::new_err(format!(
                    "token_printing_id {token_pid} not in registry"
                )));
            }
            let n = *count as usize;
            if n == 0 {
                return Ok(()); // legal no-op
            }
            let active = state.active_player;

            // Allocate fresh ids: scan every zone on both players for
            // the current max id, allocate starting at max + 1.
            // Mirrors load_deck's allocator. Includes exile so r11+
            // exiled objects don't collide.
            let mut max_id: u32 = 0;
            let mut found_any = false;
            for player in &state.players {
                for zone in [
                    &player.hand,
                    &player.library,
                    &player.battlefield,
                    &player.graveyard,
                    &player.exile,
                ] {
                    for obj in zone.iter() {
                        if !found_any || obj.id > max_id {
                            max_id = obj.id;
                            found_any = true;
                        }
                    }
                }
            }
            let mut next_id: u32 = if found_any { max_id + 1 } else { 0 };

            // Push n tokens onto the active player's battlefield via
            // Arc::make_mut so a clone of the state pre-resolve keeps
            // its old battlefield Vec untouched.
            let bf: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[active as usize].battlefield);
            for _ in 0..n {
                bf.push(GameObject {
                    id: next_id,
                    printing_id: token_pid,
                    controller: active,
                    zone: ZONE_BATTLEFIELD,
                    tapped: false,
                    summoning_sick: true,
                    damage: 0,
                    counters: 0,
                    attached_to: None,
                    exiled_with_source: None,
                    ueot_modifiers: Vec::new(),
                });
                next_id += 1;
            }
        }
        // Round-23: AddManaToPool. CR 106.1 — the resolution of a mana
        // ability. The active player (= controller of the resolving
        // mana ability or stack item, first-slice convention mirrored
        // from DealDamage / DrawCards / GainLife / CreateToken) gets
        // ``amount`` mana of ``color`` credited to their pool.
        //
        // **Controller convention: ``state.active_player``** — same
        // first-slice shape as every other implicit-controller arm.
        // Real MTG plumbs the spell/ability controller through
        // ``StackItem.controller``; deferred to a future slice along
        // with the rest of the controller plumbing.
        //
        // **Negative ``amount`` raises** loudly (mirrors ScryN /
        // DealDamage / DamageEach* / CreateToken raise-on-negative
        // shape). amount=0 is a legitimate no-op success.
        //
        // **Inlining note (cross-file friction).** The Rust `add_mana`
        // primitive on `GameState` lives in `state_ops_mana.rs`
        // (round 2) — it does exactly what we need (validate
        // non-negative, slot-mut by color, saturating_add). Routing
        // through it would require a cross-`#[pymethods]` call which
        // PyO3 lets us model only via `Bound::call_method1`, an awkward
        // shape inside `apply_effect` where we already hold
        // `state: &mut GameState`. Inlining the slot match here is
        // simpler and keeps `apply_effect` as a pure-Rust dispatch.
        // A follow-up consolidation slice can collapse this onto the
        // shared primitive once cross-file private-fn calls are
        // re-enabled.
        Effect::AddManaToPool { color, amount } => {
            if *amount < 0 {
                return Err(PyValueError::new_err(format!(
                    "AddManaToPool amount must be non-negative, got {amount}"
                )));
            }
            let controller_idx = state.active_player as usize;
            let pool = &mut state.players[controller_idx].mana_pool;
            let amount_u8 = (*amount).min(u8::MAX as i32) as u8;
            match color.as_str() {
                "W" => pool.white = pool.white.saturating_add(amount_u8),
                "U" => pool.blue = pool.blue.saturating_add(amount_u8),
                "B" => pool.black = pool.black.saturating_add(amount_u8),
                "R" => pool.red = pool.red.saturating_add(amount_u8),
                "G" => pool.green = pool.green.saturating_add(amount_u8),
                "C" => pool.colorless = pool.colorless.saturating_add(amount_u8),
                other => {
                    return Err(PyValueError::new_err(format!(
                        "AddManaToPool: unknown color {other:?}; valid: W, U, B, R, G, C"
                    )))
                }
            }
        }
        // Round-23: SearchLibraryForBasicLandTapped. CR 701.19 search +
        // 701.22 shuffle. The active player (= controller of resolving
        // stack item, first-slice convention mirrored from every other
        // implicit-controller arm) searches their library for up to
        // `count` basic land cards, puts each onto the battlefield
        // tapped. Powers Rampant Growth / Beamsaw Prospector / Kavaron
        // Harrier — 15 cards in the EoE pool per round-20 measurement.
        //
        // **Deterministic first-match pick (top-to-bottom).** Library
        // is bottom-first in the Vec (lib[len-1] = top of library); scan
        // via iter().rev() to grab the topmost matching object. Real
        // MTG lets the player choose any matching card; deferred until
        // decision callbacks exist.
        //
        // **Basic-land filter: `card_types contains "Land"`.** The Rust
        // bridge has no `supertypes` field today (Python's
        // `is_basic_land` is `is_land and "Basic" in supertypes`), so
        // the basic half is approximated by the card_types Land check.
        // For the EoE pool every basic land has card_types=["Land"]
        // with no compound non-basic land carrying this dispatch path
        // (non-basic-fetch dispatches go through SearchLibraryForCard /
        // other variants), so the proxy is faithful for the current
        // set. See SEARCH_LIMITATIONS entry for the deferred supertypes
        // work.
        //
        // **No shuffle.** CR 701.19's "always shuffle after search"
        // invariant is deliberately not honored in this first slice —
        // shuffling would require threading an RNG seed through
        // `apply_effect`, and the deterministic first-match pick is
        // reproducible without one. The
        // `search_library_for_first_of_type_and_shuffle` primitive in
        // `state_ops_library.rs` is the right composition once
        // RNG-externalization lands. Documented in SEARCH_LIMITATIONS.
        //
        // **count<0 raises** loudly (defense-in-depth; parse_effect
        // catches this at register time). **count=0 is a legal no-op**
        // (mirrors GainLife / DrawCards / Mill / CreateToken zero-count
        // conventions).
        //
        // **Partial fill on early-exhaust.** If fewer than `count`
        // basic lands exist in the library, stop early silently —
        // matches Python's `next(..., None)` short-circuit on miss.
        //
        // **Per-object state on battlefield entry.** Lands enter
        // tapped (`tapped = true`) and NOT summoning-sick
        // (`summoning_sick = false` — CR 302.1 only applies to
        // creatures; a land bypassing creature-spell resolution via
        // a search effect has no summoning sickness regardless). The
        // `controller` field is stamped to the active player —
        // searching for someone else's basic land into their own
        // battlefield isn't a thing in real MTG, so first-slice the
        // searched land enters under the searcher's control.
        //
        // **Inlining note (cross-file friction).** Per per-slice file-
        // isolation we inline the search + move logic here rather
        // than calling `search_library_for_first_of_type_and_shuffle`
        // (which is a `#[pymethods]` method in
        // `state_ops_library.rs` requiring a `Bound::call_method1`
        // awkward shape inside `apply_effect`). A future
        // consolidation slice can collapse onto the shared primitive.
        Effect::SearchLibraryForBasicLandTapped { count } => {
            if *count < 0 {
                return Err(PyValueError::new_err(format!(
                    "SearchLibraryForBasicLandTapped count must be non-negative, got {count}"
                )));
            }
            let n = *count as usize;
            if n == 0 {
                return Ok(());
            }
            let controller_idx = state.active_player as usize;
            for _ in 0..n {
                // Locate the topmost basic-land match (Vec iter rev =
                // top-to-bottom). Inlined here (vs. delegating to the
                // search-only sibling) so we have the Vec INDEX for
                // removal, not just the obj_id.
                let pos: Option<usize> = {
                    let lib = &state.players[controller_idx].library;
                    let mut found: Option<usize> = None;
                    for i in (0..lib.len()).rev() {
                        let obj = &lib[i];
                        let printing = match state.registry.lookup(obj.printing_id) {
                            Some(p) => p,
                            None => continue,
                        };
                        if printing.card_types.iter().any(|t| t == "Land") {
                            found = Some(i);
                            break;
                        }
                    }
                    found
                };
                let p = match pos {
                    Some(p) => p,
                    None => break, // no more basic lands — stop early silently
                };
                let player = &mut state.players[controller_idx];
                let lib = Arc::make_mut(&mut player.library);
                let mut obj = lib.remove(p);
                // Stamp battlefield entry: tapped, not summoning-sick
                // (CR 302.1 applies to creatures; lands don't have
                // summoning sickness regardless). Controller =
                // active_player (the searcher).
                obj.zone = ZONE_BATTLEFIELD;
                obj.tapped = true;
                obj.summoning_sick = false;
                obj.controller = state.active_player;
                obj.damage = 0;
                obj.counters = 0;
                obj.attached_to = None;
                obj.exiled_with_source = None;
                Arc::make_mut(&mut player.battlefield).push(obj);
            }
            // CR 701.19 "always shuffle after search" deliberately
            // NOT honored in this first slice — see module docstring
            // + SEARCH_LIMITATIONS entry for the deferred RNG-
            // externalization work.
        }
        // Round-23: PutPlusOneCounterOnSelf. CR 122.6 + 701.13 — put
        // `amount` +1/+1 counters on the resolving spell's source
        // permanent ("this creature" / "self" target). Powers Blade
        // of the Swarm, Atomic Microsizer — 16 cards in the EoE pool
        // per round-20 measurement.
        //
        // **"Self" vs AddCounters' "defender's first creature".**
        // AddCounters deterministically picks the defending player's
        // battlefield[0] (an opponent-target shape). This arm
        // recipient = the source GameObject of the resolving stack
        // item, located via `source_obj_id` threaded through
        // `apply_effect`. Mirrors Python's `state.resolving_source`
        // lookup in `PutPlusOneCounterOnSelf.resolve`.
        //
        // **Source-not-on-battlefield = silent no-op.** Real MTG: if
        // the source has left the battlefield by the time the
        // counter resolves (e.g. it was destroyed in response to
        // the trigger), the counter "lands on nothing" / fizzles.
        // First slice honors that — we walk both players' battlefield
        // Vecs looking for an object with the matching id; if not
        // found, return Ok(()) silently. Mirrors Python's
        // `source is None` short-circuit. NOTE: this means a
        // schema-allowed Instant/Sorcery printing carrying this
        // effect (the source still sits on the stack at resolve
        // time, NOT on the battlefield) fizzles — semantically
        // nonsense ("the instant's source isn't a creature"), but
        // doesn't error.
        //
        // **amount<0 raises** loudly (defense-in-depth; parse_effect
        // catches at register time). **amount=0 is a legal no-op**
        // (mirrors GainLife / DrawCards / Mill / SearchLibrary /
        // CreateToken zero-amount conventions).
        //
        // **Round-2 net-counter model.** The positive `amount` lands
        // as a positive delta on the i32 `counters` field via
        // `saturating_add` — same shape as AddCounters' positive
        // branch.
        //
        // **Inlining note (cross-file friction).** Per per-slice
        // file-isolation we inline the battlefield scan +
        // `Arc::make_mut` + `saturating_add` here, mirroring how
        // AddCounters / DealDamage AnyCreature / TapTarget /
        // UntapTarget inline their counter-mutations.
        Effect::PutPlusOneCounterOnSelf { amount } => {
            if *amount < 0 {
                return Err(PyValueError::new_err(format!(
                    "PutPlusOneCounterOnSelf amount must be non-negative, got {amount}"
                )));
            }
            if *amount == 0 {
                return Ok(());
            }
            let delta = *amount;
            // Locate the source on a battlefield zone. If it lives
            // somewhere else (hand / library / graveyard / stack /
            // exile) the counter add fizzles silently per the docstring
            // — schema-allowed but semantically a no-op for the spell
            // / ETB / trigger that referenced "self".
            let mut found_player: Option<usize> = None;
            for (pidx, player) in state.players.iter().enumerate() {
                if player.battlefield.iter().any(|o| o.id == source_obj_id) {
                    found_player = Some(pidx);
                    break;
                }
            }
            let pidx = match found_player {
                Some(p) => p,
                None => return Ok(()), // fizzle silently
            };
            let bf_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[pidx].battlefield);
            for obj in bf_mut.iter_mut() {
                if obj.id == source_obj_id {
                    obj.counters = obj.counters.saturating_add(delta);
                    break;
                }
            }
        }
        // Round-27 G20 closure: Surveil. CR 701.43 — controller looks
        // at the top `count` cards of their library and may put any
        // number of them into their graveyard; the rest stay on top
        // in any order. Powers Appendage Amalgam, etc.
        //
        // **Sibling of ScryN (round 16).** Same look-at-top-N shape,
        // different destination zone: Scry routes chosen cards to the
        // bottom of the library; Surveil routes them to the graveyard.
        //
        // **Decision-callback substrate (Option B: state-machine).**
        // Surveil pops `count` cards (clamped to library size) off the
        // library top and packages them into a
        // `PendingDecision::SurveilChoice` on `state.pending_decisions`.
        // The Effect arm short-circuits — the cards are NOT yet in the
        // graveyard and NOT yet back on the library. The caller drains
        // via `submit_surveil_decision(top, graveyard)` (the dispatcher
        // moves each card to its chosen zone) or
        // `auto_resolve_pending_decisions("keep_all_on_top" |
        // "send_all_to_graveyard")` (the deterministic fast-path that
        // preserves r23 baseline behavior).
        //
        // **Why state-machine over Pyo3 callback (Option A).** Pending
        // decisions participate in fingerprint / clone / CoW just like
        // any other gameplay state. A `Bound<PyAny>` callback baked into
        // the apply_effect signature would not survive fingerprinting,
        // would break clone semantics (callbacks aren't cloneable across
        // a Python boundary safely), and would couple every Effect-
        // resolution call site to a Python callable — incompatible with
        // pure-Rust MCTS rollouts. Mirrors Python's pause-and-resume
        // `ResolutionSurveilDecision` shape in
        // `mtg_bot.search.resolution_channel`.
        //
        // **Controller convention: ``state.active_player``** — first-
        // slice shape consistent with ScryN / DrawCards / GainLife (all
        // implicit-controller). Real MTG plumbs the spell controller
        // through `StackItem.controller`; deferred. `source_obj_id` is
        // recorded on the SurveilChoice for log-correlation and future
        // controller-resolution work.
        //
        // **Negative ``count`` raises** loudly (CR 701.43 doesn't
        // define Surveil -1; surface it as a schema error). Mirrors
        // ScryN's negative-count rejection.
        //
        // **count > library size**: CR 701.43 clamps to library size
        // ("look at all cards in the library"). We pop `min(count,
        // library.len())` cards; the rest of the dispatch is unchanged.
        //
        // **count = 0**: legitimate no-op. We still push an empty
        // SurveilChoice so the caller's invariant (every Surveil emits
        // exactly one PendingDecision) holds; auto-resolve discards it
        // in O(1). Pre-r27 r23-baseline tests use auto-resolve via the
        // post-resolve hook, so count=0 plus auto-resolve is bit-equal
        // to the pre-r27 behavior.
        Effect::Surveil { count } => {
            if *count < 0 {
                return Err(PyValueError::new_err(format!(
                    "Surveil count must be non-negative, got {count}"
                )));
            }
            let controller = state.active_player;
            let pidx = controller as usize;
            // Clamp count to library size (CR 701.43 fold).
            let lib_len = state.players[pidx].library.len();
            let n = (*count as usize).min(lib_len);
            // Pop n cards off library TOP. Round-1 zones convention:
            // top of library = LAST element of the Vec. So we pop n
            // times from the back. Order in `cards`: cards[0] is the
            // topmost card (first popped), cards[1] is second-from-top,
            // etc. The submit dispatcher preserves this ordering when
            // routing back to the library top.
            let lib_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[pidx].library);
            let mut cards: Vec<GameObject> = Vec::with_capacity(n);
            for _ in 0..n {
                let popped = lib_mut.pop().expect(
                    "library length checked above; pop cannot fail",
                );
                cards.push(popped);
                // The card currently lives in NO zone — its `zone`
                // field is stale until the submit dispatcher writes
                // the new zone. The submit path rewrites zone before
                // pushing back to library or graveyard.
            }
            state.pending_decisions.push(PendingDecision::SurveilChoice {
                source_obj_id,
                controller,
                cards,
            });
        }
        // Round-23: CounterTargetSpell. CR 701.5 — counter target
        // spell on the stack; the countered spell moves to its
        // controller's graveyard (CR 701.6 — first slice routes to
        // controller's graveyard since owner-vs-controller tracking
        // isn't yet split out). Powers Annul, Cancel, etc. — 7 cards
        // in the EoE pool per round-20 measurement.
        //
        // **Deterministic target choice: topmost-non-self stack item.**
        // Scan the stack from top (Vec last) down, pick the first
        // `source_obj_id` that isn't this resolving effect's own
        // source — a counterspell sitting on the stack shouldn't
        // counter itself before it resolves. The `source_obj_id`
        // parameter (round-23 refactor on `apply_effect`) carries the
        // resolving stack item's source id; we exclude it here. Real
        // MTG plumbs target choice through the cast surface; first
        // slice deterministic-top-non-self mirrors the
        // "DealDamage picks defender's battlefield[0]" convention.
        //
        // **Empty stack / only-self stack: silent fizzle.** Mirrors
        // Python's `CounterTargetSpell.resolve` short-circuit on
        // `if not targets`. The Effect doesn't error; the
        // post-resolve mover still routes the spell source to the
        // graveyard, the stack still pops at the outer
        // `resolve_top_of_stack`.
        //
        // **No filter_types / no `cant_be_countered` enforcement.**
        // Python's `filter_types` (Annul's Artifact/Enchantment-only
        // restriction) and `_is_uncounterable` checks
        // (`spell_is_uncounterable`, `grants_creature_spells_uncounterable`)
        // are deferred — the Rust bridge has neither field today.
        // First slice trusts the caller picked a legal target shape,
        // same convention as the round-7 counter_spell primitive.
        //
        // **Inlining note (cross-file friction).** Round-7's
        // `counter_spell(target_obj_id) -> bool` primitive on
        // `state_ops_counterspell.rs` does exactly what we need
        // (locate stack item, remove, move source to controller's
        // graveyard). Routing through it would require
        // `Bound::call_method1` cross-`#[pymethods]` plumbing inside
        // `apply_effect` where we already hold `state: &mut GameState`
        // — the same E0624 friction every other Effect arm hit. Per
        // the recurring per-slice file-isolation pattern (every other
        // arm — DealDamage / ReturnToHand / Mill / DrawCards /
        // ExileTarget / Sacrifice / DestroyTarget / TapTarget /
        // UntapTarget / AddCounters / DiscardCard / CreateToken /
        // AddManaToPool / SearchLibraryForBasicLandTapped /
        // PutPlusOneCounterOnSelf — inlines its primitive for the
        // same reason), we inline the equivalent logic here. A
        // follow-up consolidation slice can collapse onto the shared
        // `counter_spell` primitive once cross-file private-fn calls
        // re-open.
        Effect::CounterTargetSpell => {
            // Find the topmost stack item whose source isn't this
            // effect's own source. iter().rev() walks top-to-bottom;
            // capture both the Vec index (for stack removal) and the
            // controller (for graveyard routing).
            let target: Option<(usize, u32, u8)> = state
                .stack
                .iter()
                .enumerate()
                .rev()
                .find(|(_, item)| item.source_obj_id != source_obj_id)
                .map(|(i, item)| (i, item.source_obj_id, item.controller));
            let (stack_pos, target_obj_id, target_controller) = match target {
                Some(t) => t,
                None => return Ok(()), // empty / only-self: silent fizzle
            };
            // Remove the matched stack item (inlines round-7's
            // `counter_spell` stack-removal step).
            state.stack.remove(stack_pos);
            // Best-effort: move the source GameObject to its
            // controller's graveyard (inlines round-7's
            // `move_to_graveyard` step). Sweep both players' four
            // tracked zones to find the source — mirrors how
            // `state_ops_counterspell::move_to_graveyard` itself walks
            // hand/library/battlefield/graveyard. CR 400.7 zone-change
            // reset (tapped / summoning_sick / damage / counters) is
            // applied on the way out, mirroring every other zone-move
            // arm in this file (ReturnToHand / ExileTarget / Sacrifice
            // / DestroyTarget / DiscardCard). If the source is missing
            // (lost-track-of-source failure mode), the counter still
            // "lands" — stack item removed — but the graveyard step
            // is a no-op, same tolerance the round-7 primitive shows.
            let mut taken: Option<GameObject> = None;
            'outer: for player in state.players.iter_mut() {
                for zone in [
                    &mut player.hand,
                    &mut player.library,
                    &mut player.battlefield,
                    &mut player.graveyard,
                ] {
                    if let Some(pos) = zone.iter().position(|o| o.id == target_obj_id) {
                        let v = Arc::make_mut(zone);
                        taken = Some(v.remove(pos));
                        break 'outer;
                    }
                }
            }
            if let Some(mut obj) = taken {
                obj.zone = ZONE_GRAVEYARD;
                obj.tapped = false;
                obj.summoning_sick = false;
                obj.damage = 0;
                obj.counters = 0;
                obj.attached_to = None;
                obj.exiled_with_source = None;
                obj.controller = target_controller;
                Arc::make_mut(
                    &mut state.players[target_controller as usize].graveyard,
                )
                .push(obj);
            }
        }
        // Round-24: ReturnCreatureFromYourGraveyardToBattlefield.
        // CR 400.7 (zone-change reset) + CR 302.1 (new permanent has
        // summoning sickness) — reanimate a creature card from the
        // controller's graveyard onto their battlefield. Powers Emerge
        // from the Cocoon, Reanimate-style sugar — 8 cards in the EoE
        // pool per round-20 measurement.
        //
        // **Controller = `state.active_player`** (first-slice
        // convention, same as DrawCards / GainLife / Mill /
        // SearchLibraryForBasicLandTapped / CounterTargetSpell).
        // `source_obj_id` is unused here — the target zone is "your"
        // graveyard (= controller's), not source-relative.
        //
        // **Deterministic first-creature pick.** Scan the controller's
        // graveyard in Vec iteration order (front = smallest index =
        // oldest by `move_object`-time push order); pick the first
        // object whose printing's `card_types` contains "Creature".
        // No filtering past that (no mana-value cap, no
        // creature-or-enchantment widening — see the variant's
        // docstring for the deferred Python schema). Empty graveyard
        // or no-creature-found: silent fizzle (Python parity with
        // `ReturnFromGraveyard.resolve`'s `if not targets: return`
        // short-circuit, and matches the round-17 primitive's
        // `Ok(false)` return on absent obj_id).
        //
        // **Inlining note (cross-file friction).** The round-17
        // `move_object_from_graveyard_to_battlefield(player_id,
        // obj_id)` primitive on `state_ops_zones.rs` does exactly the
        // recipient-side work we need (remove from graveyard, push
        // onto battlefield, stamp `summoning_sick = true`, zero
        // tapped / damage / counters). Per the recurring per-slice
        // file-isolation pattern (CounterTargetSpell / Sacrifice /
        // ExileTarget / ReturnToHand / DrawCards / Mill / ... all
        // inline their primitives), this arm inlines the equivalent
        // logic. A follow-up consolidation slice can collapse onto
        // the shared primitive once cross-file private-fn calls
        // re-open.
        //
        // **Registry lookup pattern.** We hold `state: &mut GameState`,
        // and `state.registry.lookup(printing_id)` returns a borrow on
        // the registry. The `find_map` closure releases each borrow on
        // each iteration; once the loop completes we hold an
        // `Option<u32>` and the registry borrow is dropped, leaving
        // the mutable state borrow free for the subsequent
        // `Arc::make_mut` calls. Mirrors the borrow-then-drop snapshot
        // pattern `resolve_top_of_stack` uses for `printing.effects`.
        // Round-25: DiscardSelf. CR 701.8 — "you discard a card."
        // The SOURCE's controller discards `amount` cards from their
        // hand. Punisher / drawback pattern (Irreverent Gremlin
        // shape) — 8 cards in the EoE pool per round-20 measurement.
        //
        // **Distinct from round-15's DiscardCard.** DiscardCard's
        // AnyPlayer branch targets the DEFENDING player (active
        // player's spell forces the opponent to discard, Mind Rot
        // shape). DiscardSelf targets the SOURCE's controller —
        // the punisher fires on whoever cast or controls the
        // source, regardless of active_player. Cross-controller-
        // active-player tests below verify the distinction.
        //
        // **Source-finder dispatch (round-23 pattern).** Threads
        // `source_obj_id` through `apply_effect` and walks both
        // players' five tracked zones (hand / library /
        // battlefield / graveyard / exile) to recover the source's
        // `controller`. Differs from
        // `PutPlusOneCounterOnSelf`'s battlefield-only scan because
        // the punisher pattern fires on whoever controls the source
        // regardless of where the source currently sits — the
        // controller field doesn't change when a permanent leaves
        // the battlefield. Additionally scans the stack: the source
        // may still be resolving (e.g. an instant/sorcery still on
        // the stack at its own resolution time), in which case the
        // `StackItem.controller` is the authoritative controller.
        //
        // **First-slice deterministic choice: discard hand[0].**
        // Mirrors round-15's `DiscardCard` arm — pop the front of
        // the controller's hand Vec by index, no per-spell discard
        // choice yet. Up to `amount` discards in a row (stop early
        // on empty hand, matching Python's `for _ in
        // range(self.amount): if not p.hand: break` shape).
        //
        // **Empty hand = silent no-op** (Python parity:
        // `DiscardSelf.resolve` short-circuits when `p.hand` is
        // empty). **Source not found anywhere = silent no-op**
        // (lost-track-of-source tolerance, mirrors
        // `PutPlusOneCounterOnSelf` / `CounterTargetSpell` fizzle
        // shape).
        //
        // **Per-object state reset on zone change** (CR 400.7) —
        // tapped / summoning_sick / damage / counters reset on the
        // way to graveyard. In practice a card in hand already has
        // defaults; the reset is kept for schema-uniformity with
        // every other zone-move arm in this file (ReturnToHand /
        // ExileTarget / Sacrifice / DiscardCard / CounterTargetSpell
        // / DestroyTarget all apply the same reset).
        //
        // **amount<0 raises** loudly (defense-in-depth;
        // parse_effect catches at register time). **amount=0 is a
        // legal no-op** (mirrors GainLife / DrawCards / Mill /
        // ScryN / CreateToken / SearchLibrary / PutPlusOneCounterOnSelf
        // zero-amount conventions).
        //
        // **Inlining note (cross-file friction).** Per the recurring
        // per-slice file-isolation pattern (DealDamage / ReturnToHand
        // / Mill / DrawCards / ExileTarget / Sacrifice / DestroyTarget
        // / TapTarget / UntapTarget / AddCounters / DiscardCard /
        // CreateToken / AddManaToPool /
        // SearchLibraryForBasicLandTapped / PutPlusOneCounterOnSelf
        // / CounterTargetSpell /
        // ReturnCreatureFromYourGraveyardToBattlefield all inline
        // their primitives), this arm inlines the minimal
        // `Arc::make_mut` + `Vec::remove(0)` + push-to-graveyard
        // here.
        Effect::DiscardSelf { amount } => {
            if *amount < 0 {
                return Err(PyValueError::new_err(format!(
                    "DiscardSelf amount must be non-negative, got {amount}"
                )));
            }
            if *amount == 0 {
                return Ok(());
            }
            // Locate the source's controller. Walk both players'
            // five tracked zones (hand / library / battlefield /
            // graveyard / exile). The source may have already moved
            // away from where it was when the effect was queued —
            // the controller is constant across zone changes so any
            // matching obj.id resolves the question.
            let mut source_controller: Option<u8> = None;
            'outer: for player in state.players.iter() {
                for zone in [
                    &player.hand,
                    &player.library,
                    &player.battlefield,
                    &player.graveyard,
                    &player.exile,
                ] {
                    for obj in zone.iter() {
                        if obj.id == source_obj_id {
                            source_controller = Some(obj.controller);
                            break 'outer;
                        }
                    }
                }
            }
            // Stack scan: the source may still be resolving (its
            // own stack item triggered this effect). `StackItem`
            // carries an authoritative `controller` field — use
            // it when the zone scan didn't find the source.
            if source_controller.is_none() {
                if let Some(item) = state
                    .stack
                    .iter()
                    .find(|i| i.source_obj_id == source_obj_id)
                {
                    source_controller = Some(item.controller);
                }
            }
            let Some(controller) = source_controller else {
                return Ok(()); // source not found anywhere: silent fizzle
            };
            let controller_idx = controller as usize;
            // Up to `amount` discards in a row. Stop early if the
            // hand goes empty mid-loop (Python parity with the
            // `if not p.hand: break` short-circuit inside the
            // amount-range loop in `DiscardSelf.resolve`).
            let target_amount = *amount as usize;
            for _ in 0..target_amount {
                if state.players[controller_idx].hand.is_empty() {
                    break;
                }
                // Pop hand[0] (deterministic first-slice choice).
                let hand_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[controller_idx].hand);
                let mut obj = hand_mut.remove(0);
                // CR 400.7 zone-change reset.
                obj.zone = ZONE_GRAVEYARD;
                obj.tapped = false;
                obj.summoning_sick = false;
                obj.damage = 0;
                obj.counters = 0;
                obj.attached_to = None;
                obj.exiled_with_source = None;
                Arc::make_mut(&mut state.players[controller_idx].graveyard)
                    .push(obj);
            }
        }
        // Round-28 coverage. Mirror of
        // ReturnCreatureFromYourGraveyardToBattlefield but destination
        // is hand. Same first-creature-in-graveyard target selection;
        // same CR 400.7 zone-change reset (tapped/damage/counters
        // zeroed). summoning_sick set to true per the r28 CE1
        // universal-true default (gameplay-irrelevant in hand zone).
        Effect::ReturnCreatureFromYourGraveyardToHand => {
            let _ = source_obj_id;
            let controller_idx = state.active_player as usize;
            let target_obj_id: Option<u32> = state.players[controller_idx]
                .graveyard
                .iter()
                .find_map(|obj| match state.registry.lookup(obj.printing_id) {
                    Some(printing)
                        if printing.card_types.iter().any(|t| t == "Creature") =>
                    {
                        Some(obj.id)
                    }
                    _ => None,
                });
            let Some(target_id) = target_obj_id else {
                return Ok(());
            };
            let graveyard_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[controller_idx].graveyard);
            let pos = graveyard_mut
                .iter()
                .position(|o| o.id == target_id)
                .expect("target_id was just found in graveyard but not on re-scan");
            let mut obj = graveyard_mut.remove(pos);
            obj.zone = ZONE_HAND;
            obj.tapped = false;
            obj.summoning_sick = true;
            obj.damage = 0;
            obj.counters = 0;
            obj.attached_to = None;
            obj.exiled_with_source = None;
            Arc::make_mut(&mut state.players[controller_idx].hand).push(obj);
        }
        Effect::ReturnCreatureFromYourGraveyardToBattlefield => {
            let _ = source_obj_id; // controller-targeted, not source-relative
            let controller_idx = state.active_player as usize;
            // Find first creature in controller's graveyard (front =
            // smallest Vec index = top of the iteration order). Drop
            // registry borrow before mutating.
            let target_obj_id: Option<u32> = state.players[controller_idx]
                .graveyard
                .iter()
                .find_map(|obj| match state.registry.lookup(obj.printing_id) {
                    Some(printing)
                        if printing.card_types.iter().any(|t| t == "Creature") =>
                    {
                        Some(obj.id)
                    }
                    _ => None,
                });
            let Some(target_id) = target_obj_id else {
                return Ok(()); // empty / no-creature: silent fizzle
            };
            // Inline the move (mirrors CounterTargetSpell / Sacrifice /
            // ExileTarget inlining — apply_effect's free-fn signature
            // makes cross-file primitive call awkward). Move from
            // graveyard to battlefield; per round-17 conv:
            // summoning_sick=true, tapped=false, damage=0, counters=0,
            // zone=ZONE_BATTLEFIELD.
            let graveyard_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[controller_idx].graveyard);
            let pos = graveyard_mut
                .iter()
                .position(|o| o.id == target_id)
                .expect("target_id was just found in graveyard but not on re-scan");
            let mut obj = graveyard_mut.remove(pos);
            obj.zone = ZONE_BATTLEFIELD;
            obj.tapped = false;
            obj.summoning_sick = true;
            obj.damage = 0;
            obj.counters = 0;
            obj.attached_to = None;
            obj.exiled_with_source = None;
            Arc::make_mut(&mut state.players[controller_idx].battlefield).push(obj);
        }
        // Round-26: EachOpponentLosesLife. CR 118.4 — "life loss"
        // (not damage). Each opponent of the SOURCE's controller
        // loses `amount` life. Punisher / drawback pattern
        // (Balemurk Leech shape) — 6 cards in the EoE pool per
        // round-20 measurement.
        //
        // **Distinct from round-17 DamageEachOpponent.** DamageEach-
        // Opponent deals DAMAGE (CR 701.4) — routes through damage-
        // prevention / Worship-style replacement effects (CR 614)
        // when those land. EachOpponentLosesLife is direct life
        // subtraction (CR 118.4) and is NOT reducible. Two-player
        // engine first slice: both arms have identical end-state for
        // the defender's life total because neither variant routes
        // through damage-prevention yet, but the variants stay
        // distinct to mirror Python's closed `Effect` vocabulary
        // (round-15 pattern). Future slices that wire damage-
        // prevention through DealDamage / DamageEachOpponent keep
        // this arm a direct subtraction.
        //
        // **Source-finder dispatch (round-24 pattern).** Walks both
        // players' five tracked zones (hand / library / battlefield
        // / graveyard / exile) plus the stack to recover the
        // source's `controller`. Mirrors DiscardSelf — punisher
        // effects fire on whoever controls the source regardless of
        // where the source currently sits, since the controller
        // field doesn't change on zone moves.
        //
        // **Two-player "each opponent" reduces to "the one opponent".**
        // opponent_id = 1 - controller. Direct life subtraction on
        // `players[opponent_idx].life`; negative life handled by
        // the SBA loop (round-5+), no clamp here.
        //
        // **amount<0 raises** loudly (defense-in-depth; parse_effect
        // catches at register time). **amount=0 is a legal no-op**
        // (mirrors GainLife / DrawCards / Mill / DamageEachOpponent /
        // DiscardSelf zero-amount conventions). **Source not found
        // anywhere = silent fizzle** (lost-track-of-source tolerance,
        // mirrors DiscardSelf shape).
        Effect::EachOpponentLosesLife { amount } => {
            if *amount < 0 {
                return Err(PyValueError::new_err(format!(
                    "EachOpponentLosesLife amount must be non-negative, got {amount}"
                )));
            }
            // Source-controller resolution mirrors round-24
            // DiscardSelf's 5-zone walk + stack scan.
            let mut source_controller: Option<u8> = None;
            'outer: for player in state.players.iter() {
                for zone in [
                    &player.hand,
                    &player.library,
                    &player.battlefield,
                    &player.graveyard,
                    &player.exile,
                ] {
                    for obj in zone.iter() {
                        if obj.id == source_obj_id {
                            source_controller = Some(obj.controller);
                            break 'outer;
                        }
                    }
                }
            }
            if source_controller.is_none() {
                if let Some(item) = state
                    .stack
                    .iter()
                    .find(|i| i.source_obj_id == source_obj_id)
                {
                    source_controller = Some(item.controller);
                }
            }
            let Some(controller) = source_controller else {
                return Ok(()); // source not found: silent fizzle
            };
            // Each opponent: the OTHER player in 2-player land.
            let opponent_id = 1 - controller;
            let opponent_idx = opponent_id as usize;
            // Direct life subtraction — not damage. Negative life is
            // handled by SBA loop.
            state.players[opponent_idx].life =
                state.players[opponent_idx].life.saturating_sub(*amount);
        }
        // LoseLife: CR 118.4 — "life loss" (not damage). The SOURCE's
        // controller loses `amount` life. Punisher / drawback pattern
        // (Decode Transmissions shape) — 7 cards in the EoE pool per
        // round-20 measurement.
        //
        // **Distinct from round-26 EachOpponentLosesLife.** Same source-
        // finder pattern (5-zone walk + stack scan), but the recipient
        // is the source's CONTROLLER (typically the caster paying a
        // self-inflicted life cost) — NOT the controller's opponent.
        // Inverted target on an otherwise identical dispatch shape.
        //
        // **Source-finder dispatch (round-24 pattern).** Walks both
        // players' five tracked zones (hand / library / battlefield /
        // graveyard / exile) plus the stack to recover the source's
        // `controller`. Mirrors EachOpponentLosesLife / DiscardSelf —
        // punisher effects fire on whoever controls the source
        // regardless of where the source currently sits, since the
        // `controller` field doesn't change on zone moves.
        //
        // **Direct life subtraction.** Negative life is handled by the
        // SBA loop (round-5+); no clamp here beyond the saturating_sub
        // that prevents underflow on the i32.
        //
        // **amount<0 raises** loudly (defense-in-depth; parse_effect
        // catches at register time). **amount=0 is a legal no-op**
        // (mirrors GainLife / DrawCards / Mill / EachOpponentLosesLife
        // / DiscardSelf zero-amount conventions). **Source not found
        // anywhere = silent fizzle** (lost-track-of-source tolerance,
        // mirrors EachOpponentLosesLife / DiscardSelf shape).
        Effect::LoseLife { amount } => {
            if *amount < 0 {
                return Err(PyValueError::new_err(format!(
                    "LoseLife amount must be non-negative, got {amount}"
                )));
            }
            // Source-controller resolution mirrors round-24
            // EachOpponentLosesLife / DiscardSelf 5-zone walk + stack
            // scan.
            let mut source_controller: Option<u8> = None;
            'outer: for player in state.players.iter() {
                for zone in [
                    &player.hand,
                    &player.library,
                    &player.battlefield,
                    &player.graveyard,
                    &player.exile,
                ] {
                    for obj in zone.iter() {
                        if obj.id == source_obj_id {
                            source_controller = Some(obj.controller);
                            break 'outer;
                        }
                    }
                }
            }
            if source_controller.is_none() {
                if let Some(item) = state
                    .stack
                    .iter()
                    .find(|i| i.source_obj_id == source_obj_id)
                {
                    source_controller = Some(item.controller);
                }
            }
            let Some(controller) = source_controller else {
                return Ok(()); // source not found: silent fizzle
            };
            let controller_idx = controller as usize;
            // CONTROLLER (not opponent) loses life — distinguishes from
            // round-26 EachOpponentLosesLife.
            state.players[controller_idx].life =
                state.players[controller_idx].life.saturating_sub(*amount);
        }
        // TargetOpponentLosesLife: CR 118.4 — "life loss" (not damage).
        // Target opponent loses `amount` life. 2 cards in EoE pool per
        // round-20 measurement (Dubious Delicacy etc.).
        //
        // **Distinct from EachOpponentLosesLife.** That arm hits ALL
        // opponents (in 2-player land = the one opponent).
        // TargetOpponentLosesLife is targeted — the caster CHOOSES which
        // opponent loses life. In a 2-player engine these collapse to
        // the same runtime effect, but the variants stay distinct to
        // mirror Python's closed Effect vocabulary (targeted vs
        // each-opponent semantics — round-15 pattern).
        //
        // **First-slice deterministic choice**: pick the one opponent
        // (= 1 - controller). Multiplayer / archenemy work needs an
        // explicit choice callback; deferred.
        //
        // **Source-finder dispatch (round-24 pattern).** Walks both
        // players' five tracked zones (hand / library / battlefield /
        // graveyard / exile) plus the stack to recover the source's
        // `controller`. Mirrors EachOpponentLosesLife / LoseLife /
        // DiscardSelf — punisher / targeted effects fire on whoever
        // controls the source regardless of where the source currently
        // sits, since the `controller` field doesn't change on zone
        // moves.
        //
        // **amount<0 raises** loudly (defense-in-depth; parse_effect
        // catches at register time). **amount=0 is a legal no-op**
        // (mirrors GainLife / DrawCards / Mill / EachOpponentLosesLife
        // / LoseLife zero-amount conventions). **Source not found
        // anywhere = silent fizzle** (lost-track-of-source tolerance,
        // mirrors EachOpponentLosesLife / LoseLife shape).
        Effect::TargetOpponentLosesLife { amount } => {
            if *amount < 0 {
                return Err(PyValueError::new_err(format!(
                    "TargetOpponentLosesLife amount must be non-negative, got {amount}"
                )));
            }
            // Source-controller resolution (mirrors round-24 /
            // round-25): 5-zone walk + stack scan.
            let mut source_controller: Option<u8> = None;
            'outer: for player in state.players.iter() {
                for zone in [
                    &player.hand,
                    &player.library,
                    &player.battlefield,
                    &player.graveyard,
                    &player.exile,
                ] {
                    for obj in zone.iter() {
                        if obj.id == source_obj_id {
                            source_controller = Some(obj.controller);
                            break 'outer;
                        }
                    }
                }
            }
            if source_controller.is_none() {
                if let Some(item) = state
                    .stack
                    .iter()
                    .find(|i| i.source_obj_id == source_obj_id)
                {
                    source_controller = Some(item.controller);
                }
            }
            let Some(controller) = source_controller else {
                return Ok(()); // source not found: silent fizzle
            };
            // 2-player: "target opponent" = the one opponent of the
            // controller. Identical runtime behavior to
            // EachOpponentLosesLife in 2-player land.
            let opponent_id = 1 - controller;
            let opponent_idx = opponent_id as usize;
            state.players[opponent_idx].life =
                state.players[opponent_idx].life.saturating_sub(*amount);
        }
        // EachOpponentDiscards: CR 701.8 — "discard a card." Each
        // opponent of the SOURCE's controller discards `count` cards.
        // Let's Play a Game pattern — 2 cards in the EoE pool per
        // round-20 measurement. Mirrors Python's
        // `EachOpponentDiscards(count: int = 1)` dataclass.
        //
        // **Distinct from round-15 DiscardCard { target: AnyPlayer }.**
        // DiscardCard's AnyPlayer arm targets the DEFENDING player
        // (active player's spell forces the opponent to discard, Mind
        // Rot / caller-targeted shape). EachOpponentDiscards fires on
        // the SOURCE's controller's opponents — source-relative,
        // independent of active_player at apply-effect time. In a
        // 2-player engine both collapse to "the one opponent discards
        // hand[0]" but the variants stay distinct to mirror Python's
        // closed Effect vocabulary (round-15 pattern).
        //
        // **Distinct from round-24 DiscardSelf.** Same source-finder +
        // hand[0]-pop primitive, but DiscardSelf fires on the
        // CONTROLLER while this arm fires on the OPPONENT of the
        // controller (= 1 - controller in 2-player land). Inverted
        // target on otherwise identical dispatch shape — composes
        // round-24 EachOpponentLosesLife's opponent-resolution with
        // round-24 DiscardSelf's discard primitive.
        //
        // **Source-finder dispatch (round-24 pattern).** Walks both
        // players' five tracked zones (hand / library / battlefield /
        // graveyard / exile) plus the stack to recover the source's
        // `controller`. Mirrors DiscardSelf / EachOpponentLosesLife —
        // punisher / source-relative effects fire on whoever controls
        // the source regardless of where the source currently sits,
        // since the `controller` field doesn't change on zone moves.
        //
        // **First-slice deterministic choice**: opponent discards
        // hand[0]. Mirrors round-15 DiscardCard + round-24 DiscardSelf
        // hand[0] convention. Up to `count` discards in a row; stop
        // early on empty hand (Python parity with `for _ in
        // range(self.count): if not p.hand: break` inside
        // `EachOpponentDiscards.resolve`).
        //
        // **Per-object state reset on zone change** (CR 400.7) —
        // tapped / summoning_sick / damage / counters reset on the way
        // to graveyard. Schema-uniform with every other zone-move arm.
        //
        // **count<0 raises** loudly (defense-in-depth; parse_effect
        // catches at register time). **count=0 is a legal no-op**
        // (mirrors DiscardSelf / GainLife / DrawCards / Mill zero-
        // count conventions). **Empty opponent hand = silent no-op**
        // (Python parity with `if not p.hand: break`). **Source not
        // found anywhere = silent fizzle** (lost-track-of-source
        // tolerance, mirrors round-24 / round-25 / round-26 shape).
        Effect::EachOpponentDiscards { count } => {
            if *count < 0 {
                return Err(PyValueError::new_err(format!(
                    "EachOpponentDiscards count must be non-negative, got {count}"
                )));
            }
            if *count == 0 {
                return Ok(());
            }
            // Source-controller resolution (mirrors round-24 /
            // round-25 / round-26 shape): 5-zone walk + stack scan.
            let mut source_controller: Option<u8> = None;
            'outer: for player in state.players.iter() {
                for zone in [
                    &player.hand,
                    &player.library,
                    &player.battlefield,
                    &player.graveyard,
                    &player.exile,
                ] {
                    for obj in zone.iter() {
                        if obj.id == source_obj_id {
                            source_controller = Some(obj.controller);
                            break 'outer;
                        }
                    }
                }
            }
            if source_controller.is_none() {
                if let Some(item) = state
                    .stack
                    .iter()
                    .find(|i| i.source_obj_id == source_obj_id)
                {
                    source_controller = Some(item.controller);
                }
            }
            let Some(controller) = source_controller else {
                return Ok(()); // source not found: silent fizzle
            };
            // 2-player "each opponent" reduces to "the one opponent".
            let opponent_idx = (1 - controller) as usize;
            let target_count = *count as usize;
            for _ in 0..target_count {
                if state.players[opponent_idx].hand.is_empty() {
                    break; // empty hand: silent no-op (Python parity)
                }
                // Pop hand[0] of the opponent (deterministic first-
                // slice choice; mirrors round-15 DiscardCard +
                // round-24 DiscardSelf hand[0] convention).
                let hand_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[opponent_idx].hand);
                let mut obj = hand_mut.remove(0);
                // CR 400.7 zone-change reset (mirrors DiscardSelf).
                obj.zone = ZONE_GRAVEYARD;
                obj.tapped = false;
                obj.summoning_sick = false;
                obj.damage = 0;
                obj.counters = 0;
                obj.attached_to = None;
                obj.exiled_with_source = None;
                Arc::make_mut(&mut state.players[opponent_idx].graveyard)
                    .push(obj);
            }
        }
        // Round-24: DestroyAllCreatures. CR 701.7 + 701.4 AOE — Wrath
        // of God pattern. Destroys every creature on the battlefield
        // (both players), honoring indestructible (CR 702.12) inline.
        Effect::DestroyAllCreatures => {
            let _ = source_obj_id; // implicit-target AOE; source not relevant
            for pidx in 0..state.players.len() {
                let destroyable_ids: Vec<u32> = state.players[pidx]
                    .battlefield
                    .iter()
                    .filter_map(|obj| {
                        let printing = state.registry.lookup(obj.printing_id)?;
                        if !printing.card_types.iter().any(|t| t == "Creature") {
                            return None;
                        }
                        if printing.keywords.iter().any(|k| k == "indestructible") {
                            return None;
                        }
                        Some(obj.id)
                    })
                    .collect();
                if destroyable_ids.is_empty() {
                    continue;
                }
                let bf_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[pidx].battlefield);
                let mut destroyed: Vec<GameObject> =
                    Vec::with_capacity(destroyable_ids.len());
                bf_mut.retain(|obj| {
                    if destroyable_ids.contains(&obj.id) {
                        destroyed.push(obj.clone());
                        false
                    } else {
                        true
                    }
                });
                let gy_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[pidx].graveyard);
                for mut obj in destroyed {
                    obj.zone = ZONE_GRAVEYARD;
                    obj.tapped = false;
                    obj.summoning_sick = false;
                    obj.damage = 0;
                    obj.counters = 0;
                    obj.attached_to = None;
                    obj.exiled_with_source = None;
                    gy_mut.push(obj);
                }
            }
        }
        // DestroyTargetNonlandPermanent. CR 701.7 with non-land filter
        // — Drag to the Roots / Drill Too Deep pattern. Scans defender's
        // battlefield top-to-bottom; picks first non-Land, non-
        // indestructible object. Empty / only-Lands / only-indestructible
        // defender bf = silent fizzle.
        Effect::DestroyTargetNonlandPermanent => {
            let defender_idx = (1 - state.active_player) as usize;
            let target_id: Option<u32> = {
                let bf = &state.players[defender_idx].battlefield;
                let registry = &state.registry;
                bf.iter().find_map(|obj| {
                    let printing = registry.lookup(obj.printing_id)?;
                    if printing.card_types.iter().any(|t| t == "Land") {
                        return None;
                    }
                    if printing.keywords.iter().any(|k| k == "indestructible") {
                        return None;
                    }
                    Some(obj.id)
                })
            };
            if let Some(target_id) = target_id {
                let bf_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[defender_idx].battlefield);
                let pos = bf_mut
                    .iter()
                    .position(|o| o.id == target_id)
                    .expect("target_id from scan but not found on re-scan");
                let mut obj = bf_mut.remove(pos);
                obj.zone = ZONE_GRAVEYARD;
                obj.tapped = false;
                obj.summoning_sick = false;
                obj.damage = 0;
                obj.counters = 0;
                obj.attached_to = None;
                obj.exiled_with_source = None;
                Arc::make_mut(&mut state.players[defender_idx].graveyard).push(obj);
            }
        }
        // DestroyTargetArtifact. CR 701.7 with Artifact filter — Drill
        // Too Deep / Scour for Scrap pattern. 2 cards in EoE pool per
        // round-20 measurement. Mirrors round-24
        // DestroyTargetNonlandPermanent line-for-line but with an
        // `card_types.contains("Artifact")` filter in place of the
        // `!card_types.contains("Land")` filter. Scans defender's
        // battlefield top-to-bottom; picks the first Artifact that is
        // not indestructible. Empty / no-artifacts /
        // only-indestructible-artifacts defender bf = silent fizzle.
        Effect::DestroyTargetArtifact => {
            let defender_idx = (1 - state.active_player) as usize;
            let target_id: Option<u32> = {
                let bf = &state.players[defender_idx].battlefield;
                let registry = &state.registry;
                bf.iter().find_map(|obj| {
                    let printing = registry.lookup(obj.printing_id)?;
                    if !printing.card_types.iter().any(|t| t == "Artifact") {
                        return None; // not an artifact
                    }
                    if printing.keywords.iter().any(|k| k == "indestructible") {
                        return None;
                    }
                    Some(obj.id)
                })
            };
            if let Some(target_id) = target_id {
                let bf_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[defender_idx].battlefield);
                let pos = bf_mut
                    .iter()
                    .position(|o| o.id == target_id)
                    .expect("target_id from scan but not found on re-scan");
                let mut obj = bf_mut.remove(pos);
                obj.zone = ZONE_GRAVEYARD;
                obj.tapped = false;
                obj.summoning_sick = false;
                obj.damage = 0;
                obj.counters = 0;
                obj.attached_to = None;
                obj.exiled_with_source = None;
                Arc::make_mut(&mut state.players[defender_idx].graveyard).push(obj);
            }
        }
        // DestroyTargetLand. CR 701.7 with Land filter — Dust Bowl /
        // Petrified Field pattern. 2 cards in EoE pool per round-20
        // measurement. Mirrors round-25 DestroyTargetArtifact
        // line-for-line but with an `card_types.contains("Land")`
        // filter in place of the `card_types.contains("Artifact")`
        // filter. Scans defender's battlefield top-to-bottom; picks
        // the first Land that is not indestructible. Empty / no-lands
        // / only-indestructible-lands defender bf = silent fizzle.
        Effect::DestroyTargetLand => {
            let defender_idx = (1 - state.active_player) as usize;
            let target_id: Option<u32> = {
                let bf = &state.players[defender_idx].battlefield;
                let registry = &state.registry;
                bf.iter().find_map(|obj| {
                    let printing = registry.lookup(obj.printing_id)?;
                    if !printing.card_types.iter().any(|t| t == "Land") {
                        return None; // not a land
                    }
                    if printing.keywords.iter().any(|k| k == "indestructible") {
                        return None;
                    }
                    Some(obj.id)
                })
            };
            if let Some(target_id) = target_id {
                let bf_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[defender_idx].battlefield);
                let pos = bf_mut
                    .iter()
                    .position(|o| o.id == target_id)
                    .expect("target_id from scan but not found on re-scan");
                let mut obj = bf_mut.remove(pos);
                obj.zone = ZONE_GRAVEYARD;
                obj.tapped = false;
                obj.summoning_sick = false;
                obj.damage = 0;
                obj.counters = 0;
                obj.attached_to = None;
                obj.exiled_with_source = None;
                Arc::make_mut(&mut state.players[defender_idx].graveyard).push(obj);
            }
        }
        // DealDamageAnyTarget — Lightning Bolt's "any target" shape
        // (CR 701.4). The "any target" filter is intrinsic to the
        // variant; distinct from the existing DealDamage variant
        // which dispatches on TargetFilter::{AnyPlayer, AnyCreature}.
        //
        // **First-slice deterministic choice**: scan the defender's
        // battlefield top-to-bottom and pick the FIRST object whose
        // printing's `card_types` contains "Creature". If none, fall
        // back to the defender-as-player life-subtraction shape. This
        // composes the AnyCreature arm's damage-write shape with the
        // AnyPlayer arm's life-subtraction shape from the existing
        // DealDamage match. Future slice plumbs an explicit choice
        // callback.
        //
        // **Negative amount raises** at register time AND here as
        // defense-in-depth (mirrors the round-3 raise-on-negative
        // shape for DealDamage's amount; registered effects already
        // validated `amount >= 0`, but synthetic / injected printings
        // could bypass the parser).
        Effect::DealDamageAnyTarget { amount } => {
            if *amount < 0 {
                return Err(PyValueError::new_err(format!(
                    "DealDamageAnyTarget amount must be non-negative, got {amount}"
                )));
            }
            let defender_idx = (1 - state.active_player) as usize;
            let amount_i16 = (*amount).min(i16::MAX as i32) as i16;
            // First-slice deterministic choice: prefer defender's
            // first creature (mirrors the AnyCreature arm's
            // type-filtered scan); fall back to defender-as-player.
            let creature_target: Option<u32> = {
                let bf = &state.players[defender_idx].battlefield;
                let registry = &state.registry;
                bf.iter().find_map(|obj| {
                    let printing = registry.lookup(obj.printing_id)?;
                    if printing.card_types.iter().any(|t| t == "Creature") {
                        Some(obj.id)
                    } else {
                        None
                    }
                })
            };
            if let Some(target_id) = creature_target {
                let bf_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[defender_idx].battlefield);
                for obj in bf_mut.iter_mut() {
                    if obj.id == target_id {
                        obj.damage = obj.damage.saturating_add(amount_i16);
                        break;
                    }
                }
            } else {
                // No creature on defender's battlefield — damage the
                // player directly. Mirror the AnyPlayer arm's
                // life-subtraction shape (raw `-=`, no saturation —
                // life is i32 and amounts are bounded by deck pool).
                state.players[defender_idx].life -= *amount;
            }
        }
        // Round-27 UEOT-framework proof. Source gets +P/+T UEOT.
        //
        // Mechanism: locate the source GameObject on whichever
        // battlefield holds it; push a
        // `UeotModifier::PowerToughnessBonus { power, toughness }`
        // entry onto the object's `ueot_modifiers` Vec. The effective
        // P/T readers in `state_ops_combat.rs` /
        // `state_ops_sba.rs::is_lethal` walk the Vec on top of
        // printed/counter values. The entry auto-expires at the
        // next `cleanup_step_for_active_player` /
        // `advance_phase`-through-PHASE_CLEANUP via the round-27
        // CR 514.3 UEOT-clear pass landed in `state_ops_cleanup.rs`.
        //
        // **Source-not-on-battlefield handling.** Mirrors the round-23
        // `PutPlusOneCounterOnSelf` arm: walk both players'
        // battlefields, no-op if the source isn't there (the source
        // could be an in-flight stack item that hasn't yet moved,
        // a graveyard-resident ability source for a future variant,
        // etc.). Python parity: `if source is None: return`.
        //
        // **0/0 bonus is a legal no-op** — registration accepts
        // it for parity edge cases. The Vec push still happens
        // (so the next cleanup-step UEOT-clear pass touches the
        // object), but downstream `ueot_power_bonus()` /
        // `ueot_toughness_bonus()` readers see zero — the only
        // observable effect is that the object goes through one
        // CoW clone on the next cleanup. Skip the Vec push when
        // both bonuses are zero, to keep the warm path allocation-
        // free.
        Effect::PumpSelfUntilEOT { power_bonus, toughness_bonus } => {
            if *power_bonus == 0 && *toughness_bonus == 0 {
                return Ok(());
            }
            // Walk both battlefields to find the source object.
            for pidx in 0..state.players.len() {
                if state.players[pidx]
                    .battlefield
                    .iter()
                    .any(|o| o.id == source_obj_id)
                {
                    let zone: &mut Vec<GameObject> =
                        Arc::make_mut(&mut state.players[pidx].battlefield);
                    for obj in zone.iter_mut() {
                        if obj.id == source_obj_id {
                            obj.ueot_modifiers.push(UeotModifier::PowerToughnessBonus {
                                power: *power_bonus,
                                toughness: *toughness_bonus,
                            });
                            break;
                        }
                    }
                    break;
                }
            }
        }
        // Round-28 UEOT-coverage extension. Same mechanism as
        // PumpSelfUntilEOT but on a TARGET creature: the first
        // creature on the source's controller's battlefield (mirrors
        // Giant Growth-style oracle text "target creature gets +X/+Y
        // UEOT" — typically cast to buff your own creature). The
        // source's controller is looked up by finding the source
        // object's `controller` field across any zone; if the source
        // can't be located (rare; resolve_top fizzle path) the spell
        // is a silent no-op.
        //
        // **Eligibility = is_creature_now on the source-controller's
        // battlefield.** First creature in zone-iteration order wins;
        // empty battlefield (or no creatures on it) fizzles silently.
        // No creature-type filter beyond `is_creature_now` (per the
        // round-23 PutPlusOneCounterOnSelf precedent that gates on
        // `card_types contains "Creature"`).
        //
        // `(0, 0)` short-circuits before doing the lookup — pure
        // no-op without touching state.
        Effect::PumpTargetCreatureUntilEOT { power_bonus, toughness_bonus } => {
            if *power_bonus == 0 && *toughness_bonus == 0 {
                return Ok(());
            }
            // Locate source controller by scanning every zone.
            // Mirrors the same "source could be anywhere" search the
            // PumpSelfUntilEOT arm uses, extended to non-battlefield
            // zones because the source spell typically resolves from
            // the stack (technically zone=stack, but the source
            // GameObject lives in whatever zone the spell came from
            // before being put on the stack — first-slice: scan all
            // tracked zones).
            let mut src_controller: Option<u8> = None;
            'outer: for player in &state.players {
                for zone in [
                    &player.hand,
                    &player.library,
                    &player.battlefield,
                    &player.graveyard,
                    &player.exile,
                ] {
                    if let Some(obj) = zone.iter().find(|o| o.id == source_obj_id) {
                        src_controller = Some(obj.controller);
                        break 'outer;
                    }
                }
            }
            let Some(controller) = src_controller else {
                return Ok(()); // source untrackable → silent fizzle
            };
            // Pick the first creature on the controller's battlefield.
            // Creature-ness gates on the printing's `card_types`
            // (mirrors state_ops_cast.rs:304 and state_ops_legal.rs:571
            // — the canonical creature-detection pattern).
            let cidx = controller as usize;
            let target_id: Option<u32> = {
                let bf = &state.players[cidx].battlefield;
                let registry = &state.registry;
                bf.iter().find_map(|obj| {
                    let printing = registry.printings.get(obj.printing_id as usize)?;
                    if printing.card_types.iter().any(|t| t == "Creature") {
                        Some(obj.id)
                    } else {
                        None
                    }
                })
            };
            let Some(target_id) = target_id else {
                return Ok(()); // no eligible creature → silent fizzle
            };
            let zone: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[cidx].battlefield);
            for obj in zone.iter_mut() {
                if obj.id == target_id {
                    obj.ueot_modifiers.push(UeotModifier::PowerToughnessBonus {
                        power: *power_bonus,
                        toughness: *toughness_bonus,
                    });
                    break;
                }
            }
        }
        // Round-28 highest-frequency-class coverage. Sequence walks
        // its child Vec in order, calling apply_effect recursively on
        // each child with the same source_obj_id. Children share
        // resolve-time state — a Sequence of
        // [DrawCards { count: 1 }, DiscardSelf] resolves to "draw,
        // then discard" (a looting effect). Empty Vec is a legal
        // no-op. Recursion is safe: Effect is heap-allocated via
        // Vec<Effect>, and apply_effect is a regular function.
        Effect::Sequence { effects } => {
            for child in effects {
                apply_effect(state, child, source_obj_id)?;
            }
        }
        // Round-28 anthem-shape UEOT effect. Iterates every creature
        // on the source's controller's battlefield and pushes a
        // UeotModifier::PowerToughnessBonus onto each. Creature
        // eligibility gates on `card_types contains "Creature"`
        // (mirrors PumpTargetCreatureUntilEOT's predicate).
        //
        // `(0, 0)` short-circuits before doing the scan. Empty
        // battlefield or no eligible creatures is a silent no-op.
        Effect::PumpCreaturesYouControlUntilEOT { power_bonus, toughness_bonus } => {
            if *power_bonus == 0 && *toughness_bonus == 0 {
                return Ok(());
            }
            // Locate source controller (mirrors DiscardSelf /
            // PumpTargetCreatureUntilEOT pattern).
            let mut src_controller: Option<u8> = None;
            'outer: for player in &state.players {
                for zone in [
                    &player.hand,
                    &player.library,
                    &player.battlefield,
                    &player.graveyard,
                    &player.exile,
                ] {
                    if let Some(obj) = zone.iter().find(|o| o.id == source_obj_id) {
                        src_controller = Some(obj.controller);
                        break 'outer;
                    }
                }
            }
            if src_controller.is_none() {
                if let Some(item) = state
                    .stack
                    .iter()
                    .find(|i| i.source_obj_id == source_obj_id)
                {
                    src_controller = Some(item.controller);
                }
            }
            let Some(controller) = src_controller else {
                return Ok(());
            };
            let cidx = controller as usize;
            // Collect creature ids first (immutable borrow on
            // registry + battlefield), then apply mutations.
            let creature_ids: Vec<u32> = {
                let bf = &state.players[cidx].battlefield;
                let registry = &state.registry;
                bf.iter()
                    .filter_map(|obj| {
                        let printing = registry.printings.get(obj.printing_id as usize)?;
                        if printing.card_types.iter().any(|t| t == "Creature") {
                            Some(obj.id)
                        } else {
                            None
                        }
                    })
                    .collect()
            };
            if creature_ids.is_empty() {
                return Ok(());
            }
            let zone: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[cidx].battlefield);
            for obj in zone.iter_mut() {
                if creature_ids.contains(&obj.id) {
                    obj.ueot_modifiers.push(UeotModifier::PowerToughnessBonus {
                        power: *power_bonus,
                        toughness: *toughness_bonus,
                    });
                }
            }
        }
        // Round-28 coverage extension. Atmospheric-Greenhouse-shape:
        // put `amount` +1/+1 counter(s) on each creature the source's
        // controller controls. Per-object scalar mutation; non-creature
        // permanents skipped. amount=0 short-circuits; negative raises
        // (defense-in-depth — parse_effect catches at register time).
        Effect::PutPlusOneCounterOnEachCreatureYouControl { amount } => {
            if *amount < 0 {
                return Err(PyValueError::new_err(format!(
                    "PutPlusOneCounterOnEachCreatureYouControl amount must be non-negative, got {amount}"
                )));
            }
            if *amount == 0 {
                return Ok(());
            }
            // Locate source controller (mirrors PumpCreaturesYouControl).
            let mut src_controller: Option<u8> = None;
            'outer: for player in &state.players {
                for zone in [
                    &player.hand,
                    &player.library,
                    &player.battlefield,
                    &player.graveyard,
                    &player.exile,
                ] {
                    if let Some(obj) = zone.iter().find(|o| o.id == source_obj_id) {
                        src_controller = Some(obj.controller);
                        break 'outer;
                    }
                }
            }
            if src_controller.is_none() {
                if let Some(item) = state
                    .stack
                    .iter()
                    .find(|i| i.source_obj_id == source_obj_id)
                {
                    src_controller = Some(item.controller);
                }
            }
            let Some(controller) = src_controller else {
                return Ok(());
            };
            let cidx = controller as usize;
            let creature_ids: Vec<u32> = {
                let bf = &state.players[cidx].battlefield;
                let registry = &state.registry;
                bf.iter()
                    .filter_map(|obj| {
                        let printing = registry.printings.get(obj.printing_id as usize)?;
                        if printing.card_types.iter().any(|t| t == "Creature") {
                            Some(obj.id)
                        } else {
                            None
                        }
                    })
                    .collect()
            };
            if creature_ids.is_empty() {
                return Ok(());
            }
            let delta = *amount;
            let zone: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[cidx].battlefield);
            for obj in zone.iter_mut() {
                if creature_ids.contains(&obj.id) {
                    obj.counters = obj.counters.saturating_add(delta);
                }
            }
        }
        // Round-28 single-target counter add. Rayblade-Trooper-shape:
        // pick the FIRST creature on source-controller's bf and add
        // `amount` to its `counters` scalar. Empty bf or no eligible
        // creatures fizzles silently. amount=0 short-circuits;
        // negative raises.
        Effect::PutPlusOneCounterOnCreatureYouControl { amount } => {
            if *amount < 0 {
                return Err(PyValueError::new_err(format!(
                    "PutPlusOneCounterOnCreatureYouControl amount must be non-negative, got {amount}"
                )));
            }
            if *amount == 0 {
                return Ok(());
            }
            // Locate source controller.
            let mut src_controller: Option<u8> = None;
            'outer: for player in &state.players {
                for zone in [
                    &player.hand,
                    &player.library,
                    &player.battlefield,
                    &player.graveyard,
                    &player.exile,
                ] {
                    if let Some(obj) = zone.iter().find(|o| o.id == source_obj_id) {
                        src_controller = Some(obj.controller);
                        break 'outer;
                    }
                }
            }
            if src_controller.is_none() {
                if let Some(item) = state
                    .stack
                    .iter()
                    .find(|i| i.source_obj_id == source_obj_id)
                {
                    src_controller = Some(item.controller);
                }
            }
            let Some(controller) = src_controller else {
                return Ok(());
            };
            let cidx = controller as usize;
            // Pick first creature on controller's bf.
            let target_id: Option<u32> = {
                let bf = &state.players[cidx].battlefield;
                let registry = &state.registry;
                bf.iter().find_map(|obj| {
                    let printing = registry.printings.get(obj.printing_id as usize)?;
                    if printing.card_types.iter().any(|t| t == "Creature") {
                        Some(obj.id)
                    } else {
                        None
                    }
                })
            };
            let Some(target_id) = target_id else {
                return Ok(());
            };
            let delta = *amount;
            let zone: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[cidx].battlefield);
            for obj in zone.iter_mut() {
                if obj.id == target_id {
                    obj.counters = obj.counters.saturating_add(delta);
                    break;
                }
            }
        }
        // Round-28 Lotus-Field-shape mana minting. First-slice
        // deterministic color choice: pick options[0]. Mirrors
        // Python's "no-agent-seated" fallback. amount=0 is a no-op;
        // negative raises (defense-in-depth, parse catches at register
        // time). Empty options Vec would have failed at parse — treat
        // as defensive invariant here.
        Effect::AddNManaOfChosenColor { amount, options } => {
            if *amount < 0 {
                return Err(PyValueError::new_err(format!(
                    "AddNManaOfChosenColor amount must be non-negative, got {amount}"
                )));
            }
            if *amount == 0 {
                return Ok(());
            }
            let Some(chosen) = options.first() else {
                return Err(PyValueError::new_err(
                    "AddNManaOfChosenColor: options is empty",
                ));
            };
            // Source controller (mirrors AddManaToPool's active-player
            // shape — first-slice convention).
            let mut src_controller: Option<u8> = None;
            'outer: for player in &state.players {
                for zone in [
                    &player.hand,
                    &player.library,
                    &player.battlefield,
                    &player.graveyard,
                    &player.exile,
                ] {
                    if let Some(obj) = zone.iter().find(|o| o.id == source_obj_id) {
                        src_controller = Some(obj.controller);
                        break 'outer;
                    }
                }
            }
            if src_controller.is_none() {
                if let Some(item) = state
                    .stack
                    .iter()
                    .find(|i| i.source_obj_id == source_obj_id)
                {
                    src_controller = Some(item.controller);
                }
            }
            let controller_idx = match src_controller {
                Some(c) => c as usize,
                None => state.active_player as usize,
            };
            let amount_u8 = (*amount).min(u8::MAX as i32) as u8;
            let pool = &mut state.players[controller_idx].mana_pool;
            match chosen.as_str() {
                "W" => pool.white = pool.white.saturating_add(amount_u8),
                "U" => pool.blue = pool.blue.saturating_add(amount_u8),
                "B" => pool.black = pool.black.saturating_add(amount_u8),
                "R" => pool.red = pool.red.saturating_add(amount_u8),
                "G" => pool.green = pool.green.saturating_add(amount_u8),
                "C" => pool.colorless = pool.colorless.saturating_add(amount_u8),
                other => {
                    return Err(PyValueError::new_err(format!(
                        "AddNManaOfChosenColor: unknown color {other:?}; valid: W, U, B, R, G, C"
                    )));
                }
            }
        }
        // Round-28 generalized library tutor. Scans the source-
        // controller's library top-to-bottom for the FIRST card
        // matching filter_name; moves match to controller's hand
        // (revealing implicit). Unknown filter_name silently fizzles
        // (matches Python's _matches default-False). Deferred: shuffle
        // (G19), Legendary/subtype filters (no supertypes/subtypes in
        // Rust registry), may_fail interactive choice (no decision
        // callback yet for "decline fetch").
        Effect::SearchLibraryForCard {
            filter_name,
            max_mv,
            may_fail: _,
        } => {
            // Locate source controller.
            let mut src_controller: Option<u8> = None;
            'outer: for player in &state.players {
                for zone in [
                    &player.hand,
                    &player.library,
                    &player.battlefield,
                    &player.graveyard,
                    &player.exile,
                ] {
                    if let Some(obj) = zone.iter().find(|o| o.id == source_obj_id) {
                        src_controller = Some(obj.controller);
                        break 'outer;
                    }
                }
            }
            if src_controller.is_none() {
                if let Some(item) = state
                    .stack
                    .iter()
                    .find(|i| i.source_obj_id == source_obj_id)
                {
                    src_controller = Some(item.controller);
                }
            }
            let cidx = match src_controller {
                Some(c) => c as usize,
                None => state.active_player as usize,
            };
            // Top-to-bottom scan via iter().rev() (lib[len-1] is top).
            let max_mv_local = *max_mv;
            let pos: Option<usize> = {
                let lib = &state.players[cidx].library;
                let registry = &state.registry;
                let mut found: Option<usize> = None;
                for i in (0..lib.len()).rev() {
                    let obj = &lib[i];
                    let printing = match registry.lookup(obj.printing_id) {
                        Some(p) => p,
                        None => continue,
                    };
                    let matches = match filter_name.as_str() {
                        "basic_land" => printing.card_types.iter().any(|t| t == "Land"),
                        "basic_plains" => &*printing.name == "Plains",
                        "basic_island" => &*printing.name == "Island",
                        "basic_swamp" => &*printing.name == "Swamp",
                        "basic_mountain" => &*printing.name == "Mountain",
                        "basic_forest" => &*printing.name == "Forest",
                        "creature_small" => {
                            if !printing.card_types.iter().any(|t| t == "Creature") {
                                false
                            } else {
                                let mc = &printing.mana_cost;
                                let total = mc.generic as i32
                                    + mc.white as i32
                                    + mc.blue as i32
                                    + mc.black as i32
                                    + mc.red as i32
                                    + mc.green as i32;
                                total <= max_mv_local
                            }
                        }
                        "artifact" => printing.card_types.iter().any(|t| t == "Artifact"),
                        _ => false, // unknown filter → fizzle
                    };
                    if matches {
                        found = Some(i);
                        break;
                    }
                }
                found
            };
            let Some(p) = pos else {
                return Ok(()); // no match → silent fizzle
            };
            let player = &mut state.players[cidx];
            let lib = Arc::make_mut(&mut player.library);
            let mut obj = lib.remove(p);
            obj.zone = ZONE_HAND;
            obj.tapped = false;
            obj.summoning_sick = true; // r28 CE1 universal-true default
            obj.controller = cidx as u8;
            obj.damage = 0;
            obj.counters = 0;
            obj.attached_to = None;
            obj.exiled_with_source = None;
            Arc::make_mut(&mut player.hand).push(obj);
            // No shuffle (G19 deferral).
        }
        // Round-28 debuff anthem. Mirror of
        // PumpCreaturesYouControlUntilEOT but on the source-
        // controller's OPPONENTS' battlefields. Two-player engine
        // simplification: opponents = the one player whose id is
        // 1 - controller. (0, 0) short-circuits; empty opponent bf or
        // no creatures fizzles silently.
        Effect::PumpCreaturesOpponentsControlUntilEOT {
            power_bonus,
            toughness_bonus,
        } => {
            if *power_bonus == 0 && *toughness_bonus == 0 {
                return Ok(());
            }
            // Source controller lookup.
            let mut src_controller: Option<u8> = None;
            'outer: for player in &state.players {
                for zone in [
                    &player.hand,
                    &player.library,
                    &player.battlefield,
                    &player.graveyard,
                    &player.exile,
                ] {
                    if let Some(obj) = zone.iter().find(|o| o.id == source_obj_id) {
                        src_controller = Some(obj.controller);
                        break 'outer;
                    }
                }
            }
            if src_controller.is_none() {
                if let Some(item) = state
                    .stack
                    .iter()
                    .find(|i| i.source_obj_id == source_obj_id)
                {
                    src_controller = Some(item.controller);
                }
            }
            let Some(controller) = src_controller else {
                return Ok(());
            };
            let opponent_idx = (1 - controller) as usize;
            let creature_ids: Vec<u32> = {
                let bf = &state.players[opponent_idx].battlefield;
                let registry = &state.registry;
                bf.iter()
                    .filter_map(|obj| {
                        let printing = registry.printings.get(obj.printing_id as usize)?;
                        if printing.card_types.iter().any(|t| t == "Creature") {
                            Some(obj.id)
                        } else {
                            None
                        }
                    })
                    .collect()
            };
            if creature_ids.is_empty() {
                return Ok(());
            }
            let zone: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[opponent_idx].battlefield);
            for obj in zone.iter_mut() {
                if creature_ids.contains(&obj.id) {
                    obj.ueot_modifiers.push(UeotModifier::PowerToughnessBonus {
                        power: *power_bonus,
                        toughness: *toughness_bonus,
                    });
                }
            }
        }
        // Round-28 graveyard-to-library-bottom move. Scans
        // graveyards in player order; takes graveyard[0] (first card)
        // from whichever player has a non-empty graveyard; moves to
        // that player's library bottom (lib[0] per Rust's convention).
        // Empty-graveyards-both-sides = silent fizzle.
        Effect::PutCardFromGraveyardOnBottomOfLibrary => {
            let _ = source_obj_id;
            let mut found: Option<usize> = None;
            for (pidx, player) in state.players.iter().enumerate() {
                if !player.graveyard.is_empty() {
                    found = Some(pidx);
                    break;
                }
            }
            let Some(pidx) = found else {
                return Ok(()); // no graveyards have any cards
            };
            let gy_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[pidx].graveyard);
            let mut obj = gy_mut.remove(0);
            obj.zone = ZONE_LIBRARY;
            obj.tapped = false;
            obj.summoning_sick = true; // r28 CE1 universal-true default
            obj.damage = 0;
            obj.counters = 0;
            obj.attached_to = None;
            obj.exiled_with_source = None;
            let lib_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[pidx].library);
            lib_mut.insert(0, obj); // bottom of library
        }
        // Round-28 Dockworker-Drone-shape counter move. Transfer the
        // source's counters scalar to the first creature on the
        // source-controller's battlefield; clear source's counters
        // on transfer (true "move" semantics, see variant docstring).
        // No-op if source has 0 counters, isn't found, has no
        // controller, or no creature exists on controller's bf.
        Effect::MoveSelfCountersToTargetCreatureYouControl => {
            // Find source: pull counter count + controller. Search all
            // zones (typical use is dies-trigger so source may be in
            // graveyard).
            let mut src_info: Option<(u8, usize, i32)> = None; // (controller, player_idx, count)
            'outer: for (pidx, player) in state.players.iter().enumerate() {
                for zone in [
                    &player.hand,
                    &player.library,
                    &player.battlefield,
                    &player.graveyard,
                    &player.exile,
                ] {
                    if let Some(obj) = zone.iter().find(|o| o.id == source_obj_id) {
                        src_info = Some((obj.controller, pidx, obj.counters));
                        break 'outer;
                    }
                }
            }
            let (controller, _src_player_idx, src_counters) = match src_info {
                Some(info) => info,
                None => return Ok(()), // source not found → fizzle
            };
            if src_counters <= 0 {
                return Ok(()); // nothing to move
            }
            let cidx = controller as usize;
            let target_id: Option<u32> = {
                let bf = &state.players[cidx].battlefield;
                let registry = &state.registry;
                bf.iter().find_map(|obj| {
                    let printing = registry.printings.get(obj.printing_id as usize)?;
                    if printing.card_types.iter().any(|t| t == "Creature") {
                        Some(obj.id)
                    } else {
                        None
                    }
                })
            };
            let Some(target_id) = target_id else {
                return Ok(()); // no eligible target → fizzle
            };
            // Clear source's counters (true move). Source may be on
            // battlefield, graveyard, or anywhere — walk every zone
            // to flip it. Skip if source IS the target (same obj id),
            // which is a degenerate self-target case.
            if source_obj_id != target_id {
                for player in state.players.iter_mut() {
                    for zone in [
                        &mut player.hand,
                        &mut player.library,
                        &mut player.battlefield,
                        &mut player.graveyard,
                        &mut player.exile,
                    ] {
                        if zone.iter().any(|o| o.id == source_obj_id) {
                            let z = Arc::make_mut(zone);
                            for obj in z.iter_mut() {
                                if obj.id == source_obj_id {
                                    obj.counters = 0;
                                    break;
                                }
                            }
                        }
                    }
                }
            }
            // Add to target on controller's battlefield.
            let bf_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[cidx].battlefield);
            for obj in bf_mut.iter_mut() {
                if obj.id == target_id {
                    obj.counters = obj.counters.saturating_add(src_counters);
                    break;
                }
            }
        }
        // Round-28 power-scaling damage spell (Mishra's Bauble shape).
        // Compute source's effective power inline, then route through
        // the same any-target selection as DealDamageAnyTarget.
        Effect::DealDamageEqualToSourcePowerAnyTarget => {
            // Look up source on either battlefield to get printed power
            // and UEOT bonus. If source isn't on battlefield, effective
            // power is 0 → no damage.
            let mut amount: i32 = 0;
            for player in &state.players {
                if let Some(obj) = player.battlefield.iter().find(|o| o.id == source_obj_id)
                {
                    if let Some(printing) =
                        state.registry.printings.get(obj.printing_id as usize)
                    {
                        let base = printing.power.unwrap_or(0) as i32;
                        let bonus = obj.ueot_power_bonus();
                        amount = (base + bonus).max(0);
                    }
                    break;
                }
            }
            if amount == 0 {
                return Ok(());
            }
            // Reuse DealDamageAnyTarget's selection shape.
            let defender_idx = (1 - state.active_player) as usize;
            let creature_target: Option<u32> = {
                let bf = &state.players[defender_idx].battlefield;
                let registry = &state.registry;
                bf.iter().find_map(|obj| {
                    let printing = registry.lookup(obj.printing_id)?;
                    if printing.card_types.iter().any(|t| t == "Creature") {
                        Some(obj.id)
                    } else {
                        None
                    }
                })
            };
            let amount_i16 = amount.min(i16::MAX as i32) as i16;
            if let Some(target_id) = creature_target {
                let bf_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[defender_idx].battlefield);
                for obj in bf_mut.iter_mut() {
                    if obj.id == target_id {
                        obj.damage = obj.damage.saturating_add(amount_i16);
                        break;
                    }
                }
            } else {
                state.players[defender_idx].life -= amount;
            }
        }
        // Round-28 broader-filter tap. Pick first defender permanent
        // whose printing's card_types contains "Artifact" OR
        // "Creature". Idempotent on already-tapped target. No
        // eligible target → silent fizzle.
        Effect::TapTargetArtifactOrCreature => {
            let defender = (1 - state.active_player) as usize;
            let target_id: Option<u32> = {
                let bf = &state.players[defender].battlefield;
                let registry = &state.registry;
                bf.iter().find_map(|obj| {
                    let printing = registry.lookup(obj.printing_id)?;
                    if printing.card_types.iter().any(|t| t == "Artifact" || t == "Creature")
                    {
                        Some(obj.id)
                    } else {
                        None
                    }
                })
            };
            let Some(target_id) = target_id else {
                return Ok(()); // fizzle
            };
            let bf_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[defender].battlefield);
            for obj in bf_mut.iter_mut() {
                if obj.id == target_id {
                    obj.tapped = true;
                    break;
                }
            }
        }
        // Round-28 intervening-if conditional. Count source-
        // controller's tapped creatures; if >= min_count, recursively
        // apply nested effect. Otherwise silent no-op.
        Effect::ConditionalOnTappedCreatures { effect, min_count } => {
            // Locate source controller.
            let mut src_controller: Option<u8> = None;
            'outer: for player in &state.players {
                for zone in [
                    &player.hand,
                    &player.library,
                    &player.battlefield,
                    &player.graveyard,
                    &player.exile,
                ] {
                    if let Some(obj) = zone.iter().find(|o| o.id == source_obj_id) {
                        src_controller = Some(obj.controller);
                        break 'outer;
                    }
                }
            }
            if src_controller.is_none() {
                if let Some(item) = state
                    .stack
                    .iter()
                    .find(|i| i.source_obj_id == source_obj_id)
                {
                    src_controller = Some(item.controller);
                }
            }
            let Some(controller) = src_controller else {
                return Ok(()); // source not found → silent fizzle
            };
            let cidx = controller as usize;
            // Count tapped creatures on controller's battlefield.
            let tapped_count: i32 = {
                let bf = &state.players[cidx].battlefield;
                let registry = &state.registry;
                bf.iter()
                    .filter(|obj| {
                        if !obj.tapped {
                            return false;
                        }
                        let Some(printing) = registry.printings.get(obj.printing_id as usize)
                        else {
                            return false;
                        };
                        printing.card_types.iter().any(|t| t == "Creature")
                    })
                    .count() as i32
            };
            if tapped_count >= *min_count {
                apply_effect(state, effect.as_ref(), source_obj_id)?;
            }
            // else: silent no-op
        }
        // Round-28 multi-target counter add (Weftblade-Enhancer-shape).
        // Pick first min(max_n, eligible) creatures across both
        // battlefields in player-order (source controller first, then
        // opponent), add a +1/+1 counter to each. max_n=0 short-
        // circuits.
        Effect::PutPlusOneCounterOnEachOfUpToNTargetCreatures { max_n } => {
            if *max_n <= 0 {
                return Ok(());
            }
            // Locate source controller.
            let mut src_controller: Option<u8> = None;
            'outer: for player in &state.players {
                for zone in [
                    &player.hand,
                    &player.library,
                    &player.battlefield,
                    &player.graveyard,
                    &player.exile,
                ] {
                    if let Some(obj) = zone.iter().find(|o| o.id == source_obj_id) {
                        src_controller = Some(obj.controller);
                        break 'outer;
                    }
                }
            }
            if src_controller.is_none() {
                if let Some(item) = state
                    .stack
                    .iter()
                    .find(|i| i.source_obj_id == source_obj_id)
                {
                    src_controller = Some(item.controller);
                }
            }
            let cidx = match src_controller {
                Some(c) => c as usize,
                None => state.active_player as usize,
            };
            let oidx = 1 - cidx;
            let limit = *max_n as usize;
            // Collect first min(limit, total) creature ids: controller
            // first, then opponent.
            let mut picked_ids: Vec<(usize, u32)> = Vec::with_capacity(limit);
            for &pidx in &[cidx, oidx] {
                if picked_ids.len() >= limit {
                    break;
                }
                let bf = &state.players[pidx].battlefield;
                let registry = &state.registry;
                for obj in bf.iter() {
                    if picked_ids.len() >= limit {
                        break;
                    }
                    let Some(printing) = registry.printings.get(obj.printing_id as usize)
                    else {
                        continue;
                    };
                    if printing.card_types.iter().any(|t| t == "Creature") {
                        picked_ids.push((pidx, obj.id));
                    }
                }
            }
            if picked_ids.is_empty() {
                return Ok(());
            }
            // Apply +1 counter to each. Use Arc::make_mut once per
            // affected battlefield.
            // Group by player.
            for &pidx in &[cidx, oidx] {
                let any = picked_ids.iter().any(|(p, _)| *p == pidx);
                if !any {
                    continue;
                }
                let bf_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[pidx].battlefield);
                for obj in bf_mut.iter_mut() {
                    if picked_ids.iter().any(|(p, id)| *p == pidx && *id == obj.id) {
                        obj.counters = obj.counters.saturating_add(1);
                    }
                }
            }
        }
        // Round-28 charge-counters-on-self (Blast-Zone-shape).
        // Single-counter-slot Rust: charge counters route to the same
        // scalar as +1/+1 (G8 multi-kind counter map is future work).
        // amount_from_x=true defers to a future X-value tracking
        // slice and currently resolves to 0 (silent no-op).
        Effect::PutChargeCountersOnSelf { amount, amount_from_x } => {
            if *amount < 0 {
                return Err(PyValueError::new_err(format!(
                    "PutChargeCountersOnSelf amount must be non-negative, got {amount}"
                )));
            }
            let effective_amount = if *amount_from_x { 0 } else { *amount };
            if effective_amount == 0 {
                return Ok(());
            }
            // Locate source on a battlefield (Python's PutPlus also
            // restricts to battlefield, same shape).
            let mut found_player: Option<usize> = None;
            for (pidx, player) in state.players.iter().enumerate() {
                if player.battlefield.iter().any(|o| o.id == source_obj_id) {
                    found_player = Some(pidx);
                    break;
                }
            }
            let Some(pidx) = found_player else {
                return Ok(()); // source not on battlefield → silent no-op
            };
            let bf_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[pidx].battlefield);
            for obj in bf_mut.iter_mut() {
                if obj.id == source_obj_id {
                    obj.counters = obj.counters.saturating_add(effective_amount);
                    break;
                }
            }
        }
        // Round-28 token-copy. Pick first creature on source-
        // controller's bf (deterministic first-slice target); allocate
        // a new obj_id (max+1 across all zones); push a new GameObject
        // with the same printing_id onto controller's bf. Token ETBs
        // summoning-sick.
        Effect::CreateTokenCopyOfTargetCreatureYouControl => {
            // Locate source controller.
            let mut src_controller: Option<u8> = None;
            'outer: for player in &state.players {
                for zone in [
                    &player.hand,
                    &player.library,
                    &player.battlefield,
                    &player.graveyard,
                    &player.exile,
                ] {
                    if let Some(obj) = zone.iter().find(|o| o.id == source_obj_id) {
                        src_controller = Some(obj.controller);
                        break 'outer;
                    }
                }
            }
            if src_controller.is_none() {
                if let Some(item) = state
                    .stack
                    .iter()
                    .find(|i| i.source_obj_id == source_obj_id)
                {
                    src_controller = Some(item.controller);
                }
            }
            let cidx = match src_controller {
                Some(c) => c as usize,
                None => state.active_player as usize,
            };
            // Pick first creature on controller's bf.
            let target_printing_id: Option<u32> = {
                let bf = &state.players[cidx].battlefield;
                let registry = &state.registry;
                bf.iter().find_map(|obj| {
                    let printing = registry.printings.get(obj.printing_id as usize)?;
                    if printing.card_types.iter().any(|t| t == "Creature") {
                        Some(obj.printing_id)
                    } else {
                        None
                    }
                })
            };
            let Some(printing_id) = target_printing_id else {
                return Ok(()); // no eligible target
            };
            // Allocate new id: max across every object on both players.
            let mut max_id: u32 = 0;
            for player in &state.players {
                for zone in [
                    &player.hand,
                    &player.library,
                    &player.battlefield,
                    &player.graveyard,
                    &player.exile,
                ] {
                    for obj in zone.iter() {
                        if obj.id > max_id {
                            max_id = obj.id;
                        }
                    }
                }
            }
            let new_id = max_id + 1;
            let new_obj = GameObject {
                id: new_id,
                printing_id,
                controller: cidx as u8,
                zone: ZONE_BATTLEFIELD,
                tapped: false,
                summoning_sick: true,
                damage: 0,
                counters: 0,
                attached_to: None,
                exiled_with_source: None,
                ueot_modifiers: Vec::new(),
            };
            Arc::make_mut(&mut state.players[cidx].battlefield).push(new_obj);
        }
        // Round-28 "may sac for inner effect". First-slice
        // deterministic-yes: if controller controls an artifact,
        // sacrifice the first one + recursively apply inner. No
        // artifact = full no-op (no inner either).
        Effect::OptionalSacArtifactForEffect { inner_effect } => {
            // Locate source controller.
            let mut src_controller: Option<u8> = None;
            'outer: for player in &state.players {
                for zone in [
                    &player.hand,
                    &player.library,
                    &player.battlefield,
                    &player.graveyard,
                    &player.exile,
                ] {
                    if let Some(obj) = zone.iter().find(|o| o.id == source_obj_id) {
                        src_controller = Some(obj.controller);
                        break 'outer;
                    }
                }
            }
            if src_controller.is_none() {
                if let Some(item) = state
                    .stack
                    .iter()
                    .find(|i| i.source_obj_id == source_obj_id)
                {
                    src_controller = Some(item.controller);
                }
            }
            let cidx = match src_controller {
                Some(c) => c as usize,
                None => state.active_player as usize,
            };
            // Pick first artifact on controller's bf.
            let artifact_id: Option<u32> = {
                let bf = &state.players[cidx].battlefield;
                let registry = &state.registry;
                bf.iter().find_map(|obj| {
                    let printing = registry.printings.get(obj.printing_id as usize)?;
                    if printing.card_types.iter().any(|t| t == "Artifact") {
                        Some(obj.id)
                    } else {
                        None
                    }
                })
            };
            let Some(artifact_id) = artifact_id else {
                return Ok(()); // no artifact → no-op
            };
            // Sacrifice: remove from bf, push to graveyard with CR 400.7 reset.
            let bf_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[cidx].battlefield);
            let pos = bf_mut
                .iter()
                .position(|o| o.id == artifact_id)
                .expect("artifact_id was just found in bf but not on re-scan");
            let mut obj = bf_mut.remove(pos);
            obj.zone = ZONE_GRAVEYARD;
            obj.tapped = false;
            obj.summoning_sick = true; // r28 CE1 universal default
            obj.damage = 0;
            obj.counters = 0;
            obj.attached_to = None;
            obj.exiled_with_source = None;
            Arc::make_mut(&mut state.players[cidx].graveyard).push(obj);
            // Apply inner effect.
            apply_effect(state, inner_effect.as_ref(), source_obj_id)?;
        }
        // Round-28 "owner puts target artifact-or-creature on top or
        // bottom of their library." First-slice deterministic-BOTTOM:
        // Python prompts the owner's agent for top vs bottom; Rust
        // has no decision callback substrate yet so we always pick
        // bottom (= lib[0] per Rust convention; lib[len-1] is top).
        //
        // Target selection mirrors TapTargetArtifactOrCreature: first
        // defender (= 1 - active_player) permanent whose
        // card_types contains "Artifact" OR "Creature". No eligible
        // target = silent fizzle.
        //
        // Owner = target's controller (Rust doesn't track an
        // owner-vs-controller distinction; first-slice synthetic
        // states never split the two, so controller == owner).
        //
        // CR 400.7 zone-change reset: tapped, summoning_sick (true
        // per r28 CE1 universal default), damage, counters all reset.
        // attached_to also reset to None on zone change.
        Effect::OwnerPutsTargetArtifactOrCreatureOnTopOrBottomOfLibrary => {
            let _ = source_obj_id;
            let defender = (1 - state.active_player) as usize;
            let target_id: Option<u32> = {
                let bf = &state.players[defender].battlefield;
                let registry = &state.registry;
                bf.iter().find_map(|obj| {
                    let printing = registry.lookup(obj.printing_id)?;
                    if printing
                        .card_types
                        .iter()
                        .any(|t| t == "Artifact" || t == "Creature")
                    {
                        Some(obj.id)
                    } else {
                        None
                    }
                })
            };
            let Some(target_id) = target_id else {
                return Ok(()); // fizzle
            };
            // Capture owner (= controller) before mutating zones.
            let owner_idx: usize = {
                let bf = &state.players[defender].battlefield;
                let obj = bf
                    .iter()
                    .find(|o| o.id == target_id)
                    .expect("target_id was just found in bf but missing on re-scan");
                obj.controller as usize
            };
            // Remove from battlefield, reset per CR 400.7, insert at
            // owner's lib[0] (= bottom of library).
            let bf_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[defender].battlefield);
            let pos = bf_mut
                .iter()
                .position(|o| o.id == target_id)
                .expect("target_id was just found in bf but missing on re-scan");
            let mut obj = bf_mut.remove(pos);
            obj.zone = ZONE_LIBRARY;
            obj.tapped = false;
            obj.summoning_sick = true; // r28 CE1 universal-true default
            obj.damage = 0;
            obj.counters = 0;
            obj.attached_to = None;
            obj.exiled_with_source = None;
            let lib_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[owner_idx].library);
            lib_mut.insert(0, obj); // lib[0] = bottom (Rust convention)
        }
        // Round-28 EoE Equipment-ETB attach. Locate the source on
        // its controller's battlefield (Equipment ETB resolution
        // happens after the Equipment has entered the bf — CR
        // 603.6a), pick the first OTHER creature on the same bf
        // (mirrors PumpTargetCreatureUntilEOT's deterministic
        // first-slice target), and stamp
        // `source.attached_to = Some(target_id)`. Silent fizzle when
        // the source isn't on a bf (e.g. dispatched through a wrong
        // resolution path) or no eligible target exists.
        Effect::AttachToTargetCreatureYouControl => {
            // Locate source on a battlefield + capture its
            // controller. The source must be on a battlefield for
            // attach to make sense — CR 303.4 / 301.5: attach
            // relationship is a battlefield-only property.
            let mut src_loc: Option<(usize, u32)> = None; // (player_idx, source_id)
            for (pidx, player) in state.players.iter().enumerate() {
                if player.battlefield.iter().any(|o| o.id == source_obj_id) {
                    src_loc = Some((pidx, source_obj_id));
                    break;
                }
            }
            let Some((cidx, src_id)) = src_loc else {
                return Ok(()); // source not on bf → silent fizzle
            };
            // Pick the first creature on source-controller's bf
            // that ISN'T the source itself (an Equipment can't
            // attach to itself). Creature-ness gates on
            // `card_types contains "Creature"` — the canonical
            // creature-detection pattern mirroring
            // PumpTargetCreatureUntilEOT / OptionalSacArtifactForEffect.
            let target_id: Option<u32> = {
                let bf = &state.players[cidx].battlefield;
                let registry = &state.registry;
                bf.iter().find_map(|obj| {
                    if obj.id == src_id {
                        return None; // can't attach to self
                    }
                    let printing = registry.printings.get(obj.printing_id as usize)?;
                    if printing.card_types.iter().any(|t| t == "Creature") {
                        Some(obj.id)
                    } else {
                        None
                    }
                })
            };
            let Some(target_id) = target_id else {
                return Ok(()); // no eligible creature → silent fizzle
            };
            let bf_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[cidx].battlefield);
            for obj in bf_mut.iter_mut() {
                if obj.id == src_id {
                    obj.attached_to = Some(target_id);
                    break;
                }
            }
        }
        // Round-29 Equip activated-ability resolution (CR 702.6).
        // Identical mutation to AttachToTargetCreatureYouControl —
        // re-stamps `source.attached_to` to the first creature on
        // the controller's bf that isn't the source itself. The
        // distinct variant exists for logging/diagnostics parity
        // with Python's EquipToTargetCreatureYouControl, which
        // overrides only `describe`. CR 702.6c: equip can re-target
        // an Equipment that's already attached — stamping over an
        // existing `attached_to` is the expected behavior.
        Effect::EquipToTargetCreatureYouControl => {
            // Locate source on a battlefield + capture its controller.
            let mut src_loc: Option<(usize, u32)> = None;
            for (pidx, player) in state.players.iter().enumerate() {
                if player.battlefield.iter().any(|o| o.id == source_obj_id) {
                    src_loc = Some((pidx, source_obj_id));
                    break;
                }
            }
            let Some((cidx, src_id)) = src_loc else {
                return Ok(()); // source not on bf → silent fizzle
            };
            // Pick the first creature on source-controller's bf
            // that ISN'T the source itself. Mirrors the Attach
            // variant's deterministic first-slice choice.
            let target_id: Option<u32> = {
                let bf = &state.players[cidx].battlefield;
                let registry = &state.registry;
                bf.iter().find_map(|obj| {
                    if obj.id == src_id {
                        return None; // can't attach to self
                    }
                    let printing = registry.printings.get(obj.printing_id as usize)?;
                    if printing.card_types.iter().any(|t| t == "Creature") {
                        Some(obj.id)
                    } else {
                        None
                    }
                })
            };
            let Some(target_id) = target_id else {
                return Ok(()); // no eligible creature → silent fizzle
            };
            let bf_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[cidx].battlefield);
            for obj in bf_mut.iter_mut() {
                if obj.id == src_id {
                    obj.attached_to = Some(target_id);
                    break;
                }
            }
        }
        // Round-28 enchanted-permanent destroy (Cryoshatter-shape).
        // Read source's `attached_to`; if Some(target_id) and target
        // exists on a battlefield, move it to its controller's
        // graveyard with CR 400.7 zone-change reset. Source not on
        // bf / attached_to is None / target untracked → silent fizzle.
        Effect::DestroyEnchantedPermanent => {
            // Locate source on a battlefield, capture its attached_to.
            let mut target_id_opt: Option<u32> = None;
            for player in &state.players {
                if let Some(src) = player.battlefield.iter().find(|o| o.id == source_obj_id) {
                    target_id_opt = src.attached_to;
                    break;
                }
            }
            let Some(target_id) = target_id_opt else {
                return Ok(()); // source not on bf or no host → fizzle
            };
            // Locate target on either battlefield + capture owner-as-controller.
            let mut target_loc: Option<usize> = None;
            for (pidx, player) in state.players.iter().enumerate() {
                if player.battlefield.iter().any(|o| o.id == target_id) {
                    target_loc = Some(pidx);
                    break;
                }
            }
            let Some(tidx) = target_loc else {
                return Ok(()); // target untracked → fizzle
            };
            // Remove from battlefield, reset per CR 400.7, push to
            // owner's graveyard.
            let bf_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[tidx].battlefield);
            let pos = bf_mut
                .iter()
                .position(|o| o.id == target_id)
                .expect("target_id was just found in bf but missing on re-scan");
            let mut obj = bf_mut.remove(pos);
            obj.zone = ZONE_GRAVEYARD;
            obj.tapped = false;
            obj.summoning_sick = true; // r28 CE1 universal-true default
            obj.damage = 0;
            obj.counters = 0;
            obj.attached_to = None;
            obj.exiled_with_source = None;
            Arc::make_mut(&mut state.players[tidx].graveyard).push(obj);
        }
        // Round-28 enchanted-permanent tap. Same `attached_to` lookup
        // as DestroyEnchantedPermanent but mutates the target's
        // `tapped` flag instead of moving zones. Idempotent on
        // already-tapped.
        Effect::TapEnchantedPermanent => {
            let mut target_id_opt: Option<u32> = None;
            for player in &state.players {
                if let Some(src) = player.battlefield.iter().find(|o| o.id == source_obj_id) {
                    target_id_opt = src.attached_to;
                    break;
                }
            }
            let Some(target_id) = target_id_opt else {
                return Ok(());
            };
            let mut target_loc: Option<usize> = None;
            for (pidx, player) in state.players.iter().enumerate() {
                if player.battlefield.iter().any(|o| o.id == target_id) {
                    target_loc = Some(pidx);
                    break;
                }
            }
            let Some(tidx) = target_loc else {
                return Ok(());
            };
            let bf_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[tidx].battlefield);
            for obj in bf_mut.iter_mut() {
                if obj.id == target_id {
                    obj.tapped = true;
                    break;
                }
            }
        }
        // Round-28 "until source leaves" exile. Pick defender's first
        // creature, stamp `exiled_with_source = Some(source_id)`,
        // move to exile. CR 400.7 zone-change reset for all other
        // per-object state. The link enables manual return via
        // `return_paired_exiles_for(source_id)`.
        Effect::ExileTargetCreatureUntilSourceLeaves => {
            let defender = (1 - state.active_player) as usize;
            let target_id: Option<u32> = {
                let bf = &state.players[defender].battlefield;
                let registry = &state.registry;
                bf.iter().find_map(|obj| {
                    let printing = registry.lookup(obj.printing_id)?;
                    if printing.card_types.iter().any(|t| t == "Creature") {
                        Some(obj.id)
                    } else {
                        None
                    }
                })
            };
            let Some(target_id) = target_id else {
                return Ok(()); // fizzle — no eligible creature
            };
            // Capture target's owner (= controller) before mutation.
            let owner_idx: usize = {
                let obj = state.players[defender]
                    .battlefield
                    .iter()
                    .find(|o| o.id == target_id)
                    .expect("target_id was just found in bf");
                obj.controller as usize
            };
            // Remove from defender's bf, stamp link, move to owner's
            // exile zone with CR 400.7 reset (preserving the link).
            let bf_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[defender].battlefield);
            let pos = bf_mut
                .iter()
                .position(|o| o.id == target_id)
                .expect("target_id was just found in bf but missing on re-scan");
            let mut obj = bf_mut.remove(pos);
            obj.zone = ZONE_EXILE;
            obj.tapped = false;
            obj.summoning_sick = true; // r28 CE1 universal-true default
            obj.damage = 0;
            obj.counters = 0;
            obj.attached_to = None;
            obj.exiled_with_source = Some(source_obj_id);
            Arc::make_mut(&mut state.players[owner_idx].exile).push(obj);
        }
        // Round-28 broader-filter "until leaves" exile. Same shape
        // as ExileTargetCreatureUntilSourceLeaves but filters on
        // "not a Land" rather than "is a Creature" — so artifacts,
        // enchantments, planeswalkers, and creatures are all
        // eligible. Defender = 1 - active_player.
        Effect::ExileOpponentsNonlandPermanentUntilLeaves => {
            let defender = (1 - state.active_player) as usize;
            let target_id: Option<u32> = {
                let bf = &state.players[defender].battlefield;
                let registry = &state.registry;
                bf.iter().find_map(|obj| {
                    let printing = registry.lookup(obj.printing_id)?;
                    let is_land = printing.card_types.iter().any(|t| t == "Land");
                    if !is_land {
                        Some(obj.id)
                    } else {
                        None
                    }
                })
            };
            let Some(target_id) = target_id else {
                return Ok(()); // fizzle — no eligible permanent
            };
            let owner_idx: usize = {
                let obj = state.players[defender]
                    .battlefield
                    .iter()
                    .find(|o| o.id == target_id)
                    .expect("target_id was just found in bf");
                obj.controller as usize
            };
            let bf_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[defender].battlefield);
            let pos = bf_mut
                .iter()
                .position(|o| o.id == target_id)
                .expect("target_id was just found in bf but missing on re-scan");
            let mut obj = bf_mut.remove(pos);
            obj.zone = ZONE_EXILE;
            obj.tapped = false;
            obj.summoning_sick = true; // r28 CE1 universal-true default
            obj.damage = 0;
            obj.counters = 0;
            obj.attached_to = None;
            obj.exiled_with_source = Some(source_obj_id);
            Arc::make_mut(&mut state.players[owner_idx].exile).push(obj);
        }
        // Round-28 may-do decision wrapper. "You may [inner_effect]."
        // Pushes a PendingDecision::MayDoChoice onto the queue and
        // short-circuits. The controller drains via
        // `submit_may_do_decision(yes)` (manual) or
        // `auto_resolve_pending_decisions("default" | "may_do_yes" |
        // "may_do_no")` (deterministic). On "yes" the inner effect is
        // applied with the same `source_obj_id` so identity-coupled
        // riders ("if you do, draw a card") retain the resolving
        // spell's identity. The `_prompt` field rides along on the
        // PendingDecision dict snapshot for agent introspection but
        // isn't used here.
        //
        // Controller convention: `state.active_player` — first-slice
        // shape consistent with Surveil / DrawCards. Real MTG plumbs
        // the spell controller through `StackItem.controller`;
        // deferred.
        Effect::MayDo { inner_effect, prompt: _prompt } => {
            let controller = state.active_player;
            state.pending_decisions.push(PendingDecision::MayDoChoice {
                source_obj_id,
                controller,
                inner_effect: inner_effect.clone(),
            });
        }
        // Round-28 "look at top N, put one in hand, rest to graveyard"
        // — Commune-with-Evil family. Same pop-and-package shape as
        // Surveil but routes to hand+graveyard instead of library-top
        // +graveyard, and asks the controller to pick ONE rather than
        // partitioning the whole set.
        //
        // Controller convention: `state.active_player` — same first-
        // slice shape as Surveil / DrawCards.
        //
        // Empty / clamp behavior: `n=0` or library_len<n emits a
        // PendingDecision with a (possibly empty) cards Vec. The
        // submit dispatcher and auto-resolve handle an empty Vec as
        // an O(1) no-op. Mirrors Python's `if not examined: return`
        // short-circuit while preserving the substrate invariant
        // (one PendingDecision per Effect arm).
        Effect::LookTopNPutOneInHandRestToGraveyard { n } => {
            if *n < 0 {
                return Err(PyValueError::new_err(format!(
                    "LookTopNPutOneInHandRestToGraveyard: n must be non-negative, got {n}"
                )));
            }
            let controller = state.active_player;
            let pidx = controller as usize;
            let lib_len = state.players[pidx].library.len();
            let count = (*n as usize).min(lib_len);
            let lib_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[pidx].library);
            let mut cards: Vec<GameObject> = Vec::with_capacity(count);
            for _ in 0..count {
                let popped = lib_mut.pop().expect(
                    "library length checked above; pop cannot fail",
                );
                cards.push(popped);
            }
            state.pending_decisions.push(
                PendingDecision::PickCardFromExaminedChoice {
                    source_obj_id,
                    controller,
                    cards,
                },
            );
        }
        // Round-28 ModalChooseOne first-slice. Pushes a
        // ChooseModeChoice carrying every mode's Effect on the heap
        // and short-circuits. Controller drains via
        // submit_choose_mode_decision(chosen_idx) (manual) or
        // auto-resolve "default" / "choose_mode_0" (picks modes[0]).
        //
        // Controller convention: state.active_player (first-slice
        // shape consistent with Surveil / MayDo / LookTopN). Modes
        // are cloned so the registry's printing keeps its original
        // Vec and the PendingDecision owns its copy.
        //
        // Empty-modes case is rejected at parse time so the resolve
        // arm always has at least one mode to fall through to.
        Effect::ChooseOneMode { modes } => {
            let controller = state.active_player;
            state.pending_decisions.push(
                PendingDecision::ChooseModeChoice {
                    source_obj_id,
                    controller,
                    modes: modes.clone(),
                },
            );
        }
        // Round-28 IfYouDo first-slice: push an IfYouDoChoice
        // carrying both nested Effects on the heap. Controller drains
        // via submit_if_you_do_decision(yes) (manual) or auto-resolve
        // "default" / "if_you_do_yes" (apply both) / "if_you_do_no"
        // (skip both).
        //
        // Controller convention: state.active_player. Both nested
        // effects cloned so the registry's printing keeps its
        // originals and the PendingDecision owns its copies.
        Effect::IfYouDo { do_action, then_action } => {
            let controller = state.active_player;
            state.pending_decisions.push(PendingDecision::IfYouDoChoice {
                source_obj_id,
                controller,
                do_action: do_action.clone(),
                then_action: then_action.clone(),
            });
        }
        // Round-28 EachOpponentMillsCards (3+ EoE cards). Mirrors the
        // round-24 EachOpponentDiscards / EachOpponentLosesLife
        // source-finder shape: 5-zone walk + stack scan to recover
        // source's controller, then mill the (single 2-player)
        // opponent's library `count` cards. Empty library stops the
        // inner loop silently — CR 704.5b applies to drawing, not
        // milling.
        // Round-28 broader-filter pump (artifact OR creature). Same
        // shape as PumpTargetCreatureUntilEOT but the eligibility
        // filter is "card_types contains Artifact OR Creature"
        // rather than just "Creature". UEOT-modifier mechanism is
        // identical — modifier auto-expires at the next cleanup step
        // via the r27 CR 514.3 UEOT-clear pass.
        Effect::PumpTargetArtifactOrCreatureUntilEOT { power_bonus, toughness_bonus } => {
            if *power_bonus == 0 && *toughness_bonus == 0 {
                return Ok(());
            }
            // Source-controller resolution (mirrors PumpTargetCreatureUntilEOT).
            let mut src_controller: Option<u8> = None;
            'outer: for player in &state.players {
                for zone in [
                    &player.hand,
                    &player.library,
                    &player.battlefield,
                    &player.graveyard,
                    &player.exile,
                ] {
                    if let Some(obj) = zone.iter().find(|o| o.id == source_obj_id) {
                        src_controller = Some(obj.controller);
                        break 'outer;
                    }
                }
            }
            let Some(controller) = src_controller else {
                return Ok(()); // source untrackable → silent fizzle
            };
            let cidx = controller as usize;
            let target_id: Option<u32> = {
                let bf = &state.players[cidx].battlefield;
                let registry = &state.registry;
                bf.iter().find_map(|obj| {
                    let printing = registry.printings.get(obj.printing_id as usize)?;
                    let is_eligible = printing
                        .card_types
                        .iter()
                        .any(|t| t == "Artifact" || t == "Creature");
                    if is_eligible {
                        Some(obj.id)
                    } else {
                        None
                    }
                })
            };
            let Some(target_id) = target_id else {
                return Ok(()); // no eligible artifact/creature → silent fizzle
            };
            let zone: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[cidx].battlefield);
            for obj in zone.iter_mut() {
                if obj.id == target_id {
                    obj.ueot_modifiers.push(UeotModifier::PowerToughnessBonus {
                        power: *power_bonus,
                        toughness: *toughness_bonus,
                    });
                    break;
                }
            }
        }
        // Round-28 EachOpponentSacrificesCreature (3+ EoE cards).
        // Mirrors the round-24 EachOpponentDiscards source-finder
        // shape; on the resolution side, picks the (single 2-player)
        // opponent's first creature on battlefield and sends it to
        // their graveyard with CR 400.7 zone-change reset. No
        // eligible creature → silent fizzle.
        // Round-28 UntapTargetOtherPermanent (Nanoform-Sentinel
        // trigger family, 3+ EoE cards). Scans both players'
        // battlefields in zone-iteration order; picks the FIRST
        // tapped permanent whose id != source_obj_id and untaps it.
        // Mirrors Python's `[o for o in state.battlefield if
        // o.id != source_id and o.tapped]` filter + pick-first.
        //
        // No eligible permanent (everything untapped, or only the
        // source itself is tapped) → silent fizzle.
        // Round-28 SetBasePTUntilEOT (Genemorph-Imago family, 2+ EoE
        // cards). CR 613.4 layer 7b base-P/T override. Same target-
        // pick shape as PumpTargetCreatureUntilEOT but pushes
        // UeotModifier::SetBasePT instead of ::PowerToughnessBonus.
        // Composer reads the LAST SetBasePT modifier (last-applied
        // wins). Layer-7c additive bonuses stack on top.
        Effect::SetBasePTUntilEOT { power, toughness } => {
            // Source-controller resolution (5-zone walk).
            let mut src_controller: Option<u8> = None;
            'outer_sbp: for player in &state.players {
                for zone in [
                    &player.hand,
                    &player.library,
                    &player.battlefield,
                    &player.graveyard,
                    &player.exile,
                ] {
                    if let Some(obj) = zone.iter().find(|o| o.id == source_obj_id) {
                        src_controller = Some(obj.controller);
                        break 'outer_sbp;
                    }
                }
            }
            let Some(controller) = src_controller else {
                return Ok(()); // source untrackable → silent fizzle
            };
            let cidx = controller as usize;
            // Pick first creature on controller's bf.
            let target_id: Option<u32> = {
                let bf = &state.players[cidx].battlefield;
                let registry = &state.registry;
                bf.iter().find_map(|obj| {
                    let printing = registry.printings.get(obj.printing_id as usize)?;
                    if printing.card_types.iter().any(|t| t == "Creature") {
                        Some(obj.id)
                    } else {
                        None
                    }
                })
            };
            let Some(target_id) = target_id else {
                return Ok(()); // no eligible creature → silent fizzle
            };
            let zone: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[cidx].battlefield);
            for obj in zone.iter_mut() {
                if obj.id == target_id {
                    obj.ueot_modifiers.push(UeotModifier::SetBasePT {
                        power: *power,
                        toughness: *toughness,
                    });
                    break;
                }
            }
        }
        // Round-28 ManifestDread first-slice. CR 701.55 — pop top
        // min(2, library_len) cards into a ManifestDreadChoice and
        // short-circuit. Substrate-aligned with LookTopN: same pop-
        // and-package shape, but the submit dispatcher routes the
        // picked card to bf (with ETB-reset) instead of hand.
        //
        // Controller convention: state.active_player (first-slice
        // shape consistent with Surveil / LookTopN / MayDo /
        // ChooseOneMode / IfYouDo).
        //
        // First-slice: count = 1 ONLY. count > 1 raises with a clear
        // "deferred" message so a typo doesn't silently no-op. Python's
        // multi-iter form (Slimy Aquarium, Weight Room riders) and X-
        // times form (Valgavoth's Onslaught) are documented in
        // SEARCH_LIMITATIONS.md as deferred.
        //
        // Empty / 1-card library partials: emit a PendingDecision
        // with a (possibly empty / 1-card) cards Vec. Auto-resolve
        // and submit handle both — empty drains as O(1) no-op,
        // 1-card manifests the lone card.
        Effect::ManifestDread { count } => {
            if *count != 1 {
                return Err(PyValueError::new_err(format!(
                    "ManifestDread: first-slice supports count = 1 only \
                     (got count = {count}); count > 1 (multi-iter) and \
                     count = 0 (no-op) deferred — see \
                     docs/SEARCH_LIMITATIONS.md"
                )));
            }
            let controller = state.active_player;
            let pidx = controller as usize;
            let lib_len = state.players[pidx].library.len();
            let pop_count = lib_len.min(2);
            let lib_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[pidx].library);
            let mut cards: Vec<GameObject> = Vec::with_capacity(pop_count);
            for _ in 0..pop_count {
                let popped = lib_mut.pop().expect(
                    "library length checked above; pop cannot fail",
                );
                cards.push(popped);
            }
            state.pending_decisions.push(
                PendingDecision::ManifestDreadChoice {
                    source_obj_id,
                    controller,
                    cards,
                },
            );
        }
        // Round-28 LookAtTopNRevealOrCounter — Living-Phone / Pulsar-
        // Squadron-Ace family (freq 2 in EoE pool). Pop top
        // min(n, library_len) cards into a LookAtTopNRevealOrCounterChoice
        // and short-circuit. Submit dispatcher routes reveal-yes →
        // (chosen to hand, rest to library bottom); reveal-no → (all
        // to library bottom + optional counter-on-miss rider).
        //
        // Controller convention: state.active_player (first-slice
        // shape consistent with Surveil / LookTopN / MayDo / ChooseOneMode
        // / IfYouDo / ManifestDread).
        //
        // Empty / partial library: emit a PendingDecision with a
        // (possibly empty / partial) cards Vec. Auto-resolve and submit
        // handle both — empty drains as "no reveal possible" so the
        // counter-on-miss rider fires (matches Python: empty examined
        // → no reveal happened → counter rider fires).
        Effect::LookAtTopNRevealOrCounter {
            n,
            filter_name,
            max_power,
            counter_on_miss,
        } => {
            if *n < 0 {
                return Err(PyValueError::new_err(format!(
                    "LookAtTopNRevealOrCounter: n must be non-negative, got {n}"
                )));
            }
            let controller = state.active_player;
            let pidx = controller as usize;
            let lib_len = state.players[pidx].library.len();
            let pop_count = (*n as usize).min(lib_len);
            let lib_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[pidx].library);
            let mut cards: Vec<GameObject> = Vec::with_capacity(pop_count);
            for _ in 0..pop_count {
                let popped = lib_mut.pop().expect(
                    "library length checked above; pop cannot fail",
                );
                cards.push(popped);
            }
            state.pending_decisions.push(
                PendingDecision::LookAtTopNRevealOrCounterChoice {
                    source_obj_id,
                    controller,
                    cards,
                    filter_name: filter_name.clone(),
                    max_power: *max_power,
                    counter_on_miss: *counter_on_miss,
                },
            );
        }
        // Round-28 mass reanimation. Mirrors Python's
        // ReturnAllCreaturesFromYourGraveyardToBattlefield (Awakening-
        // Hall family, 2+ EoE cards). Iterate source-controller's
        // graveyard in stored order (oldest first — Vec front); move
        // every creature to the controller's bf with the standard ETB
        // reset (summoning_sick=true, tapped=false, etc.).
        Effect::ReturnAllCreaturesFromYourGraveyardToBattlefield => {
            let _ = source_obj_id; // controller-targeted, not source-relative
            let controller_idx = state.active_player as usize;
            // Collect creature ids first to avoid registry-vs-graveyard
            // borrow conflicts.
            let creature_ids: Vec<u32> = state.players[controller_idx]
                .graveyard
                .iter()
                .filter_map(|obj| {
                    let printing = state.registry.lookup(obj.printing_id)?;
                    if printing.card_types.iter().any(|t| t == "Creature") {
                        Some(obj.id)
                    } else {
                        None
                    }
                })
                .collect();
            if creature_ids.is_empty() {
                return Ok(()); // empty / no-creature graveyard: silent no-op
            }
            // Drain matching creatures from graveyard; collect for bf.
            let graveyard_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[controller_idx].graveyard);
            let mut moved: Vec<GameObject> = Vec::with_capacity(creature_ids.len());
            graveyard_mut.retain(|o| {
                if creature_ids.contains(&o.id) {
                    let mut obj = o.clone();
                    obj.zone = ZONE_BATTLEFIELD;
                    obj.tapped = false;
                    obj.summoning_sick = true;
                    obj.damage = 0;
                    obj.counters = 0;
                    obj.attached_to = None;
                    obj.exiled_with_source = None;
                    moved.push(obj);
                    false
                } else {
                    true
                }
            });
            let bf_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[controller_idx].battlefield);
            for obj in moved {
                bf_mut.push(obj);
            }
        }
        // Round-28 TapAnotherTargetCreature (Starport-Security family,
        // 2+ EoE cards). Same scan shape as UntapTargetOtherPermanent
        // but filters on Creature and taps. Already-tapped target is
        // a silent no-op (matches the existing TapTarget contract).
        Effect::TapAnotherTargetCreature => {
            let mut found: Option<(usize, u32)> = None;
            'outer_tatc: for (pidx, player) in state.players.iter().enumerate() {
                for obj in player.battlefield.iter() {
                    if obj.id == source_obj_id {
                        continue;
                    }
                    let printing_idx = obj.printing_id as usize;
                    let Some(printing) = state.registry.printings.get(printing_idx) else {
                        continue;
                    };
                    if !printing.card_types.iter().any(|t| t == "Creature") {
                        continue;
                    }
                    found = Some((pidx, obj.id));
                    break 'outer_tatc;
                }
            }
            if let Some((pidx, target_id)) = found {
                let zone: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[pidx].battlefield);
                for obj in zone.iter_mut() {
                    if obj.id == target_id {
                        obj.tapped = true;
                        break;
                    }
                }
            }
            // else: no eligible creature → silent fizzle.
        }
        Effect::UntapTargetOtherPermanent => {
            // Find first eligible (tapped, not source) across both
            // players' battlefields. Track (player_idx, obj_id) for
            // the mutating pass.
            let mut found: Option<(usize, u32)> = None;
            'outer: for (pidx, player) in state.players.iter().enumerate() {
                for obj in player.battlefield.iter() {
                    if obj.id != source_obj_id && obj.tapped {
                        found = Some((pidx, obj.id));
                        break 'outer;
                    }
                }
            }
            if let Some((pidx, target_id)) = found {
                let zone: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[pidx].battlefield);
                for obj in zone.iter_mut() {
                    if obj.id == target_id {
                        obj.tapped = false;
                        break;
                    }
                }
            }
            // else: no eligible permanent → silent fizzle.
        }
        // Round-28 GrantKeywordToTargetCreatureUntilEOT
        // (GrantUnblockable family, 3+ EoE cards; generalized to any
        // keyword). Same shape as PumpTargetCreatureUntilEOT but
        // pushes UeotModifier::GrantKeyword rather than
        // ::PowerToughnessBonus. Modifier auto-expires at the next
        // cleanup step via the r27 CR 514.3 UEOT-clear pass.
        Effect::GrantKeywordToTargetCreatureUntilEOT { keyword } => {
            // Source-controller resolution (5-zone walk).
            let mut src_controller: Option<u8> = None;
            'outer: for player in &state.players {
                for zone in [
                    &player.hand,
                    &player.library,
                    &player.battlefield,
                    &player.graveyard,
                    &player.exile,
                ] {
                    if let Some(obj) = zone.iter().find(|o| o.id == source_obj_id) {
                        src_controller = Some(obj.controller);
                        break 'outer;
                    }
                }
            }
            let Some(controller) = src_controller else {
                return Ok(()); // source untrackable → silent fizzle
            };
            let cidx = controller as usize;
            // Pick first creature on controller's bf.
            let target_id: Option<u32> = {
                let bf = &state.players[cidx].battlefield;
                let registry = &state.registry;
                bf.iter().find_map(|obj| {
                    let printing = registry.printings.get(obj.printing_id as usize)?;
                    if printing.card_types.iter().any(|t| t == "Creature") {
                        Some(obj.id)
                    } else {
                        None
                    }
                })
            };
            let Some(target_id) = target_id else {
                return Ok(()); // no eligible creature → silent fizzle
            };
            let zone: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[cidx].battlefield);
            for obj in zone.iter_mut() {
                if obj.id == target_id {
                    obj.ueot_modifiers.push(UeotModifier::GrantKeyword {
                        keyword: keyword.clone(),
                    });
                    break;
                }
            }
        }
        Effect::EachOpponentSacrificesCreature => {
            // Source-controller resolution (mirrors EachOpponentDiscards).
            let mut source_controller: Option<u8> = None;
            'outer: for player in state.players.iter() {
                for zone in [
                    &player.hand,
                    &player.library,
                    &player.battlefield,
                    &player.graveyard,
                    &player.exile,
                ] {
                    for obj in zone.iter() {
                        if obj.id == source_obj_id {
                            source_controller = Some(obj.controller);
                            break 'outer;
                        }
                    }
                }
            }
            if source_controller.is_none() {
                if let Some(item) = state
                    .stack
                    .iter()
                    .find(|i| i.source_obj_id == source_obj_id)
                {
                    source_controller = Some(item.controller);
                }
            }
            let Some(controller) = source_controller else {
                return Ok(()); // source not found: silent fizzle
            };
            let opponent_idx = (1 - controller) as usize;
            // Pick first creature on opponent's bf.
            let target_id: Option<u32> = {
                let bf = &state.players[opponent_idx].battlefield;
                let registry = &state.registry;
                bf.iter().find_map(|obj| {
                    let printing = registry.printings.get(obj.printing_id as usize)?;
                    if printing.card_types.iter().any(|t| t == "Creature") {
                        Some(obj.id)
                    } else {
                        None
                    }
                })
            };
            let Some(target_id) = target_id else {
                return Ok(()); // no eligible creature → silent fizzle
            };
            // Pop from opponent's bf, route to opponent's graveyard
            // with CR 400.7 zone-change reset.
            let bf_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut state.players[opponent_idx].battlefield);
            let pos = bf_mut
                .iter()
                .position(|o| o.id == target_id)
                .expect("target_id found above");
            let mut obj = bf_mut.remove(pos);
            obj.zone = ZONE_GRAVEYARD;
            obj.tapped = false;
            obj.summoning_sick = false;
            obj.damage = 0;
            obj.counters = 0;
            obj.attached_to = None;
            obj.exiled_with_source = None;
            Arc::make_mut(&mut state.players[opponent_idx].graveyard).push(obj);
        }
        Effect::EachOpponentMillsCards { count } => {
            if *count < 0 {
                return Err(PyValueError::new_err(format!(
                    "EachOpponentMillsCards count must be non-negative, got {count}"
                )));
            }
            if *count == 0 {
                return Ok(());
            }
            // Source-controller resolution (mirrors EachOpponentDiscards).
            let mut source_controller: Option<u8> = None;
            'outer: for player in state.players.iter() {
                for zone in [
                    &player.hand,
                    &player.library,
                    &player.battlefield,
                    &player.graveyard,
                    &player.exile,
                ] {
                    for obj in zone.iter() {
                        if obj.id == source_obj_id {
                            source_controller = Some(obj.controller);
                            break 'outer;
                        }
                    }
                }
            }
            if source_controller.is_none() {
                if let Some(item) = state
                    .stack
                    .iter()
                    .find(|i| i.source_obj_id == source_obj_id)
                {
                    source_controller = Some(item.controller);
                }
            }
            let Some(controller) = source_controller else {
                return Ok(()); // source not found: silent fizzle
            };
            // 2-player "each opponent" → "the one opponent". Mill
            // `count` cards off the opponent's library top.
            let opponent_idx = (1 - controller) as usize;
            let n = *count as usize;
            for _ in 0..n {
                let lib_mut: &mut Vec<GameObject> =
                    Arc::make_mut(&mut state.players[opponent_idx].library);
                let Some(mut obj) = lib_mut.pop() else {
                    break; // empty library: silent stop (CR parity with Effect::Mill)
                };
                obj.zone = ZONE_GRAVEYARD;
                Arc::make_mut(&mut state.players[opponent_idx].graveyard).push(obj);
            }
        }
        // Round-29 intervening-if keyed on EoE "Void" condition.
        // Mirrors Python's `ConditionalIfVoid.resolve` (combinators.py:
        // 1446): read `is_void_active(state)`; if true, apply
        // `then_effect`; else if `else_effect` is Some, apply it; else
        // no-op. Recurses via `apply_effect` with the same
        // source_obj_id so nested target-resolution / source-relative
        // lookups stay anchored to the outer spell.
        Effect::ConditionalIfVoid { then_effect, else_effect } => {
            let void_active = state.permanent_left_battlefield_this_turn
                || state.spell_warped_this_turn;
            let branch: Option<&Effect> = if void_active {
                Some(then_effect.as_ref())
            } else {
                else_effect.as_deref()
            };
            if let Some(inner) = branch {
                apply_effect(state, inner, source_obj_id)?;
            }
            // else: silent no-op (matches Python's None-branch fall-
            // through).
        }
    }
    Ok(())
}

#[pymethods]
impl GameState {
    /// Round-28 "until source leaves" — return every exiled object
    /// whose `exiled_with_source` matches `source_id` to its owner's
    /// battlefield. CR 400.7 zone-change reset on the way back
    /// (tapped, summoning_sick=true per r28 CE1, damage, counters,
    /// attached_to, exiled_with_source all cleared).
    ///
    /// Manual hook: callers (harness / future leaves-bf primitive
    /// extension) must invoke this when the source leaves the
    /// battlefield. Auto-firing on every bf-leaving zone change is a
    /// follow-up slice. Returns the count of objects returned.
    fn return_paired_exiles_for(&mut self, source_id: u32) -> i32 {
        let mut returned = 0i32;
        for pidx in 0..self.players.len() {
            // Collect ids first to avoid borrow conflicts.
            let to_return: Vec<u32> = self.players[pidx]
                .exile
                .iter()
                .filter_map(|o| {
                    if o.exiled_with_source == Some(source_id) {
                        Some(o.id)
                    } else {
                        None
                    }
                })
                .collect();
            if to_return.is_empty() {
                continue;
            }
            let exile_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut self.players[pidx].exile);
            let mut popped: Vec<GameObject> = Vec::with_capacity(to_return.len());
            exile_mut.retain(|o| {
                if to_return.contains(&o.id) {
                    let mut obj = o.clone();
                    obj.zone = ZONE_BATTLEFIELD;
                    obj.tapped = false;
                    obj.summoning_sick = true; // r28 CE1 default; also CR 302.1 for ETB
                    obj.damage = 0;
                    obj.counters = 0;
                    obj.attached_to = None;
                    obj.exiled_with_source = None;
                    popped.push(obj);
                    false
                } else {
                    true
                }
            });
            let bf_mut: &mut Vec<GameObject> =
                Arc::make_mut(&mut self.players[pidx].battlefield);
            for obj in popped {
                bf_mut.push(obj);
                returned += 1;
            }
        }
        returned
    }

    /// Resolve the top stack item. Returns the resolved item as a
    /// dict (same shape as `pop_top_of_stack`), or `None` if the
    /// stack was empty.
    ///
    /// Steps:
    /// 1. Peek top; if empty, return None.
    /// 2. Look up the source GameObject by id across all four
    ///    zones on both players.
    /// 3. Read the source printing's effects from the registry.
    /// 4. Dispatch each effect (currently only `DealDamage`).
    /// 5. Move the source per CR 608.2m: instant/sorcery to
    ///    controller's graveyard, permanents to controller's
    ///    battlefield (summoning-sick if creature). Empty
    ///    card_types leaves source in place.
    /// 6. Pop the stack item and return its dict.
    ///
    /// If the source GameObject can't be found in any zone, the
    /// item still pops — no effects fire (treated like a fizzle).
    /// This matches the "lost track of source" failure mode: the
    /// stack drains, the player observes no effect.
    fn resolve_top_of_stack<'py>(
        &mut self,
        py: Python<'py>,
    ) -> PyResult<Option<Bound<'py, PyDict>>> {
        // Peek without popping so we can read effects before
        // committing to drain.
        let top = match self.stack.last() {
            None => return Ok(None),
            Some(item) => item.clone(),
        };

        // Find the source's printing_id, then collect a snapshot of
        // its effects so we can drop the registry borrow before
        // mutating self.
        let effects: Vec<Effect> = match find_source_printing_id(self, top.source_obj_id)
        {
            Some(printing_id) => match self.registry.lookup(printing_id) {
                Some(printing) => printing.effects.clone(),
                None => Vec::new(),
            },
            None => Vec::new(),
        };

        for effect in &effects {
            apply_effect(self, effect, top.source_obj_id)?;
        }

        // CR 608.2m: post-resolve, move the spell source. Instants /
        // sorceries -> controller's graveyard; permanents (creature,
        // artifact, enchantment, planeswalker, battle) ->
        // controller's battlefield with summoning sickness for
        // creatures. Empty card_types is the synthetic-test escape
        // hatch — leave source in place. Done BEFORE the stack pop
        // so a panic in movement doesn't leave the stack drained
        // with no movement applied (transactional shape).
        let post_resolve_zone = move_source_post_resolve(self, top.source_obj_id);

        // Round-9: fire ETB-triggered effects when (and only when)
        // the source landed on the battlefield. Real MTG: ETB
        // triggers go onto the stack and resolve in priority order.
        // First slice applies them inline, same convention as the
        // spell-effects path. Snapshot etb_effects via the same
        // borrow-then-drop pattern we use for spell effects so we
        // can mutate state while iterating.
        if post_resolve_zone == Some(ZONE_BATTLEFIELD) {
            let etb_effects: Vec<Effect> =
                match find_source_printing_id(self, top.source_obj_id) {
                    Some(printing_id) => match self.registry.lookup(printing_id) {
                        Some(printing) => printing.etb_effects.clone(),
                        None => Vec::new(),
                    },
                    None => Vec::new(),
                };
            for effect in &etb_effects {
                apply_effect(self, effect, top.source_obj_id)?;
            }
        }

        // Now drain the popped item and return its dict.
        let popped = self
            .stack
            .pop()
            .expect("peeked top but pop returned None — stack invariant broken");
        // Auto-resolve any pending decisions (Round-27 G20 closure).
        // Pre-r27 behavior: Surveil etc. resolved with deterministic
        // "keep all on top". The decision-callback substrate now
        // packages those into PendingDecisions during apply_effect;
        // stack resolution defaults to the same "keep all on top"
        // strategy so existing baseline tests (test_library.py r23
        // surveil, etc.) are bit-equal to the pre-r27 path.
        // Callers that want to observe / control the decision use
        // `resolve_top_of_stack_pause` (no auto-resolve) instead.
        auto_resolve_pending(self, "keep_all_on_top")?;
        Ok(Some(stack_item_to_dict(py, &popped)?))
    }

    /// Same as `resolve_top_of_stack` but does NOT auto-resolve any
    /// `PendingDecision`s the effect dispatch leaves on the queue.
    /// The caller is responsible for either submitting decisions
    /// (`submit_surveil_decision`) or calling
    /// `auto_resolve_pending_decisions(strategy)` afterward.
    ///
    /// For tests / harnesses that need to introspect mid-resolution
    /// state (a SurveilChoice carrying its observed cards, before
    /// the controller routes them). The CR 608.2m post-resolve
    /// source mover still fires (the Sorcery still lands in the
    /// graveyard); the only difference is the pending decision
    /// queue remains populated.
    fn resolve_top_of_stack_pause<'py>(
        &mut self,
        py: Python<'py>,
    ) -> PyResult<Option<Bound<'py, PyDict>>> {
        let top = match self.stack.last() {
            None => return Ok(None),
            Some(item) => item.clone(),
        };
        let effects: Vec<Effect> = match find_source_printing_id(self, top.source_obj_id)
        {
            Some(printing_id) => match self.registry.lookup(printing_id) {
                Some(printing) => printing.effects.clone(),
                None => Vec::new(),
            },
            None => Vec::new(),
        };
        for effect in &effects {
            apply_effect(self, effect, top.source_obj_id)?;
        }
        let post_resolve_zone = move_source_post_resolve(self, top.source_obj_id);
        if post_resolve_zone == Some(ZONE_BATTLEFIELD) {
            let etb_effects: Vec<Effect> =
                match find_source_printing_id(self, top.source_obj_id) {
                    Some(printing_id) => match self.registry.lookup(printing_id) {
                        Some(printing) => printing.etb_effects.clone(),
                        None => Vec::new(),
                    },
                    None => Vec::new(),
                };
            for effect in &etb_effects {
                apply_effect(self, effect, top.source_obj_id)?;
            }
        }
        let popped = self
            .stack
            .pop()
            .expect("peeked top but pop returned None — stack invariant broken");
        Ok(Some(stack_item_to_dict(py, &popped)?))
    }

    /// **Test-fixture surface.** Register a printing dict into the
    /// in-place registry, construct a fresh GameObject pointing at
    /// it on `target_zone` for player `controller`, and return the
    /// new object's id.
    ///
    /// Used by `tests_rust/test_resolve.py` to set up cross-slice
    /// composition tests (a Bombard-shaped DealDamage source on the
    /// battlefield) without needing a separate `Registry` pyclass
    /// or hand-rolling synthetic states for every test. The id is
    /// `1 + max(existing obj.id across all zones)` so it never
    /// collides with synthetic-state ids.
    ///
    /// Lives in this slice (not `state.rs`) per the per-slice
    /// file-isolation rule. A follow-up consolidation slice can
    /// move it once the parallel-slice constraint relaxes.
    fn register_and_inject_object(
        &mut self,
        printing_dict: &Bound<'_, PyDict>,
        controller: u8,
        target_zone: u8,
    ) -> PyResult<u32> {
        if (controller as usize) >= 2 {
            return Err(PyIndexError::new_err(format!(
                "controller {controller} out of range (must be 0 or 1)"
            )));
        }

        // Append to the registry. Arc::make_mut clones RegistryData
        // on first write only when other clones observe it — same
        // CoW shape as zones.
        let printing = parse_printing(printing_dict)?;
        let reg: &mut RegistryData = Arc::make_mut(&mut self.registry);
        let printing_id = reg.printings.len() as u32;
        reg.printings.push(printing);

        // Pick a fresh obj_id: 1 + max across all zones on both
        // players. Synthetic-state ids start at 0 and pack densely;
        // this guarantees no collision regardless of seed shape.
        let mut next_id: u32 = 0;
        for player in &self.players {
            for zone in [
                &player.hand,
                &player.library,
                &player.battlefield,
                &player.graveyard,
            ] {
                for obj in zone.iter() {
                    if obj.id >= next_id {
                        next_id = obj.id + 1;
                    }
                }
            }
        }

        let obj = GameObject {
            id: next_id,
            printing_id,
            controller,
            zone: target_zone,
            tapped: false,
            summoning_sick: false,
            damage: 0,
            counters: 0,
            attached_to: None,
            exiled_with_source: None,
            ueot_modifiers: Vec::new(),
        };

        let player = &mut self.players[controller as usize];
        let dest = match target_zone {
            ZONE_HAND => &mut player.hand,
            ZONE_LIBRARY => &mut player.library,
            ZONE_BATTLEFIELD => &mut player.battlefield,
            ZONE_GRAVEYARD => &mut player.graveyard,
            other => {
                return Err(PyValueError::new_err(format!(
                    "register_and_inject_object: unsupported target_zone {other} (valid: 0-3)"
                )));
            }
        };
        Arc::make_mut(dest).push(obj);
        Ok(next_id)
    }

    // -------------------------------------------------------------
    // Round-11 exile read helpers.
    //
    // ``find_object_zone`` / ``get_damage`` / ``get_counters`` /
    // ``is_summoning_sick`` only iterate the four pre-r11 zones (hand
    // / library / battlefield / graveyard) — they don't search exile.
    // The exile-dispatch tests need a way to positively assert on an
    // exiled object's location and reset state, so we add the minimal
    // read surface here. Lives in this slice's file per per-slice
    // file-isolation; a follow-up consolidation slice can extend
    // ``find_object_zone`` (and friends) once exile has more readers.
    // -------------------------------------------------------------

    /// Per-player exile zone size, mirror of ``graveyard_sizes`` /
    /// ``battlefield_sizes``.
    #[getter]
    fn exile_sizes(&self) -> [usize; 2] {
        [self.players[0].exile.len(), self.players[1].exile.len()]
    }

    /// True iff some object with id `obj_id` is in either player's
    /// exile zone.
    fn exile_contains(&self, obj_id: u32) -> bool {
        for player in &self.players {
            if player.exile.iter().any(|o| o.id == obj_id) {
                return true;
            }
        }
        false
    }

    /// Read the `tapped` flag for an object in either player's exile.
    /// Returns `None` if no exile object with that id exists.
    fn exile_object_tapped(&self, obj_id: u32) -> Option<bool> {
        for player in &self.players {
            for obj in player.exile.iter() {
                if obj.id == obj_id {
                    return Some(obj.tapped);
                }
            }
        }
        None
    }

    /// Read the `summoning_sick` flag for an object in either
    /// player's exile.
    fn exile_object_summoning_sick(&self, obj_id: u32) -> Option<bool> {
        for player in &self.players {
            for obj in player.exile.iter() {
                if obj.id == obj_id {
                    return Some(obj.summoning_sick);
                }
            }
        }
        None
    }

    /// Read the `damage` marker for an object in either player's
    /// exile.
    fn exile_object_damage(&self, obj_id: u32) -> Option<i16> {
        for player in &self.players {
            for obj in player.exile.iter() {
                if obj.id == obj_id {
                    return Some(obj.damage);
                }
            }
        }
        None
    }

    /// Read the `counters` net value for an object in either player's
    /// exile.
    fn exile_object_counters(&self, obj_id: u32) -> Option<i32> {
        for player in &self.players {
            for obj in player.exile.iter() {
                if obj.id == obj_id {
                    return Some(obj.counters);
                }
            }
        }
        None
    }

    /// Read the `zone` field stamped on an exiled object (should be
    /// `ZONE_EXILE` after a successful ExileTarget dispatch).
    fn exile_object_zone_field(&self, obj_id: u32) -> Option<u8> {
        for player in &self.players {
            for obj in player.exile.iter() {
                if obj.id == obj_id {
                    return Some(obj.zone);
                }
            }
        }
        None
    }
}
